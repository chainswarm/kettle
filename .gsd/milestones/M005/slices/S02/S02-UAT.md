---
id: S02
parent: M005
milestone: M005
uat_mode: artifact-driven
---

# S02: Score Submission Extrinsic — UAT

**Milestone:** M005
**Written:** 2026-03-17

## UAT Type

- UAT mode: artifact-driven
- Why this mode is sufficient: S02 delivers a contract-level unit-tested wrapper and a diagnostic script. Live-chain proof (scores visible post-epoch) is the M005 integration milestone gate, not a per-slice gate. All paths under test can be exercised without a running testnet node.

## Preconditions

1. Working directory is the repo root (this worktree).
2. Python 3 and the `subnet` package are importable: `python3 -c "from subnet.consensus.chain_submitter import ChainScoreSubmitter"` exits 0.
3. Docker Compose is installed and `docker compose -f docker-compose.chain.yml` resolves.
4. `docker compose -f docker-compose.tee-dev.yml` resolves (Layer 2 baseline).
5. No local Substrate node running on `ws://127.0.0.1:9944` (tests rely on connection failure).

## Smoke Test

```bash
pytest tests/consensus/test_chain_submitter.py -v
# → 5 passed in <1s
```

If this passes, the core extrinsic contract is intact.

---

## Test Cases

### 1. All ChainScoreSubmitter unit tests pass

```bash
pytest tests/consensus/test_chain_submitter.py -v
```

**Expected:**
```
PASSED test_submit_calls_propose_attestation_with_correct_params
PASSED test_submit_returns_receipt_on_success
PASSED test_submit_empty_list_calls_through
PASSED test_submit_logs_error_on_failed_receipt
PASSED test_submit_exception_returns_none
5 passed
```

---

### 2. Exception path returns None (never re-raises)

```bash
python3 -c "
import unittest.mock as m
from subnet.consensus.chain_submitter import ChainScoreSubmitter
ht = m.MagicMock()
ht.propose_attestation.side_effect = Exception('network down')
cs = ChainScoreSubmitter(ht, subnet_id=1)
result = cs.submit([])
assert result is None, f'Expected None, got {result!r}'
print('PASS')
"
```

**Expected:** `PASS` (no exception propagates)

---

### 3. Failed receipt (is_success=False) is returned, not swallowed

```bash
python3 -c "
import unittest.mock as m
from subnet.consensus.chain_submitter import ChainScoreSubmitter
ht = m.MagicMock()
receipt = m.MagicMock(is_success=False, error_message='BadProof')
ht.propose_attestation.return_value = receipt
cs = ChainScoreSubmitter(ht, subnet_id=1)
result = cs.submit([])
assert result is receipt, f'Expected receipt, got {result!r}'
print('PASS')
"
```

**Expected:** `PASS` (receipt is returned so callers can inspect `error_message`)

---

### 4. Empty score list passes through without raising

```bash
python3 -c "
import unittest.mock as m
from subnet.consensus.chain_submitter import ChainScoreSubmitter
ht = m.MagicMock()
ht.propose_attestation.return_value = m.MagicMock(is_success=True)
cs = ChainScoreSubmitter(ht, subnet_id=42)
result = cs.submit([])
call_args = ht.propose_attestation.call_args
assert call_args[0][0] == 42, 'subnet_id must be 42'
assert call_args[1]['data'] == [], 'data must be empty list, not short-circuited'
print('PASS: propose_attestation called with subnet_id=42 data=[]')
"
```

**Expected:** `PASS: propose_attestation called with subnet_id=42 data=[]`

---

### 5. check_scores.py — connection failure exits 1 with ERROR on stderr

```bash
python3 scripts/check_scores.py --local_rpc --subnet_id 1 --epoch 0 2>&1; echo EXIT=$?
```

**Expected:**
```
ERROR: Cannot connect to ws://127.0.0.1:9944: [Errno 111] Connection refused
EXIT=1
```

---

### 6. check_scores.py — credential redaction (PHRASE never echoed)

```bash
PHRASE="super secret mnemonic" python3 scripts/check_scores.py --local_rpc --subnet_id 1 --epoch 0 2>&1 | grep -i "super secret"; echo GREP_EXIT=$?
```

**Expected:**
```
GREP_EXIT=1
```

(No match — the phrase never appears in stdout or stderr.)

---

### 7. docker-compose.chain.yml — VALIDATOR_PHRASE guard fires when missing

```bash
CHAIN_ENDPOINT=wss://rpc.hypertensor.app:443 SUBNET_ID=1 \
  docker compose -f docker-compose.chain.yml config 2>&1 | grep -i "VALIDATOR_PHRASE"
```

**Expected:** Output contains a line like:
```
error while interpolating services.validator.environment.PHRASE: required variable VALIDATOR_PHRASE is missing ...
```

---

### 8. docker-compose.chain.yml — validates cleanly with all credential vars set

```bash
CHAIN_ENDPOINT=wss://rpc.hypertensor.app:443 SUBNET_ID=1 \
  VALIDATOR_PHRASE="word word word" MINER1_PHRASE="word word word" MINER2_PHRASE="word word word" \
  docker compose -f docker-compose.chain.yml config > /dev/null 2>&1; echo EXIT=$?
```

**Expected:** `EXIT=0`

---

### 9. Layer 1 regression — full test suite still green

```bash
pytest tests/ -x -q
```

**Expected:** `188 passed, 1 skipped` (or higher if additional tests have been added)

---

### 10. Layer 2 regression — docker-compose.tee-dev.yml unaffected

```bash
docker compose -f docker-compose.tee-dev.yml config > /dev/null 2>&1; echo EXIT=$?
```

**Expected:** `EXIT=0`

---

## Edge Cases

### MINER1_PHRASE guard fires when only VALIDATOR_PHRASE is set

```bash
CHAIN_ENDPOINT=wss://rpc.hypertensor.app:443 SUBNET_ID=1 \
  VALIDATOR_PHRASE="word word word" \
  docker compose -f docker-compose.chain.yml config 2>&1 | grep -i "MINER1_PHRASE"
```

**Expected:** Error message referencing `MINER1_PHRASE is missing` — each signing node has its own independent guard.

---

### MINER2_PHRASE guard fires when only VALIDATOR_PHRASE + MINER1_PHRASE set

```bash
CHAIN_ENDPOINT=wss://rpc.hypertensor.app:443 SUBNET_ID=1 \
  VALIDATOR_PHRASE="word word word" MINER1_PHRASE="word word word" \
  docker compose -f docker-compose.chain.yml config 2>&1 | grep -i "MINER2_PHRASE"
```

**Expected:** Error message referencing `MINER2_PHRASE is missing`.

---

### check_scores.py URL precedence: --local_rpc overrides --chain

```bash
python3 scripts/check_scores.py --local_rpc --chain wss://rpc.hypertensor.app:443 --subnet_id 1 --epoch 0 2>&1 | head -1
```

**Expected:** `ERROR: Cannot connect to ws://127.0.0.1:9944: ...` (local URL used, not the --chain URL)

---

### check_scores.py with $DEV_RPC set but no --chain or --local_rpc

```bash
DEV_RPC=ws://127.0.0.1:9944 python3 scripts/check_scores.py --subnet_id 1 --epoch 0 2>&1; echo EXIT=$?
```

**Expected:** `ERROR: Cannot connect to ws://127.0.0.1:9944: ...` and `EXIT=1` — `$DEV_RPC` is picked up as fallback.

---

### check_scores.py import error surfaces cleanly

```bash
PYTHONPATH=/nonexistent python3 scripts/check_scores.py --subnet_id 1 --epoch 0 2>&1 | head -1
```

**Expected:** `ERROR: Cannot import Hypertensor — is the subnet package installed? ...` (not a raw traceback)

---

## Failure Signals

- `ImportError` or raw traceback on `check_scores.py` startup → package not installed or PYTHONPATH wrong
- `propose_attestation` call args do not include `data=` keyword → `ChainScoreSubmitter` serialisation changed
- `5 passed` in unit tests drops to fewer → regression in `chain_submitter.py`
- `GREP_EXIT=0` on credential redaction check → PHRASE or mnemonic leaked to stdout/stderr
- `EXIT=0` on `check_scores.py --local_rpc` without a running node → error handling broken
- `EXIT=0` on compose config without `VALIDATOR_PHRASE` → `:?` guard removed or anchor override broken

## Requirements Proved By This UAT

- R010 (score extrinsic) — `ChainScoreSubmitter` contract is fully exercised: correct call args, correct return values on all paths (success, failure, exception, empty-list)
- R022 (test coverage) — 188 tests passing; new `tests/consensus/` package established

## Not Proven By This UAT

- **Live chain score submission**: `[OK] Scores found for epoch N: N entries` from `check_scores.py` requires a running testnet node with a registered subnet and at least one completed epoch after `ChainScoreSubmitter.submit()` is wired into the validator loop. This is the M005 integration milestone proof.
- **Validator epoch loop wiring**: `ChainScoreSubmitter` exists and is tested but is not yet called inside `consensus.py`. The wiring step is deferred to the integration phase (after S03 and S04).
- **Per-node distinct key isolation**: compose vars are per-service, but runtime isolation (different validators cannot sign as each other) is only proven on a live testnet.

## Notes for Tester

- The `[WARN] No scores found for epoch N` exit-0 path from `check_scores.py` is correct and intentional — it means the epoch has not yet finalised or the validator has not yet submitted. It is **not** a failure signal.
- The compose bootnode service intentionally has no `PHRASE` guard — it does not sign extrinsics.
- All 5 unit tests run in under 100ms with no network or chain required.
- If running on a machine where `ws://127.0.0.1:9944` happens to be occupied by a real substrate node, Test Cases 5 and 9 will behave differently (connection succeeds). Ensure no local node is running before executing the connection-failure tests.
