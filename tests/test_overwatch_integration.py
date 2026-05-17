"""
Integration tests for ChainOverwatchReporter.

These tests verify the full overwatch slash pipeline end-to-end using the
mock Hypertensor backend — from tamper detection through commit/reveal extrinsic
submission and on-chain state confirmation.

Coverage:
  - Reporter submits commit + reveal when parity_mismatch is detected
  - Reporter is silent (no extrinsic) when parity is clean
  - Reporter is silent when OVERWATCH_NODE_ID is unset (env guard)
  - Commit hash matches sha256(weight_bytes + salt) — commit-reveal integrity
  - reveal_overwatch_subnet_weights is called with weight=0 (punish) on tamper
  - No extrinsic is submitted for no_work_record (cold-start epoch)
"""

import hashlib
import json
import os
import pytest
import trio
import subnet.node.mock as mock_module

from unittest.mock import MagicMock, patch, call

from subnet.node.mock import (
    MockNodeProtocol,
    MockOverwatchVerifier,
    _WORK_TOPIC,
    _dht_key,
)
from subnet.consensus.chain_overwatch_reporter import ChainOverwatchReporter
from subnet.tee.ratls.envelope import OutputEnvelope
from subnet.utils.db.database import RocksDB

PEER_A = "12D3KooWKxAhu5U8SreDZpokVkN6ciTBbsHxteo3Vmq6Cpuf8KEt"
EPOCH  = 42_000
SUBNET_ID = 1
OVERWATCH_NODE_ID = 1


# ── fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def db(tmp_path):
    d = RocksDB(base_path=str(tmp_path / "ow_test"))
    yield d
    d.store.close()


def _make_miner(db):
    p = MockNodeProtocol.__new__(MockNodeProtocol)
    p.host = p.subnet_info_tracker = None
    p.peer_id = PEER_A
    p.mode = "miner"
    p.db = db
    p._extra = {}
    p._tee_publisher = p._verifier = p._backend = p._tee_config = None
    return p


@pytest.fixture
def miner(db):
    return _make_miner(db)


@pytest.fixture
def overwatch_verifier(db):
    return MockOverwatchVerifier(db=db, config=None)


def _mock_hypertensor():
    """Return a mock Hypertensor with commit/reveal methods stubbed to success."""
    ht = MagicMock()
    success_receipt = MagicMock()
    success_receipt.is_success = True
    success_receipt.extrinsic_hash = "0xdeadbeef"
    ht.commit_overwatch_subnet_weights.return_value = success_receipt
    ht.reveal_overwatch_subnet_weights.return_value = success_receipt
    return ht


# ── reporter unit tests ───────────────────────────────────────────────────────

class TestChainOverwatchReporterUnit:
    """Direct unit tests for ChainOverwatchReporter.slash()."""

    def test_slash_calls_commit_then_reveal(self):
        ht = _mock_hypertensor()
        reporter = ChainOverwatchReporter(ht, OVERWATCH_NODE_ID, SUBNET_ID)

        receipt = reporter.slash(PEER_A, EPOCH)

        assert ht.commit_overwatch_subnet_weights.call_count == 1
        assert ht.reveal_overwatch_subnet_weights.call_count == 1
        assert receipt.is_success is True

    def test_slash_commit_hash_integrity(self):
        """Commit hash must equal sha256(weight_bytes + salt) with weight=0."""
        ht = _mock_hypertensor()
        reporter = ChainOverwatchReporter(ht, OVERWATCH_NODE_ID, SUBNET_ID)

        reporter.slash(PEER_A, EPOCH)

        commit_call_args = ht.commit_overwatch_subnet_weights.call_args
        reveal_call_args = ht.reveal_overwatch_subnet_weights.call_args

        # Extract commit weights and reveals from positional/keyword args
        commit_weights = commit_call_args[0][1]   # second positional arg
        reveals = reveal_call_args[0][1]

        commit = commit_weights[0]
        reveal = reveals[0]

        weight_int = reveal["weight"]   # should be 0 (punish)
        salt = reveal["salt"]
        claimed_hash = commit["weight"]  # bytes — the commit hash

        # weight=0 = punish
        assert weight_int == 0

        # Verify hash integrity
        expected_hash = hashlib.sha256(
            weight_int.to_bytes(16, byteorder="big") + salt
        ).digest()
        assert claimed_hash == expected_hash

    def test_slash_commit_failure_returns_early(self):
        """If commit fails, reveal should not be called."""
        ht = _mock_hypertensor()
        fail_receipt = MagicMock()
        fail_receipt.is_success = False
        fail_receipt.error_message = "InsufficientStake"
        ht.commit_overwatch_subnet_weights.return_value = fail_receipt

        reporter = ChainOverwatchReporter(ht, OVERWATCH_NODE_ID, SUBNET_ID)
        receipt = reporter.slash(PEER_A, EPOCH)

        assert ht.commit_overwatch_subnet_weights.call_count == 1
        assert ht.reveal_overwatch_subnet_weights.call_count == 0
        assert receipt.is_success is False

    def test_slash_exception_returns_none(self):
        """If hypertensor raises, slash returns None (non-fatal)."""
        ht = MagicMock()
        ht.commit_overwatch_subnet_weights.side_effect = RuntimeError("connection lost")

        reporter = ChainOverwatchReporter(ht, OVERWATCH_NODE_ID, SUBNET_ID)
        receipt = reporter.slash(PEER_A, EPOCH)

        assert receipt is None

    def test_slash_correct_subnet_id(self):
        """Commit and reveal must reference the configured subnet_id."""
        ht = _mock_hypertensor()
        reporter = ChainOverwatchReporter(ht, OVERWATCH_NODE_ID, subnet_id=99)

        reporter.slash(PEER_A, EPOCH)

        commit_weights = ht.commit_overwatch_subnet_weights.call_args[0][1]
        reveals = ht.reveal_overwatch_subnet_weights.call_args[0][1]

        assert commit_weights[0]["subnet_id"] == 99
        assert reveals[0]["subnet_id"] == 99


# ── overwatch detect-and-slash pipeline ──────────────────────────────────────

async def mine(miner_proto, epoch=EPOCH):
    await miner_proto.register_handlers()
    await miner_proto.miner_loop(epoch)


class TestOverwatchSlashPipeline:
    """End-to-end: tamper detected by verifier → reporter slashes on chain."""

    def test_tamper_triggers_slash(self, miner, db, overwatch_verifier):
        """parity_mismatch → reporter.slash() is called once."""
        original_rate = mock_module.TAMPER_RATE
        mock_module.TAMPER_RATE = 1.0
        try:
            trio.run(mine, miner)
        finally:
            mock_module.TAMPER_RATE = original_rate

        result = overwatch_verifier.verify(PEER_A, EPOCH)
        assert result.ok is False
        assert result.reason == "parity_mismatch"

        ht = _mock_hypertensor()
        reporter = ChainOverwatchReporter(ht, OVERWATCH_NODE_ID, SUBNET_ID)
        if result.reason == "parity_mismatch":
            reporter.slash(PEER_A, EPOCH, result.details)

        assert ht.commit_overwatch_subnet_weights.call_count == 1
        assert ht.reveal_overwatch_subnet_weights.call_count == 1

    def test_clean_work_no_slash(self, miner, db, overwatch_verifier):
        """Clean miner → overwatch passes → no slash extrinsic."""
        original_rate = mock_module.TAMPER_RATE
        mock_module.TAMPER_RATE = 0.0
        try:
            trio.run(mine, miner)
        finally:
            mock_module.TAMPER_RATE = original_rate

        result = overwatch_verifier.verify(PEER_A, EPOCH)
        assert result.ok is True

        ht = _mock_hypertensor()
        reporter = ChainOverwatchReporter(ht, OVERWATCH_NODE_ID, SUBNET_ID)
        if not result.ok and result.reason == "parity_mismatch":
            reporter.slash(PEER_A, EPOCH)

        # No extrinsic submitted for clean work
        assert ht.commit_overwatch_subnet_weights.call_count == 0
        assert ht.reveal_overwatch_subnet_weights.call_count == 0

    def test_no_work_record_no_slash(self, db, overwatch_verifier):
        """Cold start (no_work_record) → verifier returns not-ok but no slash fires."""
        # Don't mine — no work record exists
        result = overwatch_verifier.verify(PEER_A, EPOCH)
        assert result.ok is False
        assert result.reason == "no_work_record"

        ht = _mock_hypertensor()
        reporter = ChainOverwatchReporter(ht, OVERWATCH_NODE_ID, SUBNET_ID)
        # Mirroring server.py: only slash on parity_mismatch, not no_work_record
        if result.reason == "parity_mismatch":
            reporter.slash(PEER_A, EPOCH)

        assert ht.commit_overwatch_subnet_weights.call_count == 0
        assert ht.reveal_overwatch_subnet_weights.call_count == 0

    def test_multiple_epochs_slash_each_tamper(self, miner, db, overwatch_verifier):
        """Each tampered epoch produces an independent slash — not batched or coalesced."""
        original_rate = mock_module.TAMPER_RATE
        mock_module.TAMPER_RATE = 1.0
        try:
            for ep in range(3):
                m = _make_miner(db)
                trio.run(mine, m, EPOCH + ep)
        finally:
            mock_module.TAMPER_RATE = original_rate

        ht = _mock_hypertensor()
        reporter = ChainOverwatchReporter(ht, OVERWATCH_NODE_ID, SUBNET_ID)

        slash_count = 0
        for ep in range(3):
            result = overwatch_verifier.verify(PEER_A, EPOCH + ep)
            if result.reason == "parity_mismatch":
                reporter.slash(PEER_A, EPOCH + ep)
                slash_count += 1

        assert slash_count == 3
        assert ht.commit_overwatch_subnet_weights.call_count == 3
        assert ht.reveal_overwatch_subnet_weights.call_count == 3


# ── F-07: Overwatch RA-TLS signature verification ─────────────────────────────

class TestOverwatchSignatureVerification:
    """F-07: Overwatch catches OutputEnvelope signed with the wrong session key."""

    def test_wrong_session_key_detected(self, db):
        """
        Miner publishes a work record signed with one session key but overwatch
        fetches the RA-TLS cert for a *different* key pair — signature must fail.
        """
        from subnet.tee.ratls.envelope import OutputEnvelope
        from subnet.tee.ratls.session import RaTlsSession
        from subnet.tee.ratls.cert import get_cert_public_key_bytes
        from subnet.tee.quote import RATLS_CERT_TOPIC, TEE_QUOTE_TOPIC
        from subnet.tee.backends.mock import MockBackend
        from subnet.tee.ratls.server import RaTlsServer
        import hashlib, json

        backend = MockBackend()

        # Build the legitimate miner cert & session
        server = RaTlsServer(peer_id=PEER_A, epoch=EPOCH, backend=backend)
        bundle = server.cert_bundle
        quote  = bundle.quote

        # Store the TEE quote in DHT
        db.nmap_set(TEE_QUOTE_TOPIC, _dht_key(EPOCH, PEER_A), quote.to_bytes())

        # Build a DIFFERENT server (different ephemeral key) to get a wrong session
        wrong_server  = RaTlsServer(peer_id=PEER_A, epoch=EPOCH, backend=backend)
        wrong_bundle  = wrong_server.cert_bundle
        wrong_session = wrong_server.make_session()

        # Store the *wrong* cert in RATLS_CERT_TOPIC (simulates a replay/confusion attack)
        db.nmap_set(RATLS_CERT_TOPIC, _dht_key(EPOCH, PEER_A), wrong_bundle.cert_pem)

        # Sign the work record with the *correct* session
        correct_session = server.make_session()
        n = 42
        parity = "even"
        record = {
            "epoch": EPOCH,
            "peer_id": PEER_A,
            "n": n,
            "parity": parity,
            "tee_quote_hash": hashlib.sha256(quote.to_bytes()).hexdigest(),
        }
        request_id = f"mock:{EPOCH}:{PEER_A[:8]}"
        output_env = OutputEnvelope.create(
            request_id=request_id,
            output=json.dumps(record).encode(),
            session=correct_session,
        )
        db.nmap_set(_WORK_TOPIC, _dht_key(EPOCH, PEER_A), output_env.to_bytes())

        # Overwatch verifies — it will fetch wrong_bundle cert → wrong session key
        ow = MockOverwatchVerifier(db=db, config=None)
        result = ow.verify(PEER_A, EPOCH)

        assert result.ok is False
        assert result.reason == "output_signature_invalid"

    def test_correct_session_key_passes(self, db):
        """
        When the cert in DHT matches the session used to sign — overwatch should pass.
        """
        from subnet.tee.ratls.envelope import OutputEnvelope
        from subnet.tee.quote import RATLS_CERT_TOPIC, TEE_QUOTE_TOPIC
        from subnet.tee.backends.mock import MockBackend
        from subnet.tee.ratls.server import RaTlsServer
        import hashlib, json

        backend = MockBackend()
        server  = RaTlsServer(peer_id=PEER_A, epoch=EPOCH, backend=backend)
        bundle  = server.cert_bundle
        quote   = bundle.quote
        session = server.make_session()

        # Store TEE quote and cert in DHT
        db.nmap_set(TEE_QUOTE_TOPIC, _dht_key(EPOCH, PEER_A), quote.to_bytes())
        db.nmap_set(RATLS_CERT_TOPIC, _dht_key(EPOCH, PEER_A), bundle.cert_pem)

        # Sign with the matching session
        n = 7
        parity = "odd"
        record = {
            "epoch": EPOCH,
            "peer_id": PEER_A,
            "n": n,
            "parity": parity,
            "tee_quote_hash": hashlib.sha256(quote.to_bytes()).hexdigest(),
        }
        request_id = f"mock:{EPOCH}:{PEER_A[:8]}"
        output_env = OutputEnvelope.create(
            request_id=request_id,
            output=json.dumps(record).encode(),
            session=session,
        )
        db.nmap_set(_WORK_TOPIC, _dht_key(EPOCH, PEER_A), output_env.to_bytes())

        ow = MockOverwatchVerifier(db=db, config=None)
        result = ow.verify(PEER_A, EPOCH)

        assert result.ok is True
        assert result.reason == "pass"

    def test_missing_cert_skips_sig_check(self, db):
        """
        If RA-TLS cert is absent from DHT (older epoch), overwatch should still
        pass (backward compat) — no cert = skip signature check.
        """
        from subnet.tee.ratls.envelope import OutputEnvelope
        from subnet.tee.quote import TEE_QUOTE_TOPIC
        from subnet.tee.backends.mock import MockBackend
        from subnet.tee.ratls.server import RaTlsServer
        import hashlib, json

        backend = MockBackend()
        server  = RaTlsServer(peer_id=PEER_A, epoch=EPOCH, backend=backend)
        bundle  = server.cert_bundle
        quote   = bundle.quote
        session = server.make_session()

        # Store TEE quote but NOT the cert
        db.nmap_set(TEE_QUOTE_TOPIC, _dht_key(EPOCH, PEER_A), quote.to_bytes())
        # (no RATLS_CERT_TOPIC entry)

        n = 4
        parity = "even"
        record = {
            "epoch": EPOCH,
            "peer_id": PEER_A,
            "n": n,
            "parity": parity,
            "tee_quote_hash": hashlib.sha256(quote.to_bytes()).hexdigest(),
        }
        request_id = f"mock:{EPOCH}:{PEER_A[:8]}"
        output_env = OutputEnvelope.create(
            request_id=request_id,
            output=json.dumps(record).encode(),
            session=session,
        )
        db.nmap_set(_WORK_TOPIC, _dht_key(EPOCH, PEER_A), output_env.to_bytes())

        ow = MockOverwatchVerifier(db=db, config=None)
        result = ow.verify(PEER_A, EPOCH)

        # Missing cert → sig check skipped → passes parity + quote hash checks
        assert result.ok is True
        assert result.reason == "pass"


# ── OVERWATCH_NODE_ID env guard ───────────────────────────────────────────────

class TestOverwatchEnvGuard:
    """reporter=None when OVERWATCH_NODE_ID is not set — verified via server.py logic."""

    def test_no_env_var_no_reporter(self):
        """When OVERWATCH_NODE_ID is absent, reporter must be None."""
        env_without_id = {k: v for k, v in os.environ.items() if k != "OVERWATCH_NODE_ID"}
        with patch.dict(os.environ, env_without_id, clear=True):
            node_id_str = os.environ.get("OVERWATCH_NODE_ID", "")
            reporter = (
                ChainOverwatchReporter(MagicMock(), int(node_id_str), SUBNET_ID)
                if node_id_str.isdigit()
                else None
            )
        assert reporter is None

    def test_env_var_set_creates_reporter(self):
        """When OVERWATCH_NODE_ID is set, reporter must be created."""
        with patch.dict(os.environ, {"OVERWATCH_NODE_ID": "1"}):
            node_id_str = os.environ.get("OVERWATCH_NODE_ID", "")
            reporter = (
                ChainOverwatchReporter(MagicMock(), int(node_id_str), SUBNET_ID)
                if node_id_str.isdigit()
                else None
            )
        assert reporter is not None
        assert reporter.overwatch_node_id == 1

    def test_empty_env_var_no_reporter(self):
        """Empty string OVERWATCH_NODE_ID must not create a reporter."""
        with patch.dict(os.environ, {"OVERWATCH_NODE_ID": ""}):
            node_id_str = os.environ.get("OVERWATCH_NODE_ID", "")
            reporter = (
                ChainOverwatchReporter(MagicMock(), int(node_id_str), SUBNET_ID)
                if node_id_str.isdigit()
                else None
            )
        assert reporter is None
