---
id: S04
parent: M005
milestone: M005
uat_type: artifact-driven
---

# S04: Chain Integration Docs + Smoke Tests — UAT

**Milestone:** M005
**Written:** 2026-03-17

## UAT Type

- UAT mode: artifact-driven (CI + script outputs) + human-experience (CHAIN.md walkthrough)
- Why this mode is sufficient: The slice's contract is that a new developer can follow CHAIN.md from scratch and that smoke_test_chain.py exits cleanly in CI without a live chain. Both are verifiable without live testnet access. Live testnet UAT (registered subnet, scores on-chain, slash confirmed) is milestone-level UAT — documented in CHAIN.md and deferred to M005 sign-off.

## Preconditions

- Working directory: repo root (`/home/aphex5/work/subnet-template/.gsd/worktrees/M001`)
- Python 3.11 available as `python3`
- Dependencies installed: `pip install -e ".[dev]"`
- No local Hypertensor node running (tests the graceful-failure path)
- `docker` and `docker compose` available for Layer 2 check

## Smoke Test

```bash
# All three layers: pytest green + smoke exits 1 cleanly
pytest tests/ -x -q && echo "LAYER1=OK"
python3 scripts/smoke_test_chain.py --local_rpc --subnet_id 1 --epoch 0 --overwatch_node_id 1; echo EXIT=$?
```
Expected: `194 passed, 1 skipped` then `EXIT=1` with three `[FAIL]` lines (no traceback).

---

## Test Cases

### 1. Layer 1 still green (ChainScoreSubmitter wiring regression)

```bash
pytest tests/ -x -q
```
**Expected:** `194 passed, 1 skipped` — no new failures introduced by wiring ChainScoreSubmitter into server.py. The `test_wiring_pattern_two_nodes` test (6th test in test_chain_submitter.py) is included in the count.

```bash
pytest tests/consensus/test_chain_submitter.py -v
```
**Expected:** 6 passed — all six tests including `test_wiring_pattern_two_nodes`.

---

### 2. ChainScoreSubmitter wired in server.py

```bash
grep -n "ChainScoreSubmitter\|submitter\.submit" subnet/server/server.py
```
**Expected:**
```
67:from subnet.consensus.chain_submitter import ChainScoreSubmitter
567:    submitter = ChainScoreSubmitter(hypertensor, subnet_id)
618:                    submitter.submit(scores)
```
Three lines: import at top, instantiation before `while` loop, submit() call inside epoch block.

---

### 3. smoke_test_chain.py: graceful structured failure

```bash
python3 scripts/smoke_test_chain.py --local_rpc --subnet_id 1 --epoch 0 --overwatch_node_id 1
echo EXIT=$?
```
**Expected:**
```
ERROR: Cannot connect to ws://127.0.0.1:9944: [Errno 111] Connection refused   ← from check_peers.py
ERROR: Cannot connect to ws://127.0.0.1:9944: [Errno 111] Connection refused   ← from check_scores.py
ERROR: Cannot connect to ws://127.0.0.1:9944: [Errno 111] Connection refused   ← from check_slash.py
[FAIL] check_peers.py (exit 1)
[FAIL] check_scores.py (exit 1)
[FAIL] check_slash.py (exit 1)
EXIT=1
```
No Python traceback. Structured `[FAIL]` lines confirm error path works without crash.

```bash
# Confirm structured [FAIL] output separately:
python3 scripts/smoke_test_chain.py --local_rpc --subnet_id 1 --epoch 0 --overwatch_node_id 1 2>&1 | grep "\[FAIL\]"; echo FAIL_LINES=$?
```
**Expected:** 3 `[FAIL]` lines printed, `FAIL_LINES=0` (grep matched).

---

### 4. register_subnet.py: help exits 0, credentials never echoed

```bash
python3 scripts/register_subnet.py --help; echo EXIT=$?
```
**Expected:** Full usage block showing `--name`, `--repo`, `--description`, `--misc`, `--max_cost`, `--min_stake`, `--max_stake`, `--delegate_stake_percentage` args; `EXIT=0`.

```bash
PHRASE="super secret mnemonic" python3 scripts/register_subnet.py --help 2>&1 | grep -i "super secret"; echo GREP_EXIT=$?
```
**Expected:** `GREP_EXIT=1` (no match = phrase never echoed in help output or error messages).

---

### 5. register_node.py: help exits 0, friendly-ID documented

```bash
python3 scripts/register_node.py --help; echo EXIT=$?
```
**Expected:** Usage block showing `--subnet_id`, `--hotkey`, `--peer_id`, `--stake` args; help text mentions "Values < 128000 are treated as friendly IDs and resolved"; `EXIT=0`.

---

### 6. CHAIN.md: full walkthrough, stub removed

```bash
grep -c "register_subnet\|register_node\|faucet\|\[WARN\]" CHAIN.md
```
**Expected:** Count ≥ 4 (actual: 9).

```bash
grep -i "coming in M005" CHAIN.md; echo GREP_EXIT=$?
```
**Expected:** `GREP_EXIT=1` (stub placeholder removed).

```bash
# Confirm 8 sections present:
grep "^## " CHAIN.md
```
**Expected:** At least: Prerequisites, Steps (1–6 or equivalent), Troubleshooting.

---

### 7. CHAIN.md: [WARN] vs [OK] semantics documented

```bash
grep -A3 "\[WARN\]" CHAIN.md | head -20
```
**Expected:** A table or explanation distinguishing `[WARN]` (no data yet, first 2-3 epochs, not an error) from `[OK]` (data present) and `ERROR:` (connection failure).

---

### 8. TESTING_LAYERS.md: Layer 3 references all check scripts

```bash
grep "check_scores\|check_slash\|smoke_test" TESTING_LAYERS.md | wc -l
```
**Expected:** Count ≥ 3 (actual: 6).

---

### 9. CI workflow: Layer 1 + Layer 2 blocking, Layer 3 informational

```bash
test -f .github/workflows/ci.yml && echo "EXISTS"
grep -c "pytest\|docker compose" .github/workflows/ci.yml
```
**Expected:** `EXISTS` then count ≥ 2 (actual: 3).

```bash
grep "continue-on-error" .github/workflows/ci.yml
```
**Expected:** `continue-on-error: true` — confirms Layer 3 does not block PRs.

```bash
# Confirm Layer 1 and Layer 2 do NOT have continue-on-error:
grep -B5 "continue-on-error" .github/workflows/ci.yml | grep "name:"
```
**Expected:** Only the Layer 3 / chain smoke step is shown — pytest and docker compose steps have no continue-on-error.

---

### 10. Layer 2 unaffected

```bash
docker compose -f docker-compose.tee-dev.yml config > /dev/null; echo EXIT=$?
```
**Expected:** `EXIT=0` (compose config valid; version warning is cosmetic and acceptable).

---

## Edge Cases

### smoke_test_chain.py with --chain flag (not --local_rpc)

```bash
python3 scripts/smoke_test_chain.py --chain ws://127.0.0.1:9944 --subnet_id 1 --epoch 0 --overwatch_node_id 1; echo EXIT=$?
```
**Expected:** Same `[FAIL]` output as `--local_rpc`; `EXIT=1`. Confirms `--chain` path works (not just the `--local_rpc` shortcut).

### register_subnet.py with --local_rpc (connection expected to fail gracefully)

```bash
PHRASE="dummy_mnemonic" python3 scripts/register_subnet.py --local_rpc --name test_subnet; echo EXIT=$?
```
**Expected:** `ERROR: ...` message (connection refused or auth failure); `EXIT=1`. No traceback — graceful failure with sys.exit(1).

### register_node.py friendly-ID resolution boundary (subnet_id < 128000)

```bash
python3 scripts/register_node.py --help 2>&1 | grep "128000"
```
**Expected:** Line mentioning "Values < 128000 are treated as friendly IDs" — documents the resolution boundary in the help text.

### smoke_test_chain.py with all three sub-scripts independently passing

If a live testnet is available:
```bash
export CHAIN_ENDPOINT=wss://rpc.hypertensor.app:443
export PHRASE=<funded_mnemonic>
python3 scripts/smoke_test_chain.py --chain $CHAIN_ENDPOINT --subnet_id $SUBNET_ID --epoch $EPOCH --overwatch_node_id $OW_ID
echo EXIT=$?
```
**Expected:** `[PASS] check_peers.py`, `[PASS] check_scores.py` (or `[WARN]` exit 0), `[PASS] check_slash.py` (or `[WARN]` exit 0); `EXIT=0`.

---

## Failure Signals

- `pytest` shows fewer than 194 tests — server.py wiring broke an existing test
- `smoke_test_chain.py` raises a Python traceback instead of `[FAIL]` lines — graceful error handling broken
- `register_subnet.py --help` exits non-zero — argparse registration broken
- `CHAIN.md` contains "coming in M005" — stub was not replaced
- `.github/workflows/ci.yml` missing or empty — CI integration not written
- Layer 3 CI step has no `continue-on-error: true` — will permanently block all PRs with no testnet
- `grep -n "submitter.submit" subnet/server/server.py` returns nothing — ChainScoreSubmitter never called in production

---

## Requirements Proved By This UAT

- R022 (test coverage) — 194 tests green including wiring regression test for ChainScoreSubmitter integration

## Not Proven By This UAT

- Live score submission on Hypertensor testnet — requires funded wallet, registered subnet, 2+ nodes, real network. Human UAT documented in CHAIN.md Steps 1–6.
- Token emissions proportional to scores after epoch finalisation — requires live testnet run and `substrate.query("SubnetModule", "PeerScores", [subnet_id])` verification.
- Slash confirmed on-chain (`TAMPER_RATE=1.0`) — requires live testnet run and block explorer confirmation.
- These are M005 milestone-level UAT gates, not S04 slice-level gates.

---

## Notes for Tester

- Run all commands from the **repo root** — `smoke_test_chain.py` delegates to `scripts/check_*.py` via relative paths and will fail if run from a subdirectory.
- `[WARN]` output from any check script is **not an error** — it means the chain is reachable but has no data yet for that subnet/epoch. Only `ERROR:` lines indicate a connection or auth problem.
- For the live testnet walkthrough, follow `CHAIN.md` sequentially from Prerequisites through Step 6. The Troubleshooting table maps the most common errors (wrong endpoint, missing phrase, subnet not registered) to diagnostic commands.
- The CI workflow uses `python` (not `python3`) — correct for GitHub Actions' Ubuntu runner. Local environments where only `python3` is available must use `python3` directly.
- Expected test count is 194 passed, 1 skipped. The 1 skipped test is a pre-existing skip (not introduced in S04).
