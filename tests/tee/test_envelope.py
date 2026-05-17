"""
Tests for WorkEnvelope, OutputEnvelope, RATLS_CERT_TOPIC, and wired MockNodeProtocol.

Coverage areas:
1. WorkEnvelope — create/decrypt round-trip, TeeDecryptionError on tamper,
   to_bytes/from_bytes, forwards-compat extra-field deserialization.
2. OutputEnvelope — create/verify, tampered output → False, tampered sig → False,
   replay protection (different request_id → False), to_bytes/from_bytes.
3. RATLS_CERT_TOPIC — constant value "ratls_cert" and dht_key format.
4. MockNodeProtocol — full round-trip (cert + signed output), no cert → score=0.0,
   tampered output envelope → score=0.0.

All TestWorkEnvelope, TestOutputEnvelope, and TestRatlsCertTopic.test_constant_value
tests fail with ImportError until T02 creates subnet/tee/ratls/envelope.py and adds
RATLS_CERT_TOPIC to subnet/tee/quote.py.

TestMockProtocolSignedOutput tests fail with ImportError until T02+T03 wire the
protocol. All tests collect cleanly because imports are inside each test function.
"""

from __future__ import annotations

import json

import pytest
import trio

from subnet.tee.backends.mock import MockBackend
from subnet.tee.config import TeeConfig
from subnet.tee.quote import TeeBackend, dht_key
from subnet.tee.ratls import RaTlsServer, RaTlsSession, get_cert_public_key_bytes
from subnet.node.mock import MockNodeProtocol, _WORK_TOPIC, _dht_key
from subnet.utils.db.database import RocksDB

PEER_ID = "12D3KooWKxAhu5U8SreDZpokVkN6ciTBbsHxteo3Vmq6Cpuf8KEt"
EPOCH = 14_780_500
MOCK_KEY = b"mock-tee-dev-key-do-not-use-in-production-!!"


# ── Shared fixtures ────────────────────────────────────────────────────────────

@pytest.fixture
def backend():
    return MockBackend(key=MOCK_KEY)


@pytest.fixture
def mock_config():
    cfg = TeeConfig.__new__(TeeConfig)
    cfg.backend = TeeBackend.MOCK
    cfg.mock_key = MOCK_KEY
    cfg.expected_measurements = []
    cfg.expected_measurement = ""
    cfg.min_tee_score = 0.0
    cfg.tcb_strict = True
    cfg.pccs_url = ""
    cfg.allow_shared_hardware = True
    return cfg


@pytest.fixture
def server(backend):
    """RaTlsServer for PEER_ID at EPOCH — shared source of cert + session."""
    return RaTlsServer(peer_id=PEER_ID, epoch=EPOCH, backend=backend)


@pytest.fixture
def bundle(server):
    """RaTlsCertBundle from the server — cert_pem + key_pem."""
    return server.cert_bundle


@pytest.fixture
def session(server):
    """RaTlsSession derived from the server cert. Both sides share the same key."""
    return server.make_session()


@pytest.fixture
def db(tmp_path):
    """In-memory-equivalent RocksDB in a temp directory."""
    d = RocksDB(base_path=str(tmp_path / "test"))
    yield d
    d.store.close()


# ── MockNodeProtocol integration helpers ──────────────────────────────────────

def _make_proto(db, peer_id: str, mode: str) -> MockNodeProtocol:
    p = MockNodeProtocol.__new__(MockNodeProtocol)
    p.host = p.subnet_info_tracker = None
    p.peer_id = peer_id
    p.mode = mode
    p.db = db
    p._extra = {}
    p._tee_publisher = p._verifier = p._backend = p._tee_config = None
    return p


@pytest.fixture
def miner(db):
    return _make_proto(db, PEER_ID, "miner")


@pytest.fixture
def validator(db):
    return _make_proto(
        db, "12D3KooWM5J4zS17XR2LHGZgRpmzbeqg4Eibyq8sbRLwRuWxJqsV", "validator"
    )


async def _run(proto):
    await proto.register_handlers()


async def _mine(miner, epoch: int = EPOCH):
    await _run(miner)
    return await miner.miner_loop(epoch)


async def _validate(validator, peer_id: str = PEER_ID, epoch: int = EPOCH):
    await _run(validator)
    return await validator.validator_call(peer_id=peer_id, epoch=epoch)


# ── TestWorkEnvelope ──────────────────────────────────────────────────────────

class TestWorkEnvelope:

    def test_create_decrypt_roundtrip(self, session):
        from subnet.tee.ratls.envelope import WorkEnvelope
        envelope = WorkEnvelope.create(b"work payload", session)
        request_id, decrypted = envelope.decrypt(session)
        assert decrypted == b"work payload"
        assert len(request_id) > 0

    def test_request_id_is_unique(self, session):
        from subnet.tee.ratls.envelope import WorkEnvelope
        e1 = WorkEnvelope.create(b"same payload", session)
        e2 = WorkEnvelope.create(b"same payload", session)
        assert e1.request_id != e2.request_id

    def test_tampered_ciphertext_raises_tee_decryption_error(self, session):
        from subnet.tee.ratls.envelope import WorkEnvelope, TeeDecryptionError
        envelope = WorkEnvelope.create(b"secret work", session)
        # Flip the last byte of the ciphertext to break AES-GCM authentication
        tampered = bytearray(envelope.ciphertext)
        tampered[-1] ^= 0xFF
        envelope.ciphertext = bytes(tampered)
        with pytest.raises(TeeDecryptionError):
            envelope.decrypt(session)

    def test_to_bytes_from_bytes_roundtrip(self, session):
        from subnet.tee.ratls.envelope import WorkEnvelope
        envelope = WorkEnvelope.create(b"roundtrip payload", session)
        restored = WorkEnvelope.from_bytes(envelope.to_bytes())
        assert restored.request_id == envelope.request_id
        assert restored.ciphertext == envelope.ciphertext

    def test_from_bytes_extra_fields_ignored(self, session):
        from subnet.tee.ratls.envelope import WorkEnvelope
        envelope = WorkEnvelope.create(b"payload", session)
        # Inject an unknown future field into the serialised form
        raw = json.loads(envelope.to_bytes())
        raw["extra_future_field"] = "unexpected_value"
        patched = json.dumps(raw).encode()
        # Must not raise — forwards-compat deserialization
        restored = WorkEnvelope.from_bytes(patched)
        assert restored.request_id == envelope.request_id


# ── TestOutputEnvelope ────────────────────────────────────────────────────────

class TestOutputEnvelope:

    def test_create_verify_valid(self, session):
        from subnet.tee.ratls.envelope import OutputEnvelope
        output = b"miner output data"
        env = OutputEnvelope.create("req-001", output, session)
        assert env.verify(session) is True

    def test_tampered_output_fails_verify(self, session):
        from subnet.tee.ratls.envelope import OutputEnvelope
        output = b"original output"
        env = OutputEnvelope.create("req-002", output, session)
        # Flip first byte of the output field
        tampered = bytearray(env.output)
        tampered[0] ^= 0xFF
        env.output = bytes(tampered)
        assert env.verify(session) is False

    def test_tampered_signature_fails_verify(self, session):
        from subnet.tee.ratls.envelope import OutputEnvelope
        output = b"output data"
        env = OutputEnvelope.create("req-003", output, session)
        # Flip first byte of the signature field
        tampered_sig = bytearray(env.signature)
        tampered_sig[0] ^= 0xFF
        env.signature = bytes(tampered_sig)
        assert env.verify(session) is False

    def test_replay_protection(self, session):
        from subnet.tee.ratls.envelope import OutputEnvelope
        output = b"output data"
        # Create envelope bound to request_id="A"
        env_a = OutputEnvelope.create("A", output, session)
        # Construct a fake envelope with request_id="B" but the signature from "A"
        # Signature is bound to "A", so verifying with "B" must return False
        env_b = OutputEnvelope(
            request_id="B",
            output=env_a.output,
            signature=env_a.signature,
        )
        assert env_b.verify(session) is False

    def test_to_bytes_from_bytes_roundtrip(self, session):
        from subnet.tee.ratls.envelope import OutputEnvelope
        output = b"serialized output"
        env = OutputEnvelope.create("req-005", output, session)
        restored = OutputEnvelope.from_bytes(env.to_bytes())
        assert restored.request_id == env.request_id
        assert restored.output == env.output
        assert restored.signature == env.signature


# ── TestRatlsCertTopic ────────────────────────────────────────────────────────

class TestRatlsCertTopic:

    def test_constant_value(self):
        from subnet.tee.quote import RATLS_CERT_TOPIC
        assert RATLS_CERT_TOPIC == "ratls_cert"

    def test_dht_key_format(self):
        from subnet.tee.quote import dht_key as quote_dht_key
        peer_id = "12D3KooWKxAhu5U8SreDZpokVkN6ciTBbsHxteo3Vmq6Cpuf8KEt"
        result = quote_dht_key(14780500, peer_id)
        assert result == f"14780500:{peer_id}"


# ── TestMockProtocolSignedOutput ──────────────────────────────────────────────

class TestMockProtocolSignedOutput:

    def test_miner_publishes_cert_and_signed_output(self, miner, db):
        """After miner_loop: cert_pem in DHT under RATLS_CERT_TOPIC; work record
        stored as a valid OutputEnvelope (not raw JSON)."""
        from subnet.tee.ratls.envelope import OutputEnvelope
        from subnet.tee.quote import RATLS_CERT_TOPIC, dht_key as quote_dht_key

        trio.run(_mine, miner)

        # Cert must be present and look like PEM
        cert_raw = db.nmap_get(RATLS_CERT_TOPIC, quote_dht_key(EPOCH, PEER_ID))
        assert cert_raw is not None
        assert cert_raw.startswith(b"-----BEGIN CERTIFICATE-----")

        # Work record must deserialise as OutputEnvelope with all three fields set
        work_raw = db.nmap_get(_WORK_TOPIC, _dht_key(EPOCH, PEER_ID))
        assert work_raw is not None
        env = OutputEnvelope.from_bytes(work_raw)
        assert len(env.request_id) > 0
        assert len(env.output) > 0
        assert len(env.signature) > 0

    def test_validator_verifies_signed_output(self, miner, validator, db):
        """Full round-trip: miner publishes cert + signed output; validator verifies
        and returns success=True with tee_score > 0."""
        from subnet.tee.quote import RATLS_CERT_TOPIC  # noqa: F401 — fails until T02

        async def _run():
            await _mine(miner)
            return await _validate(validator)

        result = trio.run(_run)
        assert result.success is True
        assert result.metrics["tee_score"] > 0.0

    def test_no_cert_score_zero(self, miner, validator, db):
        """If the miner's cert is absent from DHT, validator must return
        success=False with error='no_ratls_cert'."""
        from subnet.tee.quote import RATLS_CERT_TOPIC, dht_key as quote_dht_key

        async def _run():
            await _mine(miner)
            # Delete cert from DHT so validator cannot verify RA-TLS
            db.nmap_set(RATLS_CERT_TOPIC, quote_dht_key(EPOCH, PEER_ID), None)
            return await _validate(validator)

        result = trio.run(_run)
        assert result.success is False
        assert result.error == "no_ratls_cert"

    def test_tampered_output_signature_score_zero(self, miner, validator, db):
        """If the OutputEnvelope signature is corrupted, validator must return
        success=False with error='output_signature_invalid'."""
        from subnet.tee.ratls.envelope import OutputEnvelope
        from subnet.tee.quote import RATLS_CERT_TOPIC  # noqa: F401 — fails until T02

        async def _run():
            await _mine(miner)
            # Corrupt the OutputEnvelope signature stored in DHT
            key = _dht_key(EPOCH, PEER_ID)
            raw = db.nmap_get(_WORK_TOPIC, key)
            env = OutputEnvelope.from_bytes(raw)
            bad_sig = bytearray(env.signature)
            bad_sig[0] ^= 0xFF
            env.signature = bytes(bad_sig)
            db.nmap_set(_WORK_TOPIC, key, env.to_bytes())
            return await _validate(validator)

        result = trio.run(_run)
        assert result.success is False
        assert result.error == "output_signature_invalid"
