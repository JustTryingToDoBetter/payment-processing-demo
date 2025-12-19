# ⚡ Real-World Constraints: Production Challenges

> Handling network failures, duplicates, chargebacks, and all the chaos of production systems

## The Reality of Production

In a perfect world, every API call succeeds in milliseconds. In the real world:

- Networks fail
- Services timeout
- Databases crash
- Users click buttons multiple times
- Fraudsters try to exploit edge cases
- Banks have outages

Let's learn how to handle these challenges.

---

## 🌐 Network Latency and Timeouts

### Understanding the Problem

```
┌─────────────────────────────────────────────────────────────────────┐
│                    TIMEOUT SCENARIOS                                 │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  SCENARIO 1: Request Timeout                                        │
│  ──────────────────────────────                                     │
│  Your Server ────── request ─────> Gateway                          │
│      │                               │                              │
│      │      (10 seconds pass...)     │                              │
│      │                               │  Processing...               │
│      × TIMEOUT                       │                              │
│      │                               │  Done! Returns success       │
│      │                               ▼                              │
│                                                                     │
│  Result: You don't know if payment succeeded!                       │
│  The charge DID go through, but you never got the response.        │
│                                                                     │
│  ─────────────────────────────────────────────────────────────────  │
│                                                                     │
│  SCENARIO 2: Response Timeout                                       │
│  ───────────────────────────────                                    │
│  Your Server ────── request ─────> Gateway                          │
│      │                               │                              │
│      │         < success ──────────│                               │
│      ×   (Response lost in network)                                 │
│      │                                                              │
│      │   TIMEOUT                                                    │
│                                                                     │
│  Result: Payment succeeded, but you think it failed!               │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

### Solution: Idempotency Keys + Safe Retries

```python
import time
from typing import Optional
import requests

class PaymentClient:
    """
    Payment gateway client with proper timeout and retry handling.
    """
    
    def __init__(self, api_key: str, base_url: str):
        self.api_key = api_key
        self.base_url = base_url
        self.session = requests.Session()
        
        # Configure timeouts
        self.connect_timeout = 5  # Time to establish connection
        self.read_timeout = 30    # Time to wait for response
    
    def create_charge(
        self,
        token: str,
        amount: int,
        currency: str,
        idempotency_key: str,
        max_retries: int = 3
    ) -> dict:
        """
        Create a charge with retry logic and idempotency.
        """
        
        for attempt in range(max_retries):
            try:
                response = self.session.post(
                    f"{self.base_url}/v1/charges",
                    json={
                        'token': token,
                        'amount': amount,
                        'currency': currency
                    },
                    headers={
                        'Authorization': f'Bearer {self.api_key}',
                        'Idempotency-Key': idempotency_key  # CRITICAL!
                    },
                    timeout=(self.connect_timeout, self.read_timeout)
                )
                
                if response.status_code == 200:
                    return response.json()
                    
                elif response.status_code == 409:
                    # Idempotency conflict - request is being processed
                    # Wait and retry
                    time.sleep(1)
                    continue
                    
                elif response.status_code >= 500:
                    # Server error - safe to retry with idempotency
                    self._wait_with_backoff(attempt)
                    continue
                    
                else:
                    # Client error (4xx) - don't retry, it will fail again
                    error = response.json()
                    raise PaymentError(error['message'], error['code'])
                    
            except requests.Timeout:
                # Timeout - safe to retry with same idempotency key!
                # If the charge went through, we'll get the same result
                if attempt < max_retries - 1:
                    self._wait_with_backoff(attempt)
                    continue
                else:
                    # Last attempt, must handle uncertainty
                    raise PaymentUnknownError(
                        "Payment status unknown after timeout. "
                        "Check payment status before retrying with new key."
                    )
                    
            except requests.ConnectionError:
                # Network issue - safe to retry
                if attempt < max_retries - 1:
                    self._wait_with_backoff(attempt)
                    continue
                raise
        
        raise PaymentError("Max retries exceeded")
    
    def _wait_with_backoff(self, attempt: int):
        """
        Exponential backoff: 1s, 2s, 4s, ...
        """
        wait_time = min(2 ** attempt, 30)  # Cap at 30 seconds
        time.sleep(wait_time)
    
    def check_charge_status(self, idempotency_key: str) -> Optional[dict]:
        """
        Check if a charge exists for this idempotency key.
        Use this after timeouts to check what happened.
        """
        response = self.session.get(
            f"{self.base_url}/v1/charges",
            params={'idempotency_key': idempotency_key},
            headers={'Authorization': f'Bearer {self.api_key}'},
            timeout=(self.connect_timeout, self.read_timeout)
        )
        
        if response.status_code == 200:
            charges = response.json()['data']
            if charges:
                return charges[0]
        return None
```

### Timeout Best Practices

```
┌─────────────────────────────────────────────────────────────────────┐
│                    TIMEOUT CONFIGURATION                             │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  CONNECT TIMEOUT: 3-5 seconds                                       │
│  • Time to establish TCP connection                                 │
│  • If server is down, fail fast                                     │
│  • Shorter is better                                                │
│                                                                     │
│  READ TIMEOUT: 20-45 seconds                                        │
│  • Time to wait for response after connection                       │
│  • Payment processing can be slow (3DS, bank networks)              │
│  • Too short = false failures                                       │
│  • Too long = poor user experience                                  │
│                                                                     │
│  TOTAL TIMEOUT: Consider user experience                            │
│  • User waiting 30+ seconds feels broken                            │
│  • Show progress indicators                                         │
│  • Consider background processing for slow operations               │
│                                                                     │
│  RETRY TIMEOUTS:                                                    │
│  • Use exponential backoff                                          │
│  • 1s → 2s → 4s → 8s → stop                                        │
│  • Add jitter to prevent thundering herd                            │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 🔄 Duplicate Request Prevention

### The Double-Click Problem

```
┌─────────────────────────────────────────────────────────────────────┐
│                    THE DOUBLE-CLICK DISASTER                         │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  User clicks "Pay" button                                           │
│       │                                                             │
│       │  (Button feels unresponsive)                                │
│       │                                                             │
│  User clicks "Pay" again                                            │
│       │                                                             │
│       │  (And again...)                                             │
│       │                                                             │
│  Result without protection:                                         │
│       │                                                             │
│       ├── Request 1 → Charge $100 → Success                         │
│       ├── Request 2 → Charge $100 → Success                         │
│       └── Request 3 → Charge $100 → Success                         │
│                                                                     │
│  Customer charged $300! 😱                                          │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

### Multi-Layer Protection

```python
# Layer 1: Frontend Protection
"""
// checkout.js
const payButton = document.getElementById('pay-button');

payButton.addEventListener('click', async () => {
    // Immediately disable button
    payButton.disabled = true;
    payButton.textContent = 'Processing...';
    
    try {
        await processPayment();
    } finally {
        // Re-enable only on definite failure
        // Don't re-enable on success - redirect instead
        payButton.disabled = false;
        payButton.textContent = 'Pay Now';
    }
});
"""

# Layer 2: Backend Request Deduplication
class RequestDeduplicator:
    """
    Prevents duplicate requests from being processed.
    Uses Redis for distributed locking.
    """
    
    def __init__(self, redis_client):
        self.redis = redis_client
    
    def deduplicate(self, order_id: str, callback):
        """
        Ensures the callback runs at most once per order.
        """
        lock_key = f"payment_lock:{order_id}"
        result_key = f"payment_result:{order_id}"
        
        # Check if already processed
        existing_result = self.redis.get(result_key)
        if existing_result:
            return json.loads(existing_result)
        
        # Try to acquire lock (only one request will succeed)
        lock = self.redis.lock(lock_key, timeout=60)
        
        if lock.acquire(blocking=False):  # Non-blocking
            try:
                # Double-check after acquiring lock
                existing_result = self.redis.get(result_key)
                if existing_result:
                    return json.loads(existing_result)
                
                # Process the request
                result = callback()
                
                # Store result for future duplicates
                self.redis.setex(
                    result_key, 
                    3600,  # Cache for 1 hour
                    json.dumps(result)
                )
                return result
                
            finally:
                lock.release()
        else:
            # Another request has the lock - wait for result
            for _ in range(60):  # Wait up to 60 seconds
                time.sleep(1)
                existing_result = self.redis.get(result_key)
                if existing_result:
                    return json.loads(existing_result)
            
            raise TimeoutError("Payment processing taking too long")


# Layer 3: Idempotency at Gateway Level
# (Already covered - gateway won't double-charge with same idempotency key)
```

### Idempotency Key Best Practices

```
┌─────────────────────────────────────────────────────────────────────┐
│                    IDEMPOTENCY KEY PATTERNS                          │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  GOOD KEYS (deterministic, meaningful):                             │
│  ✅ "order_12345_payment"                                           │
│  ✅ "subscription_789_renewal_2024-01"                              │
│  ✅ "refund_charge_abc123"                                          │
│                                                                     │
│  BAD KEYS (random, will cause duplicates):                          │
│  ❌ uuid.uuid4()  (Different each request!)                         │
│  ❌ f"{order_id}_{timestamp}" (Timestamp changes!)                  │
│  ❌ f"{order_id}_{random()}" (Random changes!)                      │
│                                                                     │
│  VERSIONED KEYS (for retries with changes):                         │
│  • First attempt: "order_123_v1"                                    │
│  • User changes card, retry: "order_123_v2"                         │
│  • Same card, different amount not allowed (use new order)          │
│                                                                     │
│  KEY PROPERTIES:                                                    │
│  • Must be deterministic for the same logical operation             │
│  • Must include all relevant context (order ID, action type)        │
│  • Should be meaningful for debugging                               │
│  • Typically expire after 24-48 hours                               │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 💸 Failed Payments: Handling Gracefully

### Common Failure Types

```
┌─────────────────────────────────────────────────────────────────────┐
│                    PAYMENT FAILURE TYPES                             │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  TYPE 1: SOFT DECLINES (Temporary, can retry)                       │
│  ─────────────────────────────────────────────                      │
│  • Issuer temporarily unavailable                                   │
│  • Card requires 3DS authentication                                 │
│  • Temporary hold on card                                           │
│                                                                     │
│  Action: Retry immediately or with 3DS                              │
│                                                                     │
│  TYPE 2: HARD DECLINES (Permanent, don't retry)                     │
│  ────────────────────────────────────────────                       │
│  • Insufficient funds                                               │
│  • Card expired                                                     │
│  • Card reported stolen                                             │
│  • Invalid card number                                              │
│                                                                     │
│  Action: Ask customer for different card                            │
│                                                                     │
│  TYPE 3: PROCESSING ERRORS (Your side)                              │
│  ──────────────────────────────────────                             │
│  • Gateway timeout                                                  │
│  • Network error                                                    │
│  • Invalid API request                                              │
│                                                                     │
│  Action: Fix issue, retry with same idempotency key                 │
│                                                                     │
│  TYPE 4: FRAUD BLOCKS                                               │
│  ─────────────────────                                              │
│  • Fraud detection triggered                                        │
│  • Suspicious activity                                              │
│                                                                     │
│  Action: Don't reveal fraud reason, ask for different card          │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

### Implementing Graceful Failure Handling

```python
from enum import Enum
from dataclasses import dataclass
from typing import Optional

class DeclineCategory(Enum):
    SOFT = "soft"           # Can retry
    HARD = "hard"           # Need different card
    FRAUD = "fraud"         # Don't reveal, need different card
    PROCESSING = "processing"  # Our problem, can retry

@dataclass
class DeclineInfo:
    category: DeclineCategory
    code: str
    internal_message: str    # For logs
    customer_message: str    # For display
    retryable: bool
    needs_different_card: bool

class DeclineHandler:
    """
    Maps decline codes to appropriate responses.
    Never reveal exact reason for fraud declines!
    """
    
    DECLINE_MAP = {
        # Soft declines - retryable
        'issuer_unavailable': DeclineInfo(
            category=DeclineCategory.SOFT,
            code='issuer_unavailable',
            internal_message='Issuer temporarily unavailable',
            customer_message='Payment could not be processed. Please try again.',
            retryable=True,
            needs_different_card=False
        ),
        'authentication_required': DeclineInfo(
            category=DeclineCategory.SOFT,
            code='authentication_required',
            internal_message='3DS authentication required',
            customer_message='Additional authentication required.',
            retryable=True,
            needs_different_card=False
        ),
        
        # Hard declines - need different card
        'insufficient_funds': DeclineInfo(
            category=DeclineCategory.HARD,
            code='insufficient_funds',
            internal_message='Card has insufficient funds',
            customer_message='Your card has insufficient funds. Please try a different card.',
            retryable=False,
            needs_different_card=True
        ),
        'expired_card': DeclineInfo(
            category=DeclineCategory.HARD,
            code='expired_card',
            internal_message='Card is expired',
            customer_message='Your card has expired. Please use a different card.',
            retryable=False,
            needs_different_card=True
        ),
        'invalid_number': DeclineInfo(
            category=DeclineCategory.HARD,
            code='invalid_number',
            internal_message='Invalid card number',
            customer_message='Please check your card number and try again.',
            retryable=False,
            needs_different_card=False  # Might be typo
        ),
        
        # Fraud - hide the real reason!
        'stolen_card': DeclineInfo(
            category=DeclineCategory.FRAUD,
            code='stolen_card',
            internal_message='Card reported stolen - DO NOT TELL CUSTOMER',
            customer_message='Your card was declined. Please try a different card.',
            retryable=False,
            needs_different_card=True
        ),
        'fraud_detected': DeclineInfo(
            category=DeclineCategory.FRAUD,
            code='fraud_detected',
            internal_message='Fraud detection triggered - DO NOT TELL CUSTOMER',
            customer_message='Your card was declined. Please try a different card.',
            retryable=False,
            needs_different_card=True
        ),
    }
    
    DEFAULT_DECLINE = DeclineInfo(
        category=DeclineCategory.HARD,
        code='generic_decline',
        internal_message='Unknown decline reason',
        customer_message='Your card was declined. Please try a different card.',
        retryable=False,
        needs_different_card=True
    )
    
    @classmethod
    def handle_decline(cls, decline_code: str) -> DeclineInfo:
        """
        Get appropriate response for a decline code.
        """
        return cls.DECLINE_MAP.get(decline_code, cls.DEFAULT_DECLINE)
    
    @classmethod
    def should_retry(cls, decline_code: str, attempt: int) -> bool:
        """
        Determine if we should automatically retry.
        """
        info = cls.handle_decline(decline_code)
        
        if not info.retryable:
            return False
        
        if attempt >= 3:  # Max 3 retries
            return False
        
        return True


# Usage in payment flow
class PaymentProcessor:
    def process_payment(self, order, token):
        max_attempts = 3
        
        for attempt in range(max_attempts):
            try:
                result = self.gateway.charge(token, order.amount)
                
                if result['status'] == 'succeeded':
                    return {'success': True, 'charge_id': result['id']}
                    
                elif result['status'] == 'failed':
                    decline_info = DeclineHandler.handle_decline(
                        result['decline_code']
                    )
                    
                    # Log internal details (for debugging)
                    self.logger.info(
                        f"Payment declined: {decline_info.internal_message}",
                        extra={'order_id': order.id, 'attempt': attempt}
                    )
                    
                    # Check if we should retry
                    if DeclineHandler.should_retry(result['decline_code'], attempt):
                        time.sleep(2 ** attempt)  # Backoff
                        continue
                    
                    # Return customer-safe message
                    return {
                        'success': False,
                        'message': decline_info.customer_message,
                        'needs_different_card': decline_info.needs_different_card
                    }
                    
            except GatewayTimeout:
                if attempt < max_attempts - 1:
                    continue
                raise
        
        return {
            'success': False,
            'message': 'Payment could not be processed. Please try again.'
        }
```

---

## 📋 Chargebacks and Refunds

### Understanding Chargebacks

```
┌─────────────────────────────────────────────────────────────────────┐
│                    CHARGEBACK FLOW                                   │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  TIMELINE:                                                          │
│  ─────────                                                          │
│                                                                     │
│  Day 1: Transaction occurs                                          │
│       └── Customer buys product                                     │
│                                                                     │
│  Day 30-120: Customer disputes charge with their bank              │
│       └── "I didn't authorize this" / "Item never arrived"         │
│                                                                     │
│  Day 30-120: Bank initiates chargeback                             │
│       ├── You receive dispute notification (webhook)               │
│       ├── Funds held from your account                              │
│       └── You have 7-14 days to respond                            │
│                                                                     │
│  Day 37-134: You submit evidence                                    │
│       ├── Proof of delivery                                         │
│       ├── Customer communication                                    │
│       ├── IP address, device info                                   │
│       └── Any other supporting docs                                 │
│                                                                     │
│  Day 60-180: Bank makes decision                                    │
│       ├── In your favor → Funds released                           │
│       └── In customer favor → Funds gone + $15-25 fee              │
│                                                                     │
│  CHARGEBACK COSTS:                                                  │
│  ────────────────                                                   │
│  • Lost product/service value                                       │
│  • Lost transaction amount                                          │
│  • Chargeback fee ($15-25 per case)                                │
│  • Increased processing fees if rate is high                        │
│  • Account termination risk if rate exceeds 1%                      │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

### Handling Disputes

```python
from datetime import datetime, timedelta
from enum import Enum
from typing import Optional

class DisputeReason(Enum):
    FRAUDULENT = "fraudulent"
    DUPLICATE = "duplicate"
    PRODUCT_NOT_RECEIVED = "product_not_received"
    PRODUCT_UNACCEPTABLE = "product_unacceptable"
    SUBSCRIPTION_CANCELED = "subscription_canceled"
    UNRECOGNIZED = "unrecognized"
    CREDIT_NOT_PROCESSED = "credit_not_processed"

class DisputeHandler:
    """
    Handle chargebacks/disputes professionally.
    """
    
    def handle_dispute_created(self, dispute_data: dict):
        """
        Called when we receive dispute.created webhook.
        """
        dispute_id = dispute_data['id']
        charge_id = dispute_data['charge_id']
        reason = DisputeReason(dispute_data['reason'])
        evidence_due = datetime.fromtimestamp(dispute_data['evidence_due_by'])
        
        # 1. Alert the team immediately
        self.send_alert(
            subject=f"🚨 Chargeback Received - ${dispute_data['amount']/100:.2f}",
            body=f"Dispute {dispute_id} for charge {charge_id}. "
                 f"Reason: {reason.value}. "
                 f"Evidence due: {evidence_due}"
        )
        
        # 2. Gather evidence automatically
        evidence = self.gather_evidence(charge_id, reason)
        
        # 3. Create task for review before deadline
        self.create_task(
            title=f"Review dispute {dispute_id}",
            due_date=evidence_due - timedelta(days=2),  # 2 days buffer
            context=evidence
        )
        
        return evidence
    
    def gather_evidence(self, charge_id: str, reason: DisputeReason) -> dict:
        """
        Automatically gather evidence based on dispute reason.
        """
        charge = self.db.get_charge(charge_id)
        order = self.db.get_order(charge.order_id)
        customer = self.db.get_customer(order.customer_id)
        
        base_evidence = {
            # Basic transaction info
            'charge_id': charge_id,
            'amount': charge.amount,
            'charge_date': charge.created_at.isoformat(),
            
            # Customer info (proves they're real)
            'customer_email': customer.email,
            'customer_name': customer.name,
            'customer_ip': charge.ip_address,
            'billing_address': order.billing_address,
            
            # Your policies
            'refund_policy': self.get_refund_policy_url(),
            'terms_of_service': self.get_tos_url(),
        }
        
        # Add reason-specific evidence
        if reason == DisputeReason.PRODUCT_NOT_RECEIVED:
            base_evidence.update({
                'shipping_carrier': order.shipping.carrier,
                'tracking_number': order.shipping.tracking,
                'delivery_date': order.shipping.delivered_at,
                'delivery_signature': order.shipping.signature_url,
            })
            
        elif reason == DisputeReason.FRAUDULENT:
            # Prove the cardholder made the purchase
            base_evidence.update({
                'device_fingerprint': charge.device_fingerprint,
                '3ds_authenticated': charge.three_d_secure.authenticated,
                'avs_match': charge.avs_check,
                'cvv_match': charge.cvv_check,
                'previous_purchases': self._get_previous_purchases(customer.id),
            })
            
        elif reason == DisputeReason.DUPLICATE:
            base_evidence.update({
                'unique_transaction_proof': self._prove_not_duplicate(charge_id),
            })
        
        return base_evidence
    
    def submit_evidence(self, dispute_id: str, evidence: dict):
        """
        Submit evidence to fight the dispute.
        """
        response = self.gateway.submit_dispute_evidence(
            dispute_id=dispute_id,
            evidence=evidence
        )
        
        self.db.save_dispute_response(dispute_id, evidence)
        self.logger.info(f"Submitted evidence for dispute {dispute_id}")
        
        return response


# Refund best practices
class RefundService:
    """
    Handle refunds proactively to prevent chargebacks.
    A refund costs ~$0 vs chargeback costs ~$25+
    """
    
    def create_refund(
        self, 
        charge_id: str, 
        amount: Optional[int] = None,
        reason: str = "customer_request"
    ) -> dict:
        """
        Create a refund for a charge.
        Can be full or partial.
        """
        charge = self.db.get_charge(charge_id)
        
        # Validate refund
        refund_amount = amount or charge.amount
        already_refunded = self._get_refunded_amount(charge_id)
        
        if already_refunded + refund_amount > charge.amount:
            raise ValueError("Cannot refund more than original charge")
        
        if charge.created_at < datetime.now() - timedelta(days=180):
            raise ValueError("Cannot refund charges older than 180 days")
        
        # Create refund with idempotency
        idempotency_key = f"refund_{charge_id}_{refund_amount}"
        
        result = self.gateway.create_refund(
            charge_id=charge_id,
            amount=refund_amount,
            reason=reason,
            idempotency_key=idempotency_key
        )
        
        # Update our records
        self.db.save_refund(
            charge_id=charge_id,
            refund_id=result['id'],
            amount=refund_amount
        )
        
        # Notify relevant systems
        self.events.emit('refund.created', {
            'refund_id': result['id'],
            'charge_id': charge_id,
            'amount': refund_amount,
            'order_id': charge.order_id
        })
        
        return result
    
    def consider_proactive_refund(self, customer_complaint: str, order_id: str):
        """
        Sometimes it's better to refund proactively than risk a chargeback.
        """
        order = self.db.get_order(order_id)
        
        # If order value is low, refund is cheaper than fighting
        if order.amount < 5000:  # Under $50
            self.logger.info(
                f"Proactive refund for order {order_id} - "
                f"${order.amount/100} cheaper than potential chargeback"
            )
            return self.create_refund(
                order.charge_id,
                reason="proactive_customer_satisfaction"
            )
        
        # For higher amounts, review first
        return None
```

---

## 🏗️ Designing for Failure

### The Circuit Breaker Pattern

```
┌─────────────────────────────────────────────────────────────────────┐
│                    CIRCUIT BREAKER PATTERN                           │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  Problem: Gateway is down. Every request fails and times out.       │
│  Result: Slow checkout, bad UX, wasted resources.                   │
│                                                                     │
│  Solution: Circuit breaker stops calling failing services.          │
│                                                                     │
│  STATES:                                                            │
│  ───────                                                            │
│                                                                     │
│  [CLOSED] ─── failure ──> [OPEN] ─── timeout ──> [HALF-OPEN]       │
│      ▲                       │                        │             │
│      │                       │                        │             │
│      └───── success ─────────┴─────── success ────────┘             │
│                              │                                      │
│                              └─────── failure ─── [OPEN]           │
│                                                                     │
│  CLOSED: Normal operation, requests go through                      │
│  OPEN: Too many failures, requests fail immediately                 │
│  HALF-OPEN: Testing if service recovered, limited requests          │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

```python
import time
from enum import Enum
from threading import Lock
from typing import Callable

class CircuitState(Enum):
    CLOSED = "closed"      # Normal operation
    OPEN = "open"          # Failing fast
    HALF_OPEN = "half_open"  # Testing recovery

class CircuitBreaker:
    """
    Prevents cascading failures when external services fail.
    """
    
    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_timeout: int = 30,
        half_open_max_calls: int = 3
    ):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.half_open_max_calls = half_open_max_calls
        
        self.state = CircuitState.CLOSED
        self.failure_count = 0
        self.last_failure_time = None
        self.half_open_calls = 0
        self.lock = Lock()
    
    def call(self, func: Callable, *args, **kwargs):
        """
        Execute function through circuit breaker.
        """
        with self.lock:
            if self.state == CircuitState.OPEN:
                if self._should_attempt_reset():
                    self.state = CircuitState.HALF_OPEN
                    self.half_open_calls = 0
                else:
                    raise CircuitOpenError("Circuit is open, failing fast")
            
            if self.state == CircuitState.HALF_OPEN:
                if self.half_open_calls >= self.half_open_max_calls:
                    raise CircuitOpenError("Half-open call limit reached")
                self.half_open_calls += 1
        
        try:
            result = func(*args, **kwargs)
            self._on_success()
            return result
            
        except Exception as e:
            self._on_failure()
            raise
    
    def _should_attempt_reset(self) -> bool:
        return (
            self.last_failure_time and 
            time.time() - self.last_failure_time >= self.recovery_timeout
        )
    
    def _on_success(self):
        with self.lock:
            if self.state == CircuitState.HALF_OPEN:
                self.state = CircuitState.CLOSED
            self.failure_count = 0
    
    def _on_failure(self):
        with self.lock:
            self.failure_count += 1
            self.last_failure_time = time.time()
            
            if self.failure_count >= self.failure_threshold:
                self.state = CircuitState.OPEN
            elif self.state == CircuitState.HALF_OPEN:
                self.state = CircuitState.OPEN


# Usage
payment_circuit = CircuitBreaker(failure_threshold=5, recovery_timeout=30)

def process_payment(token, amount):
    try:
        return payment_circuit.call(
            gateway.charge,
            token=token,
            amount=amount
        )
    except CircuitOpenError:
        # Fallback behavior
        return queue_for_later_processing(token, amount)
```

### Graceful Degradation

```
┌─────────────────────────────────────────────────────────────────────┐
│                    GRACEFUL DEGRADATION STRATEGY                     │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  When primary payment method fails, have fallbacks:                 │
│                                                                     │
│  LEVEL 1: Primary Gateway                                           │
│       └── Try primary payment processor                             │
│           └── If fails: Go to Level 2                               │
│                                                                     │
│  LEVEL 2: Retry with 3DS                                            │
│       └── Sometimes 3DS helps soft declines                         │
│           └── If fails: Go to Level 3                               │
│                                                                     │
│  LEVEL 3: Secondary Gateway                                         │
│       └── Try backup payment processor                              │
│           └── If fails: Go to Level 4                               │
│                                                                     │
│  LEVEL 4: Queue for Manual Processing                               │
│       └── Accept order, process payment later                       │
│       └── Notify customer of delay                                  │
│       └── Only for trusted customers                                │
│                                                                     │
│  LEVEL 5: Alternative Payment Methods                               │
│       └── Suggest PayPal, bank transfer, etc.                       │
│                                                                     │
│  LEVEL 6: Accept Failure Gracefully                                 │
│       └── "We're experiencing issues. Please try again later."     │
│       └── Save cart for customer                                    │
│       └── Offer to email when resolved                              │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 📊 Monitoring and Alerting

### Key Metrics to Track

```python
from prometheus_client import Counter, Histogram, Gauge

# Transaction metrics
payment_attempts = Counter(
    'payment_attempts_total',
    'Total payment attempts',
    ['gateway', 'currency']
)

payment_success = Counter(
    'payment_success_total',
    'Successful payments',
    ['gateway', 'currency']
)

payment_failures = Counter(
    'payment_failures_total',
    'Failed payments',
    ['gateway', 'currency', 'decline_code']
)

# Latency metrics
payment_latency = Histogram(
    'payment_processing_seconds',
    'Payment processing latency',
    ['gateway'],
    buckets=[0.1, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0]
)

# Business metrics
daily_volume = Gauge(
    'daily_payment_volume_cents',
    'Total payment volume today',
    ['currency']
)

# Alert conditions
ALERT_CONDITIONS = {
    'high_failure_rate': {
        'condition': 'payment_failures / payment_attempts > 0.1',
        'severity': 'critical',
        'description': 'Payment failure rate exceeds 10%'
    },
    'high_latency': {
        'condition': 'payment_latency_p99 > 10',
        'severity': 'warning',
        'description': 'P99 latency exceeds 10 seconds'
    },
    'chargeback_spike': {
        'condition': 'chargebacks_today > 5',
        'severity': 'critical',
        'description': 'Multiple chargebacks received today'
    }
}
```

---

## 🎯 Key Takeaways

1. **Always use idempotency keys** - Networks fail, requests retry
2. **Handle timeouts as unknown state** - Don't assume failure
3. **Multi-layer duplicate prevention** - Frontend + backend + gateway
4. **Graceful failure messages** - Never reveal fraud details
5. **Proactive refunds** - Cheaper than chargebacks
6. **Circuit breakers** - Fail fast when dependencies are down
7. **Monitor everything** - You can't fix what you can't see

---

**Next:** [05-common-mistakes.md](05-common-mistakes.md) - Learn from others' errors
