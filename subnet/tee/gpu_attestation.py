"""
gpu_attestation.py — GPU attestation verifier for Hypertensor TEE inference cluster.

Provides two verification paths:
- verify_gpu_mock(): deterministic mock for dev/CI — always passes, no hardware required.
- verify_gpu_nvidia(): real attestation via NVIDIA nv-attestation-sdk; gracefully handles
  ImportError when the SDK is not installed (returns ok=False with a clear reason).

GPU attestation verifies NVIDIA GPU device identity via silicon-fused keys (H100/H200/B200).
The resulting GpuAttestationResult.score integrates with the consensus scoring pipeline.

Score semantics
---------------
  1.0 — attestation passed (gpu is verified)
  0.0 — attestation failed or unavailable

Usage (dev)
-----------
    from subnet.tee.gpu_attestation import verify_gpu_mock
    result = verify_gpu_mock()
    assert result.ok
    print(result.score)  # 1.0

Usage (production, H100/H200/B200)
-----------------------------------
    from subnet.tee.gpu_attestation import verify_gpu_nvidia
    result = verify_gpu_nvidia(gpu_index=0)
    if not result.ok:
        raise RuntimeError(result.reason)
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

# Deterministic mock UUID — stable across all calls in the same process and across processes.
_MOCK_GPU_UUID: str = str(uuid.UUID(int=0x4D4F434B47505500_4D4F434B47505500))


@dataclass
class GpuAttestationResult:
    """Result of a GPU attestation check.

    Attributes
    ----------
    ok:
        True if attestation passed; False otherwise.
    gpu_uuid:
        GPU device UUID string (empty when not available).
    gpu_type:
        Human-readable GPU model string (e.g. "H100", "MockGPU").
    reason:
        Human-readable failure reason when ok=False; None on success.
    """

    ok: bool
    gpu_uuid: str = ""
    gpu_type: str = ""
    reason: str | None = None

    @property
    def score(self) -> float:
        """Return 1.0 if attestation passed, 0.0 otherwise."""
        return 1.0 if self.ok else 0.0


def verify_gpu_mock() -> GpuAttestationResult:
    """Return a passing attestation result for development and CI.

    Always succeeds regardless of the execution environment.  The returned
    uuid is deterministic so that tests can assert identity across calls.
    """
    return GpuAttestationResult(
        ok=True,
        gpu_uuid=_MOCK_GPU_UUID,
        gpu_type="MockGPU",
    )


def verify_gpu_nvidia(gpu_index: int = 0) -> GpuAttestationResult:
    """Attest a physical NVIDIA GPU using the nv-attestation-sdk.

    Parameters
    ----------
    gpu_index:
        Zero-based index of the GPU to attest (default: 0).

    Returns
    -------
    GpuAttestationResult
        ok=True with gpu_uuid/gpu_type populated on success.
        ok=False with a descriptive reason on any failure, including when the
        SDK is not installed (ImportError handled gracefully).
    """
    # --- Import nv-attestation-sdk, fail gracefully when not installed ----------
    try:
        from nv_attestation_sdk import attestation as nv_attestation  # type: ignore[import]
    except ImportError:
        return GpuAttestationResult(
            ok=False,
            reason=(
                "nv-attestation-sdk is not installed; "
                "run `pip install nv-attestation-sdk` on a GPU node"
            ),
        )

    # --- Run attestation --------------------------------------------------------
    try:
        client = nv_attestation.Attestation()
        client.set_name("hypertensor-subnet")
        client.set_nonce(_build_nonce(gpu_index))
        client.add_verifier(
            nv_attestation.Devices.GPU,
            nv_attestation.Environment.LOCAL,
            "",
            "",
        )
        result_ok: bool = client.attest()
        claims: dict = _extract_claims(client, gpu_index)

        if result_ok:
            return GpuAttestationResult(
                ok=True,
                gpu_uuid=claims.get("gpu_uuid", ""),
                gpu_type=claims.get("gpu_name", ""),
            )
        else:
            return GpuAttestationResult(
                ok=False,
                gpu_uuid=claims.get("gpu_uuid", ""),
                gpu_type=claims.get("gpu_name", ""),
                reason="nv-attestation-sdk returned attestation failure",
            )
    except Exception as exc:  # pragma: no cover — hardware-only path
        return GpuAttestationResult(
            ok=False,
            reason=f"GPU attestation error: {exc}",
        )


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _build_nonce(gpu_index: int) -> str:
    """Build a deterministic-enough nonce for the attestation session."""
    import hashlib
    import time

    raw = f"hypertensor-gpu-{gpu_index}-{int(time.time())}"
    return hashlib.sha256(raw.encode()).hexdigest()


def _extract_claims(client: object, gpu_index: int) -> dict:
    """Extract GPU UUID and name from attestation claims, returning {} on failure."""
    try:
        # nv-attestation-sdk stores results per verifier token
        token = client.get_token()  # type: ignore[attr-defined]
        if not token:
            return {}
        import json
        # The token is a JWT-like structure; the payload contains GPU claims.
        # We do a best-effort parse — the SDK may change its schema.
        parts = token.split(".")
        if len(parts) < 2:
            return {}
        import base64
        payload_bytes = base64.urlsafe_b64decode(parts[1] + "==")
        payload: dict = json.loads(payload_bytes)
        claims = payload.get("measres", payload)
        return {
            "gpu_uuid": claims.get("x-nvidia-gpu-uuid", ""),
            "gpu_name": claims.get("x-nvidia-gpu-name", ""),
        }
    except Exception:  # pragma: no cover
        return {}
