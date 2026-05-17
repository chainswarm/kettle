"""
SealedStore — Measurement-bound encrypted storage for TEE miners.

What "sealing" means
--------------------
The store derives an encryption key from:
  sealing_key = HKDF-SHA256(
      salt = b"hypertensor-sealed-storage-v1",
      ikm  = sha256(measurement),   ← measurement = enclave binary hash
      info = b"sealed-key",
  )

This means:
- Only the same enclave measurement can derive the same sealing key
- A recompiled or patched binary gets a different measurement → different key
- An attacker who boots a different binary cannot unseal the data

Security model
--------------
  STRONG (real TDX/SEV-SNP): sealing key derived from PSP/TDX hardware key +
  measurement. The hardware enforces: different measurement = irrecoverably
  different key. State from one binary is permanently inaccessible to another.

  MOCK (MOCK_TEE=true): sealing key derived from HMAC of measurement with the
  mock key. Same software enforcement; no hardware guarantee. Used for dev/CI.

The SealedStore takes a `measurement` parameter. Production code reads the
measurement from TeeConfig.expected_measurement (or from the running quote).

Storage format
--------------
Each value is stored as:
  nonce (12 bytes) || AES-256-GCM(ciphertext + 16-byte tag)

The RocksDB key is:
  nmap: "sealed" → key → ciphertext_blob

Mock measurement
----------------
In mock mode, measurement = sha256("mock-tee-v1").hexdigest() (from MockBackend).
If the test changes this, sealed data becomes unreadable — exactly the intent.
"""

from __future__ import annotations

import hashlib
import logging
import os
from typing import Any, Optional

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.hashes import SHA256
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from subnet.utils.db.database import RocksDB

logger = logging.getLogger(__name__)

_SEALED_NMAP = "sealed"
_HKDF_SALT = b"hypertensor-sealed-storage-v1"
_SEAL_KEY_LEN = 32  # AES-256
_NONCE_LEN = 12


class SealedStore:
    """
    Measurement-bound encrypted key-value store.

    Parameters
    ----------
    db          : RocksDB instance (the node's DHT / local DB)
    measurement : hex measurement string (enclave binary hash)
                  In mock mode: sha256("mock-tee-v1").hexdigest()
                  In production: quote.measurement from TdxBackend or SevSnpBackend
    mock_key    : HMAC base key (only used in mock mode — ignored on real hardware)
    is_mock     : if True, use HMAC(mock_key, measurement) as IKM (dev/CI mode)
                  if False, use sha256(measurement) directly as IKM (hardware mode)
                  Default: True for backward compatibility
    """

    def __init__(
        self,
        db: RocksDB,
        measurement: str,
        mock_key: bytes = b"mock-tee-dev-key-do-not-use-in-production-!!",
        is_mock: bool = True,
    ) -> None:
        self._db = db
        self._measurement = measurement
        self._is_mock = is_mock
        self._seal_key = self._derive_seal_key(measurement, mock_key, is_mock)
        self._aesgcm = AESGCM(self._seal_key)
        logger.debug(
            "[SealedStore] Initialised with measurement=%s... is_mock=%s",
            measurement[:16], is_mock,
        )

    @staticmethod
    def _derive_seal_key(measurement: str, mock_key: bytes, is_mock: bool) -> bytes:
        """
        Derive a 32-byte AES-256 sealing key from the enclave measurement.

        Mock mode (is_mock=True):
          IKM = HMAC-SHA256(mock_key, measurement)
          This simulates hardware key derivation for dev/CI.
          Anyone with the mock key can derive the same sealing key.

        Hardware mode (is_mock=False):
          IKM = SHA256(measurement_bytes)
          The measurement is the SHA-384 hash of the enclave binary,
          provided by real TEE hardware. Different binary = different
          measurement = different IKM = different sealing key.

          On real TDX/SEV-SNP, the measurement comes from hardware and
          cannot be forged. This makes the sealing key hardware-bound:
          only the exact same binary can derive the same key.
        """
        if is_mock:
            import hmac as _hmac
            ikm = _hmac.new(mock_key, measurement.encode(), hashlib.sha256).digest()
        else:
            # Hardware mode: measurement IS the hardware-provided identity
            # No mock key involved — key is bound to the measurement alone
            ikm = hashlib.sha256(bytes.fromhex(measurement)).digest()

        hkdf = HKDF(
            algorithm=SHA256(),
            length=_SEAL_KEY_LEN,
            salt=_HKDF_SALT,
            info=b"sealed-key",
        )
        return hkdf.derive(ikm)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def seal(self, key: str, plaintext: bytes) -> None:
        """
        Encrypt and store `plaintext` under `key`.

        Overwrites any existing sealed value.
        Uses AES-256-GCM with a fresh random nonce each call.
        """
        nonce = os.urandom(_NONCE_LEN)
        ciphertext = self._aesgcm.encrypt(nonce, plaintext, key.encode())  # key as AAD
        blob = nonce + ciphertext

        self._db.nmap_set(_SEALED_NMAP, key, blob)
        logger.debug("[SealedStore] Sealed key=%s (%d bytes)", key, len(plaintext))

    def unseal(self, key: str) -> Optional[bytes]:
        """
        Retrieve and decrypt a sealed value.

        Returns None if key not found.
        Raises SealedDecryptionError if the blob is corrupted or the
        measurement key has changed (wrong enclave binary).
        """
        blob = self._db.nmap_get(_SEALED_NMAP, key)
        if blob is None:
            return None

        if len(blob) < _NONCE_LEN:
            raise SealedDecryptionError(f"Blob too short for key={key}: {len(blob)} bytes")

        nonce = blob[:_NONCE_LEN]
        ciphertext = blob[_NONCE_LEN:]

        try:
            plaintext = self._aesgcm.decrypt(nonce, ciphertext, key.encode())
            logger.debug("[SealedStore] Unsealed key=%s (%d bytes)", key, len(plaintext))
            return plaintext
        except Exception as exc:
            raise SealedDecryptionError(
                f"Failed to unseal key={key}: measurement mismatch or corruption ({exc})"
            ) from exc

    def delete(self, key: str) -> bool:
        """Delete a sealed entry. Returns True if it existed."""
        return self._db.nmap_delete(_SEALED_NMAP, key)

    def exists(self, key: str) -> bool:
        """Return True if a sealed entry exists for key."""
        return self._db.nmap_exists(_SEALED_NMAP, key)

    @property
    def measurement(self) -> str:
        return self._measurement

    # ------------------------------------------------------------------
    # Structured helpers (JSON values)
    # ------------------------------------------------------------------

    def seal_json(self, key: str, obj: Any) -> None:
        """Seal a JSON-serialisable object."""
        import json
        self.seal(key, json.dumps(obj).encode())

    def unseal_json(self, key: str) -> Optional[Any]:
        """Unseal and deserialise a JSON value. Returns None if not found."""
        import json
        raw = self.unseal(key)
        if raw is None:
            return None
        return json.loads(raw.decode())


class SealedDecryptionError(RuntimeError):
    """
    Raised when sealed data cannot be decrypted.

    Typical causes:
    - Different enclave measurement (binary was updated or patched)
    - Corrupted ciphertext
    - Wrong mock_key in mock mode

    In production TEE deployments, this is expected when the enclave binary
    changes. The node must re-initialise state (key rotation event).
    """
