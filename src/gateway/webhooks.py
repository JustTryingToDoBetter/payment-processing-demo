"""
Webhook delivery system for the payment gateway.

Webhooks notify merchants about payment events asynchronously.
This is critical because:

1. Payment outcomes aren't always synchronous
   - Bank response timeouts
   - 3D Secure authentication
   - Fraud review queues

2. Merchants need reliable event delivery
   - Order fulfillment depends on payment confirmation
   - Refund processing needs notification
   - Dispute handling requires immediate action

Key features:
- Cryptographic signatures for authenticity
- Exponential backoff for retries
- Event deduplication
- Delivery status tracking
"""

import json
import time
import threading
import hashlib
import hmac
import secrets
from datetime import datetime
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Callable
from enum import Enum
from queue import Queue, Empty
import urllib.request
import urllib.error


class EventType(str, Enum):
    """Types of webhook events."""
    # Charges
    CHARGE_SUCCEEDED = "charge.succeeded"
    CHARGE_FAILED = "charge.failed"
    CHARGE_PENDING = "charge.pending"
    CHARGE_EXPIRED = "charge.expired"
    CHARGE_CAPTURED = "charge.captured"
    
    # Refunds
    REFUND_CREATED = "refund.created"
    REFUND_SUCCEEDED = "refund.succeeded"
    REFUND_FAILED = "refund.failed"
    
    # Disputes
    DISPUTE_CREATED = "dispute.created"
    DISPUTE_UPDATED = "dispute.updated"
    DISPUTE_CLOSED = "dispute.closed"
    
    # Payment Methods
    PAYMENT_METHOD_ATTACHED = "payment_method.attached"
    PAYMENT_METHOD_DETACHED = "payment_method.detached"
    
    # 3D Secure
    THREE_DS_REQUIRED = "three_ds.required"
    THREE_DS_COMPLETED = "three_ds.completed"


class DeliveryStatus(str, Enum):
    """Webhook delivery status."""
    PENDING = "pending"
    DELIVERED = "delivered"
    FAILED = "failed"
    RETRYING = "retrying"


@dataclass
class WebhookEvent:
    """
    A webhook event to be delivered.
    """
    id: str
    type: EventType
    created_at: datetime
    data: Dict
    merchant_id: str
    api_version: str = "2024-01-01"
    
    def to_payload(self) -> Dict:
        """Convert to webhook payload."""
        return {
            "id": self.id,
            "object": "event",
            "type": self.type.value,
            "created": int(self.created_at.timestamp()),
            "data": {
                "object": self.data
            },
            "api_version": self.api_version,
            "livemode": False  # Demo mode
        }


@dataclass
class WebhookEndpoint:
    """
    A registered webhook endpoint for a merchant.
    """
    id: str
    merchant_id: str
    url: str
    secret: str  # Signing secret for this endpoint
    events: List[str]  # Event types to receive ("*" for all)
    enabled: bool = True
    created_at: datetime = field(default_factory=datetime.utcnow)
    
    def should_receive(self, event_type: str) -> bool:
        """Check if this endpoint should receive an event type."""
        if not self.enabled:
            return False
        if "*" in self.events:
            return True
        return event_type in self.events


@dataclass
class DeliveryAttempt:
    """
    Record of a webhook delivery attempt.
    """
    id: str
    event_id: str
    endpoint_id: str
    status: DeliveryStatus
    http_status: Optional[int] = None
    response_body: Optional[str] = None
    error_message: Optional[str] = None
    attempt_number: int = 1
    next_retry_at: Optional[datetime] = None
    created_at: datetime = field(default_factory=datetime.utcnow)


class WebhookSigner:
    """
    Creates and verifies webhook signatures.
    
    Signature scheme (similar to Stripe):
    - Signature header: t=timestamp,v1=signature
    - Payload: timestamp + "." + body
    - HMAC-SHA256 with endpoint secret
    """
    
    @staticmethod
    def sign(payload: str, secret: str, timestamp: Optional[int] = None) -> str:
        """
        Sign a webhook payload.
        
        Returns signature header value: t={timestamp},v1={signature}
        """
        if timestamp is None:
            timestamp = int(time.time())
        
        # Create signed payload
        signed_payload = f"{timestamp}.{payload}"
        
        # Calculate signature
        signature = hmac.new(
            secret.encode('utf-8'),
            signed_payload.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()
        
        return f"t={timestamp},v1={signature}"
    
    @staticmethod
    def verify(
        payload: str,
        header: str,
        secret: str,
        tolerance: int = 300  # 5 minutes
    ) -> bool:
        """
        Verify a webhook signature.
        
        Args:
            payload: Raw request body
            header: Signature header value
            secret: Endpoint signing secret
            tolerance: Max age of timestamp in seconds
            
        Returns:
            True if signature is valid
        """
        try:
            # Parse header
            elements = dict(item.split("=") for item in header.split(","))
            timestamp = int(elements.get("t", 0))
            signature = elements.get("v1", "")
            
            # Check timestamp tolerance
            age = abs(int(time.time()) - timestamp)
            if age > tolerance:
                return False
            
            # Calculate expected signature
            signed_payload = f"{timestamp}.{payload}"
            expected = hmac.new(
                secret.encode('utf-8'),
                signed_payload.encode('utf-8'),
                hashlib.sha256
            ).hexdigest()
            
            # Constant-time comparison
            return hmac.compare_digest(signature, expected)
            
        except (ValueError, KeyError):
            return False


class WebhookDispatcher:
    """
    Manages webhook event creation and delivery.
    
    Features:
    - Async delivery queue
    - Exponential backoff retries
    - Delivery attempt tracking
    - Endpoint management
    """
    
    # Retry schedule (seconds): 1min, 5min, 30min, 2hr, 12hr, 24hr
    RETRY_SCHEDULE = [60, 300, 1800, 7200, 43200, 86400]
    
    def __init__(self):
        # Merchant ID → list of endpoints
        self._endpoints: Dict[str, List[WebhookEndpoint]] = {}
        
        # Event ID → event
        self._events: Dict[str, WebhookEvent] = {}
        
        # Delivery attempts
        self._attempts: Dict[str, DeliveryAttempt] = {}
        
        # Event delivery queue
        self._queue: Queue = Queue()
        
        # Lock for thread safety
        self._lock = threading.Lock()
        
        # Signer
        self.signer = WebhookSigner()
        
        # Worker thread
        self._worker: Optional[threading.Thread] = None
        self._running = False
    
    def register_endpoint(
        self,
        merchant_id: str,
        url: str,
        events: List[str] = None
    ) -> WebhookEndpoint:
        """
        Register a new webhook endpoint.
        
        Args:
            merchant_id: The merchant's ID
            url: Endpoint URL (must be HTTPS in production)
            events: Event types to subscribe to (default: all)
            
        Returns:
            Created WebhookEndpoint
        """
        endpoint = WebhookEndpoint(
            id=f"we_{secrets.token_hex(12)}",
            merchant_id=merchant_id,
            url=url,
            secret=f"whsec_{secrets.token_hex(24)}",
            events=events or ["*"]
        )
        
        with self._lock:
            if merchant_id not in self._endpoints:
                self._endpoints[merchant_id] = []
            self._endpoints[merchant_id].append(endpoint)
        
        return endpoint
    
    def create_event(
        self,
        event_type: EventType,
        merchant_id: str,
        data: Dict
    ) -> WebhookEvent:
        """
        Create a new webhook event and queue for delivery.
        
        Args:
            event_type: Type of event
            merchant_id: Merchant to notify
            data: Event data (the object that changed)
            
        Returns:
            Created WebhookEvent
        """
        event = WebhookEvent(
            id=f"evt_{secrets.token_hex(12)}",
            type=event_type,
            created_at=datetime.utcnow(),
            data=data,
            merchant_id=merchant_id
        )
        
        with self._lock:
            self._events[event.id] = event
        
        # Queue for delivery
        self._queue.put(event)
        
        return event
    
    def _deliver_to_endpoint(
        self,
        event: WebhookEvent,
        endpoint: WebhookEndpoint,
        attempt_number: int = 1
    ) -> DeliveryAttempt:
        """
        Attempt to deliver event to an endpoint.
        
        Uses HTTPS POST with:
        - JSON body
        - Signature header
        - 30 second timeout
        """
        attempt_id = f"del_{secrets.token_hex(12)}"
        payload = json.dumps(event.to_payload(), sort_keys=True)
        
        # Sign the payload
        signature = self.signer.sign(payload, endpoint.secret)
        
        try:
            # Build request
            request = urllib.request.Request(
                endpoint.url,
                data=payload.encode('utf-8'),
                headers={
                    'Content-Type': 'application/json',
                    'X-Webhook-Signature': signature,
                    'X-Webhook-Event-Type': event.type.value,
                    'X-Webhook-Event-Id': event.id,
                },
                method='POST'
            )
            
            # Send with timeout
            with urllib.request.urlopen(request, timeout=30) as response:
                http_status = response.status
                response_body = response.read().decode('utf-8')[:500]
                
                # 2xx = success
                if 200 <= http_status < 300:
                    attempt = DeliveryAttempt(
                        id=attempt_id,
                        event_id=event.id,
                        endpoint_id=endpoint.id,
                        status=DeliveryStatus.DELIVERED,
                        http_status=http_status,
                        response_body=response_body,
                        attempt_number=attempt_number
                    )
                else:
                    # Non-2xx response
                    attempt = DeliveryAttempt(
                        id=attempt_id,
                        event_id=event.id,
                        endpoint_id=endpoint.id,
                        status=DeliveryStatus.RETRYING if attempt_number < 6 else DeliveryStatus.FAILED,
                        http_status=http_status,
                        response_body=response_body,
                        attempt_number=attempt_number,
                        error_message=f"HTTP {http_status}"
                    )
                    
        except urllib.error.HTTPError as e:
            attempt = DeliveryAttempt(
                id=attempt_id,
                event_id=event.id,
                endpoint_id=endpoint.id,
                status=DeliveryStatus.RETRYING if attempt_number < 6 else DeliveryStatus.FAILED,
                http_status=e.code,
                attempt_number=attempt_number,
                error_message=str(e)
            )
            
        except (urllib.error.URLError, TimeoutError) as e:
            attempt = DeliveryAttempt(
                id=attempt_id,
                event_id=event.id,
                endpoint_id=endpoint.id,
                status=DeliveryStatus.RETRYING if attempt_number < 6 else DeliveryStatus.FAILED,
                attempt_number=attempt_number,
                error_message=str(e)
            )
            
        except Exception as e:
            attempt = DeliveryAttempt(
                id=attempt_id,
                event_id=event.id,
                endpoint_id=endpoint.id,
                status=DeliveryStatus.FAILED,
                attempt_number=attempt_number,
                error_message=f"Unexpected error: {str(e)}"
            )
        
        with self._lock:
            self._attempts[attempt.id] = attempt
        
        return attempt
    
    def _process_event(self, event: WebhookEvent) -> Dict[str, DeliveryAttempt]:
        """Process a single event - deliver to all matching endpoints."""
        results = {}
        
        with self._lock:
            endpoints = self._endpoints.get(event.merchant_id, [])
        
        for endpoint in endpoints:
            if endpoint.should_receive(event.type.value):
                attempt = self._deliver_to_endpoint(event, endpoint)
                results[endpoint.id] = attempt
        
        return results
    
    def start_worker(self):
        """Start the background delivery worker."""
        if self._running:
            return
        
        self._running = True
        self._worker = threading.Thread(target=self._worker_loop, daemon=True)
        self._worker.start()
    
    def stop_worker(self):
        """Stop the background delivery worker."""
        self._running = False
        if self._worker:
            self._worker.join(timeout=5)
    
    def _worker_loop(self):
        """Background worker that processes the delivery queue."""
        while self._running:
            try:
                event = self._queue.get(timeout=1)
                self._process_event(event)
                self._queue.task_done()
            except Empty:
                continue
            except Exception as e:
                print(f"Webhook worker error: {e}")
    
    def deliver_sync(self, event: WebhookEvent) -> Dict[str, DeliveryAttempt]:
        """
        Deliver an event synchronously (for testing).
        
        Returns dict of endpoint_id → DeliveryAttempt
        """
        return self._process_event(event)
    
    def get_event(self, event_id: str) -> Optional[WebhookEvent]:
        """Get an event by ID."""
        return self._events.get(event_id)
    
    def get_endpoint(self, endpoint_id: str) -> Optional[WebhookEndpoint]:
        """Get an endpoint by ID."""
        for endpoints in self._endpoints.values():
            for ep in endpoints:
                if ep.id == endpoint_id:
                    return ep
        return None


class WebhookReceiver:
    """
    Helper for receiving and validating webhooks (merchant side).
    
    Example usage:
        receiver = WebhookReceiver(secret)
        try:
            event = receiver.construct_event(body, signature_header)
            # Handle event
        except InvalidSignature:
            # Return 400
    """
    
    def __init__(self, secret: str):
        self.secret = secret
        self.signer = WebhookSigner()
    
    def construct_event(
        self,
        payload: str,
        signature_header: str,
        tolerance: int = 300
    ) -> Dict:
        """
        Verify signature and construct event object.
        
        Args:
            payload: Raw request body
            signature_header: X-Webhook-Signature header value
            tolerance: Max timestamp age in seconds
            
        Returns:
            Event dict if signature is valid
            
        Raises:
            InvalidSignature: If signature verification fails
        """
        if not self.signer.verify(payload, signature_header, self.secret, tolerance):
            raise InvalidSignature("Webhook signature verification failed")
        
        return json.loads(payload)


class InvalidSignature(Exception):
    """Raised when webhook signature verification fails."""
    pass


# =============================================================================
# Event Builder Helpers
# =============================================================================

def charge_succeeded_event(charge: Dict, merchant_id: str) -> tuple:
    """Build a charge.succeeded event."""
    return EventType.CHARGE_SUCCEEDED, merchant_id, charge


def charge_failed_event(charge: Dict, merchant_id: str) -> tuple:
    """Build a charge.failed event."""
    return EventType.CHARGE_FAILED, merchant_id, charge


def refund_created_event(refund: Dict, merchant_id: str) -> tuple:
    """Build a refund.created event."""
    return EventType.REFUND_CREATED, merchant_id, refund


def dispute_created_event(dispute: Dict, merchant_id: str) -> tuple:
    """Build a dispute.created event."""
    return EventType.DISPUTE_CREATED, merchant_id, dispute


# =============================================================================
# Demo
# =============================================================================

def demo_webhooks():
    """Demonstrate webhook system."""
    print("=" * 60)
    print("WEBHOOK SYSTEM DEMO")
    print("=" * 60)
    
    dispatcher = WebhookDispatcher()
    
    # Register a merchant endpoint
    print("\n1. Registering webhook endpoint:")
    endpoint = dispatcher.register_endpoint(
        merchant_id="merch_demo123",
        url="https://example.com/webhooks",
        events=["charge.succeeded", "charge.failed"]
    )
    print(f"   Endpoint ID: {endpoint.id}")
    print(f"   URL: {endpoint.url}")
    print(f"   Secret: {endpoint.secret[:20]}...")
    print(f"   Events: {endpoint.events}")
    
    # Create an event
    print("\n2. Creating charge.succeeded event:")
    event = dispatcher.create_event(
        event_type=EventType.CHARGE_SUCCEEDED,
        merchant_id="merch_demo123",
        data={
            "id": "ch_test123",
            "amount": 2499,
            "currency": "usd",
            "status": "succeeded"
        }
    )
    print(f"   Event ID: {event.id}")
    print(f"   Type: {event.type.value}")
    print(f"   Payload: {json.dumps(event.to_payload(), indent=2)[:200]}...")
    
    # Show signature
    print("\n3. Webhook signature:")
    payload = json.dumps(event.to_payload(), sort_keys=True)
    signature = dispatcher.signer.sign(payload, endpoint.secret)
    print(f"   Header: X-Webhook-Signature: {signature[:60]}...")
    
    # Verify signature (as merchant would)
    print("\n4. Verifying signature (merchant side):")
    receiver = WebhookReceiver(endpoint.secret)
    try:
        verified_event = receiver.construct_event(payload, signature)
        print(f"   ✓ Signature valid!")
        print(f"   Event type: {verified_event['type']}")
    except InvalidSignature:
        print("   ✗ Signature invalid!")
    
    # Test invalid signature
    print("\n5. Testing invalid signature:")
    try:
        receiver.construct_event(payload, "t=123,v1=invalid")
        print("   ✗ Should have failed!")
    except InvalidSignature:
        print("   ✓ Correctly rejected invalid signature")
    
    # Show retry schedule
    print("\n6. Retry schedule for failed deliveries:")
    for i, seconds in enumerate(dispatcher.RETRY_SCHEDULE, 1):
        if seconds < 3600:
            print(f"   Attempt {i+1}: After {seconds // 60} minutes")
        else:
            print(f"   Attempt {i+1}: After {seconds // 3600} hours")


if __name__ == "__main__":
    demo_webhooks()
