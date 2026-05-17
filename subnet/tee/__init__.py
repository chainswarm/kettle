"""
subnet.tee — TEE attestation layer for Hypertensor subnet template.

Provides:
- TeeQuote: normalised attestation quote schema (mock + TDX + SEV-SNP)
- MockBackend: HMAC-signed quotes for dev/CI (no hardware required)
- TdxBackend: Intel TDX DCAP quotes via /dev/tdx_guest
- SevSnpBackend: AMD SEV-SNP reports via /dev/sev-guest
- TeePublisher: per-epoch quote generation + DHT publish
- TeeConfig: env-var configuration

Quick start (dev mode)
----------------------
    export MOCK_TEE=true
    # TeePublisher will use MockBackend automatically

Production (TDX)
----------------
    export TEE_BACKEND=tdx
    export EXPECTED_MEASUREMENT=<sha384-hex-of-your-binary>
    # TeePublisher will use TdxBackend; verifier enforces measurement hash
"""

from subnet.tee.config import TeeConfig, get_tee_config
from subnet.tee.gpu_attestation import GpuAttestationResult, verify_gpu_mock, verify_gpu_nvidia
from subnet.tee.publisher import TeePublisher
from subnet.tee.quote import TEE_QUOTE_TOPIC, TeeBackend, TeeQuote, TcbStatus, dht_key
from subnet.tee.verifier import DcapVerifier, VerificationResult

__all__ = [
    "TeeQuote",
    "TeeBackend",
    "TcbStatus",
    "TeeConfig",
    "TeePublisher",
    "DcapVerifier",
    "VerificationResult",
    "TEE_QUOTE_TOPIC",
    "dht_key",
    "get_tee_config",
    # GPU attestation
    "GpuAttestationResult",
    "verify_gpu_mock",
    "verify_gpu_nvidia",
]
