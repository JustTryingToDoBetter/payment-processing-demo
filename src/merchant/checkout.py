"""
Merchant Checkout Flow

This module demonstrates a complete checkout flow from the
merchant's perspective, including:

1. Cart calculation
2. Payment intent creation (for 3DS)
3. Payment processing
4. Order fulfillment
5. Error handling

This is a simplified e-commerce checkout for educational purposes.
"""

import secrets
from datetime import datetime
from dataclasses import dataclass, field
from typing import Dict, List, Optional
from enum import Enum

from .payment_client import PaymentClient, PaymentError, CardError


class OrderStatus(str, Enum):
    """Order status."""
    PENDING = "pending"               # Order created, awaiting payment
    AWAITING_PAYMENT = "awaiting_payment"
    PAYMENT_FAILED = "payment_failed"
    PAID = "paid"                     # Payment confirmed
    PROCESSING = "processing"         # Being prepared
    SHIPPED = "shipped"
    DELIVERED = "delivered"
    REFUNDED = "refunded"
    CANCELLED = "cancelled"


@dataclass
class CartItem:
    """An item in the shopping cart."""
    product_id: str
    name: str
    price: int  # In cents
    quantity: int
    
    @property
    def total(self) -> int:
        return self.price * self.quantity


@dataclass
class ShippingAddress:
    """Customer shipping address."""
    name: str
    line1: str
    line2: Optional[str] = None
    city: str = ""
    state: str = ""
    postal_code: str = ""
    country: str = "US"


@dataclass
class Order:
    """A customer order."""
    id: str
    customer_email: str
    items: List[CartItem]
    shipping_address: ShippingAddress
    status: OrderStatus = OrderStatus.PENDING
    
    subtotal: int = 0
    shipping: int = 0
    tax: int = 0
    total: int = 0
    
    charge_id: Optional[str] = None
    payment_failed_reason: Optional[str] = None
    
    created_at: datetime = field(default_factory=datetime.utcnow)
    paid_at: Optional[datetime] = None
    
    def calculate_totals(self, tax_rate: float = 0.0825):
        """Calculate order totals."""
        self.subtotal = sum(item.total for item in self.items)
        
        # Simple flat-rate shipping
        self.shipping = 999 if self.subtotal < 5000 else 0  # Free over $50
        
        # Tax on subtotal
        self.tax = int(self.subtotal * tax_rate)
        
        self.total = self.subtotal + self.shipping + self.tax


class CheckoutService:
    """
    Handles the checkout process.
    
    Typical flow:
    1. Create order from cart
    2. Process payment with token
    3. Handle success or failure
    4. Trigger fulfillment
    """
    
    def __init__(self, payment_client: PaymentClient):
        self.payment = payment_client
        
        # In-memory orders for demo
        self._orders: Dict[str, Order] = {}
    
    def create_order(
        self,
        customer_email: str,
        items: List[CartItem],
        shipping_address: ShippingAddress
    ) -> Order:
        """
        Create a new order from cart items.
        
        This prepares the order but doesn't charge yet.
        """
        order = Order(
            id=f"ord_{secrets.token_hex(12)}",
            customer_email=customer_email,
            items=items,
            shipping_address=shipping_address,
            status=OrderStatus.PENDING
        )
        order.calculate_totals()
        
        self._orders[order.id] = order
        return order
    
    def process_payment(
        self,
        order_id: str,
        payment_token: str
    ) -> Dict:
        """
        Process payment for an order.
        
        Args:
            order_id: The order to pay for
            payment_token: Token from the frontend
            
        Returns:
            Result dict with success status and details
        """
        order = self._orders.get(order_id)
        if not order:
            return {"success": False, "error": "Order not found"}
        
        if order.status not in [OrderStatus.PENDING, OrderStatus.PAYMENT_FAILED]:
            return {
                "success": False,
                "error": f"Order cannot be paid (status: {order.status.value})"
            }
        
        order.status = OrderStatus.AWAITING_PAYMENT
        
        try:
            # Create charge with idempotency key based on order
            # This prevents duplicate charges if customer clicks "Pay" twice
            charge = self.payment.charges.create(
                amount=order.total,
                currency="usd",
                source=payment_token,
                description=f"Order {order.id}",
                metadata={
                    "order_id": order.id,
                    "customer_email": order.customer_email
                },
                idempotency_key=f"order-{order.id}-payment"
            )
            
            if charge.data.get("paid"):
                # Payment succeeded!
                order.status = OrderStatus.PAID
                order.charge_id = charge.data.get("id")
                order.paid_at = datetime.utcnow()
                
                return {
                    "success": True,
                    "order_id": order.id,
                    "charge_id": order.charge_id,
                    "amount": order.total
                }
            else:
                # Payment failed
                order.status = OrderStatus.PAYMENT_FAILED
                order.payment_failed_reason = charge.data.get("failure_message")
                
                return {
                    "success": False,
                    "error": charge.data.get("failure_message"),
                    "decline_code": charge.data.get("failure_code")
                }
                
        except CardError as e:
            # Card was declined
            order.status = OrderStatus.PAYMENT_FAILED
            order.payment_failed_reason = e.message
            
            return {
                "success": False,
                "error": e.message,
                "decline_code": e.decline_code
            }
            
        except PaymentError as e:
            # Other payment error
            order.status = OrderStatus.PAYMENT_FAILED
            order.payment_failed_reason = str(e)
            
            return {
                "success": False,
                "error": str(e)
            }
    
    def handle_payment_webhook(self, event_type: str, charge_data: Dict) -> bool:
        """
        Handle payment webhook events.
        
        This is called by the webhook handler when we receive
        events from the payment gateway.
        
        Returns True if handled successfully.
        """
        charge_id = charge_data.get("id")
        order_id = charge_data.get("metadata", {}).get("order_id")
        
        if not order_id:
            return False
        
        order = self._orders.get(order_id)
        if not order:
            return False
        
        if event_type == "charge.succeeded":
            order.status = OrderStatus.PAID
            order.charge_id = charge_id
            order.paid_at = datetime.utcnow()
            
            # Trigger fulfillment
            self._start_fulfillment(order)
            return True
            
        elif event_type == "charge.failed":
            order.status = OrderStatus.PAYMENT_FAILED
            order.payment_failed_reason = charge_data.get("failure_message")
            return True
        
        return False
    
    def _start_fulfillment(self, order: Order):
        """
        Start order fulfillment.
        
        In production, this would:
        - Send confirmation email
        - Create shipping label
        - Notify warehouse
        - Update inventory
        """
        print(f"📦 Starting fulfillment for order {order.id}")
        order.status = OrderStatus.PROCESSING
    
    def process_refund(
        self,
        order_id: str,
        amount: Optional[int] = None,
        reason: str = "requested_by_customer"
    ) -> Dict:
        """
        Process a refund for an order.
        
        Args:
            order_id: The order to refund
            amount: Amount in cents (default: full refund)
            reason: Reason for refund
        """
        order = self._orders.get(order_id)
        if not order:
            return {"success": False, "error": "Order not found"}
        
        if order.status != OrderStatus.PAID or not order.charge_id:
            return {"success": False, "error": "Order not eligible for refund"}
        
        try:
            refund = self.payment.refunds.create(
                charge=order.charge_id,
                amount=amount,
                reason=reason,
                idempotency_key=f"order-{order_id}-refund"
            )
            
            if amount is None or amount >= order.total:
                order.status = OrderStatus.REFUNDED
            
            return {
                "success": True,
                "refund_id": refund.data.get("id"),
                "amount": refund.data.get("amount")
            }
            
        except PaymentError as e:
            return {"success": False, "error": str(e)}
    
    def get_order(self, order_id: str) -> Optional[Order]:
        """Get an order by ID."""
        return self._orders.get(order_id)
    
    def get_order_summary(self, order_id: str) -> Optional[Dict]:
        """Get order summary for display."""
        order = self._orders.get(order_id)
        if not order:
            return None
        
        return {
            "id": order.id,
            "status": order.status.value,
            "items": [
                {
                    "name": item.name,
                    "quantity": item.quantity,
                    "price": f"${item.price/100:.2f}",
                    "total": f"${item.total/100:.2f}"
                }
                for item in order.items
            ],
            "subtotal": f"${order.subtotal/100:.2f}",
            "shipping": f"${order.shipping/100:.2f}",
            "tax": f"${order.tax/100:.2f}",
            "total": f"${order.total/100:.2f}",
            "charge_id": order.charge_id
        }


# =============================================================================
# Demo
# =============================================================================

def demo_checkout():
    """Demonstrate the checkout flow."""
    print("=" * 60)
    print("CHECKOUT FLOW DEMO")
    print("=" * 60)
    
    # Create a mock payment client (won't actually connect)
    class MockPaymentClient:
        class MockCharges:
            def create(self, **kwargs):
                from dataclasses import dataclass
                @dataclass
                class MockResponse:
                    data: Dict
                return MockResponse(data={
                    "id": "ch_mock123",
                    "paid": True,
                    "amount": kwargs["amount"],
                    "status": "succeeded"
                })
        
        class MockRefunds:
            def create(self, **kwargs):
                from dataclasses import dataclass
                @dataclass
                class MockResponse:
                    data: Dict
                return MockResponse(data={
                    "id": "re_mock123",
                    "amount": kwargs.get("amount", 5000),
                    "status": "succeeded"
                })
        
        charges = MockCharges()
        refunds = MockRefunds()
    
    checkout = CheckoutService(MockPaymentClient())
    
    # Create cart items
    print("\n1. Creating shopping cart:")
    items = [
        CartItem("prod_1", "Wireless Mouse", 2999, 1),
        CartItem("prod_2", "USB-C Cable", 1299, 2),
        CartItem("prod_3", "Laptop Stand", 4999, 1),
    ]
    for item in items:
        print(f"   {item.quantity}x {item.name}: ${item.total/100:.2f}")
    
    # Create order
    print("\n2. Creating order:")
    order = checkout.create_order(
        customer_email="customer@example.com",
        items=items,
        shipping_address=ShippingAddress(
            name="John Doe",
            line1="123 Main St",
            city="San Francisco",
            state="CA",
            postal_code="94102",
            country="US"
        )
    )
    print(f"   Order ID: {order.id}")
    print(f"   Subtotal: ${order.subtotal/100:.2f}")
    print(f"   Shipping: ${order.shipping/100:.2f}")
    print(f"   Tax: ${order.tax/100:.2f}")
    print(f"   Total: ${order.total/100:.2f}")
    
    # Process payment
    print("\n3. Processing payment:")
    result = checkout.process_payment(order.id, "tok_mock_token")
    print(f"   Success: {result['success']}")
    print(f"   Charge ID: {result.get('charge_id')}")
    
    # Check order status
    print("\n4. Order status after payment:")
    summary = checkout.get_order_summary(order.id)
    print(f"   Status: {summary['status']}")
    
    # Process refund
    print("\n5. Processing partial refund ($10):")
    refund_result = checkout.process_refund(order.id, amount=1000)
    print(f"   Success: {refund_result['success']}")
    print(f"   Refund ID: {refund_result.get('refund_id')}")
    
    print("\n6. Complete checkout flow code:")
    print("""
    # Frontend sends token, backend processes order
    
    def checkout_endpoint(request):
        # 1. Create order from cart
        order = checkout.create_order(
            customer_email=request.user.email,
            items=get_cart_items(request.user),
            shipping_address=request.shipping_address
        )
        
        # 2. Process payment
        result = checkout.process_payment(
            order_id=order.id,
            payment_token=request.token
        )
        
        if result["success"]:
            # 3. Success - redirect to confirmation
            return redirect(f"/order/{order.id}/confirmation")
        else:
            # 4. Failed - show error, let customer retry
            return render("checkout", error=result["error"])
    """)


if __name__ == "__main__":
    demo_checkout()
