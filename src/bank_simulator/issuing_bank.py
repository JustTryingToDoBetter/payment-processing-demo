"""
Simulated Issuing Bank for the payment demo.

The issuing bank is the customer's bank - the one that issued their card.
When a payment is made, the issuing bank:
1. Verifies the card is valid and not blocked
2. Checks available funds/credit
3. Performs fraud checks
4. Authorizes or declines the transaction
5. Places a hold on funds (for auth) or deducts (for capture)

This is a simplified simulation for educational purposes.
"""

import secrets
import threading
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from typing import Dict, List, Optional
from enum import Enum


class CardStatus(str, Enum):
    """Card status at the issuing bank."""
    ACTIVE = "active"
    BLOCKED = "blocked"
    EXPIRED = "expired"
    LOST_STOLEN = "lost_stolen"
    FRAUD_SUSPECT = "fraud_suspect"


class AccountType(str, Enum):
    """Type of card account."""
    DEBIT = "debit"
    CREDIT = "credit"
    PREPAID = "prepaid"


@dataclass
class CardAccount:
    """
    A card account at the issuing bank.
    
    For credit cards: available_credit is the spending limit minus balance
    For debit cards: available_balance is the account balance
    """
    card_number: str
    cardholder_name: str
    exp_month: int
    exp_year: int
    cvv: str
    status: CardStatus = CardStatus.ACTIVE
    account_type: AccountType = AccountType.CREDIT
    
    # For credit cards
    credit_limit: int = 500000  # $5,000 in cents
    current_balance: int = 0    # What's owed
    
    # For debit/prepaid
    account_balance: int = 100000  # $1,000 in cents
    
    # Holds (authorized but not captured)
    holds: Dict[str, int] = field(default_factory=dict)  # auth_id → amount
    
    # Fraud settings
    velocity_limit: int = 5  # Max transactions per hour
    single_transaction_limit: int = 100000  # $1,000
    
    @property
    def available_credit(self) -> int:
        """Available credit for credit cards."""
        holds_total = sum(self.holds.values())
        return self.credit_limit - self.current_balance - holds_total
    
    @property
    def available_balance(self) -> int:
        """Available balance for debit cards."""
        holds_total = sum(self.holds.values())
        return self.account_balance - holds_total


@dataclass
class AuthorizationRequest:
    """Request from card network to authorize a transaction."""
    request_id: str
    card_number: str
    exp_month: int
    exp_year: int
    cvv: str
    amount: int
    currency: str
    merchant_id: str
    merchant_name: str
    merchant_category: str


@dataclass
class AuthorizationResponse:
    """Response to authorization request."""
    request_id: str
    approved: bool
    auth_code: Optional[str] = None
    decline_reason: Optional[str] = None
    avs_result: str = "Y"  # Address verification
    cvv_result: str = "M"  # CVV match


class IssuingBank:
    """
    Simulated issuing bank.
    
    Handles:
    - Authorization requests
    - Capture requests
    - Refunds
    - Card management
    """
    
    def __init__(self, bank_name: str = "Demo Bank"):
        self.bank_name = bank_name
        
        # Card number → account
        self._accounts: Dict[str, CardAccount] = {}
        
        # Track recent transactions for velocity checks
        self._transaction_history: Dict[str, List[datetime]] = {}
        
        self._lock = threading.Lock()
        
        # Set up test accounts
        self._setup_test_accounts()
    
    def _setup_test_accounts(self):
        """Create test accounts for demo."""
        # Successful card - Visa
        self._accounts["4242424242424242"] = CardAccount(
            card_number="4242424242424242",
            cardholder_name="Test Success",
            exp_month=12,
            exp_year=2025,
            cvv="123",
            credit_limit=1000000,  # $10,000
        )
        
        # Insufficient funds - Visa
        self._accounts["4000000000009995"] = CardAccount(
            card_number="4000000000009995",
            cardholder_name="Test Insufficient",
            exp_month=12,
            exp_year=2025,
            cvv="123",
            credit_limit=10000,  # $100 only
            current_balance=9900,  # $99 already used
        )
        
        # Declined card - Visa
        self._accounts["4000000000000002"] = CardAccount(
            card_number="4000000000000002",
            cardholder_name="Test Declined",
            exp_month=12,
            exp_year=2025,
            cvv="123",
            status=CardStatus.BLOCKED,
        )
        
        # Fraud card - Visa
        self._accounts["4100000000000019"] = CardAccount(
            card_number="4100000000000019",
            cardholder_name="Test Fraud",
            exp_month=12,
            exp_year=2025,
            cvv="123",
            status=CardStatus.FRAUD_SUSPECT,
        )
        
        # Mastercard success
        self._accounts["5555555555554444"] = CardAccount(
            card_number="5555555555554444",
            cardholder_name="Test MC Success",
            exp_month=12,
            exp_year=2025,
            cvv="123",
        )
        
        # Debit card
        self._accounts["4000056655665556"] = CardAccount(
            card_number="4000056655665556",
            cardholder_name="Test Debit",
            exp_month=12,
            exp_year=2025,
            cvv="123",
            account_type=AccountType.DEBIT,
            account_balance=50000,  # $500
        )
    
    def authorize(self, request: AuthorizationRequest) -> AuthorizationResponse:
        """
        Process an authorization request.
        
        This is what happens when the card network asks the issuing bank
        to authorize a transaction.
        """
        with self._lock:
            # Find the account
            account = self._accounts.get(request.card_number)
            
            if not account:
                return AuthorizationResponse(
                    request_id=request.request_id,
                    approved=False,
                    decline_reason="invalid_card"
                )
            
            # Check card status
            if account.status == CardStatus.BLOCKED:
                return AuthorizationResponse(
                    request_id=request.request_id,
                    approved=False,
                    decline_reason="card_declined"
                )
            
            if account.status == CardStatus.LOST_STOLEN:
                return AuthorizationResponse(
                    request_id=request.request_id,
                    approved=False,
                    decline_reason="pickup_card"  # Actual decline code!
                )
            
            if account.status == CardStatus.FRAUD_SUSPECT:
                return AuthorizationResponse(
                    request_id=request.request_id,
                    approved=False,
                    decline_reason="fraudulent"
                )
            
            # Check expiration
            now = datetime.now()
            exp_date = datetime(account.exp_year, account.exp_month, 1)
            if now > exp_date + timedelta(days=31):
                return AuthorizationResponse(
                    request_id=request.request_id,
                    approved=False,
                    decline_reason="expired_card"
                )
            
            # Verify CVV
            cvv_result = "M" if request.cvv == account.cvv else "N"
            if cvv_result == "N":
                return AuthorizationResponse(
                    request_id=request.request_id,
                    approved=False,
                    decline_reason="incorrect_cvc",
                    cvv_result="N"
                )
            
            # Check transaction limit
            if request.amount > account.single_transaction_limit:
                return AuthorizationResponse(
                    request_id=request.request_id,
                    approved=False,
                    decline_reason="transaction_not_allowed"
                )
            
            # Check available funds
            if account.account_type == AccountType.CREDIT:
                available = account.available_credit
            else:
                available = account.available_balance
            
            if request.amount > available:
                return AuthorizationResponse(
                    request_id=request.request_id,
                    approved=False,
                    decline_reason="insufficient_funds"
                )
            
            # Check velocity
            if not self._check_velocity(request.card_number, account.velocity_limit):
                return AuthorizationResponse(
                    request_id=request.request_id,
                    approved=False,
                    decline_reason="withdrawal_count_limit_exceeded"
                )
            
            # Approved - create hold
            auth_code = secrets.token_hex(3).upper()
            account.holds[request.request_id] = request.amount
            
            # Record transaction
            self._record_transaction(request.card_number)
            
            return AuthorizationResponse(
                request_id=request.request_id,
                approved=True,
                auth_code=auth_code,
                cvv_result=cvv_result
            )
    
    def capture(self, auth_id: str, amount: int) -> bool:
        """
        Capture a previously authorized transaction.
        
        Moves funds from hold to actual charge.
        """
        with self._lock:
            # Find the account with this hold
            for account in self._accounts.values():
                if auth_id in account.holds:
                    held_amount = account.holds[auth_id]
                    
                    # Can only capture up to held amount
                    if amount > held_amount:
                        return False
                    
                    # Remove hold
                    del account.holds[auth_id]
                    
                    # Apply charge
                    if account.account_type == AccountType.CREDIT:
                        account.current_balance += amount
                    else:
                        account.account_balance -= amount
                    
                    return True
            
            return False
    
    def void(self, auth_id: str) -> bool:
        """
        Void an authorization (release the hold).
        """
        with self._lock:
            for account in self._accounts.values():
                if auth_id in account.holds:
                    del account.holds[auth_id]
                    return True
            return False
    
    def refund(self, card_number: str, amount: int) -> bool:
        """
        Process a refund to a card.
        """
        with self._lock:
            account = self._accounts.get(card_number)
            if not account:
                return False
            
            if account.account_type == AccountType.CREDIT:
                account.current_balance -= amount
            else:
                account.account_balance += amount
            
            return True
    
    def _check_velocity(self, card_number: str, limit: int) -> bool:
        """Check if card is within velocity limits."""
        now = datetime.now()
        cutoff = now - timedelta(hours=1)
        
        history = self._transaction_history.get(card_number, [])
        recent = [t for t in history if t > cutoff]
        
        return len(recent) < limit
    
    def _record_transaction(self, card_number: str):
        """Record a transaction for velocity tracking."""
        if card_number not in self._transaction_history:
            self._transaction_history[card_number] = []
        self._transaction_history[card_number].append(datetime.now())
    
    def get_account_status(self, card_number: str) -> Optional[Dict]:
        """Get account status (for debugging/demo)."""
        account = self._accounts.get(card_number)
        if not account:
            return None
        
        return {
            "card_number": f"****{card_number[-4:]}",
            "status": account.status.value,
            "type": account.account_type.value,
            "available": (
                account.available_credit 
                if account.account_type == AccountType.CREDIT 
                else account.available_balance
            ),
            "holds": len(account.holds),
            "holds_total": sum(account.holds.values())
        }


# =============================================================================
# Demo
# =============================================================================

def demo_issuing_bank():
    """Demonstrate issuing bank operations."""
    print("=" * 60)
    print("ISSUING BANK SIMULATION")
    print("=" * 60)
    
    bank = IssuingBank("Demo National Bank")
    
    # Test successful authorization
    print("\n1. Successful authorization:")
    response = bank.authorize(AuthorizationRequest(
        request_id="auth_001",
        card_number="4242424242424242",
        exp_month=12,
        exp_year=2025,
        cvv="123",
        amount=5000,  # $50
        currency="USD",
        merchant_id="merch_123",
        merchant_name="Test Store",
        merchant_category="5411"
    ))
    print(f"   Approved: {response.approved}")
    print(f"   Auth code: {response.auth_code}")
    
    # Check account status
    print("\n2. Account status after auth:")
    status = bank.get_account_status("4242424242424242")
    print(f"   Available: ${status['available']/100:.2f}")
    print(f"   Holds: {status['holds']} (${status['holds_total']/100:.2f})")
    
    # Capture
    print("\n3. Capturing authorization:")
    captured = bank.capture("auth_001", 5000)
    print(f"   Captured: {captured}")
    
    status = bank.get_account_status("4242424242424242")
    print(f"   Available after capture: ${status['available']/100:.2f}")
    
    # Test insufficient funds
    print("\n4. Insufficient funds:")
    response = bank.authorize(AuthorizationRequest(
        request_id="auth_002",
        card_number="4000000000009995",
        exp_month=12,
        exp_year=2025,
        cvv="123",
        amount=5000,
        currency="USD",
        merchant_id="merch_123",
        merchant_name="Test Store",
        merchant_category="5411"
    ))
    print(f"   Approved: {response.approved}")
    print(f"   Decline reason: {response.decline_reason}")
    
    # Test blocked card
    print("\n5. Blocked card:")
    response = bank.authorize(AuthorizationRequest(
        request_id="auth_003",
        card_number="4000000000000002",
        exp_month=12,
        exp_year=2025,
        cvv="123",
        amount=5000,
        currency="USD",
        merchant_id="merch_123",
        merchant_name="Test Store",
        merchant_category="5411"
    ))
    print(f"   Approved: {response.approved}")
    print(f"   Decline reason: {response.decline_reason}")
    
    # Test wrong CVV
    print("\n6. Wrong CVV:")
    response = bank.authorize(AuthorizationRequest(
        request_id="auth_004",
        card_number="4242424242424242",
        exp_month=12,
        exp_year=2025,
        cvv="999",  # Wrong!
        amount=5000,
        currency="USD",
        merchant_id="merch_123",
        merchant_name="Test Store",
        merchant_category="5411"
    ))
    print(f"   Approved: {response.approved}")
    print(f"   Decline reason: {response.decline_reason}")
    print(f"   CVV result: {response.cvv_result}")


if __name__ == "__main__":
    demo_issuing_bank()
