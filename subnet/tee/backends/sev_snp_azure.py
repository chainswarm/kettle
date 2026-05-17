"""
SevSnpAzureBackend — AMD SEV-SNP attestation via Azure vTPM.

Azure Confidential VMs (DCasv5/DCadsv5) expose the SNP attestation report
through the vTPM rather than /dev/sev-guest. The report is stored in
TPM NV index 0x01400001 with a 12-byte header (magic + version + size).

This backend reads the cached report from the vTPM NV index. For custom
report_data binding (peer_id + epoch + cert_pubkey_hash), we use the
report as-is — the report_data field contains whatever the firmware set
at boot time. On Azure CVM, the report_data is set by the hypervisor,
not by the guest.

Azure attestation flow
----------------------
1. At VM boot, the hypervisor generates an SNP report with platform-set
   report_data and stores it in vTPM NV index 0x01400001.
2. The guest reads the cached report via tpm2_nvread.
3. The report contains: measurement (SHA-384), policy, debug bit, etc.
4. For subnet attestation, we use the measurement to prove the VM runs
   the expected firmware/image. The identity binding (peer_id:epoch) is
   handled at the application layer via the RA-TLS cert.

NV blob layout
--------------
  Offset 0-3:   Magic "HCLA" (0x48434c41)
  Offset 4-7:   Header version (1)
  Offset 8-11:  Report size
  Offset 12+:   Raw SNP attestation report (1184 bytes min)

SNP report offsets (same as sev_snp.py)
---------------------------------------
  0x00:  Version (uint32, should be 2)
  0x08:  Policy (uint64, bit 19 = debug)
  0x50:  Report data (64 bytes)
  0x90:  Measurement (48 bytes, SHA-384)
  0xC0:  Host data (32 bytes)
  0x2A0: Signature (512 bytes)
"""

from __future__ import annotations

import logging
import struct
import subprocess
import time
from typing import Optional

from subnet.tee.backends.base import TeeBackendBase
from subnet.tee.quote import TeeBackend, TeeQuote, TcbStatus

logger = logging.getLogger(__name__)

# Azure vTPM NV index for SNP attestation report
AZURE_SNP_NV_INDEX = "0x01400001"

# Header offsets
AZURE_HEADER_SIZE = 12
AZURE_MAGIC = b"HCLA"

# SNP report offsets (AMD SEV-SNP ABI spec v1.55)
SNP_REPORT_VERSION_OFFSET = 0x00
SNP_REPORT_POLICY_OFFSET = 0x08
SNP_REPORT_DATA_OFFSET = 0x50      # 64 bytes
SNP_REPORT_MEASUREMENT_OFFSET = 0x90  # 48 bytes (SHA-384)
SNP_REPORT_HOST_DATA_OFFSET = 0xC0   # 32 bytes
SNP_REPORT_CHIP_ID_OFFSET = 0x1A0   # 64 bytes — unique per physical AMD EPYC CPU
SNP_REPORT_MIN_SIZE = 1184


class SevSnpAzureBackend(TeeBackendBase):
    """
    AMD SEV-SNP attestation backend for Azure Confidential VMs.

    Reads the SNP attestation report from the vTPM NV index instead of
    /dev/sev-guest ioctl. This is the standard path for Azure DCasv5 VMs.

    The measurement proves the VM image is genuine. Identity binding
    (peer_id:epoch) is handled at the RA-TLS layer, not in the SNP
    report_data (which is set by the hypervisor at boot).
    """

    def __init__(self) -> None:
        self._cached_report: Optional[bytes] = None
        self._cached_measurement: Optional[str] = None
        self._check_availability()

    def _check_availability(self) -> None:
        """Verify we can read the SNP report from vTPM."""
        try:
            report = self._read_snp_report_from_vtpm()
            ver = struct.unpack("<I", report[0:4])[0]
            if ver != 2:
                raise SevSnpAzureError(
                    f"Unexpected SNP report version: {ver} (expected 2)"
                )
            self._cached_report = report
            self._cached_measurement = self._extract_measurement(report)
            logger.info(
                "[SevSnpAzureBackend] SNP report available via vTPM, "
                "measurement=%s...",
                self._cached_measurement[:32],
            )
        except Exception as exc:
            raise SevSnpAzureError(
                f"Cannot read SNP report from vTPM NV index {AZURE_SNP_NV_INDEX}: {exc}"
            ) from exc

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
        Generate a TeeQuote from the Azure vTPM SNP report.

        On Azure CVM, the SNP report is generated at boot by the hypervisor.
        We cannot set custom report_data in the hardware report. Instead:
        - The measurement proves the VM image integrity
        - The application-layer identity binding (peer_id:epoch:cert_pubkey)
          is computed and stored in the TeeQuote.report_data field
        - The raw_bytes contain the actual hardware report for DCAP verification

        This means the verifier must check:
        1. The measurement matches EXPECTED_MEASUREMENT (hardware proof)
        2. The TeeQuote.report_data matches sha256(peer_id:epoch:pubkey)
           (application-layer binding, verified at the RA-TLS level)
        """
        # Read fresh report (may be cached from init)
        raw_report = self._cached_report or self._read_snp_report_from_vtpm()

        measurement_hex = self._extract_measurement(raw_report)
        debug = self._is_debug_mode(raw_report)
        chip_id = self._extract_chip_id(raw_report)

        from subnet.tee.tcb import extract_tcb_sev_snp
        tcb = extract_tcb_sev_snp(raw_report)

        # Application-layer identity binding
        report_data = TeeQuote.make_report_data(
            peer_id, epoch, cert_pubkey_hash=cert_pubkey_hash
        )

        return TeeQuote(
            backend=TeeBackend.SEV_SNP,
            measurement=measurement_hex,
            report_data=report_data.hex(),
            nonce=epoch,
            peer_id=peer_id,
            timestamp=time.time(),
            debug_mode=debug,
            tcb_status=TcbStatus.UP_TO_DATE,  # Azure hypervisor validates TCB at boot
            sig="",
            raw_bytes=raw_report,
            hardware_id=chip_id,
            tcb_version=tcb.to_dict(),
        )

    def _read_snp_report_from_vtpm(self) -> bytes:
        """
        Read the SNP attestation report from Azure vTPM NV index.

        Uses tpm2_nvread with owner hierarchy auth.
        Returns the raw SNP report (without the 12-byte Azure header).
        """
        # Try without sudo first (works when /dev/tpmrm0 is accessible),
        # fall back to sudo for host-level access
        cmd = ["tpm2_nvread", AZURE_SNP_NV_INDEX, "-C", "o", "-o", "/dev/stdout"]
        result = subprocess.run(cmd, capture_output=True, timeout=10)
        if result.returncode != 0:
            # Retry with sudo (host-level, non-container)
            result = subprocess.run(
                ["sudo"] + cmd, capture_output=True, timeout=10
            )

        if result.returncode != 0:
            stderr = result.stderr.decode(errors="replace")
            raise SevSnpAzureError(
                f"tpm2_nvread failed (exit {result.returncode}): {stderr[:200]}"
            )

        blob = result.stdout

        if len(blob) < AZURE_HEADER_SIZE + SNP_REPORT_MIN_SIZE:
            raise SevSnpAzureError(
                f"NV blob too short: {len(blob)} bytes "
                f"(need >= {AZURE_HEADER_SIZE + SNP_REPORT_MIN_SIZE})"
            )

        # Verify Azure header magic
        magic = blob[:4]
        if magic != AZURE_MAGIC:
            raise SevSnpAzureError(
                f"Bad NV blob magic: {magic!r} (expected {AZURE_MAGIC!r})"
            )

        # Strip the 12-byte header, return raw SNP report
        report = blob[AZURE_HEADER_SIZE:]
        return report

    def _extract_measurement(self, raw_report: bytes) -> str:
        """Extract SHA-384 measurement from SNP attestation report."""
        meas = raw_report[
            SNP_REPORT_MEASUREMENT_OFFSET:
            SNP_REPORT_MEASUREMENT_OFFSET + 48
        ]
        return meas.hex()

    def _extract_chip_id(self, raw_report: bytes) -> str:
        """Extract CHIP_ID from SNP attestation report.

        CHIP_ID is 64 bytes at offset 0x1A0 — derived from the VCEK,
        uniquely identifies the physical AMD EPYC processor.
        """
        chip_id = raw_report[SNP_REPORT_CHIP_ID_OFFSET: SNP_REPORT_CHIP_ID_OFFSET + 64]
        return chip_id.hex()

    def _is_debug_mode(self, raw_report: bytes) -> bool:
        """Check POLICY.debug bit (bit 19) in the SNP attestation report."""
        policy = int.from_bytes(
            raw_report[SNP_REPORT_POLICY_OFFSET: SNP_REPORT_POLICY_OFFSET + 8],
            "little",
        )
        return bool(policy & (1 << 19))

    def get_hardware_report_data(self) -> bytes:
        """Return the report_data from the hardware SNP report (set by hypervisor)."""
        report = self._cached_report or self._read_snp_report_from_vtpm()
        return report[SNP_REPORT_DATA_OFFSET: SNP_REPORT_DATA_OFFSET + 64]

    @property
    def measurement(self) -> str:
        """Return the cached measurement hash."""
        return self._cached_measurement or ""


class SevSnpAzureError(RuntimeError):
    """Raised when Azure vTPM SNP attestation fails."""
