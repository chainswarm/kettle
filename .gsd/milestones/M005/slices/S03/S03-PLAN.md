# S03: Overwatch Slash Extrinsic

**Goal:** `ChainOverwatchReporter` thin-wrapper that fires `commit_overwatch_subnet_weights` / `reveal_overwatch_subnet_weights` on `parity_mismatch` detection; wired into `_overwatch_epoch_loop`; `OVERWATCH_PHRASE` compose guard in place; `check_slash.py` diagnostic script available.
**Demo:** `pytest tests/consensus/test_chain_overwatch_reporter.py -v` → 5 passed; `pytest tests/ -x -q` → 193+ passed, 1 skipped; `check_slash.py --local_rpc` exits 1 with `ERROR: Cannot connect`; compose config fails fast on missing `OVERWATCH_PHRASE`.

## Must-Haves

- `ChainOverwatchReporter(hypertensor, overwatch_node_id, subnet_id)` with `slash(peer_id, epoch, evidence) → receipt | None` using `commit_overwatch_subnet_weights` + `reveal_overwatch_subnet_weights`; error-normalised (None on exception, receipt on `is_success=False`)
- 5 unit tests in `tests/consensus/test_chain_overwatch_reporter.py` mirroring `test_chain_submitter.py` structure
- `_overwatch_epoch_loop` calls `reporter.slash(peer_id, score_epoch, result.details)` when `result.reason == "parity_mismatch"`; reporter instantiated only when `OVERWATCH_NODE_ID` env var is set (MOCK_TEE mode unaffected)
- `scripts/check_slash.py` querying `get_overwatch_commits` / `get_overwatch_reveals` for a given epoch; same credential / URL / exit-code patterns as `check_scores.py`
- `OVERWATCH_PHRASE: ${OVERWATCH_PHRASE:?...}` `:?` guard added to validator service in `docker-compose.chain.yml`; header comment updated; Layer 2 compose unaffected

## Proof Level

- This slice proves: contract
- Real runtime required: no
- Human/UAT required: no

## Verification

```bash
# T01 — overwatch reporter unit tests
pytest tests/consensus/test_chain_overwatch_reporter.py -v
# → 5 passed

# T01 — Layer 1 still green
pytest tests/ -x -q
# → 193+ passed, 1 skipped

# T02 — check_slash.py exits 1 on no local node
python3 scripts/check_slash.py --local_rpc --overwatch_node_id 1 --epoch 0
# → ERROR: Cannot connect to ws://127.0.0.1:9944: [Errno 111] Connection refused
# → EXIT=1

# T02 — credential redaction
PHRASE="super secret mnemonic" python3 scripts/check_slash.py --overwatch_node_id 1 --epoch 0 2>&1 | grep -i "super secret"
# → GREP_EXIT=1

# T02 — compose guard fires on missing OVERWATCH_PHRASE
CHAIN_ENDPOINT=wss://example SUBNET_ID=1 VALIDATOR_PHRASE=x MINER1_PHRASE=x MINER2_PHRASE=x \
  docker compose -f docker-compose.chain.yml config 2>&1 | grep -i "OVERWATCH_PHRASE"
# → error ... required variable OVERWATCH_PHRASE is missing

# T02 — compose validates with all vars set
CHAIN_ENDPOINT=wss://example SUBNET_ID=1 VALIDATOR_PHRASE=x MINER1_PHRASE=x MINER2_PHRASE=x OVERWATCH_PHRASE=x \
  docker compose -f docker-compose.chain.yml config
# → EXIT=0

# T02 — Layer 2 unaffected
docker compose -f docker-compose.tee-dev.yml config
# → EXIT=0
```

## Observability / Diagnostics

- Runtime signals: `logger.warning("[Overwatch] TAMPER ...")` already fires on `parity_mismatch`; T01 adds `logger.info("[Overwatch] Submitting slash commit ...")` before commit extrinsic and `logger.error("⚠️ Overwatch commit/reveal failed: ...")` on `is_success=False`; `logger.error("Overwatch extrinsic exception: ...")` on unexpected exception
- Inspection surfaces: `python3 scripts/check_slash.py --chain $CHAIN_ENDPOINT --overwatch_node_id $OVERWATCH_NODE_ID --epoch $EPOCH` → `[OK] N commit(s)` / `[OK] N reveal(s)` / `[WARN] No commits found`; `docker compose -f docker-compose.chain.yml config` confirms credential guards
- Failure visibility: receipt `error_message` logged on `is_success=False`; exception logged with `exc_info=True`; `check_slash.py` `[WARN]` vs `[OK]` distinguishes missing-data from connection failure
- Redaction constraints: `OVERWATCH_PHRASE` never logged or echoed; `PHRASE` / `TENSOR_PRIVATE_KEY` in `check_slash.py` read from env only, never printed

### Failure-Path Verification

```bash
# Verify exception path: reporter returns None on chain error
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
# → [OK] Exception path: slash() returns None on chain error

# Verify failed-commit path: reveal is NOT called when commit fails
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
# → [OK] Failed-commit path: reveal not called; commit receipt returned (is_success=False)

# Verify MOCK_TEE guard: no reporter when OVERWATCH_NODE_ID unset
python3 - <<'EOF'
import os
os.environ.pop("OVERWATCH_NODE_ID", None)
s = os.environ.get("OVERWATCH_NODE_ID", "")
reporter = None if not s.isdigit() else "would_be_instantiated"
assert reporter is None, "Reporter should be None when OVERWATCH_NODE_ID unset"
print("[OK] MOCK_TEE guard: reporter=None when OVERWATCH_NODE_ID not set")
EOF
# → [OK] MOCK_TEE guard: reporter=None when OVERWATCH_NODE_ID not set
```

## Integration Closure

- Upstream surfaces consumed: `Hypertensor.commit_overwatch_subnet_weights(overwatch_node_id, commit_weights)` and `reveal_overwatch_subnet_weights(overwatch_node_id, reveals)` from `chain_functions.py`; `OverwatchCommit` / `OverwatchReveals` dataclasses from `chain_data.py`; `MockOverwatchVerifier.verify()` result (`result.reason == "parity_mismatch"`) from `mock.py`; `ChainScoreSubmitter` thin-wrapper pattern from S02
- New wiring introduced in this slice: `ChainOverwatchReporter` instantiated inside `_overwatch_epoch_loop` when `OVERWATCH_NODE_ID` env var is set; `reporter.slash()` called on `parity_mismatch` result
- What remains before the milestone is truly usable end-to-end: S04 docs (`CHAIN.md`), `smoke_test_chain.py`, wiring `ChainScoreSubmitter.submit()` into the validator epoch loop

## Tasks

- [x] **T01: Implement ChainOverwatchReporter and wire into overwatch epoch loop** `est:45m`
  - Why: Closes the gap between `parity_mismatch` detection (already logged in `_overwatch_epoch_loop`) and on-chain slash action (currently missing). The class is the S03 primary deliverable; tests define the contract S04 must honour.
  - Files: `subnet/consensus/chain_overwatch_reporter.py`, `tests/consensus/test_chain_overwatch_reporter.py`, `subnet/server/server.py`
  - Do: See T01-PLAN.md for full steps
  - Verify: `pytest tests/consensus/test_chain_overwatch_reporter.py -v` → 5 passed; `pytest tests/ -x -q` → 193+ passed, 1 skipped
  - Done when: 5 new tests pass; Layer 1 still green; `_overwatch_epoch_loop` calls `reporter.slash()` on `parity_mismatch` (verified by importing the loop and tracing the call)

- [x] **T02: Add check_slash.py diagnostic script and OVERWATCH_PHRASE compose guard** `est:30m`
  - Why: Closes the operational visibility gap — operators need a CLI to verify slash commits landed on-chain. The compose guard ensures `OVERWATCH_PHRASE` is never silently missing in the chain stack.
  - Files: `scripts/check_slash.py`, `docker-compose.chain.yml`
  - Do: See T02-PLAN.md for full steps
  - Verify: `check_slash.py --local_rpc` exits 1; compose fails without `OVERWATCH_PHRASE`; compose passes with it; Layer 2 unaffected
  - Done when: All 4 compose/script verification checks pass; `docker compose -f docker-compose.tee-dev.yml config` still exits 0

## Files Likely Touched

- `subnet/consensus/chain_overwatch_reporter.py` — new
- `tests/consensus/test_chain_overwatch_reporter.py` — new
- `subnet/server/server.py` — wire `ChainOverwatchReporter` into `_overwatch_epoch_loop`
- `scripts/check_slash.py` — new
- `docker-compose.chain.yml` — add `OVERWATCH_PHRASE` guard + header update
