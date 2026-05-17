---
id: S03
parent: M006
milestone: M006
provides:
  - docs/03-tee-subnet-architecture.md — 443-line HLA for architects covering the 5-layer design rationale, node topology ASCII diagram, full epoch flow sequence (miner/validator/overwatch timelines), security layer stack (5 independent layers), RA-TLS standard-vs-RA-TLS comparison diagram, sealed storage binding diagram, testing pyramid (L1/L2/L3), source navigation map
  - Cross-links to ARCHITECTURE.md (authoritative code-level detail); no content duplicated from it
  - Corrected source file references: chain_submitter.py (not chain_score_submitter.py), test_verifier.py (not test_dcap_verifier.py), test_sealed.py (not test_sealed_store.py)
requires:
  - slice: S01
    provides: Node role terminology, epoch lifecycle, chain integration points
  - slice: S02
    provides: DCAP quote terminology, measurement, TCB, RA-TLS concepts
affects: [S04]
key_files:
  - docs/03-tee-subnet-architecture.md
key_decisions:
  - "Narrative framing not duplication: doc 03 explains WHY the layers exist (risk ordering) and HOW they fit together (composability); ARCHITECTURE.md has the line-level detail. Zero content duplication."
  - "Source file corrections: discovered chain_submitter.py not chain_score_submitter.py, test_verifier.py not test_dcap_verifier.py, test_sealed.py not test_sealed_store.py — fixed before committing"
patterns_established:
  - "Three-timeline epoch flow diagram (miner/validator/overwatch) as the canonical HLA diagram for the epoch cycle"
drill_down_paths:
  - .gsd/milestones/M006/M006-ROADMAP.md
duration: 30min
verification_result: pass
completed_at: 2026-03-17T09:00:00Z
---

# S03: TEE Subnet Architecture HLA

**docs/03-tee-subnet-architecture.md — 443 lines; no placeholders; all source references verified**

## What Happened

Wrote the architecture HLA targeted at architects who need to understand the design before
forking. The key framing decision was to explain the five-layer ordering as a risk-sequencing
choice (hardest-to-fake first), not just a feature list. The epoch flow is presented as three
parallel timelines (miner/validator/overwatch) rather than a single sequential list — this makes
the timing offsets (30s validator, 35s overwatch) visible and the pipeline structure clear.

Source file references were verified against the actual filesystem after writing, catching three
filename errors (chain_score_submitter → chain_submitter, test_dcap_verifier → test_verifier,
test_sealed_store → test_sealed).

## Deviations
Three filename corrections vs initial draft (not divergences from plan).

## Files Created/Modified
- `docs/03-tee-subnet-architecture.md` — Architecture HLA (443 lines)
