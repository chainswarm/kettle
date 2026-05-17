---
id: S04
parent: M005
milestone: M005
provides:
  - ChainScoreSubmitter wired into _validator_scoring_loop in server.py — scores submitted each epoch
  - scripts/register_subnet.py — on-chain subnet registration helper
  - scripts/register_node.py — on-chain node registration helper with friendly-ID resolution
  - scripts/smoke_test_chain.py — delegating CI-safe chain smoke test (exits 0/1 cleanly)
  - CHAIN.md full 8-section developer walkthrough (prerequisites through troubleshooting)
  - TESTING_LAYERS.md Layer 3 section expanded with check_scores.py, check_slash.py, smoke_test_chain.py
  - .github/workflows/ci.yml — Layer 1 (pytest) + Layer 2 (compose config) + Layer 3 (chain smoke, continue-on-error)
  - test_wiring_pattern_two_nodes regression test in test_chain_submitter.py
requires:
  - slice: S01
    provides: Hypertensor(url, phrase) construction pattern; check_peers.py credential/URL resolution; chain peer list
  - slice: S02
    provides: ChainScoreSubmitter(hypertensor, subnet_id).submit(scores) API; check_scores.py
  - slice: S03
    provides: ChainOverwatchReporter; check_slash.py; docker-compose.chain.yml service env pattern
affects: []
key_files:
  - subnet/server/server.py
  - scripts/register_subnet.py
  - scripts/register_node.py
  - scripts/smoke_test_chain.py
  - tests/consensus/test_chain_submitter.py
  - CHAIN.md
  - TESTING_LAYERS.md
  - .github/workflows/ci.yml
key_decisions:
  - D011: CI Layer 3 continues-on-error — chain absence in CI is expected; Layer 1 + Layer 2 are the blocking gates
  - D012: [WARN] vs ERROR: semantics — [WARN] = no data yet (first 2-3 epochs); ERROR: = connection failure; documented in CHAIN.md and all check scripts
  - D013: scores[] reset per epoch; only successful score_peer() calls appended; submit() called once after per-node loop
patterns_established:
  - Registration scripts mirror check_peers.py exactly: env-only credential loading, URL precedence (--local_rpc > --chain > $DEV_RPC > hardcoded), Hypertensor construction with try/except, sys.exit(1) on failure
  - smoke_test_chain.py delegation pattern: subprocess.run(check=False) per sub-script; [PASS]/[FAIL] per check; exit 0 only if all pass
  - CI Layer 3 pattern: continue-on-error: true for chain-dependent steps; || echo "expected" for graceful log output
  - [WARN] vs ERROR: output convention across all four chain check scripts
observability_surfaces:
  - logger.info("[ValidatorLoop] Submitted scores epoch=%d count=%d") — visible via docker compose logs validator | grep "Submitted scores"
  - smoke_test_chain.py [FAIL] <script> (exit N) — structured failure output; no crash on connection failure
  - .github/workflows/ci.yml Actions log — Layer 1 pytest pass/fail + Layer 2 compose config + Layer 3 smoke test output per push/PR
  - CHAIN.md troubleshooting table — maps error symptoms to diagnostic commands
drill_down_paths:
  - .gsd/milestones/M005/slices/S04/tasks/T01-SUMMARY.md
  - .gsd/milestones/M005/slices/S04/tasks/T02-SUMMARY.md
duration: 40m
verification_result: passed
completed_at: 2026-03-17
---

# S04: Chain Integration Docs + Smoke Tests

**Wired ChainScoreSubmitter into the validator epoch loop, completed the chain developer tooling (register_subnet.py, register_node.py, smoke_test_chain.py), expanded CHAIN.md from stub to 8-section walkthrough, and added a three-layer CI workflow — 194 tests green.**

## What Happened

S04 was the final-assembly slice for M005: no new chain primitives, only wiring and documentation that made everything built in S01–S03 discoverable, testable, and actually called in production.

**T01 — Production wiring + tooling scripts:**

`ChainScoreSubmitter` had existed since S02 but was never imported or called in `server.py`. T01 added the import alongside the existing `ChainOverwatchReporter` import, instantiated `submitter = ChainScoreSubmitter(hypertensor, subnet_id)` once before the `while` loop in `_validator_scoring_loop`, and inserted score accumulation + submit after each epoch's per-node loop. Scores are accumulated in a `scores = []` list reset at epoch top; only peers that complete `score_peer()` without raising are appended (exception path silently omits, consistent with existing error handling). `int(peer_score.score * 1e18)` converts float scores to planck-scale integers for the chain.

`register_subnet.py` and `register_node.py` were written mirroring `check_peers.py`'s credential/URL patterns exactly: credentials from env only (PHRASE / TENSOR_PRIVATE_KEY), URL precedence (--local_rpc > --chain > $DEV_RPC > hardcoded `wss://rpc.hypertensor.app:443`), Hypertensor construction wrapped in try/except, sys.exit(1) on failure. `register_subnet.py` wraps `hypertensor.register_subnet()` with 8 CLI args. `register_node.py` wraps `register_subnet_node()` with friendly-ID resolution (subnet_id < 128000 triggers `get_subnet_id_from_friendly_id`).

`smoke_test_chain.py` delegates to `check_peers.py`, `check_scores.py`, and `check_slash.py` via `subprocess.run(check=False)`. Each sub-script's exit code produces a `[PASS]` or `[FAIL] <script> (exit N)` line. The script exits 0 only when all three pass; exits 1 cleanly on any failure. No crash, no traceback on connection failure — confirmed against `ws://127.0.0.1:9944` with no local node.

A `test_wiring_pattern_two_nodes` regression test was added as the 6th test in `test_chain_submitter.py`. It verifies the score-accumulation pattern: 2 nodes scored, `SubnetNodeConsensusData(subnet_node_id, int(score * 1e18))` field mapping correct, `submit()` called once with the correct list.

**T02 — Documentation + CI:**

`CHAIN.md` was a ~30-line stub with a "Coming in M005/S04" placeholder. Replaced entirely with an 8-section walkthrough: Prerequisites (faucet URL, `subkey` for key generation, required env var table), Steps 1–6 (connectivity check → register subnet → register nodes → run stack → monitor epoch-by-epoch → run smoke test), and a Troubleshooting table mapping error symptoms to diagnostic commands. The `[WARN]` vs `[OK]` semantics table documents that `[WARN]` is not an error — it means the chain is reachable but no data exists yet (normal for the first 2–3 epochs).

`TESTING_LAYERS.md` Layer 3 section was expanded with `check_scores.py`, `check_slash.py`, and `smoke_test_chain.py` command blocks alongside the existing `check_peers.py` block. The See also line was expanded to list all four check scripts.

`.github/workflows/ci.yml` was created with a single `ci` job triggering on push/PR to `main`: checkout → Python 3.11 + `pip install -e ".[dev]"` → pytest (Layer 1, blocking) → docker compose config (Layer 2, blocking) → chain smoke test (Layer 3, `continue-on-error: true`). The Layer 3 step is explicitly informational: no testnet is reachable in CI, so exit 1 is expected and must not block PRs.

## Verification

```
# Layer 1 — 194 tests green:
pytest tests/ -x -q
→ 194 passed, 1 skipped in 4.94s

# ChainScoreSubmitter wired:
grep -n "ChainScoreSubmitter|submitter.submit" subnet/server/server.py
→ 67:  from subnet.consensus.chain_submitter import ChainScoreSubmitter
→ 567: submitter = ChainScoreSubmitter(hypertensor, subnet_id)
→ 618: submitter.submit(scores)

# smoke_test_chain.py exits 1 cleanly on no local node:
python3 scripts/smoke_test_chain.py --local_rpc --subnet_id 1 --epoch 0 --overwatch_node_id 1; echo EXIT=$?
→ [FAIL] check_peers.py (exit 1)
→ [FAIL] check_scores.py (exit 1)
→ [FAIL] check_slash.py (exit 1)
→ EXIT=1  (no traceback)

# Registration scripts --help:
python3 scripts/register_subnet.py --help; echo EXIT=$?  → EXIT=0
python3 scripts/register_node.py --help; echo EXIT=$?    → EXIT=0

# Credential redaction:
PHRASE="super secret mnemonic" python3 scripts/register_subnet.py --help 2>&1 | grep -i "super secret"
→ GREP_EXIT=1 (no match = redaction confirmed)

# CHAIN.md full (not stub):
grep -c "register_subnet|register_node|faucet|[WARN]" CHAIN.md  → 9  (>3 required)
grep -i "coming in M005" CHAIN.md; echo STUB_EXIT=$?              → STUB_EXIT=1

# CI workflow structure:
grep -c "pytest|docker compose" .github/workflows/ci.yml          → 3  (>=2 required)
grep "continue-on-error" .github/workflows/ci.yml                 → continue-on-error: true

# TESTING_LAYERS.md new references:
grep "check_scores|check_slash|smoke_test" TESTING_LAYERS.md | wc -l  → 6

# Layer 2 unaffected:
docker compose -f docker-compose.tee-dev.yml config > /dev/null; echo EXIT=$?  → EXIT=0
```

## Requirements Advanced

- R022 (test coverage) — wiring regression test `test_wiring_pattern_two_nodes` added; 194 tests now cover the full chain integration path including score accumulation and submission

## Requirements Validated

None newly validated in this slice — S01–S03 validated R009–R012; S04 is final assembly.

## New Requirements Surfaced

None.

## Requirements Invalidated or Re-scoped

None.

## Deviations

None. Both tasks executed exactly as specified in their plans.

## Known Limitations

- **No live testnet proof yet**: The milestone's human UAT (subnet registered, 2+ nodes staked, scores visible on-chain, slash confirmed with `TAMPER_RATE=1.0`) requires a funded testnet wallet and manual steps. This is milestone-level UAT, not slice-level, and is documented in `CHAIN.md`.
- **CI Layer 3 is informational only**: `smoke_test_chain.py` will always exit 1 in CI until a testnet endpoint with `CHAIN_ENDPOINT` secret is wired into the workflow. This is by design (D011).
- **`python` vs `python3` in CI**: The CI workflow uses `python scripts/smoke_test_chain.py` which works on GitHub Actions' Ubuntu runner (setup-python provides `python`). Local dev environments where only `python3` is available must use `python3` directly.

## Follow-ups

- Live testnet UAT: fund a testnet wallet via faucet, run `register_subnet.py`, `register_node.py`, start `docker-compose.chain.yml`, confirm scores appear via `check_scores.py`. This is the milestone definition-of-done gate.
- Slash confirmation: run with `TAMPER_RATE=1.0`, confirm `check_slash.py` shows slash landed. Required for M005 milestone sign-off.
- If CI ever has a reliable testnet endpoint, remove `continue-on-error: true` from the Layer 3 step and pass `CHAIN_ENDPOINT` as a secret.

## Files Created/Modified

- `subnet/server/server.py` — added ChainScoreSubmitter + SubnetNodeConsensusData imports; wired submitter instantiation (line 567) and submit() call (line 618) into _validator_scoring_loop
- `scripts/register_subnet.py` — new; subnet registration helper; mirrors check_peers.py credential/URL patterns; wraps register_subnet() with 8 CLI args
- `scripts/register_node.py` — new; node registration helper; friendly-ID resolution; wraps register_subnet_node() with peer_info dict construction
- `scripts/smoke_test_chain.py` — new; delegating smoke test; subprocess.run per sub-script; [PASS]/[FAIL] per check; exits 0/1 cleanly
- `tests/consensus/test_chain_submitter.py` — added test_wiring_pattern_two_nodes (6th test)
- `CHAIN.md` — replaced ~30-line stub with ~200-line 8-section full developer walkthrough
- `TESTING_LAYERS.md` — Layer 3 section expanded with check_scores.py, check_slash.py, smoke_test_chain.py command blocks
- `.github/workflows/ci.yml` — new; Layer 1 (pytest) + Layer 2 (compose config) + Layer 3 (chain smoke, continue-on-error) CI workflow

## Forward Intelligence

### What the next slice should know
- The milestone's live testnet UAT is the only remaining proof gate. `CHAIN.md` is the authoritative walkthrough; a new developer with no Substrate experience should be able to follow it from scratch.
- All four check scripts (`check_peers.py`, `check_scores.py`, `check_slash.py`, `smoke_test_chain.py`) follow the same credential/URL resolution pattern — any future diagnostic script should mirror this.
- `ChainScoreSubmitter` is now called in production. If the submit() behaviour needs to change, the call site is `server.py` line 618 inside `_validator_scoring_loop`.

### What's fragile
- `smoke_test_chain.py` delegates via subprocess path strings hardcoded as `scripts/check_peers.py` etc. — must be run from the repo root; breaks if invoked from a different working directory.
- `register_node.py` constructs `peer_info={"peer_id": args.peer_id, "ip": "", "port": 0}` — this is the minimum-viable format; if the Hypertensor chain pallet requires non-empty ip/port in a future version, the script will need updating.

### Authoritative diagnostics
- `docker compose logs validator | grep "Submitted scores"` — confirms ChainScoreSubmitter.submit() is being called each epoch in a live run
- `python3 scripts/smoke_test_chain.py --chain $ENDPOINT --subnet_id $ID --epoch $N --overwatch_node_id $OW_ID` — structured [PASS]/[FAIL] per sub-check; exit code 0 = all chain integrations healthy
- `python3 scripts/check_scores.py --chain $ENDPOINT --subnet_id $ID --epoch $N` — ground truth that submission landed on-chain (use this to confirm M005 milestone UAT)

### What assumptions changed
- The slice plan says `smoke_test_chain.py` uses `--chain=URL` as a positional-style arg to avoid two-token split in subprocess args list; T01 implemented this as a `--chain=URL` single-string positional to subprocess — no impact on verification but worth knowing if the script's subprocess arg construction is ever modified.
