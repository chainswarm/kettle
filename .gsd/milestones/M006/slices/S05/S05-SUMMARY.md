---
id: S05
parent: M006
milestone: M006
provides:
  - docs/05-bittensor-comparison.md — 409-line comparative analysis of SN9 IOTA, SN81 GRAIL, SN75 hippius vs Hypertensor TEE; 3 structural gap analyses; full comparison table (14 dimensions); "What TEE adds" section (hardware root of trust, enclave isolation, 66% attestation); migration guidance; explicit analysis datestamps
  - Source material: excavator/catalogue/9/VALIDATOR_MECHANICS.md (SN9), excavator/catalogue/81/ANALYSIS.md (SN81), excavator/catalogue/75/VALIDATOR_MECHANICS.md (SN75), HYPERTENSOR_ANALYSIS.md
requires:
  - slice: S04
    provides: Attack taxonomy and defence taxonomy (to frame Bittensor gaps)
affects: [S06]
key_files:
  - docs/05-bittensor-comparison.md
key_decisions:
  - "Named subnets explicitly (SN9, SN81, SN75) with 2026-03-14 datestamp — architectural patterns are stable; framed as point-in-time analysis not live competitive claims"
  - "GRAIL gets the most nuanced treatment because it is genuinely sophisticated — the comparison shows what PRF proofs prove vs what TEE proves, not that GRAIL is 'worse'"
  - "66% attestation section emphasised the stake threshold math (0–65% → every attempt costs slash; 66%+ → only then profitable)"
patterns_established:
  - "Structural gaps per subnet rather than feature checklist — shows what each approach fundamentally cannot prove, not just what it lacks"
drill_down_paths:
  - .gsd/milestones/M006/M006-ROADMAP.md
duration: 25min
verification_result: pass
completed_at: 2026-03-17T09:00:00Z
---

# S05: Bittensor Comparison

**docs/05-bittensor-comparison.md — 409 lines; no placeholders; datestamp present**

## What Happened

Wrote the full Bittensor comparison using the excavator catalogue analyses as primary source
material. The SN9 treatment focuses on the centralised orchestrator trust dependency and the
optional-vs-mandatory TEE gap. The GRAIL treatment is the most nuanced — GRAIL is genuinely
sophisticated, so the comparison had to show precisely what PRF proofs prove (software output
authenticity) vs what TEE proves (hardware execution integrity) rather than dismissing it.
SN75 hippius illustrates the single-elected-validator manipulation surface and IPFS
non-determinism problem. The 66% attestation section includes the stake threshold math to make
the economic argument precise.

## Deviations
None.

## Files Created/Modified
- `docs/05-bittensor-comparison.md` — Bittensor comparison (409 lines)
