"""Event indexer that reads from RocksDB nmaps and provides filtered queries."""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Sequence

from subnet.dashboard.explorer.models import (
    AuditLogEntry,
    EpochSummary,
    EventType,
    SecurityEvent,
    Severity,
)

logger = logging.getLogger(__name__)

# Map nmap topic names to EventType
_TOPIC_MAP: Dict[str, EventType] = {
    "heartbeat": EventType.HEARTBEAT,
    "tee_quote": EventType.TEE_QUOTE,
    "mock_work": EventType.WORK_RECORD,
}

# Topics to scan
_NMAP_TOPICS = ("heartbeat", "tee_quote", "mock_work")


def _extract_dict(data: object) -> dict:
    """Convert various data formats to a plain dict."""
    if isinstance(data, dict):
        return dict(data)
    if hasattr(data, "model_dump"):
        return data.model_dump()
    if hasattr(data, "__dict__"):
        return dict(data.__dict__)
    return {"raw": str(data)}


def _determine_severity(topic: str, data: dict) -> Severity:
    """Determine severity based on event type and data content."""
    if topic == "mock_work":
        if data.get("tampered", False):
            return Severity.CRITICAL
        if not data.get("parity_ok", True):
            return Severity.WARNING
    if topic == "tee_quote":
        tee_score = data.get("tee_score", 1.0)
        if isinstance(tee_score, (int, float)) and tee_score < 1.0:
            return Severity.WARNING
    return Severity.INFO


def _make_summary(topic: str, data: dict, peer_id: str) -> str:
    """Generate a human-readable summary for an event."""
    if topic == "heartbeat":
        status = data.get("status", "ok")
        return f"Heartbeat from {peer_id[:16]}... (status={status})"
    if topic == "tee_quote":
        tee_type = data.get("tee_type", "unknown")
        return f"TEE quote ({tee_type}) from {peer_id[:16]}..."
    if topic == "mock_work":
        if data.get("tampered", False):
            return f"TAMPERED work record from {peer_id[:16]}..."
        if not data.get("parity_ok", True):
            return f"Parity mismatch in work from {peer_id[:16]}..."
        return f"Work record from {peer_id[:16]}..."
    return f"Event from {peer_id[:16]}..."


class EventIndexer:
    """Reads from RocksDB nmaps and provides filtered queries over security events."""

    def __init__(self, db: Any) -> None:
        self.db = db

    def _scan_all_events(self) -> List[SecurityEvent]:
        """Scan all nmaps and return SecurityEvent objects."""
        events: List[SecurityEvent] = []
        for topic in _NMAP_TOPICS:
            entries = self.db.nmap_get_all(topic)
            event_type = _TOPIC_MAP[topic]
            for key, raw_data in entries.items():
                parts = key.split(":", 1)
                epoch_str = parts[0] if len(parts) > 0 else "0"
                peer_id = parts[1] if len(parts) > 1 else "unknown"
                epoch = int(epoch_str) if epoch_str.isdigit() else 0
                data = _extract_dict(raw_data)
                severity = _determine_severity(topic, data)
                hardware_id = data.get("hardware_id") or data.get("chip_id") or None
                events.append(
                    SecurityEvent(
                        event_id=f"{topic}:{key}",
                        epoch=epoch,
                        peer_id=peer_id,
                        event_type=event_type,
                        severity=severity,
                        summary=_make_summary(topic, data, peer_id),
                        data=data,
                        hardware_id=hardware_id,
                    )
                )
        return events

    def query_events(
        self,
        *,
        epoch_min: Optional[int] = None,
        epoch_max: Optional[int] = None,
        peer_id: Optional[str] = None,
        event_type: Optional[EventType] = None,
        severity: Optional[Severity] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[List[SecurityEvent], int]:
        """Query events with optional filters. Returns (items, total_matching)."""
        events = self._scan_all_events()

        # Apply filters
        if epoch_min is not None:
            events = [e for e in events if e.epoch >= epoch_min]
        if epoch_max is not None:
            events = [e for e in events if e.epoch <= epoch_max]
        if peer_id is not None:
            events = [e for e in events if e.peer_id == peer_id]
        if event_type is not None:
            events = [e for e in events if e.event_type == event_type]
        if severity is not None:
            events = [e for e in events if e.severity == severity]

        # Sort by epoch descending, then by event_type for stable ordering
        events.sort(key=lambda e: (-e.epoch, e.event_type.value))

        total = len(events)
        return events[offset : offset + limit], total

    def epoch_summaries(
        self,
        *,
        epoch_min: Optional[int] = None,
        epoch_max: Optional[int] = None,
    ) -> List[EpochSummary]:
        """Get per-epoch summaries. Returns list sorted by epoch descending."""
        events = self._scan_all_events()

        # Group by epoch
        by_epoch: Dict[int, List[SecurityEvent]] = {}
        for ev in events:
            by_epoch.setdefault(ev.epoch, []).append(ev)

        summaries: List[EpochSummary] = []
        for epoch, epoch_events in sorted(by_epoch.items(), reverse=True):
            if epoch_min is not None and epoch < epoch_min:
                continue
            if epoch_max is not None and epoch > epoch_max:
                continue

            peers = set(e.peer_id for e in epoch_events)
            heartbeats = sum(1 for e in epoch_events if e.event_type == EventType.HEARTBEAT)
            tee_quotes = sum(1 for e in epoch_events if e.event_type == EventType.TEE_QUOTE)
            work_records = sum(1 for e in epoch_events if e.event_type == EventType.WORK_RECORD)

            # Extract scores from heartbeat data
            scores: Dict[str, float] = {}
            for e in epoch_events:
                if e.event_type == EventType.HEARTBEAT:
                    tee_score = e.data.get("tee_score")
                    if isinstance(tee_score, (int, float)):
                        scores[e.peer_id] = float(tee_score)

            tamper = any(e.severity == Severity.CRITICAL for e in epoch_events)

            summaries.append(
                EpochSummary(
                    epoch=epoch,
                    node_count=len(peers),
                    event_count=len(epoch_events),
                    heartbeat_count=heartbeats,
                    tee_quote_count=tee_quotes,
                    work_record_count=work_records,
                    scores=scores,
                    tamper_detected=tamper,
                )
            )

        return summaries

    def epoch_detail(self, epoch: int) -> Optional[EpochSummary]:
        """Get summary for a single epoch, or None if no events exist for it."""
        summaries = self.epoch_summaries(epoch_min=epoch, epoch_max=epoch)
        return summaries[0] if summaries else None

    def node_history(
        self,
        peer_id: str,
        *,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[List[SecurityEvent], int]:
        """Get all events for a specific peer_id."""
        return self.query_events(peer_id=peer_id, limit=limit, offset=offset)

    def audit_log(
        self,
        *,
        epoch_min: Optional[int] = None,
        epoch_max: Optional[int] = None,
        peer_id: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> tuple[List[AuditLogEntry], int]:
        """Get overwatch audit log entries with tamper evidence."""
        entries = self.db.nmap_get_all("mock_work")
        audit_entries: List[AuditLogEntry] = []

        for key, raw_data in entries.items():
            parts = key.split(":", 1)
            epoch_str = parts[0] if len(parts) > 0 else "0"
            pid = parts[1] if len(parts) > 1 else "unknown"
            epoch = int(epoch_str) if epoch_str.isdigit() else 0

            # Apply filters
            if epoch_min is not None and epoch < epoch_min:
                continue
            if epoch_max is not None and epoch > epoch_max:
                continue
            if peer_id is not None and pid != peer_id:
                continue

            data = _extract_dict(raw_data)
            tampered = data.get("tampered", False)
            parity_ok = data.get("parity_ok", True)

            if tampered:
                result = "tampered"
                details = "Work record flagged as tampered"
            elif not parity_ok:
                result = "fail"
                details = "Parity mismatch detected"
            else:
                result = "pass"
                details = "Audit passed"

            hardware_id = data.get("hardware_id") or data.get("chip_id") or None

            audit_entries.append(
                AuditLogEntry(
                    epoch=epoch,
                    peer_id=pid,
                    result=result,
                    details=details,
                    evidence={
                        k: v
                        for k, v in data.items()
                        if k in ("tampered", "parity_ok", "parity_hash", "expected_hash")
                    },
                    hardware_id=hardware_id,
                )
            )

        audit_entries.sort(key=lambda e: -e.epoch)
        total = len(audit_entries)
        return audit_entries[offset : offset + limit], total

    def search(
        self,
        *,
        query: str,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[List[dict], int]:
        """Search across events by peer_id, epoch, event_type, or hardware_id.

        Returns list of dicts with 'match_type' and 'event' keys.
        """
        events = self._scan_all_events()
        results: List[dict] = []
        query_lower = query.lower().strip()

        for ev in events:
            match_type = None
            # Match by peer_id (substring)
            if query_lower in ev.peer_id.lower():
                match_type = "peer_id"
            # Match by epoch (exact)
            elif query_lower.isdigit() and ev.epoch == int(query_lower):
                match_type = "epoch"
            # Match by event_type
            elif query_lower in ev.event_type.value.lower():
                match_type = "event_type"
            # Match by hardware_id (substring)
            elif ev.hardware_id and query_lower in ev.hardware_id.lower():
                match_type = "hardware_id"

            if match_type:
                results.append({"match_type": match_type, "event": ev})

        # Sort: exact matches first (epoch), then by recency
        results.sort(key=lambda r: (-r["event"].epoch, r["match_type"]))
        total = len(results)
        return results[offset : offset + limit], total
