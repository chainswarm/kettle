"""
TdxBackend — Intel TDX DCAP quote generation.

Requirements
------------
- Linux kernel 6.2+ with TDX guest driver loaded
- /dev/tdx_guest device accessible
- libtdx-attest or python-tdx-attest installed

How TDX quoting works
---------------------
1. Caller prepares 64-byte report_data (we use sha256(peer_id:epoch) zero-padded)
2. TDX guest driver writes report_data into the TD Report
3. Quoting Enclave (QE) signs the TD Report → produces a DCAP quote
4. Quote is a binary blob containing:
   - TD Report (with measurement MRTD + report_data)
   - QE Report
   - PCK certificate chain
   - ECDSA signature

The DCAP quote is then published to DHT and verified by validators.

Production deployment
---------------------
Subnet owner builds the miner image with TDX support.
The Gramine manifest (M002) measures the entire stack.
Validators compare quote.measurement against EXPECTED_MEASUREMENT.
"""

from __future__ import annotations

import logging
import time
from typing import Optional

from subnet.tee.backends.base import TeeBackendBase
from subnet.tee.quote import TeeBackend, TeeQuote, TcbStatus

logger = logging.getLogger(__name__)

# TDX DCAP quote header magic bytes
TDX_QUOTE_MAGIC = b"\x04\x00\x02\x00"  # version 4, attestation key type ECDSA-256


class TdxBackend(TeeBackendBase):
    """
    Intel TDX DCAP attestation backend.

    Requires /dev/tdx_guest and libtdx-attest.
    On non-TDX hardware, raises TdxNotAvailableError at init.

    For CI / development use MockBackend with MOCK_TEE=true.
    """

    def __init__(self) -> None:
        self._attest_lib: Optional[object] = None
        self._check_availability()

    def _check_availability(self) -> None:
        """Check that /dev/tdx_guest exists and libtdx-attest is importable."""
        import os

        if not os.path.exists("/dev/tdx_guest"):
            raise TdxNotAvailableError(
                "/dev/tdx_guest not found. "
                "TDX is not available on this host. "
                "Use MOCK_TEE=true for development."
            )

        try:
            import ctypes

            self._libtdx = ctypes.CDLL("libtdx_attest.so.1")
            logger.info("[TdxBackend] libtdx_attest loaded")
        except OSError as e:
            raise TdxNotAvailableError(
                f"libtdx_attest.so.1 not found: {e}. "
                "Install intel-tdx-attest package."
            ) from e

    @property
    def backend_name(self) -> str:
        return TeeBackend.TDX.value

    def generate_quote(
        self,
        peer_id: str,
        epoch: int,
        cert_pubkey_hash: bytes | None = None,
    ) -> TeeQuote:
        """
        Generate a TDX DCAP quote bound to (peer_id, epoch).

        Calls tdx_attest_get_quote() via ctypes with report_data set to
        sha256(peer_id:epoch) || sha256(cert_pubkey_der) (or zero-padded).
        """
        report_data = TeeQuote.make_report_data(peer_id, epoch, cert_pubkey_hash=cert_pubkey_hash)  # 64 bytes
        raw_quote = self._get_tdx_quote(report_data)

        # Parse measurement from TD Report (offset 512 in the quote body, 48 bytes)
        measurement_hex = self._extract_measurement(raw_quote)

        platform_id = self._extract_platform_id(raw_quote)

        from subnet.tee.tcb import extract_tcb_tdx
        tcb = extract_tcb_tdx(raw_quote)

        return TeeQuote(
            backend=TeeBackend.TDX,
            measurement=measurement_hex,
            report_data=report_data.hex(),
            nonce=epoch,
            peer_id=peer_id,
            timestamp=time.time(),
            debug_mode=self._is_debug_mode(raw_quote),
            tcb_status=TcbStatus.UNKNOWN,  # set by verifier after collateral check
            sig="",  # sig is embedded in raw_bytes
            raw_bytes=raw_quote,
            hardware_id=platform_id,
            tcb_version=tcb.to_dict(),
        )

    def _get_tdx_quote(self, report_data: bytes) -> bytes:
        """
        Call libtdx_attest to get a raw DCAP quote.

        tdx_attest_get_quote(
            report_data: *u8[64],
            att_key_id_list: *tdx_att_att_key_id_list_t,  # NULL = use default
            att_key_id: *tdx_att_att_key_id_t,            # NULL = use default
            p_quote: **u8,                                # out: raw quote pointer
            quote_size: *u32,                             # out: quote length
            flags: u32
        ) -> int (TDX_ATTEST_SUCCESS = 0)
        """
        import ctypes

        assert len(report_data) == 64

        quote_ptr = ctypes.c_char_p()
        quote_size = ctypes.c_uint32(0)

        ret = self._libtdx.tdx_attest_get_quote(
            ctypes.c_char_p(report_data),
            None,
            None,
            ctypes.byref(quote_ptr),
            ctypes.byref(quote_size),
            0,
        )

        if ret != 0:
            raise TdxQuoteError(f"tdx_attest_get_quote failed: error code {ret:#010x}")

        quote_bytes = bytes(quote_ptr.value[: quote_size.value])

        # Free the quote buffer allocated by the library
        self._libtdx.tdx_attest_free_quote(quote_ptr)

        return quote_bytes

    def _extract_measurement(self, raw_quote: bytes) -> str:
        """
        Extract MRTD (measurement register) from a TDX quote.

        TDX quote layout (v4):
          Offset 0:    Quote header (48 bytes)
          Offset 48:   TD Report body (584 bytes)
            Offset 48+512: MRTD (48 bytes) — SHA-384
        """
        mrtd_offset = 48 + 512
        mrtd = raw_quote[mrtd_offset: mrtd_offset + 48]
        return mrtd.hex()

    def _extract_platform_id(self, raw_quote: bytes) -> str:
        """
        Extract a platform-unique identifier from a TDX quote.

        Uses TEE_TCB_SVN (16 bytes at offset 48+0) + MRSEAM (48 bytes at offset
        48+16) from the TD Report body. MRSEAM is the measurement of the Intel
        TDX module — combined with TCB SVN, this identifies the specific platform
        and TDX module version.

        For stronger per-chip uniqueness, the PCK certificate's PPID (Platform
        Provisioning ID) should be extracted during DCAP chain verification (M002).
        """
        import hashlib

        # TD Report body starts at offset 48 in the quote
        td_report_offset = 48
        # TEE_TCB_SVN: 16 bytes at TD Report body offset 0
        tee_tcb_svn = raw_quote[td_report_offset: td_report_offset + 16]
        # MRSEAM: 48 bytes at TD Report body offset 16
        mrseam = raw_quote[td_report_offset + 16: td_report_offset + 16 + 48]
        # QE_VENDOR_ID: 16 bytes at quote header offset 32
        qe_vendor_id = raw_quote[32:48]

        # Hash the combination to produce a fixed-size platform ID
        composite = tee_tcb_svn + mrseam + qe_vendor_id
        return hashlib.sha256(composite).hexdigest()

    def _is_debug_mode(self, raw_quote: bytes) -> bool:
        """
        Check TD_ATTRIBUTES.debug bit in the quote.

        TD_ATTRIBUTES is at offset 48+272 (8 bytes); bit 0 is the debug flag.
        """
        td_attr_offset = 48 + 272
        td_attributes = int.from_bytes(raw_quote[td_attr_offset: td_attr_offset + 8], "little")
        return bool(td_attributes & 0x1)


class TdxNotAvailableError(RuntimeError):
    """Raised when TDX hardware or driver is not available."""


class TdxQuoteError(RuntimeError):
    """Raised when TDX quote generation fails."""
