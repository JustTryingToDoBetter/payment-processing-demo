"""
Merchant Webhook Handler

This module shows how a merchant should handle incoming webhooks
from the payment gateway.

Key principles:
1. ALWAYS verify the signature first
2. Use the event ID for idempotency
3. Process asynchronously for slow operations
4. Return 200 quickly to prevent retries
5. Handle events you care about, ignore others
"""

import json
import hashlib
import hmac
import time
from typing import Dict, Callable, Optional
from dataclasses import dataclass, field
from functools import wraps


class WebhookVerificationError(Exception):
    """Raised when webhook signature is invalid."""
    pass


@dataclass
class WebhookEvent:
    """Parsed webhook event."""
    id: str
    type: str
    created: int
    data: Dict
    raw_payload: str
    
    @property
    def object(self) -> Dict:
        """Get the main object from the event data."""
        return self.data.get("object", {})


class WebhookHandler:
    """
    Handler for processing incoming webhooks.
    
    Usage:
        handler = WebhookHandler(secret="whsec_...")
        
        @handler.on("charge.succeeded")
        def handle_charge_succeeded(event):
            charge = event.object
            order_id = charge.get("metadata", {}).get("order_id")
            fulfill_order(order_id)
        
        # In your web framework route:
        def webhook_route(request):
            try:
                handler.handle(request.body, request.headers["X-Webhook-Signature"])
                return Response(status=200)
            except WebhookVerificationError:
                return Response(status=400)
    """
    
    def __init__(self, secret: str, tolerance: int = 300):
        """
        Initialize the webhook handler.
        
        Args:
            secret: Webhook signing secret (from gateway dashboard)
            tolerance: Max timestamp age in seconds (default 5 min)
        """
        self.secret = secret
        self.tolerance = tolerance
        self._handlers: Dict[str, list] = {}
        self._processed_events: set = set()  # For idempotency
    
    def verify_signature(self, payload: str, signature_header: str) -> bool:
        """
        Verify the webhook signature.
        
        Args:
            payload: Raw request body
            signature_header: Value of X-Webhook-Signature header
            
        Returns:
            True if signature is valid
            
        Raises:
            WebhookVerificationError if invalid
        """
        try:
            # Parse signature header: t=timestamp,v1=signature
            elements = dict(item.split("=") for item in signature_header.split(","))
            timestamp = int(elements.get("t", 0))
            signature = elements.get("v1", "")
            
            # Check timestamp (prevent replay attacks)
            age = abs(int(time.time()) - timestamp)
            if age > self.tolerance:
                raise WebhookVerificationError(
                    f"Timestamp too old: {age} seconds"
                )
            
            # Calculate expected signature
            signed_payload = f"{timestamp}.{payload}"
            expected = hmac.new(
                self.secret.encode('utf-8'),
                signed_payload.encode('utf-8'),
                hashlib.sha256
            ).hexdigest()
            
            # Constant-time comparison (prevents timing attacks)
            if not hmac.compare_digest(signature, expected):
                raise WebhookVerificationError("Signature mismatch")
            
            return True
            
        except (ValueError, KeyError) as e:
            raise WebhookVerificationError(f"Invalid signature header: {e}")
    
    def parse_event(self, payload: str) -> WebhookEvent:
        """Parse webhook payload into an event object."""
        try:
            data = json.loads(payload)
            return WebhookEvent(
                id=data["id"],
                type=data["type"],
                created=data["created"],
                data=data["data"],
                raw_payload=payload
            )
        except (json.JSONDecodeError, KeyError) as e:
            raise WebhookVerificationError(f"Invalid payload: {e}")
    
    def on(self, event_type: str):
        """
        Decorator to register an event handler.
        
        Usage:
            @handler.on("charge.succeeded")
            def handle_success(event):
                # Process the event
                pass
        """
        def decorator(func: Callable[[WebhookEvent], None]):
            if event_type not in self._handlers:
                self._handlers[event_type] = []
            self._handlers[event_type].append(func)
            return func
        return decorator
    
    def handle(self, payload: str, signature_header: str) -> WebhookEvent:
        """
        Verify and process an incoming webhook.
        
        Args:
            payload: Raw request body
            signature_header: X-Webhook-Signature header value
            
        Returns:
            The parsed WebhookEvent
            
        Raises:
            WebhookVerificationError if signature is invalid
        """
        # Step 1: Verify signature
        self.verify_signature(payload, signature_header)
        
        # Step 2: Parse event
        event = self.parse_event(payload)
        
        # Step 3: Check idempotency
        if event.id in self._processed_events:
            # Already processed, return without re-processing
            return event
        
        # Step 4: Call handlers
        handlers = self._handlers.get(event.type, [])
        for handler in handlers:
            try:
                handler(event)
            except Exception as e:
                # Log but don't fail - we want to mark as processed
                print(f"Handler error for {event.type}: {e}")
        
        # Step 5: Mark as processed
        self._processed_events.add(event.id)
        
        return event
    
    def register_handler(self, event_type: str, handler: Callable):
        """Register a handler function for an event type."""
        if event_type not in self._handlers:
            self._handlers[event_type] = []
        self._handlers[event_type].append(handler)


# =============================================================================
# Example handlers for common events
# =============================================================================

def create_example_handlers(handler: WebhookHandler):
    """Register example handlers for common events."""
    
    @handler.on("charge.succeeded")
    def handle_charge_succeeded(event: WebhookEvent):
        """
        Handle successful charge.
        
        This is where you fulfill the order!
        """
        charge = event.object
        print(f"💰 Charge succeeded: {charge.get('id')}")
        print(f"   Amount: ${charge.get('amount', 0)/100:.2f}")
        
        # Get order info from metadata
        metadata = charge.get("metadata", {})
        order_id = metadata.get("order_id")
        
        if order_id:
            # In production: Mark order as paid and trigger fulfillment
            print(f"   Fulfilling order: {order_id}")
            # fulfill_order(order_id)
    
    @handler.on("charge.failed")
    def handle_charge_failed(event: WebhookEvent):
        """Handle failed charge."""
        charge = event.object
        print(f"❌ Charge failed: {charge.get('id')}")
        print(f"   Reason: {charge.get('failure_message')}")
        
        # Notify customer, retry with different payment method, etc.
    
    @handler.on("refund.created")
    def handle_refund_created(event: WebhookEvent):
        """Handle refund creation."""
        refund = event.object
        print(f"💸 Refund created: {refund.get('id')}")
        print(f"   Amount: ${refund.get('amount', 0)/100:.2f}")
        print(f"   Charge: {refund.get('charge')}")
        
        # Update order status, notify customer, etc.
    
    @handler.on("dispute.created")
    def handle_dispute_created(event: WebhookEvent):
        """
        Handle new dispute (chargeback).
        
        CRITICAL: You typically have 7-21 days to respond!
        """
        dispute = event.object
        print(f"⚠️  DISPUTE CREATED: {dispute.get('id')}")
        print(f"   Amount: ${dispute.get('amount', 0)/100:.2f}")
        print(f"   Reason: {dispute.get('reason')}")
        
        # Alert team, gather evidence, prepare response
        # send_alert_to_team("New dispute!", dispute)


# =============================================================================
# Flask/Django integration examples
# =============================================================================

FLASK_EXAMPLE = '''
# Flask webhook endpoint example
from flask import Flask, request, jsonify
from webhook_handler import WebhookHandler, WebhookVerificationError

app = Flask(__name__)
webhook_handler = WebhookHandler(secret="whsec_...")

@webhook_handler.on("charge.succeeded")
def on_charge_succeeded(event):
    charge = event.object
    fulfill_order(charge["metadata"]["order_id"])

@app.route("/webhooks/payment", methods=["POST"])
def handle_webhook():
    payload = request.data.decode("utf-8")
    signature = request.headers.get("X-Webhook-Signature", "")
    
    try:
        event = webhook_handler.handle(payload, signature)
        return jsonify({"received": True}), 200
    except WebhookVerificationError as e:
        return jsonify({"error": str(e)}), 400
'''

DJANGO_EXAMPLE = '''
# Django webhook endpoint example
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from .webhook_handler import WebhookHandler, WebhookVerificationError

webhook_handler = WebhookHandler(secret="whsec_...")

@webhook_handler.on("charge.succeeded")
def on_charge_succeeded(event):
    charge = event.object
    order_id = charge["metadata"]["order_id"]
    Order.objects.filter(id=order_id).update(status="paid")

@csrf_exempt
@require_POST
def payment_webhook(request):
    payload = request.body.decode("utf-8")
    signature = request.headers.get("X-Webhook-Signature", "")
    
    try:
        event = webhook_handler.handle(payload, signature)
        return JsonResponse({"received": True})
    except WebhookVerificationError as e:
        return JsonResponse({"error": str(e)}, status=400)
'''


# =============================================================================
# Demo
# =============================================================================

def demo_webhook_handler():
    """Demonstrate webhook handling."""
    print("=" * 60)
    print("WEBHOOK HANDLER DEMO")
    print("=" * 60)
    
    # Create handler with a secret
    secret = "whsec_test_secret_key_12345"
    handler = WebhookHandler(secret=secret)
    
    # Register example handlers
    create_example_handlers(handler)
    
    # Simulate incoming webhook
    print("\n1. Simulating incoming webhook:")
    
    # Create a mock payload
    payload = json.dumps({
        "id": "evt_test123",
        "type": "charge.succeeded",
        "created": int(time.time()),
        "data": {
            "object": {
                "id": "ch_test456",
                "amount": 2499,
                "currency": "usd",
                "status": "succeeded",
                "metadata": {
                    "order_id": "order_789"
                }
            }
        }
    })
    
    # Create valid signature
    timestamp = int(time.time())
    signed_payload = f"{timestamp}.{payload}"
    signature = hmac.new(
        secret.encode('utf-8'),
        signed_payload.encode('utf-8'),
        hashlib.sha256
    ).hexdigest()
    signature_header = f"t={timestamp},v1={signature}"
    
    # Process the webhook
    print(f"   Signature: {signature_header[:50]}...")
    event = handler.handle(payload, signature_header)
    print(f"   Event processed: {event.id}")
    
    # Test idempotency
    print("\n2. Testing idempotency (same event again):")
    event2 = handler.handle(payload, signature_header)
    print(f"   Event returned (not re-processed): {event2.id}")
    
    # Test invalid signature
    print("\n3. Testing invalid signature:")
    try:
        handler.handle(payload, "t=123,v1=invalid")
        print("   Should have failed!")
    except WebhookVerificationError as e:
        print(f"   ✓ Correctly rejected: {e}")
    
    # Test old timestamp
    print("\n4. Testing expired timestamp:")
    old_timestamp = int(time.time()) - 600  # 10 minutes ago
    old_signed = f"{old_timestamp}.{payload}"
    old_sig = hmac.new(
        secret.encode('utf-8'),
        old_signed.encode('utf-8'),
        hashlib.sha256
    ).hexdigest()
    try:
        handler.handle(payload, f"t={old_timestamp},v1={old_sig}")
        print("   Should have failed!")
    except WebhookVerificationError as e:
        print(f"   ✓ Correctly rejected: {e}")
    
    print("\n5. Framework integration examples:")
    print("-" * 40)
    print("Flask:")
    print(FLASK_EXAMPLE[:500] + "...")
    print("\nDjango:")
    print(DJANGO_EXAMPLE[:500] + "...")


if __name__ == "__main__":
    demo_webhook_handler()
