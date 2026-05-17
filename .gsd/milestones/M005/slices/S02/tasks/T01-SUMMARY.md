---
id: T01
parent: S02
milestone: M005
provides:
  - ChainScoreSubmitter class wrapping propose_attestation with correct data serialisation
  - 5 unit tests covering success, failure receipt, empty-list pass-through, and exception recovery
key_files:
  - subnet/consensus/chain_submitter.py
  - tests/consensus/test_chain_submitter.py
key_decisions:
  - ChainScoreSubmitter does NOT re-compose the call between retries — calls hypertensor.propose_attestation() directly; retry logic lives inside Hypertensor
  - Empty score list is not short-circuited; passes data=[] to propose_attestation as the chain allows it
  - asdict(s) on SubnetNodeConsensusData produces {"subnet_node_id": N, "score": M} — no additional encoding in the submitter
patterns_established:
  - thin-wrapper pattern: ChainScoreSubmitter owns only serialisation (asdict) + error normalisation (None on exception, receipt on is_success=False); all retry/nonce logic stays in Hypertensor
observability_surfaces:
  - logger.error("⚠️ Score submission failed: <error_message>") on receipt.is_success=False
  - logger.error("Score submission exception: <exc>", exc_info=True) on unexpected exception from propose_attestation
  - Both surface in structured JSON logs when LOG_JSON=true; search for "Score submission" to triage failures
duration: ~10m
verification_result: passed
completed_at: 2026-03-17
blocker_discovered: false
---

# T01: Implement ChainScoreSubmitter class and unit tests

**Created `ChainScoreSubmitter` wrapping `propose_attestation` with `asdict` serialisation and 5 passing unit tests (188 total, 1 skipped).**

## What Happened

Created `subnet/consensus/chain_submitter.py` with `ChainScoreSubmitter(hypertensor, subnet_id)`. The `submit(scores)` method converts `List[SubnetNodeConsensusData]` to dicts via `asdict`, delegates to `hypertensor.propose_attestation(subnet_id, data=...)`, logs on `is_success=False`, and catches/logs/returns-None on exceptions. No retry logic is duplicated — that lives inside `Hypertensor`.

Created `tests/consensus/` directory with `__init__.py` and `test_chain_submitter.py` with 5 `MagicMock`-based tests covering all required paths. Also fixed the S02-PLAN.md pre-flight gap by adding two diagnostic inline-script verification steps that confirm exception→None and failure-receipt→receipt behaviours without a live chain.

## Verification

```
pytest tests/consensus/test_chain_submitter.py -v
→ 5 passed in 0.04s

python3 -c "from subnet.consensus.chain_submitter import ChainScoreSubmitter; print('OK')"
→ OK

pytest tests/ -x -q
→ 188 passed, 1 skipped in 5.04s
```

Diagnostic checks (exception swallowed → None, failed receipt returned correctly) both passed inline.

## Diagnostics

- `python3 -c "from subnet.consensus.chain_submitter import ChainScoreSubmitter; ..."` confirms import is live
- `logger.error("⚠️ Score submission failed: ...")` fires on `receipt.is_success == False`
- `logger.error("Score submission exception: ...")` fires on unexpected exception
- Search container logs for `"Score submission"` to identify submission failures

## Deviations

None — implemented exactly as specified in the task plan.

## Known Issues

None.

## Files Created/Modified

- `subnet/consensus/chain_submitter.py` — new; `ChainScoreSubmitter` class (~32 lines)
- `tests/consensus/__init__.py` — new; empty init for test package
- `tests/consensus/test_chain_submitter.py` — new; 5 unit tests (~80 lines)
- `.gsd/milestones/M005/slices/S02/S02-PLAN.md` — pre-flight fix: added two diagnostic failure-path verification steps to the Verification section
