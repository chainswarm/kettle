"""
Tests for F-03: GossipSub DHT write authentication.

Verifies that the gossip receiver rejects messages where the internal
peer_id doesn't match the GossipSub sender (from_peer).
"""

import base64
import json
import tempfile
from dataclasses import dataclass
from unittest.mock import MagicMock

import pytest

from subnet.tee.backends.mock import MockBackend, MOCK_MEASUREMENT
from subnet.tee.quote import TeeQuote, TeeBackend, TcbStatus, TEE_QUOTE_TOPIC, RATLS_CERT_TOPIC
from subnet.tee.ratls.cert import generate_ratls_cert
from subnet.tee.ratls.envelope import OutputEnvelope
from subnet.tee.ratls.session import RaTlsSession
from subnet.utils.db.database import RocksDB

PEER_A = "12D3KooWKxAhu5U8SreDZpokVkN6ciTBbsHxteo3Vmq6Cpuf8KEt"
PEER_B = "12D3KooWM5J4zS17XR2LHGZgRpmzbeqg4Eibyq8sbRLwRuWxJqsV"
EPOCH = 42
MOCK_KEY = b"mock-tee-dev-key-do-not-use-in-production-!!"
_WORK_TOPIC = "mock_work"


@pytest.fixture
def db(tmp_path):
    database = RocksDB(base_path=str(tmp_path / "gossip_test"))
    yield database
    database.store.close()


@pytest.fixture
def backend():
    return MockBackend(key=MOCK_KEY)


@pytest.fixture
def receiver(db):
    """Create a GossipReceiver for testing."""
    from subnet.utils.gossipsub.gossip_receiver import GossipReceiver
    import trio

    return GossipReceiver(
        gossipsub=MagicMock(),
        pubsub=MagicMock(),
        termination_event=trio.Event(),
        db=db,
        topics=[TEE_QUOTE_TOPIC, RATLS_CERT_TOPIC, _WORK_TOPIC],
    )


def make_gossip_message(from_peer: str, topic: str, data: bytes):
    """Create a mock GossipSub message."""
    msg = MagicMock()
    # py-libp2p encodes peer ID as bytes in from_id
    import base58
    msg.from_id = base58.b58decode(from_peer)
    msg.topicIDs = [topic]
    msg.data = data
    return msg


class TestTeeQuoteValidation:
    """F-03: TEE quote gossip must have matching peer_id."""

    @pytest.mark.trio
    async def test_honest_quote_accepted(self, receiver, db, backend):
        """Quote from peer A with peer_id=A should be stored."""
        quote = backend.generate_quote(peer_id=PEER_A, epoch=EPOCH)
        msg = make_gossip_message(PEER_A, TEE_QUOTE_TOPIC, quote.to_bytes())
        await receiver._handle_message(msg)

        stored = db.nmap_get(TEE_QUOTE_TOPIC, f"{EPOCH}:{PEER_A}")
        assert stored is not None

    @pytest.mark.trio
    async def test_spoofed_quote_rejected(self, receiver, db, backend):
        """Quote claiming peer_id=A but sent by peer B should be rejected."""
        quote = backend.generate_quote(peer_id=PEER_A, epoch=EPOCH)
        msg = make_gossip_message(PEER_B, TEE_QUOTE_TOPIC, quote.to_bytes())
        await receiver._handle_message(msg)

        # Should NOT be stored under peer B's key
        stored_b = db.nmap_get(TEE_QUOTE_TOPIC, f"{EPOCH}:{PEER_B}")
        assert stored_b is None

        # And definitely not under peer A's key
        stored_a = db.nmap_get(TEE_QUOTE_TOPIC, f"{EPOCH}:{PEER_A}")
        assert stored_a is None


class TestWorkRecordValidation:
    """F-03: Work record gossip must have matching peer_id."""

    @pytest.mark.trio
    async def test_honest_work_accepted(self, receiver, db, backend):
        """Work record from peer A with peer_id=A should be stored."""
        session = RaTlsSession(
            cert_public_key_der=b"fake-key-for-test", peer_id=PEER_A, epoch=EPOCH
        )
        work = json.dumps({"epoch": EPOCH, "peer_id": PEER_A, "n": 42, "parity": "even"}).encode()
        env = OutputEnvelope.create(request_id="req:1", output=work, session=session)
        msg = make_gossip_message(PEER_A, _WORK_TOPIC, env.to_bytes())
        await receiver._handle_message(msg)

        stored = db.nmap_get(_WORK_TOPIC, f"{EPOCH}:{PEER_A}")
        assert stored is not None

    @pytest.mark.trio
    async def test_spoofed_work_rejected(self, receiver, db, backend):
        """Work record claiming peer_id=A but sent by peer B should be rejected."""
        session = RaTlsSession(
            cert_public_key_der=b"fake-key-for-test", peer_id=PEER_A, epoch=EPOCH
        )
        work = json.dumps({"epoch": EPOCH, "peer_id": PEER_A, "n": 42, "parity": "even"}).encode()
        env = OutputEnvelope.create(request_id="req:1", output=work, session=session)
        msg = make_gossip_message(PEER_B, _WORK_TOPIC, env.to_bytes())
        await receiver._handle_message(msg)

        stored = db.nmap_get(_WORK_TOPIC, f"{EPOCH}:{PEER_B}")
        assert stored is None


class TestRaTlsCertValidation:
    """F-03: RA-TLS cert gossip must have matching peer_id in embedded quote."""

    @pytest.mark.trio
    async def test_honest_cert_accepted(self, receiver, db, backend):
        """Cert with embedded quote peer_id=A sent by peer A should be stored."""
        quote = backend.generate_quote(peer_id=PEER_A, epoch=EPOCH)
        bundle = generate_ratls_cert(quote)
        payload = json.dumps({
            "epoch": EPOCH,
            "cert": base64.b64encode(bundle.cert_pem).decode(),
        }).encode()
        msg = make_gossip_message(PEER_A, RATLS_CERT_TOPIC, payload)
        await receiver._handle_message(msg)

        stored = db.nmap_get(RATLS_CERT_TOPIC, f"{EPOCH}:{PEER_A}")
        assert stored is not None

    @pytest.mark.trio
    async def test_spoofed_cert_rejected(self, receiver, db, backend):
        """Cert with embedded quote peer_id=A sent by peer B should be rejected."""
        quote = backend.generate_quote(peer_id=PEER_A, epoch=EPOCH)
        bundle = generate_ratls_cert(quote)
        payload = json.dumps({
            "epoch": EPOCH,
            "cert": base64.b64encode(bundle.cert_pem).decode(),
        }).encode()
        msg = make_gossip_message(PEER_B, RATLS_CERT_TOPIC, payload)
        await receiver._handle_message(msg)

        stored = db.nmap_get(RATLS_CERT_TOPIC, f"{EPOCH}:{PEER_B}")
        assert stored is None


# ── F-20: GossipReceiver epoch-based cleanup ──────────────────────────────────

class TestGossipReceiverCleanup:
    """F-20: cleanup_old_epochs removes stale in-memory seen-set entries."""

    def _make_receiver(self):
        from subnet.utils.gossipsub.gossip_receiver import GossipReceiver
        import trio
        r = GossipReceiver(
            gossipsub=MagicMock(),
            pubsub=MagicMock(),
            termination_event=trio.Event(),
            db=MagicMock(),
            topics=[],
        )
        return r

    def test_cleanup_removes_old_entries(self):
        """Entries for epochs before cutoff are removed; recent ones are kept."""
        r = self._make_receiver()
        # Populate seen-sets with entries across epochs 1–5
        for epoch in range(1, 6):
            r._seen_heartbeats.add(f"{epoch}:{PEER_A}")
            r._seen_tee_quotes.add(f"{epoch}:{PEER_A}")
            r._seen_ratls_certs.add(f"{epoch}:{PEER_A}")
            r._seen_work_records.add(f"{epoch}:{PEER_A}")

        # current_epoch=5, keep_epochs=3 → cutoff=2 → remove epochs 1 (< 2)
        removed = r.cleanup_old_epochs(current_epoch=5)

        # epoch 1 removed from all 4 sets = 4 entries
        assert removed == 4
        for seen_set in (r._seen_heartbeats, r._seen_tee_quotes,
                         r._seen_ratls_certs, r._seen_work_records):
            assert f"1:{PEER_A}" not in seen_set
            assert f"2:{PEER_A}" in seen_set
            assert f"5:{PEER_A}" in seen_set

    def test_cleanup_returns_zero_when_nothing_old(self):
        """Returns 0 when all entries are within the keep window."""
        r = self._make_receiver()
        for epoch in (10, 11, 12):
            r._seen_heartbeats.add(f"{epoch}:{PEER_A}")

        removed = r.cleanup_old_epochs(current_epoch=12)
        assert removed == 0
        assert len(r._seen_heartbeats) == 3

    def test_cleanup_empty_sets_returns_zero(self):
        """No error and returns 0 when all seen-sets are empty."""
        r = self._make_receiver()
        assert r.cleanup_old_epochs(current_epoch=100) == 0

    def test_keep_epochs_default_is_three(self):
        """Default _keep_epochs is 3."""
        r = self._make_receiver()
        assert r._keep_epochs == 3

    def test_cleanup_multiple_peers(self):
        """Old entries from multiple peers are all removed."""
        r = self._make_receiver()
        peers = [PEER_A, PEER_B, "12D3KooWExtra"]
        for epoch in (1, 2, 5, 6):
            for peer in peers:
                r._seen_heartbeats.add(f"{epoch}:{peer}")

        # current_epoch=6, cutoff=3 → remove epochs 1, 2
        removed = r.cleanup_old_epochs(current_epoch=6)

        assert removed == 2 * len(peers)  # epochs 1 and 2, each with 3 peers
        for peer in peers:
            assert f"1:{peer}" not in r._seen_heartbeats
            assert f"2:{peer}" not in r._seen_heartbeats
            assert f"5:{peer}" in r._seen_heartbeats
            assert f"6:{peer}" in r._seen_heartbeats
