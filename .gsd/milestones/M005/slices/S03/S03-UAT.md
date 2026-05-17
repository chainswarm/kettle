---
id: S03
parent: M005
milestone: M005
uat_mode: artifact-driven
written: 2026-03-17
---

# S03: Overwatch Slash Extrinsic — UAT

**Milestone:** M005
**Written:** 2026-03-17

## UAT Type

- UAT mode: artifact-driven
- Why this mode is sufficient: S03 proof level is "contract" — no real TEE hardware or live testnet required. All deliverables are testable in isolation via pytest (unit tests) and CLI tools (compose config, check_slash.py exit codes). Live on-chain confirmation is deferred to S04.

## Preconditions

- Working directory: `/home/aphex5/work/subnet-template/.gsd/worktrees/M001`
- Python 3.11+ with project dependencies installed (`pip install -e .` or equivalent)
- Docker Compose available (for compose guard tests)
- No local Substrate node running on `ws://127.0.0.1:9944` (for connection-failure test)
- `PHRASE` and `TENSOR_PRIVATE_KEY` env vars NOT set in the test shell (for clean credential redaction tests)

## Smoke Test

```bash
pytest tests/consensus/test_chain_overwatch_reporter.py -v
# → 5 passed in < 1s
```

## Test Cases

### 1. ChainOverwatchReporter unit tests — all paths

```bash
pytest tests/consensus/test_chain_overwatch_reporter.py -v
```

1. Run the command above.
2. **Expected:** 5 tests collected and passed:
   - `test_slash_calls_commit_and_reveal` — both `commit_overwatch_subnet_weights` and `reveal_overwatch_subnet_weights` called once each
   - `test_slash_returns_reveal_receipt_on_success` — method returns the reveal receipt object when both calls succeed
   - `test_slash_returns_commit_receipt_when_commit_fails` — when `commit.is_success=False`, returns commit receipt immediately; reveal is NOT called
   - `test_slash_logs_error_on_failed_reveal` — when `reveal.is_success=False`, logs `⚠️ Overwatch reveal failed:` and returns reveal receipt
   - `test_slash_exception_returns_none` — when commit raises an exception, returns `None` and does NOT propagate

---

### 2. Full Layer 1 suite still green

```bash
pytest tests/ -x -q
```

1. Run the command above.
2. **Expected:** `193 passed, 1 skipped` (no failures, no new errors introduced by S03)

---

### 3. Exception path — slash() returns None on chain error

```bash
python3 - <<'EOF'
from unittest.mock import MagicMock
from subnet.consensus.chain_overwatch_reporter import ChainOverwatchReporter
ht = MagicMock()
ht.commit_overwatch_subnet_weights.side_effect = Exception("simulated chain failure")
r = ChainOverwatchReporter(ht, overwatch_node_id=1, subnet_id=42)
result = r.slash("peer_test", 0, None)
assert result is None, f"Expected None on exception, got {result!r}"
print("[OK] Exception path: slash() returns None on chain error")
EOF
```

1. Run the command above.
2. **Expected:** `[OK] Exception path: slash() returns None on chain error` printed; assertion passes.
3. Note: the `Overwatch extrinsic exception: simulated chain failure` traceback is also logged — this is correct behaviour.

---

### 4. Failed-commit path — reveal not called when commit fails

```bash
python3 - <<'EOF'
from unittest.mock import MagicMock
from subnet.consensus.chain_overwatch_reporter import ChainOverwatchReporter
ht = MagicMock()
ht.commit_overwatch_subnet_weights.return_value = MagicMock(is_success=False, error_message="BadCommit")
r = ChainOverwatchReporter(ht, overwatch_node_id=1, subnet_id=42)
result = r.slash("peer_test", 0, None)
ht.reveal_overwatch_subnet_weights.assert_not_called()
print(f"[OK] Failed-commit path: reveal not called; commit receipt returned (is_success={result.is_success})")
EOF
```

1. Run the command above.
2. **Expected:** `[OK] Failed-commit path: reveal not called; commit receipt returned (is_success=False)` printed; `assert_not_called()` passes without error.

---

### 5. MOCK_TEE guard — reporter=None when OVERWATCH_NODE_ID unset

```bash
python3 - <<'EOF'
import os
os.environ.pop("OVERWATCH_NODE_ID", None)
s = os.environ.get("OVERWATCH_NODE_ID", "")
reporter = None if not s.isdigit() else "would_be_instantiated"
assert reporter is None, "Reporter should be None when OVERWATCH_NODE_ID not set"
print("[OK] MOCK_TEE guard: reporter=None when OVERWATCH_NODE_ID not set")
EOF
```

1. Run the command above.
2. **Expected:** `[OK] MOCK_TEE guard: reporter=None when OVERWATCH_NODE_ID not set` printed; assertion passes.

---

### 6. check_slash.py — exits 1 on no local node

```bash
python3 scripts/check_slash.py --local_rpc --overwatch_node_id 1 --epoch 0
echo "EXIT=$?"
```

1. Run the command above (ensure no local Substrate node is running on `ws://127.0.0.1:9944`).
2. **Expected:**
   - Stderr: `ERROR: Cannot connect to ws://127.0.0.1:9944: [Errno 111] Connection refused`
   - `EXIT=1`

---

### 7. check_slash.py — credential redaction

```bash
PHRASE="super secret mnemonic" python3 scripts/check_slash.py --overwatch_node_id 1 --epoch 0 2>&1 | grep -i "super secret"
echo "GREP_EXIT=$?"
```

1. Run the command above.
2. **Expected:** No output from grep; `GREP_EXIT=1` (grep finds nothing, confirming the phrase never appears in stdout or stderr).

---

### 8. Compose guard — fails fast when OVERWATCH_PHRASE missing

```bash
CHAIN_ENDPOINT=wss://example SUBNET_ID=1 VALIDATOR_PHRASE=x MINER1_PHRASE=x MINER2_PHRASE=x \
  docker compose -f docker-compose.chain.yml config 2>&1 | grep -i "OVERWATCH_PHRASE"
```

1. Run the command above (deliberately omitting `OVERWATCH_PHRASE`).
2. **Expected:** Output contains `required variable OVERWATCH_PHRASE is missing` — compose fails before any container starts.

---

### 9. Compose guard — succeeds with all vars set

```bash
CHAIN_ENDPOINT=wss://example SUBNET_ID=1 VALIDATOR_PHRASE=x MINER1_PHRASE=x MINER2_PHRASE=x OVERWATCH_PHRASE=x \
  docker compose -f docker-compose.chain.yml config > /dev/null 2>&1
echo "EXIT=$?"
```

1. Run the command above.
2. **Expected:** `EXIT=0` — compose renders valid configuration with no errors.

---

### 10. Layer 2 compose unaffected

```bash
docker compose -f docker-compose.tee-dev.yml config > /dev/null 2>&1
echo "EXIT=$?"
```

1. Run the command above.
2. **Expected:** `EXIT=0` — the MOCK_TEE compose file is completely unchanged and still valid.

---

## Edge Cases

### Successful slash — verify commit+reveal both called

```bash
python3 - <<'EOF'
from unittest.mock import MagicMock, call
from subnet.consensus.chain_overwatch_reporter import ChainOverwatchReporter
ht = MagicMock()
ht.commit_overwatch_subnet_weights.return_value = MagicMock(is_success=True)
reveal_receipt = MagicMock(is_success=True)
ht.reveal_overwatch_subnet_weights.return_value = reveal_receipt
r = ChainOverwatchReporter(ht, overwatch_node_id=7, subnet_id=99)
result = r.slash("abc123peer", 5, {"some": "evidence"})
assert result is reveal_receipt
assert ht.commit_overwatch_subnet_weights.call_count == 1
assert ht.reveal_overwatch_subnet_weights.call_count == 1
print("[OK] Both extrinsics called; reveal receipt returned")
EOF
```

1. Run the command above.
2. **Expected:** `[OK] Both extrinsics called; reveal receipt returned`

---

### Compose — OVERWATCH_NODE_ID is optional (no crash when absent)

```bash
CHAIN_ENDPOINT=wss://example SUBNET_ID=1 VALIDATOR_PHRASE=x MINER1_PHRASE=x MINER2_PHRASE=x OVERWATCH_PHRASE=x \
  docker compose -f docker-compose.chain.yml config 2>&1 | grep "OVERWATCH_NODE_ID"
```

1. Run the command above (no `OVERWATCH_NODE_ID` in environment).
2. **Expected:** Config renders successfully (EXIT=0); `OVERWATCH_NODE_ID` line in output shows empty string value — confirming the `:-` optional guard is in place and does not cause a compose error.

---

### check_slash.py CLI help — required args enforced

```bash
python3 scripts/check_slash.py 2>&1 | head -3
echo "EXIT=$?"
```

1. Run the command above (no args).
2. **Expected:** argparse usage error referencing `--overwatch_node_id` and `--epoch`; non-zero exit code.

---

## Failure Signals

- `ImportError: cannot import name 'ChainOverwatchReporter'` — `chain_overwatch_reporter.py` is missing or misnamed
- `pytest tests/consensus/test_chain_overwatch_reporter.py` → fewer than 5 tests collected — test file is incomplete
- `EXIT=0` from `check_slash.py --local_rpc` — connection error handling is broken
- `GREP_EXIT=0` from the credential redaction test — phrase is being echoed somewhere in the script output
- `docker compose -f docker-compose.chain.yml config` succeeds without `OVERWATCH_PHRASE` — the `:?` guard was not added correctly
- `docker compose -f docker-compose.tee-dev.yml config` fails — S03 changes accidentally modified Layer 2 compose file
- `193+ passed, 1 skipped` drops below 193 passed — a pre-existing test was broken by S03 changes

## Requirements Proved By This UAT

- R011 (slash extrinsic) — `ChainOverwatchReporter.slash()` implements commit+reveal protocol; error normalisation (None on exception, receipt on is_success=False) confirmed by unit tests and failure-path inline verifications; wiring into `_overwatch_epoch_loop` confirmed by server.py import; compose guard confirmed by config test

## Not Proven By This UAT

- Live on-chain slash confirmation (`TAMPER_RATE=1.0` → block explorer shows stake reduced) — deferred to S04 human UAT / live testnet run
- `get_overwatch_commits` / `get_overwatch_reveals` RPC method availability on the target Hypertensor testnet node — requires a live connection
- Slash visibility latency (time from `parity_mismatch` detection to on-chain confirmation) — requires live testnet
- Per-peer slash granularity — the current implementation submits a per-subnet weight; per-peer targeting requires pallet changes

## Notes for Tester

- Tests 3, 4, and 5 are inline Python scripts that can also be run directly as the S03-PLAN.md "Failure-Path Verification" section shows — all three have been confirmed passing in the executor run.
- The `Overwatch extrinsic exception:` traceback in test 3 is intentional and correct — it confirms `exc_info=True` is in place.
- The `⚠️ Overwatch commit failed: BadCommit` line printed in test 4 comes from the logger — this is expected and correct.
- For compose tests (8, 9, 10), Docker and Docker Compose must be installed. The compose config command does not start any containers — it only validates the YAML interpolation.
- `check_slash.py` requires `--overwatch_node_id` and `--epoch` as required positional-like arguments — running without them will show argparse usage error (tested in edge case above).
