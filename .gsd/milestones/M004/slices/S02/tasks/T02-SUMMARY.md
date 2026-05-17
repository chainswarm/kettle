---
id: T02
parent: S02
milestone: M004
provides:
  - TAMPER_RATE=1.0 set on miner-1 in docker-compose.tee-dev.yml (with production comment)
  - Live demo verified: [Overwatch] TAMPER + [Validator] score=0.00 correct=False for miner-1 each epoch
  - Live demo verified: [Overwatch] PASS + [Validator] score=0.50 correct=True for miner-2 each epoch
  - TESTING_LAYERS.md Layer 2 section updated with TAMPER_RATE=1.0 demo setup and expected log output
key_files:
  - docker-compose.tee-dev.yml
  - TESTING_LAYERS.md
key_decisions:
  - epoch cadence is ~120s (2-minute epochs) in the mock chain, so live demo requires ~7min to accumulate 3 TAMPER epochs (not 65s as estimated in the plan)
patterns_established:
  - First 1-2 epochs show no_work_record (cold-start GossipSub miss) at DEBUG; from epoch 3+ both [Validator] and [Overwatch] fire every epoch when TAMPER_RATE=1.0
  - no_work_record lines are never at WARNING/INFO in validator logs — confirmed 0 occurrences at INFO level
  - [Overwatch] TAMPER is logged at WARNING; [Overwatch] PASS at INFO (consistent with severity model: tamper is actionable, pass is informational)
observability_surfaces:
  - "docker compose -f docker-compose.tee-dev.yml logs validator | grep '[Overwatch]\\|[Validator]' — single command shows both audit streams"
  - "[Overwatch] TAMPER peer=<16chars> epoch=N reason=parity_mismatch — WARNING level, fires every epoch for miner-1 with TAMPER_RATE=1.0"
  - "[Overwatch] PASS peer=<16chars> epoch=N — INFO level, fires every epoch for miner-2"
  - "[OverwatchLoop] Auditing epoch=N — INFO level, confirms loop is running per epoch"
duration: ~7min demo wait (3x 2-min epochs after 1min startup)
verification_result: passed
completed_at: 2026-03-17
blocker_discovered: false
---

# T02: Set TAMPER_RATE=1.0, run live demo, update docs

**Set miner-1 TAMPER_RATE=1.0 and confirmed live demo: [Overwatch] TAMPER + [Validator] score=0.00 for miner-1 every epoch, [Overwatch] PASS + score=0.50 for miner-2, 3 tamper epochs verified, 0 loop errors, 0 no_work_record at INFO level.**

## What Happened

1. **Pre-flight**: Added `## Observability Impact` section to T02-PLAN.md (runtime signals, inspection commands, failure state shapes). Enhanced S02-PLAN.md verification step 6 with additional failure-path diagnostics (structured audit summary command, miner-2 tamper detection check).

2. **docker-compose.tee-dev.yml**: Changed miner-1's `TAMPER_RATE: "0.001"` to `TAMPER_RATE: "1.0"  # demo value; production: 0.001`. validator stays `"0.0"`, miner-2 stays `"0.001"`.

3. **Live demo**: Built and started all 4 containers (`tee-bootnode`, `tee-validator`, `tee-miner-1`, `tee-miner-2`). After ~2 minutes startup/gossip formation, epoch scoring began. From epoch 3 (14781189) onward:
   - `[Validator] peer=12D3KooWM5J4zS17 epoch=N score=0.00 correct=False` — miner-1 tamper detected by validator every epoch
   - `[Validator] peer=12D3KooWKxAhu5U8 epoch=N score=0.50 correct=True` — miner-2 clean every epoch
   - `[Overwatch] TAMPER peer=12D3KooWM5J4zS17 epoch=N reason=parity_mismatch` — overwatch independently confirms tamper
   - `[Overwatch] PASS peer=12D3KooWKxAhu5U8 epoch=N` — overwatch confirms miner-2 clean
   
   Ran for 3 complete epochs (14781189, 14781190, 14781191). Final counts: TAMPER=3, PASS=6 (3 per miner-2 epoch), loop errors=0, no_work_record at INFO=0.

4. **TESTING_LAYERS.md**: Updated Layer 2 section — "demo setup" block now shows `miner-1 ← TAMPER_RATE=1.0 (every epoch tampered — demo mode; production: 0.001)` and `miner-2 ← TAMPER_RATE=0.001 (honest reference)`; added "Expected log output (TAMPER_RATE=1.0)" subsection with actual log line examples; updated "Key variables" to show `TAMPER_RATE=1.0  # demo mode; production: 0.001`.

5. **Teardown**: `docker compose down --volumes` exited 0 cleanly, all containers and volumes removed.

## Verification

```
# Import check
python3 -c "from subnet.server.server import Server, _miner_epoch_loop, _validator_scoring_loop, _overwatch_epoch_loop; print('ok')"
# Result: ok ✓

# Unit regression
python3 -m pytest tests/ -q --tb=short
# Result: 181 passed, 1 skipped ✓

# Compose file TAMPER_RATE values
grep "TAMPER_RATE" docker-compose.tee-dev.yml
# Result: validator="0.0", miner-1="1.0", miner-2="0.001" ✓

# Live demo TAMPER count (epoch 14781189–14781191)
# TAMPER count: 3 ✓ (>= 3 required)
# PASS count:   6 ✓ (>= 1 required)
# Loop errors:  0 ✓ (should be 0)
# no_work_record at INFO level: 0 ✓ (cold-start misses suppressed to DEBUG)
```

## Diagnostics

```bash
# During a live run, inspect both audit streams in one command:
docker compose -f docker-compose.tee-dev.yml logs validator | grep "\[Overwatch\]\|\[Validator\]"

# Count tamper detections (expect >= 3 from epoch 3+):
docker compose -f docker-compose.tee-dev.yml logs validator | grep -c "\[Overwatch\] TAMPER"

# Audit summary:
echo "TAMPER: $(... | grep -c TAMPER), PASS: $(... | grep -c PASS), Errors: $(... | grep -c 'OverwatchLoop.*Error')"

# If [Overwatch] lines are absent entirely:
# → check [OverwatchLoop] lines — if only "Waiting 35s" and no "Auditing epoch=N" lines, loop failed to start
# → verify T01 import: python3 -c "from subnet.server.server import _overwatch_epoch_loop; print('ok')"

# If miner-1 shows no TAMPER (unexpected):
# → check docker compose logs miner-1 | grep "TAMPER" to confirm miner-1 is generating tampers
# → check TAMPER_RATE in docker-compose.tee-dev.yml (should be "1.0" for miner-1 service)
```

## Deviations

- **Epoch duration**: Plan estimated 65s wait to see 3+ tamper epochs. Actual epoch cadence is ~120s (mock chain epoch length), so 3 epochs required ~7 minutes. This is inherent to the mock chain, not a code issue. The plan's "count from epoch 3 onward" guidance is correct; only the wall-clock estimate was off.
- **Pre-flight fixes**: Added observability gap fixes to T02-PLAN.md (Observability Impact section) and S02-PLAN.md (enhanced failure-path verification step 6b + structured audit summary) per pre-flight instructions. These are plan file enhancements, not code changes.

## Known Issues

None.

## Files Created/Modified

- `docker-compose.tee-dev.yml` — miner-1 TAMPER_RATE changed from `"0.001"` to `"1.0"` with production comment
- `TESTING_LAYERS.md` — Layer 2 demo setup updated to TAMPER_RATE=1.0; added "Expected log output" subsection with actual log line examples; Key variables updated
- `.gsd/milestones/M004/slices/S02/tasks/T02-PLAN.md` — added Observability Impact section (pre-flight fix)
- `.gsd/milestones/M004/slices/S02/S02-PLAN.md` — enhanced verification step 6 with failure-path diagnostics (pre-flight fix)
