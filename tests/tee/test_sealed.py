"""
Tests for SealedStore — measurement-bound encrypted storage.

Covers:
- seal + unseal round-trip with same measurement
- unseal returns None for missing key
- different measurement → SealedDecryptionError (key rotation / binary change)
- different mock_key → SealedDecryptionError
- delete removes entry
- exists check
- seal_json / unseal_json round-trip
- overwrite (seal same key twice → latest value)
- deterministic: same measurement + key → always unseals (not tied to nonce)
- large payload
"""

import pytest

from subnet.tee.backends.mock import MOCK_MEASUREMENT
from subnet.tee.sealed import SealedDecryptionError, SealedStore
from subnet.utils.db.database import RocksDB

PEER_ID = "12D3KooWKxAhu5U8SreDZpokVkN6ciTBbsHxteo3Vmq6Cpuf8KEt"
MOCK_KEY = b"mock-tee-dev-key-do-not-use-in-production-!!"
ALT_MEASUREMENT = "ff" * 32   # "different binary"
ALT_KEY = b"different-mock-key-that-no-binary-should-share!!"


@pytest.fixture
def db(tmp_path):
    db_path = str(tmp_path / "sealed_test")
    database = RocksDB(base_path=db_path)
    yield database
    database.store.close()


@pytest.fixture
def store(db):
    return SealedStore(db=db, measurement=MOCK_MEASUREMENT, mock_key=MOCK_KEY)


class TestSealUnsealRoundTrip:
    def test_basic_round_trip(self, store):
        store.seal("my_key", b"sensitive data")
        assert store.unseal("my_key") == b"sensitive data"

    def test_bytes_preserved_exactly(self, store):
        payload = bytes(range(256))
        store.seal("bin", payload)
        assert store.unseal("bin") == payload

    def test_missing_key_returns_none(self, store):
        assert store.unseal("nonexistent") is None

    def test_large_payload(self, store):
        payload = b"x" * 1_000_000  # 1 MB
        store.seal("large", payload)
        assert store.unseal("large") == payload


class TestMeasurementBinding:
    def test_different_measurement_cannot_unseal(self, db):
        """Simulates binary update: different measurement = different sealing key."""
        store_v1 = SealedStore(db=db, measurement=MOCK_MEASUREMENT, mock_key=MOCK_KEY)
        store_v1.seal("state", b"private state from binary v1")

        # "New binary" with different measurement
        store_v2 = SealedStore(db=db, measurement=ALT_MEASUREMENT, mock_key=MOCK_KEY)
        with pytest.raises(SealedDecryptionError):
            store_v2.unseal("state")

    def test_same_measurement_can_unseal(self, db):
        """Same binary (same measurement) can always unseal."""
        s1 = SealedStore(db=db, measurement=MOCK_MEASUREMENT, mock_key=MOCK_KEY)
        s1.seal("key", b"value")

        s2 = SealedStore(db=db, measurement=MOCK_MEASUREMENT, mock_key=MOCK_KEY)
        assert s2.unseal("key") == b"value"

    def test_different_mock_key_cannot_unseal(self, db):
        """Different HMAC key → different sealing key → cannot decrypt."""
        s1 = SealedStore(db=db, measurement=MOCK_MEASUREMENT, mock_key=MOCK_KEY)
        s1.seal("secret", b"classified")

        s2 = SealedStore(db=db, measurement=MOCK_MEASUREMENT, mock_key=ALT_KEY)
        with pytest.raises(SealedDecryptionError):
            s2.unseal("secret")

    def test_measurement_property(self, store):
        assert store.measurement == MOCK_MEASUREMENT


class TestSealOverwrite:
    def test_seal_twice_returns_latest(self, store):
        store.seal("k", b"v1")
        store.seal("k", b"v2")
        assert store.unseal("k") == b"v2"

    def test_multiple_keys_independent(self, store):
        store.seal("a", b"aaa")
        store.seal("b", b"bbb")
        assert store.unseal("a") == b"aaa"
        assert store.unseal("b") == b"bbb"


class TestDeleteExists:
    def test_exists_true_after_seal(self, store):
        store.seal("x", b"data")
        assert store.exists("x") is True

    def test_exists_false_before_seal(self, store):
        assert store.exists("never_sealed") is False

    def test_delete_returns_true(self, store):
        store.seal("d", b"data")
        assert store.delete("d") is True

    def test_delete_removes_entry(self, store):
        store.seal("d", b"data")
        store.delete("d")
        assert store.unseal("d") is None

    def test_delete_nonexistent_does_not_raise(self, store):
        # RocksDB del on missing key is a no-op (no error)
        store.delete("ghost")  # should not raise
        assert store.unseal("ghost") is None

    def test_exists_false_after_delete(self, store):
        store.seal("d", b"data")
        store.delete("d")
        assert store.exists("d") is False


class TestJsonHelpers:
    def test_seal_unseal_json_dict(self, store):
        obj = {"accuracy": 0.97, "epoch": 42, "weights": [1, 2, 3]}
        store.seal_json("model_state", obj)
        restored = store.unseal_json("model_state")
        assert restored == obj

    def test_seal_unseal_json_string(self, store):
        store.seal_json("msg", "hello world")
        assert store.unseal_json("msg") == "hello world"

    def test_seal_unseal_json_none_returns_none(self, store):
        assert store.unseal_json("missing") is None

    def test_seal_unseal_json_wrong_measurement_fails(self, db):
        s1 = SealedStore(db=db, measurement=MOCK_MEASUREMENT, mock_key=MOCK_KEY)
        s1.seal_json("config", {"version": 1})

        s2 = SealedStore(db=db, measurement=ALT_MEASUREMENT, mock_key=MOCK_KEY)
        with pytest.raises(SealedDecryptionError):
            s2.unseal_json("config")


class TestFreshNonce:
    def test_seal_twice_same_key_different_blobs(self, store):
        """Each seal uses a fresh nonce → different ciphertext blobs."""
        store.seal("n", b"same plaintext")
        from subnet.utils.db.database import RocksDB
        # Access raw blob via nmap_get
        blob1 = store._db.nmap_get("sealed", "n")
        store.seal("n", b"same plaintext")
        blob2 = store._db.nmap_get("sealed", "n")
        # Blobs differ because nonces differ
        assert blob1 != blob2
        # But both unseal to the same plaintext
        assert store.unseal("n") == b"same plaintext"


# ------------------------------------------------------------------
# Hardware mode tests (F-05)
# ------------------------------------------------------------------

class TestHardwareModeSealing:
    """F-05: SealedStore with is_mock=False uses measurement directly."""

    def test_hardware_mode_round_trip(self, db):
        """Seal and unseal with is_mock=False."""
        store = SealedStore(db=db, measurement=MOCK_MEASUREMENT, is_mock=False)
        store.seal("hw_key", b"hardware sealed data")
        assert store.unseal("hw_key") == b"hardware sealed data"

    def test_hardware_mode_different_measurement_fails(self, db):
        """Different measurement in hardware mode → cannot unseal."""
        store1 = SealedStore(db=db, measurement=MOCK_MEASUREMENT, is_mock=False)
        store1.seal("hw_key2", b"sealed")

        store2 = SealedStore(db=db, measurement=ALT_MEASUREMENT, is_mock=False)
        with pytest.raises(SealedDecryptionError):
            store2.unseal("hw_key2")

    def test_hardware_mode_ignores_mock_key(self, db):
        """In hardware mode, different mock_key should produce same sealing key."""
        store1 = SealedStore(
            db=db, measurement=MOCK_MEASUREMENT, mock_key=MOCK_KEY, is_mock=False
        )
        store1.seal("hw_key3", b"same key regardless")

        store2 = SealedStore(
            db=db, measurement=MOCK_MEASUREMENT, mock_key=ALT_KEY, is_mock=False
        )
        # Same measurement + is_mock=False → same sealing key, regardless of mock_key
        assert store2.unseal("hw_key3") == b"same key regardless"

    def test_mock_and_hardware_keys_differ(self, db):
        """Mock mode and hardware mode produce different keys for same measurement."""
        store_mock = SealedStore(
            db=db, measurement=MOCK_MEASUREMENT, mock_key=MOCK_KEY, is_mock=True
        )
        store_mock.seal("cross_key", b"mock sealed")

        store_hw = SealedStore(
            db=db, measurement=MOCK_MEASUREMENT, mock_key=MOCK_KEY, is_mock=False
        )
        # Different key derivation path → cannot unseal
        with pytest.raises(SealedDecryptionError):
            store_hw.unseal("cross_key")
