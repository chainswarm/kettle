"""
RaTlsServer — RA-TLS server for miners.

The miner runs this server so validators can attest it via TLS handshake.
The server certificate IS the attestation — no separate quote exchange.

Usage
-----
    from subnet.tee.ratls.server import RaTlsServer
    from subnet.tee.backends.mock import MockBackend

    backend = MockBackend()
    server = RaTlsServer(peer_id=my_peer_id, epoch=current_epoch, backend=backend)

    # Get the cert bundle (PEM cert + key) — pass to ssl.SSLContext
    bundle = server.cert_bundle

    # Or use as an async context manager (trio-compatible):
    async with server.serve("0.0.0.0", port=7890) as listener:
        ...

Mock path (MOCK_TEE=true)
--------------------------
Uses MockBackend.generate_quote → RaTlsCert with HMAC-signed quote.
No hardware required.

Real path (TDX)
----------------
Uses TdxBackend.generate_quote → RaTlsCert with DCAP quote in extension.
Validator runs full DCAP chain verification.
"""

from __future__ import annotations

import hashlib
import logging
import ssl
import tempfile
import os
from pathlib import Path
from typing import Optional

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

from subnet.tee.backends.base import TeeBackendBase
from subnet.tee.ratls.cert import RaTlsCertBundle, generate_ratls_cert
from subnet.tee.ratls.session import RaTlsSession, RaTlsSession as _Session
from subnet.tee.ratls.cert import get_cert_public_key_bytes

logger = logging.getLogger(__name__)


class RaTlsServer:
    """
    RA-TLS server: generates and serves an attestation-embedded TLS certificate.

    Parameters
    ----------
    peer_id : miner's libp2p peer ID
    epoch   : current subnet epoch (used for identity binding in quote)
    backend : TEE backend (mock or real hardware)
    """

    def __init__(
        self,
        peer_id: str,
        epoch: int,
        backend: TeeBackendBase,
    ) -> None:
        self._peer_id = peer_id
        self._epoch = epoch
        self._backend = backend
        self._bundle: Optional[RaTlsCertBundle] = None

    def generate_cert(self) -> RaTlsCertBundle:
        """
        Generate a fresh RA-TLS certificate for this epoch.

        Flow (F-02 pubkey binding):
        1. Generate ECDSA P-256 keypair
        2. Compute cert_pubkey_hash = sha256(pubkey_der)
        3. Generate TEE quote with cert_pubkey_hash bound into report_data
        4. Build X.509 cert with the pre-generated private key and embedded quote

        This ensures the hardware-signed quote cryptographically ties the
        session key to the attested enclave.
        """
        # Step 1: Generate ephemeral ECDSA P-256 keypair BEFORE the quote
        private_key = ec.generate_private_key(ec.SECP256R1())
        pub_key_der = private_key.public_key().public_bytes(
            encoding=serialization.Encoding.DER,
            format=serialization.PublicFormat.SubjectPublicKeyInfo,
        )

        # Step 2: Hash the public key
        cert_pubkey_hash = hashlib.sha256(pub_key_der).digest()

        # Step 3: Generate quote with pubkey hash bound into report_data upper 32 bytes
        quote = self._backend.generate_quote(
            peer_id=self._peer_id,
            epoch=self._epoch,
            cert_pubkey_hash=cert_pubkey_hash,
        )

        # Step 4: Build cert using the pre-generated private key
        bundle = generate_ratls_cert(quote, private_key=private_key)
        self._bundle = bundle
        logger.info(
            "[RaTlsServer] Generated RA-TLS cert: peer_id=%s epoch=%d backend=%s measurement=%s...",
            self._peer_id[:16], self._epoch, quote.backend.value, quote.measurement[:16],
        )
        return bundle

    @property
    def cert_bundle(self) -> RaTlsCertBundle:
        """Return the cert bundle, generating one if not yet created."""
        if self._bundle is None:
            self.generate_cert()
        return self._bundle

    def make_ssl_context(self) -> ssl.SSLContext:
        """
        Create an ssl.SSLContext configured with the RA-TLS certificate.

        Note: Python's ssl module requires file paths for load_cert_chain().
        The private key is written to a temp file, loaded, and immediately
        deleted. In Gramine SGX deployments, ensure /tmp maps to encrypted
        tmpfs in the manifest (sgx.allowed_files or sgx.protected_files).

        The context uses TLS 1.3, server mode, and does NOT require client certs
        (validators authenticate via the server cert, not mutual TLS).

        Usage (trio example):
            ctx = server.make_ssl_context()
            async with trio.open_ssl_over_tcp_listeners(port, ctx) as listeners:
                ...
        """
        bundle = self.cert_bundle

        # Write PEM files to a temp dir (ssl.SSLContext needs file paths)
        tmpdir = tempfile.mkdtemp()
        cert_path = os.path.join(tmpdir, "ratls.crt")
        key_path = os.path.join(tmpdir, "ratls.key")

        Path(cert_path).write_bytes(bundle.cert_pem)
        Path(key_path).write_bytes(bundle.key_pem)

        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.minimum_version = ssl.TLSVersion.TLSv1_3
        ctx.load_cert_chain(certfile=cert_path, keyfile=key_path)

        # Clean up temp files — they've been loaded into the context
        os.unlink(cert_path)
        os.unlink(key_path)
        os.rmdir(tmpdir)

        return ctx

    def make_session(self) -> RaTlsSession:
        """
        Create an RaTlsSession from this server's cert.

        The session key is derived from the ephemeral cert public key + peer_id + epoch.
        Both miner and validator independently derive the same key after handshake.
        """
        bundle = self.cert_bundle
        pub_key_der = get_cert_public_key_bytes(bundle.cert_pem)
        return RaTlsSession(
            cert_public_key_der=pub_key_der,
            peer_id=self._peer_id,
            epoch=self._epoch,
        )
