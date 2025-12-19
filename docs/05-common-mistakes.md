# ⚠️ Common Mistakes: What Junior Developers Get Wrong

> Learn from the expensive mistakes others have made so you don't repeat them

## Why This Matters

Payment mistakes are expensive. A single bug can result in:
- Customers charged twice
- Lost revenue from failed valid payments
- Chargebacks and fraud losses
- PCI compliance violations and fines
- Lost customer trust

Let's learn what NOT to do.

---

## 💳 Mistake #1: Handling Card Data Directly

### The Mistake

```javascript
// ❌ CATASTROPHICALLY WRONG
<form action="/api/pay" method="POST">
    <input type="text" name="card_number" placeholder="Card Number">
    <input type="text" name="cvv" placeholder="CVV">
    <input type="text" name="expiry" placeholder="MM/YY">
    <button type="submit">Pay</button>
</form>

// Backend receives raw card data
app.post('/api/pay', (req, res) => {
    const { card_number, cvv, expiry } = req.body;
    // Now YOU are responsible for PCI-DSS Level 1 compliance!
    // That's $100,000+ in audits, and massive liability
});
```

### Why It's Wrong

```
┌─────────────────────────────────────────────────────────────────────┐
│                    PCI SCOPE EXPLOSION                               │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  When card data touches your server:                                │
│                                                                     │
│  • Your ENTIRE server is in PCI scope                               │
│  • Every system that server connects to is in scope                 │
│  • Your database is in scope                                        │
│  • Your logs are in scope (and probably contain card data now!)    │
│  • Your backups are in scope                                        │
│  • Your developers' machines are in scope                           │
│  • You need quarterly security scans                                │
│  • You need annual penetration testing                              │
│  • You need a QSA audit ($50k-100k+)                               │
│                                                                     │
│  If breached: Fines up to $500k, lawsuits, and you're done.       │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

### The Right Way

```javascript
// ✅ CORRECT - Card data never touches your server
// Load payment gateway's SDK
<script src="https://js.stripe.com/v3/"></script>

<div id="card-element">
    <!-- Gateway's secure iframe loads here -->
</div>
<button id="pay-button">Pay</button>

<script>
const stripe = Stripe('pk_live_...');  // Public key only
const elements = stripe.elements();
const cardElement = elements.create('card');
cardElement.mount('#card-element');

document.getElementById('pay-button').addEventListener('click', async () => {
    // Card data goes directly to Stripe, returns a token
    const {token, error} = await stripe.createToken(cardElement);
    
    if (token) {
        // Only the token goes to your backend - never the card number
        await fetch('/api/pay', {
            method: 'POST',
            body: JSON.stringify({ 
                token: token.id,      // Safe to handle
                order_id: 'ord_123'
            })
        });
    }
});
</script>
```

---

## 💰 Mistake #2: Trusting Frontend Amount

### The Mistake

```javascript
// Frontend
const payButton = document.querySelector('#pay');
payButton.addEventListener('click', () => {
    fetch('/api/charge', {
        method: 'POST',
        body: JSON.stringify({
            token: 'tok_xxx',
            amount: document.querySelector('#total').textContent,  // ❌ $99.99
            order_id: 'ord_123'
        })
    });
});

// Backend - THE MISTAKE
app.post('/api/charge', async (req, res) => {
    const { token, amount, order_id } = req.body;
    
    // ❌ NEVER trust the frontend amount!
    // Attacker can modify this to $0.01
    const charge = await stripe.charges.create({
        source: token,
        amount: amount,  // ❌ This came from the client!
    });
});
```

### What Attackers Do

```
┌─────────────────────────────────────────────────────────────────────┐
│                    THE AMOUNT MANIPULATION ATTACK                    │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  1. Attacker adds $500 item to cart                                │
│                                                                     │
│  2. At checkout, attacker opens browser DevTools                    │
│                                                                     │
│  3. Attacker modifies the request:                                  │
│     Before: { "amount": 50000, "order_id": "123" }                 │
│     After:  { "amount": 1, "order_id": "123" }                     │
│                                                                     │
│  4. Server trusts the amount and charges $0.01                     │
│                                                                     │
│  5. Attacker gets $500 item for $0.01                              │
│                                                                     │
│  6. You lose $499.99                                                │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

### The Right Way

```python
# ✅ CORRECT - Always calculate amount server-side
@app.post('/api/charge')
def create_charge(request):
    order_id = request.json['order_id']
    token = request.json['token']
    # Ignore any 'amount' from the client!
    
    # Get order from YOUR database
    order = db.get_order(order_id)
    if not order:
        raise NotFoundError("Order not found")
    
    # Calculate amount from YOUR data
    amount = order.calculate_total()  # Items + shipping + tax
    
    # Verify order hasn't been paid
    if order.status == 'paid':
        raise ConflictError("Order already paid")
    
    # Now charge the CORRECT amount
    charge = gateway.charge(
        token=token,
        amount=amount,  # From YOUR database, not client
        metadata={'order_id': order_id}
    )
    
    return {'success': True}
```

---

## 🔄 Mistake #3: Missing Idempotency Keys

### The Mistake

```python
# ❌ WRONG - No idempotency key
def process_payment(order_id, token):
    order = db.get_order(order_id)
    
    # No idempotency key!
    charge = gateway.charge(
        token=token,
        amount=order.total
    )
    
    order.mark_paid(charge['id'])
    return charge
```

### What Goes Wrong

```
┌─────────────────────────────────────────────────────────────────────┐
│                    THE DOUBLE-CHARGE DISASTER                        │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  Timeline:                                                          │
│                                                                     │
│  T+0s:    Request 1 sent to gateway                                │
│  T+10s:   Request 1 still processing (slow)                        │
│  T+15s:   Your server times out, thinks it failed                  │
│  T+15s:   Your code retries: Request 2 sent                        │
│  T+18s:   Request 1 succeeds at gateway → Charge #1                │
│  T+20s:   Request 2 succeeds at gateway → Charge #2                │
│                                                                     │
│  Result: Customer charged twice!                                    │
│                                                                     │
│  Customer sees:                                                     │
│  - Transaction 1: $99.99                                            │
│  - Transaction 2: $99.99                                            │
│                                                                     │
│  Now you need to:                                                   │
│  - Refund one charge                                                │
│  - Apologize to customer                                            │
│  - Hope they don't chargeback both                                  │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

### The Right Way

```python
# ✅ CORRECT - Always use idempotency keys
def process_payment(order_id, token):
    order = db.get_order(order_id)
    
    # Deterministic key based on order
    idempotency_key = f"charge_order_{order_id}_v{order.version}"
    
    # With idempotency key, retries return same result
    charge = gateway.charge(
        token=token,
        amount=order.total,
        idempotency_key=idempotency_key  # ✅ Safe to retry!
    )
    
    order.mark_paid(charge['id'])
    return charge
```

---

## 📝 Mistake #4: Logging Sensitive Data

### The Mistake

```python
# ❌ CATASTROPHICALLY WRONG
import logging
logger = logging.getLogger(__name__)

def process_payment(request):
    # This logs the ENTIRE request including card data!
    logger.info(f"Processing payment: {request}")
    
    # This logs card details!
    logger.debug(f"Card: {request['card_number']}, CVV: {request['cvv']}")
    
    # This might log tokens (less bad but still wrong)
    logger.info(f"Token details: {token}")
```

### What Goes Wrong

```
┌─────────────────────────────────────────────────────────────────────┐
│                    LOG EXPOSURE NIGHTMARE                            │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  Your logs now contain:                                             │
│  2024-01-15 10:30:45 INFO Processing payment:                      │
│  {'card_number': '4242424242424242', 'cvv': '123', ...}            │
│                                                                     │
│  These logs might be:                                               │
│  • Stored in plain text                                             │
│  • Shipped to log aggregators (Datadog, Splunk)                    │
│  • Backed up without encryption                                     │
│  • Accessible to all developers                                     │
│  • Retained for years                                               │
│  • Exposed in a breach                                              │
│                                                                     │
│  If audited for PCI: Immediate failure                              │
│  If breached: Massive liability, fines, card brand penalties       │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

### The Right Way

```python
# ✅ CORRECT - Never log sensitive data
import logging
logger = logging.getLogger(__name__)

# Define what's safe to log
SAFE_FIELDS = {'order_id', 'amount', 'currency', 'status', 'created_at'}

def safe_log_payment(payment_data: dict) -> dict:
    """Extract only safe fields for logging."""
    return {k: v for k, v in payment_data.items() if k in SAFE_FIELDS}

def process_payment(order_id: str, token: str):
    # ✅ Log safe identifiers only
    logger.info(f"Processing payment for order {order_id}")
    
    result = gateway.charge(token=token, amount=amount)
    
    # ✅ Mask sensitive parts
    logger.info(f"Payment result: {safe_log_payment(result)}")
    
    # ✅ If you must reference card, use last 4 only
    logger.info(f"Charged card ending in {result['last4']}")
    
    return result

# Configure log scrubbing as safety net
class SensitiveDataFilter(logging.Filter):
    """Scrub any accidentally logged sensitive data."""
    
    PATTERNS = [
        (r'\b\d{16}\b', '[CARD REDACTED]'),           # Card numbers
        (r'\b\d{3,4}\b(?=.*cvv)', '[CVV REDACTED]'),  # CVV
        (r'tok_[a-zA-Z0-9]+', '[TOKEN REDACTED]'),    # Tokens
    ]
    
    def filter(self, record):
        for pattern, replacement in self.PATTERNS:
            record.msg = re.sub(pattern, replacement, str(record.msg))
        return True
```

---

## 🔐 Mistake #5: Exposing API Keys

### The Mistake

```javascript
// ❌ WRONG - Secret key in frontend code
const stripe = require('stripe')('sk_live_abc123xyz...');

// ❌ WRONG - Key in public repository
// config.js (committed to git)
const STRIPE_SECRET_KEY = 'sk_live_abc123xyz...';

// ❌ WRONG - Key in client-side code
fetch('/api/charge', {
    headers: {
        'Authorization': 'Bearer sk_live_abc123xyz...'  // Visible in browser!
    }
});
```

### What Goes Wrong

```
┌─────────────────────────────────────────────────────────────────────┐
│                    API KEY EXPOSURE ATTACK                           │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  When your secret key is exposed:                                   │
│                                                                     │
│  1. Attacker finds key (GitHub search, browser DevTools, etc.)     │
│                                                                     │
│  2. Attacker can:                                                   │
│     • Charge any card on your account                              │
│     • Issue refunds to themselves                                  │
│     • Access all your customer data                                │
│     • View all your transaction history                            │
│     • Modify your account settings                                 │
│                                                                     │
│  3. You get:                                                        │
│     • Fraudulent charges on your account                           │
│     • Unauthorized refunds (money gone)                            │
│     • Data breach notification requirements                        │
│     • Account termination                                          │
│                                                                     │
│  GitHub constantly scans for exposed keys - if found, Stripe       │
│  immediately revokes it. But attackers scan faster.                │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

### The Right Way

```python
# ✅ CORRECT - Environment variables
import os

# Never hardcode keys
STRIPE_SECRET_KEY = os.environ.get('STRIPE_SECRET_KEY')
if not STRIPE_SECRET_KEY:
    raise EnvironmentError("STRIPE_SECRET_KEY not configured")

# Use different keys for different environments
STRIPE_KEY = os.environ.get(
    'STRIPE_SECRET_KEY_LIVE' if IS_PRODUCTION else 'STRIPE_SECRET_KEY_TEST'
)

# For frontend, only use publishable keys
# config.js (client-side)
const STRIPE_PUBLISHABLE_KEY = 'pk_live_xxx';  # ✅ Safe for frontend
```

```yaml
# .gitignore - Never commit secrets
.env
.env.*
secrets.yml
**/config/secrets.*
```

```yaml
# .env.example (commit this, not .env)
STRIPE_SECRET_KEY=sk_test_replace_me
STRIPE_PUBLISHABLE_KEY=pk_test_replace_me
WEBHOOK_SECRET=whsec_replace_me
```

---

## 🎣 Mistake #6: Not Verifying Webhooks

### The Mistake

```python
# ❌ WRONG - No signature verification
@app.post('/webhooks/stripe')
def handle_webhook(request):
    event = request.json
    
    # Blindly trust the webhook is from Stripe
    if event['type'] == 'charge.succeeded':
        order_id = event['data']['object']['metadata']['order_id']
        mark_order_paid(order_id)  # ❌ Attacker can fake this!
    
    return {'received': True}
```

### What Goes Wrong

```
┌─────────────────────────────────────────────────────────────────────┐
│                    WEBHOOK SPOOFING ATTACK                           │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  Attacker sends fake webhook:                                       │
│                                                                     │
│  POST /webhooks/stripe                                              │
│  Content-Type: application/json                                     │
│                                                                     │
│  {                                                                  │
│      "type": "charge.succeeded",                                    │
│      "data": {                                                      │
│          "object": {                                                │
│              "id": "ch_fake",                                       │
│              "amount": 99900,                                       │
│              "metadata": {"order_id": "expensive_item"}             │
│          }                                                          │
│      }                                                              │
│  }                                                                  │
│                                                                     │
│  Your system:                                                       │
│  1. Receives fake webhook                                           │
│  2. Marks order as paid                                             │
│  3. Ships $999 item                                                 │
│  4. Attacker never actually paid!                                   │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

### The Right Way

```python
import hmac
import hashlib

# ✅ CORRECT - Always verify webhook signatures
@app.post('/webhooks/stripe')
def handle_webhook(request):
    payload = request.body
    signature = request.headers.get('Stripe-Signature')
    
    # Verify the webhook is from Stripe
    try:
        event = verify_webhook_signature(
            payload=payload,
            signature=signature,
            webhook_secret=WEBHOOK_SECRET
        )
    except SignatureVerificationError:
        # Log for security monitoring but don't reveal details
        logger.warning("Invalid webhook signature received")
        return {'error': 'Invalid signature'}, 401
    
    # Also verify the event by fetching from Stripe API
    # (Belt and suspenders approach for critical operations)
    if event['type'] == 'charge.succeeded':
        charge_id = event['data']['object']['id']
        
        # Fetch the charge directly from Stripe to verify
        charge = stripe.Charge.retrieve(charge_id)
        
        if charge['status'] == 'succeeded':
            order_id = charge['metadata']['order_id']
            mark_order_paid(order_id)
    
    return {'received': True}


def verify_webhook_signature(payload: bytes, signature: str, webhook_secret: str) -> dict:
    """
    Verify Stripe webhook signature.
    """
    # Parse the signature header
    # Format: t=timestamp,v1=signature
    parts = dict(part.split('=') for part in signature.split(','))
    timestamp = parts['t']
    expected_sig = parts['v1']
    
    # Create the signed payload
    signed_payload = f"{timestamp}.{payload.decode()}"
    
    # Calculate expected signature
    computed_sig = hmac.new(
        webhook_secret.encode(),
        signed_payload.encode(),
        hashlib.sha256
    ).hexdigest()
    
    # Constant-time comparison to prevent timing attacks
    if not hmac.compare_digest(computed_sig, expected_sig):
        raise SignatureVerificationError("Signature mismatch")
    
    # Check timestamp to prevent replay attacks
    if abs(time.time() - int(timestamp)) > 300:  # 5 minute tolerance
        raise SignatureVerificationError("Timestamp too old")
    
    return json.loads(payload)
```

---

## 🔢 Mistake #7: Using Floats for Money

### The Mistake

```python
# ❌ WRONG - Floating point math for money
subtotal = 19.99
tax = subtotal * 0.08  # 1.5992
total = subtotal + tax  # 21.5892...

# When you charge:
charge_amount = total * 100  # 2158.9199999999... ❌

# Or worse:
item1 = 0.1
item2 = 0.2
total = item1 + item2  # 0.30000000000000004 ❌
```

### Why It's Wrong

```
┌─────────────────────────────────────────────────────────────────────┐
│                    FLOATING POINT MONEY DISASTERS                    │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  Python:                                                            │
│  >>> 0.1 + 0.2                                                      │
│  0.30000000000000004                                                │
│                                                                     │
│  >>> 19.99 * 100                                                    │
│  1999.0000000000002                                                 │
│                                                                     │
│  >>> int(2.9999999999 * 100)                                       │
│  299  # Should be 300!                                              │
│                                                                     │
│  JavaScript:                                                        │
│  > 0.1 + 0.2 === 0.3                                               │
│  false                                                              │
│                                                                     │
│  Real-world bug:                                                    │
│  Customer owes: $21.59                                              │
│  You charge: $21.58 (off by a penny due to float)                  │
│  Over 1M transactions: $10,000 discrepancy                         │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

### The Right Way

```python
from decimal import Decimal, ROUND_HALF_UP

# ✅ CORRECT - Use integers (cents) for money
class Money:
    """Always store and calculate money as integer cents."""
    
    def __init__(self, cents: int):
        if not isinstance(cents, int):
            raise TypeError("Money must be initialized with integer cents")
        self.cents = cents
    
    @classmethod
    def from_dollars(cls, dollars: str) -> 'Money':
        """Convert dollar string to cents."""
        # Use Decimal for parsing to avoid float issues
        d = Decimal(dollars)
        cents = int(d * 100)
        return cls(cents)
    
    def to_dollars(self) -> str:
        """Convert cents to dollar string for display."""
        return f"{self.cents / 100:.2f}"
    
    def __add__(self, other: 'Money') -> 'Money':
        return Money(self.cents + other.cents)
    
    def apply_percentage(self, percentage: str) -> 'Money':
        """Apply a percentage (like tax) correctly."""
        p = Decimal(percentage)
        result = Decimal(self.cents) * (1 + p)
        # Round half up (standard for money)
        rounded = result.quantize(Decimal('1'), rounding=ROUND_HALF_UP)
        return Money(int(rounded))


# Usage
subtotal = Money(1999)  # $19.99 stored as 1999 cents
tax = subtotal.apply_percentage('0.08')  # 8% tax
total = subtotal + tax

# When charging payment gateway
gateway.charge(amount=total.cents)  # Gateway expects integer cents
```

---

## ⏰ Mistake #8: Not Handling Async Payment Status

### The Mistake

```python
# ❌ WRONG - Assuming synchronous success
def process_payment(order_id, token):
    result = gateway.charge(token=token, amount=order.total)
    
    if result['status'] == 'succeeded':
        order.status = 'paid'
        send_confirmation_email()
        ship_order()
    else:
        order.status = 'failed'
```

### Why It's Wrong

```
┌─────────────────────────────────────────────────────────────────────┐
│                    ASYNC PAYMENT STATES                              │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  Not all payments complete synchronously!                           │
│                                                                     │
│  PENDING STATES:                                                    │
│  • requires_action - Needs 3DS authentication                       │
│  • requires_capture - Authorized but not captured                   │
│  • processing - Still being processed                               │
│  • pending - Waiting for bank (ACH, SEPA)                          │
│                                                                     │
│  If you only check 'succeeded':                                     │
│  • 3DS payments appear to fail                                      │
│  • Customers can't complete checkout                                │
│  • Bank transfers never complete                                    │
│                                                                     │
│  If you ship on 'processing':                                       │
│  • Payment might fail later                                         │
│  • You shipped for free                                             │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

### The Right Way

```python
# ✅ CORRECT - Handle all payment states
from enum import Enum

class PaymentStatus(Enum):
    PENDING = "pending"           # Waiting for async confirmation
    REQUIRES_ACTION = "requires_action"  # Needs customer action (3DS)
    PROCESSING = "processing"     # Gateway processing
    SUCCEEDED = "succeeded"       # Confirmed success
    FAILED = "failed"            # Confirmed failure
    CANCELED = "canceled"        # Canceled by merchant

def process_payment(order_id: str, token: str) -> dict:
    result = gateway.charge(token=token, amount=order.total)
    
    if result['status'] == 'succeeded':
        # Confirmed success - safe to fulfill
        order.status = 'paid'
        queue_fulfillment(order)
        return {'success': True}
        
    elif result['status'] == 'requires_action':
        # 3DS needed - return URL for customer to complete
        order.status = 'pending_authentication'
        return {
            'success': False,
            'requires_action': True,
            'action_url': result['next_action']['redirect_url']
        }
        
    elif result['status'] == 'processing':
        # Async processing - wait for webhook
        order.status = 'pending_payment'
        return {
            'success': False,
            'processing': True,
            'message': 'Payment is being processed. You will receive confirmation shortly.'
        }
        
    else:
        # Failed
        order.status = 'payment_failed'
        return {
            'success': False,
            'error': result.get('failure_message', 'Payment failed')
        }


# Handle webhook for async confirmation
@app.post('/webhooks/payment')
def handle_payment_webhook(request):
    event = verify_and_parse_webhook(request)
    
    if event['type'] == 'charge.succeeded':
        charge = event['data']['object']
        order_id = charge['metadata']['order_id']
        
        order = db.get_order(order_id)
        if order.status in ['pending_payment', 'pending_authentication']:
            order.status = 'paid'
            queue_fulfillment(order)
            send_confirmation_email(order)
    
    elif event['type'] == 'charge.failed':
        charge = event['data']['object']
        order_id = charge['metadata']['order_id']
        
        order = db.get_order(order_id)
        order.status = 'payment_failed'
        send_payment_failed_email(order)
```

---

## 📋 Mistake Summary Checklist

Before deploying any payment code, verify:

```
┌─────────────────────────────────────────────────────────────────────┐
│                    PAYMENT CODE REVIEW CHECKLIST                     │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  □ Card data NEVER touches my servers (using tokenization)         │
│                                                                     │
│  □ Amount is ALWAYS calculated server-side from my database        │
│                                                                     │
│  □ Every charge has an idempotency key                             │
│                                                                     │
│  □ No card numbers, CVVs, or full tokens in logs                   │
│                                                                     │
│  □ API keys are in environment variables, not code                 │
│                                                                     │
│  □ Webhooks verify signatures before processing                    │
│                                                                     │
│  □ Money calculations use integers (cents), not floats             │
│                                                                     │
│  □ All payment states are handled (not just success/fail)          │
│                                                                     │
│  □ Frontend validates AND backend validates                        │
│                                                                     │
│  □ Decline reasons never reveal fraud details to users             │
│                                                                     │
│  □ Retry logic uses same idempotency key                           │
│                                                                     │
│  □ Timeouts are handled as "unknown state"                         │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 🎯 Key Takeaways

1. **Tokenization is mandatory** - Never let card data touch your servers
2. **Never trust the client** - Validate everything server-side
3. **Idempotency prevents disasters** - Always use idempotency keys
4. **Logs are liability** - Scrub all sensitive data
5. **Keys stay secret** - Environment variables only
6. **Verify all webhooks** - Attackers will try to spoof them
7. **Integers for money** - Floats will betray you
8. **Handle async states** - Not all payments complete instantly

---

**Congratulations!** You've completed the documentation. Now let's build the actual system. Check out the [src/](../src/) directory to see these concepts implemented.
