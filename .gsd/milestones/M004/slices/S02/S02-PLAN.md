# S02: Live tamper detection demo

**Goal:** Wire `MockOverwatchVerifier` into the server nursery so the overwatch loop runs alongside the validator loop; then set `TAMPER_RATE=1.0` on miner-1 so every epoch is flagged by both validator and overwatch.
**Demo:** `docker compose -f docker-compose.tee-dev.yml up --build` → from epoch 3 onward, both `[Validator] peer=<miner-1> epoch=N score=0.00 correct=False` and `[Overwatch] TAMPER peer=<miner-1> epoch=N reason=parity_mismatch` appear in `docker compose logs validator`, while miner-2 scores `0.50` and gets `[Overwatch] PASS` every epoch.

## Must-Haves

- `_overwatch_epoch_loop` runs in the server nursery for all non-bootstrap nodes
- `[Overwatch] TAMPER ... reason=parity_mismatch` appears in validator logs for miner-1 every epoch (from epoch 3+)
- `[Overwatch] PASS` appears for miner-2 every epoch (from epoch 3+)
- miner-1 validator score is `0.00 correct=False` every epoch (TAMPER_RATE=1.0)
- miner-2 validator score is `0.50 correct=True` every epoch
- `python3 -m pytest tests/ -q --tb=short` → 181 passed, 1 skipped (no regressions)

## Proof Level

- This slice proves: integration
- Real runtime required: yes
- Human/UAT required: yes (log inspection)

## Verification

```bash
# 1. Unit regression: no new failures
python3 -m pytest tests/ -q --tb=short
# Expected: 181 passed, 1 skipped

# 2. Import check
python3 -c "from subnet.server.server import Server, _miner_epoch_loop, _validator_scoring_loop, _overwatch_epoch_loop; print('ok')"
# Expected: ok

# 3. Live demo — build and start
docker compose -f docker-compose.tee-dev.yml up --build -d
sleep 65

# 4. Validator detects tamper on miner-1 every epoch
docker compose -f docker-compose.tee-dev.yml logs validator | grep "\[Validator\]"
# Expected lines (one per miner per epoch, from epoch 3+):
#   [Validator] peer=<miner-1-prefix> epoch=N score=0.00 correct=False
#   [Validator] peer=<miner-2-prefix> epoch=N score=0.50 correct=True

# 5. Overwatch independently flags miner-1
docker compose -f docker-compose.tee-dev.yml logs validator | grep "\[Overwatch\]"
# Expected lines:
#   [Overwatch] TAMPER peer=<miner-1-prefix> epoch=N reason=parity_mismatch
#   [Overwatch] PASS peer=<miner-2-prefix> epoch=N

# 6. Failure-path diagnostics — confirm cold-start misses and loop errors are visible
docker compose -f docker-compose.tee-dev.yml logs validator | grep "\[OverwatchLoop\]"
# Expected lines on cold start (DEBUG only, may not appear at INFO level):
#   [OverwatchLoop] Waiting 35s for mesh formation...
#   [OverwatchLoop] Auditing epoch=N
# On any loop exception (should be absent in healthy run):
#   [OverwatchLoop] Error (non-fatal): <exc>
#   [OverwatchLoop] Audit error peer=<prefix>: <exc>
# Confirm no_work_record lines are absent at WARNING level (cold-start misses must NOT surface as warnings):
docker compose -f docker-compose.tee-dev.yml logs validator | grep -c "no_work_record" && echo "count_ok"
# Expected: 0\ncount_ok  (no WARNING-level no_work_record lines in logs)

# 6b. Failure-state inspection — confirm inspectable error output exists
# If TAMPER lines are missing, check for loop start failure:
docker compose -f docker-compose.tee-dev.yml logs validator | grep "\[OverwatchLoop\] Error"
# Expected: no lines (healthy run); if lines appear, check exc message for DB or import issues

# If miner-2 shows TAMPER (should never happen):
docker compose -f docker-compose.tee-dev.yml logs validator | grep "\[Overwatch\] TAMPER" | grep -v "$(docker inspect tee-miner-1 2>/dev/null | python3 -c 'import sys,json; d=json.load(sys.stdin); print(d[0]["Config"]["Hostname"][:16] if d else "miner-1")' 2>/dev/null)"
# Expected: no lines (only miner-1 should be flagged)

# Structured audit summary — counts for quick pass/fail assessment:
echo "=== Overwatch audit summary ===" && \
  echo "TAMPER count: $(docker compose -f docker-compose.tee-dev.yml logs validator | grep -c '\[Overwatch\] TAMPER')" && \
  echo "PASS count:   $(docker compose -f docker-compose.tee-dev.yml logs validator | grep -c '\[Overwatch\] PASS')" && \
  echo "Loop errors:  $(docker compose -f docker-compose.tee-dev.yml logs validator | grep -c '\[OverwatchLoop\] Error')"
# Expected: TAMPER count >= 3, PASS count >= 1, Loop errors = 0

# 7. Tear down
docker compose -f docker-compose.tee-dev.yml down --volumes
# Expected: exit 0, all containers and volumes removed
```

## Observability / Diagnostics

- Runtime signals: `[Overwatch] TAMPER` / `[Overwatch] PASS` per epoch per peer; `[Validator] score=0.00 correct=False` per miner-1 epoch
- Inspection surfaces: `docker compose logs validator | grep "\[Overwatch\]\|\[Validator\]"` — single command shows both audit streams
- Failure visibility: `[OverwatchLoop] No work record` at DEBUG on cold start (first 1–2 epochs); `[OverwatchLoop] Error (non-fatal)` on exceptions with full traceback
- Redaction constraints: none (no secrets in mock TEE logs)

## Integration Closure

- Upstream surfaces consumed: `MockOverwatchVerifier.verify(peer_id, epoch)` from `subnet/node/mock.py`; `hypertensor.get_min_class_subnet_nodes_formatted(...)` peer list; `db.nmap_get` work records written by `GossipReceiver`
- New wiring introduced in this slice: `_overwatch_epoch_loop` in `server.py` + `nursery.start_soon(...)` call in `Server.run()` non-bootstrap block
- What remains before the milestone is truly usable end-to-end: S03 (restart recovery + structured JSON logs)

## Tasks

- [x] **T01: Wire `_overwatch_epoch_loop` into server nursery** `est:45m`
  - Why: `MockOverwatchVerifier` exists and works in tests but is never called in a running server. This task adds the missing third epoch loop so overwatch output appears in logs.
  - Files: `subnet/server/server.py`
  - Do: (1) Add `MockOverwatchVerifier` to the existing import on line 64: `from subnet.node.mock import MockNodeProtocol, MockNodeScoring, MockOverwatchVerifier, _WORK_TOPIC`. (2) Add module-level async function `_overwatch_epoch_loop(db, self_peer_id, hypertensor, subnet_id, termination_event)` after `_validator_scoring_loop`. Pattern: 35s startup wait; poll epoch; score `epoch - 1`; iterate peers via `hypertensor.get_min_class_subnet_nodes_formatted(subnet_id, score_epoch, SubnetNodeClass.Validator)`; extract `peer_id` using `hasattr(peer_info, "peer_id")` pattern; skip self; call `MockOverwatchVerifier(db=db).verify(peer_id, score_epoch)`; log `[Overwatch] TAMPER peer=<16chars> epoch=N reason=<result.reason>` when `not result.ok and result.reason != "no_work_record"`; log `[Overwatch] PASS peer=<16chars> epoch=N` when `result.ok`; log at DEBUG (not WARNING) when `result.reason == "no_work_record"` (cold-start miss); same `trio.Cancelled` re-raise + non-Cancelled exception loop as other two loops. (3) In `Server.run()`, add `nursery.start_soon(_overwatch_epoch_loop, self.db, peer_id_str, self.hypertensor, self.subnet_id, termination_event)` immediately after the `_validator_scoring_loop` start_soon call (around line 393).
  - Verify: `python3 -c "from subnet.server.server import _overwatch_epoch_loop; print('ok')"` → ok; `python3 -m pytest tests/ -q --tb=short` → 181 passed, 1 skipped
  - Done when: import check passes and all 181 tests still pass

- [x] **T02: Set TAMPER_RATE=1.0, run live demo, update docs** `est:30m`
  - Why: The milestone DoD requires demo verification with `TAMPER_RATE=1.0` (every epoch tampered). The compose file currently has `0.001` (1-in-1000). This task flips the rate, runs the live demo to confirm both log streams fire, and updates `TESTING_LAYERS.md` to reflect actual demo behaviour.
  - Files: `docker-compose.tee-dev.yml`, `TESTING_LAYERS.md`
  - Do: (1) In `docker-compose.tee-dev.yml`, change miner-1's `TAMPER_RATE: "0.001"` to `TAMPER_RATE: "1.0"  # demo value; production: 0.001`. Leave miner-2 at `"0.001"` (honest reference). Leave validator at `"0.0"`. (2) Run `docker compose -f docker-compose.tee-dev.yml up --build -d`, wait 65s, then grep validator logs for `[Validator]` and `[Overwatch]`. Confirm: miner-1 shows `score=0.00 correct=False` and `TAMPER ... parity_mismatch`; miner-2 shows `score=0.50 correct=True` and `PASS`. Count from epoch 3+ (first 1–2 epochs may miss due to GossipSub cold-start). Run `docker compose -f docker-compose.tee-dev.yml down --volumes`. (3) Update `TESTING_LAYERS.md` Layer 2 section: change `TAMPER_RATE=1/1000` to `TAMPER_RATE=1.0` in the demo setup block; add actual observed log lines under a "Expected log output" subsection; update verification commands to include the `grep "[Overwatch]"` command alongside the existing `grep "[Validator]"` command.
  - Verify: `docker compose logs validator | grep "\[Overwatch\] TAMPER"` returns at least 3 lines (one per epoch from epoch 3+); `docker compose logs validator | grep "\[Overwatch\] PASS"` also returns lines for miner-2; `python3 -m pytest tests/ -q --tb=short` → 181 passed, 1 skipped
  - Done when: both `[Overwatch] TAMPER` and `[Overwatch] PASS` appear in live logs; TESTING_LAYERS.md reflects TAMPER_RATE=1.0 demo with actual log examples

## Files Likely Touched

- `subnet/server/server.py` — add `MockOverwatchVerifier` import + `_overwatch_epoch_loop` function + `nursery.start_soon` call
- `docker-compose.tee-dev.yml` — miner-1 `TAMPER_RATE` `0.001` → `1.0` (with comment)
- `TESTING_LAYERS.md` — Layer 2 section: update demo setup, add overwatch log lines, update verification commands
