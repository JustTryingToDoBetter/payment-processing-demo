"""
Merchant Payment Client

This is what a merchant's backend uses to communicate with
the payment gateway. Similar to Stripe's stripe-python library.

Example usage:
    client = PaymentClient(api_key="sk_test_...")
    
    # Create a charge
    charge = client.charges.create(
        amount=2499,
        currency="usd",
        source=token_id,
        description="Order #123"
    )
"""

import json
import urllib.request
import urllib.error
from typing import Dict, Optional, Any
from dataclasses import dataclass


class PaymentError(Exception):
    """Base exception for payment errors."""
    def __init__(self, message: str, code: str = None, http_status: int = None):
        super().__init__(message)
        self.message = message
        self.code = code
        self.http_status = http_status


class AuthenticationError(PaymentError):
    """Invalid API key."""
    pass


class InvalidRequestError(PaymentError):
    """Invalid request parameters."""
    pass


class CardError(PaymentError):
    """Card was declined."""
    def __init__(self, message: str, decline_code: str = None, **kwargs):
        super().__init__(message, **kwargs)
        self.decline_code = decline_code


class RateLimitError(PaymentError):
    """Too many requests."""
    pass


@dataclass
class PaymentResponse:
    """Wrapper for API responses."""
    data: Dict
    
    def __getattr__(self, name):
        return self.data.get(name)
    
    def __getitem__(self, key):
        return self.data[key]
    
    def to_dict(self) -> Dict:
        return self.data


class APIResource:
    """Base class for API resources."""
    
    def __init__(self, client: 'PaymentClient'):
        self.client = client
    
    def _request(
        self,
        method: str,
        path: str,
        data: Dict = None,
        idempotency_key: str = None
    ) -> Dict:
        """Make an API request."""
        return self.client._request(method, path, data, idempotency_key)


class TokensResource(APIResource):
    """
    Tokens API.
    
    Tokens are single-use and represent a card that can be charged.
    Typically created client-side (in the browser/app).
    """
    
    def create(
        self,
        card_number: str,
        exp_month: int,
        exp_year: int,
        cvv: str,
        name: str = None
    ) -> PaymentResponse:
        """
        Create a token from card details.
        
        NOTE: In production, this would ONLY be called from the frontend
        (via JavaScript SDK). Card details should never touch your server.
        This is here for testing only.
        """
        data = {
            "card_number": card_number,
            "exp_month": exp_month,
            "exp_year": exp_year,
            "cvv": cvv,
        }
        if name:
            data["name"] = name
        
        return PaymentResponse(self._request("POST", "/v1/tokens", data))
    
    def retrieve(self, token_id: str) -> PaymentResponse:
        """Retrieve a token by ID."""
        return PaymentResponse(self._request("GET", f"/v1/tokens/{token_id}"))


class ChargesResource(APIResource):
    """
    Charges API.
    
    Charges represent a payment. Create a charge to collect payment.
    """
    
    def create(
        self,
        amount: int,
        currency: str,
        source: str,  # token ID
        description: str = None,
        capture: bool = True,
        idempotency_key: str = None,
        metadata: Dict = None
    ) -> PaymentResponse:
        """
        Create a charge.
        
        Args:
            amount: Amount in cents (e.g., 2499 for $24.99)
            currency: Three-letter ISO currency code (e.g., "usd")
            source: Token ID from tokenization
            description: Optional description
            capture: Whether to immediately capture (default True)
            idempotency_key: Unique key for idempotent request
            metadata: Additional data to store with charge
            
        Returns:
            Charge object
        """
        data = {
            "amount": amount,
            "currency": currency,
            "token": source,
            "capture": capture,
        }
        if description:
            data["description"] = description
        if metadata:
            data["metadata"] = metadata
        
        return PaymentResponse(
            self._request("POST", "/v1/charges", data, idempotency_key)
        )
    
    def retrieve(self, charge_id: str) -> PaymentResponse:
        """Retrieve a charge by ID."""
        return PaymentResponse(self._request("GET", f"/v1/charges/{charge_id}"))
    
    def capture(
        self,
        charge_id: str,
        amount: int = None
    ) -> PaymentResponse:
        """
        Capture a previously authorized charge.
        
        Args:
            charge_id: The charge to capture
            amount: Optional amount to capture (for partial capture)
        """
        data = {}
        if amount is not None:
            data["amount"] = amount
        
        return PaymentResponse(
            self._request("POST", f"/v1/charges/{charge_id}/capture", data)
        )


class RefundsResource(APIResource):
    """
    Refunds API.
    
    Create refunds for previously successful charges.
    """
    
    def create(
        self,
        charge: str,
        amount: int = None,
        reason: str = None,
        idempotency_key: str = None
    ) -> PaymentResponse:
        """
        Create a refund.
        
        Args:
            charge: ID of charge to refund
            amount: Amount to refund in cents (default: full amount)
            reason: Reason for refund (duplicate, fraudulent, requested_by_customer)
            idempotency_key: Unique key for idempotent request
            
        Returns:
            Refund object
        """
        data = {"charge": charge}
        if amount is not None:
            data["amount"] = amount
        if reason:
            data["reason"] = reason
        
        return PaymentResponse(
            self._request("POST", "/v1/refunds", data, idempotency_key)
        )
    
    def retrieve(self, refund_id: str) -> PaymentResponse:
        """Retrieve a refund by ID."""
        return PaymentResponse(self._request("GET", f"/v1/refunds/{refund_id}"))


class PaymentClient:
    """
    Payment Gateway Client.
    
    Usage:
        client = PaymentClient(api_key="sk_test_...")
        
        # Create a charge
        charge = client.charges.create(
            amount=2499,
            currency="usd",
            source="tok_xxx"
        )
        
        # Refund a charge
        refund = client.refunds.create(
            charge=charge.id
        )
    """
    
    DEFAULT_API_BASE = "http://localhost:8080"
    
    def __init__(
        self,
        api_key: str,
        api_base: str = None,
        timeout: int = 30
    ):
        """
        Initialize the payment client.
        
        Args:
            api_key: Your API key (starts with sk_test_ or sk_live_)
            api_base: API base URL (default: localhost for demo)
            timeout: Request timeout in seconds
        """
        self.api_key = api_key
        self.api_base = api_base or self.DEFAULT_API_BASE
        self.timeout = timeout
        
        # Initialize resources
        self.tokens = TokensResource(self)
        self.charges = ChargesResource(self)
        self.refunds = RefundsResource(self)
    
    def _request(
        self,
        method: str,
        path: str,
        data: Dict = None,
        idempotency_key: str = None
    ) -> Dict:
        """
        Make an HTTP request to the API.
        
        Handles:
        - Authentication via Bearer token
        - JSON encoding/decoding
        - Error handling
        - Idempotency keys
        """
        url = f"{self.api_base}{path}"
        
        # Build headers
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        
        # Build request
        body = json.dumps(data).encode('utf-8') if data else None
        request = urllib.request.Request(url, data=body, headers=headers, method=method)
        
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                response_body = response.read().decode('utf-8')
                return json.loads(response_body)
                
        except urllib.error.HTTPError as e:
            response_body = e.read().decode('utf-8')
            try:
                error_data = json.loads(response_body)
                error_info = error_data.get("error", {})
            except json.JSONDecodeError:
                error_info = {"message": response_body}
            
            self._handle_error(e.code, error_info)
            
        except urllib.error.URLError as e:
            raise PaymentError(f"Connection error: {e.reason}")
    
    def _handle_error(self, status_code: int, error_info: Dict):
        """Convert HTTP errors to appropriate exceptions."""
        message = error_info.get("message", "Unknown error")
        code = error_info.get("code")
        
        if status_code == 401:
            raise AuthenticationError(message, code=code, http_status=401)
        elif status_code == 402:
            raise CardError(
                message,
                decline_code=error_info.get("decline_code"),
                code=code,
                http_status=402
            )
        elif status_code == 400:
            raise InvalidRequestError(message, code=code, http_status=400)
        elif status_code == 429:
            raise RateLimitError(message, code=code, http_status=429)
        else:
            raise PaymentError(message, code=code, http_status=status_code)


# =============================================================================
# Convenience function
# =============================================================================

_default_client: Optional[PaymentClient] = None


def set_api_key(api_key: str, api_base: str = None):
    """
    Set the default API key for the module.
    
    After calling this, you can use the module-level functions:
        import payment_client as payments
        payments.set_api_key("sk_test_...")
        
        charge = payments.Charge.create(...)
    """
    global _default_client
    _default_client = PaymentClient(api_key, api_base)


def get_client() -> PaymentClient:
    """Get the default client."""
    if _default_client is None:
        raise PaymentError("API key not set. Call set_api_key() first.")
    return _default_client


# =============================================================================
# Demo
# =============================================================================

def demo_payment_client():
    """Demonstrate the payment client."""
    print("=" * 60)
    print("PAYMENT CLIENT DEMO")
    print("=" * 60)
    
    # Note: This requires the gateway server to be running
    print("\nNOTE: This demo requires the gateway server to be running.")
    print("Start it with: python -m src.gateway.server")
    
    # Create client
    client = PaymentClient(api_key="sk_test_demo123456789")
    
    print("\n1. Creating a token (normally done client-side):")
    try:
        token = client.tokens.create(
            card_number="4242424242424242",
            exp_month=12,
            exp_year=2025,
            cvv="123",
            name="Test User"
        )
        print(f"   Token: {token.id}")
        print(f"   Card: {token.data.get('card', {}).get('brand')} ****{token.data.get('card', {}).get('last4')}")
        
        print("\n2. Creating a charge:")
        charge = client.charges.create(
            amount=2499,
            currency="usd",
            source=token.id,
            description="Test order",
            idempotency_key="demo-charge-001"
        )
        print(f"   Charge: {charge.id}")
        print(f"   Amount: ${charge.data.get('amount', 0)/100:.2f}")
        print(f"   Status: {charge.data.get('status')}")
        
        print("\n3. Creating a refund:")
        refund = client.refunds.create(
            charge=charge.id,
            amount=1000,  # Partial refund of $10
            reason="requested_by_customer"
        )
        print(f"   Refund: {refund.id}")
        print(f"   Amount: ${refund.data.get('amount', 0)/100:.2f}")
        
    except PaymentError as e:
        print(f"\n   Error: {e.message}")
        print("   Make sure the gateway server is running!")
    
    print("\n4. Example usage in your code:")
    print("""
    from payment_client import PaymentClient
    
    client = PaymentClient(api_key="sk_test_...")
    
    # Create charge with idempotency key
    charge = client.charges.create(
        amount=2499,
        currency="usd",
        source=token_id,
        description=f"Order #{order_id}",
        idempotency_key=f"order-{order_id}"
    )
    
    if charge.data.get('paid'):
        # Success! Fulfill the order
        fulfill_order(order_id)
    else:
        # Handle failure
        handle_failure(charge.data.get('failure_code'))
    """)


if __name__ == "__main__":
    demo_payment_client()
