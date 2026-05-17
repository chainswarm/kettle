---
id: T02
parent: S04
milestone: M005
provides:
  - CHAIN.md full developer walkthrough — 8 sections, prerequisites through troubleshooting, [WARN] vs [OK] semantics, expected time-to-first-submission
  - TESTING_LAYERS.md Layer 3 section updated with check_scores.py, check_slash.py, smoke_test_chain.py command examples and See also reference
  - .github/workflows/ci.yml — Layer 1 (pytest), Layer 2 (compose config), Layer 3 (chain smoke, continue-on-error) automated CI
key_files:
  - CHAIN.md
  - TESTING_LAYERS.md
  - .github/workflows/ci.yml
  - .gsd/milestones/M005/slices/S04/tasks/T02-PLAN.md
  - .gsd/milestones/M005/slices/S04/S04-PLAN.md
key_decisions:
  - CI Layer 3 step uses continue-on-error: true so no testnet in CI does not block PRs — matches graceful-degradation pattern from T01's smoke_test_chain.py
  - CHAIN.md [WARN] vs [OK] semantics table documents that WARN is not an error — first 2-3 epochs produce no scores (normal)
  - TESTING_LAYERS.md See also line expanded to list all four check scripts, not just check_peers.py
patterns_established:
  - Layer 3 CI steps should always carry continue-on-error: true when testnet is unavailable in the CI environment
  - [WARN] semantics (data not yet present) must be distinguished from ERROR: (connection failure) in all chain check scripts and their documentation
observability_surfaces:
  - CHAIN.md troubleshooting table maps each error symptom to a concrete diagnostic command
  - .github/workflows/ci.yml Actions run log shows Layer 1 pytest + Layer 2 compose config + Layer 3 smoke test output per push/PR
  - smoke_test_chain.py [PASS]/[FAIL] per sub-check with exit code visible in CI step log
duration: 15m
verification_result: passed
completed_at: 2026-03-17
blocker_discovered: false
---

# T02: Expand CHAIN.md, update TESTING_LAYERS.md, and add CI workflow

**Replaced CHAIN.md stub with 8-section developer walkthrough, updated TESTING_LAYERS.md Layer 3 with check_scores/check_slash/smoke_test commands, and created .github/workflows/ci.yml with Layer 1+2+3 steps.**

## What Happened

The existing `CHAIN.md` was a ~30-line stub with a "Coming in M005/S04" placeholder. Replaced it entirely with a full developer walkthrough covering: Prerequisites (faucet link, subkey command, env var table), Steps 1-6 (connectivity check → register subnet → register nodes → run stack → monitor → smoke test), and a Troubleshooting table.

`TESTING_LAYERS.md` Layer 3 section already had the `check_peers.py` block. Added `check_scores.py`, `check_slash.py`, and `smoke_test_chain.py` command blocks after it, plus expanded the See also line to reference all four check scripts.

Created `.github/workflows/ci.yml` with a single `ci` job: checkout → Python 3.11 setup + `pip install -e ".[dev]"` → pytest Layer 1 → docker compose config Layer 2 → chain smoke test Layer 3 with `continue-on-error: true`.

Pre-flight issues were addressed: added `## Observability Impact` section to `T02-PLAN.md` describing what CI surfaces show, and added failure-state inspection block to `S04-PLAN.md` Observability section.

## Verification

```
# CHAIN.md registration content (not a stub):
grep -c "register_subnet|register_node|faucet|[WARN]" CHAIN.md
→ 9  (>3 required)

# CHAIN.md stub placeholder removed:
grep -i "coming in M005" CHAIN.md; echo GREP_EXIT=$?
→ GREP_EXIT=1

# CHAIN.md sections:
→ 8 sections: Prerequisites, Step 1-6, Troubleshooting

# TESTING_LAYERS.md new script references:
grep "check_scores|check_slash|smoke_test" TESTING_LAYERS.md | wc -l
→ 6  (>=3 required)

# CI workflow steps:
grep -c "pytest|docker compose" .github/workflows/ci.yml
→ 3  (>=2 required)

# CI continue-on-error:
grep "continue-on-error" .github/workflows/ci.yml
→ continue-on-error: true

# Layer 2 compose config:
docker compose -f docker-compose.tee-dev.yml config > /dev/null; echo EXIT=$?
→ EXIT=0

# Layer 1 pytest:
pytest tests/ -x -q
→ 194 passed, 1 skipped in 5.05s
```

## Diagnostics

- `grep -c "register_subnet\|register_node\|faucet\|\[WARN\]" CHAIN.md` — confirms full walkthrough present
- `grep -i "coming in M005" CHAIN.md` — GREP_EXIT=1 confirms stub removed
- `cat .github/workflows/ci.yml | grep -n "continue-on-error\|pytest\|docker compose"` — confirms CI structure
- GitHub Actions tab on any push to `main` shows Layer 1 + Layer 2 pass/fail and Layer 3 informational output

## Deviations

None. Implemented exactly as specified in T02-PLAN.md.

## Known Issues

None.

## Files Created/Modified

- `CHAIN.md` — replaced stub with 8-section full developer walkthrough (~200 lines)
- `TESTING_LAYERS.md` — Layer 3 section expanded with check_scores.py, check_slash.py, smoke_test_chain.py command blocks and expanded See also line
- `.github/workflows/ci.yml` — new; Layer 1 (pytest) + Layer 2 (compose config) + Layer 3 (chain smoke, continue-on-error) CI workflow
- `.gsd/milestones/M005/slices/S04/tasks/T02-PLAN.md` — added Observability Impact section (pre-flight fix)
- `.gsd/milestones/M005/slices/S04/S04-PLAN.md` — added failure-state inspection block to Observability section (pre-flight fix)
