"""
Tests for TCB version enforcement and CVE-aware rejection.

Covers:
- TcbVersion extraction from synthetic reports
- Known CVE detection (CacheWarp, BadRAM)
- MinTcbPolicy parsing and enforcement
- Verifier integration: reject vulnerable firmware
- Patched firmware passes
- Mock backend skips TCB checks
"""

import pytest

from subnet.tee.tcb import (
    TcbVersion,
    CveCheckResult,
    MinTcbPolicy,
    check_known_cves,
    extract_tcb_sev_snp,
    extract_tcb_tdx,
)


# ---------------------------------------------------------------------------
# TcbVersion unit tests
# ---------------------------------------------------------------------------

class TestTcbVersion:
    def test_sev_snp_str(self):
        tcb = TcbVersion(boot_loader=3, tee=2, snp=20, microcode=170, platform="Milan")
        s = str(tcb)
        assert "Milan" in s
        assert "ucode=170" in s

    def test_tdx_str(self):
        tcb = TcbVersion(seam_svn=5, platform="Sapphire Rapids")
        s = str(tcb)
        assert "seam=5" in s

    def test_roundtrip(self):
        tcb = TcbVersion(boot_loader=1, tee=2, snp=22, microcode=171, platform="Milan")
        d = tcb.to_dict()
        restored = TcbVersion.from_dict(d)
        assert restored == tcb


# ---------------------------------------------------------------------------
# Extraction from raw reports
# ---------------------------------------------------------------------------

class TestExtraction:
    def test_extract_sev_snp(self):
        report = bytearray(0x188)
        report[0x180] = 3    # bl
        report[0x181] = 2    # tee
        report[0x186] = 22   # snp
        report[0x187] = 171  # microcode (0xAB)

        tcb = extract_tcb_sev_snp(bytes(report), platform="Milan")
        assert tcb.boot_loader == 3
        assert tcb.tee == 2
        assert tcb.snp == 22
        assert tcb.microcode == 171
        assert tcb.platform == "Milan"

    def test_extract_tdx(self):
        quote = bytearray(100)
        quote[48] = 7  # SEAM SVN at TD Report body offset 0

        tcb = extract_tcb_tdx(bytes(quote))
        assert tcb.seam_svn == 7

    def test_short_report_raises(self):
        with pytest.raises(ValueError, match="too short"):
            extract_tcb_sev_snp(b"\x00" * 10)


# ---------------------------------------------------------------------------
# CVE checking
# ---------------------------------------------------------------------------

class TestCveChecking:
    def test_cachewarp_vulnerable_milan(self):
        """Milan node with microcode < 0xAB → flagged for CacheWarp."""
        tcb = TcbVersion(microcode=0xAA, snp=22, platform="Milan")
        result = check_known_cves(tcb)
        assert not result.safe
        assert "CVE-2023-20592" in result.vulnerabilities

    def test_cachewarp_patched_milan(self):
        """Milan node with microcode >= 0xAB → safe from CacheWarp."""
        tcb = TcbVersion(microcode=0xAB, snp=22, platform="Milan")
        result = check_known_cves(tcb)
        assert "CVE-2023-20592" not in result.vulnerabilities

    def test_badram_vulnerable_milan(self):
        """Milan node with snp < 22 → flagged for BadRAM."""
        tcb = TcbVersion(microcode=0xAB, snp=21, platform="Milan")
        result = check_known_cves(tcb)
        assert not result.safe
        assert "CVE-2024-21944" in result.vulnerabilities

    def test_badram_patched_milan(self):
        """Milan node with snp >= 22 → safe from BadRAM."""
        tcb = TcbVersion(microcode=0xAB, snp=22, platform="Milan")
        result = check_known_cves(tcb)
        assert "CVE-2024-21944" not in result.vulnerabilities

    def test_fully_patched_passes(self):
        """Fully patched Milan node → no vulnerabilities."""
        tcb = TcbVersion(microcode=0xAB, snp=22, platform="Milan")
        result = check_known_cves(tcb)
        assert result.safe
        assert result.vulnerabilities == []

    def test_both_cves_flagged(self):
        """Node vulnerable to both CacheWarp and BadRAM."""
        tcb = TcbVersion(microcode=0x50, snp=10, platform="Milan")
        result = check_known_cves(tcb)
        assert not result.safe
        assert "CVE-2023-20592" in result.vulnerabilities
        assert "CVE-2024-21944" in result.vulnerabilities

    def test_genoa_cachewarp(self):
        """Genoa has different microcode threshold."""
        tcb = TcbVersion(microcode=0x46, platform="Genoa")  # below 0x47
        result = check_known_cves(tcb)
        assert "CVE-2023-20592" in result.vulnerabilities

        tcb_patched = TcbVersion(microcode=0x47, platform="Genoa")
        result2 = check_known_cves(tcb_patched)
        assert "CVE-2023-20592" not in result2.vulnerabilities

    def test_unknown_platform_skips_cves(self):
        """Unknown platform (TDX, etc.) → no SEV-SNP CVEs apply."""
        tcb = TcbVersion(seam_svn=1, platform="Sapphire Rapids")
        result = check_known_cves(tcb)
        assert result.safe

    def test_mock_platform_safe(self):
        tcb = TcbVersion(platform="mock")
        result = check_known_cves(tcb)
        assert result.safe


# ---------------------------------------------------------------------------
# MinTcbPolicy
# ---------------------------------------------------------------------------

class TestMinTcbPolicy:
    def test_parse_empty(self):
        policy = MinTcbPolicy.from_env("")
        assert policy.requirements == {}

    def test_parse_single(self):
        policy = MinTcbPolicy.from_env("microcode=171")
        assert policy.requirements == {"microcode": 171}

    def test_parse_multiple(self):
        policy = MinTcbPolicy.from_env("microcode=171,snp=22")
        assert policy.requirements == {"microcode": 171, "snp": 22}

    def test_check_passes(self):
        policy = MinTcbPolicy.from_env("microcode=171,snp=22")
        tcb = TcbVersion(microcode=171, snp=22, platform="Milan")
        ok, reason = policy.check(tcb)
        assert ok is True

    def test_check_fails_below_minimum(self):
        policy = MinTcbPolicy.from_env("microcode=171")
        tcb = TcbVersion(microcode=170, platform="Milan")
        ok, reason = policy.check(tcb)
        assert ok is False
        assert "microcode=170<171" in reason

    def test_check_above_minimum_passes(self):
        policy = MinTcbPolicy.from_env("microcode=171")
        tcb = TcbVersion(microcode=200, platform="Milan")
        ok, reason = policy.check(tcb)
        assert ok is True

    def test_empty_policy_always_passes(self):
        policy = MinTcbPolicy.from_env("")
        tcb = TcbVersion(microcode=1, platform="Milan")
        ok, _ = policy.check(tcb)
        assert ok is True
