"""
TeeQuote — normalised attestation quote schema.

Works across all backends (mock, TDX, SEV-SNP) and is the unit of exchange
stored in the DHT and verified by validators.

Identity binding contract (enforced by every backend):
    report_data[0:32]  = sha256(f"{peer_id}:{epoch}".encode()).digest()
    report_data[32:64] = sha256(cert_pubkey_der) if RA-TLS, else zeros

This means every quote is cryptographically tied to a specific node identity,
a specific epoch, and (when RA-TLS is used) the session public key.
A stolen or replayed quote fails identity verification.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class TeeBackend(str, Enum):
    MOCK = "mock"
    TDX = "tdx"
    SEV_SNP = "sev-snp"


class TcbStatus(str, Enum):
    UP_TO_DATE = "UpToDate"
    SW_HARDENING_NEEDED = "SWHardeningNeeded"
    CONFIG_NEEDED = "ConfigurationNeeded"
    CONFIG_AND_SW_HARDENING_NEEDED = "ConfigurationAndSWHardeningNeeded"
    OUT_OF_DATE = "OutOfDate"
    REVOKED = "Revoked"
    UNKNOWN = "Unknown"


@dataclass
class TeeQuote:
    """
    Normalised TEE attestation quote.

    Fields
    ------
    backend         : which hardware/mock generated this quote
    measurement     : hex-encoded enclave measurement (MRTD for TDX, MEASUREMENT for SEV-SNP)
    report_data     : hex-encoded 64-byte report data field — MUST be sha256(peer_id:epoch) zero-padded
    nonce           : epoch number (anti-replay: validator rejects if nonce != current_epoch)
    peer_id         : libp2p peer ID of the miner — redundant but explicit for fast rejection
    timestamp       : unix timestamp when quote was generated
    debug_mode      : True if enclave is in debug/test mode — validators MUST reject
    tcb_status      : TCB status from Intel collateral (set during verification, not generation)
    sig             : backend-specific signature blob (HMAC for mock, ECDSA P-256 for TDX/SEV-SNP)
    raw_bytes       : full raw quote bytes (None for mock — mock has no binary format)
    """

    backend: TeeBackend
    measurement: str           # hex
    report_data: str           # hex, 64 bytes = 128 hex chars
    nonce: int                 # epoch number
    peer_id: str
    timestamp: float = field(default_factory=time.time)
    debug_mode: bool = False
    tcb_status: TcbStatus = TcbStatus.UNKNOWN
    sig: str = ""              # hex
    raw_bytes: Optional[bytes] = field(default=None, repr=False)
    version: int = 1

    # Hardware uniqueness fields (Sybil resistance)
    hardware_id: str = ""      # hex — CVM chip ID (SEV-SNP CHIP_ID / TDX platform ID)
    gpu_uuids: list[str] = field(default_factory=list)  # GPU device UUIDs reported from inside TEE

    # TCB version (firmware/microcode levels for CVE checking)
    tcb_version: Optional[dict] = None  # TcbVersion.to_dict() — None for legacy quotes

    # ------------------------------------------------------------------
    # Identity binding
    # ------------------------------------------------------------------

    @staticmethod
    def make_report_data(
        peer_id: str,
        epoch: int,
        cert_pubkey_hash: bytes | None = None,
    ) -> bytes:
        """
        Compute the 64-byte report_data value for a given peer_id and epoch.

        Layout:
            [0:32]  = sha256(peer_id:epoch)
            [32:64] = cert_pubkey_hash (sha256 of cert public key DER) or zeros

        If cert_pubkey_hash is provided (must be 32 bytes), it fills the upper
        32 bytes.  If None, the upper 32 bytes are zero-padded (backward compat).
        """
        identity_digest = hashlib.sha256(f"{peer_id}:{epoch}".encode()).digest()
        if cert_pubkey_hash is not None:
            if len(cert_pubkey_hash) != 32:
                raise ValueError(
                    f"cert_pubkey_hash must be 32 bytes, got {len(cert_pubkey_hash)}"
                )
            return identity_digest + cert_pubkey_hash
        return identity_digest + b"\x00" * 32

    @staticmethod
    def make_report_data_hex(
        peer_id: str,
        epoch: int,
        cert_pubkey_hash: bytes | None = None,
    ) -> str:
        """Return make_report_data() as a hex string (128 hex chars)."""
        return TeeQuote.make_report_data(peer_id, epoch, cert_pubkey_hash=cert_pubkey_hash).hex()

    def verify_identity(
        self,
        peer_id: str,
        epoch: int,
        cert_pubkey_hash: bytes | None = None,
    ) -> bool:
        """
        Return True iff this quote's report_data matches the expected value.

        Protects against:
        - Replay attacks: wrong epoch nonce → False
        - Sybil / identity theft: wrong peer_id → False
        - Session hijack (F-02): wrong cert pubkey → False
        """
        expected = TeeQuote.make_report_data_hex(peer_id, epoch, cert_pubkey_hash=cert_pubkey_hash)
        return self.report_data == expected and self.nonce == epoch

    # ------------------------------------------------------------------
    # Serialisation
    # ------------------------------------------------------------------

    def to_dict(self) -> dict:
        d = {
            "version": self.version,
            "backend": self.backend.value,
            "measurement": self.measurement,
            "report_data": self.report_data,
            "nonce": self.nonce,
            "peer_id": self.peer_id,
            "timestamp": self.timestamp,
            "debug_mode": self.debug_mode,
            "tcb_status": self.tcb_status.value,
            "sig": self.sig,
            "hardware_id": self.hardware_id,
            "gpu_uuids": self.gpu_uuids,
            "tcb_version": self.tcb_version,
        }
        # Include raw_bytes for real hardware quotes (needed for DCAP verification)
        if self.raw_bytes is not None:
            import base64
            d["raw_bytes_b64"] = base64.b64encode(self.raw_bytes).decode()
        return d

    def to_bytes(self) -> bytes:
        """Serialise for DHT storage (JSON). Includes base64 raw_bytes if present."""
        return json.dumps(self.to_dict()).encode()

    @classmethod
    def from_bytes(cls, data: bytes) -> "TeeQuote":
        """Deserialise from DHT storage."""
        d = json.loads(data.decode())
        version = d.get("version", 1)
        if version > 1:
            raise ValueError(f"unsupported quote version: {version}")
        # Restore raw_bytes from base64 if present
        raw_bytes = None
        if "raw_bytes_b64" in d:
            import base64
            raw_bytes = base64.b64decode(d["raw_bytes_b64"])
        return cls(
            backend=TeeBackend(d["backend"]),
            measurement=d["measurement"],
            report_data=d["report_data"],
            nonce=d["nonce"],
            peer_id=d["peer_id"],
            timestamp=d["timestamp"],
            debug_mode=d.get("debug_mode", False),
            tcb_status=TcbStatus(d.get("tcb_status", TcbStatus.UNKNOWN.value)),
            sig=d.get("sig", ""),
            version=version,
            raw_bytes=raw_bytes,
            hardware_id=d.get("hardware_id", ""),
            gpu_uuids=d.get("gpu_uuids", []),
            tcb_version=d.get("tcb_version"),
        )

    @classmethod
    def from_dict(cls, d: dict) -> "TeeQuote":
        version = d.get("version", 1)
        if version > 1:
            raise ValueError(f"unsupported quote version: {version}")
        return cls(
            backend=TeeBackend(d["backend"]),
            measurement=d["measurement"],
            report_data=d["report_data"],
            nonce=d["nonce"],
            peer_id=d["peer_id"],
            timestamp=d.get("timestamp", 0.0),
            debug_mode=d.get("debug_mode", False),
            tcb_status=TcbStatus(d.get("tcb_status", TcbStatus.UNKNOWN.value)),
            sig=d.get("sig", ""),
            version=version,
            hardware_id=d.get("hardware_id", ""),
            gpu_uuids=d.get("gpu_uuids", []),
            tcb_version=d.get("tcb_version"),
        )


# DHT key helpers

TEE_QUOTE_TOPIC = "tee_quote"
RATLS_CERT_TOPIC = "ratls_cert"


def dht_key(epoch: int, peer_id: str) -> str:
    """Canonical DHT key for a quote: '{epoch}:{peer_id}'"""
    return f"{epoch}:{peer_id}"
