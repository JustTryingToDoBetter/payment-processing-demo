"""
Shared constants and configuration for the payment system.

This module defines constants used across the payment gateway,
merchant backend, and bank simulator.
"""

from enum import Enum

# =============================================================================
# CURRENCY CODES (ISO 4217)
# =============================================================================

class Currency(str, Enum):
    """Supported currencies."""
    USD = "usd"
    EUR = "eur"
    GBP = "gbp"
    
    @property
    def minor_units(self) -> int:
        """Number of minor units (cents) per major unit."""
        return 100  # Most currencies use 100


# =============================================================================
# CARD BRANDS
# =============================================================================

class CardBrand(str, Enum):
    """Supported card brands identified by BIN ranges."""
    VISA = "visa"
    MASTERCARD = "mastercard"
    AMEX = "amex"
    DISCOVER = "discover"
    UNKNOWN = "unknown"


# BIN (Bank Identification Number) ranges for card brand detection
BIN_RANGES = {
    CardBrand.VISA: [('4',)],  # Starts with 4
    CardBrand.MASTERCARD: [('51', '52', '53', '54', '55'), ('2221', '2720')],
    CardBrand.AMEX: [('34', '37')],
    CardBrand.DISCOVER: [('6011',), ('644', '649'), ('65',)],
}


# =============================================================================
# PAYMENT STATUS
# =============================================================================

class PaymentStatus(str, Enum):
    """Status of a payment throughout its lifecycle."""
    PENDING = "pending"                     # Initial state
    REQUIRES_ACTION = "requires_action"     # Needs 3DS or other action
    PROCESSING = "processing"               # Being processed
    AUTHORIZED = "authorized"               # Auth only, not captured
    SUCCEEDED = "succeeded"                 # Completed successfully
    FAILED = "failed"                       # Failed
    CANCELED = "canceled"                   # Canceled by merchant
    REFUNDED = "refunded"                   # Fully refunded
    PARTIALLY_REFUNDED = "partially_refunded"


class AuthorizationStatus(str, Enum):
    """Status of an authorization hold."""
    ACTIVE = "active"           # Hold is active
    CAPTURED = "captured"       # Funds captured
    VOIDED = "voided"          # Hold released
    EXPIRED = "expired"        # Hold expired (typically 7 days)


# =============================================================================
# DECLINE CODES
# =============================================================================

class DeclineCode(str, Enum):
    """Standardized decline codes from issuing banks."""
    # Hard declines - don't retry
    CARD_DECLINED = "card_declined"
    INSUFFICIENT_FUNDS = "insufficient_funds"
    EXPIRED_CARD = "expired_card"
    INVALID_NUMBER = "invalid_number"
    INVALID_CVV = "invalid_cvv"
    STOLEN_CARD = "stolen_card"
    LOST_CARD = "lost_card"
    
    # Soft declines - may retry
    ISSUER_UNAVAILABLE = "issuer_unavailable"
    TRY_AGAIN = "try_again"
    AUTHENTICATION_REQUIRED = "authentication_required"
    
    # Processing errors
    PROCESSING_ERROR = "processing_error"
    GATEWAY_ERROR = "gateway_error"


# =============================================================================
# EVENT TYPES (for webhooks)
# =============================================================================

class EventType(str, Enum):
    """Types of events dispatched via webhooks."""
    # Payment events
    PAYMENT_CREATED = "payment.created"
    PAYMENT_SUCCEEDED = "payment.succeeded"
    PAYMENT_FAILED = "payment.failed"
    PAYMENT_CANCELED = "payment.canceled"
    
    # Authorization events
    AUTHORIZATION_CREATED = "authorization.created"
    AUTHORIZATION_CAPTURED = "authorization.captured"
    AUTHORIZATION_VOIDED = "authorization.voided"
    AUTHORIZATION_EXPIRED = "authorization.expired"
    
    # Refund events
    REFUND_CREATED = "refund.created"
    REFUND_SUCCEEDED = "refund.succeeded"
    REFUND_FAILED = "refund.failed"
    
    # Dispute events
    DISPUTE_CREATED = "dispute.created"
    DISPUTE_UPDATED = "dispute.updated"
    DISPUTE_WON = "dispute.won"
    DISPUTE_LOST = "dispute.lost"


# =============================================================================
# MAGIC TEST CARD NUMBERS
# =============================================================================
# These special card numbers trigger specific behaviors in our mock gateway
# Inspired by Stripe's test card numbers

TEST_CARDS = {
    # Successful payments
    "4242424242424242": {"brand": CardBrand.VISA, "behavior": "success"},
    "5555555555554444": {"brand": CardBrand.MASTERCARD, "behavior": "success"},
    "378282246310005": {"brand": CardBrand.AMEX, "behavior": "success"},
    
    # Declined payments
    "4000000000000002": {"brand": CardBrand.VISA, "behavior": "decline", "code": DeclineCode.CARD_DECLINED},
    "4000000000009995": {"brand": CardBrand.VISA, "behavior": "decline", "code": DeclineCode.INSUFFICIENT_FUNDS},
    "4000000000000069": {"brand": CardBrand.VISA, "behavior": "decline", "code": DeclineCode.EXPIRED_CARD},
    "4000000000000127": {"brand": CardBrand.VISA, "behavior": "decline", "code": DeclineCode.INVALID_CVV},
    
    # Special behaviors
    "4000000000003220": {"brand": CardBrand.VISA, "behavior": "3ds_required"},
    "4000000000000077": {"brand": CardBrand.VISA, "behavior": "success_delayed"},  # 5 second delay
    "4000000000000341": {"brand": CardBrand.VISA, "behavior": "attach_fail"},  # Token creation fails
}


# =============================================================================
# CONFIGURATION
# =============================================================================

class Config:
    """Configuration constants."""
    
    # Token configuration
    TOKEN_PREFIX = "tok_"
    TOKEN_LENGTH = 24
    TOKEN_EXPIRY_MINUTES = 15  # One-time tokens expire
    
    # Payment configuration
    MIN_AMOUNT_CENTS = 50  # Minimum $0.50
    MAX_AMOUNT_CENTS = 99999999  # Maximum ~$1M
    
    # Authorization configuration
    AUTH_HOLD_DAYS = 7  # Auths expire after 7 days
    
    # Idempotency configuration
    IDEMPOTENCY_KEY_TTL_HOURS = 24
    
    # Webhook configuration
    WEBHOOK_TIMEOUT_SECONDS = 30
    WEBHOOK_MAX_RETRIES = 5
    WEBHOOK_RETRY_DELAYS = [0, 60, 300, 1800, 7200]  # seconds
    
    # Rate limiting
    MAX_REQUESTS_PER_MINUTE = 100
    MAX_FAILED_ATTEMPTS_PER_HOUR = 10  # Per IP
    
    # API versioning
    API_VERSION = "2024-01-01"


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def detect_card_brand(card_number: str) -> CardBrand:
    """
    Detect card brand from card number (BIN lookup).
    
    Args:
        card_number: The card number (can include spaces/dashes)
        
    Returns:
        The detected card brand
    """
    # Remove spaces and dashes
    number = card_number.replace(" ", "").replace("-", "")
    
    for brand, ranges in BIN_RANGES.items():
        for prefix_group in ranges:
            if isinstance(prefix_group, tuple):
                if any(number.startswith(p) for p in prefix_group):
                    return brand
            elif number.startswith(prefix_group):
                return brand
    
    return CardBrand.UNKNOWN


def validate_luhn(card_number: str) -> bool:
    """
    Validate card number using Luhn algorithm (mod 10 checksum).
    
    This is the standard algorithm to detect typos in card numbers.
    
    Args:
        card_number: The card number to validate
        
    Returns:
        True if valid, False otherwise
    """
    number = card_number.replace(" ", "").replace("-", "")
    
    if not number.isdigit():
        return False
    
    digits = [int(d) for d in number]
    
    # Double every second digit from right
    for i in range(len(digits) - 2, -1, -2):
        digits[i] *= 2
        if digits[i] > 9:
            digits[i] -= 9
    
    return sum(digits) % 10 == 0


def format_amount(cents: int, currency: Currency = Currency.USD) -> str:
    """
    Format amount in cents to display string.
    
    Args:
        cents: Amount in minor units
        currency: The currency
        
    Returns:
        Formatted string like "$19.99"
    """
    major = cents / currency.minor_units
    
    symbols = {
        Currency.USD: "$",
        Currency.EUR: "€",
        Currency.GBP: "£",
    }
    
    symbol = symbols.get(currency, currency.value.upper())
    return f"{symbol}{major:.2f}"
