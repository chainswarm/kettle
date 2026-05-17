"""
MockBackend — deterministic TEE quotes for development and CI.

Security model
--------------
Mock quotes are signed with an HMAC-SHA256 using a well-known dev key.
The signature covers: measurement + report_data (which encodes peer_id + epoch).
Anyone with the mock key can verify — this is intentional for dev mode.

A mock quote has tee_score = 0.5 (not 1.0) because there is no hardware guarantee.
Subnet owners set MIN_TEE_SCORE=1.0 to require real hardware in production.

The measurement in mock mode is a deterministic sha256 of the backend label,
simulating a pinned binary hash. Production subnets set EXPECTED_MEASUREMENT
to a specific value; mock passes if that value matches the simulated measurement.
"""

from __future__ import annotations

import hashlib
import hmac
import time

from subnet.tee.backends.base import TeeBackendBase
from subnet.tee.quote import TeeBackend, TeeQuote, TcbStatus

# Simulated measurement for mock mode: sha256("mock-tee-v1")
MOCK_MEASUREMENT = hashlib.sha256(b"mock-tee-v1").hexdigest()

# Default dev HMAC key — explicitly NOT secret
MOCK_DEV_KEY = b"mock-tee-dev-key-do-not-use-in-production-!!"

# Default mock hardware ID — simulates a single CVM chip.
# Tests that need separate CVMs should pass different hardware_id values.
MOCK_HARDWARE_ID = hashlib.sha256(b"mock-chip-id-v1").hexdigest()


class MockBackend(TeeBackendBase):
    """
    Mock TEE backend.

    Generates HMAC-signed quotes bound to peer_id + epoch.
    No hardware required. Used for development and CI.

    Parameters
    ----------
    key         : HMAC key bytes (default: dev key)
    measurement : hex measurement string (default: sha256("mock-tee-v1"))
    debug_mode  : if True, simulates a debug-mode enclave (should be rejected by validators)
    """

    def __init__(
        self,
        key: bytes = MOCK_DEV_KEY,
        measurement: str = MOCK_MEASUREMENT,
        debug_mode: bool = False,
        hardware_id: str = MOCK_HARDWARE_ID,
        gpu_uuids: list[str] | None = None,
    ) -> None:
        self._key = key
        self._measurement = measurement
        self._debug_mode = debug_mode
        self._hardware_id = hardware_id
        self._gpu_uuids = gpu_uuids or []

    @property
    def backend_name(self) -> str:
        return TeeBackend.MOCK.value

    def generate_quote(
        self,
        peer_id: str,
        epoch: int,
        cert_pubkey_hash: bytes | None = None,
    ) -> TeeQuote:
        """
        Generate a mock quote bound to (peer_id, epoch).

        The HMAC signs: measurement + report_data_hex
        This means:
        - Changing peer_id → different report_data → different sig → fails verify
        - Changing epoch → different report_data → different sig → fails verify
        - Changing measurement → different sig → fails verify
        """
        report_data_hex = TeeQuote.make_report_data_hex(peer_id, epoch, cert_pubkey_hash=cert_pubkey_hash)

        # HMAC over: measurement || report_data
        msg = (self._measurement + report_data_hex).encode()
        sig = hmac.new(self._key, msg, hashlib.sha256).hexdigest()

        return TeeQuote(
            backend=TeeBackend.MOCK,
            measurement=self._measurement,
            report_data=report_data_hex,
            nonce=epoch,
            peer_id=peer_id,
            timestamp=time.time(),
            debug_mode=self._debug_mode,
            tcb_status=TcbStatus.UP_TO_DATE,  # mock is always "up to date"
            sig=sig,
            hardware_id=self._hardware_id,
            gpu_uuids=list(self._gpu_uuids),
        )

    def verify_sig(self, quote: TeeQuote) -> bool:
        """
        Verify the HMAC signature on a mock quote.

        Returns True iff sig is valid for the quote's measurement + report_data.
        Constant-time comparison via hmac.compare_digest.
        """
        msg = (quote.measurement + quote.report_data).encode()
        expected = hmac.new(self._key, msg, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, quote.sig)
