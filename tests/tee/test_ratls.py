"""
Tests for RA-TLS: cert generation, quote extraction, verification, session keys.

Covers:
- RaTlsCert: quote embedded correctly, extractable, round-trip
- RaTlsClient: valid cert → ok, score=0.5 (mock)
- RaTlsClient: debug mode cert → REJECT
- RaTlsClient: wrong peer_id → REJECT (identity binding)
- RaTlsClient: wrong epoch → REJECT (nonce mismatch)
- RaTlsClient: tampered quote sig → REJECT (chain verification)
- RaTlsClient: missing extension → REJECT
- RaTlsServer: generates cert with quote, creates session
- RaTlsSession: encrypt/decrypt round-trip
- RaTlsSession: sign/verify output
- RaTlsSession: tampered output → verify_signature False
- RaTlsSession: different epoch → different session key
- RaTlsSession: different peer_id → different session key
- Miner+Validator: both derive the same session key from the same cert
"""

import json

import pytest

from subnet.tee.backends.mock import MockBackend, MOCK_MEASUREMENT
from subnet.tee.config import TeeConfig
from subnet.tee.quote import TeeBackend, TeeQuote, TcbStatus
from subnet.tee.ratls import (
    RaTlsCertBundle,
    RaTlsClient,
    RaTlsServer,
    RaTlsSession,
    TEE_QUOTE_OID,
    extract_quote_from_cert,
    generate_ratls_cert,
    get_cert_public_key_bytes,
    RaTlsExtensionMissingError,
)

PEER_ID = "12D3KooWKxAhu5U8SreDZpokVkN6ciTBbsHxteo3Vmq6Cpuf8KEt"
ANOTHER_PEER = "12D3KooWM5J4zS17XR2LHGZgRpmzbeqg4Eibyq8sbRLwRuWxJqsV"
EPOCH = 14_780_500

MOCK_KEY = b"mock-tee-dev-key-do-not-use-in-production-!!"


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
def quote(backend):
    return backend.generate_quote(PEER_ID, EPOCH)


@pytest.fixture
def bundle(backend):
    """Generate a cert bundle via RaTlsServer (F-02: pubkey bound in report_data)."""
    server = RaTlsServer(peer_id=PEER_ID, epoch=EPOCH, backend=backend)
    return server.cert_bundle


# ------------------------------------------------------------------
# RaTlsCert — generation and extraction
# ------------------------------------------------------------------

class TestRaTlsCertGeneration:
    def test_bundle_has_cert_pem(self, bundle):
        assert bundle.cert_pem.startswith(b"-----BEGIN CERTIFICATE-----")

    def test_bundle_has_key_pem(self, bundle):
        assert bundle.key_pem.startswith(b"-----BEGIN")

    def test_bundle_quote_is_tee_quote(self, bundle):
        assert isinstance(bundle.quote, TeeQuote)

    def test_cert_contains_tee_quote_extension(self, bundle):
        from cryptography import x509
        cert = x509.load_pem_x509_certificate(bundle.cert_pem)
        ext = cert.extensions.get_extension_for_oid(TEE_QUOTE_OID)
        assert ext is not None

    def test_extract_quote_round_trip(self, bundle):
        extracted = extract_quote_from_cert(bundle.cert_pem)
        assert extracted.peer_id == bundle.quote.peer_id
        assert extracted.nonce == bundle.quote.nonce
        assert extracted.report_data == bundle.quote.report_data
        assert extracted.backend == bundle.quote.backend

    def test_extract_quote_identity_still_valid(self, bundle):
        import hashlib
        extracted = extract_quote_from_cert(bundle.cert_pem)
        pub_key_der = get_cert_public_key_bytes(bundle.cert_pem)
        cert_pubkey_hash = hashlib.sha256(pub_key_der).digest()
        assert extracted.verify_identity(PEER_ID, EPOCH, cert_pubkey_hash=cert_pubkey_hash) is True

    def test_missing_extension_raises(self):
        """A regular (non-RA-TLS) cert raises RaTlsExtensionMissingError."""
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import ec
        from cryptography.x509.oid import NameOID
        import datetime

        key = ec.generate_private_key(ec.SECP256R1())
        subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "regular-cert")])
        now = datetime.datetime.now(datetime.timezone.utc)
        cert = (
            x509.CertificateBuilder()
            .subject_name(subject)
            .issuer_name(subject)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now)
            .not_valid_after(now + datetime.timedelta(hours=1))
            .sign(key, hashes.SHA256())
        )
        cert_pem = cert.public_bytes(serialization.Encoding.PEM)
        with pytest.raises(RaTlsExtensionMissingError):
            extract_quote_from_cert(cert_pem)

    def test_get_cert_public_key_bytes(self, bundle):
        pub_key = get_cert_public_key_bytes(bundle.cert_pem)
        assert len(pub_key) > 0
        assert isinstance(pub_key, bytes)


# ------------------------------------------------------------------
# RaTlsServer
# ------------------------------------------------------------------

class TestRaTlsServer:
    def test_server_generates_bundle(self, backend):
        server = RaTlsServer(peer_id=PEER_ID, epoch=EPOCH, backend=backend)
        bundle = server.cert_bundle
        assert isinstance(bundle, RaTlsCertBundle)

    def test_server_bundle_lazy_generation(self, backend):
        server = RaTlsServer(peer_id=PEER_ID, epoch=EPOCH, backend=backend)
        assert server._bundle is None
        _ = server.cert_bundle
        assert server._bundle is not None

    def test_server_makes_session(self, backend):
        server = RaTlsServer(peer_id=PEER_ID, epoch=EPOCH, backend=backend)
        session = server.make_session()
        assert isinstance(session, RaTlsSession)
        assert session.peer_id == PEER_ID
        assert session.epoch == EPOCH

    def test_server_makes_ssl_context(self, backend):
        import ssl
        server = RaTlsServer(peer_id=PEER_ID, epoch=EPOCH, backend=backend)
        ctx = server.make_ssl_context()
        assert isinstance(ctx, ssl.SSLContext)


# ------------------------------------------------------------------
# RaTlsClient — verify_cert
# ------------------------------------------------------------------

class TestRaTlsClientValid:
    def test_valid_cert_ok(self, bundle, mock_config):
        client = RaTlsClient(config=mock_config)
        result = client.verify_cert(bundle.cert_pem, PEER_ID, EPOCH)
        assert result.ok is True

    def test_valid_cert_score_half(self, bundle, mock_config):
        client = RaTlsClient(config=mock_config)
        result = client.verify_cert(bundle.cert_pem, PEER_ID, EPOCH)
        assert result.score == 0.5

    def test_valid_cert_session_derived(self, bundle, mock_config):
        client = RaTlsClient(config=mock_config)
        result = client.verify_cert(bundle.cert_pem, PEER_ID, EPOCH)
        assert result.session is not None
        assert isinstance(result.session, RaTlsSession)

    def test_valid_cert_quote_embedded(self, bundle, mock_config):
        client = RaTlsClient(config=mock_config)
        result = client.verify_cert(bundle.cert_pem, PEER_ID, EPOCH)
        assert result.quote is not None
        assert result.quote.peer_id == PEER_ID


class TestRaTlsClientRejectDebugMode:
    def test_debug_mode_cert_rejected(self, mock_config):
        debug_backend = MockBackend(key=MOCK_KEY, debug_mode=True)
        server = RaTlsServer(peer_id=PEER_ID, epoch=EPOCH, backend=debug_backend)
        debug_bundle = server.cert_bundle

        client = RaTlsClient(config=mock_config)
        result = client.verify_cert(debug_bundle.cert_pem, PEER_ID, EPOCH)
        assert result.ok is False
        assert result.rejection_reason == "debug_mode"


class TestRaTlsClientRejectWrongPeer:
    def test_wrong_peer_id_rejected(self, mock_config):
        """Cert generated for PEER_ID but validator checks ANOTHER_PEER."""
        backend = MockBackend(key=MOCK_KEY)
        server = RaTlsServer(peer_id=PEER_ID, epoch=EPOCH, backend=backend)
        bundle = server.cert_bundle

        client = RaTlsClient(config=mock_config)
        result = client.verify_cert(bundle.cert_pem, ANOTHER_PEER, EPOCH)
        assert result.ok is False
        assert result.rejection_reason == "identity_binding_failed"


class TestRaTlsClientRejectWrongEpoch:
    def test_old_epoch_cert_rejected(self, mock_config):
        """Cert generated for EPOCH-1 is rejected when validator checks EPOCH."""
        backend = MockBackend(key=MOCK_KEY)
        server = RaTlsServer(peer_id=PEER_ID, epoch=EPOCH - 1, backend=backend)
        old_bundle = server.cert_bundle

        client = RaTlsClient(config=mock_config)
        result = client.verify_cert(old_bundle.cert_pem, PEER_ID, EPOCH)
        assert result.ok is False
        assert "nonce_mismatch" in result.rejection_reason


class TestRaTlsClientRejectTamperedSig:
    def test_tampered_sig_rejected(self, bundle, mock_config):
        """Tamper the embedded quote sig → chain_verification_failed."""
        import hashlib as _hashlib
        from cryptography.hazmat.primitives.asymmetric import ec as _ec

        quote = extract_quote_from_cert(bundle.cert_pem)
        quote.sig = "00" * 32  # tamper

        # Rebuild cert with a new key; the quote's report_data still binds
        # to the old key, so the pubkey check will fail first.
        # Instead, build with same key approach: generate a new key, embed the
        # tampered-sig quote with the new key's pubkey hash in report_data
        # so the pubkey check passes but the sig check fails.
        new_key = _ec.generate_private_key(_ec.SECP256R1())
        from cryptography.hazmat.primitives import serialization as _ser
        pub_der = new_key.public_key().public_bytes(
            encoding=_ser.Encoding.DER, format=_ser.PublicFormat.SubjectPublicKeyInfo,
        )
        new_pubkey_hash = _hashlib.sha256(pub_der).digest()
        # Rewrite report_data with new pubkey hash (keeps identity lower 32)
        identity_lower = bytes.fromhex(quote.report_data)[:32]
        quote.report_data = (identity_lower + new_pubkey_hash).hex()
        tampered_bundle = generate_ratls_cert(quote, private_key=new_key)

        client = RaTlsClient(config=mock_config)
        result = client.verify_cert(tampered_bundle.cert_pem, PEER_ID, EPOCH)
        assert result.ok is False
        assert "chain_verification_failed" in result.rejection_reason

    def test_missing_extension_cert_rejected(self, mock_config):
        """A cert without the TEE_QUOTE_OID extension is rejected."""
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes, serialization
        from cryptography.hazmat.primitives.asymmetric import ec
        from cryptography.x509.oid import NameOID
        import datetime

        key = ec.generate_private_key(ec.SECP256R1())
        subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "no-quote")])
        now = datetime.datetime.now(datetime.timezone.utc)
        cert = (
            x509.CertificateBuilder()
            .subject_name(subject)
            .issuer_name(subject)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now)
            .not_valid_after(now + datetime.timedelta(hours=1))
            .sign(key, hashes.SHA256())
        )
        plain_cert_pem = cert.public_bytes(serialization.Encoding.PEM)

        client = RaTlsClient(config=mock_config)
        result = client.verify_cert(plain_cert_pem, PEER_ID, EPOCH)
        assert result.ok is False
        assert "missing_extension" in result.rejection_reason


# ------------------------------------------------------------------
# RaTlsSession — encrypt/decrypt/sign/verify
# ------------------------------------------------------------------

class TestRaTlsSession:
    @pytest.fixture
    def session(self, bundle):
        pub_key_der = get_cert_public_key_bytes(bundle.cert_pem)
        return RaTlsSession(cert_public_key_der=pub_key_der, peer_id=PEER_ID, epoch=EPOCH)

    def test_encrypt_decrypt_round_trip(self, session):
        plaintext = b"hello from the enclave"
        ciphertext = session.encrypt(plaintext)
        decrypted = session.decrypt(ciphertext)
        assert decrypted == plaintext

    def test_encrypt_different_nonce_each_time(self, session):
        """Each encrypt call uses a fresh nonce — ciphertexts differ."""
        plaintext = b"work item"
        c1 = session.encrypt(plaintext)
        c2 = session.encrypt(plaintext)
        assert c1 != c2  # different nonces → different ciphertexts

    def test_decrypt_tampered_fails(self, session):
        """Tampered ciphertext raises InvalidTag."""
        from cryptography.exceptions import InvalidTag
        plaintext = b"secret work"
        ciphertext = session.encrypt(plaintext)
        tampered = ciphertext[:-1] + bytes([ciphertext[-1] ^ 0xFF])
        with pytest.raises(Exception):  # cryptography raises InvalidTag
            session.decrypt(tampered)

    def test_sign_verify_valid(self, session):
        output = b"miner output bytes"
        sig = session.sign(output)
        assert session.verify_signature(output, sig) is True

    def test_sign_verify_tampered_output(self, session):
        output = b"original output"
        sig = session.sign(output)
        assert session.verify_signature(b"tampered output", sig) is False

    def test_sign_verify_tampered_sig(self, session):
        output = b"output"
        sig = session.sign(output)
        bad_sig = bytes([sig[0] ^ 0xFF]) + sig[1:]
        assert session.verify_signature(output, bad_sig) is False

    def test_different_epochs_different_keys(self, bundle):
        pub = get_cert_public_key_bytes(bundle.cert_pem)
        s1 = RaTlsSession(pub, PEER_ID, EPOCH)
        s2 = RaTlsSession(pub, PEER_ID, EPOCH + 1)
        assert s1.session_key_hex != s2.session_key_hex

    def test_different_peers_different_keys(self, bundle):
        pub = get_cert_public_key_bytes(bundle.cert_pem)
        s1 = RaTlsSession(pub, PEER_ID, EPOCH)
        s2 = RaTlsSession(pub, ANOTHER_PEER, EPOCH)
        assert s1.session_key_hex != s2.session_key_hex


# ------------------------------------------------------------------
# Miner + Validator: same session key derived independently
# ------------------------------------------------------------------

class TestMinerValidatorSessionKeyAgreement:
    def test_same_key_both_sides(self, backend, mock_config):
        """
        Miner generates cert → Validator verifies → both derive identical session key.
        This is the critical property: key agreement without a separate key exchange.
        """
        # Miner side
        miner_server = RaTlsServer(peer_id=PEER_ID, epoch=EPOCH, backend=backend)
        miner_session = miner_server.make_session()

        # Validator side (receives the miner's cert PEM)
        cert_pem = miner_server.cert_bundle.cert_pem
        client = RaTlsClient(config=mock_config)
        val_result = client.verify_cert(cert_pem, PEER_ID, EPOCH)

        assert val_result.ok is True
        assert val_result.session.session_key_hex == miner_session.session_key_hex

    def test_end_to_end_encrypt_decrypt(self, backend, mock_config):
        """
        Miner encrypts work result → Validator decrypts and verifies signature.
        """
        work_result = b"{'accuracy': 0.97, 'loss': 0.12}"

        # Miner
        miner_server = RaTlsServer(peer_id=PEER_ID, epoch=EPOCH, backend=backend)
        miner_session = miner_server.make_session()
        ciphertext = miner_session.encrypt(work_result)
        sig = miner_session.sign(work_result)

        # Validator verifies cert and gets session
        cert_pem = miner_server.cert_bundle.cert_pem
        client = RaTlsClient(config=mock_config)
        val_result = client.verify_cert(cert_pem, PEER_ID, EPOCH)
        assert val_result.ok is True

        # Validator decrypts and verifies
        val_session = val_result.session
        decrypted = val_session.decrypt(ciphertext)
        assert decrypted == work_result
        assert val_session.verify_signature(decrypted, sig) is True

    def test_tampered_output_detected(self, backend, mock_config):
        """Validator detects tampered miner output."""
        work_result = b"{'accuracy': 0.97}"

        miner_server = RaTlsServer(peer_id=PEER_ID, epoch=EPOCH, backend=backend)
        miner_session = miner_server.make_session()
        sig = miner_session.sign(work_result)

        cert_pem = miner_server.cert_bundle.cert_pem
        client = RaTlsClient(config=mock_config)
        val_result = client.verify_cert(cert_pem, PEER_ID, EPOCH)

        tampered = b"{'accuracy': 1.0}"  # attacker modifies output
        assert val_result.session.verify_signature(tampered, sig) is False
