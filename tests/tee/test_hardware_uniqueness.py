"""
Tests for hardware-level Sybil resistance.

Covers:
- CVM hardware_id deduplication (same CHIP_ID on two peers → reject second)
- GPU UUID deduplication (same GPU on two peers → reject second)
- ALLOW_SHARED_HARDWARE bypass for single-machine testing
- Multiple GPUs per node (each UUID checked independently)
- Re-verification of the same peer (idempotent — not a duplicate)
- Empty hardware_id / gpu_uuids (skip check gracefully)
- clear_epoch frees tracking state
"""

import hashlib

import pytest

from subnet.tee.backends.mock import MockBackend, MOCK_HARDWARE_ID
from subnet.tee.config import TeeConfig
from subnet.tee.publisher import TeePublisher
from subnet.tee.quote import TeeBackend, TeeQuote
from subnet.tee.verifier import DcapVerifier
from subnet.utils.db.database import RocksDB

PEER_ID_A = "12D3KooWKxAhu5U8SreDZpokVkN6ciTBbsHxteo3Vmq6Cpuf8KEt"
PEER_ID_B = "12D3KooWM5J4zS17XR2LHGZgRpmzbeqg4Eibyq8sbRLwRuWxJqsV"
PEER_ID_C = "12D3KooWPJTZ7pJTkxpRPKvHfQsQvRjHXcKTcPnXHSdNkiLjRoNq"
EPOCH = 14_780_600

GPU_UUID_1 = "GPU-aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
GPU_UUID_2 = "GPU-11111111-2222-3333-4444-555555555555"

CHIP_ID_1 = hashlib.sha256(b"chip-1").hexdigest()
CHIP_ID_2 = hashlib.sha256(b"chip-2").hexdigest()


@pytest.fixture
def db(tmp_path):
    db_path = str(tmp_path / "hw_unique")
    database = RocksDB(base_path=db_path)
    yield database
    database.store.close()


def make_config(allow_shared: bool = False) -> TeeConfig:
    cfg = TeeConfig.__new__(TeeConfig)
    cfg.backend = TeeBackend.MOCK
    cfg.mock_key = b"mock-tee-dev-key-do-not-use-in-production-!!"
    cfg.expected_measurements = []
    cfg.expected_measurement = ""
    cfg.min_tee_score = 0.0
    cfg.tcb_strict = True
    cfg.pccs_url = ""
    cfg.allow_shared_hardware = allow_shared
    return cfg


class TestCvmHardwareDedup:
    """Two peers on the same CVM (same hardware_id) → reject second."""

    def test_same_hardware_id_rejects_second_peer(self, db):
        cfg = make_config(allow_shared=False)
        backend = MockBackend(key=cfg.mock_key, hardware_id=CHIP_ID_1)

        pub_a = TeePublisher(db=db, peer_id=PEER_ID_A, backend=backend)
        pub_b = TeePublisher(db=db, peer_id=PEER_ID_B, backend=backend)
        pub_a.publish(EPOCH)
        pub_b.publish(EPOCH)

        verifier = DcapVerifier(db=db, config=cfg)

        result_a = verifier.verify(PEER_ID_A, EPOCH)
        assert result_a.ok is True

        result_b = verifier.verify(PEER_ID_B, EPOCH)
        assert result_b.ok is False
        assert "duplicate_hardware" in result_b.rejection_reason

    def test_different_hardware_ids_both_pass(self, db):
        cfg = make_config(allow_shared=False)
        backend_a = MockBackend(key=cfg.mock_key, hardware_id=CHIP_ID_1)
        backend_b = MockBackend(key=cfg.mock_key, hardware_id=CHIP_ID_2)

        pub_a = TeePublisher(db=db, peer_id=PEER_ID_A, backend=backend_a)
        pub_b = TeePublisher(db=db, peer_id=PEER_ID_B, backend=backend_b)
        pub_a.publish(EPOCH)
        pub_b.publish(EPOCH)

        verifier = DcapVerifier(db=db, config=cfg)

        result_a = verifier.verify(PEER_ID_A, EPOCH)
        result_b = verifier.verify(PEER_ID_B, EPOCH)
        assert result_a.ok is True
        assert result_b.ok is True

    def test_same_peer_reverify_is_idempotent(self, db):
        """Re-verifying the same peer_id with the same hardware_id should pass."""
        cfg = make_config(allow_shared=False)
        backend = MockBackend(key=cfg.mock_key, hardware_id=CHIP_ID_1)

        pub = TeePublisher(db=db, peer_id=PEER_ID_A, backend=backend)
        pub.publish(EPOCH)

        verifier = DcapVerifier(db=db, config=cfg)

        result1 = verifier.verify(PEER_ID_A, EPOCH)
        result2 = verifier.verify(PEER_ID_A, EPOCH)
        assert result1.ok is True
        assert result2.ok is True


class TestGpuUuidDedup:
    """Two peers claiming the same GPU → reject second."""

    def test_same_gpu_uuid_rejects_second_peer(self, db):
        cfg = make_config(allow_shared=False)
        backend_a = MockBackend(key=cfg.mock_key, hardware_id=CHIP_ID_1, gpu_uuids=[GPU_UUID_1])
        backend_b = MockBackend(key=cfg.mock_key, hardware_id=CHIP_ID_2, gpu_uuids=[GPU_UUID_1])

        pub_a = TeePublisher(db=db, peer_id=PEER_ID_A, backend=backend_a)
        pub_b = TeePublisher(db=db, peer_id=PEER_ID_B, backend=backend_b)
        pub_a.publish(EPOCH)
        pub_b.publish(EPOCH)

        verifier = DcapVerifier(db=db, config=cfg)

        result_a = verifier.verify(PEER_ID_A, EPOCH)
        assert result_a.ok is True

        result_b = verifier.verify(PEER_ID_B, EPOCH)
        assert result_b.ok is False
        assert "duplicate_gpu" in result_b.rejection_reason

    def test_different_gpu_uuids_both_pass(self, db):
        cfg = make_config(allow_shared=False)
        backend_a = MockBackend(key=cfg.mock_key, hardware_id=CHIP_ID_1, gpu_uuids=[GPU_UUID_1])
        backend_b = MockBackend(key=cfg.mock_key, hardware_id=CHIP_ID_2, gpu_uuids=[GPU_UUID_2])

        pub_a = TeePublisher(db=db, peer_id=PEER_ID_A, backend=backend_a)
        pub_b = TeePublisher(db=db, peer_id=PEER_ID_B, backend=backend_b)
        pub_a.publish(EPOCH)
        pub_b.publish(EPOCH)

        verifier = DcapVerifier(db=db, config=cfg)

        result_a = verifier.verify(PEER_ID_A, EPOCH)
        result_b = verifier.verify(PEER_ID_B, EPOCH)
        assert result_a.ok is True
        assert result_b.ok is True

    def test_multi_gpu_partial_overlap_rejects(self, db):
        """Node B shares one GPU with Node A even though it also has a unique one."""
        cfg = make_config(allow_shared=False)
        backend_a = MockBackend(key=cfg.mock_key, hardware_id=CHIP_ID_1, gpu_uuids=[GPU_UUID_1])
        backend_b = MockBackend(key=cfg.mock_key, hardware_id=CHIP_ID_2, gpu_uuids=[GPU_UUID_2, GPU_UUID_1])

        pub_a = TeePublisher(db=db, peer_id=PEER_ID_A, backend=backend_a)
        pub_b = TeePublisher(db=db, peer_id=PEER_ID_B, backend=backend_b)
        pub_a.publish(EPOCH)
        pub_b.publish(EPOCH)

        verifier = DcapVerifier(db=db, config=cfg)

        result_a = verifier.verify(PEER_ID_A, EPOCH)
        assert result_a.ok is True

        result_b = verifier.verify(PEER_ID_B, EPOCH)
        assert result_b.ok is False
        assert "duplicate_gpu" in result_b.rejection_reason

    def test_no_gpu_uuids_passes(self, db):
        """Nodes without GPU still pass (CVM-only attestation)."""
        cfg = make_config(allow_shared=False)
        backend_a = MockBackend(key=cfg.mock_key, hardware_id=CHIP_ID_1, gpu_uuids=[])
        backend_b = MockBackend(key=cfg.mock_key, hardware_id=CHIP_ID_2, gpu_uuids=[])

        pub_a = TeePublisher(db=db, peer_id=PEER_ID_A, backend=backend_a)
        pub_b = TeePublisher(db=db, peer_id=PEER_ID_B, backend=backend_b)
        pub_a.publish(EPOCH)
        pub_b.publish(EPOCH)

        verifier = DcapVerifier(db=db, config=cfg)

        result_a = verifier.verify(PEER_ID_A, EPOCH)
        result_b = verifier.verify(PEER_ID_B, EPOCH)
        assert result_a.ok is True
        assert result_b.ok is True


class TestAllowSharedHardware:
    """ALLOW_SHARED_HARDWARE=true bypasses all dedup checks."""

    def test_shared_hardware_allowed_both_pass(self, db):
        cfg = make_config(allow_shared=True)
        backend = MockBackend(key=cfg.mock_key, hardware_id=CHIP_ID_1, gpu_uuids=[GPU_UUID_1])

        pub_a = TeePublisher(db=db, peer_id=PEER_ID_A, backend=backend)
        pub_b = TeePublisher(db=db, peer_id=PEER_ID_B, backend=backend)
        pub_a.publish(EPOCH)
        pub_b.publish(EPOCH)

        verifier = DcapVerifier(db=db, config=cfg)

        result_a = verifier.verify(PEER_ID_A, EPOCH)
        result_b = verifier.verify(PEER_ID_B, EPOCH)
        assert result_a.ok is True
        assert result_b.ok is True


class TestEmptyHardwareId:
    """Empty hardware_id skips CVM dedup (backward compat)."""

    def test_empty_hardware_id_skips_check(self, db):
        cfg = make_config(allow_shared=False)
        backend = MockBackend(key=cfg.mock_key, hardware_id="", gpu_uuids=[])

        pub_a = TeePublisher(db=db, peer_id=PEER_ID_A, backend=backend)
        pub_b = TeePublisher(db=db, peer_id=PEER_ID_B, backend=backend)
        pub_a.publish(EPOCH)
        pub_b.publish(EPOCH)

        verifier = DcapVerifier(db=db, config=cfg)

        result_a = verifier.verify(PEER_ID_A, EPOCH)
        result_b = verifier.verify(PEER_ID_B, EPOCH)
        assert result_a.ok is True
        assert result_b.ok is True


class TestClearEpoch:
    """clear_epoch removes tracking state for a given epoch."""

    def test_clear_epoch_allows_reuse(self, db):
        cfg = make_config(allow_shared=False)
        backend = MockBackend(key=cfg.mock_key, hardware_id=CHIP_ID_1)

        pub_a = TeePublisher(db=db, peer_id=PEER_ID_A, backend=backend)
        pub_b = TeePublisher(db=db, peer_id=PEER_ID_B, backend=backend)
        pub_a.publish(EPOCH)
        pub_b.publish(EPOCH)

        verifier = DcapVerifier(db=db, config=cfg)

        # First pass: A takes the hardware_id
        result_a = verifier.verify(PEER_ID_A, EPOCH)
        assert result_a.ok is True

        # B rejected
        result_b = verifier.verify(PEER_ID_B, EPOCH)
        assert result_b.ok is False

        # Clear epoch state
        verifier.clear_epoch(EPOCH)

        # Now B can claim the hardware_id (simulates new epoch scoring round)
        result_b2 = verifier.verify(PEER_ID_B, EPOCH)
        assert result_b2.ok is True


class TestThreePeersSameHardware:
    """Three peers on same CVM — only first passes."""

    def test_third_peer_also_rejected(self, db):
        cfg = make_config(allow_shared=False)
        backend = MockBackend(key=cfg.mock_key, hardware_id=CHIP_ID_1, gpu_uuids=[GPU_UUID_1])

        for pid in [PEER_ID_A, PEER_ID_B, PEER_ID_C]:
            pub = TeePublisher(db=db, peer_id=pid, backend=backend)
            pub.publish(EPOCH)

        verifier = DcapVerifier(db=db, config=cfg)

        result_a = verifier.verify(PEER_ID_A, EPOCH)
        result_b = verifier.verify(PEER_ID_B, EPOCH)
        result_c = verifier.verify(PEER_ID_C, EPOCH)

        assert result_a.ok is True
        assert result_b.ok is False
        assert result_c.ok is False
        assert "duplicate_hardware" in result_b.rejection_reason
        assert "duplicate_hardware" in result_c.rejection_reason


class TestQuoteSerialization:
    """hardware_id and gpu_uuids survive serialization round-trip."""

    def test_roundtrip_with_hardware_fields(self):
        quote = TeeQuote(
            backend=TeeBackend.MOCK,
            measurement="abc123",
            report_data="00" * 64,
            nonce=1,
            peer_id="test-peer",
            hardware_id=CHIP_ID_1,
            gpu_uuids=[GPU_UUID_1, GPU_UUID_2],
        )
        raw = quote.to_bytes()
        restored = TeeQuote.from_bytes(raw)

        assert restored.hardware_id == CHIP_ID_1
        assert restored.gpu_uuids == [GPU_UUID_1, GPU_UUID_2]

    def test_roundtrip_empty_hardware_fields(self):
        quote = TeeQuote(
            backend=TeeBackend.MOCK,
            measurement="abc123",
            report_data="00" * 64,
            nonce=1,
            peer_id="test-peer",
        )
        raw = quote.to_bytes()
        restored = TeeQuote.from_bytes(raw)

        assert restored.hardware_id == ""
        assert restored.gpu_uuids == []

    def test_backward_compat_no_hardware_fields(self):
        """Quotes without hardware fields (v1 format) deserialize with defaults."""
        import json
        d = {
            "version": 1,
            "backend": "mock",
            "measurement": "abc",
            "report_data": "00" * 64,
            "nonce": 1,
            "peer_id": "test",
            "timestamp": 0.0,
        }
        raw = json.dumps(d).encode()
        restored = TeeQuote.from_bytes(raw)
        assert restored.hardware_id == ""
        assert restored.gpu_uuids == []
