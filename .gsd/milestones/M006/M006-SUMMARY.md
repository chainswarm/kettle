---
milestone: M006
completed_at: 2026-03-17T09:00:00Z
slices_completed: [S01, S02, S03, S04, S05, S06]
total_lines: 2464
docs_created: 6
verification_result: pass
---

# M006: Knowledge Base — TEE Subnet Education + Architect Reference

**All 6 slices complete. All success criteria met.**

## What Was Built

A `docs/` folder with 6 comprehensive markdown files covering Hypertensor and TEE from zero
knowledge to production-ready understanding. Every doc is GitHub-renderable, cross-linked,
and anchored in actual source code.

| Doc | Lines | Purpose |
|---|---|---|
| `docs/01-what-is-hypertensor.md` | 362 | Hypertensor primer — consensus, node roles, slashing, emission |
| `docs/02-what-is-tee.md` | 481 | TEE primer — TDX, SEV-SNP, DCAP, identity binding, cloud options |
| `docs/03-tee-subnet-architecture.md` | 443 | HLA for architects — epoch flow, security layers, source navigation |
| `docs/04-anti-cheat.md` | 497 | Attack taxonomy — 7 attacks, per-attack source evidence, economic stakes |
| `docs/05-bittensor-comparison.md` | 409 | Bittensor comparison — SN9/SN81/SN75 gap analysis, TEE advantages |
| `docs/06-business-case.md` | 272 | Business case — productisation gap, 4 properties, use cases, cost/benefit |

`README.md` updated with `## Documentation` section linking all 6 files.

## Verification

- ✓ All 6 docs exist with substantive content (no stubs, no placeholders — verified by `grep -c "{{" docs/*.md`)
- ✓ README.md has `## Documentation` section
- ✓ All cross-references resolve: `../ARCHITECTURE.md`, `../CHAIN.md`, `../GRAMINE.md`, `../NODE.md`
- ✓ All 11 source file citations in doc 04 verified against filesystem
- ✓ No content duplicated from ARCHITECTURE.md — docs link to it
- ✓ Analysis datestamps present in doc 05
- ✓ Doc 06 grounds every claim in named failure mode (no marketing-speak)

## Key Decisions

- **Narrative framing not duplication (D014):** doc 03 explains the WHY and HOW of the architecture;
  ARCHITECTURE.md has the line-level detail. Zero content duplication.
- **Named Bittensor subnets with explicit dates:** analysis is point-in-time architectural, not
  live competitive; framing prevents the comparison from aging poorly.
- **Every attack defence cites a specific function:** quote.py `make_report_data()`, verifier.py
  step 3, backends/tdx.py `_is_debug_mode()` — this is what separates the doc from marketing.
- **Business case anchors to attack taxonomy:** each business-critical property links back to
  the specific code path that enforces it.

## Drill-Down Paths

- `.gsd/milestones/M006/slices/S01/S01-SUMMARY.md` — Hypertensor primer
- `.gsd/milestones/M006/slices/S02/S02-SUMMARY.md` — TEE primer
- `.gsd/milestones/M006/slices/S03/S03-SUMMARY.md` — Architecture HLA
- `.gsd/milestones/M006/slices/S04/S04-SUMMARY.md` — Attack taxonomy
- `.gsd/milestones/M006/slices/S05/S05-SUMMARY.md` — Bittensor comparison
- `.gsd/milestones/M006/slices/S06/S06-SUMMARY.md` — Business case + README
