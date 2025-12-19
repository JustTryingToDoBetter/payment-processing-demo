"""
Tests for the payment processing system.

Run with: python -m pytest tests/ -v
"""

import pytest
import time
import hashlib
import hmac
import json
from datetime import datetime

# Import our modules
import sys
sys.path.insert(0, 'src')


class TestLuhnValidation:
    """Test Luhn algorithm implementation."""
    
    def test_valid_card_numbers(self):
        from shared.constants import validate_luhn
        
        # Valid test card numbers
        valid_numbers = [
            "4242424242424242",  # Visa
            "5555555555554444",  # Mastercard
            "378282246310005",   # Amex
            "6011111111111117",  # Discover
        ]
        
        for number in valid_numbers:
            assert validate_luhn(number), f"{number} should be valid"
    
    def test_invalid_card_numbers(self):
        from shared.constants import validate_luhn
        
        # Invalid numbers
        invalid_numbers = [
            "4242424242424241",  # Wrong check digit
            "1234567890123456",
            "0000000000000000",
        ]
        
        for number in invalid_numbers:
            assert not validate_luhn(number), f"{number} should be invalid"


class TestCardBrandDetection:
    """Test card brand detection from BIN."""
    
    def test_visa(self):
        from shared.constants import detect_card_brand, CardBrand
        
        assert detect_card_brand("4242424242424242") == CardBrand.VISA
        assert detect_card_brand("4111111111111111") == CardBrand.VISA
    
    def test_mastercard(self):
        from shared.constants import detect_card_brand, CardBrand
        
        assert detect_card_brand("5555555555554444") == CardBrand.MASTERCARD
        assert detect_card_brand("5105105105105100") == CardBrand.MASTERCARD
    
    def test_amex(self):
        from shared.constants import detect_card_brand, CardBrand
        
        assert detect_card_brand("378282246310005") == CardBrand.AMEX
        assert detect_card_brand("371449635398431") == CardBrand.AMEX
    
    def test_discover(self):
        from shared.constants import detect_card_brand, CardBrand
        
        assert detect_card_brand("6011111111111117") == CardBrand.DISCOVER


class TestCardMasking:
    """Test card number masking."""
    
    def test_mask_card(self):
        from shared.encryption import CardMasker
        
        masked = CardMasker.mask_card("4242424242424242")
        assert masked == "************4242"
    
    def test_extract_last_four(self):
        from shared.encryption import CardMasker
        
        last4 = CardMasker.get_last_four("4242424242424242")
        assert last4 == "4242"
    
    def test_extract_bin(self):
        from shared.encryption import CardMasker
        
        bin_number = CardMasker.get_bin("4242424242424242")
        assert bin_number == "424242"


class TestEncryption:
    """Test encryption service."""
    
    def test_encrypt_decrypt(self):
        from shared.encryption import EncryptionService
        
        service = EncryptionService()
        
        plaintext = "4242424242424242"
        encrypted = service.encrypt(plaintext)
        decrypted = service.decrypt(encrypted)
        
        assert decrypted == plaintext
        assert encrypted != plaintext
    
    def test_encrypted_data_is_different_each_time(self):
        from shared.encryption import EncryptionService
        
        service = EncryptionService()
        plaintext = "4242424242424242"
        
        # Encrypt the same data twice
        enc1 = service.encrypt(plaintext)
        enc2 = service.encrypt(plaintext)
        
        # Should be different due to random IV
        assert enc1 != enc2
        
        # But should decrypt to same value
        assert service.decrypt(enc1) == service.decrypt(enc2)


class TestTokenGeneration:
    """Test token generation."""
    
    def test_token_format(self):
        from shared.encryption import TokenGenerator
        
        token = TokenGenerator.generate_token("tok")
        
        assert token.startswith("tok_")
        assert len(token) > 10
    
    def test_tokens_are_unique(self):
        from shared.encryption import TokenGenerator
        
        tokens = [TokenGenerator.generate_token("tok") for _ in range(100)]
        
        # All tokens should be unique
        assert len(set(tokens)) == 100


class TestWebhookSignature:
    """Test webhook signature creation and verification."""
    
    def test_sign_and_verify(self):
        from shared.encryption import SignatureGenerator
        
        payload = '{"id": "evt_123", "type": "charge.succeeded"}'
        secret = "whsec_test_secret"
        timestamp = int(time.time())
        
        # Sign
        signature = SignatureGenerator.sign_webhook(payload, secret, timestamp)
        
        # Verify
        is_valid = SignatureGenerator.verify_webhook(
            payload, signature, secret, timestamp
        )
        
        assert is_valid
    
    def test_invalid_signature_rejected(self):
        from shared.encryption import SignatureGenerator
        
        payload = '{"id": "evt_123"}'
        secret = "whsec_test_secret"
        timestamp = int(time.time())
        
        # Tampered signature
        is_valid = SignatureGenerator.verify_webhook(
            payload, "invalid_signature", secret, timestamp
        )
        
        assert not is_valid


class TestIdempotency:
    """Test idempotency service."""
    
    def test_same_key_returns_cached_result(self):
        from shared.idempotency import IdempotencyService
        
        service = IdempotencyService()
        
        call_count = 0
        def operation():
            nonlocal call_count
            call_count += 1
            return {"id": "result_123"}
        
        # First call - should execute
        result1 = service.execute("key_1", operation)
        
        # Second call with same key - should return cached
        result2 = service.execute("key_1", operation)
        
        assert result1 == result2
        assert call_count == 1  # Only called once
    
    def test_different_keys_execute_separately(self):
        from shared.idempotency import IdempotencyService
        
        service = IdempotencyService()
        
        call_count = 0
        def operation():
            nonlocal call_count
            call_count += 1
            return {"count": call_count}
        
        result1 = service.execute("key_1", operation)
        result2 = service.execute("key_2", operation)
        
        assert call_count == 2
        assert result1["count"] == 1
        assert result2["count"] == 2


class TestTokenization:
    """Test tokenization service."""
    
    def test_create_token(self):
        from gateway.tokenization import TokenizationService
        from gateway.models import TokenizeRequest
        
        service = TokenizationService()
        
        request = TokenizeRequest(
            card_number="4242424242424242",
            exp_month=12,
            exp_year=2025,
            cvv="123",
            cardholder_name="Test User"
        )
        
        token = service.create_token(request, merchant_id="merch_test")
        
        assert token.id.startswith("tok_")
        assert token.last_four == "4242"
        assert token.merchant_id == "merch_test"
        assert not token.is_used
    
    def test_token_can_be_retrieved(self):
        from gateway.tokenization import TokenizationService
        from gateway.models import TokenizeRequest
        
        service = TokenizationService()
        
        request = TokenizeRequest(
            card_number="4242424242424242",
            exp_month=12,
            exp_year=2025,
            cvv="123"
        )
        
        created_token = service.create_token(request, merchant_id="merch_test")
        retrieved_token = service.get_token(created_token.id)
        
        assert retrieved_token.id == created_token.id
        assert retrieved_token.last_four == "4242"
    
    def test_invalid_card_rejected(self):
        from gateway.tokenization import TokenizationService, InvalidCardError
        from gateway.models import TokenizeRequest
        
        service = TokenizationService()
        
        request = TokenizeRequest(
            card_number="1234567890123456",  # Invalid Luhn
            exp_month=12,
            exp_year=2025,
            cvv="123"
        )
        
        with pytest.raises(InvalidCardError):
            service.create_token(request, merchant_id="merch_test")


class TestFraudDetection:
    """Test fraud detection."""
    
    def test_normal_transaction_low_risk(self):
        from gateway.fraud_detection import FraudDetector, RiskLevel
        
        detector = FraudDetector()
        
        assessment = detector.assess_risk(
            amount=5000,  # $50
            card_fingerprint="fp_normal_123",
            ip_address="192.168.1.1"
        )
        
        assert assessment.level == RiskLevel.LOW
        assert assessment.recommendation == "approve"
    
    def test_high_velocity_raises_risk(self):
        from gateway.fraud_detection import FraudDetector, RiskLevel
        
        detector = FraudDetector()
        
        # Simulate high velocity
        for i in range(15):
            detector.velocity.record_attempt(
                ip_address="10.0.0.1",
                card_fingerprint=f"fp_card_{i}"
            )
        
        assessment = detector.assess_risk(
            amount=5000,
            card_fingerprint="fp_new",
            ip_address="10.0.0.1"
        )
        
        assert assessment.level in [RiskLevel.MEDIUM, RiskLevel.HIGH]
    
    def test_disposable_email_raises_risk(self):
        from gateway.fraud_detection import FraudDetector
        
        detector = FraudDetector()
        
        assessment = detector.assess_risk(
            amount=5000,
            card_fingerprint="fp_test",
            email="test@mailinator.com"
        )
        
        # Should have a signal for disposable email
        signal_types = [s.type.value for s in assessment.signals]
        assert "disposable_email" in signal_types


class TestWebhookHandler:
    """Test merchant webhook handler."""
    
    def test_verify_valid_signature(self):
        from merchant.webhook_handler import WebhookHandler
        
        secret = "whsec_test_secret"
        handler = WebhookHandler(secret=secret)
        
        payload = '{"id": "evt_123", "type": "charge.succeeded"}'
        timestamp = int(time.time())
        
        # Create valid signature
        signed = f"{timestamp}.{payload}"
        signature = hmac.new(
            secret.encode(),
            signed.encode(),
            hashlib.sha256
        ).hexdigest()
        
        header = f"t={timestamp},v1={signature}"
        
        # Should not raise
        assert handler.verify_signature(payload, header)
    
    def test_reject_invalid_signature(self):
        from merchant.webhook_handler import (
            WebhookHandler, WebhookVerificationError
        )
        
        handler = WebhookHandler(secret="whsec_test")
        
        with pytest.raises(WebhookVerificationError):
            handler.verify_signature(
                '{"id": "evt_123"}',
                "t=123,v1=invalid"
            )
    
    def test_reject_old_timestamp(self):
        from merchant.webhook_handler import (
            WebhookHandler, WebhookVerificationError
        )
        
        secret = "whsec_test"
        handler = WebhookHandler(secret=secret, tolerance=60)
        
        payload = '{"id": "evt_123"}'
        old_timestamp = int(time.time()) - 120  # 2 minutes ago
        
        signed = f"{old_timestamp}.{payload}"
        signature = hmac.new(
            secret.encode(),
            signed.encode(),
            hashlib.sha256
        ).hexdigest()
        
        header = f"t={old_timestamp},v1={signature}"
        
        with pytest.raises(WebhookVerificationError):
            handler.verify_signature(payload, header)


class TestIssuingBank:
    """Test issuing bank simulation."""
    
    def test_successful_authorization(self):
        from bank_simulator.issuing_bank import (
            IssuingBank, AuthorizationRequest
        )
        
        bank = IssuingBank()
        
        response = bank.authorize(AuthorizationRequest(
            request_id="auth_001",
            card_number="4242424242424242",
            exp_month=12,
            exp_year=2025,
            cvv="123",
            amount=5000,
            currency="USD",
            merchant_id="merch_test",
            merchant_name="Test Store",
            merchant_category="5411"
        ))
        
        assert response.approved
        assert response.auth_code is not None
    
    def test_insufficient_funds_declined(self):
        from bank_simulator.issuing_bank import (
            IssuingBank, AuthorizationRequest
        )
        
        bank = IssuingBank()
        
        response = bank.authorize(AuthorizationRequest(
            request_id="auth_002",
            card_number="4000000000009995",
            exp_month=12,
            exp_year=2025,
            cvv="123",
            amount=5000,
            currency="USD",
            merchant_id="merch_test",
            merchant_name="Test Store",
            merchant_category="5411"
        ))
        
        assert not response.approved
        assert response.decline_reason == "insufficient_funds"
    
    def test_wrong_cvv_declined(self):
        from bank_simulator.issuing_bank import (
            IssuingBank, AuthorizationRequest
        )
        
        bank = IssuingBank()
        
        response = bank.authorize(AuthorizationRequest(
            request_id="auth_003",
            card_number="4242424242424242",
            exp_month=12,
            exp_year=2025,
            cvv="999",  # Wrong CVV
            amount=5000,
            currency="USD",
            merchant_id="merch_test",
            merchant_name="Test Store",
            merchant_category="5411"
        ))
        
        assert not response.approved
        assert response.decline_reason == "incorrect_cvc"


class TestCheckoutFlow:
    """Test merchant checkout flow."""
    
    def test_create_order(self):
        from merchant.checkout import (
            CheckoutService, CartItem, ShippingAddress
        )
        
        # Mock payment client
        class MockClient:
            pass
        
        checkout = CheckoutService(MockClient())
        
        order = checkout.create_order(
            customer_email="test@example.com",
            items=[
                CartItem("prod_1", "Widget", 1999, 2),
                CartItem("prod_2", "Gadget", 4999, 1)
            ],
            shipping_address=ShippingAddress(
                name="Test User",
                line1="123 Test St",
                city="Test City",
                state="TS",
                postal_code="12345"
            )
        )
        
        assert order.id.startswith("ord_")
        assert order.subtotal == 8997  # 19.99*2 + 49.99
        assert order.total > order.subtotal  # Has tax


# =============================================================================
# Run tests
# =============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
