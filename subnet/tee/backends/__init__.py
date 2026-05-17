"""TEE backend factory.

PRODUCTION NOTE: Gramine/SGX is the only supported production runtime.
CVM-only backends (SEV-SNP, TDX without Gramine) are vulnerable to runtime
code tampering — the operator can modify code after boot while attestation
reports still show the original measurement. See docs/04-anti-cheat.md §10a.

MockBackend and CVM backends are available for development and testing.
"""

from __future__ import annotations

import logging

from subnet.tee.backends.base import TeeBackendBase
from subnet.tee.backends.mock import MockBackend
from subnet.tee.quote import TeeBackend

logger = logging.getLogger(__name__)


def get_backend(config) -> TeeBackendBase:
    """
    Return the appropriate TEE backend based on config.

    Falls back to MockBackend if the requested hardware backend is unavailable.
    This ensures the subnet can run without TEE hardware during development.

    WARNING: For production, deploy under Gramine/SGX. CVM-only backends
    (SEV-SNP, TDX) do not protect against runtime code tampering by the operator.
    """
    if config.backend == TeeBackend.MOCK:
        logger.info("[TEE] Using MockBackend (MOCK_TEE=true)")
        return MockBackend(key=config.mock_key)

    if config.backend == TeeBackend.TDX:
        try:
            from subnet.tee.backends.tdx import TdxBackend
            backend = TdxBackend()
            logger.info("[TEE] Using TdxBackend")
            return backend
        except Exception as exc:
            logger.warning("[TEE] TdxBackend unavailable (%s) — falling back to MockBackend", exc)
            return MockBackend(key=config.mock_key)

    if config.backend == TeeBackend.SEV_SNP:
        # Try Azure vTPM path first (Azure CVM), then raw /dev/sev-guest
        try:
            from subnet.tee.backends.sev_snp_azure import SevSnpAzureBackend
            backend = SevSnpAzureBackend()
            logger.info("[TEE] Using SevSnpAzureBackend (Azure vTPM)")
            return backend
        except Exception as exc_azure:
            logger.debug("[TEE] Azure vTPM not available (%s), trying /dev/sev-guest", exc_azure)
            try:
                from subnet.tee.backends.sev_snp import SevSnpBackend
                backend = SevSnpBackend()
                logger.info("[TEE] Using SevSnpBackend (/dev/sev-guest)")
                return backend
            except Exception as exc:
                logger.warning("[TEE] SevSnpBackend unavailable (%s) — falling back to MockBackend", exc)
                return MockBackend(key=config.mock_key)

    logger.warning("[TEE] Unknown backend %s — using MockBackend", config.backend)
    return MockBackend(key=config.mock_key)


__all__ = ["TeeBackendBase", "MockBackend", "get_backend"]
