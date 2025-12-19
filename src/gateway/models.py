"""
Data models for the payment gateway.

These models represent the core entities in a payment system.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from enum import Enum

from ..shared.constants import (
    CardBrand, PaymentStatus, AuthorizationStatus, 
    DeclineCode, Currency, detect_card_brand
)


@dataclass
class Card:
    """
    Represents a credit/debit card.
    
    SECURITY NOTE: In a real system, the full card number would
    NEVER be stored like this. It would be:
    - Encrypted in a secure vault (HSM)
    - Only accessible by the tokenization service
    - Never exposed in logs or API responses
    """
    number: str           # Full card number (DEMO ONLY - never store in prod!)
    exp_month: int        # 1-12
    exp_year: int         # Full year (2024, not 24)
    cvv: str              # Card verification value (NEVER stored in prod!)
    cardholder_name: Optional[str] = None
    
    # Derived/safe-to-store fields
    last_four: str = field(init=False)
    brand: CardBrand = field(init=False)
    fingerprint: Optional[str] = None  # For duplicate detection
    
    def __post_init__(self):
        """Derive fields after initialization."""
        clean_number = self.number.replace(" ", "").replace("-", "")
        self.last_four = clean_number[-4:]
        self.brand = detect_card_brand(clean_number)
    
    def is_expired(self) -> bool:
        """Check if card is expired."""
        now = datetime.utcnow()
        # Card is valid through the last day of exp_month
        expiry = datetime(self.exp_year, self.exp_month, 1)
        if self.exp_month == 12:
            expiry = datetime(self.exp_year + 1, 1, 1)
        else:
            expiry = datetime(self.exp_year, self.exp_month + 1, 1)
        return now >= expiry
    
    def to_safe_dict(self) -> Dict:
        """
        Return only safe-to-expose fields.
        NEVER include full number or CVV!
        """
        return {
            "last_four": self.last_four,
            "brand": self.brand.value,
            "exp_month": self.exp_month,
            "exp_year": self.exp_year,
            "cardholder_name": self.cardholder_name,
        }


@dataclass
class Token:
    """
    A token representing a card.
    
    Tokens are safe to:
    - Store in merchant databases
    - Pass through APIs
    - Log (though still best to avoid)
    
    They cannot be used to retrieve the original card number.
    """
    id: str                           # e.g., "tok_1abc2def3ghi"
    card_last_four: str
    card_brand: CardBrand
    card_exp_month: int
    card_exp_year: int
    created_at: datetime = field(default_factory=datetime.utcnow)
    expires_at: Optional[datetime] = None  # One-time tokens expire
    used: bool = False
    
    # Internal reference (not exposed to merchants)
    _card_vault_id: Optional[str] = None
    
    def is_expired(self) -> bool:
        """Check if token has expired."""
        if self.expires_at is None:
            return False
        return datetime.utcnow() > self.expires_at
    
    def is_valid(self) -> bool:
        """Check if token can be used."""
        return not self.used and not self.is_expired()
    
    def to_dict(self) -> Dict:
        """Serialize for API response."""
        return {
            "id": self.id,
            "object": "token",
            "card": {
                "last4": self.card_last_four,
                "brand": self.card_brand.value,
                "exp_month": self.card_exp_month,
                "exp_year": self.card_exp_year,
            },
            "created": int(self.created_at.timestamp()),
            "used": self.used,
        }


@dataclass 
class Authorization:
    """
    An authorization hold on funds.
    
    Authorization places a hold on the cardholder's available credit
    but doesn't transfer any money. The funds are reserved until:
    - Captured (money transferred)
    - Voided (hold released)
    - Expired (hold automatically released)
    """
    id: str                           # e.g., "auth_1abc2def3ghi"
    amount: int                       # In cents
    currency: Currency
    status: AuthorizationStatus
    
    # Card info (safe subset)
    card_last_four: str
    card_brand: CardBrand
    
    # Timestamps
    created_at: datetime = field(default_factory=datetime.utcnow)
    expires_at: datetime = field(default_factory=lambda: datetime.utcnow() + timedelta(days=7))
    captured_at: Optional[datetime] = None
    voided_at: Optional[datetime] = None
    
    # Capture tracking
    captured_amount: int = 0
    
    # Bank response
    auth_code: Optional[str] = None   # Bank's authorization code
    
    # Metadata
    merchant_id: str = ""
    metadata: Dict = field(default_factory=dict)
    
    def can_capture(self, amount: Optional[int] = None) -> bool:
        """Check if authorization can be captured."""
        if self.status != AuthorizationStatus.ACTIVE:
            return False
        if datetime.utcnow() > self.expires_at:
            return False
        if amount and amount > (self.amount - self.captured_amount):
            return False
        return True
    
    def can_void(self) -> bool:
        """Check if authorization can be voided."""
        return self.status == AuthorizationStatus.ACTIVE
    
    def to_dict(self) -> Dict:
        """Serialize for API response."""
        return {
            "id": self.id,
            "object": "authorization",
            "amount": self.amount,
            "currency": self.currency.value,
            "status": self.status.value,
            "card": {
                "last4": self.card_last_four,
                "brand": self.card_brand.value,
            },
            "auth_code": self.auth_code,
            "captured_amount": self.captured_amount,
            "created": int(self.created_at.timestamp()),
            "expires_at": int(self.expires_at.timestamp()),
            "metadata": self.metadata,
        }


@dataclass
class Charge:
    """
    A completed charge (successful or failed payment).
    
    A charge represents an actual attempt to move money.
    It's created after authorization + capture in one step,
    or after capturing an existing authorization.
    """
    id: str                           # e.g., "ch_1abc2def3ghi"
    amount: int                       # In cents
    currency: Currency
    status: PaymentStatus
    
    # Card info
    card_last_four: str
    card_brand: CardBrand
    
    # Timestamps
    created_at: datetime = field(default_factory=datetime.utcnow)
    
    # Result info
    authorization_code: Optional[str] = None
    decline_code: Optional[DeclineCode] = None
    decline_message: Optional[str] = None
    
    # Refund tracking
    refunded: bool = False
    refunded_amount: int = 0
    
    # Related objects
    authorization_id: Optional[str] = None  # If created from auth+capture
    
    # Merchant info
    merchant_id: str = ""
    description: Optional[str] = None
    metadata: Dict = field(default_factory=dict)
    
    # Risk info (from fraud detection)
    risk_score: Optional[float] = None
    risk_level: Optional[str] = None
    
    def can_refund(self, amount: Optional[int] = None) -> bool:
        """Check if charge can be refunded."""
        if self.status != PaymentStatus.SUCCEEDED:
            return False
        refund_amount = amount or (self.amount - self.refunded_amount)
        return refund_amount <= (self.amount - self.refunded_amount)
    
    def to_dict(self) -> Dict:
        """Serialize for API response."""
        result = {
            "id": self.id,
            "object": "charge",
            "amount": self.amount,
            "currency": self.currency.value,
            "status": self.status.value,
            "card": {
                "last4": self.card_last_four,
                "brand": self.card_brand.value,
            },
            "created": int(self.created_at.timestamp()),
            "description": self.description,
            "metadata": self.metadata,
            "refunded": self.refunded,
            "amount_refunded": self.refunded_amount,
        }
        
        if self.status == PaymentStatus.SUCCEEDED:
            result["authorization_code"] = self.authorization_code
        elif self.status == PaymentStatus.FAILED:
            result["failure_code"] = self.decline_code.value if self.decline_code else None
            result["failure_message"] = self.decline_message
        
        return result


@dataclass
class Refund:
    """
    A refund of a charge.
    
    Refunds return money to the cardholder. They can be:
    - Full: Refund entire charge amount
    - Partial: Refund part of the charge
    """
    id: str                           # e.g., "re_1abc2def3ghi"
    charge_id: str                    # The charge being refunded
    amount: int                       # Refund amount in cents
    currency: Currency
    status: PaymentStatus             # pending, succeeded, or failed
    
    created_at: datetime = field(default_factory=datetime.utcnow)
    
    reason: Optional[str] = None      # Reason for refund
    metadata: Dict = field(default_factory=dict)
    
    def to_dict(self) -> Dict:
        """Serialize for API response."""
        return {
            "id": self.id,
            "object": "refund",
            "charge": self.charge_id,
            "amount": self.amount,
            "currency": self.currency.value,
            "status": self.status.value,
            "created": int(self.created_at.timestamp()),
            "reason": self.reason,
            "metadata": self.metadata,
        }


@dataclass
class Dispute:
    """
    A payment dispute (chargeback).
    
    Disputes occur when a cardholder challenges a charge
    with their bank. They're expensive and time-sensitive.
    """
    id: str                           # e.g., "dp_1abc2def3ghi"
    charge_id: str
    amount: int
    currency: Currency
    
    status: str                       # needs_response, under_review, won, lost
    reason: str                       # fraudulent, duplicate, product_not_received, etc.
    
    created_at: datetime = field(default_factory=datetime.utcnow)
    evidence_due_by: datetime = field(
        default_factory=lambda: datetime.utcnow() + timedelta(days=7)
    )
    
    evidence_submitted: bool = False
    metadata: Dict = field(default_factory=dict)
    
    def to_dict(self) -> Dict:
        """Serialize for API response."""
        return {
            "id": self.id,
            "object": "dispute",
            "charge": self.charge_id,
            "amount": self.amount,
            "currency": self.currency.value,
            "status": self.status,
            "reason": self.reason,
            "created": int(self.created_at.timestamp()),
            "evidence_due_by": int(self.evidence_due_by.timestamp()),
            "evidence_submitted": self.evidence_submitted,
        }


@dataclass
class Merchant:
    """
    A merchant account.
    
    Merchants are businesses that accept payments through the gateway.
    """
    id: str                           # e.g., "merch_1abc2def3ghi"
    name: str
    email: str
    
    # API keys
    api_key_live: str                 # sk_live_xxx
    api_key_test: str                 # sk_test_xxx
    publishable_key_live: str         # pk_live_xxx
    publishable_key_test: str         # pk_test_xxx
    
    # Webhook configuration
    webhook_url: Optional[str] = None
    webhook_secret: Optional[str] = None
    
    # Settings
    default_currency: Currency = Currency.USD
    auto_capture: bool = True         # Auth+capture vs auth-only default
    
    created_at: datetime = field(default_factory=datetime.utcnow)
    metadata: Dict = field(default_factory=dict)


@dataclass
class Event:
    """
    A webhook event.
    
    Events are sent to merchants when things happen:
    - Payments succeed or fail
    - Refunds are processed
    - Disputes are opened
    """
    id: str                           # e.g., "evt_1abc2def3ghi"
    type: str                         # e.g., "charge.succeeded"
    data: Dict                        # The object that triggered the event
    
    created_at: datetime = field(default_factory=datetime.utcnow)
    
    # Delivery tracking
    merchant_id: str = ""
    delivered: bool = False
    delivery_attempts: int = 0
    last_attempt_at: Optional[datetime] = None
    next_attempt_at: Optional[datetime] = None
    
    def to_dict(self) -> Dict:
        """Serialize for webhook payload."""
        return {
            "id": self.id,
            "object": "event",
            "type": self.type,
            "data": {
                "object": self.data
            },
            "created": int(self.created_at.timestamp()),
        }


# =============================================================================
# Request/Response Models
# =============================================================================

@dataclass
class TokenizeRequest:
    """Request to create a token from card data."""
    card_number: str
    exp_month: int
    exp_year: int
    cvv: str
    cardholder_name: Optional[str] = None


@dataclass
class ChargeRequest:
    """Request to create a charge."""
    token: str
    amount: int
    currency: str = "usd"
    capture: bool = True              # If False, auth-only
    description: Optional[str] = None
    metadata: Dict = field(default_factory=dict)
    idempotency_key: Optional[str] = None


@dataclass
class RefundRequest:
    """Request to create a refund."""
    charge_id: str
    amount: Optional[int] = None      # If None, full refund
    reason: Optional[str] = None
    metadata: Dict = field(default_factory=dict)
    idempotency_key: Optional[str] = None


@dataclass
class CaptureRequest:
    """Request to capture an authorization."""
    authorization_id: str
    amount: Optional[int] = None      # If None, capture full amount
