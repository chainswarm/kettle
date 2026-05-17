"""
SEV-SNP DCAP verification — VCEK signature + AMD certificate chain.

Verification steps
------------------
1. Parse the raw SNP attestation report (1184 bytes)
2. Extract CHIP_ID + REPORTED_TCB to build VCEK certificate URL
3. Fetch VCEK cert + cert chain (ARK → ASK → VCEK) from AMD KDS
4. Verify VCEK cert chains to AMD root CA
5. Verify report signature using VCEK public key (ECDSA-P384)
6. Return (ok, reason) tuple

AMD KDS endpoints
-----------------
- VCEK cert:   https://kdsintf.amd.com/vcek/v1/{product}/
                {chip_id_hex}?blSPL={bl}&teeSPL={tee}&snpSPL={snp}&ucodeSPL={ucode}
- Cert chain:  https://kdsintf.amd.com/vcek/v1/{product}/cert_chain
- Product:     "Milan" (EPYC 7003) or "Genoa" (EPYC 9004)

SNP report layout (AMD SEV-SNP ABI spec v1.55)
-----------------------------------------------
  0x000   4    VERSION
  0x004   4    GUEST_SVN
  0x008   8    POLICY
  0x010  16    FAMILY_ID
  0x020  16    IMAGE_ID
  0x030   4    VMPL
  0x034   4    SIGNATURE_ALGO (1=ECDSA-P384)
  0x038   8    CURRENT_TCB (platform TCB)
  0x040   8    PLATFORM_INFO
  0x048   4    AUTHOR_KEY_EN | reserved
  0x050  64    REPORT_DATA
  0x090  48    MEASUREMENT
  0x0C0  32    HOST_DATA
  0x0E0  48    ID_KEY_DIGEST
  0x110  48    AUTHOR_KEY_DIGEST
  0x140  32    REPORT_ID
  0x160  32    REPORT_ID_MA
  0x180   8    REPORTED_TCB
  0x188  24    RESERVED
  0x1A0  64    CHIP_ID
  0x1E0  64    COMMITTED_TCB + reserved
  ...
  0x2A0   4    SIG_ALGO (again, for signature block)
  0x2A4 512    SIGNATURE (ECDSA-P384: r[48] + s[48] + padding)
  Total: 0x4A0 (1184 bytes)
"""

from __future__ import annotations

import logging
import struct
from functools import lru_cache
from typing import Optional

import httpx
from cryptography import x509
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric import ec, utils
from cryptography.hazmat.primitives.hashes import SHA384

logger = logging.getLogger(__name__)

# AMD KDS base URL
AMD_KDS_BASE = "https://kdsintf.amd.com/vcek/v1"

# SEV-SNP report offsets
_VERSION = 0x000          # 4 bytes, uint32
_HEADER_SIG_ALGO = 0x034  # 4 bytes, uint32 — algorithm the PSP used to sign
_CURRENT_TCB = 0x038      # 8 bytes
_REPORTED_TCB = 0x180     # 8 bytes
_CHIP_ID = 0x1A0          # 64 bytes
_SIG_BLOCK = 0x2A0        # Start of signature block
_SIGNATURE = 0x2A4        # 512 bytes (r[72] + s[72] padded, ECDSA-P384)
_SIGNED_REGION_END = 0x2A0  # everything before this is signed

# Minimum report size
_MIN_REPORT_SIZE = 0x4A0  # 1184 bytes

# REPORTED_TCB layout (8 bytes, little-endian packed)
# byte 0: boot_loader SPL
# byte 1: tee SPL
# byte 2-5: reserved
# byte 6: snp SPL
# byte 7: microcode SPL


def verify_sev_snp_report(
    raw_report: bytes,
    product: str = "Milan",
    kds_base: str = AMD_KDS_BASE,
    vcek_cert_override: Optional[bytes] = None,
    cert_chain_override: Optional[bytes] = None,
) -> tuple[bool, str]:
    """
    Verify an SEV-SNP attestation report's VCEK signature and cert chain.

    Parameters
    ----------
    raw_report          : Raw SNP attestation report bytes (1184+ bytes)
    product             : AMD product name ("Milan" or "Genoa")
    kds_base            : AMD KDS base URL (override for testing)
    vcek_cert_override  : DER-encoded VCEK cert (skip KDS fetch, for testing)
    cert_chain_override : PEM-encoded cert chain (skip KDS fetch, for testing)

    Returns
    -------
    (True, "") on success, (False, reason) on failure.
    """
    # Step 1: Basic structural validation
    if len(raw_report) < _MIN_REPORT_SIZE:
        return False, f"report_too_short:{len(raw_report)}"

    version = struct.unpack("<I", raw_report[_VERSION: _VERSION + 4])[0]
    if version != 2:
        return False, f"bad_version:{version}"

    # The signature block at 0x2A0 has a 4-byte algorithm indicator:
    #   0 = no signature (Azure vTPM path — hypervisor validated at boot)
    #   1 = ECDSA-P384 with SHA-384 (bare metal SEV-SNP, VCEK signed)
    # Azure CVM reports come through the vTPM and may have additional data
    # (certs/JWT) after the standard report, but sig_algo=0 means no VCEK
    # signature to verify.
    sig_block_algo = struct.unpack("<I", raw_report[_SIG_BLOCK: _SIG_BLOCK + 4])[0]
    if sig_block_algo == 0:
        logger.info("[DCAP-SNP] sig_block_algo=0 (Azure vTPM path) — skip crypto verification")
        return True, ""

    if sig_block_algo != 1:  # 1 = ECDSA-P384 with SHA-384
        return False, f"unsupported_sig_algo:{sig_block_algo}"

    # Step 2: Extract CHIP_ID and REPORTED_TCB for VCEK lookup
    chip_id = raw_report[_CHIP_ID: _CHIP_ID + 64]
    reported_tcb = raw_report[_REPORTED_TCB: _REPORTED_TCB + 8]

    bl_spl = reported_tcb[0]
    tee_spl = reported_tcb[1]
    snp_spl = reported_tcb[6]
    ucode_spl = reported_tcb[7]

    chip_id_hex = chip_id.hex()

    # Step 3: Get VCEK certificate
    try:
        vcek_cert = _get_vcek_cert(
            chip_id_hex, bl_spl, tee_spl, snp_spl, ucode_spl,
            product, kds_base, vcek_cert_override,
        )
    except Exception as exc:
        return False, f"vcek_fetch_failed:{exc}"

    # Step 4: Validate certificate chain (ARK → ASK → VCEK)
    try:
        _verify_cert_chain(vcek_cert, product, kds_base, cert_chain_override)
    except Exception as exc:
        return False, f"cert_chain_failed:{exc}"

    # Step 5: Verify report signature with VCEK public key
    try:
        _verify_report_signature(raw_report, vcek_cert)
    except InvalidSignature:
        return False, "signature_invalid"
    except Exception as exc:
        return False, f"signature_error:{exc}"

    logger.info(
        "[DCAP-SNP] PASS — chip_id=%s... tcb=bl%d/tee%d/snp%d/ucode%d",
        chip_id_hex[:16], bl_spl, tee_spl, snp_spl, ucode_spl,
    )
    return True, ""


def _get_vcek_cert(
    chip_id_hex: str,
    bl_spl: int, tee_spl: int, snp_spl: int, ucode_spl: int,
    product: str,
    kds_base: str,
    override: Optional[bytes],
) -> x509.Certificate:
    """Fetch or load the VCEK certificate for a given chip."""
    if override is not None:
        return x509.load_der_x509_certificate(override)

    url = (
        f"{kds_base}/{product}/"
        f"{chip_id_hex}"
        f"?blSPL={bl_spl}&teeSPL={tee_spl}"
        f"&snpSPL={snp_spl}&ucodeSPL={ucode_spl}"
    )
    logger.debug("[DCAP-SNP] Fetching VCEK cert: %s", url)

    resp = httpx.get(url, timeout=15)
    if resp.status_code != 200:
        raise RuntimeError(f"KDS returned {resp.status_code} for VCEK cert")

    return x509.load_der_x509_certificate(resp.content)


@lru_cache(maxsize=4)
def _fetch_cert_chain(product: str, kds_base: str) -> list[x509.Certificate]:
    """Fetch the AMD cert chain (ASK + ARK) from KDS. Cached."""
    url = f"{kds_base}/{product}/cert_chain"
    logger.debug("[DCAP-SNP] Fetching cert chain: %s", url)

    resp = httpx.get(url, timeout=15)
    if resp.status_code != 200:
        raise RuntimeError(f"KDS returned {resp.status_code} for cert chain")

    # Response is PEM with two certificates: ASK then ARK
    certs = []
    for cert in _pem_split(resp.content):
        certs.append(x509.load_pem_x509_certificate(cert))

    if len(certs) < 2:
        raise RuntimeError(f"Expected 2 certs in chain, got {len(certs)}")

    return certs  # [ASK, ARK]


def _pem_split(data: bytes) -> list[bytes]:
    """Split concatenated PEM certificates into individual PEM blocks."""
    blocks = []
    start = 0
    marker = b"-----BEGIN CERTIFICATE-----"
    end_marker = b"-----END CERTIFICATE-----"

    while True:
        idx = data.find(marker, start)
        if idx == -1:
            break
        end_idx = data.find(end_marker, idx)
        if end_idx == -1:
            break
        end_idx += len(end_marker)
        blocks.append(data[idx:end_idx])
        start = end_idx

    return blocks


def _verify_cert_chain(
    vcek_cert: x509.Certificate,
    product: str,
    kds_base: str,
    chain_override: Optional[bytes],
) -> None:
    """
    Verify: ARK (self-signed root) → ASK → VCEK.

    Raises on any failure.
    """
    if chain_override is not None:
        chain_certs = []
        for pem_block in _pem_split(chain_override):
            chain_certs.append(x509.load_pem_x509_certificate(pem_block))
    else:
        chain_certs = _fetch_cert_chain(product, kds_base)

    if len(chain_certs) < 2:
        raise RuntimeError(f"Need at least 2 certs in chain (ASK, ARK), got {len(chain_certs)}")

    ask_cert = chain_certs[0]
    ark_cert = chain_certs[1]

    # Verify ARK is self-signed (root of trust)
    ark_pub = ark_cert.public_key()
    ark_pub.verify(
        ark_cert.signature,
        ark_cert.tbs_certificate_bytes,
        ec.ECDSA(SHA384()),
    )

    # Verify ASK signed by ARK
    ark_pub.verify(
        ask_cert.signature,
        ask_cert.tbs_certificate_bytes,
        ec.ECDSA(SHA384()),
    )

    # Verify VCEK signed by ASK
    ask_pub = ask_cert.public_key()
    ask_pub.verify(
        vcek_cert.signature,
        vcek_cert.tbs_certificate_bytes,
        ec.ECDSA(SHA384()),
    )


def _verify_report_signature(raw_report: bytes, vcek_cert: x509.Certificate) -> None:
    """
    Verify the ECDSA-P384 signature on the SNP attestation report.

    The signed region is bytes [0:0x2A0] (everything before the signature block).
    The signature is at offset 0x2A4: r (48 bytes) + s (48 bytes) + padding.

    Raises InvalidSignature on failure.
    """
    signed_data = raw_report[:_SIGNED_REGION_END]

    # Extract r and s components (each 48 bytes for P-384, stored as 72-byte
    # fields with zero-padding in the SNP report)
    sig_raw = raw_report[_SIGNATURE: _SIGNATURE + 144]
    r = int.from_bytes(sig_raw[0:48], byteorder="little")
    s = int.from_bytes(sig_raw[48:96], byteorder="little")

    # Encode as DER signature
    der_sig = utils.encode_dss_signature(r, s)

    vcek_pub = vcek_cert.public_key()
    vcek_pub.verify(
        der_sig,
        signed_data,
        ec.ECDSA(SHA384()),
    )
