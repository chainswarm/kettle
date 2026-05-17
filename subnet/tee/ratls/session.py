"""
RaTlsSession — Session key derivation and output signing.

Session key contract
--------------------
After RA-TLS handshake:
  session_key = HKDF-SHA256(
      salt    = b"hypertensor-ratls-session-v1",
      ikm     = sha256(cert_public_key_der),   ← ties key to the ephemeral cert
      info    = f"{peer_id}:{epoch}".encode(),  ← ties key to identity + epoch
      length  = 32,
  )

This means:
- Each epoch gets a distinct session key (epoch rotation)
- Each node gets a distinct session key (peer_id binding)
- The key is derived from the ephemeral cert — re-keying the cert rotates the key

Work item encryption (R013)
---------------------------
  ciphertext = AES-GCM(session_key, nonce=os.urandom(12), plaintext=work_item)
  message    = nonce || ciphertext || tag

Output signing (R014)
---------------------
  sig = HMAC-SHA256(session_key, output_bytes)
  Validator: HMAC-SHA256(session_key, output_bytes) == sig
"""

from __future__ import annotations

import hashlib
import hmac
import os
import struct

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.hashes import SHA256
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

_HKDF_SALT = b"hypertensor-ratls-session-v1"
_SESSION_KEY_LEN = 32  # 256-bit AES key


class RaTlsSession:
    """
    Ephemeral session context after RA-TLS handshake.

    Encapsulates the session key and provides encrypt/decrypt/sign/verify.

    Parameters
    ----------
    cert_public_key_der : raw DER bytes of the miner's ephemeral cert public key
    peer_id             : miner's libp2p peer ID
    epoch               : current subnet epoch
    """

    def __init__(self, cert_public_key_der: bytes, peer_id: str, epoch: int) -> None:
        self._peer_id = peer_id
        self._epoch = epoch
        self._session_key = self._derive_session_key(cert_public_key_der, peer_id, epoch)

    @staticmethod
    def _derive_session_key(cert_public_key_der: bytes, peer_id: str, epoch: int) -> bytes:
        """Derive a 32-byte session key using HKDF-SHA256."""
        ikm = hashlib.sha256(cert_public_key_der).digest()
        info = f"{peer_id}:{epoch}".encode()

        hkdf = HKDF(
            algorithm=SHA256(),
            length=_SESSION_KEY_LEN,
            salt=_HKDF_SALT,
            info=info,
        )
        return hkdf.derive(ikm)

    # ------------------------------------------------------------------
    # Work item encryption (R013)
    # ------------------------------------------------------------------

    def encrypt(self, plaintext: bytes) -> bytes:
        """
        Encrypt a work item with AES-256-GCM.

        Returns nonce (12 bytes) || ciphertext+tag.
        """
        nonce = os.urandom(12)
        aesgcm = AESGCM(self._session_key)
        ciphertext = aesgcm.encrypt(nonce, plaintext, None)
        return nonce + ciphertext

    def decrypt(self, ciphertext_msg: bytes) -> bytes:
        """
        Decrypt an AES-256-GCM encrypted work item.

        Expects nonce (12 bytes) || ciphertext+tag.

        Raises
        ------
        InvalidTag if authentication fails (tampered ciphertext).
        """
        nonce = ciphertext_msg[:12]
        ciphertext = ciphertext_msg[12:]
        aesgcm = AESGCM(self._session_key)
        return aesgcm.decrypt(nonce, ciphertext, None)

    # ------------------------------------------------------------------
    # Output signing (R014)
    # ------------------------------------------------------------------

    def sign(self, output: bytes) -> bytes:
        """Sign miner output with HMAC-SHA256(session_key, output). Returns 32-byte sig."""
        return hmac.new(self._session_key, output, hashlib.sha256).digest()

    def verify_signature(self, output: bytes, sig: bytes) -> bool:
        """Verify an output signature. Returns True iff valid."""
        expected = hmac.new(self._session_key, output, hashlib.sha256).digest()
        return hmac.compare_digest(expected, sig)

    # ------------------------------------------------------------------
    # Accessors
    # ------------------------------------------------------------------

    @property
    def peer_id(self) -> str:
        return self._peer_id

    @property
    def epoch(self) -> int:
        return self._epoch

    @property
    def session_key_hex(self) -> str:
        """For diagnostics only — do NOT log in production."""
        return self._session_key.hex()

    def __repr__(self) -> str:
        return f"RaTlsSession(peer_id={self._peer_id[:16]}..., epoch={self._epoch})"
