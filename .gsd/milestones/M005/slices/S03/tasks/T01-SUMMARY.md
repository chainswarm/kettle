---
id: T01
parent: S03
milestone: M005
provides:
  - ChainOverwatchReporter class with commit+reveal slash logic
  - 5 unit tests covering all error paths
  - _overwatch_epoch_loop wired to call reporter.slash() on parity_mismatch
key_files:
  - subnet/consensus/chain_overwatch_reporter.py
  - tests/consensus/test_chain_overwatch_reporter.py
  - subnet/server/server.py
key_decisions:
  - reporter instantiated from OVERWATCH_NODE_ID env var before the while-loop so it is created once per overwatch lifetime, not per iteration
  - reporter=None guard means MOCK_TEE mode (no OVERWATCH_NODE_ID) is completely unaffected
patterns_established:
  - ChainOverwatchReporter mirrors ChainScoreSubmitter thin-wrapper pattern: constructor(hypertensor, id, subnet_id), method returns receipt|None, exception caught+logged with exc_info=True
observability_surfaces:
  - logger.info("[Overwatch] Submitting slash commit peer=... epoch=... subnet_id=...")
  - logger.error("⚠️ Overwatch commit failed: {error_message}") on is_success=False commit
  - logger.error("⚠️ Overwatch reveal failed: {error_message}") on is_success=False reveal
  - logger.error("Overwatch extrinsic exception: ...", exc_info=True) on unexpected exception
duration: 15m
verification_result: passed
completed_at: 2026-03-17
blocker_discovered: false
---

# T01: Implement ChainOverwatchReporter and wire into overwatch epoch loop

**Added ChainOverwatchReporter (commit+reveal slash wrapper) and wired it into _overwatch_epoch_loop behind OVERWATCH_NODE_ID guard; 5 unit tests pass; 193 passed, 1 skipped full suite.**

## What Happened

Created `subnet/consensus/chain_overwatch_reporter.py` — a thin wrapper mirroring `ChainScoreSubmitter` exactly. The constructor takes `(hypertensor, overwatch_node_id, subnet_id)`. `slash(peer_id, epoch, evidence)` generates a fresh 32-byte salt, computes `sha256(weight_bytes + salt)` as the commit hash, submits `commit_overwatch_subnet_weights`, then `reveal_overwatch_subnet_weights`. Returns the reveal receipt on success, the commit receipt early if commit fails, and `None` on any exception (with `exc_info=True` logging).

Wired into `_overwatch_epoch_loop` in `server.py`:
- Added module-level import `from subnet.consensus.chain_overwatch_reporter import ChainOverwatchReporter`
- Reporter instantiated once before the `while` loop using `OVERWATCH_NODE_ID` env var; `reporter=None` when env var is absent
- `reporter.slash(peer_id, score_epoch, result.details)` called in the `parity_mismatch` else branch after the existing `loop_logger.warning("[Overwatch] TAMPER ...")` call

Also applied the S03-PLAN.md pre-flight fix: added a `### Failure-Path Verification` block with three inspectable commands covering exception path, failed-commit path, and MOCK_TEE guard.

## Verification

```
pytest tests/consensus/test_chain_overwatch_reporter.py -v
# → 5 passed

pytest tests/ -x -q
# → 193 passed, 1 skipped

python3 -c "from subnet.consensus.chain_overwatch_reporter import ChainOverwatchReporter; print('OK')"
# → OK

# Slash wiring
python3 - <<'EOF'
from unittest.mock import MagicMock; import os; os.environ["OVERWATCH_NODE_ID"] = "1"
from subnet.consensus.chain_overwatch_reporter import ChainOverwatchReporter
r = ChainOverwatchReporter(MagicMock(), 1, 42)
r.hypertensor.commit_overwatch_subnet_weights.return_value = MagicMock(is_success=True)
r.hypertensor.reveal_overwatch_subnet_weights.return_value = MagicMock(is_success=True)
assert r.slash("test_peer", 5, None) is not None; print("PASS")
EOF
# → PASS

# Exception path → None
# Failed-commit path → reveal not called, commit receipt returned
# MOCK_TEE guard → reporter=None when OVERWATCH_NODE_ID unset
# All three confirmed
```

## Diagnostics

- Grep `docker compose logs validator` for `[Overwatch] Submitting slash commit` to confirm reporter fired on a `parity_mismatch`
- `[Overwatch] TAMPER` (pre-existing log) confirms detection; next line is the slash attempt
- `⚠️ Overwatch commit/reveal failed:` with receipt.error_message exposes chain-level failures
- `Overwatch extrinsic exception:` with full traceback exposes network-level failures
- `reporter is None` in logs (absent) confirms MOCK_TEE mode is running without chain calls

## Deviations

None. Implementation followed the plan exactly.

## Known Issues

None.

## Files Created/Modified

- `subnet/consensus/chain_overwatch_reporter.py` — new; ChainOverwatchReporter class (~70 lines)
- `tests/consensus/test_chain_overwatch_reporter.py` — new; 5 unit tests covering all required paths
- `subnet/server/server.py` — module-level import added; reporter instantiation (7 lines) before while-loop; reporter.slash() call (2 lines) in parity_mismatch branch
- `.gsd/milestones/M005/slices/S03/S03-PLAN.md` — pre-flight fix: added Failure-Path Verification block to Observability/Diagnostics section
