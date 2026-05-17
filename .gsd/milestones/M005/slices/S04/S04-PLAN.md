# S04: Chain Integration Docs + Smoke Tests

**Goal:** Wire `ChainScoreSubmitter` into the validator epoch loop; write `register_subnet.py`, `register_node.py`, and `smoke_test_chain.py`; expand `CHAIN.md` from stub to full developer walkthrough; add CI GitHub Actions workflow. After this, a new developer can follow `CHAIN.md` and get a running subnet on testnet from scratch, and `smoke_test_chain.py` passes (exits 1 gracefully) in CI.

**Demo:** `scripts/smoke_test_chain.py --local_rpc --subnet_id 1 --epoch 0 --overwatch_node_id 1` exits 1 with `ERROR: Cannot connect` per sub-check (graceful, no crash); `pytest tests/ -x -q` shows 194+ passed, 1 skipped; `CHAIN.md` has registration, staking, monitoring, and `[WARN]` vs `[OK]` semantics; `.github/workflows/ci.yml` runs Layer 1 + Layer 2 checks.

## Must-Haves

- `ChainScoreSubmitter` imported in `server.py` and instantiated once before the `while` loop in `_validator_scoring_loop`; calls `submitter.submit(scores)` after each epoch's peer loop with collected `SubnetNodeConsensusData` entries
- `scripts/register_subnet.py` and `scripts/register_node.py` — interactive registration helpers following `check_peers.py` credential/URL patterns exactly; credentials never echoed
- `scripts/smoke_test_chain.py` — delegates to `check_peers.py`, `check_scores.py`, `check_slash.py` via `subprocess.run(check=False)`; exits 0 only when all pass; exits 1 gracefully when chain is unreachable (no crash)
- `CHAIN.md` expanded from stub to full walkthrough: faucet/key setup, register_subnet.py, register_node.py, running the stack, monitoring with check scripts, `[WARN]` vs `[OK]` semantics, expected time-to-first-submission
- `.github/workflows/ci.yml` — Layer 1 (`pytest tests/`) and Layer 2 (`docker compose config`) steps; chain smoke test step skipped gracefully when `CHAIN_ENDPOINT` unset
- Layer 1 still green: 194+ passed, 1 skipped (includes new wiring regression test)

## Proof Level

- This slice proves: final-assembly
- Real runtime required: no (chain unreachable in CI; graceful exits suffice for slice proof)
- Human/UAT required: yes — `CHAIN.md` walkthrough must be reproducible by a new developer; live testnet proof is milestone-level UAT

## Verification

```bash
# 1. Layer 1 still green (includes new wiring test):
pytest tests/ -x -q
# → 194+ passed, 1 skipped

# 2. smoke_test_chain.py exits 1 gracefully (no crash, no traceback) on no local node:
python scripts/smoke_test_chain.py --local_rpc --subnet_id 1 --epoch 0 --overwatch_node_id 1; echo EXIT=$?
# → ERROR: Cannot connect ... (per sub-check)
# → EXIT=1  (not a crash, not a Python traceback)

# 3. register_subnet.py --help exits 0:
python scripts/register_subnet.py --help; echo EXIT=$?
# → EXIT=0

# 4. register_node.py --help exits 0:
python scripts/register_node.py --help; echo EXIT=$?
# → EXIT=0

# 5. Credential redaction on registration scripts:
PHRASE="super secret mnemonic" python scripts/register_subnet.py --help 2>&1 | grep -i "super secret"; echo GREP_EXIT=$?
# → GREP_EXIT=1  (no match = redaction confirmed)

# 6. CHAIN.md has registration content (not a stub):
grep -c "register_subnet\|register_node\|faucet\|\[WARN\]" CHAIN.md
# → count > 0

# 7. CI workflow exists and references pytest + docker compose:
grep -c "pytest\|docker compose" .github/workflows/ci.yml
# → count >= 2

# 8. Layer 2 unaffected:
docker compose -f docker-compose.tee-dev.yml config > /dev/null; echo EXIT=$?
# → EXIT=0

# 9. ChainScoreSubmitter wired: scoring loop collects scores and calls submit():
grep -n "ChainScoreSubmitter\|submitter.submit" subnet/server/server.py
# → shows import + instantiation + submit() call

# 10. Failure-path: smoke_test_chain.py emits structured [FAIL] lines (not a crash):
python scripts/smoke_test_chain.py --local_rpc --subnet_id 1 --epoch 0 --overwatch_node_id 1 2>&1 | grep "\[FAIL\]"; echo "FAIL_LINES=$?"
# → [FAIL] check_peers.py (exit 1)
# → [FAIL] check_scores.py (exit 1)
# → [FAIL] check_slash.py (exit 1)
# → FAIL_LINES=0  (grep matched — structured failure output confirmed)
```

## Observability / Diagnostics

**Inspectable failure-state checks (run after T02):**
```bash
# CI workflow missing or broken → no automated verification:
test -f .github/workflows/ci.yml && grep -q "continue-on-error" .github/workflows/ci.yml && echo "CI OK" || echo "CI MISSING or BROKEN"

# CHAIN.md still a stub → developer cannot follow walkthrough:
grep -i "coming in M005" CHAIN.md; echo "GREP_EXIT=$?"
# GREP_EXIT=1 means stub removed correctly

# smoke_test_chain.py structured failure output (not crash):
python scripts/smoke_test_chain.py --local_rpc --subnet_id 1 --epoch 0 --overwatch_node_id 1 2>&1 | grep "\[FAIL\]"
# → [FAIL] check_peers.py (exit 1) — connection failure is structured, not a traceback

# Layer 2 compose config unaffected after CI workflow added:
docker compose -f docker-compose.tee-dev.yml config > /dev/null; echo EXIT=$?
# → EXIT=0
```

- Runtime signals: `logger.info("[ValidatorLoop] Submitted scores epoch=%d count=%d", epoch, len(scores))` after each successful submission batch; existing `⚠️ Score submission failed:` and `Score submission exception:` from `ChainScoreSubmitter` unchanged
- Inspection surfaces: `python scripts/smoke_test_chain.py --chain $ENDPOINT --subnet_id $ID --epoch $N --overwatch_node_id $OW_ID`; `python scripts/check_peers.py / check_scores.py / check_slash.py` individually; `.github/workflows/ci.yml` Actions run log
- Failure visibility: Each sub-check in `smoke_test_chain.py` prints `[PASS]` or `[FAIL]` with the script exit code; final exit code is 0 (all pass) or 1 (any fail); connection failures surface `ERROR: Cannot connect` from the delegated script
- Redaction constraints: `PHRASE`/`TENSOR_PRIVATE_KEY` read from env in all scripts; never passed to argparse or printed; `register_subnet.py` / `register_node.py` must not echo phrase in help output or error messages

## Integration Closure

- Upstream surfaces consumed: `ChainScoreSubmitter(hypertensor, subnet_id).submit(scores: List[SubnetNodeConsensusData])` from `subnet/consensus/chain_submitter.py`; `SubnetNodeConsensusData(subnet_node_id, score)` from `subnet/hypertensor/chain_data.py`; `Hypertensor.register_subnet()` / `register_subnet_node()` from `subnet/hypertensor/chain_functions.py`; `check_peers.py`, `check_scores.py`, `check_slash.py` patterns as delegation targets
- New wiring introduced in this slice: `ChainScoreSubmitter` import + instantiation in `server.py`; `submit(scores)` call at end of each scoring epoch in `_validator_scoring_loop`; `smoke_test_chain.py` delegates to all three existing check scripts
- What remains before the milestone is truly usable end-to-end: live testnet run with registered subnet + at least 2 nodes (human UAT); `TAMPER_RATE=1.0` slash confirmation on-chain; scores visible via `substrate.query("SubnetModule", "PeerScores")`

## Tasks

- [x] **T01: Wire ChainScoreSubmitter into scoring loop and write registration + smoke-test scripts** `est:45m`
  - Why: The only production code change in S04 — without it, `ChainScoreSubmitter` exists but is never called; registration scripts and `smoke_test_chain.py` complete the chain integration tooling
  - Files: `subnet/server/server.py`, `scripts/register_subnet.py`, `scripts/register_node.py`, `scripts/smoke_test_chain.py`, `tests/consensus/test_chain_submitter.py`
  - Do: (1) Add `from subnet.consensus.chain_submitter import ChainScoreSubmitter` import in `server.py` alongside the existing `ChainOverwatchReporter` import; (2) In `_validator_scoring_loop`, instantiate `submitter = ChainScoreSubmitter(hypertensor, subnet_id)` once before the `while` loop; (3) Inside the per-epoch block, collect `SubnetNodeConsensusData` entries after each successful `score_peer()` call into a `scores: list` (reset to `[]` at top of each epoch); convert score with `int(peer_score.score * 1e18)` and use `node.subnet_node_id` as the ID; (4) After the per-node `for` loop, call `submitter.submit(scores)` and log `[ValidatorLoop] Submitted scores epoch=%d count=%d`; (5) Write `scripts/register_subnet.py` mirroring `check_peers.py` credential/URL pattern; wraps `hypertensor.register_subnet(max_cost, name, repo, description, misc, min_stake, max_stake, delegate_stake_percentage, initial_coldkeys, bootnodes)` with `--name`, `--repo`, `--description`, `--misc`, `--min_stake`, `--max_stake`, `--delegate_stake_percentage`, `--max_cost` CLI args and sensible defaults; never echoes phrase; prints `[OK] Subnet registered: <extrinsic_hash>` or `ERROR: Registration failed: <reason>`; (6) Write `scripts/register_node.py` wrapping `hypertensor.register_subnet_node(subnet_id, hotkey, peer_info, delegate_reward_rate, stake_to_be_added, max_burn_amount)` with CLI args; documents `peer_info` format in help text; (7) Write `scripts/smoke_test_chain.py` that delegates to `check_peers.py`, `check_scores.py`, `check_slash.py` via `subprocess.run(check=False)`; accepts `--chain`/`--local_rpc`/`--subnet_id`/`--epoch`/`--overwatch_node_id` args; prints `[PASS]` or `[FAIL] <script> exited N` per check; exits 0 only when all pass; never raises on connection failure; (8) Add one regression test to `tests/consensus/test_chain_submitter.py` that mocks `_validator_scoring_loop`-style usage: 2 nodes scored, `submit()` called once with correct `SubnetNodeConsensusData` list (subnet_node_id + int score)
  - Verify: `pytest tests/ -x -q` → 194+ passed, 1 skipped; `python scripts/smoke_test_chain.py --local_rpc --subnet_id 1 --epoch 0 --overwatch_node_id 1; echo EXIT=$?` → EXIT=1 no traceback; `python scripts/register_subnet.py --help; echo EXIT=$?` → EXIT=0; `grep -n "submitter.submit" subnet/server/server.py` shows the call site
  - Done when: pytest green at 194+, smoke_test_chain.py exits 1 cleanly on no local node, both registration scripts show `--help` without error

- [x] **T02: Expand CHAIN.md, update TESTING_LAYERS.md, and add CI workflow** `est:30m`
  - Why: Completes the developer-facing documentation and CI integration that make the chain tooling discoverable and automatically verified
  - Files: `CHAIN.md`, `TESTING_LAYERS.md`, `.github/workflows/ci.yml`
  - Do: (1) Replace `CHAIN.md` stub content with full walkthrough covering: prerequisites (faucet URL, `subkey` for key generation, required env vars); step-by-step registration flow (`register_subnet.py` then `register_node.py` with example values and expected output); running the full stack (`docker-compose.chain.yml`); monitoring epoch-by-epoch with `check_peers.py`, `check_scores.py`, `check_slash.py`; `[WARN]` vs `[OK]` semantics (WARN = no data yet, not an error); expected time-to-first-submission (typically 2-3 epochs after startup); MOCK_TEE=true note (no EPYC hardware needed for testnet); troubleshooting section pointing to each check script; (2) Update `TESTING_LAYERS.md` Layer 3 section to reference `check_scores.py` and `check_slash.py` usage commands and add `smoke_test_chain.py` as the combined Layer 3 smoke test command; (3) Create `.github/workflows/ci.yml` with a single job `ci` on push/PR to `main`: step 1 sets up Python 3.11 + `pip install -e ".[dev]"`; step 2 runs `pytest tests/ -x -q` (Layer 1); step 3 runs `docker compose -f docker-compose.tee-dev.yml config` (Layer 2 config validation); step 4 runs `python scripts/smoke_test_chain.py --local_rpc --subnet_id 1 --epoch 0 --overwatch_node_id 1 || true` with comment "# No testnet in CI — expect exit 1 (graceful); step is informational only" and `continue-on-error: true` so CI does not fail on expected chain absence
  - Verify: `grep -c "register_subnet\|register_node\|faucet\|\[WARN\]" CHAIN.md` → count > 3; `grep -c "pytest\|docker compose" .github/workflows/ci.yml` → count >= 2; `grep "check_scores\|check_slash\|smoke_test" TESTING_LAYERS.md` → shows new references; `docker compose -f docker-compose.tee-dev.yml config > /dev/null; echo EXIT=$?` → EXIT=0
  - Done when: `CHAIN.md` has ≥4 sections (prerequisites, registration, running, monitoring); `.github/workflows/ci.yml` exists with pytest + compose steps; TESTING_LAYERS.md references `smoke_test_chain.py`

## Files Likely Touched

- `subnet/server/server.py` — add `ChainScoreSubmitter` import; wire into `_validator_scoring_loop`
- `tests/consensus/test_chain_submitter.py` — add regression test for wiring pattern
- `scripts/register_subnet.py` — new; registration helper
- `scripts/register_node.py` — new; node registration helper
- `scripts/smoke_test_chain.py` — new; CI-safe delegating smoke test
- `CHAIN.md` — expand from stub to full walkthrough
- `TESTING_LAYERS.md` — add check_scores.py / check_slash.py / smoke_test_chain.py references
- `.github/workflows/ci.yml` — new; Layer 1 + Layer 2 + chain smoke test (informational)
