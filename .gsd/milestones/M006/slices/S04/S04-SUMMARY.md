---
id: S04
parent: M006
milestone: M006
provides:
  - docs/04-anti-cheat.md — 497-line attack taxonomy covering 7 attack vectors (identity theft, quote replay, debug mode bypass, measurement swap, output forgery, validator collusion, overwatch evasion); per-attack: description, why it matters, exact defence, source file + function citations, residual risk acknowledgment
  - Defence summary table (7 rows) linking each attack to source file
  - Economic summary table — consequence of each undefended attack
  - "What TEE does not protect against" section — explicit limits (incorrect code, malicious subnet owner, input manipulation, side-channel attacks, >66% collusion)
requires:
  - slice: S03
    provides: Full epoch flow, all security layers, module-to-file mappings
affects: [S05, S06]
key_files:
  - docs/04-anti-cheat.md
key_decisions:
  - "Economic summary included: each attack's economic consequence makes the case for why the defence is not optional overhead but economically necessary — directly feeds doc 06 business case"
  - "Explicit limits section: 'What TEE does not protect against' is as important as the attack list — avoiding overpromising is critical for trust"
  - "Every defence cites a specific function, not just a file — quote.py make_report_data(), verifier.py step 3, backends/tdx.py _is_debug_mode()"
patterns_established:
  - "Attack description → why it matters → defence implementation → source evidence → residual risk structure per attack"
drill_down_paths:
  - .gsd/milestones/M006/M006-ROADMAP.md
duration: 30min
verification_result: pass
completed_at: 2026-03-17T09:00:00Z
---

# S04: Anti-Cheat Attack Taxonomy

**docs/04-anti-cheat.md — 497 lines; no placeholders; all 11 source file references verified**

## What Happened

Wrote the full attack taxonomy with direct code evidence for each defence. Every attack section
follows the same structure: the attack scenario, why it is economically rational, the specific
code path that blocks it (function-level), and what residual risk remains. All 11 source file
references were verified against the filesystem before committing. The validator collusion section
is honest about the residual: >66% majority-stake collusion cannot be blocked cryptographically,
only economically.

## Deviations
None.

## Files Created/Modified
- `docs/04-anti-cheat.md` — Attack taxonomy (497 lines)
