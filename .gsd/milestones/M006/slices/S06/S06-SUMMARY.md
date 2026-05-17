---
id: S06
parent: M006
milestone: M006
provides:
  - docs/06-business-case.md — 272-line business case covering the productisation gap (why "plausibly correct" ≠ "provably correct"), non-TEE vs TEE output claims table, four business-critical properties (quality floor, miner accountability, verifiable SLAs, model IP protection), 4 concrete use cases (regulated inference, on-chain oracle, proprietary model subnet, verifiable training), cost/benefit analysis, "what sustainable looks like"
  - README.md updated — added ## Documentation section with 6-row table linking all docs
requires:
  - slice: S04
    provides: Named failure modes (attack taxonomy) used as anchors for business case claims
  - slice: S05
    provides: Named structural gaps (Bittensor comparison) as market context
affects: []
key_files:
  - docs/06-business-case.md
  - README.md
key_decisions:
  - "Business case anchors every claim in doc 04 attack taxonomy: each 'what TEE adds' item links to the specific source file that enforces it — avoids marketing-speak by grounding in code"
  - "Use cases are concrete scenarios not abstract descriptions: regulated healthcare inference, on-chain oracle, proprietary model deployment, verifiable training — each maps to a real buyer category"
  - "Explicit 'what sustainable looks like' conclusion: non-TEE is a maintenance race; TEE is front-loaded security — this is the key business model argument"
patterns_established:
  - "Business case must anchor claims in failure modes, not aspirational benefits"
drill_down_paths:
  - .gsd/milestones/M006/M006-ROADMAP.md
duration: 20min
verification_result: pass
completed_at: 2026-03-17T09:00:00Z
---

# S06: Business Case + README

**docs/06-business-case.md — 272 lines; README.md updated with Documentation section**

## What Happened

Wrote the business case grounded entirely in concrete failure modes from doc 04 and structural
gaps from doc 05 — no abstract benefit claims. The "four business-critical properties" section
is the core: quality floor (enforced by EXPECTED_MEASUREMENT), miner accountability (honest
compute is economically rational), verifiable SLAs (attestation as audit trail), model IP
protection (enclave isolation). Each property links back to the specific source file.

Updated README.md with a ## Documentation section containing a 6-row table linking all docs.

## Deviations
None.

## Files Created/Modified
- `docs/06-business-case.md` — Business case (272 lines)
- `README.md` — Added ## Documentation section before ## License
