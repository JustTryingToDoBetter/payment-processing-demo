"""
Tokenization service for secure card handling.

This is the CORE security component of a payment gateway.
It handles the sensitive card data so merchants don't have to.

Key responsibilities:
1. Accept raw card data from client-side SDKs
2. Validate card format and Luhn check
3. Encrypt and store card in secure vault
4. Return a non-sensitive token

The token can be safely:
- Stored in merchant databases
- Passed through APIs
- Logged (though not recommended)
"""

import threading
from datetime import datetime, timedelta
from typing import Dict, Optional, Tuple
from dataclasses import dataclass

from ..shared.constants import (
    CardBrand, Config, TEST_CARDS,
    detect_card_brand, validate_luhn
)
from ..shared.encryption import (
    EncryptionService, EncryptedData, CardFingerprint, TokenGenerator
)
from .models import Card, Token


class TokenizationError(Exception):
    """Base exception for tokenization errors."""
    pass


class InvalidCardError(TokenizationError):
    """Card validation failed."""
    def __init__(self, message: str, code: str):
        super().__init__(message)
        self.code = code


class TokenNotFoundError(TokenizationError):
    """Token doesn't exist."""
    pass


class TokenExpiredError(TokenizationError):
    """Token has expired."""
    pass


class TokenAlreadyUsedError(TokenizationError):
    """One-time token was already used."""
    pass


@dataclass
class VaultEntry:
    """
    An entry in the card vault.
    
    In production, this would be stored in an HSM or secure database
    with the card number encrypted.
    """
    id: str
    encrypted_card: EncryptedData
    exp_month: int
    exp_year: int
    last_four: str
    brand: CardBrand
    fingerprint: str
    created_at: datetime


class CardVault:
    """
    Secure storage for encrypted card data.
    
    In production, this would be:
    - Backed by HSMs (Hardware Security Modules)
    - Running in a PCI-compliant environment
    - Isolated from other systems
    - Heavily audited and monitored
    
    This demo version uses in-memory storage with software encryption.
    """
    
    def __init__(self, encryption_service: EncryptionService):
        self.encryption = encryption_service
        self.fingerprint_generator = CardFingerprint(salt="demo_merchant_salt")
        self._vault: Dict[str, VaultEntry] = {}
        self._lock = threading.Lock()
    
    def store_card(self, card: Card) -> str:
        """
        Store a card securely and return vault ID.
        
        Args:
            card: The card to store
            
        Returns:
            Vault entry ID
        """
        # Generate fingerprint for duplicate detection
        fingerprint = self.fingerprint_generator.generate(
            card.number, card.exp_month, card.exp_year
        )
        
        # Check for duplicate
        with self._lock:
            for entry in self._vault.values():
                if entry.fingerprint == fingerprint:
                    # Return existing entry ID
                    return entry.id
        
        # Encrypt the card number
        clean_number = card.number.replace(" ", "").replace("-", "")
        encrypted = self.encryption.encrypt(clean_number)
        
        # Create vault entry
        vault_id = TokenGenerator.generate("vault_", 24)
        entry = VaultEntry(
            id=vault_id,
            encrypted_card=encrypted,
            exp_month=card.exp_month,
            exp_year=card.exp_year,
            last_four=card.last_four,
            brand=card.brand,
            fingerprint=fingerprint,
            created_at=datetime.utcnow()
        )
        
        with self._lock:
            self._vault[vault_id] = entry
        
        return vault_id
    
    def get_entry(self, vault_id: str) -> Optional[VaultEntry]:
        """Get a vault entry by ID."""
        return self._vault.get(vault_id)
    
    def decrypt_card_number(self, vault_id: str) -> str:
        """
        Decrypt and return the card number.
        
        This should be called sparingly and only when actually
        needed (e.g., to send to the bank network).
        
        All access should be logged and audited.
        """
        entry = self._vault.get(vault_id)
        if not entry:
            raise TokenNotFoundError(f"Vault entry {vault_id} not found")
        
        # Decrypt
        card_number = self.encryption.decrypt(entry.encrypted_card)
        
        # In production: Log this access for audit trail
        # audit_log.record("card_decrypted", vault_id=vault_id, reason="bank_auth")
        
        return card_number


class TokenizationService:
    """
    Service for tokenizing cards.
    
    This is what merchants interact with (through the SDK).
    """
    
    def __init__(self, vault: Optional[CardVault] = None):
        """
        Initialize the tokenization service.
        
        Args:
            vault: Card vault for storage. Creates default if not provided.
        """
        if vault is None:
            encryption = EncryptionService()
            vault = CardVault(encryption)
        
        self.vault = vault
        self._tokens: Dict[str, Token] = {}
        self._lock = threading.Lock()
    
    def create_token(
        self,
        card_number: str,
        exp_month: int,
        exp_year: int,
        cvv: str,
        cardholder_name: Optional[str] = None
    ) -> Token:
        """
        Create a token from card data.
        
        This is called by the client-side SDK after collecting card data
        in a secure iframe.
        
        Args:
            card_number: Full card number
            exp_month: Expiration month (1-12)
            exp_year: Expiration year (4 digits)
            cvv: Card verification value
            cardholder_name: Optional cardholder name
            
        Returns:
            A Token object
            
        Raises:
            InvalidCardError: If card validation fails
        """
        # Clean the card number
        clean_number = card_number.replace(" ", "").replace("-", "")
        
        # Validate card
        self._validate_card(clean_number, exp_month, exp_year, cvv)
        
        # Check for test cards with special behavior
        test_behavior = TEST_CARDS.get(clean_number, {}).get("behavior")
        if test_behavior == "attach_fail":
            raise InvalidCardError(
                "Your card could not be tokenized.",
                "card_declined"
            )
        
        # Create Card object
        card = Card(
            number=clean_number,
            exp_month=exp_month,
            exp_year=exp_year,
            cvv=cvv,
            cardholder_name=cardholder_name
        )
        
        # Store in vault and get vault ID
        vault_id = self.vault.store_card(card)
        
        # Create token
        token = Token(
            id=TokenGenerator.generate(Config.TOKEN_PREFIX, Config.TOKEN_LENGTH),
            card_last_four=card.last_four,
            card_brand=card.brand,
            card_exp_month=exp_month,
            card_exp_year=exp_year,
            created_at=datetime.utcnow(),
            expires_at=datetime.utcnow() + timedelta(minutes=Config.TOKEN_EXPIRY_MINUTES),
            used=False,
            _card_vault_id=vault_id
        )
        
        # Store token
        with self._lock:
            self._tokens[token.id] = token
        
        return token
    
    def get_token(self, token_id: str) -> Token:
        """
        Get a token by ID.
        
        Args:
            token_id: The token ID
            
        Returns:
            The Token object
            
        Raises:
            TokenNotFoundError: If token doesn't exist
            TokenExpiredError: If token has expired
        """
        token = self._tokens.get(token_id)
        
        if not token:
            raise TokenNotFoundError(f"Token {token_id} not found")
        
        if token.is_expired():
            raise TokenExpiredError(f"Token {token_id} has expired")
        
        return token
    
    def use_token(self, token_id: str) -> Tuple[Token, str]:
        """
        Use a token and get the card number for processing.
        
        This marks the token as used (for one-time tokens) and
        returns the decrypted card number for bank authorization.
        
        Args:
            token_id: The token ID
            
        Returns:
            Tuple of (Token, card_number)
            
        Raises:
            TokenNotFoundError: If token doesn't exist
            TokenExpiredError: If token has expired
            TokenAlreadyUsedError: If one-time token was already used
        """
        with self._lock:
            token = self.get_token(token_id)
            
            if token.used:
                raise TokenAlreadyUsedError(f"Token {token_id} has already been used")
            
            # Mark as used
            token.used = True
        
        # Get card number from vault
        card_number = self.vault.decrypt_card_number(token._card_vault_id)
        
        return token, card_number
    
    def get_vault_entry(self, token_id: str) -> VaultEntry:
        """
        Get the vault entry associated with a token.
        
        Used for accessing card details without the full number.
        """
        token = self.get_token(token_id)
        entry = self.vault.get_entry(token._card_vault_id)
        if not entry:
            raise TokenNotFoundError(f"Vault entry for token {token_id} not found")
        return entry
    
    def _validate_card(
        self,
        card_number: str,
        exp_month: int,
        exp_year: int,
        cvv: str
    ) -> None:
        """
        Validate card data.
        
        Raises:
            InvalidCardError: If validation fails
        """
        # Check card number format
        if not card_number.isdigit():
            raise InvalidCardError(
                "Card number must contain only digits",
                "invalid_number"
            )
        
        if len(card_number) < 13 or len(card_number) > 19:
            raise InvalidCardError(
                "Card number must be between 13 and 19 digits",
                "invalid_number"
            )
        
        # Luhn check
        if not validate_luhn(card_number):
            raise InvalidCardError(
                "Card number is invalid",
                "invalid_number"
            )
        
        # Check expiration
        if exp_month < 1 or exp_month > 12:
            raise InvalidCardError(
                "Expiration month must be between 1 and 12",
                "invalid_expiry_month"
            )
        
        current_year = datetime.utcnow().year
        if exp_year < current_year or exp_year > current_year + 20:
            raise InvalidCardError(
                "Expiration year is invalid",
                "invalid_expiry_year"
            )
        
        # Check if expired
        now = datetime.utcnow()
        if exp_year < now.year or (exp_year == now.year and exp_month < now.month):
            raise InvalidCardError(
                "Card has expired",
                "expired_card"
            )
        
        # Check CVV
        brand = detect_card_brand(card_number)
        expected_cvv_length = 4 if brand == CardBrand.AMEX else 3
        
        if not cvv.isdigit() or len(cvv) != expected_cvv_length:
            raise InvalidCardError(
                f"CVV must be {expected_cvv_length} digits",
                "invalid_cvc"
            )


# =============================================================================
# Demo
# =============================================================================

def demo_tokenization():
    """Demonstrate tokenization functionality."""
    print("=" * 60)
    print("TOKENIZATION DEMO")
    print("=" * 60)
    
    service = TokenizationService()
    
    # Create a token
    print("\n1. Creating token from card data:")
    print("   Card: 4242 4242 4242 4242")
    print("   Exp: 12/2025")
    print("   CVV: 123")
    
    token = service.create_token(
        card_number="4242 4242 4242 4242",
        exp_month=12,
        exp_year=2025,
        cvv="123",
        cardholder_name="Test User"
    )
    
    print(f"\n   Token created: {token.id}")
    print(f"   Token data: {token.to_dict()}")
    
    # Use the token
    print("\n2. Using token to get card number:")
    used_token, card_number = service.use_token(token.id)
    print(f"   Card number retrieved: {card_number[:4]}...{card_number[-4:]}")
    print(f"   Token marked as used: {used_token.used}")
    
    # Try to use again (should fail)
    print("\n3. Trying to use token again:")
    try:
        service.use_token(token.id)
    except TokenAlreadyUsedError as e:
        print(f"   Error (expected): {e}")
    
    # Test invalid card
    print("\n4. Testing invalid card number:")
    try:
        service.create_token(
            card_number="1234567890123456",
            exp_month=12,
            exp_year=2025,
            cvv="123"
        )
    except InvalidCardError as e:
        print(f"   Error (expected): {e} (code: {e.code})")
    
    # Test expired card
    print("\n5. Testing expired card:")
    try:
        service.create_token(
            card_number="4242424242424242",
            exp_month=1,
            exp_year=2020,
            cvv="123"
        )
    except InvalidCardError as e:
        print(f"   Error (expected): {e} (code: {e.code})")


if __name__ == "__main__":
    demo_tokenization()
