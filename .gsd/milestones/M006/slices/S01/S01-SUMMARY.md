---
id: S01
parent: M006
milestone: M006
provides:
  - docs/01-what-is-hypertensor.md — 362-line primer covering consensus model, node roles (bootnode/validator/miner/overwatch), slashing (3.125%/epoch), emission flow, subnet lifecycle, key extrinsics table, env var quick reference
  - Terminology anchor for downstream docs: "epoch", "validator class", "overwatch node", "propose_attestation", "commit+reveal slash", "TENSOR emission"
  - Cross-links to CHAIN.md, NODE.md, subnet/hypertensor/config.py, chain_functions.py, chain_overwatch_reporter.py — all verified to exist
requires: []
affects: [S03, S05]
key_files:
  - docs/01-what-is-hypertensor.md
key_decisions:
  - "Consensus depth: included full 3-phase epoch diagram (election → scoring → finalisation) because the determinism requirement is the most important constraint for subnet developers"
  - "Score format: documented planck-scale u128 (int(score × 1e18)) because it trips every developer who first reads propose_attestation"
patterns_established:
  - "Docs cross-link to CHAIN.md for operational steps rather than duplicating them"
  - "Quick reference tables at doc end (constants, extrinsics, env vars) for developer reference"
drill_down_paths:
  - .gsd/milestones/M006/M006-ROADMAP.md
duration: 25min
verification_result: pass
completed_at: 2026-03-17T09:00:00Z
---

# S01: Hypertensor Primer

**docs/01-what-is-hypertensor.md — 362 lines; no placeholders; all cross-references resolve**

## What Happened

Wrote the full Hypertensor primer from scratch using HYPERTENSOR_ANALYSIS.md, CHAIN.md, and
chain_functions.py as source material. Covers the three-phase consensus (election/scoring/
finalisation), the determinism requirement (100% validator agreement vs Bittensor stake-averaging),
all four node roles, slashing mechanics with exact parameters (3.125%/epoch, 1 TENSOR cap),
emission flow (planck-scale u128), subnet lifecycle (7+3 day registration+enactment), and the
structural diff table vs Bittensor. Ends with quick reference tables for constants, extrinsics,
and env vars.

## Deviations
None — single-task slice, executed as planned.

## Files Created/Modified
- `docs/01-what-is-hypertensor.md` — Hypertensor primer (362 lines)
