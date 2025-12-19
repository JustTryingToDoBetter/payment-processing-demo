# 🔐 Security & PCI-DSS: Protecting Payment Data

> Understanding the security requirements, compliance standards, and best practices

## Why Payment Security is Different

Payment security isn't just "nice to have"—it's legally mandated, contractually required, and the difference between a business and a lawsuit. Let's understand why and how.

---

## 🏛️ PCI-DSS: The Governing Standard

### What is PCI-DSS?

**Payment Card Industry Data Security Standard** - A set of security requirements created by card networks (Visa, Mastercard, Amex, etc.) that ANYONE handling card data must follow.

```
┌─────────────────────────────────────────────────────────────────────┐
│                    PCI-DSS COMPLIANCE LEVELS                         │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  Level 1:  > 6 million transactions/year                           │
│            • Annual on-site audit by QSA                            │
│            • Quarterly network scans                                │
│            • Penetration testing                                    │
│            Example: Amazon, Walmart                                 │
│                                                                     │
│  Level 2:  1-6 million transactions/year                           │
│            • Annual self-assessment (SAQ)                           │
│            • Quarterly network scans                                │
│            Example: Mid-size e-commerce                             │
│                                                                     │
│  Level 3:  20,000-1 million e-commerce transactions/year           │
│            • Annual self-assessment                                 │
│            Example: Small online retailers                          │
│                                                                     │
│  Level 4:  < 20,000 e-commerce or < 1 million other                │
│            • Annual self-assessment                                 │
│            • Compliance validation varies by acquirer               │
│            Example: Small businesses, startups                      │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

### The 12 Requirements of PCI-DSS

```
┌─────────────────────────────────────────────────────────────────────┐
│            PCI-DSS 12 REQUIREMENTS (Simplified)                      │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  BUILD AND MAINTAIN A SECURE NETWORK                                │
│  ────────────────────────────────────                               │
│  1. Install and maintain a firewall                                 │
│  2. Don't use vendor-supplied default passwords                     │
│                                                                     │
│  PROTECT CARDHOLDER DATA                                            │
│  ────────────────────────                                           │
│  3. Protect stored cardholder data                                  │
│  4. Encrypt transmission of cardholder data                         │
│                                                                     │
│  MAINTAIN A VULNERABILITY MANAGEMENT PROGRAM                        │
│  ────────────────────────────────────────────                       │
│  5. Use and regularly update anti-virus                             │
│  6. Develop and maintain secure systems                             │
│                                                                     │
│  IMPLEMENT STRONG ACCESS CONTROL MEASURES                           │
│  ──────────────────────────────────────────                         │
│  7. Restrict access to cardholder data by business need             │
│  8. Assign unique IDs to each person with access                    │
│  9. Restrict physical access to cardholder data                     │
│                                                                     │
│  REGULARLY MONITOR AND TEST NETWORKS                                │
│  ───────────────────────────────────                                │
│  10. Track and monitor all access to network and card data          │
│  11. Regularly test security systems                                │
│                                                                     │
│  MAINTAIN AN INFORMATION SECURITY POLICY                            │
│  ───────────────────────────────────────                            │
│  12. Maintain a policy addressing information security              │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

### How to Minimize Your PCI Scope (Smart Approach)

**The golden rule: Don't touch card data if you don't have to.**

```
┌─────────────────────────────────────────────────────────────────────┐
│             PCI SCOPE REDUCTION STRATEGIES                           │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  APPROACH 1: Full Redirect (Lowest Scope)                           │
│  ─────────────────────────────────────────                          │
│  Customer redirected to payment gateway's hosted page               │
│  Card data never touches your systems                               │
│  PCI SAQ-A (simplest questionnaire)                                 │
│                                                                     │
│  Your Site ──────> Gateway Hosted Page ──────> Your Site            │
│              redirect        (card entered)         redirect        │
│                                                                     │
│  APPROACH 2: Iframe/JS SDK (Low Scope)                              │
│  ─────────────────────────────────────                              │
│  Gateway's iframe embedded in your page                             │
│  Card data captured by gateway's origin                             │
│  PCI SAQ-A-EP                                                       │
│                                                                     │
│  Your Page:                                                         │
│  ┌────────────────────────────────────────────────────────────┐    │
│  │  [Your content]                                            │    │
│  │  ╔════════════════════════════════════════════════════╗    │    │
│  │  ║  Gateway Iframe (different origin)                 ║    │    │
│  │  ║  Card: [____________]  CVV: [___]                  ║    │    │
│  │  ╚════════════════════════════════════════════════════╝    │    │
│  │  [Your submit button]                                      │    │
│  └────────────────────────────────────────────────────────────┘    │
│                                                                     │
│  APPROACH 3: Direct API (High Scope)                               │
│  ───────────────────────────────────                               │
│  Your server receives card data, sends to gateway                  │
│  Full PCI SAQ-D (extensive requirements)                           │
│  ⚠️ AVOID unless absolutely necessary                              │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 🔒 Encryption: Protecting Data in Motion and at Rest

### Encryption in Transit (TLS)

**ALL payment data must be encrypted during transmission.**

```
┌─────────────────────────────────────────────────────────────────────┐
│                    TLS REQUIREMENTS                                  │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  MINIMUM REQUIREMENTS:                                              │
│  • TLS 1.2 or higher (TLS 1.3 preferred)                           │
│  • Strong cipher suites only                                        │
│  • Valid certificates from trusted CAs                              │
│  • HSTS headers to prevent downgrade attacks                        │
│                                                                     │
│  ✅ ALLOWED:                                                        │
│  • TLS_AES_256_GCM_SHA384                                          │
│  • TLS_CHACHA20_POLY1305_SHA256                                    │
│  • ECDHE key exchange                                               │
│                                                                     │
│  ❌ FORBIDDEN:                                                      │
│  • SSL 2.0, SSL 3.0                                                │
│  • TLS 1.0, TLS 1.1                                                │
│  • RC4, DES, 3DES ciphers                                          │
│  • MD5 for integrity                                                │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

```python
# Server configuration example (Python/Flask)
from flask import Flask
import ssl

app = Flask(__name__)

# Create secure SSL context
context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
context.minimum_version = ssl.TLSVersion.TLSv1_2
context.set_ciphers('ECDHE+AESGCM:ECDHE+CHACHA20')
context.load_cert_chain('cert.pem', 'key.pem')

# Add security headers
@app.after_request
def add_security_headers(response):
    response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    return response

if __name__ == '__main__':
    app.run(ssl_context=context)
```

### Encryption at Rest

**Stored card data must be encrypted with strong algorithms.**

```
┌─────────────────────────────────────────────────────────────────────┐
│                    ENCRYPTION AT REST                                │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  WHAT MUST BE ENCRYPTED:                                            │
│  • Full card number (PAN)                                           │
│  • Any stored authentication data                                   │
│                                                                     │
│  WHAT MUST NEVER BE STORED (even encrypted):                        │
│  • CVV/CVC (3-4 digit security code)                               │
│  • Full magnetic stripe data                                        │
│  • PIN or PIN block                                                 │
│                                                                     │
│  ENCRYPTION REQUIREMENTS:                                           │
│  • AES-256 for symmetric encryption                                 │
│  • RSA-2048+ or ECC for asymmetric                                  │
│  • Proper key management (HSM recommended)                          │
│  • Key rotation policies                                            │
│                                                                     │
│  KEY MANAGEMENT HIERARCHY:                                          │
│                                                                     │
│       ┌─────────────────────────────────────┐                      │
│       │  Master Key (in HSM)               │                      │
│       │  Never leaves secure hardware      │                      │
│       └──────────────┬──────────────────────┘                      │
│                      │ encrypts                                     │
│                      ▼                                              │
│       ┌─────────────────────────────────────┐                      │
│       │  Key Encryption Key (KEK)          │                      │
│       │  Stored encrypted                  │                      │
│       └──────────────┬──────────────────────┘                      │
│                      │ encrypts                                     │
│                      ▼                                              │
│       ┌─────────────────────────────────────┐                      │
│       │  Data Encryption Key (DEK)         │                      │
│       │  Used for actual card data         │                      │
│       └─────────────────────────────────────┘                      │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

```python
# Simplified encryption example (educational - use proper HSM in production)
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
import os
import base64

class CardEncryption:
    """
    Educational example of card encryption.
    Production systems use HSMs (Hardware Security Modules).
    """
    
    def __init__(self, master_key: bytes):
        # In reality, master_key would be in an HSM
        self.master_key = master_key
    
    def encrypt_pan(self, card_number: str) -> dict:
        """
        Encrypt a card number (PAN).
        Returns encrypted data + metadata needed for decryption.
        """
        # Generate unique key for this card
        salt = os.urandom(16)
        nonce = os.urandom(12)
        
        # Derive key from master key + salt
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,  # 256 bits
            salt=salt,
            iterations=100000,
        )
        key = kdf.derive(self.master_key)
        
        # Encrypt with AES-256-GCM
        aesgcm = AESGCM(key)
        encrypted = aesgcm.encrypt(
            nonce,
            card_number.encode(),
            None  # Additional authenticated data
        )
        
        return {
            'encrypted_pan': base64.b64encode(encrypted).decode(),
            'salt': base64.b64encode(salt).decode(),
            'nonce': base64.b64encode(nonce).decode(),
            'key_version': 'v1',  # For key rotation
            'last_four': card_number[-4:]  # Safe to store
        }
    
    def decrypt_pan(self, encrypted_data: dict) -> str:
        """
        Decrypt a card number.
        Only called when actually needed (e.g., sending to bank).
        """
        salt = base64.b64decode(encrypted_data['salt'])
        nonce = base64.b64decode(encrypted_data['nonce'])
        encrypted = base64.b64decode(encrypted_data['encrypted_pan'])
        
        # Derive same key
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=100000,
        )
        key = kdf.derive(self.master_key)
        
        # Decrypt
        aesgcm = AESGCM(key)
        decrypted = aesgcm.decrypt(nonce, encrypted, None)
        
        return decrypted.decode()
```

---

## 🎭 Tokenization vs. Hashing vs. Encryption

Understanding the differences is crucial:

```
┌─────────────────────────────────────────────────────────────────────┐
│        TOKENIZATION vs HASHING vs ENCRYPTION                        │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  ENCRYPTION                                                         │
│  ──────────                                                         │
│  Purpose: Make data unreadable, but REVERSIBLE                      │
│  Input:   4242-4242-4242-4242                                       │
│  Output:  aGVsbG8gd29ybGQhCg== (can decrypt back)                   │
│                                                                     │
│  Pros: Can get original data back when needed                       │
│  Cons: If key is stolen, all data is exposed                        │
│  Use:  When you MUST store and later retrieve card data             │
│                                                                     │
│  ─────────────────────────────────────────────────────────────────  │
│                                                                     │
│  HASHING                                                            │
│  ───────                                                            │
│  Purpose: One-way fingerprint, NOT reversible                       │
│  Input:   4242-4242-4242-4242                                       │
│  Output:  8d969eef6ecad3c29a3a629280e686cf0c3f5d5a86aff3ca12020c92  │
│                                                                     │
│  Pros: Can't reverse to get original                                │
│  Cons: Same input = same hash (can be attacked)                     │
│  Use:  Passwords, NOT card numbers (attackable via lookup tables)   │
│                                                                     │
│  ⚠️ NEVER hash card numbers for storage - only 10^16 combinations! │
│                                                                     │
│  ─────────────────────────────────────────────────────────────────  │
│                                                                     │
│  TOKENIZATION                                                       │
│  ────────────                                                       │
│  Purpose: Replace with random, meaningless substitute               │
│  Input:   4242-4242-4242-4242                                       │
│  Output:  tok_1Abc2Def3Ghi (no mathematical relationship)           │
│                                                                     │
│  Pros: Token is useless if stolen (only valid for one merchant)     │
│  Cons: Need to maintain token vault                                 │
│  Use:  Best practice for payment systems!                           │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘

COMPARISON TABLE:
┌─────────────────┬─────────────┬─────────────┬─────────────┐
│                 │ Reversible? │ Deterministic?│ Best For   │
├─────────────────┼─────────────┼───────────────┼────────────┤
│ Encryption      │     Yes     │      Yes      │ Storage    │
│ Hashing         │     No      │      Yes      │ Passwords  │
│ Tokenization    │     No*     │      No       │ Card data  │
└─────────────────┴─────────────┴───────────────┴────────────┘
                   *Can look up in vault, but not derive mathematically
```

---

## 🛡️ 3-D Secure (3DS): Fraud Prevention

### What is 3-D Secure?

An additional authentication layer where the cardholder proves they're the legitimate owner.

```
┌─────────────────────────────────────────────────────────────────────┐
│                    3-D SECURE FLOW                                   │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  WITHOUT 3DS:                                                       │
│  ────────────                                                       │
│  Customer → Card Details → Merchant → Bank → Approved               │
│  (Merchant liable for fraud)                                        │
│                                                                     │
│  WITH 3DS:                                                          │
│  ─────────                                                          │
│  Customer → Card Details → Merchant → Bank                          │
│                              ↓                                      │
│  Customer ← Challenge ← Issuing Bank                                │
│  (OTP, biometric, app approval)                                     │
│                              ↓                                      │
│  Customer → Verification → Bank → Approved                          │
│  (Liability shifts to bank!)                                        │
│                                                                     │
│  3DS VERSIONS:                                                      │
│  ─────────────                                                      │
│  3DS 1.0: Redirect to bank page (poor UX)                          │
│  3DS 2.0: In-app/modal experience, risk-based (better UX)          │
│                                                                     │
│  RISK-BASED AUTHENTICATION (3DS 2.0):                              │
│  Low Risk:  Frictionless (no challenge needed)                      │
│  Med Risk:  Simple challenge (one-tap approval)                     │
│  High Risk: Full challenge (OTP, biometric)                         │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

```python
# 3DS implementation flow
class ThreeDSecureService:
    
    def check_enrollment(self, card_token: str, amount: int) -> dict:
        """
        Check if card is enrolled in 3DS and if challenge is needed.
        """
        # Send to card network's 3DS server
        response = self.directory_server.check_enrollment(
            token=card_token,
            amount=amount,
            merchant_id=self.merchant_id
        )
        
        if not response.enrolled:
            # Card not enrolled, proceed without 3DS
            return {'enrolled': False, 'proceed': True}
        
        if response.frictionless:
            # Low risk, no challenge needed
            return {
                'enrolled': True,
                'challenged': False,
                'authentication_value': response.cavv,  # Proof of auth
                'eci': response.eci  # E-commerce indicator
            }
        
        # Challenge required
        return {
            'enrolled': True,
            'challenged': True,
            'redirect_url': response.challenge_url,  # Send customer here
            'transaction_id': response.transaction_id
        }
    
    def verify_challenge(self, transaction_id: str) -> dict:
        """
        After customer completes challenge, verify the result.
        """
        result = self.directory_server.get_result(transaction_id)
        
        if result.authenticated:
            return {
                'success': True,
                'authentication_value': result.cavv,
                'eci': result.eci,
                'liability_shift': True  # Bank takes fraud liability!
            }
        else:
            return {
                'success': False,
                'reason': result.failure_reason
            }
```

### Why 3DS Matters for Merchants

```
┌─────────────────────────────────────────────────────────────────────┐
│              3DS LIABILITY SHIFT                                     │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  SCENARIO: Fraudster uses stolen card on your site                  │
│                                                                     │
│  WITHOUT 3DS:                                                       │
│  ├── Charge goes through                                            │
│  ├── Real cardholder sees charge, disputes                          │
│  ├── Bank issues chargeback                                         │
│  └── YOU lose the money + $15-25 chargeback fee                    │
│                                                                     │
│  WITH 3DS (authenticated):                                          │
│  ├── Fraudster can't complete 3DS challenge                        │
│  └── Transaction declined → No fraud occurs                        │
│                                                                     │
│  WITH 3DS (fraudster bypasses somehow):                             │
│  ├── 3DS authentication completed                                   │
│  ├── Charge goes through                                            │
│  ├── Real cardholder disputes                                       │
│  └── BANK is liable, not you! (liability shift)                    │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 🕵️ Fraud Prevention Layers

Multiple layers work together to prevent fraud:

```
┌─────────────────────────────────────────────────────────────────────┐
│                    FRAUD PREVENTION LAYERS                           │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  LAYER 1: INPUT VALIDATION                                          │
│  ─────────────────────────                                          │
│  • Luhn algorithm check (card number checksum)                      │
│  • BIN validation (first 6 digits identify issuer)                  │
│  • Format validation                                                │
│                                                                     │
│  LAYER 2: VELOCITY CHECKS                                           │
│  ────────────────────────                                           │
│  • Too many attempts from same IP                                   │
│  • Too many cards tried from same device                            │
│  • Too many transactions in short period                            │
│                                                                     │
│  LAYER 3: DEVICE FINGERPRINTING                                     │
│  ──────────────────────────────                                     │
│  • Browser fingerprint                                              │
│  • Known fraud device lists                                         │
│  • Bot detection                                                    │
│                                                                     │
│  LAYER 4: GEOGRAPHIC CHECKS                                         │
│  ──────────────────────────                                         │
│  • IP geolocation                                                   │
│  • Billing address vs IP location                                   │
│  • Known high-risk regions                                          │
│                                                                     │
│  LAYER 5: BEHAVIORAL ANALYSIS                                       │
│  ────────────────────────────                                       │
│  • Typing patterns                                                  │
│  • Mouse movements                                                  │
│  • Time on page                                                     │
│                                                                     │
│  LAYER 6: MACHINE LEARNING                                          │
│  ─────────────────────────                                          │
│  • Historical fraud patterns                                        │
│  • Cross-merchant intelligence                                      │
│  • Real-time risk scoring                                           │
│                                                                     │
│  LAYER 7: 3-D SECURE                                                │
│  ────────────────────                                               │
│  • Cardholder authentication                                        │
│  • Liability shift                                                  │
│                                                                     │
│  LAYER 8: MANUAL REVIEW                                             │
│  ──────────────────────                                             │
│  • High-value transactions                                          │
│  • Medium-risk scores                                               │
│  • New customer patterns                                            │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

### Implementing Basic Fraud Checks

```python
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

@dataclass
class FraudSignal:
    name: str
    score: float  # 0.0 to 1.0
    reason: str

class FraudDetector:
    """
    Basic fraud detection implementation.
    Production systems use ML models and external services.
    """
    
    def __init__(self, redis_client):
        self.redis = redis_client
        self.risk_threshold = 0.7  # Above this = decline or review
    
    def evaluate_transaction(
        self,
        ip_address: str,
        card_fingerprint: str,  # Hash of card for tracking
        amount: int,
        email: str,
        device_id: str
    ) -> dict:
        """
        Evaluate transaction risk.
        Returns risk score and signals.
        """
        signals = []
        
        # Check 1: Velocity - too many attempts from IP
        signals.append(self._check_ip_velocity(ip_address))
        
        # Check 2: Velocity - too many cards from device
        signals.append(self._check_device_velocity(device_id))
        
        # Check 3: Velocity - too many attempts with this card
        signals.append(self._check_card_velocity(card_fingerprint))
        
        # Check 4: Email domain risk
        signals.append(self._check_email_risk(email))
        
        # Check 5: Amount anomaly
        signals.append(self._check_amount_risk(amount))
        
        # Calculate overall risk
        total_score = sum(s.score for s in signals if s) / len(signals)
        
        return {
            'risk_score': total_score,
            'signals': [s for s in signals if s and s.score > 0],
            'recommendation': self._get_recommendation(total_score)
        }
    
    def _check_ip_velocity(self, ip: str) -> FraudSignal:
        """
        Check if too many payment attempts from this IP.
        """
        key = f"velocity:ip:{ip}"
        count = self.redis.incr(key)
        self.redis.expire(key, 3600)  # 1 hour window
        
        if count > 10:
            return FraudSignal(
                name="high_ip_velocity",
                score=0.9,
                reason=f"{count} attempts from IP in last hour"
            )
        elif count > 5:
            return FraudSignal(
                name="medium_ip_velocity",
                score=0.4,
                reason=f"{count} attempts from IP in last hour"
            )
        return FraudSignal(name="ip_velocity", score=0.0, reason="Normal")
    
    def _check_device_velocity(self, device_id: str) -> FraudSignal:
        """
        Check if too many different cards tried from this device.
        Fraudsters often test multiple stolen cards.
        """
        key = f"velocity:device_cards:{device_id}"
        # Store set of card fingerprints for this device
        card_count = self.redis.scard(key)
        
        if card_count > 3:
            return FraudSignal(
                name="multiple_cards_device",
                score=0.95,  # Very suspicious
                reason=f"{card_count} different cards from device"
            )
        return FraudSignal(name="device_velocity", score=0.0, reason="Normal")
    
    def _check_card_velocity(self, card_fp: str) -> FraudSignal:
        """
        Check for rapid attempts with same card (brute force CVV).
        """
        key = f"velocity:card:{card_fp}"
        count = self.redis.incr(key)
        self.redis.expire(key, 600)  # 10 minute window
        
        if count > 5:
            return FraudSignal(
                name="card_velocity",
                score=0.85,
                reason=f"{count} attempts with card in 10 minutes"
            )
        return FraudSignal(name="card_velocity", score=0.0, reason="Normal")
    
    def _check_email_risk(self, email: str) -> FraudSignal:
        """
        Check for risky email patterns.
        """
        domain = email.split('@')[-1].lower()
        
        # Disposable email domains (high risk)
        disposable_domains = {'tempmail.com', 'throwaway.com', 'guerrillamail.com'}
        if domain in disposable_domains:
            return FraudSignal(
                name="disposable_email",
                score=0.7,
                reason="Disposable email domain"
            )
        
        return FraudSignal(name="email_risk", score=0.0, reason="Normal")
    
    def _check_amount_risk(self, amount: int) -> FraudSignal:
        """
        Unusually round or high amounts can indicate testing.
        """
        # Fraudsters often test with small round amounts
        if amount in [100, 500, 1000]:  # $1, $5, $10
            return FraudSignal(
                name="test_amount",
                score=0.3,
                reason="Common test amount"
            )
        
        if amount > 100000:  # Over $1000
            return FraudSignal(
                name="high_amount",
                score=0.2,
                reason="High value transaction"
            )
        
        return FraudSignal(name="amount_risk", score=0.0, reason="Normal")
    
    def _get_recommendation(self, score: float) -> str:
        if score >= 0.8:
            return "DECLINE"
        elif score >= 0.5:
            return "REVIEW"
        elif score >= 0.3:
            return "3DS_REQUIRED"
        else:
            return "APPROVE"
```

---

## 🔑 Secure Key Management

API keys and secrets require special handling:

```
┌─────────────────────────────────────────────────────────────────────┐
│                    KEY MANAGEMENT BEST PRACTICES                     │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  ❌ NEVER DO:                                                       │
│  • Commit keys to git                                               │
│  • Put keys in frontend code                                        │
│  • Log API keys                                                     │
│  • Share keys via email/chat                                        │
│  • Use same keys for prod and dev                                   │
│                                                                     │
│  ✅ ALWAYS DO:                                                      │
│  • Use environment variables                                        │
│  • Use secret managers (AWS Secrets, Vault)                         │
│  • Rotate keys regularly                                            │
│  • Use separate keys per environment                                │
│  • Restrict key permissions (principle of least privilege)          │
│                                                                     │
│  KEY TYPES (like Stripe):                                           │
│  ─────────────────────────                                          │
│  Publishable Key (pk_...):                                          │
│  • Safe for frontend                                                │
│  • Can only create tokens                                           │
│  • Cannot charge cards                                              │
│                                                                     │
│  Secret Key (sk_...):                                               │
│  • Backend only!                                                    │
│  • Can create charges                                               │
│  • Full API access                                                  │
│                                                                     │
│  Restricted Keys:                                                   │
│  • Limited to specific operations                                   │
│  • e.g., "only create refunds"                                     │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

```python
# Secure configuration pattern
import os
from dataclasses import dataclass

@dataclass
class PaymentConfig:
    """
    Secure configuration for payment credentials.
    Never hardcode secrets!
    """
    gateway_secret_key: str
    gateway_publishable_key: str
    webhook_secret: str
    
    @classmethod
    def from_environment(cls) -> 'PaymentConfig':
        """Load config from environment variables."""
        secret_key = os.environ.get('PAYMENT_SECRET_KEY')
        if not secret_key:
            raise ValueError("PAYMENT_SECRET_KEY not set!")
        
        return cls(
            gateway_secret_key=secret_key,
            gateway_publishable_key=os.environ.get('PAYMENT_PUBLISHABLE_KEY'),
            webhook_secret=os.environ.get('PAYMENT_WEBHOOK_SECRET')
        )
    
    def __repr__(self):
        # Never print secrets!
        return f"PaymentConfig(secret_key=***{self.gateway_secret_key[-4:]})"
```

---

## 📋 Security Checklist

Before going live with any payment integration:

```
┌─────────────────────────────────────────────────────────────────────┐
│                    PAYMENT SECURITY CHECKLIST                        │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  DATA HANDLING                                                      │
│  □ Card data never touches my servers (using tokenization)         │
│  □ CVV never stored anywhere                                        │
│  □ Only last 4 digits of card stored                               │
│  □ Sensitive data encrypted at rest                                 │
│                                                                     │
│  TRANSMISSION                                                       │
│  □ All endpoints use HTTPS                                          │
│  □ TLS 1.2+ enforced                                                │
│  □ HSTS header configured                                           │
│  □ Certificate is valid and from trusted CA                         │
│                                                                     │
│  API SECURITY                                                       │
│  □ Secret keys only on backend                                      │
│  □ Keys stored in env vars / secret manager                         │
│  □ Different keys for test/production                               │
│  □ Webhook signatures verified                                      │
│                                                                     │
│  AUTHENTICATION                                                     │
│  □ 3DS implemented for high-risk transactions                       │
│  □ Rate limiting on payment endpoints                               │
│  □ Fraud detection layer active                                     │
│                                                                     │
│  VALIDATION                                                         │
│  □ Amount validated server-side (never trust frontend)              │
│  □ Idempotency keys used for all charges                           │
│  □ Currency codes validated                                         │
│                                                                     │
│  LOGGING & MONITORING                                               │
│  □ Card numbers never logged                                        │
│  □ Failed payment attempts monitored                                │
│  □ Alerting for unusual patterns                                    │
│                                                                     │
│  COMPLIANCE                                                         │
│  □ SAQ type determined and completed                               │
│  □ Quarterly network scans (if required)                           │
│  □ Security policy documented                                       │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 🎯 Key Takeaways

1. **Minimize PCI scope** - Use tokenization to avoid handling card data
2. **Encryption everywhere** - TLS in transit, AES at rest
3. **Tokenization > Hashing** for card data - Hashing is attackable
4. **3DS shifts liability** - Implement it to protect against chargebacks
5. **Defense in depth** - Multiple fraud prevention layers
6. **Never log secrets** - Card numbers, CVVs, API keys stay out of logs
7. **Verify webhooks** - Always check signatures to prevent spoofing

---

**Next:** [04-real-world-constraints.md](04-real-world-constraints.md) - Handling production chaos
