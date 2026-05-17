"""Pydantic models for the Explorer API."""

from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class EventType(str, Enum):
    """Types of security-relevant events in the subnet."""

    HEARTBEAT = "heartbeat"
    TEE_QUOTE = "tee_quote"
    WORK_RECORD = "work_record"
    OVERWATCH_AUDIT = "overwatch_audit"


class Severity(str, Enum):
    """Severity levels for security events."""

    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class SecurityEvent(BaseModel):
    """A single security-relevant event from the subnet."""

    event_id: str = Field(description="Unique event identifier (topic:epoch:peer_id)")
    epoch: int = Field(description="Epoch in which the event occurred")
    peer_id: str = Field(description="Peer ID of the node involved")
    event_type: EventType = Field(description="Type of event")
    severity: Severity = Field(default=Severity.INFO, description="Event severity")
    summary: str = Field(default="", description="Human-readable event summary")
    data: Dict[str, Any] = Field(default_factory=dict, description="Raw event payload")
    hardware_id: Optional[str] = Field(default=None, description="Hardware/CHIP_ID if available")


class EpochSummary(BaseModel):
    """Summary of a single epoch's activity."""

    epoch: int
    node_count: int = Field(description="Number of unique nodes active in this epoch")
    event_count: int = Field(description="Total events in this epoch")
    heartbeat_count: int = 0
    tee_quote_count: int = 0
    work_record_count: int = 0
    overwatch_audit_count: int = 0
    scores: Dict[str, float] = Field(
        default_factory=dict,
        description="Peer scores for this epoch (peer_id -> score)",
    )
    tamper_detected: bool = Field(
        default=False, description="Whether any tamper was detected this epoch"
    )


class AuditLogEntry(BaseModel):
    """An overwatch audit log entry with tamper evidence."""

    epoch: int
    peer_id: str
    result: str = Field(description="pass, fail, or tampered")
    details: str = Field(default="", description="Human-readable audit detail")
    evidence: Dict[str, Any] = Field(
        default_factory=dict, description="Evidence data (parity, flags, etc.)"
    )
    hardware_id: Optional[str] = Field(default=None, description="Hardware ID if known")


class SearchResult(BaseModel):
    """A single search result entry."""

    match_type: str = Field(description="What matched: peer_id, epoch, event_type, hardware_id")
    event: SecurityEvent


class PaginatedResponse(BaseModel):
    """Generic paginated response wrapper."""

    items: List[Any]
    total: int
    offset: int
    limit: int
