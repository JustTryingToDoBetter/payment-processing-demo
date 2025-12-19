"""
Simulated Card Network (Visa, Mastercard, etc.)

The card network sits between the acquiring bank (merchant's bank)
and the issuing bank (customer's bank). It:

1. Routes transactions to the correct issuing bank
2. Enforces network rules
3. Handles interbank settlement
4. Provides dispute resolution
5. Manages fraud detection at network level

Major networks: Visa, Mastercard, American Express, Discover
"""

import secrets
import threading
from datetime import datetime
from dataclasses import dataclass
from typing import Dict, Optional
from enum import Enum

from .issuing_bank import IssuingBank, AuthorizationRequest, AuthorizationResponse


class NetworkType(str, Enum):
    """Card network types."""
    VISA = "visa"
    MASTERCARD = "mastercard"
    AMEX = "amex"
    DISCOVER = "discover"


@dataclass
class NetworkTransaction:
    """
    A transaction record at the network level.
    """
    transaction_id: str
    network: NetworkType
    acquirer_id: str
    issuer_id: str
    amount: int
    currency: str
    auth_code: Optional[str]
    status: str
    created_at: datetime
    metadata: Dict


class CardNetwork:
    """
    Simulated card network (Visa-like).
    
    In reality, Visa and Mastercard operate massive global networks
    that process billions of transactions. This simulation shows
    the basic concepts.
    """
    
    # BIN ranges for card detection (simplified)
    # In reality, there are detailed BIN tables
    BIN_RANGES = {
        "4": NetworkType.VISA,      # Visa starts with 4
        "5": NetworkType.MASTERCARD, # MC starts with 51-55
        "34": NetworkType.AMEX,      # Amex starts with 34 or 37
        "37": NetworkType.AMEX,
        "6": NetworkType.DISCOVER,   # Discover starts with 6
    }
    
    def __init__(self, network_type: NetworkType = NetworkType.VISA):
        self.network_type = network_type
        
        # Issuing banks registered with this network
        self._issuers: Dict[str, IssuingBank] = {}
        
        # Transaction log
        self._transactions: Dict[str, NetworkTransaction] = {}
        
        # Network fees (basis points)
        self.interchange_fee_bps = 200  # 2%
        self.assessment_fee_bps = 13    # 0.13%
        
        self._lock = threading.Lock()
        
        # Register a default issuer
        self._register_default_issuer()
    
    def _register_default_issuer(self):
        """Set up a default issuing bank."""
        self._issuers["default"] = IssuingBank("Demo Issuing Bank")
    
    def detect_network(self, card_number: str) -> Optional[NetworkType]:
        """Detect which network a card belongs to."""
        # Check 2-digit prefix first
        if card_number[:2] in self.BIN_RANGES:
            return self.BIN_RANGES[card_number[:2]]
        # Check 1-digit prefix
        if card_number[0] in self.BIN_RANGES:
            return self.BIN_RANGES[card_number[0]]
        return None
    
    def route_authorization(
        self,
        acquirer_id: str,
        card_number: str,
        exp_month: int,
        exp_year: int,
        cvv: str,
        amount: int,
        currency: str,
        merchant_id: str,
        merchant_name: str,
        merchant_category: str
    ) -> Dict:
        """
        Route an authorization request through the network.
        
        This is what happens when the acquiring bank sends a transaction
        to the card network:
        
        1. Validate the transaction format
        2. Identify the issuing bank
        3. Forward to issuer for authorization
        4. Return response to acquirer
        5. Log transaction for settlement
        """
        transaction_id = f"nt_{secrets.token_hex(12)}"
        
        # Validate card network
        network = self.detect_network(card_number)
        if network != self.network_type:
            return {
                "success": False,
                "error": f"Card not valid for {self.network_type.value} network"
            }
        
        # Find the issuing bank (simplified - using default)
        issuer = self._issuers.get("default")
        if not issuer:
            return {
                "success": False,
                "error": "No issuing bank found for card"
            }
        
        # Create authorization request
        auth_request = AuthorizationRequest(
            request_id=transaction_id,
            card_number=card_number,
            exp_month=exp_month,
            exp_year=exp_year,
            cvv=cvv,
            amount=amount,
            currency=currency,
            merchant_id=merchant_id,
            merchant_name=merchant_name,
            merchant_category=merchant_category
        )
        
        # Forward to issuer
        response = issuer.authorize(auth_request)
        
        # Calculate fees
        interchange = int(amount * self.interchange_fee_bps / 10000)
        assessment = int(amount * self.assessment_fee_bps / 10000)
        
        # Log transaction
        with self._lock:
            self._transactions[transaction_id] = NetworkTransaction(
                transaction_id=transaction_id,
                network=self.network_type,
                acquirer_id=acquirer_id,
                issuer_id="default",
                amount=amount,
                currency=currency,
                auth_code=response.auth_code,
                status="approved" if response.approved else "declined",
                created_at=datetime.utcnow(),
                metadata={
                    "merchant_id": merchant_id,
                    "decline_reason": response.decline_reason,
                    "interchange_fee": interchange,
                    "assessment_fee": assessment
                }
            )
        
        return {
            "success": response.approved,
            "transaction_id": transaction_id,
            "auth_code": response.auth_code,
            "decline_reason": response.decline_reason,
            "avs_result": response.avs_result,
            "cvv_result": response.cvv_result,
            "fees": {
                "interchange": interchange,
                "assessment": assessment,
                "total": interchange + assessment
            }
        }
    
    def capture(self, transaction_id: str, amount: int) -> Dict:
        """
        Capture a previously authorized transaction.
        
        The network routes the capture request to the issuing bank.
        """
        with self._lock:
            transaction = self._transactions.get(transaction_id)
        
        if not transaction:
            return {"success": False, "error": "Transaction not found"}
        
        if transaction.status != "approved":
            return {"success": False, "error": "Transaction not authorized"}
        
        # Route to issuer
        issuer = self._issuers.get(transaction.issuer_id)
        if issuer:
            captured = issuer.capture(transaction_id, amount)
            if captured:
                transaction.status = "captured"
                return {"success": True, "amount_captured": amount}
        
        return {"success": False, "error": "Capture failed"}
    
    def void(self, transaction_id: str) -> Dict:
        """Void an authorized transaction."""
        with self._lock:
            transaction = self._transactions.get(transaction_id)
        
        if not transaction:
            return {"success": False, "error": "Transaction not found"}
        
        issuer = self._issuers.get(transaction.issuer_id)
        if issuer:
            voided = issuer.void(transaction_id)
            if voided:
                transaction.status = "voided"
                return {"success": True}
        
        return {"success": False, "error": "Void failed"}
    
    def get_transaction(self, transaction_id: str) -> Optional[Dict]:
        """Get transaction details."""
        transaction = self._transactions.get(transaction_id)
        if not transaction:
            return None
        
        return {
            "id": transaction.transaction_id,
            "network": transaction.network.value,
            "amount": transaction.amount,
            "currency": transaction.currency,
            "status": transaction.status,
            "auth_code": transaction.auth_code,
            "fees": transaction.metadata.get("interchange_fee", 0) + 
                    transaction.metadata.get("assessment_fee", 0),
            "created_at": transaction.created_at.isoformat()
        }


# =============================================================================
# Demo
# =============================================================================

def demo_card_network():
    """Demonstrate card network operations."""
    print("=" * 60)
    print("CARD NETWORK SIMULATION (VISA)")
    print("=" * 60)
    
    network = CardNetwork(NetworkType.VISA)
    
    # Route a transaction
    print("\n1. Routing authorization through network:")
    result = network.route_authorization(
        acquirer_id="acq_demo123",
        card_number="4242424242424242",
        exp_month=12,
        exp_year=2025,
        cvv="123",
        amount=10000,  # $100
        currency="USD",
        merchant_id="merch_123",
        merchant_name="Demo Store",
        merchant_category="5411"
    )
    print(f"   Success: {result['success']}")
    print(f"   Transaction ID: {result['transaction_id']}")
    print(f"   Auth code: {result['auth_code']}")
    print(f"   Interchange fee: ${result['fees']['interchange']/100:.2f}")
    print(f"   Assessment fee: ${result['fees']['assessment']/100:.2f}")
    
    # Capture
    print("\n2. Capturing transaction:")
    capture_result = network.capture(result['transaction_id'], 10000)
    print(f"   Captured: {capture_result['success']}")
    
    # Check transaction status
    print("\n3. Transaction details:")
    details = network.get_transaction(result['transaction_id'])
    print(f"   Status: {details['status']}")
    print(f"   Total fees: ${details['fees']/100:.2f}")
    
    # Test wrong network
    print("\n4. Testing wrong network (Mastercard on Visa network):")
    result = network.route_authorization(
        acquirer_id="acq_demo123",
        card_number="5555555555554444",  # Mastercard
        exp_month=12,
        exp_year=2025,
        cvv="123",
        amount=5000,
        currency="USD",
        merchant_id="merch_123",
        merchant_name="Demo Store",
        merchant_category="5411"
    )
    print(f"   Success: {result['success']}")
    print(f"   Error: {result.get('error')}")


if __name__ == "__main__":
    demo_card_network()
