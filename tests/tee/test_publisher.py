"""
Tests for TeePublisher.

Covers:
- publish() writes quote to DHT
- get_published_quote() retrieves it back
- published quote passes verify_identity
- published quote sig is valid
- missing quote returns None
- republish same epoch overwrites
- last_published_epoch tracking
"""

import tempfile
import os

import pytest

from subnet.tee.backends.mock import MockBackend
from subnet.tee.publisher import TeePublisher
from subnet.tee.quote import TEE_QUOTE_TOPIC, TeeQuote, dht_key
from subnet.utils.db.database import RocksDB


PEER_ID = "12D3KooWKxAhu5U8SreDZpokVkN6ciTBbsHxteo3Vmq6Cpuf8KEt"
EPOCH = 14_780_500


@pytest.fixture
def db(tmp_path):
    db_path = str(tmp_path / "test_tee")
    database = RocksDB(base_path=db_path)
    yield database
    database.store.close()


@pytest.fixture
def backend():
    return MockBackend()


@pytest.fixture
def publisher(db, backend):
    return TeePublisher(db=db, peer_id=PEER_ID, backend=backend)


class TestTeePublisherPublish:
    def test_publish_returns_quote(self, publisher):
        q = publisher.publish(EPOCH)
        assert isinstance(q, TeeQuote)

    def test_published_quote_is_in_dht(self, publisher, db):
        publisher.publish(EPOCH)
        key = dht_key(EPOCH, PEER_ID)
        raw = db.nmap_get(TEE_QUOTE_TOPIC, key)
        assert raw is not None

    def test_published_quote_deserialises(self, publisher, db):
        publisher.publish(EPOCH)
        key = dht_key(EPOCH, PEER_ID)
        raw = db.nmap_get(TEE_QUOTE_TOPIC, key)
        q = TeeQuote.from_bytes(raw)
        assert q.peer_id == PEER_ID
        assert q.nonce == EPOCH

    def test_published_quote_passes_identity_check(self, publisher):
        q = publisher.publish(EPOCH)
        assert q.verify_identity(PEER_ID, EPOCH) is True

    def test_published_quote_sig_valid(self, publisher, backend):
        q = publisher.publish(EPOCH)
        assert backend.verify_sig(q) is True

    def test_last_published_epoch_updated(self, publisher):
        assert publisher.last_published_epoch is None
        publisher.publish(EPOCH)
        assert publisher.last_published_epoch == EPOCH

    def test_publish_different_epochs(self, publisher, db):
        publisher.publish(EPOCH)
        publisher.publish(EPOCH + 1)

        key1 = dht_key(EPOCH, PEER_ID)
        key2 = dht_key(EPOCH + 1, PEER_ID)

        q1 = TeeQuote.from_bytes(db.nmap_get(TEE_QUOTE_TOPIC, key1))
        q2 = TeeQuote.from_bytes(db.nmap_get(TEE_QUOTE_TOPIC, key2))

        assert q1.nonce == EPOCH
        assert q2.nonce == EPOCH + 1
        assert q1.verify_identity(PEER_ID, EPOCH)
        assert q2.verify_identity(PEER_ID, EPOCH + 1)

    def test_republish_same_epoch_overwrites(self, publisher, db):
        q1 = publisher.publish(EPOCH)
        q2 = publisher.publish(EPOCH)

        key = dht_key(EPOCH, PEER_ID)
        stored = TeeQuote.from_bytes(db.nmap_get(TEE_QUOTE_TOPIC, key))

        # Both sigs should be identical (deterministic HMAC, same inputs)
        assert stored.sig == q1.sig == q2.sig
        assert stored.verify_identity(PEER_ID, EPOCH)


class TestTeePublisherGetPublishedQuote:
    def test_get_published_quote_returns_quote(self, publisher):
        publisher.publish(EPOCH)
        q = publisher.get_published_quote(EPOCH)
        assert q is not None
        assert q.nonce == EPOCH

    def test_get_published_quote_missing_returns_none(self, publisher):
        q = publisher.get_published_quote(EPOCH + 999)
        assert q is None

    def test_get_published_quote_after_round_trip(self, publisher, backend):
        publisher.publish(EPOCH)
        q = publisher.get_published_quote(EPOCH)
        assert q is not None
        assert backend.verify_sig(q) is True
        assert q.verify_identity(PEER_ID, EPOCH) is True


class TestTeePublisherMultiplePeers:
    def test_two_peers_store_independently(self, db, backend):
        """Two miners publish quotes to the same DHT without collision."""
        peer_a = "12D3KooWKxAhu5U8SreDZpokVkN6ciTBbsHxteo3Vmq6Cpuf8KEt"
        peer_b = "12D3KooWM5J4zS17XR2LHGZgRpmzbeqg4Eibyq8sbRLwRuWxJqsV"

        pub_a = TeePublisher(db=db, peer_id=peer_a, backend=backend)
        pub_b = TeePublisher(db=db, peer_id=peer_b, backend=backend)

        pub_a.publish(EPOCH)
        pub_b.publish(EPOCH)

        qa = TeeQuote.from_bytes(db.nmap_get(TEE_QUOTE_TOPIC, dht_key(EPOCH, peer_a)))
        qb = TeeQuote.from_bytes(db.nmap_get(TEE_QUOTE_TOPIC, dht_key(EPOCH, peer_b)))

        assert qa.peer_id == peer_a
        assert qb.peer_id == peer_b
        assert qa.verify_identity(peer_a, EPOCH)
        assert qb.verify_identity(peer_b, EPOCH)

        # Cross-check: A's quote does not validate as B's identity
        assert not qa.verify_identity(peer_b, EPOCH)
        assert not qb.verify_identity(peer_a, EPOCH)
