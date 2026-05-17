---
id: T01
parent: S04
milestone: M005
provides:
  - ChainScoreSubmitter wired into _validator_scoring_loop in server.py
  - scripts/register_subnet.py — on-chain subnet registration helper
  - scripts/register_node.py — on-chain node registration helper
  - scripts/smoke_test_chain.py — delegating CI-safe chain smoke test
  - test_wiring_pattern_two_nodes regression test added to test_chain_submitter.py
key_files:
  - subnet/server/server.py
  - scripts/register_subnet.py
  - scripts/register_node.py
  - scripts/smoke_test_chain.py
  - tests/consensus/test_chain_submitter.py
key_decisions:
  - scores[] list reset at top of each epoch block; only nodes that complete score_peer() are included — peers that raise exceptions are omitted from the batch (correct per plan)
  - submitter instantiated once before the while loop (not per-iteration) to match plan
  - smoke_test_chain.py uses url_flag as a positional-style string for --chain=URL to avoid two-token split when building subprocess args list
patterns_established:
  - Registration scripts mirror check_peers.py exactly for credential loading (env-only), URL resolution (--local_rpc > --chain > $DEV_RPC > hardcoded), Hypertensor construction with try/except, and sys.exit(1) on failure
  - Smoke test delegates to sub-scripts via subprocess.run(check=False); prints [PASS]/[FAIL] per check; exits 0 only if all pass
observability_surfaces:
  - logger.info("[ValidatorLoop] Submitted scores epoch=%d count=%d", ...) in scoring loop — visible via docker compose logs validator | grep "Submitted scores"
  - smoke_test_chain.py prints [FAIL] <script> (exit N) per failed sub-check — structured failure output confirming error path works without crash
  - Existing ChainScoreSubmitter.submit() logs "⚠️ Score submission failed:" on receipt.is_success=False unchanged
duration: 25m
verification_result: passed
completed_at: 2026-03-17
blocker_discovered: false
---

# T01: Wire ChainScoreSubmitter into scoring loop and write registration + smoke-test scripts

**Wired ChainScoreSubmitter into _validator_scoring_loop and added register_subnet.py, register_node.py, smoke_test_chain.py, and a two-node wiring regression test.**

## What Happened

1. Added `from subnet.consensus.chain_submitter import ChainScoreSubmitter` and `from subnet.hypertensor.chain_data import SubnetNodeConsensusData` imports to `server.py` after the existing `ChainOverwatchReporter` import.
2. Instantiated `submitter = ChainScoreSubmitter(hypertensor, subnet_id)` once before the `while` loop in `_validator_scoring_loop`.
3. Added `scores = []` before the per-node `for` loop inside the epoch block; appended `SubnetNodeConsensusData(subnet_node_id=node.subnet_node_id, score=int(peer_score.score * 1e18))` inside the `try:` block after `score_peer()` succeeds (exception path skips append — correct).
4. Added `if scores: submitter.submit(scores); loop_logger.info(...)` after the for loop.
5. Wrote `scripts/register_subnet.py` mirroring `check_peers.py` pattern exactly; wraps `hypertensor.register_subnet()` with 8 CLI args and empty list defaults for `initial_coldkeys`/`bootnodes`.
6. Wrote `scripts/register_node.py` with friendly-ID resolution; wraps `hypertensor.register_subnet_node()` with `peer_info={"peer_id": args.peer_id, "ip": "", "port": 0}`.
7. Wrote `scripts/smoke_test_chain.py` delegating to 3 sub-scripts via `subprocess.run(check=False)`; exits 1 cleanly on connection failure.
8. Added `test_wiring_pattern_two_nodes` to `tests/consensus/test_chain_submitter.py` — 6th test, verifies score type conversion and subnet_node_id field mapping.

## Verification

```
pytest tests/ -x -q                          → 194 passed, 1 skipped
pytest tests/consensus/test_chain_submitter.py -v → 6 passed
grep -n "ChainScoreSubmitter|submitter.submit" subnet/server/server.py
  → 67: from subnet.consensus.chain_submitter import ChainScoreSubmitter
  → 567: submitter = ChainScoreSubmitter(hypertensor, subnet_id)
  → 618: submitter.submit(scores)
python3 scripts/register_subnet.py --help    → EXIT=0
python3 scripts/register_node.py --help      → EXIT=0
python3 scripts/smoke_test_chain.py --local_rpc --subnet_id 1 --epoch 0 --overwatch_node_id 1
  → [FAIL] check_peers.py (exit 1)
  → [FAIL] check_scores.py (exit 1)
  → [FAIL] check_slash.py (exit 1)
  → EXIT=1  (no traceback)
PHRASE="super secret mnemonic" python3 scripts/register_subnet.py --help 2>&1 | grep -i "super secret"
  → GREP_EXIT=1 (redaction confirmed)
```

## Diagnostics

- `docker compose logs validator | grep "Submitted scores"` — confirms submission ran each epoch
- `python3 scripts/smoke_test_chain.py --chain $ENDPOINT --subnet_id $ID --epoch $N --overwatch_node_id $OW_ID` — structured [PASS]/[FAIL] per sub-check
- `python3 scripts/check_scores.py --chain $ENDPOINT --subnet_id $ID --epoch $N` — ground truth that submission landed on-chain
- `docker compose logs validator | grep "Score submission failed"` — surfaces failed receipts from ChainScoreSubmitter

## Deviations

None — all steps executed as written in the plan.

## Known Issues

None.

## Files Created/Modified

- `subnet/server/server.py` — added ChainScoreSubmitter + SubnetNodeConsensusData imports; wired submitter instantiation and submit() call into _validator_scoring_loop
- `scripts/register_subnet.py` — new; subnet registration helper mirroring check_peers.py patterns
- `scripts/register_node.py` — new; node registration helper with friendly-ID resolution
- `scripts/smoke_test_chain.py` — new; delegating smoke test; exits 0/1 cleanly; structured [PASS]/[FAIL] output
- `tests/consensus/test_chain_submitter.py` — added test_wiring_pattern_two_nodes (6th test)
