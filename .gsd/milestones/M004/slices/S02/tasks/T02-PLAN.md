---
estimated_steps: 3
estimated_files: 3
---

# T02: Set TAMPER_RATE=1.0, run live demo, update docs

**Slice:** S02 — Live tamper detection demo
**Milestone:** M004

## Description

With `_overwatch_epoch_loop` now running (T01), this task flips miner-1's `TAMPER_RATE` from `0.001` to `1.0` so every epoch is tampered, runs the live docker compose demo to confirm both `[Validator]` and `[Overwatch]` log lines fire as expected, and updates `TESTING_LAYERS.md` to document the verified behaviour.

This is the milestone's primary demo moment: after ~65 seconds you see every miner-1 epoch flagged independently by both the validator and overwatch, while miner-2 passes cleanly.

## Steps

1. **Update `docker-compose.tee-dev.yml`** — change miner-1's `TAMPER_RATE` from `"0.001"` to `"1.0"`, adding a comment for the production value:
   ```yaml
   TAMPER_RATE: "1.0"  # demo value; production: 0.001
   ```
   Leave miner-2's `TAMPER_RATE: "0.001"` unchanged (honest reference node).
   Leave validator's `TAMPER_RATE: "0.0"` unchanged.

2. **Run the live demo** to confirm expected output:
   ```bash
   # Build and start
   docker compose -f docker-compose.tee-dev.yml up --build -d
   # Wait for mesh formation + first scored epochs (65s covers 30s validator wait + ~2 epoch cycles)
   sleep 65
   
   # Check validator detects tamper on miner-1
   docker compose -f docker-compose.tee-dev.yml logs validator | grep "\[Validator\]"
   # Must see: score=0.00 correct=False for miner-1; score=0.50 correct=True for miner-2
   
   # Check overwatch independently flags miner-1
   docker compose -f docker-compose.tee-dev.yml logs validator | grep "\[Overwatch\]"
   # Must see: TAMPER ... parity_mismatch for miner-1; PASS for miner-2
   
   # Confirm unit tests still green
   python3 -m pytest tests/ -q --tb=short
   # Expected: 181 passed, 1 skipped
   
   # Tear down
   docker compose -f docker-compose.tee-dev.yml down --volumes
   ```
   Count from epoch 3 onward — first 1–2 epochs may show `no_work_record` (GossipSub cold-start miss). This is expected. Verify at least 3 tamper-flagged epochs appear in the logs.

3. **Update `TESTING_LAYERS.md`** Layer 2 section:
   - In the "demo setup" block, change `miner-1    ← TAMPER_RATE=1/1000` to `miner-1    ← TAMPER_RATE=1.0 (every epoch tampered — demo mode; production: 0.001)`
   - Change `miner-2    ← TAMPER_RATE=0 (always honest)` to `miner-2    ← TAMPER_RATE=0.001 (honest reference)`
   - Remove the "After ~1000 epochs..." sentence and replace with: "With `TAMPER_RATE=1.0`, from epoch 3 onward, miner-1 is flagged every epoch by both validator and overwatch. This is visible in `docker compose logs validator`."
   - Add a **"Expected log output"** subsection after the demo setup block:
     ```
     ## Expected log output (TAMPER_RATE=1.0)
     
     ```bash
     # Validator detects tamper on miner-1, scores miner-2 cleanly:
     docker compose -f docker-compose.tee-dev.yml logs validator | grep "\[Validator\]"
     # [Validator] peer=<miner-1-prefix> epoch=N score=0.00 correct=False
     # [Validator] peer=<miner-2-prefix> epoch=N score=0.50 correct=True
     
     # Overwatch independently confirms parity_mismatch on miner-1:
     docker compose -f docker-compose.tee-dev.yml logs validator | grep "\[Overwatch\]"
     # [Overwatch] TAMPER peer=<miner-1-prefix> epoch=N reason=parity_mismatch
     # [Overwatch] PASS peer=<miner-2-prefix> epoch=N
     ```
     ```
   - In the "Key variables" section, update `TAMPER_RATE=0.001` to `TAMPER_RATE=1.0  # demo mode; production: 0.001`

## Must-Haves

- [ ] miner-1's `TAMPER_RATE` is `"1.0"` in `docker-compose.tee-dev.yml` with a comment noting the production value (`0.001`)
- [ ] miner-2's `TAMPER_RATE` is still `"0.001"` (unchanged)
- [ ] Live demo produces `[Overwatch] TAMPER ... parity_mismatch` for miner-1 (at least 3 occurrences from epoch 3+)
- [ ] Live demo produces `[Overwatch] PASS` for miner-2 (at least 1 occurrence)
- [ ] Live demo produces `[Validator] ... score=0.00 correct=False` for miner-1
- [ ] Live demo produces `[Validator] ... score=0.50 correct=True` for miner-2
- [ ] `docker compose down --volumes` exits 0 cleanly
- [ ] `TESTING_LAYERS.md` Layer 2 section reflects `TAMPER_RATE=1.0` demo with actual log line examples
- [ ] Unit tests: 181 passed, 1 skipped

## Verification

```bash
# Import check (ensures T01 is complete and server.py is importable)
python3 -c "from subnet.server.server import _overwatch_epoch_loop; print('ok')"

# Unit regression
python3 -m pytest tests/ -q --tb=short
# Expected: 181 passed, 1 skipped

# Compose file sanity
grep "TAMPER_RATE" docker-compose.tee-dev.yml
# Expected: miner-1 shows "1.0", miner-2 shows "0.001", validator shows "0.0"

# Live demo (after docker compose up + 65s wait):
docker compose -f docker-compose.tee-dev.yml logs validator | grep "\[Overwatch\] TAMPER" | wc -l
# Expected: >= 3

docker compose -f docker-compose.tee-dev.yml logs validator | grep "\[Overwatch\] PASS" | wc -l
# Expected: >= 1
```

## Inputs

- `docker-compose.tee-dev.yml` — existing file with `TAMPER_RATE: "0.001"` on miner-1 (line ~100)
- `TESTING_LAYERS.md` — Layer 2 section starting at "## Layer 2 — Docker Network (Integration Tests)" (~line 61)
- T01 output: `_overwatch_epoch_loop` wired and importable from `subnet.server.server`
- S01 Forward Intelligence: count tamper detections from epoch 3+, not epoch 1; GossipSub cold-start miss is expected on first 1–2 epochs

## Observability Impact

**Signals added/changed by this task:**
- `[Overwatch] TAMPER peer=<16chars> epoch=N reason=parity_mismatch` — fires every epoch for miner-1 when `TAMPER_RATE=1.0`; visible in `docker compose logs validator | grep "\[Overwatch\]"`
- `[Overwatch] PASS peer=<16chars> epoch=N` — fires every epoch for miner-2 (honest reference)
- `[Validator] peer=<prefix> epoch=N score=0.00 correct=False` — validator independently confirms tamper on miner-1
- `[Validator] peer=<prefix> epoch=N score=0.50 correct=True` — validator confirms clean score for miner-2

**How a future agent inspects this task:**
```bash
# Both audit streams in one command:
docker compose -f docker-compose.tee-dev.yml logs validator | grep "\[Overwatch\]\|\[Validator\]"

# Count TAMPER detections (expect >= 3 from epoch 3+):
docker compose -f docker-compose.tee-dev.yml logs validator | grep "\[Overwatch\] TAMPER" | wc -l

# Failure-path: check for unexpected loop errors:
docker compose -f docker-compose.tee-dev.yml logs validator | grep "\[OverwatchLoop\] Error"

# Verify no_work_record lines are suppressed at INFO level (cold-start, not a failure):
docker compose -f docker-compose.tee-dev.yml logs validator | grep -c "no_work_record"
# Expected: 0 (DEBUG-only; not visible at default INFO log level)
```

**What failure state looks like:**
- Zero `[Overwatch]` lines → `_overwatch_epoch_loop` not wired (T01 incomplete or import error)
- `[OverwatchLoop] Error (non-fatal): <exc>` lines → check `MockOverwatchVerifier` contract or DB connectivity
- `no_work_record` at WARNING → cold-start suppression broke (must be DEBUG only)
- miner-2 showing `TAMPER` → `TAMPER_RATE` accidentally set on miner-2 (should stay `0.001`)

## Expected Output

- `docker-compose.tee-dev.yml` — miner-1 `TAMPER_RATE` changed to `"1.0"` with production-value comment
- `TESTING_LAYERS.md` — Layer 2 section updated with `TAMPER_RATE=1.0` demo description and actual log line examples
- Live demo confirmed: both `[Overwatch] TAMPER` and `[Validator] score=0.00` appear for miner-1 from epoch 3+
