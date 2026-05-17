"""Tests for overwatch salt persistence (F-06) and evidence storage (F-19)."""
import json
import os
import pytest
from unittest.mock import MagicMock

from subnet.tee.backends.mock import MOCK_MEASUREMENT
from subnet.tee.sealed.store import SealedStore
from subnet.utils.db.database import RocksDB


@pytest.fixture
def db(tmp_path):
    database = RocksDB(base_path=str(tmp_path / "test_overwatch"))
    yield database
    database.store.close()


@pytest.fixture
def sealed_store(db):
    return SealedStore(db=db, measurement=MOCK_MEASUREMENT)


class TestOverwatchSaltPersistence:
    def test_salt_stored_and_recoverable(self, sealed_store):
        from subnet.consensus.chain_overwatch_reporter import _make_salt_key
        epoch, peer_id = 5, "12D3KooWtest"
        key = _make_salt_key(epoch, peer_id)
        salt = os.urandom(32)
        sealed_store.seal(key, salt)
        recovered = sealed_store.unseal(key)
        assert recovered == salt

    def test_salt_key_format(self):
        from subnet.consensus.chain_overwatch_reporter import _make_salt_key
        key = _make_salt_key(5, "12D3KooWtest")
        assert key == "overwatch_salt:5:12D3KooWtest"


class TestOverwatchEvidenceStorage:
    """F-19: slash() stores evidence in SealedStore when evidence is provided."""

    def test_evidence_stored_and_recoverable(self, sealed_store):
        """Evidence dict is serialized to JSON and recoverable via unseal()."""
        from subnet.consensus.chain_overwatch_reporter import ChainOverwatchReporter

        ht = MagicMock()
        ht.commit_overwatch_subnet_weights.return_value = MagicMock(is_success=True)
        ht.reveal_overwatch_subnet_weights.return_value = MagicMock(is_success=True)

        reporter = ChainOverwatchReporter(
            ht, overwatch_node_id=1, subnet_id=1, sealed_store=sealed_store
        )

        epoch = 99
        peer_id = "12D3KooWEvidence"
        evidence = {"n": 42, "claimed": "odd", "expected": "even"}

        reporter.slash(peer_id, epoch, evidence=evidence)

        evidence_key = f"overwatch_evidence:{epoch}:{peer_id}"
        raw = sealed_store.unseal(evidence_key)
        assert raw is not None
        recovered = json.loads(raw.decode())
        assert recovered == evidence

    def test_no_evidence_nothing_stored(self, sealed_store):
        """When evidence=None, no evidence key is written to the store."""
        from subnet.consensus.chain_overwatch_reporter import ChainOverwatchReporter

        ht = MagicMock()
        ht.commit_overwatch_subnet_weights.return_value = MagicMock(is_success=True)
        ht.reveal_overwatch_subnet_weights.return_value = MagicMock(is_success=True)

        reporter = ChainOverwatchReporter(
            ht, overwatch_node_id=1, subnet_id=1, sealed_store=sealed_store
        )

        epoch = 100
        peer_id = "12D3KooWNoEvidence"

        reporter.slash(peer_id, epoch, evidence=None)

        evidence_key = f"overwatch_evidence:{epoch}:{peer_id}"
        assert sealed_store.unseal(evidence_key) is None

    def test_evidence_stored_without_sealed_store(self):
        """When sealed_store=None, evidence is silently ignored (no error)."""
        from subnet.consensus.chain_overwatch_reporter import ChainOverwatchReporter

        ht = MagicMock()
        ht.commit_overwatch_subnet_weights.return_value = MagicMock(is_success=True)
        ht.reveal_overwatch_subnet_weights.return_value = MagicMock(is_success=True)

        reporter = ChainOverwatchReporter(
            ht, overwatch_node_id=1, subnet_id=1, sealed_store=None
        )

        evidence = {"n": 7, "claimed": "even", "expected": "odd"}
        # Should not raise
        reporter.slash("12D3KooWPeer", epoch=5, evidence=evidence)
