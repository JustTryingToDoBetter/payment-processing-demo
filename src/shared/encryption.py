"""
Encryption utilities for secure data handling.

IMPORTANT: This is an EDUCATIONAL implementation.
Production systems should use:
- Hardware Security Modules (HSMs)
- Cloud KMS (AWS KMS, Google Cloud KMS, Azure Key Vault)
- Proper key management procedures

This module demonstrates the CONCEPTS of encryption at rest.
"""

import os
import base64
import hashlib
import hmac
import secrets
from dataclasses import dataclass
from typing import Optional
from datetime import datetime, timedelta

# Using cryptography library for proper encryption
try:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
    from cryptography.hazmat.primitives import hashes
    CRYPTO_AVAILABLE = True
except ImportError:
    CRYPTO_AVAILABLE = False
    print("Warning: cryptography library not installed. Using mock encryption.")


@dataclass
class EncryptedData:
    """
    Container for encrypted data with all metadata needed for decryption.
    """
    ciphertext: str      # Base64 encoded encrypted data
    nonce: str           # Base64 encoded nonce/IV
    salt: str            # Base64 encoded salt for key derivation
    key_version: str     # Which key was used (for rotation)
    algorithm: str       # Algorithm used
    created_at: datetime


class EncryptionService:
    """
    Encryption service for sensitive data (like card numbers).
    
    Key concepts demonstrated:
    - AES-256-GCM for symmetric encryption (authenticated encryption)
    - Key derivation from master key
    - Unique nonce per encryption
    - Key versioning for rotation
    
    In production, the master key would be in an HSM, not memory.
    """
    
    ALGORITHM = "AES-256-GCM"
    KEY_LENGTH = 32  # 256 bits
    NONCE_LENGTH = 12  # 96 bits for GCM
    SALT_LENGTH = 16  # 128 bits
    
    def __init__(self, master_key: Optional[bytes] = None, key_version: str = "v1"):
        """
        Initialize encryption service.
        
        Args:
            master_key: The master encryption key (32 bytes for AES-256)
                       In production, this comes from HSM/KMS
            key_version: Version identifier for key rotation
        """
        if master_key:
            self.master_key = master_key
        else:
            # Generate a random key for demo purposes
            # In production: NEVER generate keys this way
            self.master_key = os.urandom(self.KEY_LENGTH)
        
        self.key_version = key_version
        
        if not CRYPTO_AVAILABLE:
            print("⚠️  Running in mock mode - data not actually encrypted!")
    
    def encrypt(self, plaintext: str) -> EncryptedData:
        """
        Encrypt sensitive data.
        
        Each encryption uses:
        - Unique salt for key derivation
        - Unique nonce for encryption
        - Authenticated encryption (GCM) to detect tampering
        
        Args:
            plaintext: The data to encrypt
            
        Returns:
            EncryptedData with all components needed for decryption
        """
        if not CRYPTO_AVAILABLE:
            # Mock encryption for demo without cryptography library
            return EncryptedData(
                ciphertext=base64.b64encode(plaintext.encode()).decode(),
                nonce=base64.b64encode(os.urandom(self.NONCE_LENGTH)).decode(),
                salt=base64.b64encode(os.urandom(self.SALT_LENGTH)).decode(),
                key_version=self.key_version,
                algorithm=self.ALGORITHM + "-MOCK",
                created_at=datetime.utcnow()
            )
        
        # Generate unique salt and nonce
        salt = os.urandom(self.SALT_LENGTH)
        nonce = os.urandom(self.NONCE_LENGTH)
        
        # Derive encryption key from master key + salt
        # This allows different data to have different encryption keys
        derived_key = self._derive_key(salt)
        
        # Encrypt using AES-256-GCM
        aesgcm = AESGCM(derived_key)
        ciphertext = aesgcm.encrypt(nonce, plaintext.encode(), None)
        
        return EncryptedData(
            ciphertext=base64.b64encode(ciphertext).decode(),
            nonce=base64.b64encode(nonce).decode(),
            salt=base64.b64encode(salt).decode(),
            key_version=self.key_version,
            algorithm=self.ALGORITHM,
            created_at=datetime.utcnow()
        )
    
    def decrypt(self, encrypted: EncryptedData) -> str:
        """
        Decrypt encrypted data.
        
        Args:
            encrypted: The EncryptedData object
            
        Returns:
            The original plaintext
            
        Raises:
            ValueError: If decryption fails (wrong key or tampered data)
        """
        if not CRYPTO_AVAILABLE or encrypted.algorithm.endswith("-MOCK"):
            # Mock decryption
            return base64.b64decode(encrypted.ciphertext).decode()
        
        # Decode components
        ciphertext = base64.b64decode(encrypted.ciphertext)
        nonce = base64.b64decode(encrypted.nonce)
        salt = base64.b64decode(encrypted.salt)
        
        # Verify key version matches
        if encrypted.key_version != self.key_version:
            raise ValueError(
                f"Key version mismatch: data encrypted with {encrypted.key_version}, "
                f"but current key is {self.key_version}"
            )
        
        # Derive the same key using the stored salt
        derived_key = self._derive_key(salt)
        
        # Decrypt
        aesgcm = AESGCM(derived_key)
        try:
            plaintext = aesgcm.decrypt(nonce, ciphertext, None)
            return plaintext.decode()
        except Exception as e:
            raise ValueError(f"Decryption failed: {e}")
    
    def _derive_key(self, salt: bytes) -> bytes:
        """
        Derive an encryption key from master key using PBKDF2.
        
        This allows each piece of data to have its own key derived
        from the master key, providing additional security.
        """
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=self.KEY_LENGTH,
            salt=salt,
            iterations=100000,  # OWASP recommended minimum
        )
        return kdf.derive(self.master_key)


class CardMasker:
    """
    Utility for masking card numbers for display.
    
    Card numbers should be masked in logs, UI, and storage.
    Only the last 4 digits are safe to display.
    """
    
    @staticmethod
    def mask(card_number: str) -> str:
        """
        Mask a card number showing only last 4 digits.
        
        Examples:
            4242424242424242 → ************4242
            4242 4242 4242 4242 → **** **** **** 4242
        """
        # Remove non-digits
        digits_only = ''.join(c for c in card_number if c.isdigit())
        
        if len(digits_only) < 4:
            return '*' * len(digits_only)
        
        # Check if original had spaces (for formatting)
        if ' ' in card_number:
            # Maintain spacing pattern
            parts = card_number.split()
            masked_parts = ['*' * len(p) for p in parts[:-1]]
            last_part = parts[-1]
            masked_parts.append('*' * (len(last_part) - 4) + last_part[-4:])
            return ' '.join(masked_parts)
        
        # No spaces - simple masking
        return '*' * (len(digits_only) - 4) + digits_only[-4:]
    
    @staticmethod
    def get_last_four(card_number: str) -> str:
        """Get just the last 4 digits."""
        digits_only = ''.join(c for c in card_number if c.isdigit())
        return digits_only[-4:] if len(digits_only) >= 4 else digits_only


class SignatureGenerator:
    """
    Generate and verify HMAC signatures for webhooks and API requests.
    
    Used to:
    - Sign webhook payloads so merchants can verify authenticity
    - Sign API requests for additional security
    """
    
    def __init__(self, secret_key: str):
        """
        Initialize with signing secret.
        
        Args:
            secret_key: The shared secret for HMAC signing
        """
        self.secret_key = secret_key.encode() if isinstance(secret_key, str) else secret_key
    
    def sign(self, payload: str, timestamp: Optional[int] = None) -> str:
        """
        Create HMAC-SHA256 signature for a payload.
        
        Args:
            payload: The data to sign
            timestamp: Unix timestamp (added to prevent replay attacks)
            
        Returns:
            The signature string
        """
        if timestamp is None:
            timestamp = int(datetime.utcnow().timestamp())
        
        # Include timestamp in signed data
        signed_data = f"{timestamp}.{payload}"
        
        signature = hmac.new(
            self.secret_key,
            signed_data.encode(),
            hashlib.sha256
        ).hexdigest()
        
        return f"t={timestamp},v1={signature}"
    
    def verify(self, payload: str, signature: str, tolerance_seconds: int = 300) -> bool:
        """
        Verify a signature is valid and recent.
        
        Args:
            payload: The original data
            signature: The signature string (format: t=xxx,v1=xxx)
            tolerance_seconds: How old a signature can be (prevents replay)
            
        Returns:
            True if signature is valid and recent
        """
        try:
            # Parse signature components
            parts = dict(part.split('=') for part in signature.split(','))
            timestamp = int(parts['t'])
            provided_sig = parts['v1']
            
            # Check timestamp is recent
            current_time = int(datetime.utcnow().timestamp())
            if abs(current_time - timestamp) > tolerance_seconds:
                return False
            
            # Recreate expected signature
            signed_data = f"{timestamp}.{payload}"
            expected_sig = hmac.new(
                self.secret_key,
                signed_data.encode(),
                hashlib.sha256
            ).hexdigest()
            
            # Constant-time comparison to prevent timing attacks
            return hmac.compare_digest(expected_sig, provided_sig)
            
        except (KeyError, ValueError):
            return False


class TokenGenerator:
    """
    Generate secure random tokens for various purposes.
    """
    
    @staticmethod
    def generate(prefix: str = "", length: int = 24) -> str:
        """
        Generate a cryptographically secure random token.
        
        Args:
            prefix: Prefix for the token (e.g., 'tok_', 'ch_')
            length: Length of random part
            
        Returns:
            Token like 'tok_a1b2c3d4e5f6...'
        """
        # Use secrets module for cryptographically secure random
        random_part = secrets.token_urlsafe(length)[:length]
        return f"{prefix}{random_part}"
    
    @staticmethod
    def generate_idempotency_key() -> str:
        """Generate a unique idempotency key."""
        return TokenGenerator.generate("idem_", 32)
    
    @staticmethod
    def generate_api_key(prefix: str = "sk_live_") -> str:
        """Generate an API key."""
        return TokenGenerator.generate(prefix, 32)


# =============================================================================
# Fingerprinting for fraud detection
# =============================================================================

class CardFingerprint:
    """
    Generate fingerprints for cards without storing the actual number.
    
    Fingerprints allow detecting if the same card is used again
    without storing the actual card number.
    
    Note: This uses a deterministic hash, so the same card always
    produces the same fingerprint (within a merchant account).
    """
    
    def __init__(self, salt: str):
        """
        Initialize with a merchant-specific salt.
        
        The salt ensures fingerprints are unique per merchant,
        so a fingerprint from one merchant can't be used at another.
        """
        self.salt = salt.encode()
    
    def generate(self, card_number: str, exp_month: int, exp_year: int) -> str:
        """
        Generate a fingerprint for a card.
        
        Uses card number + expiry to generate deterministic hash.
        """
        # Normalize card number
        normalized = card_number.replace(" ", "").replace("-", "")
        
        # Combine card details
        data = f"{normalized}:{exp_month:02d}:{exp_year}"
        
        # Generate HMAC fingerprint
        fingerprint = hmac.new(
            self.salt,
            data.encode(),
            hashlib.sha256
        ).hexdigest()[:32]
        
        return f"fp_{fingerprint}"


# =============================================================================
# Demo/Testing utilities
# =============================================================================

def demo_encryption():
    """Demonstrate encryption functionality."""
    print("=" * 60)
    print("ENCRYPTION DEMO")
    print("=" * 60)
    
    # Initialize encryption service
    encryption = EncryptionService()
    
    # Encrypt a card number
    card_number = "4242424242424242"
    print(f"\nOriginal card: {card_number}")
    
    encrypted = encryption.encrypt(card_number)
    print(f"\nEncrypted:")
    print(f"  Ciphertext: {encrypted.ciphertext[:40]}...")
    print(f"  Nonce: {encrypted.nonce}")
    print(f"  Salt: {encrypted.salt}")
    print(f"  Algorithm: {encrypted.algorithm}")
    print(f"  Key Version: {encrypted.key_version}")
    
    # Decrypt
    decrypted = encryption.decrypt(encrypted)
    print(f"\nDecrypted: {decrypted}")
    print(f"Match: {decrypted == card_number}")
    
    # Demonstrate masking
    print("\n" + "=" * 60)
    print("CARD MASKING")
    print("=" * 60)
    
    masker = CardMasker()
    print(f"\nOriginal: {card_number}")
    print(f"Masked: {masker.mask(card_number)}")
    print(f"Last 4: {masker.get_last_four(card_number)}")
    
    formatted = "4242 4242 4242 4242"
    print(f"\nFormatted: {formatted}")
    print(f"Masked: {masker.mask(formatted)}")
    
    # Demonstrate signatures
    print("\n" + "=" * 60)
    print("WEBHOOK SIGNATURES")
    print("=" * 60)
    
    signer = SignatureGenerator("whsec_test_secret_key")
    
    payload = '{"event": "charge.succeeded", "amount": 9900}'
    signature = signer.sign(payload)
    print(f"\nPayload: {payload}")
    print(f"Signature: {signature}")
    
    is_valid = signer.verify(payload, signature)
    print(f"Verification: {'✓ Valid' if is_valid else '✗ Invalid'}")
    
    # Test with tampered payload
    is_valid = signer.verify(payload + "x", signature)
    print(f"Tampered verification: {'✓ Valid' if is_valid else '✗ Invalid (expected)'}")


if __name__ == "__main__":
    demo_encryption()
