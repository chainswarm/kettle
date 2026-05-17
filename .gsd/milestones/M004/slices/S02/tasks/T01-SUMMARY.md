---
id: T01
parent: S02
milestone: M004
provides:
  - _overwatch_epoch_loop wired into server nursery alongside _validator_scoring_loop
key_files:
  - subnet/server/server.py
key_decisions:
  - no_work_record logged at DEBUG (not WARNING) to suppress cold-start noise in INFO-level logs
patterns_established:
  - Overwatch loop starts 35s after server start (5s later than validator's 30s) so miner gossip is available on first audit
  - result.reason included in TAMPER log line for immediate triage without DB lookup
observability_surfaces:
  - "[Overwatch] TAMPER peer=<16chars> epoch=N reason=<reason> (WARNING)"
  - "[Overwatch] PASS peer=<16chars> epoch=N (INFO)"
  - "[OverwatchLoop] Auditing epoch=N (INFO) — one line per epoch to confirm loop is running"
  - "[OverwatchLoop] Error (non-fatal): <exc> (WARNING) — surfaced on unexpected exceptions"
  - "Diagnostic command: docker compose logs validator | grep '[Overwatch]'"
duration: 10m
verification_result: passed
completed_at: 2026-03-17
blocker_discovered: false
---

# T01: Wire `_overwatch_epoch_loop` into server nursery

**Added `_overwatch_epoch_loop` to `server.py` and wired it into the server nursery so every non-bootstrap node runs an independent overwatch audit alongside the validator scoring loop.**

## What Happened

Three surgical changes to `subnet/server/server.py`:

1. Added `MockOverwatchVerifier` to the existing import on line 64.
2. Appended `_overwatch_epoch_loop` as a module-level async function after `_validator_scoring_loop`, following the same trio-safe pattern (Cancelled re-raise, non-Cancelled loop guard, 5s poll interval, `move_on_after` sleep).
3. Added `nursery.start_soon(_overwatch_epoch_loop, self.db, peer_id_str, self.hypertensor, self.subnet_id, termination_event)` immediately after the `_validator_scoring_loop` start_soon block in `Server.run()`.

The loop waits 35s on startup (vs 30s for validator) so miner work records are available via GossipSub before the first audit runs. `no_work_record` results are logged at DEBUG to avoid INFO-level noise during the first 1–2 cold-start epochs.

## Verification

```
python3 -c "from subnet.server.server import Server, _miner_epoch_loop, _validator_scoring_loop, _overwatch_epoch_loop; print('ok')"
# → ok

python3 -m pytest tests/ -q --tb=short
# → 181 passed, 1 skipped in 5.03s
```

Both checks pass with no regressions.

## Diagnostics

- `docker compose logs validator | grep "\[Overwatch\]"` — shows TAMPER/PASS lines per peer per epoch
- `docker compose logs validator | grep "\[OverwatchLoop\]"` — shows startup wait, per-epoch audit start, and any non-fatal errors
- `[OverwatchLoop] Error (non-fatal): <exc>` at WARNING on unexpected exceptions; loop continues after 10s sleep
- Cold-start `no_work_record` misses appear only at DEBUG — absent from INFO-level container logs unless log level lowered

## Deviations

none

## Known Issues

none

## Files Created/Modified

- `subnet/server/server.py` — Added `MockOverwatchVerifier` to import; appended `_overwatch_epoch_loop` function; added `nursery.start_soon` call in `Server.run()` non-bootstrap block
- `.gsd/milestones/M004/slices/S02/S02-PLAN.md` — Added failure-path diagnostic verification step (pre-flight fix)
