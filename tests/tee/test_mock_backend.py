"""
Tests for MockBackend.

Covers:
- Quote generated with correct identity binding
- HMAC signature is valid
- Tampered measurement → sig invalid
- Tampered report_data → sig invalid
- Debug mode flag propagated
- Different keys produce different (incompatible) signatures
- Round-trip: generate → serialise → deserialise → verify_identity
"""

import pytest

from subnet.tee.backends.mock import MOCK_MEASUREMENT, MockBackend
from subnet.tee.quote import TeeBackend, TeeQuote


PEER_ID = "12D3KooWKxAhu5U8SreDZpokVkN6ciTBbsHxteo3Vmq6Cpuf8KEt"
EPOCH = 14_780_500

ANOTHER_PEER = "12D3KooWM5J4zS17XR2LHGZgRpmzbeqg4Eibyq8sbRLwRuWxJqsV"


@pytest.fixture
def backend():
    return MockBackend()


class TestMockBackendGenerate:
    def test_backend_name(self, backend):
        assert backend.backend_name == "mock"

    def test_quote_backend_field(self, backend):
        q = backend.generate_quote(PEER_ID, EPOCH)
        assert q.backend == TeeBackend.MOCK

    def test_quote_has_correct_nonce(self, backend):
        q = backend.generate_quote(PEER_ID, EPOCH)
        assert q.nonce == EPOCH

    def test_quote_has_correct_peer_id(self, backend):
        q = backend.generate_quote(PEER_ID, EPOCH)
        assert q.peer_id == PEER_ID

    def test_quote_has_correct_measurement(self, backend):
        q = backend.generate_quote(PEER_ID, EPOCH)
        assert q.measurement == MOCK_MEASUREMENT

    def test_identity_binding_correct(self, backend):
        q = backend.generate_quote(PEER_ID, EPOCH)
        assert q.verify_identity(PEER_ID, EPOCH) is True

    def test_report_data_matches_schema(self, backend):
        q = backend.generate_quote(PEER_ID, EPOCH)
        expected = TeeQuote.make_report_data_hex(PEER_ID, EPOCH)
        assert q.report_data == expected

    def test_not_debug_mode_by_default(self, backend):
        q = backend.generate_quote(PEER_ID, EPOCH)
        assert q.debug_mode is False

    def test_debug_mode_backend(self):
        debug_backend = MockBackend(debug_mode=True)
        q = debug_backend.generate_quote(PEER_ID, EPOCH)
        assert q.debug_mode is True

    def test_sig_is_non_empty(self, backend):
        q = backend.generate_quote(PEER_ID, EPOCH)
        assert len(q.sig) == 64  # HMAC-SHA256 = 32 bytes = 64 hex chars


class TestMockBackendVerifySig:
    def test_valid_sig_passes(self, backend):
        q = backend.generate_quote(PEER_ID, EPOCH)
        assert backend.verify_sig(q) is True

    def test_tampered_measurement_fails(self, backend):
        q = backend.generate_quote(PEER_ID, EPOCH)
        q.measurement = "00" * 32  # tamper
        assert backend.verify_sig(q) is False

    def test_tampered_report_data_fails(self, backend):
        q = backend.generate_quote(PEER_ID, EPOCH)
        q.report_data = "ff" * 64  # tamper
        assert backend.verify_sig(q) is False

    def test_tampered_sig_fails(self, backend):
        q = backend.generate_quote(PEER_ID, EPOCH)
        q.sig = "00" * 32  # tamper
        assert backend.verify_sig(q) is False

    def test_wrong_key_fails(self, backend):
        q = backend.generate_quote(PEER_ID, EPOCH)
        other_backend = MockBackend(key=b"different-key")
        assert other_backend.verify_sig(q) is False

    def test_quote_for_different_peer_fails_identity(self, backend):
        """Quote generated for PEER_ID cannot be used by ANOTHER_PEER."""
        q = backend.generate_quote(PEER_ID, EPOCH)
        assert q.verify_identity(ANOTHER_PEER, EPOCH) is False

    def test_quote_for_different_epoch_fails_identity(self, backend):
        """Quote generated for EPOCH cannot be replayed at EPOCH+1."""
        q = backend.generate_quote(PEER_ID, EPOCH)
        assert q.verify_identity(PEER_ID, EPOCH + 1) is False


class TestMockBackendRoundTrip:
    def test_generate_serialise_deserialise_verify(self, backend):
        """Full round-trip: generate → DHT bytes → restore → verify."""
        q = backend.generate_quote(PEER_ID, EPOCH)
        restored = TeeQuote.from_bytes(q.to_bytes())

        # Identity still valid after round-trip
        assert restored.verify_identity(PEER_ID, EPOCH) is True

        # Sig still valid after round-trip
        assert backend.verify_sig(restored) is True

    def test_custom_measurement(self):
        custom = "custom-measurement-hex-" + "0" * 50
        b = MockBackend(measurement=custom)
        q = b.generate_quote(PEER_ID, EPOCH)
        assert q.measurement == custom
        assert b.verify_sig(q) is True

    def test_two_quotes_same_params_different_timestamps(self, backend):
        """Each quote has a fresh timestamp; both valid."""
        q1 = backend.generate_quote(PEER_ID, EPOCH)
        q2 = backend.generate_quote(PEER_ID, EPOCH)
        assert q1.verify_identity(PEER_ID, EPOCH)
        assert q2.verify_identity(PEER_ID, EPOCH)
        # Sigs are identical because inputs are identical (deterministic HMAC)
        assert q1.sig == q2.sig
