"""
HTTP API server for the payment gateway.

This provides REST endpoints for the payment gateway operations:
- Tokenization (card → token)
- Charges (create, capture, refund)
- Payment intents (for 3DS flows)
- Webhook endpoint management

This uses Python's built-in http.server for simplicity.
In production, you'd use Flask, FastAPI, Django, etc.
"""

import json
import secrets
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from typing import Dict, Any, Optional
from datetime import datetime
from functools import wraps

# Import our gateway components
from .tokenization import TokenizationService
from .authorization import AuthorizationService
from .fraud_detection import FraudDetector
from .webhooks import WebhookDispatcher, EventType
from .models import Card, TokenizeRequest, ChargeRequest, RefundRequest
from ..shared.encryption import CardMasker
from ..shared.idempotency import IdempotencyService, RequestInProgress
from ..shared.constants import PaymentStatus, Currency


class PaymentGateway:
    """
    Main gateway coordinating all services.
    
    This is the orchestrator that brings together:
    - Tokenization
    - Authorization
    - Fraud detection
    - Webhooks
    - Idempotency
    """
    
    def __init__(self):
        self.tokenization = TokenizationService()
        self.authorization = AuthorizationService()
        self.fraud_detector = FraudDetector()
        self.webhooks = WebhookDispatcher()
        self.idempotency = IdempotencyService()
        
        # API keys → merchant info (simplified)
        self.api_keys: Dict[str, Dict] = {}
        
        # Add a test merchant
        self._setup_test_merchant()
    
    def _setup_test_merchant(self):
        """Set up a test merchant for demos."""
        test_key = "sk_test_demo123456789"
        self.api_keys[test_key] = {
            "merchant_id": "merch_demo123",
            "name": "Demo Merchant",
            "mode": "test"
        }
    
    def authenticate(self, api_key: str) -> Optional[Dict]:
        """Authenticate an API key and return merchant info."""
        return self.api_keys.get(api_key)
    
    def create_token(
        self,
        merchant_id: str,
        card_number: str,
        exp_month: int,
        exp_year: int,
        cvv: str,
        name: Optional[str] = None
    ) -> Dict:
        """
        Create a payment token from card details.
        
        This is what happens when checkout form is submitted.
        """
        token = self.tokenization.create_token(
            TokenizeRequest(
                card_number=card_number,
                exp_month=exp_month,
                exp_year=exp_year,
                cvv=cvv,
                cardholder_name=name
            ),
            merchant_id=merchant_id
        )
        
        return {
            "id": token.id,
            "object": "token",
            "card": {
                "brand": token.card_brand.value,
                "last4": token.last_four,
                "exp_month": token.exp_month,
                "exp_year": token.exp_year,
                "funding": token.card_funding
            },
            "created": int(token.created_at.timestamp()),
            "used": token.is_used
        }
    
    def create_charge(
        self,
        merchant_id: str,
        token_id: str,
        amount: int,
        currency: str,
        description: Optional[str] = None,
        idempotency_key: Optional[str] = None,
        ip_address: Optional[str] = None,
        capture: bool = True
    ) -> Dict:
        """
        Create a charge using a token.
        
        This is the main payment endpoint.
        """
        def do_charge():
            # Retrieve the token
            token = self.tokenization.get_token(token_id)
            if not token:
                raise InvalidRequest(f"Token not found: {token_id}")
            
            if token.merchant_id != merchant_id:
                raise InvalidRequest("Token does not belong to this merchant")
            
            if token.is_used:
                raise InvalidRequest("Token has already been used")
            
            if token.is_expired():
                raise InvalidRequest("Token has expired")
            
            # Fraud check
            risk = self.fraud_detector.assess_risk(
                amount=amount,
                card_fingerprint=token.card_fingerprint,
                ip_address=ip_address
            )
            
            if risk.recommendation == "decline":
                return self._build_declined_charge(
                    token, amount, currency, "high_risk_transaction"
                )
            
            # Create the charge
            charge = self.authorization.create_charge(
                ChargeRequest(
                    token_id=token_id,
                    amount=amount,
                    currency=Currency(currency.upper())
                ),
                merchant_id=merchant_id,
                capture=capture
            )
            
            # Mark token as used
            self.tokenization.mark_token_used(token_id)
            
            # Record for velocity tracking
            self.fraud_detector.record_transaction_result(
                ip_address=ip_address or "unknown",
                card_fingerprint=token.card_fingerprint,
                device_id=None,
                success=charge.status == PaymentStatus.SUCCEEDED
            )
            
            # Send webhook
            if charge.status == PaymentStatus.SUCCEEDED:
                self.webhooks.create_event(
                    EventType.CHARGE_SUCCEEDED,
                    merchant_id,
                    charge.to_dict()
                )
            elif charge.status == PaymentStatus.DECLINED:
                self.webhooks.create_event(
                    EventType.CHARGE_FAILED,
                    merchant_id,
                    charge.to_dict()
                )
            
            return self._build_charge_response(charge, token)
        
        # Use idempotency if key provided
        if idempotency_key:
            return self.idempotency.execute(idempotency_key, do_charge)
        
        return do_charge()
    
    def _build_charge_response(self, charge, token) -> Dict:
        """Build API response for a charge."""
        return {
            "id": charge.id,
            "object": "charge",
            "amount": charge.amount,
            "currency": charge.currency.value.lower(),
            "status": charge.status.value,
            "captured": charge.captured,
            "paid": charge.status == PaymentStatus.SUCCEEDED,
            "source": {
                "brand": token.card_brand.value,
                "last4": token.last_four,
                "exp_month": token.exp_month,
                "exp_year": token.exp_year
            },
            "created": int(charge.created_at.timestamp()),
            "failure_code": charge.decline_code.value if charge.decline_code else None,
            "failure_message": charge.decline_reason
        }
    
    def _build_declined_charge(
        self,
        token,
        amount: int,
        currency: str,
        reason: str
    ) -> Dict:
        """Build a declined charge response."""
        return {
            "id": f"ch_{secrets.token_hex(12)}",
            "object": "charge",
            "amount": amount,
            "currency": currency,
            "status": "declined",
            "captured": False,
            "paid": False,
            "source": {
                "brand": token.card_brand.value,
                "last4": token.last_four,
                "exp_month": token.exp_month,
                "exp_year": token.exp_year
            },
            "created": int(datetime.utcnow().timestamp()),
            "failure_code": reason,
            "failure_message": "Transaction declined by fraud detection"
        }
    
    def capture_charge(
        self,
        merchant_id: str,
        charge_id: str,
        amount: Optional[int] = None
    ) -> Dict:
        """Capture a previously authorized charge."""
        # In a real implementation, we'd look up the charge and capture it
        # For demo, we'll return a mock response
        return {
            "id": charge_id,
            "object": "charge",
            "captured": True,
            "amount_captured": amount,
            "status": "succeeded"
        }
    
    def create_refund(
        self,
        merchant_id: str,
        charge_id: str,
        amount: Optional[int] = None,
        reason: Optional[str] = None
    ) -> Dict:
        """Create a refund for a charge."""
        refund = self.authorization.create_refund(
            RefundRequest(
                charge_id=charge_id,
                amount=amount,
                reason=reason
            ),
            merchant_id=merchant_id
        )
        
        # Send webhook
        self.webhooks.create_event(
            EventType.REFUND_CREATED,
            merchant_id,
            refund.to_dict()
        )
        
        return {
            "id": refund.id,
            "object": "refund",
            "amount": refund.amount,
            "currency": refund.currency.value.lower(),
            "charge": refund.charge_id,
            "status": refund.status.value,
            "reason": refund.reason,
            "created": int(refund.created_at.timestamp())
        }


class InvalidRequest(Exception):
    """Raised for invalid API requests."""
    pass


class PaymentAPIHandler(BaseHTTPRequestHandler):
    """
    HTTP request handler for the payment API.
    
    Endpoints:
        POST /v1/tokens - Create a token
        POST /v1/charges - Create a charge
        POST /v1/charges/{id}/capture - Capture a charge
        POST /v1/refunds - Create a refund
    """
    
    gateway: PaymentGateway = None  # Set by server
    
    def do_POST(self):
        """Handle POST requests."""
        path = urlparse(self.path).path
        
        try:
            # Authenticate
            merchant = self._authenticate()
            if not merchant:
                self._send_error(401, "Invalid API key")
                return
            
            merchant_id = merchant["merchant_id"]
            
            # Parse body
            content_length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(content_length).decode('utf-8')
            data = json.loads(body) if body else {}
            
            # Route request
            if path == "/v1/tokens":
                result = self._handle_create_token(merchant_id, data)
            elif path == "/v1/charges":
                result = self._handle_create_charge(merchant_id, data)
            elif path.startswith("/v1/charges/") and path.endswith("/capture"):
                charge_id = path.split("/")[3]
                result = self._handle_capture_charge(merchant_id, charge_id, data)
            elif path == "/v1/refunds":
                result = self._handle_create_refund(merchant_id, data)
            else:
                self._send_error(404, f"Unknown endpoint: {path}")
                return
            
            self._send_json(200, result)
            
        except InvalidRequest as e:
            self._send_error(400, str(e))
        except RequestInProgress:
            self._send_error(409, "Request with this idempotency key is in progress")
        except json.JSONDecodeError:
            self._send_error(400, "Invalid JSON")
        except Exception as e:
            self._send_error(500, f"Internal error: {str(e)}")
    
    def do_GET(self):
        """Handle GET requests."""
        path = urlparse(self.path).path
        
        if path == "/health":
            self._send_json(200, {"status": "healthy"})
        else:
            self._send_error(404, "Not found")
    
    def _authenticate(self) -> Optional[Dict]:
        """Extract and validate API key from Authorization header."""
        auth_header = self.headers.get('Authorization', '')
        
        if auth_header.startswith('Bearer '):
            api_key = auth_header[7:]
        elif auth_header.startswith('Basic '):
            # API key as username with blank password
            import base64
            decoded = base64.b64decode(auth_header[6:]).decode('utf-8')
            api_key = decoded.split(':')[0]
        else:
            return None
        
        return self.gateway.authenticate(api_key)
    
    def _handle_create_token(self, merchant_id: str, data: Dict) -> Dict:
        """Handle POST /v1/tokens."""
        required = ['card_number', 'exp_month', 'exp_year', 'cvv']
        for field in required:
            if field not in data:
                raise InvalidRequest(f"Missing required field: {field}")
        
        return self.gateway.create_token(
            merchant_id=merchant_id,
            card_number=data['card_number'],
            exp_month=int(data['exp_month']),
            exp_year=int(data['exp_year']),
            cvv=data['cvv'],
            name=data.get('name')
        )
    
    def _handle_create_charge(self, merchant_id: str, data: Dict) -> Dict:
        """Handle POST /v1/charges."""
        required = ['token', 'amount', 'currency']
        for field in required:
            if field not in data:
                raise InvalidRequest(f"Missing required field: {field}")
        
        idempotency_key = self.headers.get('Idempotency-Key')
        
        return self.gateway.create_charge(
            merchant_id=merchant_id,
            token_id=data['token'],
            amount=int(data['amount']),
            currency=data['currency'],
            description=data.get('description'),
            idempotency_key=idempotency_key,
            ip_address=self.client_address[0],
            capture=data.get('capture', True)
        )
    
    def _handle_capture_charge(
        self,
        merchant_id: str,
        charge_id: str,
        data: Dict
    ) -> Dict:
        """Handle POST /v1/charges/{id}/capture."""
        return self.gateway.capture_charge(
            merchant_id=merchant_id,
            charge_id=charge_id,
            amount=data.get('amount')
        )
    
    def _handle_create_refund(self, merchant_id: str, data: Dict) -> Dict:
        """Handle POST /v1/refunds."""
        if 'charge' not in data:
            raise InvalidRequest("Missing required field: charge")
        
        return self.gateway.create_refund(
            merchant_id=merchant_id,
            charge_id=data['charge'],
            amount=data.get('amount'),
            reason=data.get('reason')
        )
    
    def _send_json(self, status: int, data: Dict):
        """Send JSON response."""
        body = json.dumps(data, indent=2).encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', len(body))
        self.end_headers()
        self.wfile.write(body)
    
    def _send_error(self, status: int, message: str):
        """Send error response."""
        self._send_json(status, {
            "error": {
                "message": message,
                "type": "api_error",
                "code": status
            }
        })
    
    def log_message(self, format, *args):
        """Override to customize logging."""
        print(f"[API] {self.address_string()} - {format % args}")


def create_server(host: str = "localhost", port: int = 8080) -> HTTPServer:
    """Create the payment API server."""
    gateway = PaymentGateway()
    
    PaymentAPIHandler.gateway = gateway
    
    server = HTTPServer((host, port), PaymentAPIHandler)
    return server


def run_server(host: str = "localhost", port: int = 8080):
    """Run the payment API server."""
    print(f"Starting Payment Gateway API on http://{host}:{port}")
    print("\nTest API key: sk_test_demo123456789")
    print("\nEndpoints:")
    print("  POST /v1/tokens   - Create a payment token")
    print("  POST /v1/charges  - Create a charge")
    print("  POST /v1/refunds  - Create a refund")
    print("  GET  /health      - Health check")
    print("\nPress Ctrl+C to stop\n")
    
    server = create_server(host, port)
    
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down...")
        server.shutdown()


# =============================================================================
# Demo/Test
# =============================================================================

def demo_api():
    """Demo the API without starting the server."""
    print("=" * 60)
    print("PAYMENT GATEWAY API DEMO")
    print("=" * 60)
    
    gateway = PaymentGateway()
    
    # Create token
    print("\n1. Creating token:")
    token = gateway.create_token(
        merchant_id="merch_demo123",
        card_number="4242424242424242",
        exp_month=12,
        exp_year=2025,
        cvv="123",
        name="Test User"
    )
    print(f"   Token: {token['id']}")
    print(f"   Card: {token['card']['brand']} ending in {token['card']['last4']}")
    
    # Create charge
    print("\n2. Creating charge:")
    charge = gateway.create_charge(
        merchant_id="merch_demo123",
        token_id=token['id'],
        amount=2499,
        currency="usd",
        description="Test charge",
        idempotency_key="test-key-123"
    )
    print(f"   Charge: {charge['id']}")
    print(f"   Amount: ${charge['amount']/100:.2f} {charge['currency'].upper()}")
    print(f"   Status: {charge['status']}")
    
    # Test idempotency - same key should return same result
    print("\n3. Testing idempotency (same key):")
    try:
        # Need to un-use the token for this demo...
        charge2 = gateway.create_charge(
            merchant_id="merch_demo123",
            token_id=token['id'],
            amount=2499,
            currency="usd",
            idempotency_key="test-key-123"  # Same key
        )
        print(f"   Same charge returned: {charge2['id']}")
    except Exception as e:
        print(f"   Note: {e}")
    
    # Create refund
    print("\n4. Creating refund:")
    refund = gateway.create_refund(
        merchant_id="merch_demo123",
        charge_id=charge['id'],
        amount=1000,
        reason="Customer request"
    )
    print(f"   Refund: {refund['id']}")
    print(f"   Amount: ${refund['amount']/100:.2f}")
    print(f"   Status: {refund['status']}")
    
    print("\n5. Example cURL commands:")
    print("""
    # Create token
    curl -X POST http://localhost:8080/v1/tokens \\
      -H "Authorization: Bearer sk_test_demo123456789" \\
      -H "Content-Type: application/json" \\
      -d '{"card_number": "4242424242424242", "exp_month": 12, "exp_year": 2025, "cvv": "123"}'
    
    # Create charge
    curl -X POST http://localhost:8080/v1/charges \\
      -H "Authorization: Bearer sk_test_demo123456789" \\
      -H "Content-Type: application/json" \\
      -H "Idempotency-Key: unique-key-123" \\
      -d '{"token": "tok_xxx", "amount": 2499, "currency": "usd"}'
    """)


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "demo":
        demo_api()
    else:
        run_server()
