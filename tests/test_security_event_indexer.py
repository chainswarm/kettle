"""
Tests for SecurityEvent model, SecurityEventIndexer, and DcapVerifier integration.

Covers:
- SecurityEvent creation and serialisation
- SecurityEventIndexer CRUD (record, query by time/peer/type, counts)
- DcapVerifier rejection indexing (all rejection paths)
- Overwatch slash indexing
- Scoring failure indexing
- Event type mapping from DcapVerifier rejection reasons
"""

import time
import tempfile

import pytest

from subnet.security.events import (
    SecurityEvent,
    SecurityEventIndexer,
    SecurityEventType,
    SecuritySeverity,
    SECURITY_EVENTS_NMAP,
    SECURITY_BY_PEER_NMAP,
    SECURITY_BY_TYPE_NMAP,
)
from subnet.tee.backends.mock import MockBackend
from subnet.tee.config import TeeConfig
from subnet.tee.publisher import TeePublisher
from subnet.tee.quote import TeeBackend, TeeQuote, TcbStatus
from subnet.tee.verifier import DcapVerifier, VerificationResult
from subnet.utils.db.database import RocksDB


PEER_ID = "12D3KooWKxAhu5U8SreDZpokVkN6ciTBbsHxteo3Vmq6Cpuf8KEt"
ANOTHER_PEER = "12D3KooWM5J4zS17XR2LHGZgRpmzbeqg4Eibyq8sbRLwRuWxJqsV"
EPOCH = 14_780_500


@pytest.fixture
def db(tmp_path):
    db_path = str(tmp_path / "test_security")
    database = RocksDB(base_path=db_path)
    yield database
    database.store.close()


@pytest.fixture
def indexer(db):
    return SecurityEventIndexer(db=db)


@pytest.fixture
def mock_config():
    cfg = TeeConfig.__new__(TeeConfig)
    cfg.backend = TeeBackend.MOCK
    cfg.mock_key = b"mock-tee-dev-key-do-not-use-in-production-!!"
    cfg.expected_measurements = []
    cfg.expected_measurement = ""
    cfg.min_tee_score = 0.0
    cfg.tcb_strict = True
    cfg.pccs_url = ""
    cfg.allow_shared_hardware = True
    return cfg


@pytest.fixture
def backend(mock_config):
    return MockBackend(key=mock_config.mock_key)


@pytest.fixture
def publisher(db, backend):
    return TeePublisher(db=db, peer_id=PEER_ID, backend=backend)


@pytest.fixture
def verifier_with_indexer(db, mock_config, indexer):
    return DcapVerifier(db=db, config=mock_config, security_indexer=indexer)


# ══════════════════════════════════════════════════════════════════════
# SecurityEvent model
# ══════════════════════════════════════════════════════════════════════


class TestSecurityEventModel:
    def test_create_event(self):
        event = SecurityEvent(
            event_type="tee_nonce_mismatch",
            peer_id=PEER_ID,
            epoch=EPOCH,
            reason="nonce_mismatch:got=5,expected=6",
            severity="medium",
        )
        assert event.event_type == "tee_nonce_mismatch"
        assert event.peer_id == PEER_ID
        assert event.epoch == EPOCH
        assert event.severity == "medium"
        assert isinstance(event.timestamp, float)
        assert event.details == {}

    def test_to_dict_roundtrip(self):
        event = SecurityEvent(
            event_type="tee_debug_mode",
            peer_id=PEER_ID,
            epoch=EPOCH,
            reason="debug_mode",
            severity="medium",
            timestamp=1000.0,
            details={"backend": "mock"},
        )
        d = event.to_dict()
        assert d["event_type"] == "tee_debug_mode"
        assert d["timestamp"] == 1000.0
        assert d["details"]["backend"] == "mock"

        restored = SecurityEvent.from_dict(d)
        assert restored.event_type == event.event_type
        assert restored.peer_id == event.peer_id
        assert restored.epoch == event.epoch
        assert restored.timestamp == event.timestamp

    def test_details_optional(self):
        event = SecurityEvent(
            event_type="test",
            peer_id="",
            epoch=0,
            reason="test",
            severity="low",
        )
        assert event.details == {}


# ══════════════════════════════════════════════════════════════════════
# SecurityEventIndexer — recording and querying
# ══════════════════════════════════════════════════════════════════════


class TestSecurityEventIndexer:
    def test_record_stores_in_all_three_nmaps(self, db, indexer):
        event = SecurityEvent(
            event_type="tee_debug_mode",
            peer_id=PEER_ID,
            epoch=EPOCH,
            reason="debug_mode",
            severity="medium",
            timestamp=1000.123456,
        )
        indexer.record(event)

        # Primary index (by time)
        all_events = db.nmap_get_all(SECURITY_EVENTS_NMAP)
        assert len(all_events) == 1

        # Secondary index (by peer)
        all_peer = db.nmap_get_all(SECURITY_BY_PEER_NMAP)
        assert len(all_peer) == 1

        # Tertiary index (by type)
        all_type = db.nmap_get_all(SECURITY_BY_TYPE_NMAP)
        assert len(all_type) == 1

    def test_record_tee_rejection(self, indexer):
        event = indexer.record_tee_rejection(
            PEER_ID, EPOCH, "nonce_mismatch:got=5,expected=6"
        )
        assert event.event_type == SecurityEventType.TEE_NONCE_MISMATCH.value
        assert event.severity == SecuritySeverity.MEDIUM.value
        assert event.peer_id == PEER_ID

    def test_record_overwatch_slash(self, indexer):
        event = indexer.record_overwatch_slash(
            PEER_ID, EPOCH, evidence={"audit_id": "abc123"}
        )
        assert event.event_type == SecurityEventType.OVERWATCH_SLASH.value
        assert event.severity == SecuritySeverity.CRITICAL.value
        assert event.details["audit_id"] == "abc123"

    def test_record_scoring_failure(self, indexer):
        event = indexer.record_scoring_failure(
            PEER_ID, EPOCH, "Connection refused"
        )
        assert event.event_type == SecurityEventType.SCORING_ERROR.value

    def test_record_scoring_unreachable(self, indexer):
        event = indexer.record_scoring_failure(
            PEER_ID, EPOCH, "Node unreachable: timeout"
        )
        assert event.event_type == SecurityEventType.SCORING_UNREACHABLE.value

    def test_get_recent_events_ordered(self, indexer):
        # Record three events with different timestamps
        for i, ts in enumerate([100.0, 300.0, 200.0]):
            event = SecurityEvent(
                event_type="tee_debug_mode",
                peer_id=PEER_ID,
                epoch=EPOCH + i,
                reason="test",
                severity="medium",
                timestamp=ts,
            )
            indexer.record(event)

        recent = indexer.get_recent_events(limit=10)
        assert len(recent) == 3
        # Should be ordered by timestamp descending
        timestamps = [e["timestamp"] for e in recent]
        assert timestamps == sorted(timestamps, reverse=True)

    def test_get_recent_events_respects_limit(self, indexer):
        for i in range(5):
            indexer.record_tee_rejection(PEER_ID, EPOCH + i, "debug_mode")

        recent = indexer.get_recent_events(limit=2)
        assert len(recent) == 2

    def test_get_events_by_peer(self, indexer):
        indexer.record_tee_rejection(PEER_ID, EPOCH, "debug_mode")
        indexer.record_tee_rejection(ANOTHER_PEER, EPOCH, "nonce_mismatch:got=1,expected=2")
        indexer.record_tee_rejection(PEER_ID, EPOCH + 1, "identity_binding_failed")

        peer_events = indexer.get_events_by_peer(PEER_ID)
        assert len(peer_events) == 2
        for ev in peer_events:
            assert ev["peer_id"] == PEER_ID

    def test_get_events_by_type(self, indexer):
        indexer.record_tee_rejection(PEER_ID, EPOCH, "debug_mode")
        indexer.record_tee_rejection(PEER_ID, EPOCH + 1, "nonce_mismatch:got=1,expected=2")
        indexer.record_tee_rejection(ANOTHER_PEER, EPOCH, "debug_mode")

        debug_events = indexer.get_events_by_type("tee_debug_mode")
        assert len(debug_events) == 2
        for ev in debug_events:
            assert ev["event_type"] == "tee_debug_mode"

    def test_get_event_counts(self, indexer):
        indexer.record_tee_rejection(PEER_ID, EPOCH, "debug_mode")
        indexer.record_tee_rejection(PEER_ID, EPOCH + 1, "debug_mode")
        indexer.record_tee_rejection(PEER_ID, EPOCH + 2, "nonce_mismatch:got=1,expected=2")
        indexer.record_overwatch_slash(PEER_ID, EPOCH)

        counts = indexer.get_event_counts()
        assert counts["tee_debug_mode"] == 2
        assert counts["tee_nonce_mismatch"] == 1
        assert counts["overwatch_slash"] == 1

    def test_get_event_counts_by_severity(self, indexer):
        indexer.record_tee_rejection(PEER_ID, EPOCH, "debug_mode")  # medium
        indexer.record_overwatch_slash(PEER_ID, EPOCH)  # critical

        counts = indexer.get_event_counts_by_severity()
        assert counts["medium"] == 1
        assert counts["critical"] == 1

    def test_empty_db_returns_empty_lists(self, indexer):
        assert indexer.get_recent_events() == []
        assert indexer.get_events_by_peer(PEER_ID) == []
        assert indexer.get_events_by_type("nonexistent") == []
        assert indexer.get_event_counts() == {}


# ══════════════════════════════════════════════════════════════════════
# Event type mapping
# ══════════════════════════════════════════════════════════════════════


class TestEventTypeMapping:
    def test_quote_not_found(self):
        result = SecurityEventIndexer._map_tee_reason("quote_not_found")
        assert result == SecurityEventType.TEE_QUOTE_NOT_FOUND

    def test_debug_mode(self):
        result = SecurityEventIndexer._map_tee_reason("debug_mode")
        assert result == SecurityEventType.TEE_DEBUG_MODE

    def test_nonce_mismatch(self):
        result = SecurityEventIndexer._map_tee_reason("nonce_mismatch:got=5,expected=6")
        assert result == SecurityEventType.TEE_NONCE_MISMATCH

    def test_identity_binding_failed(self):
        result = SecurityEventIndexer._map_tee_reason("identity_binding_failed")
        assert result == SecurityEventType.TEE_IDENTITY_BINDING_FAILED

    def test_chain_verification_failed(self):
        result = SecurityEventIndexer._map_tee_reason("chain_verification_failed:hmac_invalid")
        assert result == SecurityEventType.TEE_CHAIN_VERIFICATION_FAILED

    def test_measurement_mismatch(self):
        result = SecurityEventIndexer._map_tee_reason("measurement_mismatch:got=abc,expected=def")
        assert result == SecurityEventType.TEE_MEASUREMENT_MISMATCH

    def test_vulnerable_firmware(self):
        result = SecurityEventIndexer._map_tee_reason("vulnerable_firmware:CVE-2023-20592")
        assert result == SecurityEventType.TEE_VULNERABLE_FIRMWARE

    def test_duplicate_hardware(self):
        result = SecurityEventIndexer._map_tee_reason("duplicate_hardware:hw=abc,first_peer=def")
        assert result == SecurityEventType.TEE_DUPLICATE_HARDWARE

    def test_duplicate_gpu(self):
        result = SecurityEventIndexer._map_tee_reason("duplicate_gpu:uuid=abc,first_peer=def")
        assert result == SecurityEventType.TEE_DUPLICATE_GPU

    def test_unknown_falls_back(self):
        result = SecurityEventIndexer._map_tee_reason("some_new_reason")
        assert result == SecurityEventType.TEE_CHAIN_VERIFICATION_FAILED


# ══════════════════════════════════════════════════════════════════════
# DcapVerifier integration — rejections get indexed
# ══════════════════════════════════════════════════════════════════════


class TestVerifierIndexesRejections:
    """Verify that DcapVerifier rejection paths write to the security index."""

    def test_missing_quote_indexed(self, db, verifier_with_indexer, indexer):
        result = verifier_with_indexer.verify(PEER_ID, EPOCH)
        assert not result.ok
        assert result.rejection_reason == "quote_not_found"

        events = indexer.get_recent_events()
        assert len(events) == 1
        assert events[0]["event_type"] == "tee_quote_not_found"
        assert events[0]["peer_id"] == PEER_ID

    def test_debug_mode_indexed(self, db, verifier_with_indexer, indexer, publisher):
        # Publish a debug quote
        quote = publisher.publish(EPOCH)
        # Tamper: set debug_mode
        quote.debug_mode = True
        from subnet.tee.quote import TEE_QUOTE_TOPIC, dht_key
        db.nmap_set(TEE_QUOTE_TOPIC, dht_key(EPOCH, PEER_ID), quote.to_bytes())

        result = verifier_with_indexer.verify(PEER_ID, EPOCH)
        assert not result.ok

        events = indexer.get_recent_events()
        assert len(events) == 1
        assert events[0]["event_type"] == "tee_debug_mode"

    def test_nonce_mismatch_indexed(self, db, verifier_with_indexer, indexer, publisher):
        # Publish for wrong epoch
        publisher.publish(EPOCH + 1)
        from subnet.tee.quote import TEE_QUOTE_TOPIC, dht_key
        # Move the quote to look like it's for EPOCH
        raw = db.nmap_get(TEE_QUOTE_TOPIC, dht_key(EPOCH + 1, PEER_ID))
        db.nmap_set(TEE_QUOTE_TOPIC, dht_key(EPOCH, PEER_ID), raw)

        result = verifier_with_indexer.verify(PEER_ID, EPOCH)
        assert not result.ok

        events = indexer.get_recent_events()
        assert len(events) == 1
        assert events[0]["event_type"] == "tee_nonce_mismatch"

    def test_identity_binding_indexed(self, db, verifier_with_indexer, indexer, publisher):
        # Publish quote for PEER_ID, try to verify as ANOTHER_PEER
        publisher.publish(EPOCH)
        from subnet.tee.quote import TEE_QUOTE_TOPIC, dht_key
        # Copy the quote to ANOTHER_PEER's key
        raw = db.nmap_get(TEE_QUOTE_TOPIC, dht_key(EPOCH, PEER_ID))
        db.nmap_set(TEE_QUOTE_TOPIC, dht_key(EPOCH, ANOTHER_PEER), raw)

        result = verifier_with_indexer.verify(ANOTHER_PEER, EPOCH)
        assert not result.ok

        events = indexer.get_events_by_peer(ANOTHER_PEER)
        assert len(events) == 1
        assert events[0]["event_type"] == "tee_identity_binding_failed"

    def test_pass_does_not_index(self, db, verifier_with_indexer, indexer, publisher):
        """Passing verification must NOT create security events."""
        publisher.publish(EPOCH)
        result = verifier_with_indexer.verify(PEER_ID, EPOCH)
        assert result.ok
        assert result.score == 0.5  # mock

        events = indexer.get_recent_events()
        assert len(events) == 0

    def test_verifier_without_indexer_still_works(self, db, mock_config):
        """DcapVerifier without indexer should work exactly as before."""
        verifier = DcapVerifier(db=db, config=mock_config)
        result = verifier.verify(PEER_ID, EPOCH)
        assert not result.ok  # no quote
        assert result.rejection_reason == "quote_not_found"

    def test_verify_quote_rejection_indexed(self, db, verifier_with_indexer, indexer, publisher):
        """verify_quote() should also index rejections."""
        # Publish a valid quote, then modify it to be debug mode
        quote = publisher.publish(EPOCH)
        quote.debug_mode = True

        result = verifier_with_indexer.verify_quote(quote, PEER_ID, EPOCH)
        assert not result.ok  # debug_mode

        events = indexer.get_recent_events()
        assert len(events) == 1
        assert events[0]["event_type"] == "tee_debug_mode"


# ══════════════════════════════════════════════════════════════════════
# Severity assignments
# ══════════════════════════════════════════════════════════════════════


class TestSeverityAssignment:
    def test_quote_not_found_is_low(self, indexer):
        event = indexer.record_tee_rejection(PEER_ID, EPOCH, "quote_not_found")
        assert event.severity == "low"

    def test_debug_mode_is_medium(self, indexer):
        event = indexer.record_tee_rejection(PEER_ID, EPOCH, "debug_mode")
        assert event.severity == "medium"

    def test_identity_binding_is_high(self, indexer):
        event = indexer.record_tee_rejection(PEER_ID, EPOCH, "identity_binding_failed")
        assert event.severity == "high"

    def test_vulnerable_firmware_is_critical(self, indexer):
        event = indexer.record_tee_rejection(PEER_ID, EPOCH, "vulnerable_firmware:CVE-2023-20592")
        assert event.severity == "critical"

    def test_overwatch_slash_is_critical(self, indexer):
        event = indexer.record_overwatch_slash(PEER_ID, EPOCH)
        assert event.severity == "critical"

    def test_duplicate_hardware_is_high(self, indexer):
        event = indexer.record_tee_rejection(PEER_ID, EPOCH, "duplicate_hardware:hw=abc,first_peer=def")
        assert event.severity == "high"
