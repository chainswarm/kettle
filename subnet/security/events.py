"""
SecurityEvent model and SecurityEventIndexer.

Design principle: "good is good, let it go" — only index rejections and failures.
Passing verifications and normal operations are NOT indexed.

Events are stored in RocksDB using named maps (nmap) for efficient querying:

  nmap="security_events"  key="{timestamp}:{event_type}:{peer_id_short}"  value=event_dict
  nmap="security_by_peer" key="{peer_id}:{timestamp}"                     value=event_dict
  nmap="security_by_type" key="{event_type}:{timestamp}:{peer_id_short}"  value=event_dict

This triple-index pattern enables querying by:
  - Time range (scan security_events)
  - Peer (scan security_by_peer with prefix)
  - Event type (scan security_by_type with prefix)
"""

from __future__ import annotations

import logging
import time
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

from subnet.utils.db.database import RocksDB

logger = logging.getLogger(__name__)


class SecurityEventType(str, Enum):
    """Categories of security events that get indexed."""

    # TEE verification rejections
    TEE_QUOTE_NOT_FOUND = "tee_quote_not_found"
    TEE_DEBUG_MODE = "tee_debug_mode"
    TEE_NONCE_MISMATCH = "tee_nonce_mismatch"
    TEE_IDENTITY_BINDING_FAILED = "tee_identity_binding_failed"
    TEE_CHAIN_VERIFICATION_FAILED = "tee_chain_verification_failed"
    TEE_MEASUREMENT_MISMATCH = "tee_measurement_mismatch"
    TEE_VULNERABLE_FIRMWARE = "tee_vulnerable_firmware"
    TEE_TCB_POLICY_FAILED = "tee_tcb_policy_failed"
    TEE_DUPLICATE_HARDWARE = "tee_duplicate_hardware"
    TEE_DUPLICATE_GPU = "tee_duplicate_gpu"

    # Overwatch events
    OVERWATCH_SLASH = "overwatch_slash"

    # Scoring failures
    SCORING_ERROR = "scoring_error"
    SCORING_UNREACHABLE = "scoring_unreachable"


class SecuritySeverity(str, Enum):
    """Severity levels for security events."""

    LOW = "low"          # Operational issues (quote not found, unreachable)
    MEDIUM = "medium"    # Suspicious (nonce mismatch, debug mode)
    HIGH = "high"        # Active threats (duplicate hardware, chain verification failed)
    CRITICAL = "critical"  # Overwatch slashes, vulnerable firmware


# Map event types to default severity
_DEFAULT_SEVERITY: Dict[SecurityEventType, SecuritySeverity] = {
    SecurityEventType.TEE_QUOTE_NOT_FOUND: SecuritySeverity.LOW,
    SecurityEventType.TEE_DEBUG_MODE: SecuritySeverity.MEDIUM,
    SecurityEventType.TEE_NONCE_MISMATCH: SecuritySeverity.MEDIUM,
    SecurityEventType.TEE_IDENTITY_BINDING_FAILED: SecuritySeverity.HIGH,
    SecurityEventType.TEE_CHAIN_VERIFICATION_FAILED: SecuritySeverity.HIGH,
    SecurityEventType.TEE_MEASUREMENT_MISMATCH: SecuritySeverity.HIGH,
    SecurityEventType.TEE_VULNERABLE_FIRMWARE: SecuritySeverity.CRITICAL,
    SecurityEventType.TEE_TCB_POLICY_FAILED: SecuritySeverity.MEDIUM,
    SecurityEventType.TEE_DUPLICATE_HARDWARE: SecuritySeverity.HIGH,
    SecurityEventType.TEE_DUPLICATE_GPU: SecuritySeverity.HIGH,
    SecurityEventType.OVERWATCH_SLASH: SecuritySeverity.CRITICAL,
    SecurityEventType.SCORING_ERROR: SecuritySeverity.LOW,
    SecurityEventType.SCORING_UNREACHABLE: SecuritySeverity.LOW,
}


@dataclass
class SecurityEvent:
    """
    A security event record — represents a single rejection or failure.

    Fields
    ------
    event_type  : category of the security event
    peer_id     : the peer involved (empty string if not applicable)
    epoch       : the subnet epoch when this occurred
    reason      : human-readable rejection reason from the verifier
    severity    : LOW / MEDIUM / HIGH / CRITICAL
    timestamp   : unix timestamp (float) when the event was created
    details     : additional structured data (e.g., expected vs got values)
    """

    event_type: str
    peer_id: str
    epoch: int
    reason: str
    severity: str
    timestamp: float = field(default_factory=time.time)
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Serialise to a dict for RocksDB storage."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> SecurityEvent:
        """Deserialise from a dict."""
        return cls(**data)


# ── Named map constants ──────────────────────────────────────────────
SECURITY_EVENTS_NMAP = "security_events"
SECURITY_BY_PEER_NMAP = "security_by_peer"
SECURITY_BY_TYPE_NMAP = "security_by_type"


class SecurityEventIndexer:
    """
    Indexes security events into RocksDB for audit and querying.

    Thread-safe for single-writer (the validator node). Multiple readers
    can use a secondary RocksDB instance.

    Usage:
        indexer = SecurityEventIndexer(db)
        indexer.record_tee_rejection(peer_id, epoch, "nonce_mismatch:got=5,expected=6")
        indexer.record_overwatch_slash(peer_id, epoch, evidence={...})

        # Query
        events = indexer.get_events_by_peer(peer_id)
        recent = indexer.get_recent_events(limit=50)
    """

    def __init__(self, db: RocksDB) -> None:
        self._db = db

    # ── Recording methods ────────────────────────────────────────────

    def record(self, event: SecurityEvent) -> None:
        """
        Index a security event into all three nmaps.

        This is the low-level method. Prefer the typed helpers below.
        """
        ts = f"{event.timestamp:.6f}"
        peer_short = event.peer_id[:16] if event.peer_id else "unknown"
        event_dict = event.to_dict()

        # Primary index: by time
        primary_key = f"{ts}:{event.event_type}:{peer_short}"
        self._db.nmap_set(SECURITY_EVENTS_NMAP, primary_key, event_dict)

        # Secondary index: by peer
        if event.peer_id:
            peer_key = f"{event.peer_id}:{ts}"
            self._db.nmap_set(SECURITY_BY_PEER_NMAP, peer_key, event_dict)

        # Tertiary index: by type
        type_key = f"{event.event_type}:{ts}:{peer_short}"
        self._db.nmap_set(SECURITY_BY_TYPE_NMAP, type_key, event_dict)

        logger.info(
            "[SecurityIndex] Recorded %s peer=%s epoch=%d severity=%s",
            event.event_type, peer_short, event.epoch, event.severity,
        )

    def record_tee_rejection(
        self,
        peer_id: str,
        epoch: int,
        rejection_reason: str,
        details: Optional[Dict[str, Any]] = None,
    ) -> SecurityEvent:
        """
        Record a TEE verification rejection.

        Maps the rejection_reason string from DcapVerifier to a SecurityEventType
        and assigns appropriate severity.
        """
        event_type = self._map_tee_reason(rejection_reason)
        severity = _DEFAULT_SEVERITY.get(event_type, SecuritySeverity.MEDIUM)

        event = SecurityEvent(
            event_type=event_type.value,
            peer_id=peer_id,
            epoch=epoch,
            reason=rejection_reason,
            severity=severity.value,
            details=details or {},
        )
        self.record(event)
        return event

    def record_overwatch_slash(
        self,
        peer_id: str,
        epoch: int,
        reason: str = "overwatch_slash",
        evidence: Optional[Dict[str, Any]] = None,
    ) -> SecurityEvent:
        """Record an overwatch slash event."""
        event = SecurityEvent(
            event_type=SecurityEventType.OVERWATCH_SLASH.value,
            peer_id=peer_id,
            epoch=epoch,
            reason=reason,
            severity=SecuritySeverity.CRITICAL.value,
            details=evidence or {},
        )
        self.record(event)
        return event

    def record_scoring_failure(
        self,
        peer_id: str,
        epoch: int,
        reason: str,
        details: Optional[Dict[str, Any]] = None,
    ) -> SecurityEvent:
        """Record a scoring failure (unreachable node, scoring error)."""
        if "unreachable" in reason.lower():
            event_type = SecurityEventType.SCORING_UNREACHABLE
        else:
            event_type = SecurityEventType.SCORING_ERROR
        severity = _DEFAULT_SEVERITY.get(event_type, SecuritySeverity.LOW)

        event = SecurityEvent(
            event_type=event_type.value,
            peer_id=peer_id,
            epoch=epoch,
            reason=reason,
            severity=severity.value,
            details=details or {},
        )
        self.record(event)
        return event

    # ── Query methods ────────────────────────────────────────────────

    def get_recent_events(self, limit: int = 100) -> List[Dict[str, Any]]:
        """
        Get the most recent security events, ordered by timestamp descending.

        Uses the primary time-ordered nmap. Returns dicts (not SecurityEvent
        instances) for API serialisation convenience.
        """
        all_events = self._db.nmap_get_all(SECURITY_EVENTS_NMAP)
        # Keys are "{timestamp}:{type}:{peer}" — lexicographic sort = time sort
        sorted_keys = sorted(all_events.keys(), reverse=True)
        return [all_events[k] for k in sorted_keys[:limit]]

    def get_events_by_peer(
        self, peer_id: str, limit: int = 100
    ) -> List[Dict[str, Any]]:
        """Get security events for a specific peer, most recent first."""
        all_peer_events = self._db.nmap_get_all(SECURITY_BY_PEER_NMAP)
        prefix = f"{peer_id}:"
        matching = {
            k: v for k, v in all_peer_events.items() if k.startswith(prefix)
        }
        sorted_keys = sorted(matching.keys(), reverse=True)
        return [matching[k] for k in sorted_keys[:limit]]

    def get_events_by_type(
        self, event_type: str, limit: int = 100
    ) -> List[Dict[str, Any]]:
        """Get security events of a specific type, most recent first."""
        all_type_events = self._db.nmap_get_all(SECURITY_BY_TYPE_NMAP)
        prefix = f"{event_type}:"
        matching = {
            k: v for k, v in all_type_events.items() if k.startswith(prefix)
        }
        sorted_keys = sorted(matching.keys(), reverse=True)
        return [matching[k] for k in sorted_keys[:limit]]

    def get_event_counts(self) -> Dict[str, int]:
        """Get count of events per event type."""
        all_events = self._db.nmap_get_all(SECURITY_EVENTS_NMAP)
        counts: Dict[str, int] = {}
        for event_dict in all_events.values():
            etype = event_dict.get("event_type", "unknown")
            counts[etype] = counts.get(etype, 0) + 1
        return counts

    def get_event_counts_by_severity(self) -> Dict[str, int]:
        """Get count of events per severity level."""
        all_events = self._db.nmap_get_all(SECURITY_EVENTS_NMAP)
        counts: Dict[str, int] = {}
        for event_dict in all_events.values():
            sev = event_dict.get("severity", "unknown")
            counts[sev] = counts.get(sev, 0) + 1
        return counts

    # ── Internal helpers ─────────────────────────────────────────────

    @staticmethod
    def _map_tee_reason(rejection_reason: str) -> SecurityEventType:
        """Map a DcapVerifier rejection_reason string to a SecurityEventType."""
        reason_lower = rejection_reason.lower()

        if reason_lower == "quote_not_found":
            return SecurityEventType.TEE_QUOTE_NOT_FOUND
        if reason_lower == "debug_mode":
            return SecurityEventType.TEE_DEBUG_MODE
        if reason_lower.startswith("nonce_mismatch"):
            return SecurityEventType.TEE_NONCE_MISMATCH
        if reason_lower == "identity_binding_failed":
            return SecurityEventType.TEE_IDENTITY_BINDING_FAILED
        if reason_lower.startswith("chain_verification_failed"):
            return SecurityEventType.TEE_CHAIN_VERIFICATION_FAILED
        if reason_lower.startswith("measurement_mismatch"):
            return SecurityEventType.TEE_MEASUREMENT_MISMATCH
        if reason_lower.startswith("vulnerable_firmware"):
            return SecurityEventType.TEE_VULNERABLE_FIRMWARE
        if reason_lower.startswith("duplicate_hardware"):
            return SecurityEventType.TEE_DUPLICATE_HARDWARE
        if reason_lower.startswith("duplicate_gpu"):
            return SecurityEventType.TEE_DUPLICATE_GPU
        if "tcb" in reason_lower or "min_tcb" in reason_lower:
            return SecurityEventType.TEE_TCB_POLICY_FAILED

        # Fallback: chain verification for unknown TEE reasons
        return SecurityEventType.TEE_CHAIN_VERIFICATION_FAILED
