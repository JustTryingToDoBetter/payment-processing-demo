"""
Idempotency handling for safe payment retries.

Idempotency ensures that an operation produces the same result
no matter how many times it's called with the same key.

This is CRITICAL for payments because:
- Networks can timeout after the charge succeeds
- Clients may retry not knowing if the first request worked
- Without idempotency, customers could be charged multiple times
"""

import json
import hashlib
import threading
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, Optional
from enum import Enum


class IdempotencyStatus(str, Enum):
    """Status of an idempotent operation."""
    PENDING = "pending"       # Currently being processed
    COMPLETED = "completed"   # Finished, result stored
    FAILED = "failed"        # Failed, error stored


@dataclass
class IdempotencyRecord:
    """
    Record of an idempotent operation.
    """
    key: str
    status: IdempotencyStatus
    request_hash: str               # Hash of request params for validation
    result: Optional[Dict] = None   # Stored result if completed
    error: Optional[Dict] = None    # Stored error if failed
    created_at: datetime = field(default_factory=datetime.utcnow)
    expires_at: datetime = field(default_factory=lambda: datetime.utcnow() + timedelta(hours=24))
    
    def is_expired(self) -> bool:
        return datetime.utcnow() > self.expires_at


class IdempotencyStore:
    """
    In-memory idempotency store for demonstration.
    
    In production, use Redis or another distributed cache:
    - Supports TTL for automatic expiration
    - Handles concurrent requests across multiple servers
    - Persists across restarts
    """
    
    def __init__(self, ttl_hours: int = 24):
        self.ttl_hours = ttl_hours
        self._store: Dict[str, IdempotencyRecord] = {}
        self._lock = threading.Lock()
    
    def get(self, key: str) -> Optional[IdempotencyRecord]:
        """Get a record by idempotency key."""
        with self._lock:
            record = self._store.get(key)
            if record and record.is_expired():
                del self._store[key]
                return None
            return record
    
    def set(self, record: IdempotencyRecord) -> None:
        """Store or update a record."""
        with self._lock:
            self._store[record.key] = record
    
    def delete(self, key: str) -> None:
        """Delete a record."""
        with self._lock:
            self._store.pop(key, None)
    
    def cleanup_expired(self) -> int:
        """Remove expired records. Returns count removed."""
        with self._lock:
            expired_keys = [
                k for k, v in self._store.items()
                if v.is_expired()
            ]
            for key in expired_keys:
                del self._store[key]
            return len(expired_keys)


class IdempotencyService:
    """
    Service for handling idempotent operations.
    
    Usage:
        idempotency = IdempotencyService()
        
        def create_charge(amount, token):
            return gateway.charge(amount=amount, token=token)
        
        # This is safe to call multiple times with the same key
        result = idempotency.execute(
            key="order_123_charge",
            operation=lambda: create_charge(9900, "tok_xxx"),
            request_params={"amount": 9900, "token": "tok_xxx"}
        )
    """
    
    def __init__(self, store: Optional[IdempotencyStore] = None):
        self.store = store or IdempotencyStore()
        self._locks: Dict[str, threading.Lock] = {}
        self._locks_lock = threading.Lock()
    
    def execute(
        self,
        key: str,
        operation: Callable[[], Any],
        request_params: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Execute an operation with idempotency protection.
        
        Args:
            key: The idempotency key (should be deterministic for same operation)
            operation: The function to execute
            request_params: Parameters to hash for validation
            
        Returns:
            The operation result (either fresh or cached)
            
        Raises:
            IdempotencyConflict: If same key used with different params
            IdempotencyInProgress: If another request is processing
        """
        # Hash the request params to detect misuse
        request_hash = self._hash_params(request_params)
        
        # Check for existing record
        existing = self.store.get(key)
        
        if existing:
            return self._handle_existing_record(existing, request_hash)
        
        # No existing record - acquire lock and process
        lock = self._get_lock(key)
        
        if not lock.acquire(blocking=False):
            # Another thread is processing - wait briefly
            if lock.acquire(timeout=30):
                lock.release()
                # Re-check store after acquiring lock
                existing = self.store.get(key)
                if existing:
                    return self._handle_existing_record(existing, request_hash)
            raise IdempotencyInProgress(
                "Another request with this idempotency key is being processed"
            )
        
        try:
            # Double-check after acquiring lock
            existing = self.store.get(key)
            if existing:
                return self._handle_existing_record(existing, request_hash)
            
            # Create pending record
            record = IdempotencyRecord(
                key=key,
                status=IdempotencyStatus.PENDING,
                request_hash=request_hash
            )
            self.store.set(record)
            
            try:
                # Execute the operation
                result = operation()
                
                # Store successful result
                record.status = IdempotencyStatus.COMPLETED
                record.result = self._serialize_result(result)
                self.store.set(record)
                
                return record.result
                
            except Exception as e:
                # Store error for consistency
                record.status = IdempotencyStatus.FAILED
                record.error = {"type": type(e).__name__, "message": str(e)}
                self.store.set(record)
                raise
                
        finally:
            lock.release()
    
    def _handle_existing_record(
        self, 
        record: IdempotencyRecord, 
        request_hash: str
    ) -> Dict[str, Any]:
        """Handle case where we already have a record for this key."""
        
        # Verify request params match
        if record.request_hash != request_hash:
            raise IdempotencyConflict(
                f"Idempotency key '{record.key}' was used with different parameters. "
                "Use a new key for different operations."
            )
        
        if record.status == IdempotencyStatus.PENDING:
            raise IdempotencyInProgress(
                "This request is currently being processed"
            )
        
        if record.status == IdempotencyStatus.FAILED:
            # Re-raise the original error
            error = record.error
            raise IdempotencyFailedPreviously(
                f"Previous request failed with: {error['type']}: {error['message']}"
            )
        
        # Return cached result
        return record.result
    
    def _hash_params(self, params: Dict[str, Any]) -> str:
        """Create deterministic hash of request parameters."""
        # Sort keys for deterministic ordering
        serialized = json.dumps(params, sort_keys=True, default=str)
        return hashlib.sha256(serialized.encode()).hexdigest()[:16]
    
    def _serialize_result(self, result: Any) -> Dict:
        """Serialize result for storage."""
        if isinstance(result, dict):
            return result
        if hasattr(result, '__dict__'):
            return result.__dict__
        return {"value": str(result)}
    
    def _get_lock(self, key: str) -> threading.Lock:
        """Get or create a lock for an idempotency key."""
        with self._locks_lock:
            if key not in self._locks:
                self._locks[key] = threading.Lock()
            return self._locks[key]


# =============================================================================
# Exceptions
# =============================================================================

class IdempotencyError(Exception):
    """Base exception for idempotency errors."""
    pass


class IdempotencyConflict(IdempotencyError):
    """
    Raised when idempotency key is reused with different parameters.
    
    This indicates programmer error - the same key should always
    represent the same operation.
    """
    pass


class IdempotencyInProgress(IdempotencyError):
    """
    Raised when another request with the same key is being processed.
    
    The client should wait and retry.
    """
    pass


class IdempotencyFailedPreviously(IdempotencyError):
    """
    Raised when a previous request with this key failed.
    
    The client should use a new idempotency key to retry.
    """
    pass


# =============================================================================
# Key Generation Helpers
# =============================================================================

class IdempotencyKeyBuilder:
    """
    Helper for building good idempotency keys.
    
    Good keys are:
    - Deterministic for the same logical operation
    - Include all relevant context (order ID, action, etc.)
    - Meaningful for debugging
    
    Bad keys are:
    - Random UUIDs (different each time!)
    - Including timestamps (changes each request!)
    """
    
    @staticmethod
    def for_charge(order_id: str, attempt: int = 1) -> str:
        """
        Create idempotency key for a charge.
        
        Args:
            order_id: The order being charged
            attempt: Attempt number (increment for genuine retries with new card)
        """
        return f"charge:{order_id}:v{attempt}"
    
    @staticmethod
    def for_refund(charge_id: str, amount_cents: int) -> str:
        """
        Create idempotency key for a refund.
        
        Args:
            charge_id: The charge being refunded
            amount_cents: The refund amount
        """
        return f"refund:{charge_id}:{amount_cents}"
    
    @staticmethod
    def for_capture(authorization_id: str) -> str:
        """
        Create idempotency key for a capture.
        
        Args:
            authorization_id: The authorization being captured
        """
        return f"capture:{authorization_id}"
    
    @staticmethod
    def custom(action: str, *identifiers) -> str:
        """
        Create a custom idempotency key.
        
        Args:
            action: The action being performed
            identifiers: Unique identifiers for this operation
        """
        parts = [action] + [str(i) for i in identifiers]
        return ":".join(parts)


# =============================================================================
# Demo
# =============================================================================

def demo_idempotency():
    """Demonstrate idempotency handling."""
    print("=" * 60)
    print("IDEMPOTENCY DEMO")
    print("=" * 60)
    
    service = IdempotencyService()
    
    # Simulate a charge operation
    call_count = 0
    
    def charge_operation():
        nonlocal call_count
        call_count += 1
        print(f"  → Executing charge (call #{call_count})")
        return {"charge_id": "ch_123", "amount": 9900, "status": "succeeded"}
    
    # First call - actually executes
    print("\n1. First call with key 'order_123':")
    result1 = service.execute(
        key="order_123",
        operation=charge_operation,
        request_params={"amount": 9900, "token": "tok_xxx"}
    )
    print(f"   Result: {result1}")
    
    # Second call - returns cached result
    print("\n2. Second call with same key 'order_123':")
    result2 = service.execute(
        key="order_123",
        operation=charge_operation,
        request_params={"amount": 9900, "token": "tok_xxx"}
    )
    print(f"   Result: {result2}")
    print(f"   (Notice: operation was NOT called again)")
    
    print(f"\n   Total actual executions: {call_count}")
    
    # Try with different params - should fail
    print("\n3. Try same key with different params:")
    try:
        service.execute(
            key="order_123",
            operation=charge_operation,
            request_params={"amount": 5000, "token": "tok_yyy"}  # Different!
        )
    except IdempotencyConflict as e:
        print(f"   Error (expected): {e}")
    
    # New key for different operation
    print("\n4. New key for different operation:")
    result3 = service.execute(
        key="order_456",  # Different key
        operation=charge_operation,
        request_params={"amount": 5000, "token": "tok_yyy"}
    )
    print(f"   Result: {result3}")
    print(f"   Total actual executions: {call_count}")
    
    # Demonstrate key builder
    print("\n" + "=" * 60)
    print("IDEMPOTENCY KEY EXAMPLES")
    print("=" * 60)
    
    builder = IdempotencyKeyBuilder
    print(f"\nCharge key: {builder.for_charge('ord_123')}")
    print(f"Charge retry: {builder.for_charge('ord_123', attempt=2)}")
    print(f"Refund key: {builder.for_refund('ch_abc', 5000)}")
    print(f"Capture key: {builder.for_capture('auth_xyz')}")
    print(f"Custom key: {builder.custom('subscription', 'sub_123', 'renew', '2024-01')}")


if __name__ == "__main__":
    demo_idempotency()
