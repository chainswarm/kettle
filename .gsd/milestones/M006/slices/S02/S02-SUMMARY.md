---
id: S02
parent: M006
milestone: M006
provides:
  - docs/02-what-is-tee.md — 481-line primer covering TEE threat model, Intel TDX (device node, kernel requirements, quote layout, measurement extraction), AMD SEV-SNP (SNP_GET_REPORT ioctl, report layout), DCAP attestation lifecycle, identity binding, TCB status table, debug mode trap, sealed storage, ARM TrustZone note, cloud options table, hardware requirements, MOCK_TEE
  - Terminology anchor: "DCAP quote", "measurement (MRTD)", "TCB status", "report_data binding", "debug mode", "sealed storage", "remote attestation"
  - Cross-links to GRAMINE.md, subnet/tee/backends/tdx.py, sev_snp.py — all verified
requires: []
affects: [S03]
key_files:
  - docs/02-what-is-tee.md
key_decisions:
  - "TDX vs SEV-SNP diff table: included side-by-side comparison table because developers frequently conflate them; table shows device node, kernel version, quote size, measurement register location"
  - "Identity binding section: included because it is the key concept that prevents both replay and Sybil attacks — understanding why the nonce and peer_id go into report_data is more important than knowing the ioctl call signature"
  - "MOCK_TEE table: included comparison of mock vs real TEE behaviours to make the 0.5 vs 1.0 score semantics clear to first-time users"
patterns_established:
  - "Cloud options table includes AWS caveat (Nitro Enclaves not DCAP-compatible) — prevents common misunderstanding"
  - "Hardware checking bash snippet at end of §13 for quick availability check"
drill_down_paths:
  - .gsd/milestones/M006/M006-ROADMAP.md
duration: 30min
verification_result: pass
completed_at: 2026-03-17T09:00:00Z
---

# S02: TEE Primer

**docs/02-what-is-tee.md — 481 lines; no placeholders; all cross-references resolve**

## What Happened

Wrote the full TEE primer using tdx.py, sev_snp.py, verifier.py, and quote.py as primary source
material. Derived the TDX quote layout from the actual byte offsets in tdx.py (header=48, TD Report
body=584, MRTD at 48+512). Derived the SNP report layout from sev_snp.py constants (MEASUREMENT at
0x90, POLICY at 0x08, debug_swap bit 19). The DCAP lifecycle section bridges from the hardware
(what the ioctl does) to the subnet (how the quote flows through DHT to the DcapVerifier). Identity
binding section explains why sha256(peer_id:epoch) goes into report_data — the most important
conceptual link between TEE fundamentals and the subnet's specific anti-Sybil design.

## Deviations
None — single-task slice, executed as planned.

## Files Created/Modified
- `docs/02-what-is-tee.md` — TEE primer (481 lines)
