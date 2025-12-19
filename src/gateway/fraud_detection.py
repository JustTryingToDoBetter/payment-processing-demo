"""
Fraud detection for the payment gateway.

This module implements basic fraud detection patterns:
- Velocity checks (rate limiting)
- Geographic anomalies
- Device fingerprinting
- Risk scoring

In production, fraud detection would also include:
- Machine learning models trained on historical fraud data
- External fraud detection services (Sift, Signifyd, Riskified)
- Cross-merchant intelligence
- Behavioral analysis
"""

import threading
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Set
from dataclasses import dataclass, field
from enum import Enum


class RiskLevel(str, Enum):
    """Risk assessment levels."""
    LOW = "low"           # Proceed normally
    MEDIUM = "medium"     # Consider 3DS or manual review
    HIGH = "high"         # Require 3DS or review
    CRITICAL = "critical" # Decline automatically


class RiskSignalType(str, Enum):
    """Types of fraud signals."""
    VELOCITY_IP = "velocity_ip"
    VELOCITY_CARD = "velocity_card"
    VELOCITY_DEVICE = "velocity_device"
    MULTIPLE_CARDS_DEVICE = "multiple_cards_device"
    GEOGRAPHIC_MISMATCH = "geographic_mismatch"
    HIGH_RISK_COUNTRY = "high_risk_country"
    DISPOSABLE_EMAIL = "disposable_email"
    TEST_AMOUNT = "test_amount"
    HIGH_AMOUNT = "high_amount"
    NEW_CARD = "new_card"
    FAILED_ATTEMPTS = "failed_attempts"


@dataclass
class RiskSignal:
    """
    An individual fraud signal.
    """
    type: RiskSignalType
    score: float  # 0.0 to 1.0 contribution to risk
    reason: str
    metadata: Dict = field(default_factory=dict)


@dataclass
class RiskAssessment:
    """
    Complete risk assessment for a transaction.
    """
    score: float  # 0.0 to 1.0 overall risk
    level: RiskLevel
    signals: List[RiskSignal]
    recommendation: str  # "approve", "3ds_required", "review", "decline"
    
    def to_dict(self) -> Dict:
        return {
            "score": round(self.score, 3),
            "level": self.level.value,
            "signals": [
                {
                    "type": s.type.value,
                    "score": round(s.score, 3),
                    "reason": s.reason
                }
                for s in self.signals
            ],
            "recommendation": self.recommendation
        }


class VelocityTracker:
    """
    Track request velocity for fraud detection.
    
    Uses sliding window counters to track:
    - Requests per IP
    - Requests per card fingerprint
    - Cards per device
    - Failed attempts
    
    In production, use Redis for distributed tracking.
    """
    
    def __init__(self):
        # IP → list of timestamps
        self._ip_requests: Dict[str, List[datetime]] = {}
        
        # Card fingerprint → list of timestamps
        self._card_requests: Dict[str, List[datetime]] = {}
        
        # Device → set of card fingerprints
        self._device_cards: Dict[str, Set[str]] = {}
        
        # IP → failed attempt timestamps
        self._failed_attempts: Dict[str, List[datetime]] = {}
        
        self._lock = threading.Lock()
    
    def record_attempt(
        self,
        ip_address: str,
        card_fingerprint: Optional[str] = None,
        device_id: Optional[str] = None,
        success: bool = True
    ) -> None:
        """Record a payment attempt."""
        now = datetime.utcnow()
        
        with self._lock:
            # Record IP request
            if ip_address not in self._ip_requests:
                self._ip_requests[ip_address] = []
            self._ip_requests[ip_address].append(now)
            
            # Record card request
            if card_fingerprint:
                if card_fingerprint not in self._card_requests:
                    self._card_requests[card_fingerprint] = []
                self._card_requests[card_fingerprint].append(now)
                
                # Track cards per device
                if device_id:
                    if device_id not in self._device_cards:
                        self._device_cards[device_id] = set()
                    self._device_cards[device_id].add(card_fingerprint)
            
            # Record failed attempts
            if not success:
                if ip_address not in self._failed_attempts:
                    self._failed_attempts[ip_address] = []
                self._failed_attempts[ip_address].append(now)
    
    def get_ip_velocity(
        self,
        ip_address: str,
        window_minutes: int = 60
    ) -> int:
        """Get number of requests from IP in time window."""
        return self._count_in_window(
            self._ip_requests.get(ip_address, []),
            window_minutes
        )
    
    def get_card_velocity(
        self,
        card_fingerprint: str,
        window_minutes: int = 10
    ) -> int:
        """Get number of requests for card in time window."""
        return self._count_in_window(
            self._card_requests.get(card_fingerprint, []),
            window_minutes
        )
    
    def get_cards_per_device(self, device_id: str) -> int:
        """Get number of different cards used from device."""
        return len(self._device_cards.get(device_id, set()))
    
    def get_failed_attempts(
        self,
        ip_address: str,
        window_minutes: int = 60
    ) -> int:
        """Get number of failed attempts from IP."""
        return self._count_in_window(
            self._failed_attempts.get(ip_address, []),
            window_minutes
        )
    
    def _count_in_window(
        self,
        timestamps: List[datetime],
        window_minutes: int
    ) -> int:
        """Count timestamps within window."""
        cutoff = datetime.utcnow() - timedelta(minutes=window_minutes)
        return sum(1 for ts in timestamps if ts > cutoff)


class FraudDetector:
    """
    Main fraud detection service.
    
    Analyzes transaction data and produces risk assessments.
    """
    
    # Risk thresholds
    THRESHOLDS = {
        RiskLevel.LOW: 0.3,
        RiskLevel.MEDIUM: 0.5,
        RiskLevel.HIGH: 0.7,
        RiskLevel.CRITICAL: 0.9,
    }
    
    # High-risk countries (example - adjust based on your data)
    HIGH_RISK_COUNTRIES = {"XX", "YY"}  # Placeholder country codes
    
    # Disposable email domains
    DISPOSABLE_EMAIL_DOMAINS = {
        "tempmail.com", "throwaway.com", "guerrillamail.com",
        "temp-mail.org", "fakeinbox.com", "mailinator.com"
    }
    
    def __init__(self, velocity_tracker: Optional[VelocityTracker] = None):
        self.velocity = velocity_tracker or VelocityTracker()
    
    def assess_risk(
        self,
        amount: int,
        card_fingerprint: str,
        ip_address: Optional[str] = None,
        device_id: Optional[str] = None,
        email: Optional[str] = None,
        billing_country: Optional[str] = None,
        ip_country: Optional[str] = None,
        is_new_card: bool = False,
    ) -> RiskAssessment:
        """
        Perform comprehensive risk assessment.
        
        Args:
            amount: Transaction amount in cents
            card_fingerprint: Fingerprint of the card
            ip_address: Customer's IP address
            device_id: Device fingerprint
            email: Customer email
            billing_country: Billing address country
            ip_country: Country derived from IP
            is_new_card: Whether this card has been seen before
            
        Returns:
            RiskAssessment with score, level, and signals
        """
        signals = []
        
        # Check velocity by IP
        if ip_address:
            signals.append(self._check_ip_velocity(ip_address))
            signals.append(self._check_failed_attempts(ip_address))
        
        # Check card velocity
        signals.append(self._check_card_velocity(card_fingerprint))
        
        # Check device
        if device_id:
            signals.append(self._check_device_cards(device_id))
        
        # Check email
        if email:
            signals.append(self._check_email(email))
        
        # Check geography
        if billing_country and ip_country:
            signals.append(
                self._check_geographic_mismatch(billing_country, ip_country)
            )
        
        # Check amount patterns
        signals.append(self._check_amount(amount))
        
        # Check new card risk
        if is_new_card:
            signals.append(RiskSignal(
                type=RiskSignalType.NEW_CARD,
                score=0.1,
                reason="First transaction with this card"
            ))
        
        # Filter out zero-score signals
        active_signals = [s for s in signals if s.score > 0]
        
        # Calculate overall score
        if active_signals:
            # Weighted average with emphasis on high scores
            total_score = sum(s.score for s in active_signals)
            max_score = max(s.score for s in active_signals)
            # Blend average and max (max has more weight for critical signals)
            avg_score = total_score / len(active_signals)
            score = (avg_score * 0.3) + (max_score * 0.7)
            score = min(1.0, score)
        else:
            score = 0.0
        
        # Determine level and recommendation
        level, recommendation = self._get_recommendation(score)
        
        return RiskAssessment(
            score=score,
            level=level,
            signals=active_signals,
            recommendation=recommendation
        )
    
    def _check_ip_velocity(self, ip_address: str) -> RiskSignal:
        """Check request velocity from IP."""
        count = self.velocity.get_ip_velocity(ip_address, window_minutes=60)
        
        if count > 20:
            return RiskSignal(
                type=RiskSignalType.VELOCITY_IP,
                score=0.9,
                reason=f"Very high velocity: {count} requests from IP in 1 hour",
                metadata={"count": count, "window": "1h"}
            )
        elif count > 10:
            return RiskSignal(
                type=RiskSignalType.VELOCITY_IP,
                score=0.6,
                reason=f"High velocity: {count} requests from IP in 1 hour",
                metadata={"count": count, "window": "1h"}
            )
        elif count > 5:
            return RiskSignal(
                type=RiskSignalType.VELOCITY_IP,
                score=0.3,
                reason=f"Elevated velocity: {count} requests from IP in 1 hour",
                metadata={"count": count, "window": "1h"}
            )
        
        return RiskSignal(
            type=RiskSignalType.VELOCITY_IP,
            score=0.0,
            reason="Normal IP velocity"
        )
    
    def _check_card_velocity(self, card_fingerprint: str) -> RiskSignal:
        """Check request velocity for card."""
        count = self.velocity.get_card_velocity(card_fingerprint, window_minutes=10)
        
        if count > 5:
            return RiskSignal(
                type=RiskSignalType.VELOCITY_CARD,
                score=0.95,
                reason=f"Card tested {count} times in 10 minutes (likely CVV brute force)",
                metadata={"count": count, "window": "10m"}
            )
        elif count > 3:
            return RiskSignal(
                type=RiskSignalType.VELOCITY_CARD,
                score=0.7,
                reason=f"Card used {count} times in 10 minutes",
                metadata={"count": count, "window": "10m"}
            )
        
        return RiskSignal(
            type=RiskSignalType.VELOCITY_CARD,
            score=0.0,
            reason="Normal card velocity"
        )
    
    def _check_device_cards(self, device_id: str) -> RiskSignal:
        """Check number of different cards from device."""
        card_count = self.velocity.get_cards_per_device(device_id)
        
        if card_count > 5:
            return RiskSignal(
                type=RiskSignalType.MULTIPLE_CARDS_DEVICE,
                score=0.95,
                reason=f"{card_count} different cards from same device (card testing)",
                metadata={"card_count": card_count}
            )
        elif card_count > 3:
            return RiskSignal(
                type=RiskSignalType.MULTIPLE_CARDS_DEVICE,
                score=0.7,
                reason=f"{card_count} different cards from same device",
                metadata={"card_count": card_count}
            )
        
        return RiskSignal(
            type=RiskSignalType.MULTIPLE_CARDS_DEVICE,
            score=0.0,
            reason="Normal device card count"
        )
    
    def _check_failed_attempts(self, ip_address: str) -> RiskSignal:
        """Check failed payment attempts from IP."""
        count = self.velocity.get_failed_attempts(ip_address, window_minutes=60)
        
        if count > 10:
            return RiskSignal(
                type=RiskSignalType.FAILED_ATTEMPTS,
                score=0.9,
                reason=f"{count} failed attempts from IP in 1 hour",
                metadata={"count": count}
            )
        elif count > 5:
            return RiskSignal(
                type=RiskSignalType.FAILED_ATTEMPTS,
                score=0.5,
                reason=f"{count} failed attempts from IP in 1 hour",
                metadata={"count": count}
            )
        
        return RiskSignal(
            type=RiskSignalType.FAILED_ATTEMPTS,
            score=0.0,
            reason="Normal failure rate"
        )
    
    def _check_email(self, email: str) -> RiskSignal:
        """Check email for fraud signals."""
        if "@" not in email:
            return RiskSignal(
                type=RiskSignalType.DISPOSABLE_EMAIL,
                score=0.3,
                reason="Invalid email format"
            )
        
        domain = email.split("@")[1].lower()
        
        if domain in self.DISPOSABLE_EMAIL_DOMAINS:
            return RiskSignal(
                type=RiskSignalType.DISPOSABLE_EMAIL,
                score=0.7,
                reason="Disposable email domain",
                metadata={"domain": domain}
            )
        
        return RiskSignal(
            type=RiskSignalType.DISPOSABLE_EMAIL,
            score=0.0,
            reason="Normal email"
        )
    
    def _check_geographic_mismatch(
        self,
        billing_country: str,
        ip_country: str
    ) -> RiskSignal:
        """Check for geographic anomalies."""
        billing = billing_country.upper()
        ip = ip_country.upper()
        
        if billing != ip:
            # Some countries are commonly adjacent (e.g., EU)
            # This is simplified - real systems have more nuanced rules
            return RiskSignal(
                type=RiskSignalType.GEOGRAPHIC_MISMATCH,
                score=0.5,
                reason=f"Billing country ({billing}) != IP country ({ip})",
                metadata={"billing_country": billing, "ip_country": ip}
            )
        
        if ip in self.HIGH_RISK_COUNTRIES:
            return RiskSignal(
                type=RiskSignalType.HIGH_RISK_COUNTRY,
                score=0.6,
                reason=f"Transaction from high-risk country: {ip}",
                metadata={"country": ip}
            )
        
        return RiskSignal(
            type=RiskSignalType.GEOGRAPHIC_MISMATCH,
            score=0.0,
            reason="Geography normal"
        )
    
    def _check_amount(self, amount: int) -> RiskSignal:
        """Check for suspicious amount patterns."""
        # Common test amounts (in cents)
        test_amounts = {100, 500, 1000, 2000}  # $1, $5, $10, $20
        
        if amount in test_amounts:
            return RiskSignal(
                type=RiskSignalType.TEST_AMOUNT,
                score=0.3,
                reason=f"Common test amount: ${amount/100:.2f}",
                metadata={"amount": amount}
            )
        
        # Very high amounts
        if amount > 500000:  # Over $5,000
            return RiskSignal(
                type=RiskSignalType.HIGH_AMOUNT,
                score=0.4,
                reason=f"High value transaction: ${amount/100:.2f}",
                metadata={"amount": amount}
            )
        
        return RiskSignal(
            type=RiskSignalType.TEST_AMOUNT,
            score=0.0,
            reason="Normal amount"
        )
    
    def _get_recommendation(self, score: float) -> tuple:
        """Get risk level and recommendation based on score."""
        if score >= self.THRESHOLDS[RiskLevel.CRITICAL]:
            return RiskLevel.CRITICAL, "decline"
        elif score >= self.THRESHOLDS[RiskLevel.HIGH]:
            return RiskLevel.HIGH, "review"
        elif score >= self.THRESHOLDS[RiskLevel.MEDIUM]:
            return RiskLevel.MEDIUM, "3ds_required"
        else:
            return RiskLevel.LOW, "approve"
    
    def record_transaction_result(
        self,
        ip_address: str,
        card_fingerprint: str,
        device_id: Optional[str],
        success: bool
    ) -> None:
        """Record transaction result for velocity tracking."""
        self.velocity.record_attempt(
            ip_address=ip_address,
            card_fingerprint=card_fingerprint,
            device_id=device_id,
            success=success
        )


# =============================================================================
# Demo
# =============================================================================

def demo_fraud_detection():
    """Demonstrate fraud detection."""
    print("=" * 60)
    print("FRAUD DETECTION DEMO")
    print("=" * 60)
    
    detector = FraudDetector()
    
    # Normal transaction
    print("\n1. Normal transaction:")
    assessment1 = detector.assess_risk(
        amount=9900,  # $99
        card_fingerprint="fp_normal_card_123",
        ip_address="192.168.1.1",
        email="customer@gmail.com"
    )
    print(f"   Score: {assessment1.score:.2f}")
    print(f"   Level: {assessment1.level.value}")
    print(f"   Recommendation: {assessment1.recommendation}")
    
    # Simulate multiple requests from same IP
    print("\n2. Simulating high velocity from IP:")
    for i in range(12):
        detector.velocity.record_attempt(
            ip_address="10.0.0.1",
            card_fingerprint=f"fp_card_{i}",
            device_id="device_suspicious",
            success=i % 3 == 0  # Some failures
        )
    
    assessment2 = detector.assess_risk(
        amount=5000,
        card_fingerprint="fp_new_card",
        ip_address="10.0.0.1",
        device_id="device_suspicious"
    )
    print(f"   Score: {assessment2.score:.2f}")
    print(f"   Level: {assessment2.level.value}")
    print(f"   Recommendation: {assessment2.recommendation}")
    print(f"   Signals:")
    for signal in assessment2.signals:
        print(f"      - {signal.type.value}: {signal.reason}")
    
    # Transaction with disposable email
    print("\n3. Disposable email transaction:")
    assessment3 = detector.assess_risk(
        amount=50000,  # $500
        card_fingerprint="fp_disposable_123",
        email="test@tempmail.com"
    )
    print(f"   Score: {assessment3.score:.2f}")
    print(f"   Level: {assessment3.level.value}")
    print(f"   Recommendation: {assessment3.recommendation}")
    
    # Multiple cards from device
    print("\n4. Multiple cards from same device:")
    for i in range(6):
        detector.velocity.record_attempt(
            ip_address="172.16.0.1",
            card_fingerprint=f"fp_card_test_{i}",
            device_id="device_card_testing"
        )
    
    assessment4 = detector.assess_risk(
        amount=100,  # $1 - test amount!
        card_fingerprint="fp_card_test_new",
        device_id="device_card_testing"
    )
    print(f"   Score: {assessment4.score:.2f}")
    print(f"   Level: {assessment4.level.value}")
    print(f"   Recommendation: {assessment4.recommendation}")
    print(f"   Signals:")
    for signal in assessment4.signals:
        print(f"      - {signal.type.value}: {signal.reason}")


if __name__ == "__main__":
    demo_fraud_detection()
