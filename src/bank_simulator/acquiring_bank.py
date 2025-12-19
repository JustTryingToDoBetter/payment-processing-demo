"""
Simulated Acquiring Bank (Merchant's Bank)

The acquiring bank is the merchant's bank that:
1. Provides the merchant with a merchant account
2. Settles funds to the merchant
3. Handles chargebacks
4. Connects to card networks on behalf of merchants

In many modern setups, payment processors like Stripe act
as a payment facilitator (PayFac) with their own acquiring
bank relationships, abstracting this complexity.
"""

import secrets
import threading
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from typing import Dict, List, Optional
from enum import Enum

from .card_network import CardNetwork, NetworkType


class SettlementStatus(str, Enum):
    """Settlement status."""
    PENDING = "pending"
    BATCHED = "batched"
    SETTLED = "settled"
    FAILED = "failed"


class MerchantStatus(str, Enum):
    """Merchant account status."""
    ACTIVE = "active"
    SUSPENDED = "suspended"
    CLOSED = "closed"
    UNDER_REVIEW = "under_review"


@dataclass
class MerchantAccount:
    """
    A merchant account with the acquiring bank.
    """
    merchant_id: str
    business_name: str
    status: MerchantStatus = MerchantStatus.ACTIVE
    
    # Pricing
    discount_rate_bps: int = 290  # 2.9% + fixed
    fixed_fee_cents: int = 30     # 30 cents
    
    # Settlement
    settlement_delay_days: int = 2
    pending_settlement: int = 0   # Cents awaiting settlement
    
    # Risk settings
    monthly_volume_limit: int = 10000000  # $100,000
    current_month_volume: int = 0
    chargeback_rate: float = 0.0
    
    # MCC (Merchant Category Code)
    mcc: str = "5411"  # Grocery stores


@dataclass
class AcquirerTransaction:
    """
    Transaction record at the acquiring bank.
    """
    transaction_id: str
    merchant_id: str
    network_transaction_id: str
    amount: int
    currency: str
    fees: int  # Total fees charged
    net_amount: int  # Amount after fees
    settlement_status: SettlementStatus
    settlement_date: Optional[datetime] = None
    created_at: datetime = field(default_factory=datetime.utcnow)


class AcquiringBank:
    """
    Simulated acquiring bank / payment processor.
    
    This represents what Stripe, Square, or a traditional
    acquiring bank does.
    """
    
    def __init__(self, bank_name: str = "Demo Acquiring Bank"):
        self.bank_name = bank_name
        
        # Merchant accounts
        self._merchants: Dict[str, MerchantAccount] = {}
        
        # Card networks
        self._networks: Dict[NetworkType, CardNetwork] = {
            NetworkType.VISA: CardNetwork(NetworkType.VISA),
            NetworkType.MASTERCARD: CardNetwork(NetworkType.MASTERCARD),
        }
        
        # Transaction log
        self._transactions: Dict[str, AcquirerTransaction] = {}
        
        # Settlement batches
        self._batches: List[Dict] = []
        
        self._lock = threading.Lock()
        
        # Set up test merchant
        self._setup_test_merchant()
    
    def _setup_test_merchant(self):
        """Create a test merchant account."""
        self._merchants["merch_demo123"] = MerchantAccount(
            merchant_id="merch_demo123",
            business_name="Demo Store",
            mcc="5411"
        )
    
    def create_merchant(
        self,
        business_name: str,
        mcc: str = "5411"
    ) -> MerchantAccount:
        """Onboard a new merchant."""
        merchant = MerchantAccount(
            merchant_id=f"merch_{secrets.token_hex(8)}",
            business_name=business_name,
            mcc=mcc
        )
        self._merchants[merchant.merchant_id] = merchant
        return merchant
    
    def process_authorization(
        self,
        merchant_id: str,
        card_number: str,
        exp_month: int,
        exp_year: int,
        cvv: str,
        amount: int,
        currency: str
    ) -> Dict:
        """
        Process an authorization request from a merchant.
        
        1. Validate merchant
        2. Determine card network
        3. Route to network
        4. Calculate fees
        5. Return result
        """
        # Validate merchant
        merchant = self._merchants.get(merchant_id)
        if not merchant:
            return {"success": False, "error": "Invalid merchant"}
        
        if merchant.status != MerchantStatus.ACTIVE:
            return {"success": False, "error": f"Merchant {merchant.status.value}"}
        
        # Check volume limits
        if merchant.current_month_volume + amount > merchant.monthly_volume_limit:
            return {"success": False, "error": "Monthly volume limit exceeded"}
        
        # Determine network
        network = self._detect_and_get_network(card_number)
        if not network:
            return {"success": False, "error": "Unsupported card network"}
        
        # Route to network
        network_result = network.route_authorization(
            acquirer_id=self.bank_name,
            card_number=card_number,
            exp_month=exp_month,
            exp_year=exp_year,
            cvv=cvv,
            amount=amount,
            currency=currency,
            merchant_id=merchant_id,
            merchant_name=merchant.business_name,
            merchant_category=merchant.mcc
        )
        
        if not network_result["success"]:
            return network_result
        
        # Calculate our fees
        discount_fee = int(amount * merchant.discount_rate_bps / 10000)
        total_fee = discount_fee + merchant.fixed_fee_cents
        net_amount = amount - total_fee
        
        # Create transaction record
        transaction_id = f"txn_{secrets.token_hex(12)}"
        
        with self._lock:
            self._transactions[transaction_id] = AcquirerTransaction(
                transaction_id=transaction_id,
                merchant_id=merchant_id,
                network_transaction_id=network_result["transaction_id"],
                amount=amount,
                currency=currency,
                fees=total_fee,
                net_amount=net_amount,
                settlement_status=SettlementStatus.PENDING
            )
            
            # Update merchant volume
            merchant.current_month_volume += amount
        
        return {
            "success": True,
            "transaction_id": transaction_id,
            "network_transaction_id": network_result["transaction_id"],
            "auth_code": network_result["auth_code"],
            "amount": amount,
            "fees": {
                "discount": discount_fee,
                "fixed": merchant.fixed_fee_cents,
                "network": network_result["fees"]["total"],
                "total": total_fee + network_result["fees"]["total"]
            },
            "net_amount": net_amount - network_result["fees"]["total"]
        }
    
    def capture(self, transaction_id: str, amount: Optional[int] = None) -> Dict:
        """Capture an authorized transaction."""
        with self._lock:
            transaction = self._transactions.get(transaction_id)
        
        if not transaction:
            return {"success": False, "error": "Transaction not found"}
        
        # Get the network
        network = list(self._networks.values())[0]  # Simplified
        
        # Capture on network
        capture_amount = amount or transaction.amount
        result = network.capture(
            transaction.network_transaction_id,
            capture_amount
        )
        
        if result["success"]:
            # Update for settlement
            merchant = self._merchants.get(transaction.merchant_id)
            if merchant:
                merchant.pending_settlement += transaction.net_amount
        
        return result
    
    def create_settlement_batch(self) -> Dict:
        """
        Create a settlement batch for all pending transactions.
        
        In production, this runs daily (often multiple times).
        """
        batch_id = f"batch_{secrets.token_hex(8)}"
        batch_transactions = []
        total_amount = 0
        total_fees = 0
        
        with self._lock:
            for txn in self._transactions.values():
                if txn.settlement_status == SettlementStatus.PENDING:
                    txn.settlement_status = SettlementStatus.BATCHED
                    txn.settlement_date = datetime.utcnow() + timedelta(days=2)
                    batch_transactions.append(txn.transaction_id)
                    total_amount += txn.amount
                    total_fees += txn.fees
            
            batch = {
                "id": batch_id,
                "transactions": batch_transactions,
                "total_amount": total_amount,
                "total_fees": total_fees,
                "net_amount": total_amount - total_fees,
                "created_at": datetime.utcnow().isoformat()
            }
            self._batches.append(batch)
        
        return batch
    
    def _detect_and_get_network(self, card_number: str) -> Optional[CardNetwork]:
        """Detect card network and return the handler."""
        first_digit = card_number[0]
        
        if first_digit == "4":
            return self._networks.get(NetworkType.VISA)
        elif first_digit == "5":
            return self._networks.get(NetworkType.MASTERCARD)
        
        return None
    
    def get_merchant_balance(self, merchant_id: str) -> Optional[Dict]:
        """Get a merchant's balance and pending settlements."""
        merchant = self._merchants.get(merchant_id)
        if not merchant:
            return None
        
        pending_count = 0
        pending_amount = 0
        
        for txn in self._transactions.values():
            if txn.merchant_id == merchant_id:
                if txn.settlement_status in [SettlementStatus.PENDING, SettlementStatus.BATCHED]:
                    pending_count += 1
                    pending_amount += txn.net_amount
        
        return {
            "merchant_id": merchant_id,
            "business_name": merchant.business_name,
            "pending_transactions": pending_count,
            "pending_amount": pending_amount,
            "current_month_volume": merchant.current_month_volume
        }


# =============================================================================
# Demo
# =============================================================================

def demo_acquiring_bank():
    """Demonstrate acquiring bank operations."""
    print("=" * 60)
    print("ACQUIRING BANK SIMULATION")
    print("=" * 60)
    
    acquirer = AcquiringBank("Demo Payments Inc")
    
    # Process an authorization
    print("\n1. Processing authorization:")
    result = acquirer.process_authorization(
        merchant_id="merch_demo123",
        card_number="4242424242424242",
        exp_month=12,
        exp_year=2025,
        cvv="123",
        amount=10000,  # $100
        currency="USD"
    )
    print(f"   Success: {result['success']}")
    print(f"   Transaction ID: {result['transaction_id']}")
    print(f"   Auth code: {result['auth_code']}")
    print(f"   Gross amount: ${result['amount']/100:.2f}")
    print(f"   Fees breakdown:")
    print(f"      Discount rate: ${result['fees']['discount']/100:.2f}")
    print(f"      Fixed fee: ${result['fees']['fixed']/100:.2f}")
    print(f"      Network fees: ${result['fees']['network']/100:.2f}")
    print(f"      Total fees: ${result['fees']['total']/100:.2f}")
    print(f"   Net to merchant: ${result['net_amount']/100:.2f}")
    
    # Capture
    print("\n2. Capturing transaction:")
    capture_result = acquirer.capture(result['transaction_id'])
    print(f"   Captured: {capture_result['success']}")
    
    # Merchant balance
    print("\n3. Merchant balance:")
    balance = acquirer.get_merchant_balance("merch_demo123")
    print(f"   Pending transactions: {balance['pending_transactions']}")
    print(f"   Pending amount: ${balance['pending_amount']/100:.2f}")
    
    # Create settlement batch
    print("\n4. Creating settlement batch:")
    batch = acquirer.create_settlement_batch()
    print(f"   Batch ID: {batch['id']}")
    print(f"   Transactions: {len(batch['transactions'])}")
    print(f"   Total amount: ${batch['total_amount']/100:.2f}")
    print(f"   Total fees: ${batch['total_fees']/100:.2f}")
    print(f"   Net settlement: ${batch['net_amount']/100:.2f}")


if __name__ == "__main__":
    demo_acquiring_bank()
