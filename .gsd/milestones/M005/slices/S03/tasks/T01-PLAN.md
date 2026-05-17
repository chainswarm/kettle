---
estimated_steps: 8
estimated_files: 3
---

# T01: Implement ChainOverwatchReporter and wire into overwatch epoch loop

**Slice:** S03 — Overwatch Slash Extrinsic
**Milestone:** M005

## Description

Create `ChainOverwatchReporter`, a thin wrapper around `commit_overwatch_subnet_weights` / `reveal_overwatch_subnet_weights` that fires when `_overwatch_epoch_loop` detects `parity_mismatch`. The class mirrors `ChainScoreSubmitter` exactly: constructor takes `(hypertensor, overwatch_node_id, subnet_id)`, method `slash(peer_id, epoch, evidence)` performs commit+reveal, returns `receipt | None`. Error normalisation follows the same pattern: None on exception, receipt (even `is_success=False`) otherwise.

The "slash" is a commit-reveal weight signal: low weight (0) for tampered peer's subnet, high weight (`int(1e18)`) for clean. There is no `slash_node` extrinsic — the term in the roadmap refers to the weight penalty that reduces token emissions.

Wire the reporter into `_overwatch_epoch_loop` in `server.py` — guarded behind `OVERWATCH_NODE_ID` env var so `MOCK_TEE=true` mode is completely unaffected.

## Steps

1. **Create `subnet/consensus/chain_overwatch_reporter.py`**

   ```python
   import hashlib
   import logging
   import os
   from dataclasses import asdict

   from subnet.hypertensor.chain_data import OverwatchCommit, OverwatchReveals

   logger = logging.getLogger(__name__)

   # Weight constants: punish = 0, reward = int(1e18)
   _PUNISH_WEIGHT = 0
   _REWARD_WEIGHT = int(1e18)


   class ChainOverwatchReporter:
       """
       Thin wrapper around commit_overwatch_subnet_weights / reveal_overwatch_subnet_weights.

       Mirrors ChainScoreSubmitter: constructor takes (hypertensor, overwatch_node_id, subnet_id);
       slash() returns receipt | None; no retry duplication (Hypertensor owns retry/nonce).
       """
       def __init__(self, hypertensor, overwatch_node_id: int, subnet_id: int):
           self.hypertensor = hypertensor
           self.overwatch_node_id = overwatch_node_id
           self.subnet_id = subnet_id

       def slash(self, peer_id: str, epoch: int, evidence=None) -> object:
           """
           Submit commit + reveal overwatch weight for this subnet.

           A 'parity_mismatch' maps to weight=0 (punish). The peer_id and epoch
           are used only for logging — the chain weight is per-subnet, not per-peer.

           :returns: ExtrinsicReceipt from reveal (or commit if reveal fails), None on exception.
           """
           salt = os.urandom(32)
           weight_int = _PUNISH_WEIGHT  # tamper → punish

           # Commit: hash(weight_int_bytes + salt)
           weight_bytes = weight_int.to_bytes(16, byteorder="big")
           commit_hash = hashlib.sha256(weight_bytes + salt).digest()

           commit_weights = [asdict(OverwatchCommit(subnet_id=self.subnet_id, weight=commit_hash))]
           reveals = [asdict(OverwatchReveals(subnet_id=self.subnet_id, weight=weight_int, salt=salt))]

           logger.info(
               "[Overwatch] Submitting slash commit peer=%s epoch=%d subnet_id=%d",
               peer_id[:16] if peer_id else "?", epoch, self.subnet_id,
           )
           try:
               commit_receipt = self.hypertensor.commit_overwatch_subnet_weights(
                   self.overwatch_node_id, commit_weights
               )
               if commit_receipt is not None and not commit_receipt.is_success:
                   logger.error(
                       "⚠️ Overwatch commit failed: %s", commit_receipt.error_message
                   )
                   return commit_receipt

               reveal_receipt = self.hypertensor.reveal_overwatch_subnet_weights(
                   self.overwatch_node_id, reveals
               )
               if reveal_receipt is not None and not reveal_receipt.is_success:
                   logger.error(
                       "⚠️ Overwatch reveal failed: %s", reveal_receipt.error_message
                   )
               return reveal_receipt
           except Exception as exc:
               logger.error("Overwatch extrinsic exception: %s", exc, exc_info=True)
               return None
   ```

   Key constraints:
   - `asdict(OverwatchCommit(...))` and `asdict(OverwatchReveals(...))` handle serialisation — same pattern as `asdict(s)` in `ChainScoreSubmitter`
   - No retry logic — `commit_overwatch_subnet_weights` / `reveal_overwatch_subnet_weights` both have `@retry` internally
   - `peer_id` / `epoch` are for logging only; evidence maps to weight direction (always punish=0 here since slash is only called on `parity_mismatch`)
   - `salt` is `os.urandom(32)` — fresh per call, not persisted

2. **Create `tests/consensus/test_chain_overwatch_reporter.py`** with 5 MagicMock tests

   Mirror `test_chain_submitter.py` structure exactly:

   ```python
   """Unit tests for ChainOverwatchReporter."""
   import logging
   from unittest.mock import MagicMock, patch
   import pytest
   from subnet.consensus.chain_overwatch_reporter import ChainOverwatchReporter


   def make_reporter(overwatch_node_id=1, subnet_id=42):
       hypertensor = MagicMock()
       return ChainOverwatchReporter(hypertensor, overwatch_node_id, subnet_id), hypertensor


   class TestChainOverwatchReporter:
       def test_slash_calls_commit_and_reveal(self):
           """commit_overwatch_subnet_weights and reveal_overwatch_subnet_weights are both called."""
           reporter, ht = make_reporter(overwatch_node_id=1, subnet_id=42)
           ht.commit_overwatch_subnet_weights.return_value = MagicMock(is_success=True)
           ht.reveal_overwatch_subnet_weights.return_value = MagicMock(is_success=True)

           reporter.slash("peer123", epoch=5, evidence=None)

           ht.commit_overwatch_subnet_weights.assert_called_once()
           ht.reveal_overwatch_subnet_weights.assert_called_once()

       def test_slash_returns_reveal_receipt_on_success(self):
           """slash() returns the reveal ExtrinsicReceipt when both calls succeed."""
           reporter, ht = make_reporter()
           commit_receipt = MagicMock(is_success=True)
           reveal_receipt = MagicMock(is_success=True)
           ht.commit_overwatch_subnet_weights.return_value = commit_receipt
           ht.reveal_overwatch_subnet_weights.return_value = reveal_receipt

           result = reporter.slash("peer_abc", epoch=3, evidence=None)

           assert result is reveal_receipt

       def test_slash_returns_commit_receipt_when_commit_fails(self):
           """Failed commit (is_success=False) is returned early — reveal is not called."""
           reporter, ht = make_reporter()
           commit_receipt = MagicMock(is_success=False, error_message="BadCommit")
           ht.commit_overwatch_subnet_weights.return_value = commit_receipt

           result = reporter.slash("peer_xyz", epoch=1, evidence=None)

           assert result is commit_receipt
           ht.reveal_overwatch_subnet_weights.assert_not_called()

       def test_slash_logs_error_on_failed_reveal(self, caplog):
           """Failed reveal receipt is returned and error is logged."""
           reporter, ht = make_reporter()
           ht.commit_overwatch_subnet_weights.return_value = MagicMock(is_success=True)
           reveal_receipt = MagicMock(is_success=False, error_message="BadReveal")
           ht.reveal_overwatch_subnet_weights.return_value = reveal_receipt

           with caplog.at_level(logging.ERROR, logger="subnet.consensus.chain_overwatch_reporter"):
               result = reporter.slash("peer_def", epoch=2, evidence=None)

           assert result is reveal_receipt
           assert any("BadReveal" in record.message for record in caplog.records)

       def test_slash_exception_returns_none(self):
           """Exception from commit is caught; slash() returns None."""
           reporter, ht = make_reporter()
           ht.commit_overwatch_subnet_weights.side_effect = Exception("network down")

           result = reporter.slash("peer_ghi", epoch=0, evidence=None)

           assert result is None
   ```

3. **Run tests to verify they pass:**
   ```bash
   pytest tests/consensus/test_chain_overwatch_reporter.py -v
   ```

4. **Wire `ChainOverwatchReporter` into `_overwatch_epoch_loop` in `subnet/server/server.py`**

   In `_overwatch_epoch_loop`, add an import at the top of the function body (or at module level alongside existing imports) and instantiate once per loop entry using `OVERWATCH_NODE_ID` env var:

   At the top of `server.py` imports, add:
   ```python
   from subnet.consensus.chain_overwatch_reporter import ChainOverwatchReporter
   ```

   Inside `_overwatch_epoch_loop`, after the `while not termination_event.is_set():` block setup — instantiate the reporter once before the loop (outside the while):

   ```python
   # --- overwatch reporter setup (guarded) ---
   import os as _os
   _overwatch_node_id_str = _os.environ.get("OVERWATCH_NODE_ID", "")
   reporter = (
       ChainOverwatchReporter(hypertensor, int(_overwatch_node_id_str), subnet_id)
       if _overwatch_node_id_str.isdigit()
       else None
   )
   ```

   Then, inside the tamper-detection branch where the `else:` currently just logs `[Overwatch] TAMPER`, add after the existing `loop_logger.warning(...)` call:
   ```python
   if result.reason == "parity_mismatch" and reporter is not None:
       reporter.slash(peer_id, score_epoch, result.details)
   ```

   The `reporter is None` guard means: if `OVERWATCH_NODE_ID` is not set (standard `MOCK_TEE=true` mode), the reporter is never instantiated and no extrinsic is ever attempted. This preserves existing `MOCK_TEE` behaviour completely.

5. **Verify Layer 1 still green:**
   ```bash
   pytest tests/ -x -q
   ```

## Must-Haves

- [ ] `ChainOverwatchReporter(hypertensor, overwatch_node_id, subnet_id)` created in `subnet/consensus/chain_overwatch_reporter.py`
- [ ] `slash(peer_id, epoch, evidence)` calls commit then reveal; returns reveal receipt on success; returns commit receipt early if commit fails; returns None on exception
- [ ] Error normalisation matches `ChainScoreSubmitter`: `is_success=False` receipt is returned (not None) + error is logged; exception is caught, logged with `exc_info=True`, returns None
- [ ] 5 unit tests covering: commit+reveal both called, success returns reveal receipt, failed commit returns early (reveal not called), failed reveal logged + returned, exception returns None
- [ ] `_overwatch_epoch_loop` wired: reporter instantiated from `OVERWATCH_NODE_ID` env var; `reporter.slash()` called on `parity_mismatch`; `reporter is None` guard preserves MOCK_TEE mode
- [ ] `pytest tests/consensus/test_chain_overwatch_reporter.py -v` → 5 passed
- [ ] `pytest tests/ -x -q` → 193+ passed, 1 skipped

## Verification

```bash
# 5 new unit tests
pytest tests/consensus/test_chain_overwatch_reporter.py -v
# → 5 passed

# Full suite still green
pytest tests/ -x -q
# → 193+ passed, 1 skipped

# Import check — no circular imports
python3 -c "from subnet.consensus.chain_overwatch_reporter import ChainOverwatchReporter; print('OK')"
# → OK

# Wiring check — slash is called on parity_mismatch
python3 - <<'EOF'
from unittest.mock import MagicMock, patch
import os
os.environ["OVERWATCH_NODE_ID"] = "1"
# The import path is checked by the import; actual loop testing is via unit tests
from subnet.consensus.chain_overwatch_reporter import ChainOverwatchReporter
r = ChainOverwatchReporter(MagicMock(), 1, 42)
r.hypertensor.commit_overwatch_subnet_weights.return_value = MagicMock(is_success=True)
r.hypertensor.reveal_overwatch_subnet_weights.return_value = MagicMock(is_success=True)
receipt = r.slash("test_peer", 5, None)
assert receipt is not None
print("PASS: slash wiring works")
EOF
```

## Observability Impact

- Signals added/changed: `logger.info("[Overwatch] Submitting slash commit ...")` before commit; `logger.error("⚠️ Overwatch commit failed: ...")` on failed commit; `logger.error("⚠️ Overwatch reveal failed: ...")` on failed reveal; `logger.error("Overwatch extrinsic exception: ...", exc_info=True)` on exception
- How a future agent inspects this: grep `docker compose logs validator` for `[Overwatch] Submitting slash commit` to confirm the reporter fired; check `[Overwatch] TAMPER` (existing log) confirms detection; `check_slash.py` (T02) confirms on-chain receipt
- Failure state exposed: `receipt.error_message` surfaced via `logger.error`; exception traceback via `exc_info=True`

## Inputs

- `subnet/consensus/chain_submitter.py` — the exact thin-wrapper pattern to follow; copy constructor shape, error normalisation, and test structure verbatim
- `tests/consensus/test_chain_submitter.py` — the exact 5-test structure to mirror
- `subnet/hypertensor/chain_data.py` — `OverwatchCommit(subnet_id, weight: bytes)` and `OverwatchReveals(subnet_id, weight: int, salt: bytes)` dataclass definitions
- `subnet/hypertensor/chain_functions.py` — `commit_overwatch_subnet_weights(overwatch_node_id, commit_weights)` and `reveal_overwatch_subnet_weights(overwatch_node_id, reveals)` signatures; both already have `@retry` internally, so no retry duplication
- `subnet/server/server.py` lines 618–695 — `_overwatch_epoch_loop` full body; the `else:` branch at line ~670 currently only logs `[Overwatch] TAMPER`; add `reporter.slash()` call after the existing `loop_logger.warning(...)` line

## Expected Output

- `subnet/consensus/chain_overwatch_reporter.py` — new; `ChainOverwatchReporter` class (~55 lines); thin wrapper around commit+reveal extrinsics
- `tests/consensus/test_chain_overwatch_reporter.py` — new; 5 unit tests (~90 lines) covering all required paths
- `subnet/server/server.py` — modified; top-level import added; reporter instantiation (2 lines) + slash call (2 lines) added inside `_overwatch_epoch_loop`
