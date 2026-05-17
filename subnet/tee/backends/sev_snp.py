"""
SevSnpBackend — AMD SEV-SNP attestation report generation.

Requirements
------------
- AMD EPYC Genoa/Milan with SEV-SNP enabled in BIOS
- Linux kernel 5.19+ with sev-guest driver
- /dev/sev-guest device accessible
- sevsnpattest or sev-guest-tool installed

How SEV-SNP attestation works
------------------------------
1. Caller writes 64-byte user_data into the report request
   (we use sha256(peer_id:epoch) zero-padded — same binding as TDX)
2. PSP (Platform Security Processor) generates an attestation report
3. Report contains: measurement (SHA-384), user_data, platform info
4. Report is signed by the VCEK (Versioned Chip Endorsement Key)
5. VCEK cert chain leads to AMD root CA

SEV-SNP vs TDX differences
---------------------------
- SEV-SNP: /dev/sev-guest ioctl SNP_GET_REPORT
- TDX:     /dev/tdx_guest ioctl TDX_CMD_GET_QUOTE (via QE)
- Both produce a 384-byte measurement (SHA-384 of the initial guest image)
- Both bind user_data / report_data to the quote — same binding contract

Schema normalisation
--------------------
SevSnpBackend returns the same TeeQuote schema as TdxBackend.
The `backend` field distinguishes them for the verifier.
"""

from __future__ import annotations

import logging
import struct
import time

from subnet.tee.backends.base import TeeBackendBase
from subnet.tee.quote import TeeBackend, TeeQuote, TcbStatus

logger = logging.getLogger(__name__)

# SNP_GET_REPORT ioctl number (Linux 5.19+, arch/x86/include/uapi/asm/sev.h)
SNP_GET_REPORT = 0xC0185300  # _IOWR(0x53, 0x0, snp_report_req)

# SNP attestation report offsets (AMD SEV-SNP ABI spec, version 1.55)
SNP_REPORT_VERSION_OFFSET = 0
SNP_REPORT_MEASUREMENT_OFFSET = 0x90  # 48 bytes (SHA-384)
SNP_REPORT_HOST_DATA_OFFSET = 0xC0   # 32 bytes (our user_data / binding)
SNP_REPORT_POLICY_OFFSET = 0x08      # 8 bytes (debug bit is bit 19)
SNP_REPORT_CHIP_ID_OFFSET = 0x1A0    # 64 bytes — unique per physical AMD EPYC CPU


class SevSnpBackend(TeeBackendBase):
    """
    AMD SEV-SNP attestation backend.

    Requires /dev/sev-guest and AMD EPYC with SEV-SNP.
    On non-SEV-SNP hardware, raises SevSnpNotAvailableError at init.

    For CI / development use MockBackend with MOCK_TEE=true.
    """

    def __init__(self) -> None:
        self._check_availability()

    def _check_availability(self) -> None:
        import os

        if not os.path.exists("/dev/sev-guest"):
            raise SevSnpNotAvailableError(
                "/dev/sev-guest not found. "
                "SEV-SNP is not available on this host. "
                "Use MOCK_TEE=true for development."
            )
        logger.info("[SevSnpBackend] /dev/sev-guest available")

    @property
    def backend_name(self) -> str:
        return TeeBackend.SEV_SNP.value

    def generate_quote(
        self,
        peer_id: str,
        epoch: int,
        cert_pubkey_hash: bytes | None = None,
    ) -> TeeQuote:
        """
        Generate a SEV-SNP attestation report bound to (peer_id, epoch).

        Calls SNP_GET_REPORT ioctl with report_data = sha256(peer_id:epoch) || sha256(cert_pubkey_der).
        """
        report_data = TeeQuote.make_report_data(peer_id, epoch, cert_pubkey_hash=cert_pubkey_hash)  # 64 bytes
        raw_report = self._get_snp_report(report_data)

        measurement_hex = self._extract_measurement(raw_report)
        debug = self._is_debug_mode(raw_report)
        chip_id = self._extract_chip_id(raw_report)

        from subnet.tee.tcb import extract_tcb_sev_snp
        tcb = extract_tcb_sev_snp(raw_report)

        return TeeQuote(
            backend=TeeBackend.SEV_SNP,
            measurement=measurement_hex,
            report_data=report_data.hex(),
            nonce=epoch,
            peer_id=peer_id,
            timestamp=time.time(),
            debug_mode=debug,
            tcb_status=TcbStatus.UNKNOWN,
            sig="",
            raw_bytes=raw_report,
            hardware_id=chip_id,
            tcb_version=tcb.to_dict(),
        )

    def _get_snp_report(self, report_data: bytes) -> bytes:
        """
        Issue SNP_GET_REPORT ioctl to /dev/sev-guest.

        snp_report_req layout (96 bytes):
          u8  user_data[64]   — our binding (sha256(peer_id:epoch) zero-padded)
          u32 vmpl            — VMPL level (0 = most privileged)
          u8  rsvd[28]        — reserved, must be zero

        Returns raw attestation report (1184 bytes).
        """
        import array
        import fcntl

        assert len(report_data) == 64

        # Build request: 64-byte user_data + u32 vmpl + 28 zero bytes
        req = report_data + struct.pack("<I", 0) + b"\x00" * 28
        assert len(req) == 96

        # Response buffer: 4000 bytes (report + certs)
        resp = array.array("B", b"\x00" * 4000)

        # Pack into ioctl buffer: req (96) + resp (4000)
        buf = array.array("B", req) + resp

        with open("/dev/sev-guest", "rb") as fd:
            fcntl.ioctl(fd, SNP_GET_REPORT, buf)

        # Response starts at offset 96
        return bytes(buf[96: 96 + 1184])

    def _extract_measurement(self, raw_report: bytes) -> str:
        """Extract SHA-384 measurement from SEV-SNP attestation report."""
        meas = raw_report[SNP_REPORT_MEASUREMENT_OFFSET: SNP_REPORT_MEASUREMENT_OFFSET + 48]
        return meas.hex()

    def _extract_chip_id(self, raw_report: bytes) -> str:
        """Extract CHIP_ID from SEV-SNP attestation report.

        CHIP_ID is 64 bytes at offset 0x1A0 — derived from the VCEK,
        uniquely identifies the physical AMD EPYC processor.
        """
        chip_id = raw_report[SNP_REPORT_CHIP_ID_OFFSET: SNP_REPORT_CHIP_ID_OFFSET + 64]
        return chip_id.hex()

    def _is_debug_mode(self, raw_report: bytes) -> bool:
        """
        Check POLICY.debug bit (bit 19) in the SEV-SNP attestation report.

        AMD SEV-SNP spec: POLICY field at offset 0x08, 8 bytes little-endian.
        Bit 19 = debug_swap (allows debug register inspection by hypervisor).
        """
        policy = int.from_bytes(
            raw_report[SNP_REPORT_POLICY_OFFSET: SNP_REPORT_POLICY_OFFSET + 8],
            "little",
        )
        return bool(policy & (1 << 19))


class SevSnpNotAvailableError(RuntimeError):
    """Raised when SEV-SNP hardware or driver is not available."""


class SevSnpReportError(RuntimeError):
    """Raised when SEV-SNP report generation fails."""
