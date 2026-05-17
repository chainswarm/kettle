"""
Envelope protocol for TEE subnet work item encryption and output signing.

Protocol overview
-----------------
1. Validator → Miner (WorkEnvelope):
   - Validator generates a random request_id and wraps the work item JSON inside
     an AES-GCM ciphertext keyed to the miner's RA-TLS session key.
   - Only the miner (who holds the matching session key) can decrypt it.

2. Miner → Validator (OutputEnvelope):
   - Miner signs the output bytes bound to the original request_id using
     HMAC-SHA256(session_key, request_id + b":" + output).
   - Validator verifies the signature: wrong request_id or tampered output fails.
   - The request_id binding provides replay protection: a signature from one
     work item cannot be presented as a valid response for a different request.

Wire format
-----------
Both envelope types serialise to JSON with bytes fields base64-encoded for safe
DHT storage.  Deserialisation uses ``d.get(key, default)`` for optional fields so
new fields added in future protocol versions are silently ignored by older readers.

Error handling
--------------
``TeeDecryptionError`` is the stable error type for AES-GCM authentication
failures.  Callers catch it without importing ``cryptography.exceptions`` directly.
"""

from __future__ import annotations

import base64
import json
import os
from dataclasses import dataclass

from cryptography.exceptions import InvalidTag

from subnet.tee.ratls.session import RaTlsSession


class TeeDecryptionError(Exception):
    """Raised when AES-GCM authentication tag is invalid — ciphertext tampered or session key mismatch."""


@dataclass
class WorkEnvelope:
    """
    Encrypted work item sent from validator to miner.

    Fields
    ------
    request_id  : 32-char hex string — unique per call, binds the work item to
                  the eventual OutputEnvelope for replay protection.
    ciphertext  : AES-256-GCM encrypted JSON payload (nonce || ciphertext+tag).
    """

    request_id: str
    ciphertext: bytes

    # ------------------------------------------------------------------
    # Factory
    # ------------------------------------------------------------------

    @classmethod
    def create(cls, work_item: bytes, session: RaTlsSession) -> "WorkEnvelope":
        """
        Encrypt *work_item* with *session* and return a new WorkEnvelope.

        A fresh ``request_id`` is generated for every call using
        ``os.urandom(16).hex()`` (32-char hex string, 128 bits of entropy).
        """
        request_id = os.urandom(16).hex()
        payload = json.dumps({
            "request_id": request_id,
            "work_item": base64.b64encode(work_item).decode(),
        })
        return cls(
            request_id=request_id,
            ciphertext=session.encrypt(payload.encode()),
        )

    # ------------------------------------------------------------------
    # Decrypt
    # ------------------------------------------------------------------

    def decrypt(self, session: RaTlsSession) -> tuple[str, bytes]:
        """
        Decrypt the work item using *session*.

        Returns ``(request_id, work_item_bytes)``.

        Raises
        ------
        TeeDecryptionError
            If AES-GCM authentication fails (tampered ciphertext or wrong key).
        """
        try:
            plaintext = session.decrypt(self.ciphertext)
        except InvalidTag:
            raise TeeDecryptionError(
                "authentication failed: ciphertext tampered or wrong key"
            )
        d = json.loads(plaintext.decode())
        return d["request_id"], base64.b64decode(d["work_item"])

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def to_bytes(self) -> bytes:
        """Serialise to JSON bytes for DHT storage."""
        return json.dumps({
            "request_id": self.request_id,
            "ciphertext": base64.b64encode(self.ciphertext).decode(),
        }).encode()

    @classmethod
    def from_bytes(cls, data: bytes) -> "WorkEnvelope":
        """Deserialise from DHT storage. Unknown fields are silently ignored."""
        d = json.loads(data.decode())
        return cls(
            request_id=d.get("request_id", ""),
            ciphertext=base64.b64decode(d.get("ciphertext", "")),
        )


@dataclass
class OutputEnvelope:
    """
    Signed output sent from miner to validator.

    Fields
    ------
    request_id  : echoed from the WorkEnvelope — binds this response to the
                  specific work item request.
    output      : raw output bytes produced by the miner.
    signature   : HMAC-SHA256(session_key, request_id.encode() + b":" + output).
                  Changing either ``request_id`` or ``output`` invalidates the sig.
    """

    request_id: str
    output: bytes
    signature: bytes

    # ------------------------------------------------------------------
    # Factory
    # ------------------------------------------------------------------

    @classmethod
    def create(
        cls, request_id: str, output: bytes, session: RaTlsSession
    ) -> "OutputEnvelope":
        """
        Sign *output* bound to *request_id* and return a new OutputEnvelope.

        The signed payload is ``request_id.encode() + b":" + output`` so that
        the signature is strictly coupled to both the identity of the request
        and the content of the response.
        """
        payload = request_id.encode() + b":" + output
        sig = session.sign(payload)
        return cls(request_id=request_id, output=output, signature=sig)

    # ------------------------------------------------------------------
    # Verify
    # ------------------------------------------------------------------

    def verify(self, session: RaTlsSession) -> bool:
        """
        Return ``True`` iff the signature is valid for this envelope's
        ``request_id`` and ``output``.

        Returns ``False`` on any mismatch — no exception is raised.
        """
        payload = self.request_id.encode() + b":" + self.output
        return session.verify_signature(payload, self.signature)

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def to_bytes(self) -> bytes:
        """Serialise to JSON bytes for DHT storage."""
        return json.dumps({
            "request_id": self.request_id,
            "output": base64.b64encode(self.output).decode(),
            "signature": base64.b64encode(self.signature).decode(),
        }).encode()

    @classmethod
    def from_bytes(cls, data: bytes) -> "OutputEnvelope":
        """Deserialise from DHT storage. Unknown fields are silently ignored."""
        d = json.loads(data.decode())
        return cls(
            request_id=d.get("request_id", ""),
            output=base64.b64decode(d.get("output", "")),
            signature=base64.b64decode(d.get("signature", "")),
        )
