"""
Integration tests for TEE-weighted consensus scoring.

Tests DcapVerifier wired into get_scores() logic (without the full Consensus class,
which requires an async runtime + real chain). We test the scoring formula directly:

    score = int(1e18 * tee_score)  where tee_score ∈ {0.0, 0.5, 1.0}

Covers:
- Mock backend: score = int(0.5e18)
- TEE fail (no quote): node excluded
- TEE fail (debug mode): node excluded
- MIN_TEE_SCORE enforcement: mock score below threshold → excluded
- Multiple peers: independent scoring
"""

import pytest

from subnet.tee.backends.mock import MockBackend
from subnet.tee.config import TeeConfig
from subnet.tee.publisher import TeePublisher
from subnet.tee.quote import TeeBackend, TeeQuote, TcbStatus
from subnet.tee.verifier import DcapVerifier
from subnet.utils.db.database import RocksDB

PEER_ID_A = "12D3KooWKxAhu5U8SreDZpokVkN6ciTBbsHxteo3Vmq6Cpuf8KEt"
PEER_ID_B = "12D3KooWM5J4zS17XR2LHGZgRpmzbeqg4Eibyq8sbRLwRuWxJqsV"
EPOCH = 14_780_500
BASE_SCORE = int(1e18)


@pytest.fixture
def db(tmp_path):
    db_path = str(tmp_path / "consensus_int")
    database = RocksDB(base_path=db_path)
    yield database
    database.store.close()


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
    cfg.allow_shared_hardware = True  # test nodes share a mock backend
    return cfg


@pytest.fixture
def backend(mock_config):
    return MockBackend(key=mock_config.mock_key)


def make_verifier(db, mock_config) -> DcapVerifier:
    return DcapVerifier(db=db, config=mock_config)


class TestScoringFormula:
    def test_mock_tee_score_is_half(self, db, backend, mock_config):
        pub = TeePublisher(db=db, peer_id=PEER_ID_A, backend=backend)
        pub.publish(EPOCH)

        verifier = make_verifier(db, mock_config)
        result = verifier.verify(PEER_ID_A, EPOCH)

        expected_final = int(BASE_SCORE * 0.5)
        assert result.score == 0.5
        assert int(BASE_SCORE * result.score) == expected_final
        assert expected_final == 500_000_000_000_000_000

    def test_missing_quote_excluded(self, db, mock_config):
        verifier = make_verifier(db, mock_config)
        result = verifier.verify(PEER_ID_A, EPOCH)
        assert result.ok is False
        # Node would be excluded from consensus_score_list

    def test_debug_mode_excluded(self, db, mock_config):
        debug_backend = MockBackend(key=mock_config.mock_key, debug_mode=True)
        pub = TeePublisher(db=db, peer_id=PEER_ID_A, backend=debug_backend)
        pub.publish(EPOCH)

        verifier = make_verifier(db, mock_config)
        result = verifier.verify(PEER_ID_A, EPOCH)
        assert result.ok is False
        assert result.rejection_reason == "debug_mode"

    def test_min_tee_score_excludes_mock(self, db, backend):
        """If MIN_TEE_SCORE=1.0, mock backend (0.5) is excluded."""
        pub = TeePublisher(db=db, peer_id=PEER_ID_A, backend=backend)
        pub.publish(EPOCH)

        cfg = TeeConfig.__new__(TeeConfig)
        cfg.backend = TeeBackend.MOCK
        cfg.mock_key = b"mock-tee-dev-key-do-not-use-in-production-!!"
        cfg.expected_measurements = []
        cfg.expected_measurement = ""
        cfg.min_tee_score = 1.0  # require real hardware
        cfg.tcb_strict = True
        cfg.pccs_url = ""
        cfg.allow_shared_hardware = True

        verifier = DcapVerifier(db=db, config=cfg)
        result = verifier.verify(PEER_ID_A, EPOCH)
        # TEE check passes (score=0.5), but 0.5 < 1.0 → consensus excludes node
        assert result.ok is True
        assert result.score == 0.5
        # Simulated consensus gate
        assert result.score < cfg.min_tee_score  # → node excluded

    def test_min_tee_score_zero_includes_mock(self, db, backend, mock_config):
        """MIN_TEE_SCORE=0.0 (default) accepts mock scores."""
        pub = TeePublisher(db=db, peer_id=PEER_ID_A, backend=backend)
        pub.publish(EPOCH)

        verifier = make_verifier(db, mock_config)
        result = verifier.verify(PEER_ID_A, EPOCH)
        assert result.ok is True
        assert result.score >= mock_config.min_tee_score


class TestMultiplePeers:
    def test_both_peers_score_independently(self, db, backend, mock_config):
        pub_a = TeePublisher(db=db, peer_id=PEER_ID_A, backend=backend)
        pub_b = TeePublisher(db=db, peer_id=PEER_ID_B, backend=backend)
        pub_a.publish(EPOCH)
        pub_b.publish(EPOCH)

        verifier = make_verifier(db, mock_config)
        result_a = verifier.verify(PEER_ID_A, EPOCH)
        result_b = verifier.verify(PEER_ID_B, EPOCH)

        assert result_a.ok is True
        assert result_b.ok is True
        assert result_a.score == 0.5
        assert result_b.score == 0.5

    def test_one_peer_missing_quote_other_scores(self, db, backend, mock_config):
        pub_a = TeePublisher(db=db, peer_id=PEER_ID_A, backend=backend)
        pub_a.publish(EPOCH)
        # Peer B never publishes

        verifier = make_verifier(db, mock_config)
        result_a = verifier.verify(PEER_ID_A, EPOCH)
        result_b = verifier.verify(PEER_ID_B, EPOCH)

        assert result_a.ok is True
        assert result_b.ok is False

    def test_stolen_quote_does_not_affect_legitimate_peer(self, db, backend, mock_config):
        """Attacker stores Peer A's quote under Peer B's key — Peer A still scores."""
        from subnet.tee.quote import TEE_QUOTE_TOPIC, dht_key
        pub_a = TeePublisher(db=db, peer_id=PEER_ID_A, backend=backend)
        pub_a.publish(EPOCH)

        # Attacker copies Peer A's quote under Peer B's key
        raw_a = db.nmap_get(TEE_QUOTE_TOPIC, dht_key(EPOCH, PEER_ID_A))
        db.nmap_set(TEE_QUOTE_TOPIC, dht_key(EPOCH, PEER_ID_B), raw_a)

        verifier = make_verifier(db, mock_config)
        # Peer A still scores fine
        result_a = verifier.verify(PEER_ID_A, EPOCH)
        assert result_a.ok is True

        # Peer B's stolen quote fails identity check
        result_b = verifier.verify(PEER_ID_B, EPOCH)
        assert result_b.ok is False
        assert result_b.rejection_reason == "identity_binding_failed"
