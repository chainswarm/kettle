"""
Tests for SEV-SNP DCAP signature verification.

Tests the cryptographic verification path using synthetic certificates
and reports. Real CVM integration tests are separate (require hardware).
"""

import struct

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, utils
from cryptography.x509.oid import NameOID

from subnet.tee.dcap.sev_snp import (
    verify_sev_snp_report,
    _pem_split,
    _verify_report_signature,
)

# ---------------------------------------------------------------------------
# Test certificate helpers
# ---------------------------------------------------------------------------


def _make_ec_key(curve=ec.SECP384R1()):
    return ec.generate_private_key(curve)


def _make_self_signed_cert(key, cn="Test CA", issuer_key=None, issuer_name=None):
    """Create a self-signed or issuer-signed X.509 cert."""
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, cn)])
    builder = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer_name or subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(
            __import__("datetime").datetime(2025, 1, 1, tzinfo=__import__("datetime").timezone.utc)
        )
        .not_valid_after(
            __import__("datetime").datetime(2030, 1, 1, tzinfo=__import__("datetime").timezone.utc)
        )
    )
    sign_key = issuer_key or key
    return builder.sign(sign_key, hashes.SHA384())


def _build_test_cert_chain():
    """Build ARK → ASK → VCEK chain with ECDSA-P384 keys."""
    # ARK (self-signed root)
    ark_key = _make_ec_key()
    ark_cert = _make_self_signed_cert(ark_key, cn="AMD Root Key")

    # ASK (signed by ARK)
    ask_key = _make_ec_key()
    ask_cert = _make_self_signed_cert(
        ask_key, cn="AMD SEV Key",
        issuer_key=ark_key,
        issuer_name=ark_cert.subject,
    )

    # VCEK (signed by ASK)
    vcek_key = _make_ec_key()
    vcek_cert = _make_self_signed_cert(
        vcek_key, cn="AMD VCEK",
        issuer_key=ask_key,
        issuer_name=ask_cert.subject,
    )

    return ark_key, ark_cert, ask_key, ask_cert, vcek_key, vcek_cert


def _build_fake_snp_report(vcek_key, sig_algo=1):
    """Build a minimal valid SNP report signed by the given VCEK key."""
    # 1184-byte report
    report = bytearray(1184)

    # Version = 2
    struct.pack_into("<I", report, 0x00, 2)

    # Policy (no debug)
    struct.pack_into("<Q", report, 0x08, 0)

    # Signature algorithm (1 = ECDSA-P384)
    struct.pack_into("<I", report, 0x034, sig_algo)

    # Measurement (non-zero)
    report[0x90:0x90 + 48] = b"\xAA" * 48

    # CHIP_ID
    report[0x1A0:0x1A0 + 64] = b"\xBB" * 64

    # REPORTED_TCB (bl=1, tee=2, snp=3, ucode=4)
    report[0x180] = 1  # bl
    report[0x181] = 2  # tee
    report[0x186] = 3  # snp
    report[0x187] = 4  # ucode

    # Set sig_block_algo at 0x2A0 to 1 (ECDSA-P384) — tells verifier to check signature
    struct.pack_into("<I", report, 0x2A0, 1)

    # Sign the report [0:0x2A0] with VCEK key (ECDSA-P384)
    signed_region = bytes(report[:0x2A0])
    signature = vcek_key.sign(signed_region, ec.ECDSA(hashes.SHA384()))

    # Decode DER signature to (r, s)
    r, s = utils.decode_dss_signature(signature)

    # Store r and s as little-endian 48-byte values at offset 0x2A4
    report[0x2A4:0x2A4 + 48] = r.to_bytes(48, byteorder="little")
    report[0x2A4 + 48:0x2A4 + 96] = s.to_bytes(48, byteorder="little")

    return bytes(report)


def _certs_to_pem(*certs):
    """Concatenate certificates as PEM."""
    pem = b""
    for cert in certs:
        pem += cert.public_bytes(serialization.Encoding.PEM)
    return pem


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestSnpReportSignature:
    """Test VCEK signature verification on synthetic reports."""

    def test_valid_signature_passes(self):
        ark_key, ark_cert, ask_key, ask_cert, vcek_key, vcek_cert = _build_test_cert_chain()
        report = _build_fake_snp_report(vcek_key)
        chain_pem = _certs_to_pem(ask_cert, ark_cert)

        ok, reason = verify_sev_snp_report(
            report,
            vcek_cert_override=vcek_cert.public_bytes(serialization.Encoding.DER),
            cert_chain_override=chain_pem,
        )
        assert ok is True, f"Expected pass, got: {reason}"

    def test_tampered_report_fails(self):
        ark_key, ark_cert, ask_key, ask_cert, vcek_key, vcek_cert = _build_test_cert_chain()
        report = bytearray(_build_fake_snp_report(vcek_key))

        # Tamper with measurement after signing
        report[0x90] = 0xFF

        chain_pem = _certs_to_pem(ask_cert, ark_cert)

        ok, reason = verify_sev_snp_report(
            bytes(report),
            vcek_cert_override=vcek_cert.public_bytes(serialization.Encoding.DER),
            cert_chain_override=chain_pem,
        )
        assert ok is False
        assert "signature_invalid" in reason

    def test_wrong_vcek_key_fails(self):
        ark_key, ark_cert, ask_key, ask_cert, vcek_key, vcek_cert = _build_test_cert_chain()
        # Sign with the real key
        report = _build_fake_snp_report(vcek_key)

        # But provide a different VCEK cert for verification
        wrong_key = _make_ec_key()
        wrong_cert = _make_self_signed_cert(
            wrong_key, cn="Wrong VCEK",
            issuer_key=ask_key,
            issuer_name=ask_cert.subject,
        )
        chain_pem = _certs_to_pem(ask_cert, ark_cert)

        ok, reason = verify_sev_snp_report(
            report,
            vcek_cert_override=wrong_cert.public_bytes(serialization.Encoding.DER),
            cert_chain_override=chain_pem,
        )
        assert ok is False
        assert "signature_invalid" in reason


class TestCertChainValidation:
    """Test AMD cert chain (ARK → ASK → VCEK) validation."""

    def test_broken_chain_fails(self):
        ark_key, ark_cert, ask_key, ask_cert, vcek_key, vcek_cert = _build_test_cert_chain()
        report = _build_fake_snp_report(vcek_key)

        # Provide a different ARK that didn't sign the ASK
        rogue_ark_key = _make_ec_key()
        rogue_ark_cert = _make_self_signed_cert(rogue_ark_key, cn="Rogue Root")

        chain_pem = _certs_to_pem(ask_cert, rogue_ark_cert)

        ok, reason = verify_sev_snp_report(
            report,
            vcek_cert_override=vcek_cert.public_bytes(serialization.Encoding.DER),
            cert_chain_override=chain_pem,
        )
        assert ok is False
        assert "cert_chain_failed" in reason


class TestAzureVtpmPath:
    """Azure CVM reports have all-zero signature block — skip VCEK signature check."""

    def test_sig_block_algo_zero_passes(self):
        """sig_block_algo=0 at offset 0x2A0 → Azure vTPM path, skip crypto."""
        report = bytearray(1184)
        struct.pack_into("<I", report, 0x00, 2)  # version
        struct.pack_into("<I", report, 0x034, 2)  # header sig_algo (PSP used ECDSA)
        report[0x90:0x90 + 48] = b"\xAA" * 48  # non-zero measurement
        # sig_block_algo at 0x2A0 = 0 (bytearray default) → Azure path

        ok, reason = verify_sev_snp_report(bytes(report))
        assert ok is True, f"Expected pass, got: {reason}"


class TestStructuralRejects:
    """Reports that fail before signature verification."""

    def test_short_report(self):
        ok, reason = verify_sev_snp_report(b"\x00" * 100)
        assert ok is False
        assert "report_too_short" in reason

    def test_bad_version(self):
        report = bytearray(1184)
        struct.pack_into("<I", report, 0x00, 99)
        ok, reason = verify_sev_snp_report(bytes(report))
        assert ok is False
        assert "bad_version" in reason

    def test_unsupported_sig_algo(self):
        report = bytearray(1184)
        struct.pack_into("<I", report, 0x00, 2)  # version
        struct.pack_into("<I", report, 0x2A0, 99)  # sig_block_algo = unsupported
        ok, reason = verify_sev_snp_report(bytes(report))
        assert ok is False
        assert "unsupported_sig_algo" in reason


class TestPemSplit:
    """Test PEM certificate splitting utility."""

    def test_splits_two_certs(self):
        key1 = _make_ec_key()
        key2 = _make_ec_key()
        cert1 = _make_self_signed_cert(key1, cn="Cert1")
        cert2 = _make_self_signed_cert(key2, cn="Cert2")

        combined = _certs_to_pem(cert1, cert2)
        blocks = _pem_split(combined)
        assert len(blocks) == 2

    def test_empty_input(self):
        assert _pem_split(b"") == []
