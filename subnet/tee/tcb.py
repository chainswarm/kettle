"""
TCB (Trusted Computing Base) version tracking and vulnerability enforcement.

Extracts firmware/microcode version numbers from attestation reports and
checks them against known-vulnerable versions.

AMD SEV-SNP REPORTED_TCB layout (8 bytes at report offset 0x180)
----------------------------------------------------------------
  byte 0:   boot_loader SPL (Security Patch Level)
  byte 1:   tee SPL (PSP operating system)
  byte 2-5: reserved (must be zero)
  byte 6:   snp SPL (SNP firmware)
  byte 7:   microcode SPL

Intel TDX TEE_TCB_SVN layout (16 bytes at TD Report body offset 0)
-------------------------------------------------------------------
  byte 0:   SEAM module SVN (TDX module version)
  byte 1-15: component SVNs (ISV, config, etc.)

Known CVEs and minimum safe versions
-------------------------------------
CacheWarp (CVE-2023-20592):
  - Affects: AMD SEV-SNP on Milan (EPYC 7003)
  - Fix: microcode >= 0xAB (171) for Milan, >= 0x47 (71) for Genoa
  - Impact: fault injection can revert memory writes inside guest

BadRAM (CVE-2024-21944):
  - Affects: AMD SEV-SNP (requires physical DIMM access)
  - Fix: SNP firmware >= 22 for Milan, >= 22 for Genoa
  - Impact: SPD manipulation can bypass memory encryption

SEV-Step (side-channel):
  - No specific microcode fix — mitigation is at hypervisor level
  - We flag it as advisory, not blocking
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, asdict
from typing import Optional


@dataclass(frozen=True)
class TcbVersion:
    """
    Parsed TCB version from an attestation report.

    For SEV-SNP: extracted from REPORTED_TCB (8 bytes at offset 0x180).
    For TDX: extracted from TEE_TCB_SVN (16 bytes at TD Report body offset 0).
    For Mock: synthetic values set by the test.
    """

    # AMD SEV-SNP fields (0 for TDX/mock)
    boot_loader: int = 0
    tee: int = 0
    snp: int = 0
    microcode: int = 0

    # Intel TDX fields (0 for SEV-SNP/mock)
    seam_svn: int = 0

    # Platform identifier for CVE lookup
    platform: str = ""  # "Milan", "Genoa", "Sapphire Rapids", "mock", etc.

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "TcbVersion":
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})

    def __str__(self) -> str:
        if self.platform in ("Milan", "Genoa"):
            return (
                f"SNP(bl={self.boot_loader},tee={self.tee},"
                f"snp={self.snp},ucode={self.microcode},"
                f"platform={self.platform})"
            )
        return f"TDX(seam={self.seam_svn},platform={self.platform})"


# ---------------------------------------------------------------------------
# Known CVE database — minimum safe TCB component versions
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class CveEntry:
    """A known CVE with minimum safe TCB component versions."""
    cve_id: str
    description: str
    severity: str  # "critical", "high", "medium", "low"

    # Minimum safe versions per platform.
    # Key: platform name. Value: dict of TCB component → minimum safe value.
    # If a component is not listed, any value is acceptable.
    min_safe: dict  # {platform: {component: min_value}}


# Known vulnerabilities affecting TEE attestation
KNOWN_CVES: list[CveEntry] = [
    CveEntry(
        cve_id="CVE-2023-20592",
        description="CacheWarp: INVD instruction fault injection reverting SEV-SNP guest memory writes",
        severity="critical",
        min_safe={
            "Milan": {"microcode": 0xAB},    # 171 decimal
            "Genoa": {"microcode": 0x47},     # 71 decimal
        },
    ),
    CveEntry(
        cve_id="CVE-2024-21944",
        description="BadRAM: SPD manipulation bypasses SEV-SNP memory encryption (physical access required)",
        severity="high",
        min_safe={
            "Milan": {"snp": 22},
            "Genoa": {"snp": 22},
        },
    ),
]


# ---------------------------------------------------------------------------
# Extraction from raw attestation reports
# ---------------------------------------------------------------------------

def extract_tcb_sev_snp(raw_report: bytes, platform: str = "Milan") -> TcbVersion:
    """
    Extract TCB version from a raw SEV-SNP attestation report.

    REPORTED_TCB is 8 bytes at offset 0x180.
    """
    if len(raw_report) < 0x188:
        raise ValueError(f"Report too short for TCB extraction: {len(raw_report)} bytes")

    tcb = raw_report[0x180:0x188]
    return TcbVersion(
        boot_loader=tcb[0],
        tee=tcb[1],
        snp=tcb[6],
        microcode=tcb[7],
        platform=platform,
    )


def extract_tcb_tdx(raw_quote: bytes, platform: str = "Sapphire Rapids") -> TcbVersion:
    """
    Extract TCB version from a raw TDX DCAP quote.

    TEE_TCB_SVN is 16 bytes at TD Report body offset 0 (quote offset 48).
    """
    td_report_offset = 48
    if len(raw_quote) < td_report_offset + 16:
        raise ValueError(f"Quote too short for TCB extraction: {len(raw_quote)} bytes")

    tee_tcb_svn = raw_quote[td_report_offset:td_report_offset + 16]
    return TcbVersion(
        seam_svn=tee_tcb_svn[0],
        platform=platform,
    )


# ---------------------------------------------------------------------------
# CVE checking
# ---------------------------------------------------------------------------

@dataclass
class CveCheckResult:
    """Result of checking a TcbVersion against known CVEs."""
    safe: bool
    vulnerabilities: list[str]  # list of CVE IDs that affect this TCB
    details: list[str]          # human-readable descriptions


def check_known_cves(tcb: TcbVersion) -> CveCheckResult:
    """
    Check a TcbVersion against all known CVEs.

    Returns CveCheckResult with list of CVEs the node is vulnerable to.
    """
    vulns = []
    details = []

    for cve in KNOWN_CVES:
        platform_reqs = cve.min_safe.get(tcb.platform, {})
        if not platform_reqs:
            continue  # CVE doesn't apply to this platform

        for component, min_val in platform_reqs.items():
            actual = getattr(tcb, component, 0)
            if actual < min_val:
                vulns.append(cve.cve_id)
                details.append(
                    f"{cve.cve_id} ({cve.severity}): {cve.description} — "
                    f"{component}={actual} < {min_val} (minimum safe)"
                )
                break  # one failed component is enough for this CVE

    return CveCheckResult(
        safe=len(vulns) == 0,
        vulnerabilities=vulns,
        details=details,
    )


# ---------------------------------------------------------------------------
# Minimum TCB version enforcement
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class MinTcbPolicy:
    """
    Minimum required TCB component versions.

    Parsed from MIN_TCB_VERSION env var.
    Format: "component=value,component=value"
    Example: "microcode=171,snp=22"
    """
    requirements: dict  # {component: min_value}

    @classmethod
    def from_env(cls, raw: str) -> "MinTcbPolicy":
        """Parse from env var string like 'microcode=171,snp=22'."""
        reqs = {}
        if not raw.strip():
            return cls(requirements={})

        for part in raw.split(","):
            part = part.strip()
            if "=" not in part:
                continue
            key, val = part.split("=", 1)
            try:
                reqs[key.strip()] = int(val.strip())
            except ValueError:
                continue

        return cls(requirements=reqs)

    def check(self, tcb: TcbVersion) -> tuple[bool, str]:
        """
        Check a TcbVersion against minimum requirements.

        Returns (True, "") if passes, (False, reason) if fails.
        """
        for component, min_val in self.requirements.items():
            actual = getattr(tcb, component, None)
            if actual is None:
                continue
            if actual < min_val:
                return False, f"tcb_below_minimum:{component}={actual}<{min_val}"

        return True, ""
