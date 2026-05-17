---
estimated_steps: 8
estimated_files: 5
---

# T01: Wire ChainScoreSubmitter into scoring loop and write registration + smoke-test scripts

**Slice:** S04 — Chain Integration Docs + Smoke Tests
**Milestone:** M005

## Description

This task makes `ChainScoreSubmitter` actually run in production for the first time. The class was built and tested in S02 but never wired into the validator epoch loop. After this task, every epoch the validator scores peers, it also submits those scores on-chain via `propose_attestation`. It also produces the three remaining scripts needed to complete the chain tooling: `register_subnet.py`, `register_node.py`, and `smoke_test_chain.py`.

## Steps

1. **Add `ChainScoreSubmitter` import to `subnet/server/server.py`.**
   After the existing line `from subnet.consensus.chain_overwatch_reporter import ChainOverwatchReporter` (line ~66), add:
   ```python
   from subnet.consensus.chain_submitter import ChainScoreSubmitter
   from subnet.hypertensor.chain_data import SubnetNodeConsensusData
   ```
   Note: `SubnetNodeConsensusData` may already be imported indirectly — check first. If it is, skip that import line.

2. **Instantiate `ChainScoreSubmitter` before the `while` loop in `_validator_scoring_loop`.**
   `_validator_scoring_loop` is at line ~548. After the `loop_logger = ...` and `last_epoch = None` lines (before `await trio.sleep(30)`), add:
   ```python
   submitter = ChainScoreSubmitter(hypertensor, subnet_id)
   ```
   One instance per loop invocation, not per iteration.

3. **Collect scores during the per-epoch, per-node loop.**
   In the `if current_epoch != last_epoch and current_epoch >= 1:` block, before the `for node in nodes:` loop, add:
   ```python
   scores = []
   ```
   Inside the `try:` block that calls `scoring.score_peer()`, after the `loop_logger.info("[Validator] ...")` call, add:
   ```python
   scores.append(SubnetNodeConsensusData(
       subnet_node_id=node.subnet_node_id,
       score=int(peer_score.score * 1e18),
   ))
   ```
   This must be inside the `try:` that wraps `validator_call` + `score_peer` — peers that raise an exception `continue` past and are omitted from the batch (correct behaviour per research doc).

4. **Call `submitter.submit(scores)` after the per-node `for` loop.**
   After the `for node in nodes:` loop ends (but still inside the `if current_epoch != last_epoch` block), add:
   ```python
   if scores:
       submitter.submit(scores)
       loop_logger.info("[ValidatorLoop] Submitted scores epoch=%d count=%d", score_epoch, len(scores))
   ```
   The `if scores:` guard avoids an unnecessary empty extrinsic when all peers were unreachable.

5. **Write `scripts/register_subnet.py`.**
   Mirror `check_peers.py` exactly for: credential loading (`phrase = os.environ.get("PHRASE") or os.environ.get("TENSOR_PRIVATE_KEY") or ""`), URL resolution (`--local_rpc > --chain > $DEV_RPC > hardcoded default`), Hypertensor construction (`try/except` with `ERROR: Cannot connect to {url}: {exc}` + `sys.exit(1)`), and friendly-ID resolution is NOT needed here (registering creates a new subnet). CLI args: `--name` (str, required), `--repo` (str, default `""`), `--description` (str, default `""`), `--misc` (str, default `""`), `--max_cost` (int, default `100000000000000000000`), `--min_stake` (int, default `1000000000000000000`), `--max_stake` (int, default `100000000000000000000`), `--delegate_stake_percentage` (int, default `10`). For `initial_coldkeys` and `bootnodes` use hardcoded empty list defaults (document in help that these can be extended). Call `hypertensor.register_subnet(...)` and print `[OK] Subnet registered: {receipt.extrinsic_hash}` on success, `ERROR: Registration failed: {receipt.error_message}` on `not receipt.is_success`.

6. **Write `scripts/register_node.py`.**
   Same credential/URL/connection pattern as `register_subnet.py`. Resolve friendly subnet_id (< 128000 → `get_subnet_id_from_friendly_id`). Required CLI args: `--subnet_id` (int), `--hotkey` (str, help: "SS58 hotkey address"), `--peer_id` (str, help: "libp2p peer ID (e.g. 12D3Koo...); used as peer_info"), `--stake` (int, default `1000000000000000000`, help: "stake amount in planck (default 1 HTSR)"). Use `peer_info = {"peer_id": args.peer_id, "ip": "", "port": 0}` as the peer_info dict. `delegate_reward_rate=0`, `max_burn_amount=100000000000000000000` as hardcoded defaults. Document the format clearly in the docstring. Call `hypertensor.register_subnet_node(real_id, hotkey, peer_info, ...)` and print `[OK] Node registered: {receipt.extrinsic_hash}` on success.

7. **Write `scripts/smoke_test_chain.py`.**
   Non-interactive. Accept args: `--chain URL`, `--local_rpc` (flag), `--subnet_id INT` (required), `--epoch INT` (required), `--overwatch_node_id INT` (required). Build the URL using the same precedence as `check_peers.py`. For each sub-check, call the corresponding script via `subprocess.run([sys.executable, script_path, ...], check=False, capture_output=False)`. Sub-checks and their args:
   - `check_peers.py`: `[url_flag, "--subnet_id", str(args.subnet_id)]`
   - `check_scores.py`: `[url_flag, "--subnet_id", str(args.subnet_id), "--epoch", str(args.epoch)]`
   - `check_slash.py`: `[url_flag, "--overwatch_node_id", str(args.overwatch_node_id), "--epoch", str(args.epoch)]`
   After each `subprocess.run`, print `[PASS] <script_name>` if `returncode == 0`, else `[FAIL] <script_name> (exit {returncode})`. Collect failed checks. If any failed, `sys.exit(1)`. If all passed, `sys.exit(0)`. Use `check=False` — never let a sub-process crash bubble up as an unhandled exception.

8. **Add one regression test to `tests/consensus/test_chain_submitter.py`.**
   Add a test `test_wiring_pattern_two_nodes` that: creates two `SubnetNodeConsensusData(subnet_node_id=1, score=int(0.5 * 1e18))` and `SubnetNodeConsensusData(subnet_node_id=2, score=int(1.0 * 1e18))` entries; calls `ChainScoreSubmitter(mock_ht, 42).submit(scores)` where `mock_ht.propose_attestation` is a `MagicMock` returning a receipt; asserts `mock_ht.propose_attestation` was called once with `subnet_id=42` and `data` containing two dicts with `{"subnet_node_id": 1, "score": int(0.5e18)}` and `{"subnet_node_id": 2, "score": int(1.0e18)}`. This verifies the score type conversion and subnet_node_id field mapping are correct.

## Must-Haves

- [ ] `from subnet.consensus.chain_submitter import ChainScoreSubmitter` present in `server.py`
- [ ] `submitter = ChainScoreSubmitter(hypertensor, subnet_id)` instantiated once before the `while` loop in `_validator_scoring_loop`
- [ ] `submitter.submit(scores)` called after each epoch's per-node loop; scores collected as `List[SubnetNodeConsensusData]` with `score=int(peer_score.score * 1e18)` and `subnet_node_id=node.subnet_node_id`
- [ ] `register_subnet.py` exits 0 with `--help`; never echoes phrase; calls `hypertensor.register_subnet()`
- [ ] `register_node.py` exits 0 with `--help`; never echoes phrase; calls `hypertensor.register_subnet_node()`
- [ ] `smoke_test_chain.py` exits 1 cleanly (no traceback) when chain is unreachable; uses `subprocess.run(check=False)`
- [ ] `pytest tests/ -x -q` → 194+ passed, 1 skipped

## Verification

```bash
# Layer 1 still green:
pytest tests/ -x -q
# → 194+ passed, 1 skipped

# Regression test specifically:
pytest tests/consensus/test_chain_submitter.py -v
# → 6 passed

# ChainScoreSubmitter wired in server.py:
grep -n "ChainScoreSubmitter\|submitter\.submit" subnet/server/server.py
# → shows import + instantiation + .submit() call

# smoke_test_chain.py exits 1 cleanly (no Python traceback):
python scripts/smoke_test_chain.py --local_rpc --subnet_id 1 --epoch 0 --overwatch_node_id 1; echo EXIT=$?
# → [FAIL] check_peers.py (exit 1)
# → [FAIL] check_scores.py (exit 1)
# → [FAIL] check_slash.py (exit 1)
# → EXIT=1  (not a crash)

# Registration scripts import cleanly and show help:
python scripts/register_subnet.py --help; echo EXIT=$?
# → EXIT=0

python scripts/register_node.py --help; echo EXIT=$?
# → EXIT=0

# Credential redaction:
PHRASE="super secret mnemonic" python scripts/register_subnet.py --help 2>&1 | grep -i "super secret"; echo GREP_EXIT=$?
# → GREP_EXIT=1
```

## Observability Impact

- Signals added/changed: `logger.info("[ValidatorLoop] Submitted scores epoch=%d count=%d", ...)` added to validator scoring loop — visible in `docker compose logs validator | grep "Submitted scores"`; existing `⚠️ Score submission failed:` from `ChainScoreSubmitter.submit()` is unchanged
- How a future agent inspects this: `python scripts/check_scores.py --chain $ENDPOINT --subnet_id $ID --epoch $N` — ground truth that submission landed; `docker compose logs validator | grep "Submitted\|Score submission"` — runtime signal
- Failure state exposed: `smoke_test_chain.py` prints `[FAIL] <script> (exit N)` per failed sub-check; `ChainScoreSubmitter.submit()` already logs `⚠️ Score submission failed:` with error message

## Inputs

- `subnet/server/server.py` — `_validator_scoring_loop` at lines ~548–615; `hypertensor` and `subnet_id` already in scope as function args; `ChainOverwatchReporter` already imported at line ~66; loop structure already iterates `node.subnet_node_id` (from `SubnetNodeInfo` — see `get_min_class_subnet_nodes_formatted` which returns `List[SubnetNodeInfo]`)
- `subnet/consensus/chain_submitter.py` — `ChainScoreSubmitter(hypertensor, subnet_id).submit(scores: List[SubnetNodeConsensusData])` interface; no changes needed to this file
- `subnet/hypertensor/chain_data.py` — `SubnetNodeConsensusData` at line 1187 with fields `subnet_node_id: int` and `score: int`; `SubnetNodeInfo` at line 847 has `subnet_node_id` field
- `subnet/hypertensor/chain_functions.py` — `Hypertensor.register_subnet()` at line 272 (11 positional args); `Hypertensor.register_subnet_node()` at line 430 (6 required args + optional)
- `scripts/check_peers.py` — authoritative pattern for credential loading, URL resolution, Hypertensor construction, friendly-ID resolution, error handling — all registration/smoke-test scripts must mirror this exactly
- `tests/consensus/test_chain_submitter.py` — existing 5 unit tests using `MagicMock`; add test 6 (`test_wiring_pattern_two_nodes`) to the same file following the existing test structure

## Expected Output

- `subnet/server/server.py` — modified: `ChainScoreSubmitter` import added; `submitter` instantiated before `while` loop; `scores` list collected per epoch; `submitter.submit(scores)` called post-loop
- `scripts/register_subnet.py` — new (~100 lines); `--help` exits 0; credentials from env only; calls `hypertensor.register_subnet()`
- `scripts/register_node.py` — new (~100 lines); `--help` exits 0; credentials from env only; friendly-ID resolution; calls `hypertensor.register_subnet_node()`
- `scripts/smoke_test_chain.py` — new (~70 lines); delegates to 3 existing check scripts; exits 0/1 cleanly; no crash on connection failure
- `tests/consensus/test_chain_submitter.py` — modified: 1 test added (`test_wiring_pattern_two_nodes`); total 6 passed
