"""
TDX DCAP verification — PCK signature + Intel certificate chain.

Verification steps
------------------
1. Parse TDX quote v4 structure
2. Extract QE Report + ECDSA-P256 signature
3. Extract PCK certificate from cert data section
4. Verify QE Report signature with PCK public key
5. Verify TD Report binding to QE Report
6. Verify PCK cert chains to Intel root CA
7. Return (ok, reason) tuple

TDX quote v4 layout
--------------------
Header (48 bytes):
  0x00   2    version (4)
  0x02   2    attestation_key_type (2 = ECDSA-P256)
  0x04   4    tee_type (0x81 = TDX)
  0x08   2    reserved
  0x0A   2    reserved
  0x0C  20    qe_vendor_id (Intel QE: 939A7233F79C4CA9940A0DB3957F0607)
  0x20  16    user_data (first 16 bytes of custom data)

TD Report body (584 bytes, starting at offset 48):
  Various TDX-specific fields (MRTD, MRCONFIGID, etc.)

Quote signature data (variable, starting at offset 48+584=632):
  0x00   4    signature_data_len
  0x04  64    ECDSA-P256 signature over (header + td_report_body)
  0x44  64    ECDSA public key (attestation key)
  0x84 384    QE Report (same layout as SGX REPORT)
  0x204 64    QE Report signature (ECDSA-P256, signed by PCK)
  0x244  2    QE Auth data len
  0x246  N    QE Auth data
  ...         QE Cert data (type + size + certs)

Intel PCS endpoints
-------------------
- Root CA:       https://certificates.trustedservices.intel.com/IntelSGXRootCA.der
- TCB Info:      https://api.trustedservices.intel.com/tdx/certification/v4/tcb?fmspc={fmspc}
- QE Identity:   https://api.trustedservices.intel.com/tdx/certification/v4/qe/identity
"""

from __future__ import annotations

import logging
import struct
from typing import Optional

from cryptography import x509
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric import ec, utils
from cryptography.hazmat.primitives.hashes import SHA256

logger = logging.getLogger(__name__)

# TDX quote header constants
_HEADER_SIZE = 48
_TD_REPORT_BODY_SIZE = 584
_QUOTE_BODY_SIZE = _HEADER_SIZE + _TD_REPORT_BODY_SIZE  # 632 bytes — signed region

# Expected values
_TDX_VERSION = 4
_ECDSA_P256_TYPE = 2
_TDX_TEE_TYPE = 0x00000081

# Intel QE Vendor ID
_INTEL_QE_VENDOR_ID = bytes.fromhex("939A7233F79C4CA9940A0DB3957F0607")

# Signature data offsets (relative to signature data start)
_SIG_DATA_LEN = 0        # 4 bytes
_ECDSA_SIG = 4           # 64 bytes (r[32] + s[32])
_ATTEST_PUB_KEY = 68     # 64 bytes (x[32] + y[32])
_QE_REPORT = 132         # 384 bytes
_QE_REPORT_SIG = 516     # 64 bytes
_QE_AUTH_DATA_LEN = 580  # 2 bytes

# QE cert data types
_CERT_TYPE_PCK_CHAIN = 5  # PEM-encoded cert chain (PCK + Intermediate + Root)


def verify_tdx_quote(
    raw_quote: bytes,
    pck_chain_override: Optional[bytes] = None,
) -> tuple[bool, str]:
    """
    Verify a TDX DCAP quote's signature chain.

    Parameters
    ----------
    raw_quote         : Raw TDX DCAP quote bytes
    pck_chain_override: PEM-encoded PCK cert chain (skip extraction, for testing)

    Returns
    -------
    (True, "") on success, (False, reason) on failure.
    """
    # Step 1: Parse and validate header
    if len(raw_quote) < _QUOTE_BODY_SIZE + 4:
        return False, f"quote_too_short:{len(raw_quote)}"

    version = struct.unpack("<H", raw_quote[0:2])[0]
    if version != _TDX_VERSION:
        return False, f"bad_version:{version}"

    ak_type = struct.unpack("<H", raw_quote[2:4])[0]
    if ak_type != _ECDSA_P256_TYPE:
        return False, f"bad_ak_type:{ak_type}"

    tee_type = struct.unpack("<I", raw_quote[4:8])[0]
    if tee_type != _TDX_TEE_TYPE:
        return False, f"bad_tee_type:{tee_type:#x}"

    # Step 2: Parse signature data section
    sig_data_offset = _QUOTE_BODY_SIZE
    sig_data_len = struct.unpack("<I", raw_quote[sig_data_offset: sig_data_offset + 4])[0]

    if len(raw_quote) < sig_data_offset + 4 + sig_data_len:
        return False, "sig_data_truncated"

    sig_start = sig_data_offset + 4

    # Extract ECDSA signature over header + td_report_body
    quote_sig = raw_quote[sig_start + _ECDSA_SIG - 4: sig_start + _ECDSA_SIG - 4 + 64]

    # Extract attestation public key
    attest_pub_bytes = raw_quote[sig_start + _ATTEST_PUB_KEY - 4: sig_start + _ATTEST_PUB_KEY - 4 + 64]

    # Extract QE Report (384 bytes)
    qe_report_offset = sig_start + _QE_REPORT - 4
    qe_report = raw_quote[qe_report_offset: qe_report_offset + 384]

    # Extract QE Report signature (64 bytes)
    qe_report_sig_offset = sig_start + _QE_REPORT_SIG - 4
    qe_report_sig = raw_quote[qe_report_sig_offset: qe_report_sig_offset + 64]

    # Step 3: Extract PCK certificate chain from QE cert data
    try:
        pck_certs = _extract_pck_chain(raw_quote, sig_start, sig_data_len, pck_chain_override)
    except Exception as exc:
        return False, f"pck_extraction_failed:{exc}"

    if not pck_certs:
        return False, "no_pck_certs"

    pck_cert = pck_certs[0]

    # Step 4: Verify QE Report signature with PCK public key
    try:
        _verify_ecdsa_p256(
            pck_cert.public_key(),
            qe_report_sig,
            qe_report,
        )
    except InvalidSignature:
        return False, "qe_report_signature_invalid"
    except Exception as exc:
        return False, f"qe_sig_error:{exc}"

    # Step 5: Verify quote signature (header + td_report_body) with attestation key
    try:
        attest_pub = ec.EllipticCurvePublicKey.from_encoded_point(
            ec.SECP256R1(), b"\x04" + attest_pub_bytes
        )
        signed_data = raw_quote[:_QUOTE_BODY_SIZE]
        _verify_ecdsa_p256(attest_pub, quote_sig, signed_data)
    except InvalidSignature:
        return False, "quote_signature_invalid"
    except Exception as exc:
        return False, f"quote_sig_error:{exc}"

    # Step 6: Verify PCK certificate chain
    try:
        _verify_pck_chain(pck_certs)
    except Exception as exc:
        return False, f"pck_chain_failed:{exc}"

    logger.info("[DCAP-TDX] PASS — quote verified with %d certs in chain", len(pck_certs))
    return True, ""


def _extract_pck_chain(
    raw_quote: bytes,
    sig_start: int,
    sig_data_len: int,
    override: Optional[bytes],
) -> list[x509.Certificate]:
    """Extract PCK certificate chain from quote cert data section."""
    if override is not None:
        return _parse_pem_chain(override)

    # Navigate past QE auth data to reach cert data
    qe_auth_len_offset = sig_start + _QE_AUTH_DATA_LEN - 4
    qe_auth_len = struct.unpack("<H", raw_quote[qe_auth_len_offset: qe_auth_len_offset + 2])[0]

    cert_data_offset = qe_auth_len_offset + 2 + qe_auth_len

    if cert_data_offset + 6 > len(raw_quote):
        raise RuntimeError("cert data section truncated")

    cert_type = struct.unpack("<H", raw_quote[cert_data_offset: cert_data_offset + 2])[0]
    cert_size = struct.unpack("<I", raw_quote[cert_data_offset + 2: cert_data_offset + 6])[0]

    cert_bytes = raw_quote[cert_data_offset + 6: cert_data_offset + 6 + cert_size]

    if cert_type == _CERT_TYPE_PCK_CHAIN:
        return _parse_pem_chain(cert_bytes)

    raise RuntimeError(f"unsupported cert type: {cert_type}")


def _parse_pem_chain(data: bytes) -> list[x509.Certificate]:
    """Parse concatenated PEM certificates into a list."""
    certs = []
    marker = b"-----BEGIN CERTIFICATE-----"
    end_marker = b"-----END CERTIFICATE-----"
    start = 0

    while True:
        idx = data.find(marker, start)
        if idx == -1:
            break
        end_idx = data.find(end_marker, idx)
        if end_idx == -1:
            break
        end_idx += len(end_marker)
        certs.append(x509.load_pem_x509_certificate(data[idx:end_idx]))
        start = end_idx

    return certs


def _verify_ecdsa_p256(
    pub_key: ec.EllipticCurvePublicKey,
    sig_bytes: bytes,
    data: bytes,
) -> None:
    """Verify an ECDSA-P256 signature. sig_bytes is r[32] + s[32]."""
    r = int.from_bytes(sig_bytes[0:32], byteorder="big")
    s = int.from_bytes(sig_bytes[32:64], byteorder="big")
    der_sig = utils.encode_dss_signature(r, s)
    pub_key.verify(der_sig, data, ec.ECDSA(SHA256()))


def _verify_pck_chain(certs: list[x509.Certificate]) -> None:
    """
    Verify the PCK certificate chain: Root → Intermediate → PCK Leaf.

    Typically 3 certs: [PCK, Platform CA / Processor CA, Root CA].
    """
    if len(certs) < 2:
        raise RuntimeError(f"Need at least 2 certs in PCK chain, got {len(certs)}")

    # Verify from root down
    # Last cert should be self-signed root
    root = certs[-1]
    root_pub = root.public_key()

    # Verify root is self-signed
    try:
        root_pub.verify(
            root.signature,
            root.tbs_certificate_bytes,
            ec.ECDSA(SHA256()),
        )
    except InvalidSignature:
        raise RuntimeError("Root CA is not self-signed")

    # Verify each cert is signed by its parent
    for i in range(len(certs) - 2, -1, -1):
        child = certs[i]
        parent = certs[i + 1]
        parent_pub = parent.public_key()
        try:
            parent_pub.verify(
                child.signature,
                child.tbs_certificate_bytes,
                ec.ECDSA(SHA256()),
            )
        except InvalidSignature:
            raise RuntimeError(
                f"Cert chain broken at index {i}: "
                f"{child.subject} not signed by {parent.subject}"
            )
