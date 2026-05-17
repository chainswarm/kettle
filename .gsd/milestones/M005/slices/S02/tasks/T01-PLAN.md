---
estimated_steps: 7
estimated_files: 2
---

# T01: Implement ChainScoreSubmitter class and unit tests

**Slice:** S02 — Score Submission Extrinsic
**Milestone:** M005

## Description

Create `subnet/consensus/chain_submitter.py` with a `ChainScoreSubmitter` class that wraps `Hypertensor.propose_attestation()`. This is the boundary contract S03 will consume for slash reporting context — a thin, testable layer with a stable interface. Write 5 unit tests in `tests/consensus/test_chain_submitter.py` using `MagicMock` to verify correct call params, receipt handling, empty-list pass-through, and exception recovery — no live chain required.

**Key constraints from research:**
- `propose_attestation` composes the call *outside* the retry block — the call object is created once, nonce is fetched inside the retry. `ChainScoreSubmitter` must NOT re-compose between retries. Do not duplicate the retry logic — just call `hypertensor.propose_attestation()` and let it handle its own retry.
- Empty score list (`submit([])`) must NOT short-circuit or raise — the chain accepts an empty `data=[]` and the existing `Consensus.run_consensus()` handles this case.
- Score format is `List[SubnetNodeConsensusData]` with pre-computed `int(1e18 * tee_score)` values. `ChainScoreSubmitter` receives already-encoded scores; it does NOT encode floats.
- `asdict(s)` on `SubnetNodeConsensusData` produces `{"subnet_node_id": N, "score": M}` — this is the exact format `propose_attestation(data=...)` expects.

## Steps

1. **Read** `subnet/hypertensor/chain_data.py` around line 1187 to confirm `SubnetNodeConsensusData` fields (`subnet_node_id: int`, `score: int`) and the `asdict()` output.

2. **Create `subnet/consensus/chain_submitter.py`:**
   ```python
   from dataclasses import asdict
   from typing import List, Optional
   import logging

   from subnet.hypertensor.chain_data import SubnetNodeConsensusData

   logger = logging.getLogger(__name__)

   class ChainScoreSubmitter:
       def __init__(self, hypertensor, subnet_id: int):
           self.hypertensor = hypertensor
           self.subnet_id = subnet_id

       def submit(self, scores: List[SubnetNodeConsensusData]):
           """
           Sign and broadcast a propose_attestation extrinsic with the given scores.

           :param scores: List of SubnetNodeConsensusData with pre-computed integer scores.
                          Empty list is valid — passes through to chain unchanged.
           :returns: ExtrinsicReceipt on success, None on failure or exception.
           """
           data = [asdict(s) for s in scores]
           try:
               receipt = self.hypertensor.propose_attestation(self.subnet_id, data=data)
               if receipt is not None and not receipt.is_success:
                   logger.error(f"⚠️ Score submission failed: {receipt.error_message}")
               return receipt
           except Exception as exc:
               logger.error(f"Score submission exception: {exc}", exc_info=True)
               return None
   ```

3. **Create `tests/consensus/test_chain_submitter.py`** with 5 tests using `unittest.mock.MagicMock`:
   - `test_submit_calls_propose_attestation_with_correct_params` — verifies `propose_attestation` is called with `subnet_id` and `data=[{"subnet_node_id": N, "score": M}]`
   - `test_submit_returns_receipt_on_success` — mock receipt where `is_success=True`; verify return value is the receipt
   - `test_submit_empty_list_calls_through` — `submit([])` calls `propose_attestation` with `data=[]` (no short-circuit)
   - `test_submit_logs_error_on_failed_receipt` — mock receipt where `is_success=False`, `error_message="BadProof"`; verify return is the receipt (not None) and error is logged
   - `test_submit_exception_returns_none` — `propose_attestation` raises `Exception("network down")`; verify `submit()` returns `None` and does not re-raise

4. **Verify tests pass** before declaring done.

## Must-Haves

- [ ] `ChainScoreSubmitter.__init__(hypertensor, subnet_id)` stores both attrs
- [ ] `submit(scores)` calls `hypertensor.propose_attestation(self.subnet_id, data=[asdict(s) for s in scores])`
- [ ] `submit([])` calls `propose_attestation` with `data=[]` — no early return, no raise
- [ ] On `receipt.is_success == False`: logs error with `receipt.error_message`, returns receipt (not None)
- [ ] On exception from `propose_attestation`: catches, logs, returns None (does not re-raise)
- [ ] All 5 unit tests pass with `MagicMock` — no live chain needed
- [ ] `pytest tests/ -x -q` still passes (183+ tests, 0 failed)

## Verification

```bash
# Unit tests
pytest tests/consensus/test_chain_submitter.py -v
# → 5 passed

# Full layer 1
pytest tests/ -x -q
# → 183+ passed, 0 failed

# Quick import sanity (no chain needed)
python3 -c "from subnet.consensus.chain_submitter import ChainScoreSubmitter; print('OK')"
# → OK
```

## Observability Impact

- Signals added/changed: `logger.error("⚠️ Score submission failed: ...")` on `is_success=False`; `logger.error("Score submission exception: ...")` on unexpected exceptions — both appear in structured JSON logs when `LOG_JSON=true`
- How a future agent inspects this: search container logs for `"Score submission"` to identify submission failures; `check_scores.py` (T02) queries chain state to confirm success
- Failure state exposed: returns `None` on exception, receipt on failure — caller (Consensus loop) can distinguish soft failure from hard failure

## Inputs

- `subnet/hypertensor/chain_functions.py` — `Hypertensor.propose_attestation(subnet_id, data, ...)` signature at ~line 173; `data` is a list of dicts
- `subnet/hypertensor/chain_data.py` — `SubnetNodeConsensusData(subnet_node_id: int, score: int)` at ~line 1187; `asdict()` produces `{"subnet_node_id": N, "score": M}`
- `subnet/consensus/consensus.py` — shows existing `propose_attestation` call pattern; `ChainScoreSubmitter` is a wrapper around this, not a replacement
- Research constraint: the call is composed outside the retry loop — do not re-compose in `ChainScoreSubmitter`; just call `hypertensor.propose_attestation()` directly

## Expected Output

- `subnet/consensus/chain_submitter.py` — new module; `ChainScoreSubmitter` class with `submit()` method; ~50 lines
- `tests/consensus/test_chain_submitter.py` — new test file; 5 tests using `MagicMock`; all pass; ~80 lines
