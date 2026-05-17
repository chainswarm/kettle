"""
TEE configuration — loaded from environment variables.

Environment variables
---------------------
MOCK_TEE            : "true"/"false" — use mock backend (default: true)
TEE_BACKEND         : "mock" | "tdx" | "sev-snp" (overrides MOCK_TEE)
MOCK_TEE_KEY        : hex secret for HMAC signing in mock mode (default: dev key)
EXPECTED_MEASUREMENT: hex measurement hash validators enforce; empty = skip check
MIN_TEE_SCORE       : float 0.0–1.0, minimum tee_score to score non-zero (default: 0.0)
TCB_POLICY          : "strict" | "permissive" (default: strict)
                      strict:     any non-UpToDate TCB → 0.0
                      permissive: SWHardeningNeeded/ConfigNeeded → 0.5, OutOfDate/Revoked → 0.0
PCCS_URL            : URL of PCCS server for real DCAP verification (empty = use Intel PCS)
ALLOW_SHARED_HARDWARE: "true"/"false" — allow multiple nodes on same CVM/GPU (default: false)
                       Set to true for single-machine testing only.
MIN_TCB_VERSION     : "component=value,..." — reject nodes below these firmware levels
                      Example: "microcode=171,snp=22" (rejects CacheWarp + BadRAM vulnerable nodes)
                      Empty = no minimum (default). Use "auto" to enforce all known CVE patches.
REJECT_KNOWN_CVES   : "true"/"false" — reject nodes vulnerable to any known CVE (default: true)
"""

from __future__ import annotations

import os

from subnet.tee.quote import TeeBackend


class TeeConfig:
    """Immutable TEE configuration snapshot."""

    def __init__(self) -> None:
        backend_env = os.environ.get("TEE_BACKEND", "").strip().lower()
        mock_env = os.environ.get("MOCK_TEE", "true").strip().lower()

        if backend_env in ("tdx", "sev-snp", "sev_snp"):
            self.backend = TeeBackend.TDX if backend_env == "tdx" else TeeBackend.SEV_SNP
        elif backend_env == "mock":
            self.backend = TeeBackend.MOCK
        else:
            # Fall back to MOCK_TEE boolean
            self.backend = TeeBackend.MOCK if mock_env in ("1", "true", "yes") else TeeBackend.TDX

        # Mock HMAC key (hex) — used only when backend=mock
        mock_key_hex = os.environ.get("MOCK_TEE_KEY", "").strip()
        if mock_key_hex:
            self.mock_key: bytes = bytes.fromhex(mock_key_hex)
        else:
            # Default dev key — NOT secret; clearly labelled
            self.mock_key = b"mock-tee-dev-key-do-not-use-in-production-!!"

        # Measurement hash — validators enforce this if non-empty.
        # Supports comma-separated list for rolling updates, e.g. "abc,def".
        # Empty string → skip check entirely.
        raw = os.environ.get("EXPECTED_MEASUREMENT", "").strip().lower()
        self.expected_measurements: list[str] = [m.strip() for m in raw.split(",") if m.strip()]
        # Backward-compat single-value property (first entry or empty string)
        self.expected_measurement: str = self.expected_measurements[0] if self.expected_measurements else ""

        # Minimum tee_score to earn non-zero emissions
        try:
            self.min_tee_score: float = float(os.environ.get("MIN_TEE_SCORE", "0.0"))
        except ValueError:
            self.min_tee_score = 0.0

        # TCB policy
        tcb_policy = os.environ.get("TCB_POLICY", "strict").strip().lower()
        self.tcb_strict: bool = tcb_policy != "permissive"

        # PCCS URL for real hardware verification
        self.pccs_url: str = os.environ.get("PCCS_URL", "").strip()

        # Hardware uniqueness enforcement (Sybil resistance)
        allow_shared = os.environ.get("ALLOW_SHARED_HARDWARE", "false").strip().lower()
        self.allow_shared_hardware: bool = allow_shared in ("1", "true", "yes")

        # TCB version enforcement (CVE protection)
        from subnet.tee.tcb import MinTcbPolicy
        min_tcb_raw = os.environ.get("MIN_TCB_VERSION", "").strip()
        self.min_tcb_policy: MinTcbPolicy = MinTcbPolicy.from_env(min_tcb_raw)

        reject_cves = os.environ.get("REJECT_KNOWN_CVES", "true").strip().lower()
        self.reject_known_cves: bool = reject_cves not in ("0", "false", "no")

    @property
    def is_mock(self) -> bool:
        return self.backend == TeeBackend.MOCK

    def __repr__(self) -> str:
        return (
            f"TeeConfig(backend={self.backend.value}, "
            f"expected_measurements={self.expected_measurements or '<any>'}, "
            f"min_tee_score={self.min_tee_score}, "
            f"tcb_strict={self.tcb_strict}, "
            f"allow_shared_hardware={self.allow_shared_hardware})"
        )


# Module-level singleton — re-read on each instantiation to support test patching
def get_tee_config() -> TeeConfig:
    return TeeConfig()
