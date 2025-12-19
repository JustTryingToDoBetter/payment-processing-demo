"""
Authorization and capture logic for the payment gateway.

This module handles:
- Authorization: Placing a hold on funds
- Capture: Actually taking the money
- Combined auth+capture for immediate payments
- Voids: Releasing authorized funds

Key concepts:
- Authorization is a PROMISE that funds are available
- Capture is the ACTUAL transfer of funds
- Authorizations expire (typically 7 days)
- You can capture less than authorized (partial capture)
"""

import time
import threading
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass

from ..shared.constants import (
    PaymentStatus, AuthorizationStatus, DeclineCode, Currency,
    Config, TEST_CARDS
)
from ..shared.idempotency import IdempotencyService, IdempotencyKeyBuilder
from ..shared.encryption import TokenGenerator

from .models import Authorization, Charge, Token
from .tokenization import TokenizationService


class PaymentError(Exception):
    """Base exception for payment errors."""
    pass


class AuthorizationError(PaymentError):
    """Authorization failed."""
    def __init__(self, message: str, decline_code: DeclineCode):
        super().__init__(message)
        self.decline_code = decline_code


class CaptureError(PaymentError):
    """Capture failed."""
    pass


class InvalidAmountError(PaymentError):
    """Invalid payment amount."""
    pass


@dataclass
class BankAuthResponse:
    """
    Simulated response from the bank network.
    
    In reality, this comes from the card network (Visa/MC)
    after routing through acquiring bank → card network → issuing bank.
    """
    approved: bool
    auth_code: Optional[str] = None
    decline_code: Optional[DeclineCode] = None
    decline_message: Optional[str] = None
    issuer_response_code: Optional[str] = None


class BankSimulator:
    """
    Simulates the bank network authorization process.
    
    In a real system, this would:
    1. Format ISO 8583 message
    2. Send to acquiring bank
    3. Route through card network
    4. Get response from issuing bank
    
    This simulator uses test card numbers to trigger different behaviors.
    """
    
    # Decline messages for each code
    DECLINE_MESSAGES = {
        DeclineCode.CARD_DECLINED: "Your card was declined.",
        DeclineCode.INSUFFICIENT_FUNDS: "Your card has insufficient funds.",
        DeclineCode.EXPIRED_CARD: "Your card has expired.",
        DeclineCode.INVALID_NUMBER: "Your card number is invalid.",
        DeclineCode.INVALID_CVV: "Your card's security code is invalid.",
        DeclineCode.STOLEN_CARD: "Your card was declined.",  # Don't reveal stolen!
        DeclineCode.LOST_CARD: "Your card was declined.",    # Don't reveal lost!
        DeclineCode.ISSUER_UNAVAILABLE: "The card issuer is temporarily unavailable.",
        DeclineCode.TRY_AGAIN: "Please try again.",
        DeclineCode.AUTHENTICATION_REQUIRED: "Additional authentication required.",
        DeclineCode.PROCESSING_ERROR: "An error occurred processing your card.",
    }
    
    def authorize(
        self,
        card_number: str,
        amount: int,
        currency: Currency
    ) -> BankAuthResponse:
        """
        Simulate bank authorization.
        
        Args:
            card_number: The full card number
            amount: Amount in cents
            currency: Transaction currency
            
        Returns:
            BankAuthResponse with approval or decline
        """
        # Check for test cards
        test_card = TEST_CARDS.get(card_number)
        
        if test_card:
            behavior = test_card.get("behavior", "success")
            
            if behavior == "success":
                return BankAuthResponse(
                    approved=True,
                    auth_code=self._generate_auth_code()
                )
            
            elif behavior == "decline":
                decline_code = test_card.get("code", DeclineCode.CARD_DECLINED)
                return BankAuthResponse(
                    approved=False,
                    decline_code=decline_code,
                    decline_message=self.DECLINE_MESSAGES.get(
                        decline_code, 
                        "Your card was declined."
                    )
                )
            
            elif behavior == "success_delayed":
                # Simulate slow bank response
                time.sleep(2)
                return BankAuthResponse(
                    approved=True,
                    auth_code=self._generate_auth_code()
                )
            
            elif behavior == "3ds_required":
                return BankAuthResponse(
                    approved=False,
                    decline_code=DeclineCode.AUTHENTICATION_REQUIRED,
                    decline_message="3D Secure authentication required"
                )
        
        # Default: approve for non-test cards
        return BankAuthResponse(
            approved=True,
            auth_code=self._generate_auth_code()
        )
    
    def capture(self, auth_code: str, amount: int) -> bool:
        """
        Simulate capture request.
        
        In reality, this completes the fund transfer.
        For this simulation, captures always succeed if we have a valid auth.
        """
        # In production: Send capture message to bank network
        # For demo: Always succeed
        return True
    
    def _generate_auth_code(self) -> str:
        """Generate a realistic-looking auth code."""
        import random
        return ''.join(random.choices('ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789', k=6))


class AuthorizationService:
    """
    Service for handling authorizations and captures.
    
    This is the core payment processing logic.
    """
    
    def __init__(
        self,
        tokenization: TokenizationService,
        idempotency: Optional[IdempotencyService] = None,
        bank_simulator: Optional[BankSimulator] = None
    ):
        self.tokenization = tokenization
        self.idempotency = idempotency or IdempotencyService()
        self.bank = bank_simulator or BankSimulator()
        
        # Storage (in production: database)
        self._authorizations: Dict[str, Authorization] = {}
        self._charges: Dict[str, Charge] = {}
        self._lock = threading.Lock()
    
    def authorize(
        self,
        token_id: str,
        amount: int,
        currency: Currency = Currency.USD,
        merchant_id: str = "",
        metadata: Optional[Dict] = None,
        idempotency_key: Optional[str] = None
    ) -> Authorization:
        """
        Create an authorization hold on funds.
        
        This checks if the card can pay the amount and places a hold,
        but does NOT transfer any money yet.
        
        Args:
            token_id: Token representing the card
            amount: Amount in cents
            currency: Transaction currency
            merchant_id: Merchant identifier
            metadata: Additional data to attach
            idempotency_key: Key for idempotent requests
            
        Returns:
            Authorization object
            
        Raises:
            InvalidAmountError: If amount is invalid
            AuthorizationError: If bank declines
        """
        # Validate amount
        self._validate_amount(amount)
        
        # Use idempotency if key provided
        if idempotency_key:
            return self.idempotency.execute(
                key=idempotency_key,
                operation=lambda: self._do_authorize(
                    token_id, amount, currency, merchant_id, metadata
                ),
                request_params={
                    "token_id": token_id,
                    "amount": amount,
                    "currency": currency.value
                }
            )
        
        return self._do_authorize(token_id, amount, currency, merchant_id, metadata)
    
    def _do_authorize(
        self,
        token_id: str,
        amount: int,
        currency: Currency,
        merchant_id: str,
        metadata: Optional[Dict]
    ) -> Authorization:
        """Internal authorization logic."""
        # Get token and card number
        token, card_number = self.tokenization.use_token(token_id)
        
        # Send to bank
        bank_response = self.bank.authorize(card_number, amount, currency)
        
        if not bank_response.approved:
            raise AuthorizationError(
                bank_response.decline_message or "Authorization failed",
                bank_response.decline_code or DeclineCode.CARD_DECLINED
            )
        
        # Create authorization record
        auth = Authorization(
            id=TokenGenerator.generate("auth_", 24),
            amount=amount,
            currency=currency,
            status=AuthorizationStatus.ACTIVE,
            card_last_four=token.card_last_four,
            card_brand=token.card_brand,
            auth_code=bank_response.auth_code,
            merchant_id=merchant_id,
            metadata=metadata or {},
            created_at=datetime.utcnow(),
            expires_at=datetime.utcnow() + timedelta(days=Config.AUTH_HOLD_DAYS)
        )
        
        with self._lock:
            self._authorizations[auth.id] = auth
        
        return auth
    
    def capture(
        self,
        authorization_id: str,
        amount: Optional[int] = None,
        idempotency_key: Optional[str] = None
    ) -> Charge:
        """
        Capture an authorization (take the money).
        
        Args:
            authorization_id: The authorization to capture
            amount: Amount to capture (None = full amount)
            idempotency_key: Key for idempotent requests
            
        Returns:
            Charge object
            
        Raises:
            CaptureError: If capture fails
        """
        if idempotency_key:
            return self.idempotency.execute(
                key=idempotency_key,
                operation=lambda: self._do_capture(authorization_id, amount),
                request_params={
                    "authorization_id": authorization_id,
                    "amount": amount
                }
            )
        
        return self._do_capture(authorization_id, amount)
    
    def _do_capture(
        self,
        authorization_id: str,
        amount: Optional[int]
    ) -> Charge:
        """Internal capture logic."""
        with self._lock:
            auth = self._authorizations.get(authorization_id)
            
            if not auth:
                raise CaptureError(f"Authorization {authorization_id} not found")
            
            capture_amount = amount or auth.amount
            
            if not auth.can_capture(capture_amount):
                if auth.status == AuthorizationStatus.CAPTURED:
                    raise CaptureError("Authorization has already been captured")
                elif auth.status == AuthorizationStatus.VOIDED:
                    raise CaptureError("Authorization has been voided")
                elif datetime.utcnow() > auth.expires_at:
                    raise CaptureError("Authorization has expired")
                else:
                    raise CaptureError("Cannot capture this amount")
            
            # Send capture to bank
            if not self.bank.capture(auth.auth_code, capture_amount):
                raise CaptureError("Bank declined capture")
            
            # Update authorization
            auth.status = AuthorizationStatus.CAPTURED
            auth.captured_amount = capture_amount
            auth.captured_at = datetime.utcnow()
            
            # Create charge record
            charge = Charge(
                id=TokenGenerator.generate("ch_", 24),
                amount=capture_amount,
                currency=auth.currency,
                status=PaymentStatus.SUCCEEDED,
                card_last_four=auth.card_last_four,
                card_brand=auth.card_brand,
                authorization_code=auth.auth_code,
                authorization_id=auth.id,
                merchant_id=auth.merchant_id,
                metadata=auth.metadata.copy()
            )
            
            self._charges[charge.id] = charge
        
        return charge
    
    def void(self, authorization_id: str) -> Authorization:
        """
        Void an authorization (release the hold).
        
        Args:
            authorization_id: The authorization to void
            
        Returns:
            Updated Authorization object
            
        Raises:
            PaymentError: If void fails
        """
        with self._lock:
            auth = self._authorizations.get(authorization_id)
            
            if not auth:
                raise PaymentError(f"Authorization {authorization_id} not found")
            
            if not auth.can_void():
                raise PaymentError(f"Authorization cannot be voided (status: {auth.status})")
            
            auth.status = AuthorizationStatus.VOIDED
            auth.voided_at = datetime.utcnow()
        
        return auth
    
    def create_charge(
        self,
        token_id: str,
        amount: int,
        currency: Currency = Currency.USD,
        capture: bool = True,
        merchant_id: str = "",
        description: Optional[str] = None,
        metadata: Optional[Dict] = None,
        idempotency_key: Optional[str] = None
    ) -> Charge:
        """
        Create a charge (auth + capture in one step).
        
        This is the most common payment flow for immediate purchases.
        
        Args:
            token_id: Token representing the card
            amount: Amount in cents
            currency: Transaction currency
            capture: If True, capture immediately. If False, auth only.
            merchant_id: Merchant identifier
            description: Payment description
            metadata: Additional data
            idempotency_key: Key for idempotent requests
            
        Returns:
            Charge object
        """
        if idempotency_key:
            return self.idempotency.execute(
                key=idempotency_key,
                operation=lambda: self._do_create_charge(
                    token_id, amount, currency, capture, 
                    merchant_id, description, metadata
                ),
                request_params={
                    "token_id": token_id,
                    "amount": amount,
                    "currency": currency.value,
                    "capture": capture
                }
            )
        
        return self._do_create_charge(
            token_id, amount, currency, capture, 
            merchant_id, description, metadata
        )
    
    def _do_create_charge(
        self,
        token_id: str,
        amount: int,
        currency: Currency,
        capture: bool,
        merchant_id: str,
        description: Optional[str],
        metadata: Optional[Dict]
    ) -> Charge:
        """Internal charge creation logic."""
        # Validate
        self._validate_amount(amount)
        
        # Get token and card
        token, card_number = self.tokenization.use_token(token_id)
        
        # Authorize with bank
        bank_response = self.bank.authorize(card_number, amount, currency)
        
        if not bank_response.approved:
            # Create failed charge record
            charge = Charge(
                id=TokenGenerator.generate("ch_", 24),
                amount=amount,
                currency=currency,
                status=PaymentStatus.FAILED,
                card_last_four=token.card_last_four,
                card_brand=token.card_brand,
                decline_code=bank_response.decline_code,
                decline_message=bank_response.decline_message,
                merchant_id=merchant_id,
                description=description,
                metadata=metadata or {}
            )
            
            with self._lock:
                self._charges[charge.id] = charge
            
            # Return the failed charge (caller can check status)
            return charge
        
        # If capture=False, return auth-only (create an authorization)
        if not capture:
            auth = Authorization(
                id=TokenGenerator.generate("auth_", 24),
                amount=amount,
                currency=currency,
                status=AuthorizationStatus.ACTIVE,
                card_last_four=token.card_last_four,
                card_brand=token.card_brand,
                auth_code=bank_response.auth_code,
                merchant_id=merchant_id,
                metadata=metadata or {}
            )
            
            with self._lock:
                self._authorizations[auth.id] = auth
            
            # Return a pending charge with authorization reference
            charge = Charge(
                id=TokenGenerator.generate("ch_", 24),
                amount=amount,
                currency=currency,
                status=PaymentStatus.AUTHORIZED,
                card_last_four=token.card_last_four,
                card_brand=token.card_brand,
                authorization_code=bank_response.auth_code,
                authorization_id=auth.id,
                merchant_id=merchant_id,
                description=description,
                metadata=metadata or {}
            )
            
            with self._lock:
                self._charges[charge.id] = charge
            
            return charge
        
        # Capture immediately
        if not self.bank.capture(bank_response.auth_code, amount):
            raise CaptureError("Bank declined capture")
        
        # Create successful charge
        charge = Charge(
            id=TokenGenerator.generate("ch_", 24),
            amount=amount,
            currency=currency,
            status=PaymentStatus.SUCCEEDED,
            card_last_four=token.card_last_four,
            card_brand=token.card_brand,
            authorization_code=bank_response.auth_code,
            merchant_id=merchant_id,
            description=description,
            metadata=metadata or {}
        )
        
        with self._lock:
            self._charges[charge.id] = charge
        
        return charge
    
    def get_charge(self, charge_id: str) -> Optional[Charge]:
        """Get a charge by ID."""
        return self._charges.get(charge_id)
    
    def get_authorization(self, auth_id: str) -> Optional[Authorization]:
        """Get an authorization by ID."""
        return self._authorizations.get(auth_id)
    
    def list_charges(
        self,
        merchant_id: Optional[str] = None,
        limit: int = 10
    ) -> List[Charge]:
        """List charges, optionally filtered by merchant."""
        charges = list(self._charges.values())
        
        if merchant_id:
            charges = [c for c in charges if c.merchant_id == merchant_id]
        
        # Sort by created_at descending
        charges.sort(key=lambda c: c.created_at, reverse=True)
        
        return charges[:limit]
    
    def _validate_amount(self, amount: int) -> None:
        """Validate payment amount."""
        if not isinstance(amount, int):
            raise InvalidAmountError("Amount must be an integer (cents)")
        
        if amount < Config.MIN_AMOUNT_CENTS:
            raise InvalidAmountError(
                f"Amount must be at least {Config.MIN_AMOUNT_CENTS} cents"
            )
        
        if amount > Config.MAX_AMOUNT_CENTS:
            raise InvalidAmountError(
                f"Amount cannot exceed {Config.MAX_AMOUNT_CENTS} cents"
            )


# =============================================================================
# Demo
# =============================================================================

def demo_authorization():
    """Demonstrate authorization and capture."""
    print("=" * 60)
    print("AUTHORIZATION & CAPTURE DEMO")
    print("=" * 60)
    
    # Set up services
    tokenization = TokenizationService()
    auth_service = AuthorizationService(tokenization)
    
    # Create a token first
    token = tokenization.create_token(
        card_number="4242424242424242",
        exp_month=12,
        exp_year=2025,
        cvv="123"
    )
    print(f"\n1. Created token: {token.id}")
    
    # Create a charge (auth + capture)
    print("\n2. Creating charge (auth + capture in one step):")
    charge = auth_service.create_charge(
        token_id=token.id,
        amount=9900,  # $99.00
        description="Test purchase",
        idempotency_key="demo_charge_001"
    )
    print(f"   Charge ID: {charge.id}")
    print(f"   Status: {charge.status.value}")
    print(f"   Amount: ${charge.amount / 100:.2f}")
    print(f"   Card: {charge.card_brand.value} ****{charge.card_last_four}")
    
    # Demonstrate auth-only flow
    print("\n3. Auth-only flow (for hotels, car rentals, etc.):")
    
    token2 = tokenization.create_token(
        card_number="5555555555554444",  # Mastercard
        exp_month=6,
        exp_year=2026,
        cvv="456"
    )
    
    charge2 = auth_service.create_charge(
        token_id=token2.id,
        amount=50000,  # $500.00 hold
        capture=False,  # Auth only!
        description="Hotel reservation",
        idempotency_key="demo_auth_001"
    )
    print(f"   Charge ID: {charge2.id}")
    print(f"   Status: {charge2.status.value}")  # Should be "authorized"
    print(f"   Auth Code: {charge2.authorization_code}")
    
    # Later: capture a different amount (actual stay cost)
    print("\n4. Capturing a partial amount:")
    print(f"   Original auth: $500.00")
    print(f"   Actual stay cost: $450.00")
    
    # Get the authorization
    auth = auth_service.get_authorization(charge2.authorization_id)
    captured = auth_service.capture(
        authorization_id=auth.id,
        amount=45000,  # $450.00 (less than authed)
        idempotency_key="demo_capture_001"
    )
    print(f"   Captured: ${captured.amount / 100:.2f}")
    print(f"   Status: {captured.status.value}")
    
    # Test decline
    print("\n5. Testing declined card:")
    token3 = tokenization.create_token(
        card_number="4000000000000002",  # Decline test card
        exp_month=12,
        exp_year=2025,
        cvv="123"
    )
    
    declined = auth_service.create_charge(
        token_id=token3.id,
        amount=1000,
        idempotency_key="demo_decline_001"
    )
    print(f"   Status: {declined.status.value}")
    print(f"   Decline code: {declined.decline_code.value if declined.decline_code else 'N/A'}")
    print(f"   Message: {declined.decline_message}")
    
    # Test idempotency
    print("\n6. Testing idempotency (same key = same result):")
    token4 = tokenization.create_token(
        card_number="4242424242424242",
        exp_month=12,
        exp_year=2025,
        cvv="123"
    )
    
    charge_a = auth_service.create_charge(
        token_id=token4.id,
        amount=2500,
        idempotency_key="demo_idem_001"
    )
    print(f"   First call: Charge {charge_a.id}, status={charge_a.status.value}")
    
    # Try again with same key - should return cached result
    # Note: We'd need a new token normally, but idempotency returns cached result
    # In real usage, the same token would work because it's the same request
    print(f"   Second call with same key would return same result (cached)")


if __name__ == "__main__":
    demo_authorization()
