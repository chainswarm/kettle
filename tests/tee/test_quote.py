"""
Tests for TeeQuote schema and identity binding.

Covers:
- report_data generation from peer_id + epoch
- verify_identity: correct pair → True
- verify_identity: wrong epoch (replay) → False
- verify_identity: wrong peer_id (Sybil/stolen) → False
- serialisation round-trip (to_bytes / from_bytes)
- to_dict / from_dict round-trip
- dht_key format
"""

import hashlib

import pytest

from subnet.tee.quote import TeeBackend, TeeQuote, TcbStatus, dht_key


PEER_ID = "12D3KooWKxAhu5U8SreDZpokVkN6ciTBbsHxteo3Vmq6Cpuf8KEt"
EPOCH = 14_780_500


class TestReportDataBinding:
    def test_make_report_data_is_64_bytes(self):
        rd = TeeQuote.make_report_data(PEER_ID, EPOCH)
        assert len(rd) == 64

    def test_make_report_data_first_32_is_sha256(self):
        rd = TeeQuote.make_report_data(PEER_ID, EPOCH)
        expected_digest = hashlib.sha256(f"{PEER_ID}:{EPOCH}".encode()).digest()
        assert rd[:32] == expected_digest

    def test_make_report_data_last_32_zero_padded(self):
        rd = TeeQuote.make_report_data(PEER_ID, EPOCH)
        assert rd[32:] == b"\x00" * 32

    def test_make_report_data_hex_is_128_chars(self):
        hex_val = TeeQuote.make_report_data_hex(PEER_ID, EPOCH)
        assert len(hex_val) == 128

    def test_make_report_data_hex_matches_bytes(self):
        rd_bytes = TeeQuote.make_report_data(PEER_ID, EPOCH)
        rd_hex = TeeQuote.make_report_data_hex(PEER_ID, EPOCH)
        assert rd_bytes.hex() == rd_hex

    def test_different_peer_ids_produce_different_report_data(self):
        rd1 = TeeQuote.make_report_data_hex("peer-A", EPOCH)
        rd2 = TeeQuote.make_report_data_hex("peer-B", EPOCH)
        assert rd1 != rd2

    def test_different_epochs_produce_different_report_data(self):
        rd1 = TeeQuote.make_report_data_hex(PEER_ID, EPOCH)
        rd2 = TeeQuote.make_report_data_hex(PEER_ID, EPOCH + 1)
        assert rd1 != rd2


class TestVerifyIdentity:
    def _make_quote(self, peer_id: str, epoch: int) -> TeeQuote:
        return TeeQuote(
            backend=TeeBackend.MOCK,
            measurement="aabbcc",
            report_data=TeeQuote.make_report_data_hex(peer_id, epoch),
            nonce=epoch,
            peer_id=peer_id,
            debug_mode=False,
            tcb_status=TcbStatus.UP_TO_DATE,
            sig="",
        )

    def test_correct_identity_returns_true(self):
        quote = self._make_quote(PEER_ID, EPOCH)
        assert quote.verify_identity(PEER_ID, EPOCH) is True

    def test_replay_wrong_epoch_returns_false(self):
        """Attacker replays a valid quote from a previous epoch."""
        quote = self._make_quote(PEER_ID, EPOCH - 1)  # old epoch
        assert quote.verify_identity(PEER_ID, EPOCH) is False  # validator checks current epoch

    def test_replay_wrong_nonce_returns_false(self):
        """Quote's nonce field doesn't match current epoch."""
        quote = self._make_quote(PEER_ID, EPOCH)
        quote.nonce = EPOCH - 1  # tamper nonce
        assert quote.verify_identity(PEER_ID, EPOCH) is False

    def test_stolen_quote_wrong_peer_id_returns_false(self):
        """Attacker copies another miner's valid quote."""
        thief_peer_id = "12D3KooWM5J4zS17XR2LHGZgRpmzbeqg4Eibyq8sbRLwRuWxJqsV"
        legitimate_quote = self._make_quote(PEER_ID, EPOCH)
        # Thief tries to use the legitimate quote under their own peer_id
        assert legitimate_quote.verify_identity(thief_peer_id, EPOCH) is False

    def test_tampered_report_data_returns_false(self):
        """Attacker modifies the report_data field."""
        quote = self._make_quote(PEER_ID, EPOCH)
        quote.report_data = "ff" * 64  # garbage
        assert quote.verify_identity(PEER_ID, EPOCH) is False


class TestSerialisationRoundTrip:
    def _make_quote(self) -> TeeQuote:
        return TeeQuote(
            backend=TeeBackend.MOCK,
            measurement="deadbeef" * 12,
            report_data=TeeQuote.make_report_data_hex(PEER_ID, EPOCH),
            nonce=EPOCH,
            peer_id=PEER_ID,
            timestamp=1_700_000_000.0,
            debug_mode=False,
            tcb_status=TcbStatus.UP_TO_DATE,
            sig="cafebabe" * 8,
            raw_bytes=None,
        )

    def test_to_bytes_from_bytes_round_trip(self):
        q = self._make_quote()
        restored = TeeQuote.from_bytes(q.to_bytes())
        assert restored.backend == q.backend
        assert restored.measurement == q.measurement
        assert restored.report_data == q.report_data
        assert restored.nonce == q.nonce
        assert restored.peer_id == q.peer_id
        assert restored.debug_mode == q.debug_mode
        assert restored.tcb_status == q.tcb_status
        assert restored.sig == q.sig
        assert restored.raw_bytes is None  # raw_bytes not serialised

    def test_from_bytes_verify_identity_still_works(self):
        q = self._make_quote()
        restored = TeeQuote.from_bytes(q.to_bytes())
        assert restored.verify_identity(PEER_ID, EPOCH) is True

    def test_to_dict_from_dict_round_trip(self):
        q = self._make_quote()
        d = q.to_dict()
        restored = TeeQuote.from_dict(d)
        assert restored.backend == q.backend
        assert restored.nonce == q.nonce
        assert restored.peer_id == q.peer_id

    def test_to_bytes_is_json(self):
        import json
        q = self._make_quote()
        data = json.loads(q.to_bytes().decode())
        assert data["backend"] == "mock"
        assert data["peer_id"] == PEER_ID

    def test_debug_mode_preserved_in_round_trip(self):
        q = TeeQuote(
            backend=TeeBackend.MOCK,
            measurement="aa",
            report_data=TeeQuote.make_report_data_hex(PEER_ID, EPOCH),
            nonce=EPOCH,
            peer_id=PEER_ID,
            debug_mode=True,  # debug enclave
            tcb_status=TcbStatus.UNKNOWN,
            sig="",
        )
        restored = TeeQuote.from_bytes(q.to_bytes())
        assert restored.debug_mode is True


class TestQuoteVersioning:
    """F-10: TeeQuote serialization includes a version field."""

    def test_serialized_quote_has_version(self):
        q = TeeQuote(
            backend=TeeBackend.MOCK,
            measurement="ab" * 24,
            report_data="cd" * 64,
            nonce=1,
            peer_id="test-peer",
        )
        d = q.to_dict()
        assert "version" in d
        assert d["version"] == 1

    def test_from_bytes_accepts_versioned_quote(self):
        q = TeeQuote(
            backend=TeeBackend.MOCK,
            measurement="ab" * 24,
            report_data="cd" * 64,
            nonce=1,
            peer_id="test-peer",
        )
        restored = TeeQuote.from_bytes(q.to_bytes())
        assert restored.version == 1

    def test_from_bytes_accepts_unversioned_quote(self):
        """Backward compat: old quotes without version field default to 1."""
        import json
        old_data = json.dumps({
            "backend": "mock",
            "measurement": "ab" * 24,
            "report_data": "cd" * 64,
            "nonce": 1,
            "peer_id": "test-peer",
            "timestamp": 0.0,
            "debug_mode": False,
            "tcb_status": "Unknown",
            "sig": "",
        }).encode()
        q = TeeQuote.from_bytes(old_data)
        assert q.version == 1

    def test_unknown_version_raises(self):
        import json
        future_data = json.dumps({
            "version": 999,
            "backend": "mock",
            "measurement": "ab" * 24,
            "report_data": "cd" * 64,
            "nonce": 1,
            "peer_id": "test-peer",
            "timestamp": 0.0,
        }).encode()
        with pytest.raises(ValueError, match="unsupported.*version"):
            TeeQuote.from_bytes(future_data)


class TestReportDataWithCertPubkey:
    """F-02: cert pubkey hash bound into upper 32 bytes of report_data."""

    def test_make_report_data_without_pubkey_is_zero_padded(self):
        rd = TeeQuote.make_report_data("peer1", 1)
        assert len(rd) == 64
        assert rd[32:] == b"\x00" * 32

    def test_make_report_data_with_pubkey_fills_upper_bytes(self):
        fake_pubkey = b"fake-public-key-der-bytes"
        rd = TeeQuote.make_report_data("peer1", 1, cert_pubkey_hash=hashlib.sha256(fake_pubkey).digest())
        assert len(rd) == 64
        assert rd[32:] == hashlib.sha256(fake_pubkey).digest()
        expected_lower = hashlib.sha256(b"peer1:1").digest()
        assert rd[:32] == expected_lower

    def test_verify_identity_with_pubkey(self):
        fake_pubkey = b"fake-public-key-der-bytes"
        pubkey_hash = hashlib.sha256(fake_pubkey).digest()
        rd_hex = TeeQuote.make_report_data_hex("peer1", 1, cert_pubkey_hash=pubkey_hash)
        q = TeeQuote(
            backend=TeeBackend.MOCK, measurement="ab" * 24,
            report_data=rd_hex, nonce=1, peer_id="peer1",
        )
        assert q.verify_identity("peer1", 1, cert_pubkey_hash=pubkey_hash) is True
        assert q.verify_identity("peer1", 1, cert_pubkey_hash=None) is False
        assert q.verify_identity("peer1", 1, cert_pubkey_hash=b"\x00" * 32) is False

    def test_old_quote_without_pubkey_still_verifies(self):
        rd_hex = TeeQuote.make_report_data_hex("peer1", 1)
        q = TeeQuote(
            backend=TeeBackend.MOCK, measurement="ab" * 24,
            report_data=rd_hex, nonce=1, peer_id="peer1",
        )
        assert q.verify_identity("peer1", 1) is True

    def test_cert_pubkey_hash_wrong_length_raises(self):
        import pytest as _pytest
        with _pytest.raises(ValueError, match="32 bytes"):
            TeeQuote.make_report_data("peer1", 1, cert_pubkey_hash=b"\x00" * 16)


class TestDhtKey:
    def test_dht_key_format(self):
        key = dht_key(EPOCH, PEER_ID)
        assert key == f"{EPOCH}:{PEER_ID}"

    def test_dht_key_different_epochs_differ(self):
        assert dht_key(EPOCH, PEER_ID) != dht_key(EPOCH + 1, PEER_ID)

    def test_dht_key_different_peers_differ(self):
        assert dht_key(EPOCH, "peer-A") != dht_key(EPOCH, "peer-B")
