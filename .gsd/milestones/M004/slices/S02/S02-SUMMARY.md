---
id: S02
parent: M004
milestone: M004
provides:
  - _overwatch_epoch_loop wired into server nursery — runs alongside validator scoring loop on all non-bootstrap nodes
  - TAMPER_RATE=1.0 set on miner-1 in docker-compose.tee-dev.yml for demo
  - Live demo verified: [Overwatch] TAMPER + [Validator] score=0.00 correct=False for miner-1 every epoch from epoch 3+
  - Live demo verified: [Overwatch] PASS + [Validator] score=0.50 correct=True for miner-2 every epoch from epoch 3+
  - TESTING_LAYERS.md Layer 2 section updated with TAMPER_RATE=1.0 demo setup and actual observed log output
requires:
  - slice: S01
    provides: Live multi-node epoch loop (bootnode + validator + 2 miners), GossipSub cross-container work record transport, [Validator] score lines in logs
affects:
  - S03
key_files:
  - subnet/server/server.py
  - docker-compose.tee-dev.yml
  - TESTING_LAYERS.md
key_decisions:
  - no_work_record logged at DEBUG (not WARNING) — suppresses cold-start noise from first 1-2 epochs at INFO log level
  - Overwatch loop starts 35s after server start (5s later than validator's 30s) — gives GossipSub mesh time to form so first audit has records to check
  - result.reason included in TAMPER log line for immediate triage without DB lookup
  - [Overwatch] TAMPER logged at WARNING; [Overwatch] PASS at INFO — severity models tamper as actionable, pass as informational
  - Epoch cadence is ~120s (2-minute epochs) in the mock chain — 3 tamper epochs require ~7 minutes of runtime, not 65s as estimated in the plan
patterns_established:
  - Third nursery loop (_overwatch_epoch_loop) follows the same trio-safe pattern as _miner_epoch_loop and _validator_scoring_loop (Cancelled re-raise, non-Cancelled exception guard, move_on_after sleep)
  - Overwatch audits epoch-1 on the same cadence as validator, so both streams always refer to the same epoch number
  - Cold-start misses (no_work_record) are structurally expected for the first 1-2 epochs and are invisible at INFO level — only appear at DEBUG
  - Single grep command inspects both audit streams: docker compose logs validator | grep "[Overwatch]\|[Validator]"
observability_surfaces:
  - "[Overwatch] TAMPER peer=<16chars> epoch=N reason=parity_mismatch — WARNING, fires every epoch for miner-1 with TAMPER_RATE=1.0"
  - "[Overwatch] PASS peer=<16chars> epoch=N — INFO, fires every epoch for miner-2"
  - "[OverwatchLoop] Auditing epoch=N — INFO, one line per epoch confirming loop is alive"
  - "[OverwatchLoop] Error (non-fatal): <exc> — WARNING, on unexpected exceptions; loop continues after 10s sleep"
  - "docker compose -f docker-compose.tee-dev.yml logs validator | grep '[Overwatch]\\|[Validator]' — primary inspection command"
drill_down_paths:
  - .gsd/milestones/M004/slices/S02/tasks/T01-SUMMARY.md
  - .gsd/milestones/M004/slices/S02/tasks/T02-SUMMARY.md
duration: ~45m implementation + ~7min live demo run (3x 2-min epochs after ~1min startup)
verification_result: passed
completed_at: 2026-03-17
---

# S02: Live tamper detection demo

**Every epoch, both validator and overwatch independently flag miner-1 tampers in live Docker logs — `[Validator] score=0.00 correct=False` and `[Overwatch] TAMPER reason=parity_mismatch` — while miner-2 consistently passes both checks.**

## What Happened

S02 added the missing third server loop and flipped a config value to complete the tamper detection demo:

**T01 — Wire `_overwatch_epoch_loop` into server nursery** (`subnet/server/server.py`):

`MockOverwatchVerifier` existed and was tested in isolation (M003) but was never called in a running server. Three surgical changes wired it in: (1) added `MockOverwatchVerifier` to the existing mock import line; (2) added a module-level `_overwatch_epoch_loop` async function following the established trio-safe pattern — 35s startup wait, epoch poll, iterate peers via `hypertensor.get_min_class_subnet_nodes_formatted`, skip self, call `MockOverwatchVerifier(db=db).verify(peer_id, score_epoch)`, log TAMPER/PASS/no_work_record accordingly; (3) added `nursery.start_soon(_overwatch_epoch_loop, ...)` in `Server.run()` immediately after the validator start_soon call. The 35s startup delay (vs 30s for validator) ensures GossipSub mesh formation is complete before the first audit runs. Cold-start `no_work_record` results are suppressed to DEBUG so INFO-level logs are clean.

**T02 — Set TAMPER_RATE=1.0 and verify live demo** (`docker-compose.tee-dev.yml`, `TESTING_LAYERS.md`):

Changed miner-1's `TAMPER_RATE: "0.001"` to `TAMPER_RATE: "1.0"  # demo value; production: 0.001`. Validator stays `"0.0"`, miner-2 stays `"0.001"`. Built and ran all 4 containers; after ~2 minutes for gossip mesh formation, epoch scoring began. From epoch 3 (14781189) onward, every epoch produced:

- `[Validator] peer=12D3KooWM5J4zS17 epoch=N score=0.00 correct=False` (miner-1, tampered)
- `[Validator] peer=12D3KooWKxAhu5U8 epoch=N score=0.50 correct=True` (miner-2, honest)
- `[Overwatch] TAMPER peer=12D3KooWM5J4zS17 epoch=N reason=parity_mismatch` (overwatch catches miner-1)
- `[Overwatch] PASS peer=12D3KooWKxAhu5U8 epoch=N` (overwatch clears miner-2)

Final counts over 3 complete epochs: TAMPER=3, PASS=6, loop errors=0, no_work_record at INFO=0. `docker compose down --volumes` exited 0 cleanly. `TESTING_LAYERS.md` updated with TAMPER_RATE=1.0 demo setup block and actual observed log line examples.

## Verification

```
# Import check
python3 -c "from subnet.server.server import Server, _miner_epoch_loop, _validator_scoring_loop, _overwatch_epoch_loop; print('ok')"
# → ok ✓

# Unit regression
python3 -m pytest tests/ -q --tb=short
# → 181 passed, 1 skipped in 6.68s ✓

# Compose TAMPER_RATE values
grep "TAMPER_RATE" docker-compose.tee-dev.yml
# → validator="0.0", miner-1="1.0", miner-2="0.001" ✓

# Live demo (run previously, results observed):
# TAMPER count: 3 ✓ (>= 3 required)
# PASS count:   6 ✓ (>= 1 required)
# Loop errors:  0 ✓
# no_work_record at INFO level: 0 ✓
```

## Requirements Advanced

- R022 — Live overwatch loop in server nursery adds runtime coverage beyond the in-memory mock node tests; cold-start no_work_record suppression pattern validated in multi-container environment

## Requirements Validated

- R005 (multi-node) — Two miners + validator + bootnode running simultaneously; each miner independently assessed by both validator and overwatch
- R006 (real P2P DHT/GossipSub) — Work records from GossipSub transport used by overwatch to audit each miner; cross-container gossip confirmed
- R007 (live epoch timing) — Overwatch loop and validator loop both operate on the same epoch number in a live multi-container run; epoch agreement confirmed

## New Requirements Surfaced

- None

## Requirements Invalidated or Re-scoped

- None

## Deviations

- **Epoch duration**: Plan estimated 65s wait to see 3+ tamper epochs. Actual epoch cadence in the mock chain is ~120s (2-minute epochs), so 3 epochs required ~7 minutes. This is an inherent property of the mock chain, not a code issue. The 65s estimate in the plan was based on a 30s epoch assumption that doesn't match the actual mock chain configuration.

## Known Limitations

- **Epoch cadence**: ~120s mock chain epochs mean demo observers must wait ~7 minutes after `docker compose up` to see 3 tamper events. The S02-PLAN estimated 65s — the TESTING_LAYERS.md has been corrected but the plan file still reflects the shorter estimate.
- **No TAMPER_RATE toggle at runtime**: Switching from demo mode (1.0) back to production-realistic (0.001) requires a compose file edit and container rebuild. No hot-reload mechanism.
- **Cold-start epochs 1-2**: First two epochs show `no_work_record` at DEBUG (not surfaced at INFO). This is expected GossipSub behaviour and documented in KNOWLEDGE.md. From epoch 3 onward, both streams fire reliably.

## Follow-ups

- S03 should add structured JSON log output so `docker compose logs | jq` filtering works alongside the existing `grep "[Overwatch]"` pattern
- S03's restart recovery test should verify that `docker compose restart miner-1` causes `[Overwatch] TAMPER` to resume within one epoch (not just `[Validator]` lines)
- If a future slice needs faster tamper demo feedback, consider a `MOCK_CHAIN_EPOCH_SECONDS` env var to shorten epochs in demo/test environments without changing the mock chain internals

## Files Created/Modified

- `subnet/server/server.py` — Added `MockOverwatchVerifier` to mock import; appended `_overwatch_epoch_loop` async function; added `nursery.start_soon` call in `Server.run()` non-bootstrap block
- `docker-compose.tee-dev.yml` — miner-1 TAMPER_RATE changed from `"0.001"` to `"1.0"  # demo value; production: 0.001`
- `TESTING_LAYERS.md` — Layer 2 demo setup updated to TAMPER_RATE=1.0; added "Expected log output" subsection with actual log line examples from live run; Key variables updated
- `.gsd/milestones/M004/slices/S02/S02-PLAN.md` — Enhanced verification step 6 with failure-path diagnostics and structured audit summary command (pre-flight fix)
- `.gsd/milestones/M004/slices/S02/tasks/T02-PLAN.md` — Added Observability Impact section (pre-flight fix)

## Forward Intelligence

### What the next slice should know

- The three-loop nursery pattern (`_miner_epoch_loop`, `_validator_scoring_loop`, `_overwatch_epoch_loop`) is now complete and stable. S03 work on `server.py` should focus on adding structured log output to these existing loops, not restructuring them.
- `docker compose restart miner-1` is the core S03 recovery test case. When miner-1 restarts, the overwatch loop on the validator will encounter `no_work_record` for 1-2 epochs (cold-start miss), then resume `TAMPER` detection. This is expected behaviour — S03 should confirm it, not try to eliminate it.
- The single-command inspection pattern (`grep "[Overwatch]\|[Validator]"`) is established and documented. S03's structured JSON logs should preserve these prefixes so both grep and jq work on the same log stream.
- `TESTING_LAYERS.md` Layer 2 section is now authoritative — it has actual log line examples from a live run. S03 should add a Layer 2 subsection for restart recovery and structured logs rather than modifying the existing demo section.

### What's fragile

- **GossipSub cold-start window**: The 35s overwatch startup delay is calibrated for the current 4-container setup. If S03 adds more containers or changes bootnode timing, this delay may need adjustment. The symptom of a too-short delay is `[Overwatch] TAMPER` appearing in the first 1-2 epochs when it shouldn't (before miner gossip has propagated) — which would look like false positives.
- **MockOverwatchVerifier stateless instantiation**: `MockOverwatchVerifier(db=db)` is instantiated fresh each epoch loop iteration, which is safe but slightly wasteful. If the verifier ever gains startup cost (e.g., loading a model), this should be hoisted to a module-level or loop-level singleton.

### Authoritative diagnostics

- `docker compose -f docker-compose.tee-dev.yml logs validator | grep "\[Overwatch\]\|\[Validator\]"` — single command showing both audit streams; the primary signal for "is tamper detection working?"
- `[OverwatchLoop] Auditing epoch=N` at INFO — one line per epoch; if absent, the loop failed to start (check import, nursery wiring)
- `[OverwatchLoop] Error (non-fatal): <exc>` at WARNING — loop is running but hitting exceptions; check exc message for DB or MockOverwatchVerifier issues
- `grep -c "\[Overwatch\] TAMPER"` count: should equal the number of epochs completed since epoch 3 when TAMPER_RATE=1.0

### What assumptions changed

- **Epoch duration**: Plan assumed 30s epochs (65s wait → 2 epochs). Actual mock chain uses ~120s epochs. The 35s startup wait is correct relative to gossip formation, but the plan's wall-clock demo timeline was based on the wrong epoch length.
- **no_work_record suppression**: Plan said "log at DEBUG (not WARNING)". This was implemented correctly. Confirmed in live demo that 0 `no_work_record` lines appear at INFO level across a full 3-epoch run including cold start.
