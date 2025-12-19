# 🏗️ Architecture Deep Dive: Component Breakdown

> Understanding why each piece exists and how they work together

## Overview

A payment system isn't just one thing—it's an orchestra of specialized components. Let's understand each one deeply.

---

## 🎨 Component 1: Checkout UI

### What It Does
The frontend interface where customers enter payment information.

### Why It Exists
- Provides a user-friendly payment experience
- Collects card data securely (via gateway's iframe)
- Handles form validation and error display
- Manages the payment flow state (loading, success, error)

### Architecture Patterns

```
┌─────────────────────────────────────────────────────────────────────┐
│                    CHECKOUT UI ARCHITECTURE                          │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │  YOUR CHECKOUT PAGE (e.g., checkout.html)                   │   │
│  ├─────────────────────────────────────────────────────────────┤   │
│  │                                                             │   │
│  │  ┌─────────────────────────────────────────────────────┐   │   │
│  │  │  Order Summary                                       │   │   │
│  │  │  ─────────────                                       │   │   │
│  │  │  Product: Widget Pro           $79.00                │   │   │
│  │  │  Shipping:                     $10.00                │   │   │
│  │  │  Tax:                          $10.00                │   │   │
│  │  │  ──────────────────────────────────────             │   │   │
│  │  │  Total:                        $99.00                │   │   │
│  │  └─────────────────────────────────────────────────────┘   │   │
│  │                                                             │   │
│  │  ┌─────────────────────────────────────────────────────┐   │   │
│  │  │  Payment Details                                     │   │   │
│  │  │  ───────────────                                     │   │   │
│  │  │                                                       │   │   │
│  │  │  ╔═══════════════════════════════════════════════╗   │   │
│  │  │  ║  🔒 SECURE IFRAME (from Payment Gateway)      ║   │   │
│  │  │  ║                                               ║   │   │
│  │  │  ║  Card Number: [4242 4242 4242 4242]          ║   │   │
│  │  │  ║  Expiry:      [12/27]    CVV: [123]          ║   │   │
│  │  │  ║                                               ║   │   │
│  │  │  ║  This iframe is served from gateway.com       ║   │   │
│  │  │  ║  Card data NEVER touches your domain          ║   │   │
│  │  │  ╚═══════════════════════════════════════════════╝   │   │
│  │  │                                                       │   │
│  │  │  [        Pay $99.00 Securely        ]               │   │
│  │  │                                                       │   │
│  │  └─────────────────────────────────────────────────────┘   │   │
│  │                                                             │   │
│  └─────────────────────────────────────────────────────────────┘   │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

### The Iframe Pattern (Critical for PCI Compliance)

```javascript
// ✅ CORRECT: Card data stays in gateway's iframe
// Your page loads gateway's JavaScript SDK
<script src="https://gateway.com/v1/sdk.js"></script>

// Gateway creates a secure iframe on your page
const cardElement = gateway.elements.create('card');
cardElement.mount('#card-element');

// When submitted, card data goes directly to gateway
const { token } = await gateway.createToken(cardElement);
// You only receive a token, never the card number

// ❌ WRONG: Never do this
<input type="text" id="card-number" name="card">  // Card data touches your server!
```

### Error Handling UX

```
┌─────────────────────────────────────────────────────┐
│  Error States to Handle:                            │
├─────────────────────────────────────────────────────┤
│                                                     │
│  Validation Errors (before submission):             │
│  • Invalid card number format                       │
│  • Expired date in past                             │
│  • CVV wrong length                                 │
│                                                     │
│  Processing Errors (during submission):             │
│  • Network timeout                                  │
│  • Gateway unavailable                              │
│                                                     │
│  Decline Errors (from bank):                        │
│  • Insufficient funds                               │
│  • Card declined                                    │
│  • Fraud suspected                                  │
│                                                     │
│  Best Practice: Show friendly messages              │
│  ❌ "Error code 51: Insufficient funds"             │
│  ✅ "Payment declined. Please try another card."   │
│                                                     │
└─────────────────────────────────────────────────────┘
```

---

## 🔌 Component 2: Payment API (Your Backend)

### What It Does
Your server-side code that orchestrates the payment process.

### Why It Exists
- Validates orders and amounts (prevents tampering)
- Securely stores API keys (never in frontend)
- Creates payment records in your database
- Handles business logic (inventory, fulfillment)
- Processes webhooks from payment gateway

### Key Endpoints

```python
# Your Merchant Backend API

# Endpoint 1: Create Payment Intent
# Called when customer is ready to pay
POST /api/payments/create-intent
{
    "order_id": "ord_123",
    "amount": 9900,           # Always in cents!
    "currency": "usd"
}
Response: {
    "client_secret": "pi_abc_secret_xyz",  # For frontend
    "payment_id": "pay_123"
}

# Endpoint 2: Confirm Payment
# Called after frontend tokenizes card
POST /api/payments/confirm
{
    "payment_id": "pay_123",
    "token": "tok_abc123",
    "idempotency_key": "order_ord_123_v1"
}
Response: {
    "status": "succeeded",
    "charge_id": "ch_xyz"
}

# Endpoint 3: Webhook Handler
# Called by payment gateway for async events
POST /api/webhooks/payment-gateway
Headers: {
    "X-Signature": "sha256=abc123..."
}
Body: {
    "event": "charge.succeeded",
    "data": { ... }
}
```

### Critical Security Patterns

```python
class PaymentService:
    """
    Secure payment processing patterns
    """
    
    def create_charge(self, order_id: str, token: str) -> ChargeResult:
        # PATTERN 1: Always validate amount server-side
        order = self.db.get_order(order_id)
        if not order:
            raise NotFoundError("Order not found")
        
        # PATTERN 2: Never trust frontend amount
        # Calculate amount from your source of truth
        amount = order.calculate_total()  # Your DB, not frontend
        
        # PATTERN 3: Use idempotency keys
        idempotency_key = f"charge_{order_id}_{order.version}"
        
        # PATTERN 4: Log extensively (but not card data!)
        logger.info(f"Creating charge", extra={
            "order_id": order_id,
            "amount": amount,
            "idempotency_key": idempotency_key
            # NEVER log: token details, card numbers
        })
        
        # PATTERN 5: Handle all possible outcomes
        try:
            result = self.gateway.create_charge(
                token=token,
                amount=amount,
                idempotency_key=idempotency_key
            )
            
            if result.status == "succeeded":
                order.mark_paid(result.charge_id)
                self.events.emit("order.paid", order)
            elif result.status == "requires_action":
                # 3D Secure needed
                return ChargeResult(
                    status="requires_action",
                    action_url=result.redirect_url
                )
            else:
                order.mark_payment_failed(result.error_code)
                
        except GatewayTimeoutError:
            # PATTERN 6: Safe retry with same idempotency key
            return self.create_charge(order_id, token)  # Safe!
            
        except GatewayError as e:
            logger.error(f"Gateway error: {e}")
            raise PaymentError("Payment processing failed")
```

---

## 🔐 Component 3: Tokenization Service

### What It Does
Converts sensitive card data into secure, non-sensitive tokens.

### Why It Exists
- Removes card data from your scope (PCI compliance)
- Enables safe storage for recurring payments
- Isolates sensitive data handling to specialists

### How It Works Internally

```
┌─────────────────────────────────────────────────────────────────────┐
│                    TOKENIZATION SERVICE                              │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│   INPUT                     PROCESS                   OUTPUT        │
│   ─────                     ───────                   ──────        │
│                                                                     │
│   Card: 4242424242424242    ┌─────────────────────┐                │
│   Exp:  12/27               │ 1. Validate format  │   Token:       │
│   CVV:  123                 │ 2. Check Luhn algo  │   tok_xK3mN9   │
│   Name: John Doe            │ 3. Encrypt card     │                │
│                             │ 4. Store in vault   │   Expires:     │
│                             │ 5. Generate token   │   in 15 mins   │
│                             │ 6. Map token→card   │                │
│                             └─────────────────────┘                │
│                                                                     │
│   Token Properties:                                                 │
│   ─────────────────                                                 │
│   • Randomly generated (no relation to card number)                 │
│   • Short-lived for one-time payments                              │
│   • Long-lived version for saved cards                             │
│   • Scoped to specific merchant                                    │
│   • Revocable                                                       │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

### Token Types

```python
# One-Time Token (for single payment)
{
    "token": "tok_1Abc2Def3",
    "type": "one_time",
    "expires_at": "2024-01-15T10:30:00Z",  # ~15 minutes
    "card": {
        "last4": "4242",
        "brand": "visa",
        "exp_month": 12,
        "exp_year": 2027
    }
}

# Reusable Token (for saved cards/subscriptions)
{
    "token": "pm_card_abc123",
    "type": "reusable",
    "customer_id": "cus_xyz",
    "card": {
        "last4": "4242",
        "brand": "visa",
        "exp_month": 12,
        "exp_year": 2027,
        "fingerprint": "fp_abc"  # For duplicate detection
    }
}
```

---

## ⚖️ Component 4: Authorization Engine

### What It Does
Decides whether to approve or decline a transaction (on the gateway side before sending to banks).

### Why It Exists
- Pre-screens transactions before bank costs
- Applies merchant-specific rules
- Detects obvious fraud patterns
- Manages velocity limits

### Authorization Flow

```
┌─────────────────────────────────────────────────────────────────────┐
│                    AUTHORIZATION ENGINE                              │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│   Incoming Request                                                  │
│        │                                                            │
│        ▼                                                            │
│   ┌─────────────────────────────────────────────────────────────┐  │
│   │  STEP 1: Token Validation                                   │  │
│   │  ───────────────────────                                    │  │
│   │  • Is token valid and not expired?                          │  │
│   │  • Is token for this merchant?                              │  │
│   │  • Has token been used? (if one-time)                       │  │
│   └─────────────────────────────────────────────────────────────┘  │
│        │                                                            │
│        ▼                                                            │
│   ┌─────────────────────────────────────────────────────────────┐  │
│   │  STEP 2: Amount Validation                                  │  │
│   │  ─────────────────────────                                  │  │
│   │  • Is amount positive?                                      │  │
│   │  • Is amount within merchant limits?                        │  │
│   │  • Is currency supported?                                   │  │
│   └─────────────────────────────────────────────────────────────┘  │
│        │                                                            │
│        ▼                                                            │
│   ┌─────────────────────────────────────────────────────────────┐  │
│   │  STEP 3: Fraud Screening                                    │  │
│   │  ──────────────────────                                     │  │
│   │  • Velocity check (too many attempts?)                      │  │
│   │  • Geographic anomalies                                     │  │
│   │  • Device fingerprint checks                                │  │
│   │  • Risk score calculation                                   │  │
│   └─────────────────────────────────────────────────────────────┘  │
│        │                                                            │
│        ▼                                                            │
│   ┌─────────────────────────────────────────────────────────────┐  │
│   │  STEP 4: Merchant Rules                                     │  │
│   │  ─────────────────────                                      │  │
│   │  • Blocked countries?                                       │  │
│   │  • Blocked BINs?                                            │  │
│   │  • Required 3D Secure?                                      │  │
│   └─────────────────────────────────────────────────────────────┘  │
│        │                                                            │
│        ▼                                                            │
│   ┌─────────────────────────────────────────────────────────────┐  │
│   │  STEP 5: Send to Bank Network                               │  │
│   │  ────────────────────────                                   │  │
│   │  • Format ISO 8583 message                                  │  │
│   │  • Route to acquiring bank                                  │  │
│   │  • Wait for response                                        │  │
│   └─────────────────────────────────────────────────────────────┘  │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

### Authorization vs Capture Logic

```python
class AuthorizationEngine:
    
    def authorize(self, request: AuthRequest) -> AuthResponse:
        """
        AUTHORIZE: "Can this card pay this amount?"
        Places a hold on funds, doesn't transfer them.
        """
        # Validate and screen
        self._validate_token(request.token)
        self._check_fraud(request)
        
        # Send to bank network
        bank_response = self.bank_network.authorize(
            card=self._decrypt_card(request.token),
            amount=request.amount,
            merchant_id=request.merchant_id
        )
        
        if bank_response.approved:
            # Create authorization record
            auth = Authorization(
                id=generate_id("auth"),
                amount=request.amount,
                auth_code=bank_response.auth_code,
                status="authorized",
                expires_at=now() + timedelta(days=7),  # Auths expire!
                captured=False
            )
            self.db.save(auth)
            
        return AuthResponse(
            authorized=bank_response.approved,
            authorization_id=auth.id,
            auth_code=bank_response.auth_code
        )
    
    def capture(self, authorization_id: str, amount: int = None) -> CaptureResponse:
        """
        CAPTURE: "Actually take the money"
        Can capture full or partial amount.
        """
        auth = self.db.get(authorization_id)
        
        # Can't capture expired auths
        if auth.expires_at < now():
            raise AuthorizationExpiredError()
        
        # Can't capture more than authorized
        capture_amount = amount or auth.amount
        if capture_amount > auth.amount:
            raise InvalidCaptureAmountError()
        
        # Send capture to bank
        result = self.bank_network.capture(
            auth_code=auth.auth_code,
            amount=capture_amount
        )
        
        auth.status = "captured"
        auth.captured_amount = capture_amount
        self.db.save(auth)
        
        return CaptureResponse(success=True)
```

---

## 🔔 Component 5: Webhook System

### What It Does
Sends real-time notifications about payment events to merchants.

### Why It Exists
- API responses can fail (network issues)
- Some events are asynchronous (chargebacks, refunds)
- Provides reliable event delivery with retries
- Enables event-driven architectures

### Webhook Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                    WEBHOOK SYSTEM ARCHITECTURE                       │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│   Payment Gateway                       Your Merchant Server        │
│   ───────────────                       ────────────────────        │
│                                                                     │
│   ┌─────────────────┐                                               │
│   │  Event Occurs   │                                               │
│   │  (charge.ok)    │                                               │
│   └────────┬────────┘                                               │
│            │                                                        │
│            ▼                                                        │
│   ┌─────────────────┐                                               │
│   │  Event Queue    │    Events are queued for reliable delivery    │
│   │  ┌───┬───┬───┐  │                                               │
│   │  │ 1 │ 2 │ 3 │  │                                               │
│   │  └───┴───┴───┘  │                                               │
│   └────────┬────────┘                                               │
│            │                                                        │
│            ▼                                                        │
│   ┌─────────────────┐        HTTPS POST              ┌───────────┐ │
│   │  Webhook        │ ─────────────────────────────> │  /webhook │ │
│   │  Dispatcher     │                                │  endpoint │ │
│   │                 │ <───────────────────────────── │           │ │
│   │                 │        200 OK (ACK)            │           │ │
│   └────────┬────────┘                                └───────────┘ │
│            │                                                        │
│            │  If no 2xx response:                                   │
│            │  ┌─────────────────────────────────────────────────┐  │
│            │  │  RETRY SCHEDULE                                 │  │
│            │  │  ─────────────                                  │  │
│            │  │  Attempt 1: Immediate                           │  │
│            │  │  Attempt 2: 5 minutes                           │  │
│            │  │  Attempt 3: 30 minutes                          │  │
│            │  │  Attempt 4: 2 hours                             │  │
│            │  │  Attempt 5: 24 hours                            │  │
│            │  │  After 5 failures: Alert merchant, pause        │  │
│            │  └─────────────────────────────────────────────────┘  │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

### Webhook Payload Structure

```python
# Example webhook payloads

# Charge Succeeded
{
    "id": "evt_1abc2def",
    "type": "charge.succeeded",
    "created": 1703001234,
    "data": {
        "object": {
            "id": "ch_xyz",
            "amount": 9900,
            "currency": "usd",
            "status": "succeeded",
            "metadata": {
                "order_id": "ord_123"
            }
        }
    }
}

# Charge Failed
{
    "id": "evt_2def3ghi",
    "type": "charge.failed",
    "data": {
        "object": {
            "id": "ch_abc",
            "amount": 9900,
            "failure_code": "card_declined",
            "failure_message": "Your card was declined."
        }
    }
}

# Dispute Created (Chargeback!)
{
    "id": "evt_3ghi4jkl",
    "type": "dispute.created",
    "data": {
        "object": {
            "id": "dp_xyz",
            "charge": "ch_original",
            "amount": 9900,
            "reason": "fraudulent",
            "status": "needs_response",
            "evidence_due_by": 1704000000
        }
    }
}
```

### Secure Webhook Handler

```python
import hmac
import hashlib

class WebhookHandler:
    def __init__(self, webhook_secret: str):
        self.webhook_secret = webhook_secret
    
    def handle(self, request) -> Response:
        # STEP 1: Verify signature (CRITICAL!)
        signature = request.headers.get('X-Gateway-Signature')
        if not self._verify_signature(request.body, signature):
            # Log security event but don't reveal details
            logger.warning("Invalid webhook signature")
            return Response(status=401)
        
        # STEP 2: Parse event
        event = json.loads(request.body)
        
        # STEP 3: Idempotency - have we processed this event?
        if self.db.event_exists(event['id']):
            # Already processed, return success
            return Response(status=200)
        
        # STEP 4: Process based on event type
        try:
            if event['type'] == 'charge.succeeded':
                self._handle_charge_succeeded(event['data']['object'])
            elif event['type'] == 'charge.failed':
                self._handle_charge_failed(event['data']['object'])
            elif event['type'] == 'dispute.created':
                self._handle_dispute(event['data']['object'])
            
            # STEP 5: Mark event as processed
            self.db.save_event(event['id'])
            
            # STEP 6: Return 200 to acknowledge
            return Response(status=200)
            
        except Exception as e:
            # Return 500 so gateway will retry
            logger.error(f"Webhook processing failed: {e}")
            return Response(status=500)
    
    def _verify_signature(self, payload: bytes, signature: str) -> bool:
        """
        Verify the webhook came from the real gateway.
        Prevents attackers from sending fake events.
        """
        expected = hmac.new(
            self.webhook_secret.encode(),
            payload,
            hashlib.sha256
        ).hexdigest()
        
        return hmac.compare_digest(f"sha256={expected}", signature)
```

---

## 🔄 Component 6: Idempotency Layer

### What It Does
Ensures operations produce the same result even if called multiple times.

### Why It Exists
- Networks are unreliable (timeouts, retries)
- Prevents double-charging customers
- Enables safe automatic retries
- Critical for financial operations

### How It Works

```
┌─────────────────────────────────────────────────────────────────────┐
│                    IDEMPOTENCY FLOW                                  │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│   Request 1: Create charge, key="abc123"                            │
│        │                                                            │
│        ▼                                                            │
│   ┌─────────────────────────────────────────────────────────────┐  │
│   │  Check: Have we seen key "abc123"?                          │  │
│   │  Result: NO (first time)                                    │  │
│   │  Action: Process charge, store result with key              │  │
│   └─────────────────────────────────────────────────────────────┘  │
│        │                                                            │
│        ▼                                                            │
│   Response: {status: "succeeded", charge_id: "ch_xyz"}              │
│                                                                     │
│   ════════════════════════════════════════════════════════════════  │
│                                                                     │
│   Request 2: Create charge, key="abc123" (retry due to timeout)    │
│        │                                                            │
│        ▼                                                            │
│   ┌─────────────────────────────────────────────────────────────┐  │
│   │  Check: Have we seen key "abc123"?                          │  │
│   │  Result: YES (already processed)                            │  │
│   │  Action: Return stored result WITHOUT processing again      │  │
│   └─────────────────────────────────────────────────────────────┘  │
│        │                                                            │
│        ▼                                                            │
│   Response: {status: "succeeded", charge_id: "ch_xyz"} (same!)     │
│                                                                     │
│   Customer charged exactly ONCE ✓                                   │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

### Implementation

```python
class IdempotencyService:
    """
    Idempotency implementation with proper locking
    """
    
    def __init__(self, redis_client, ttl_hours=24):
        self.redis = redis_client
        self.ttl = ttl_hours * 3600
    
    def execute_once(
        self, 
        idempotency_key: str, 
        operation: Callable
    ) -> Any:
        """
        Execute an operation exactly once per idempotency key.
        """
        cache_key = f"idempotency:{idempotency_key}"
        
        # Try to get existing result
        existing = self.redis.get(cache_key)
        if existing:
            return json.loads(existing)
        
        # Acquire lock to prevent race conditions
        lock_key = f"lock:{cache_key}"
        lock = self.redis.lock(lock_key, timeout=30)
        
        try:
            if lock.acquire(blocking=True, blocking_timeout=5):
                # Double-check after acquiring lock
                existing = self.redis.get(cache_key)
                if existing:
                    return json.loads(existing)
                
                # Execute the operation
                result = operation()
                
                # Store result for future requests
                self.redis.setex(
                    cache_key, 
                    self.ttl, 
                    json.dumps(result)
                )
                
                return result
            else:
                raise ConcurrencyError("Could not acquire lock")
        finally:
            lock.release()
    
    @staticmethod
    def generate_key(order_id: str, action: str) -> str:
        """
        Generate a good idempotency key.
        Should be deterministic for the same logical operation.
        """
        return f"{action}:{order_id}:{hash_of_amount_and_details}"
```

---

## 📊 Complete System Diagram

```
┌────────────────────────────────────────────────────────────────────────────┐
│                     COMPLETE PAYMENT SYSTEM ARCHITECTURE                    │
├────────────────────────────────────────────────────────────────────────────┤
│                                                                            │
│  ┌──────────────────────────────────────────────────────────────────────┐ │
│  │                         MERCHANT DOMAIN                               │ │
│  │  ┌─────────────┐    ┌─────────────┐    ┌─────────────────────────┐  │ │
│  │  │  Checkout   │───>│  Merchant   │───>│  Order & Payment       │  │ │
│  │  │  UI         │    │  Backend    │    │  Database              │  │ │
│  │  │             │    │             │<───│                        │  │ │
│  │  │  (iframe)───────────────┐      │    └─────────────────────────┘  │ │
│  │  └─────────────┘    │      │      │                                  │ │
│  │                     │      │      │    ┌─────────────────────────┐  │ │
│  │                     │      │      │───>│  Webhook Handler        │  │ │
│  │                     │      │      │    │  (async events)         │  │ │
│  │                     │      │      │    └─────────────────────────┘  │ │
│  └─────────────────────│──────│──────│──────────────────────────────────┘ │
│                        │      │      │                                     │
│  ══════════════════════│══════│══════│═════════════════════════════════   │
│                        │      │      │                                     │
│  ┌─────────────────────│──────│──────│──────────────────────────────────┐ │
│  │                     │  PAYMENT GATEWAY DOMAIN                        │ │
│  │                     ▼      │      ▼                                  │ │
│  │  ┌─────────────────────────────────────┐                            │ │
│  │  │  Gateway API                        │                            │ │
│  │  │  ┌─────────────┐  ┌──────────────┐  │    ┌──────────────────┐   │ │
│  │  │  │ Tokenizer   │  │ Idempotency  │  │───>│  Webhook         │   │ │
│  │  │  │ Service     │  │ Service      │  │    │  Dispatcher      │   │ │
│  │  │  └─────────────┘  └──────────────┘  │    └──────────────────┘   │ │
│  │  │                                     │                            │ │
│  │  │  ┌─────────────┐  ┌──────────────┐  │                            │ │
│  │  │  │ Auth        │  │ Fraud        │  │                            │ │
│  │  │  │ Engine      │  │ Detection    │  │                            │ │
│  │  │  └─────────────┘  └──────────────┘  │                            │ │
│  │  └─────────────────────────────────────┘                            │ │
│  │                        │                                             │ │
│  │  ┌─────────────────────────────────────┐                            │ │
│  │  │  Card Vault (HSM-backed)           │                            │ │
│  │  │  Encrypted card storage            │                            │ │
│  │  └─────────────────────────────────────┘                            │ │
│  └──────────────────────────│───────────────────────────────────────────┘ │
│                             │                                              │
│  ═══════════════════════════│══════════════════════════════════════════   │
│                             │                                              │
│  ┌──────────────────────────│───────────────────────────────────────────┐ │
│  │                     BANKING NETWORK                                   │ │
│  │                          ▼                                            │ │
│  │  ┌─────────────┐    ┌─────────────┐    ┌─────────────────────────┐  │ │
│  │  │  Acquiring  │───>│  Card       │───>│  Issuing Bank           │  │ │
│  │  │  Bank       │    │  Network    │    │  (Approves/Declines)    │  │ │
│  │  │             │<───│  (Visa/MC)  │<───│                         │  │ │
│  │  └─────────────┘    └─────────────┘    └─────────────────────────┘  │ │
│  └──────────────────────────────────────────────────────────────────────┘ │
│                                                                            │
└────────────────────────────────────────────────────────────────────────────┘
```

---

## 🎯 Key Takeaways

| Component | Responsibility | Why It's Separate |
|-----------|---------------|-------------------|
| Checkout UI | User experience, card collection | Frontend/UX concerns |
| Payment API | Business logic, orchestration | Your core business |
| Tokenization | Secure card handling | PCI isolation |
| Auth Engine | Transaction decisions | Complex rules |
| Webhooks | Event delivery | Reliability, async |
| Idempotency | Duplicate prevention | Safety |

---

**Next:** [03-security-and-pci-dss.md](03-security-and-pci-dss.md) - Deep dive into security
