"""
Tests for DcapVerifier — full verification pipeline.

Covers every rejection path:
- Quote not found in DHT → REJECT (score=0.0)
- Debug mode quote → REJECT
- Nonce mismatch (replay) → REJECT
- Identity binding failure (stolen quote) → REJECT
- Invalid HMAC sig → REJECT
- Measurement mismatch → REJECT
- All checks pass, mock backend → PASS (score=0.5)
- All checks pass, TCB UpToDate, real backend → PASS (score=1.0)
- TCB degraded, strict policy → REJECT
- TCB degraded, permissive policy → PASS (score=0.5)
"""

import tempfile

import pytest

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
    db_path = str(tmp_path / "test_verifier")
    database = RocksDB(base_path=db_path)
    yield database
    database.store.close()


@pytest.fixture
def mock_config():
    """TeeConfig in mock mode, no measurement enforcement."""
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
def verifier(db, mock_config):
    return DcapVerifier(db=db, config=mock_config)


def publish_quote(publisher, peer_id=PEER_ID, epoch=EPOCH, **overrides) -> TeeQuote:
    """Helper: publish a quote and return it."""
    return publisher.publish(epoch)


# ------------------------------------------------------------------
# Rejection paths
# ------------------------------------------------------------------

class TestRejectMissingQuote:
    def test_missing_quote_returns_zero(self, verifier):
        result = verifier.verify(PEER_ID, EPOCH)
        assert result.score == 0.0
        assert result.ok is False
        assert result.rejection_reason == "quote_not_found"

    def test_missing_quote_quote_is_none(self, verifier):
        result = verifier.verify(PEER_ID, EPOCH)
        assert result.quote is None


class TestRejectDebugMode:
    def test_debug_mode_quote_rejected(self, db, mock_config):
        debug_backend = MockBackend(key=mock_config.mock_key, debug_mode=True)
        pub = TeePublisher(db=db, peer_id=PEER_ID, backend=debug_backend)
        pub.publish(EPOCH)

        verifier = DcapVerifier(db=db, config=mock_config)
        result = verifier.verify(PEER_ID, EPOCH)

        assert result.score == 0.0
        assert result.ok is False
        assert result.rejection_reason == "debug_mode"


class TestRejectReplay:
    def test_old_epoch_quote_rejected(self, db, backend, mock_config):
        """Quote from epoch N-1 is rejected at epoch N."""
        old_pub = TeePublisher(db=db, peer_id=PEER_ID, backend=backend)
        old_pub.publish(EPOCH - 1)

        verifier = DcapVerifier(db=db, config=mock_config)
        result = verifier.verify(PEER_ID, EPOCH)

        # Quote from EPOCH-1 is not stored under EPOCH key → missing
        assert result.score == 0.0
        assert result.rejection_reason == "quote_not_found"

    def test_tampered_nonce_rejected(self, db, backend, mock_config, publisher):
        """Quote published at EPOCH but nonce changed to EPOCH-1 → nonce_mismatch."""
        from subnet.tee.quote import TEE_QUOTE_TOPIC, dht_key
        import json

        q = publisher.publish(EPOCH)

        # Tamper: change nonce in the stored bytes
        raw = db.nmap_get(TEE_QUOTE_TOPIC, dht_key(EPOCH, PEER_ID))
        d = json.loads(raw.decode())
        d["nonce"] = EPOCH - 1
        db.nmap_set(TEE_QUOTE_TOPIC, dht_key(EPOCH, PEER_ID), json.dumps(d).encode())

        verifier = DcapVerifier(db=db, config=mock_config)
        result = verifier.verify(PEER_ID, EPOCH)

        assert result.score == 0.0
        assert "nonce_mismatch" in result.rejection_reason


class TestRejectStolenIdentity:
    def test_another_peers_quote_fails_identity(self, db, mock_config):
        """Peer B cannot use Peer A's quote."""
        backend = MockBackend(key=mock_config.mock_key)
        pub_a = TeePublisher(db=db, peer_id=PEER_ID, backend=backend)
        pub_a.publish(EPOCH)

        verifier = DcapVerifier(db=db, config=mock_config)
        # Peer B tries to claim Peer A's quote by querying under Peer A's key
        # (real attack: Peer B stores Peer A's quote under its own key)
        # Simulated: directly write Peer A's quote bytes under Peer B's key
        from subnet.tee.quote import TEE_QUOTE_TOPIC, dht_key
        raw_a = db.nmap_get(TEE_QUOTE_TOPIC, dht_key(EPOCH, PEER_ID))
        db.nmap_set(TEE_QUOTE_TOPIC, dht_key(EPOCH, ANOTHER_PEER), raw_a)

        # Verifier checks Peer B's quote — report_data binds to Peer A's peer_id
        result = verifier.verify(ANOTHER_PEER, EPOCH)
        assert result.score == 0.0
        assert result.rejection_reason == "identity_binding_failed"


class TestRejectInvalidSig:
    def test_tampered_sig_rejected(self, db, mock_config, publisher):
        """Tampered HMAC sig causes chain_verification_failed."""
        from subnet.tee.quote import TEE_QUOTE_TOPIC, dht_key
        import json

        publisher.publish(EPOCH)

        raw = db.nmap_get(TEE_QUOTE_TOPIC, dht_key(EPOCH, PEER_ID))
        d = json.loads(raw.decode())
        d["sig"] = "00" * 32  # garbage sig
        db.nmap_set(TEE_QUOTE_TOPIC, dht_key(EPOCH, PEER_ID), json.dumps(d).encode())

        verifier = DcapVerifier(db=db, config=mock_config)
        result = verifier.verify(PEER_ID, EPOCH)

        assert result.score == 0.0
        assert "chain_verification_failed" in result.rejection_reason
        assert "hmac_invalid" in result.rejection_reason


class TestRejectMeasurementMismatch:
    def test_wrong_measurement_rejected(self, db, backend, publisher):
        """Measurement doesn't match EXPECTED_MEASUREMENT → reject."""
        publisher.publish(EPOCH)

        wrong = "deadbeef" * 16
        cfg = TeeConfig.__new__(TeeConfig)
        cfg.backend = TeeBackend.MOCK
        cfg.mock_key = b"mock-tee-dev-key-do-not-use-in-production-!!"
        cfg.expected_measurements = [wrong]
        cfg.expected_measurement = wrong
        cfg.min_tee_score = 0.0
        cfg.tcb_strict = True
        cfg.pccs_url = ""
        cfg.allow_shared_hardware = True

        verifier = DcapVerifier(db=db, config=cfg)
        result = verifier.verify(PEER_ID, EPOCH)

        assert result.score == 0.0
        assert "measurement_mismatch" in result.rejection_reason


# ------------------------------------------------------------------
# Pass paths
# ------------------------------------------------------------------

class TestPassMockBackend:
    def test_mock_quote_scores_half(self, verifier, publisher):
        """All checks pass for mock backend → score=0.5."""
        publisher.publish(EPOCH)
        result = verifier.verify(PEER_ID, EPOCH)
        assert result.ok is True
        assert result.score == 0.5
        assert result.rejection_reason is None

    def test_mock_backend_field(self, verifier, publisher):
        publisher.publish(EPOCH)
        result = verifier.verify(PEER_ID, EPOCH)
        assert result.backend == TeeBackend.MOCK

    def test_mock_with_matching_measurement_passes(self, db, backend):
        """Measurement enforcement passes when expected==actual."""
        from subnet.tee.backends.mock import MOCK_MEASUREMENT
        pub = TeePublisher(db=db, peer_id=PEER_ID, backend=backend)
        pub.publish(EPOCH)

        cfg = TeeConfig.__new__(TeeConfig)
        cfg.backend = TeeBackend.MOCK
        cfg.mock_key = b"mock-tee-dev-key-do-not-use-in-production-!!"
        cfg.expected_measurements = [MOCK_MEASUREMENT]
        cfg.expected_measurement = MOCK_MEASUREMENT  # correct measurement
        cfg.min_tee_score = 0.0
        cfg.tcb_strict = True
        cfg.pccs_url = ""
        cfg.allow_shared_hardware = True

        verifier = DcapVerifier(db=db, config=cfg)
        result = verifier.verify(PEER_ID, EPOCH)
        assert result.ok is True
        assert result.score == 0.5


class TestTcbPolicy:
    def _store_quote_with_tcb(self, db, tcb_status: TcbStatus):
        """Store a synthetic real-hardware quote with a specific TCB status."""
        from subnet.tee.quote import TEE_QUOTE_TOPIC, dht_key
        import json

        # Build a quote that passes debug/nonce/identity checks but has custom TCB
        report_data_hex = TeeQuote.make_report_data_hex(PEER_ID, EPOCH)
        q = TeeQuote(
            backend=TeeBackend.TDX,  # "real" hardware
            measurement="aa" * 32,
            report_data=report_data_hex,
            nonce=EPOCH,
            peer_id=PEER_ID,
            debug_mode=False,
            tcb_status=tcb_status,
            sig="",
            raw_bytes=b"\x04\x00\x02\x00" + b"\x00" * 1000,  # fake TDX quote with magic
        )
        # Store JSON (raw_bytes excluded) + also needs chain verification to pass
        # We'll store as bytes including a fake raw_bytes marker
        raw = q.to_bytes()
        db.nmap_set(TEE_QUOTE_TOPIC, dht_key(EPOCH, PEER_ID), raw)
        return q

    def _make_tdx_config(self, strict: bool) -> TeeConfig:
        cfg = TeeConfig.__new__(TeeConfig)
        cfg.backend = TeeBackend.TDX
        cfg.mock_key = b"mock-tee-dev-key-do-not-use-in-production-!!"
        cfg.expected_measurements = []
        cfg.expected_measurement = ""
        cfg.min_tee_score = 0.0
        cfg.tcb_strict = strict
        cfg.pccs_url = ""
        cfg.allow_shared_hardware = True
        return cfg

    def test_up_to_date_scores_one(self, db):
        """TDX + UpToDate TCB should score 1.0... but chain stub needs raw_bytes."""
        # This tests the TCB scoring logic in isolation by calling _score_from_tcb directly
        cfg = self._make_tdx_config(strict=True)
        verifier = DcapVerifier(db=db, config=cfg)

        q = TeeQuote(
            backend=TeeBackend.TDX,
            measurement="aa",
            report_data="bb",
            nonce=EPOCH,
            peer_id=PEER_ID,
            tcb_status=TcbStatus.UP_TO_DATE,
            sig="",
        )
        assert verifier._score_from_tcb(q) == 1.0

    def test_revoked_scores_zero(self, db):
        cfg = self._make_tdx_config(strict=True)
        verifier = DcapVerifier(db=db, config=cfg)
        q = TeeQuote(
            backend=TeeBackend.TDX,
            measurement="aa",
            report_data="bb",
            nonce=EPOCH,
            peer_id=PEER_ID,
            tcb_status=TcbStatus.REVOKED,
            sig="",
        )
        assert verifier._score_from_tcb(q) == 0.0

    def test_sw_hardening_strict_scores_zero(self, db):
        cfg = self._make_tdx_config(strict=True)
        verifier = DcapVerifier(db=db, config=cfg)
        q = TeeQuote(
            backend=TeeBackend.TDX,
            measurement="aa",
            report_data="bb",
            nonce=EPOCH,
            peer_id=PEER_ID,
            tcb_status=TcbStatus.SW_HARDENING_NEEDED,
            sig="",
        )
        assert verifier._score_from_tcb(q) == 0.0

    def test_sw_hardening_permissive_scores_half(self, db):
        cfg = self._make_tdx_config(strict=False)  # permissive
        verifier = DcapVerifier(db=db, config=cfg)
        q = TeeQuote(
            backend=TeeBackend.TDX,
            measurement="aa",
            report_data="bb",
            nonce=EPOCH,
            peer_id=PEER_ID,
            tcb_status=TcbStatus.SW_HARDENING_NEEDED,
            sig="",
        )
        assert verifier._score_from_tcb(q) == 0.5

    def test_mock_always_half_regardless_of_tcb(self, db):
        cfg = self._make_tdx_config(strict=True)
        verifier = DcapVerifier(db=db, config=cfg)
        for status in TcbStatus:
            q = TeeQuote(
                backend=TeeBackend.MOCK,
                measurement="aa",
                report_data="bb",
                nonce=EPOCH,
                peer_id=PEER_ID,
                tcb_status=status,
                sig="",
            )
            assert verifier._score_from_tcb(q) == 0.5, f"Expected 0.5 for TCB={status}"


class TestVerificationResult:
    def test_fail_factory(self):
        r = VerificationResult.fail("test_reason")
        assert r.score == 0.0
        assert r.ok is False
        assert r.rejection_reason == "test_reason"
        assert r.quote is None

    def test_fail_factory_with_quote(self):
        q = TeeQuote(
            backend=TeeBackend.MOCK,
            measurement="aa",
            report_data="bb",
            nonce=EPOCH,
            peer_id=PEER_ID,
            sig="",
        )
        r = VerificationResult.fail("test", q)
        assert r.quote is q
        assert r.backend == TeeBackend.MOCK

    def test_pass_factory(self):
        q = TeeQuote(
            backend=TeeBackend.MOCK,
            measurement="aa",
            report_data="bb",
            nonce=EPOCH,
            peer_id=PEER_ID,
            sig="",
        )
        r = VerificationResult.pass_(0.5, q)
        assert r.score == 0.5
        assert r.ok is True
        assert r.rejection_reason is None


class TestTcbUnknownScoring:
    """F-22: Test _score_from_tcb directly to avoid chain verification path issues."""

    def test_unknown_tcb_permissive_returns_zero(self, db, mock_config):
        """UNKNOWN TCB status should score 0.0 even with permissive policy."""
        mock_config.tcb_strict = False  # permissive
        verifier = DcapVerifier(db=db, config=mock_config)
        quote = TeeQuote(
            backend=TeeBackend.TDX,
            measurement="ab" * 24,
            report_data="cd" * 64,
            nonce=EPOCH,
            peer_id=PEER_ID,
            tcb_status=TcbStatus.UNKNOWN,
        )
        score = verifier._score_from_tcb(quote)
        assert score == 0.0, f"UNKNOWN TCB with permissive policy should be 0.0, got {score}"

    def test_unknown_tcb_strict_returns_zero(self, db, mock_config):
        mock_config.tcb_strict = True
        verifier = DcapVerifier(db=db, config=mock_config)
        quote = TeeQuote(
            backend=TeeBackend.TDX,
            measurement="ab" * 24,
            report_data="cd" * 64,
            nonce=EPOCH,
            peer_id=PEER_ID,
            tcb_status=TcbStatus.UNKNOWN,
        )
        score = verifier._score_from_tcb(quote)
        assert score == 0.0

    def test_sw_hardening_permissive_returns_degraded(self, db, mock_config):
        mock_config.tcb_strict = False
        verifier = DcapVerifier(db=db, config=mock_config)
        quote = TeeQuote(
            backend=TeeBackend.TDX,
            measurement="ab" * 24,
            report_data="cd" * 64,
            nonce=EPOCH,
            peer_id=PEER_ID,
            tcb_status=TcbStatus.SW_HARDENING_NEEDED,
        )
        score = verifier._score_from_tcb(quote)
        assert score == 0.5


class TestVerifyQuoteInline:
    """F-08: DcapVerifier.verify_quote() accepts a TeeQuote directly."""

    def test_valid_quote_passes(self, db, backend, mock_config):
        quote = backend.generate_quote(peer_id=PEER_ID, epoch=EPOCH)
        verifier = DcapVerifier(db=db, config=mock_config)
        result = verifier.verify_quote(quote, peer_id=PEER_ID, epoch=EPOCH)
        assert result.ok is True
        assert result.score == 0.5  # mock backend

    def test_wrong_peer_fails(self, db, backend, mock_config):
        quote = backend.generate_quote(peer_id=PEER_ID, epoch=EPOCH)
        verifier = DcapVerifier(db=db, config=mock_config)
        result = verifier.verify_quote(quote, peer_id=ANOTHER_PEER, epoch=EPOCH)
        assert result.ok is False
        assert result.rejection_reason == "identity_binding_failed"

    def test_wrong_epoch_fails(self, db, backend, mock_config):
        quote = backend.generate_quote(peer_id=PEER_ID, epoch=EPOCH)
        verifier = DcapVerifier(db=db, config=mock_config)
        result = verifier.verify_quote(quote, peer_id=PEER_ID, epoch=EPOCH + 1)
        assert result.ok is False
        assert "nonce_mismatch" in result.rejection_reason

    def test_debug_mode_fails(self, db, mock_config):
        debug_backend = MockBackend(key=mock_config.mock_key, debug_mode=True)
        quote = debug_backend.generate_quote(peer_id=PEER_ID, epoch=EPOCH)
        verifier = DcapVerifier(db=db, config=mock_config)
        result = verifier.verify_quote(quote, peer_id=PEER_ID, epoch=EPOCH)
        assert result.ok is False
        assert result.rejection_reason == "debug_mode"


# ------------------------------------------------------------------
# F-17: Multi-measurement support
# ------------------------------------------------------------------

class TestMultiMeasurement:
    """F-17: EXPECTED_MEASUREMENT accepts comma-separated list."""

    def _make_config_with_measurements(self, raw: str) -> TeeConfig:
        """Build a TeeConfig with expected_measurements parsed from raw string."""
        cfg = TeeConfig.__new__(TeeConfig)
        cfg.backend = TeeBackend.MOCK
        cfg.mock_key = b"mock-tee-dev-key-do-not-use-in-production-!!"
        raw_clean = raw.strip().lower()
        cfg.expected_measurements = [m.strip() for m in raw_clean.split(",") if m.strip()]
        cfg.expected_measurement = cfg.expected_measurements[0] if cfg.expected_measurements else ""
        cfg.min_tee_score = 0.0
        cfg.tcb_strict = True
        cfg.pccs_url = ""
        cfg.allow_shared_hardware = True
        return cfg

    def test_single_measurement_match_passes(self, db, backend):
        """Single measurement value that matches → PASS."""
        from subnet.tee.backends.mock import MOCK_MEASUREMENT
        pub = TeePublisher(db=db, peer_id=PEER_ID, backend=backend)
        pub.publish(EPOCH)

        cfg = self._make_config_with_measurements(MOCK_MEASUREMENT)
        verifier = DcapVerifier(db=db, config=cfg)
        result = verifier.verify(PEER_ID, EPOCH)
        assert result.ok is True
        assert result.score == 0.5

    def test_single_measurement_no_match_fails(self, db, backend):
        """Single measurement value that does not match → FAIL."""
        pub = TeePublisher(db=db, peer_id=PEER_ID, backend=backend)
        pub.publish(EPOCH)

        cfg = self._make_config_with_measurements("deadbeef" * 16)
        verifier = DcapVerifier(db=db, config=cfg)
        result = verifier.verify(PEER_ID, EPOCH)
        assert result.ok is False
        assert "measurement_mismatch" in result.rejection_reason

    def test_comma_list_one_matches_passes(self, db, backend):
        """Comma-separated list where one entry matches → PASS."""
        from subnet.tee.backends.mock import MOCK_MEASUREMENT
        pub = TeePublisher(db=db, peer_id=PEER_ID, backend=backend)
        pub.publish(EPOCH)

        # List contains the correct measurement among several wrong ones
        raw = f"deadbeef{'00' * 28},{MOCK_MEASUREMENT},cafecafe{'00' * 28}"
        cfg = self._make_config_with_measurements(raw)
        assert len(cfg.expected_measurements) == 3
        verifier = DcapVerifier(db=db, config=cfg)
        result = verifier.verify(PEER_ID, EPOCH)
        assert result.ok is True
        assert result.score == 0.5

    def test_comma_list_none_match_fails(self, db, backend):
        """Comma-separated list where no entry matches → FAIL."""
        pub = TeePublisher(db=db, peer_id=PEER_ID, backend=backend)
        pub.publish(EPOCH)

        raw = f"{'aa' * 32},{'bb' * 32}"
        cfg = self._make_config_with_measurements(raw)
        verifier = DcapVerifier(db=db, config=cfg)
        result = verifier.verify(PEER_ID, EPOCH)
        assert result.ok is False
        assert "measurement_mismatch" in result.rejection_reason

    def test_empty_string_skips_check(self, db, backend):
        """Empty EXPECTED_MEASUREMENT → measurement check skipped → PASS."""
        pub = TeePublisher(db=db, peer_id=PEER_ID, backend=backend)
        pub.publish(EPOCH)

        cfg = self._make_config_with_measurements("")
        assert cfg.expected_measurements == []
        verifier = DcapVerifier(db=db, config=cfg)
        result = verifier.verify(PEER_ID, EPOCH)
        assert result.ok is True

    def test_tee_config_env_parses_comma_list(self, monkeypatch):
        """TeeConfig reads EXPECTED_MEASUREMENT env var and parses comma list."""
        import os
        monkeypatch.setenv("EXPECTED_MEASUREMENT", "aabb,ccdd,eeff")
        cfg = TeeConfig()
        assert cfg.expected_measurements == ["aabb", "ccdd", "eeff"]
        assert cfg.expected_measurement == "aabb"

    def test_tee_config_env_single_value(self, monkeypatch):
        """TeeConfig with single measurement (no comma) still works."""
        monkeypatch.setenv("EXPECTED_MEASUREMENT", "abcdef01")
        cfg = TeeConfig()
        assert cfg.expected_measurements == ["abcdef01"]
        assert cfg.expected_measurement == "abcdef01"

    def test_tee_config_env_empty(self, monkeypatch):
        """TeeConfig with empty EXPECTED_MEASUREMENT → empty list."""
        monkeypatch.setenv("EXPECTED_MEASUREMENT", "")
        cfg = TeeConfig()
        assert cfg.expected_measurements == []
        assert cfg.expected_measurement == ""
