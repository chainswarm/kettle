"""
subnet.tee.ratls — Remote Attestation TLS for Hypertensor TEE subnets.

The TLS handshake IS the attestation.

Quick start
-----------
Miner (server side):
    from subnet.tee.ratls import RaTlsServer
    from subnet.tee.backends.mock import MockBackend

    server = RaTlsServer(peer_id=my_peer_id, epoch=epoch, backend=MockBackend())
    bundle = server.cert_bundle           # PEM cert + key
    session = server.make_session()       # for encrypting outputs
    ciphertext = session.encrypt(result)
    sig = session.sign(result)

Validator (client side):
    from subnet.tee.ratls import RaTlsClient

    client = RaTlsClient()
    result = client.verify_cert(cert_pem=server_cert_pem, peer_id=peer_id, epoch=epoch)
    if result.ok:
        plaintext = result.session.decrypt(ciphertext)
        assert result.session.verify_signature(plaintext, sig)
"""

from subnet.tee.ratls.envelope import TeeDecryptionError, WorkEnvelope, OutputEnvelope
from subnet.tee.ratls.cert import (
    RaTlsCertBundle,
    RaTlsExtensionMissingError,
    RaTlsExtensionParseError,
    TEE_QUOTE_OID,
    extract_quote_from_cert,
    generate_ratls_cert,
    get_cert_public_key_bytes,
)
from subnet.tee.ratls.client import RaTlsAttestationError, RaTlsClient, RaTlsVerificationResult
from subnet.tee.ratls.server import RaTlsServer
from subnet.tee.ratls.session import RaTlsSession

__all__ = [
    # envelope
    "WorkEnvelope",
    "OutputEnvelope",
    "TeeDecryptionError",
    # cert
    "RaTlsCertBundle",
    "TEE_QUOTE_OID",
    "generate_ratls_cert",
    "extract_quote_from_cert",
    "get_cert_public_key_bytes",
    "RaTlsExtensionMissingError",
    "RaTlsExtensionParseError",
    # server
    "RaTlsServer",
    # client
    "RaTlsClient",
    "RaTlsVerificationResult",
    "RaTlsAttestationError",
    # session
    "RaTlsSession",
]
