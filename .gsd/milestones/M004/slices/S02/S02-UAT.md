# S02: Live tamper detection demo — UAT

**Milestone:** M004
**Written:** 2026-03-17

## UAT Type

- UAT mode: live-runtime
- Why this mode is sufficient: The slice goal is demonstrating that two independent audit systems (validator + overwatch) both flag miner-1 tampers in a live multi-container Docker environment. This requires real containers, real GossipSub transport, and human inspection of log output — no mock or artifact-driven test can substitute.

## Preconditions

1. Docker is running and `docker compose` is available
2. Working directory is the repo root (contains `docker-compose.tee-dev.yml`)
3. No leftover containers from a previous run: `docker compose -f docker-compose.tee-dev.yml down --volumes` exits cleanly (or was never run)
4. `python3 -m pytest tests/ -q --tb=short` → 181 passed, 1 skipped (baseline regression check)
5. Import check: `python3 -c "from subnet.server.server import Server, _miner_epoch_loop, _validator_scoring_loop, _overwatch_epoch_loop; print('ok')"` → ok

## Smoke Test

```bash
grep "TAMPER_RATE" docker-compose.tee-dev.yml
```
**Expected:** Three lines — validator=`"0.0"`, miner-1=`"1.0"`, miner-2=`"0.001"`. If miner-1 shows anything other than `"1.0"`, stop — the compose file is wrong.

---

## Test Cases

### 1. All four containers start cleanly

```bash
docker compose -f docker-compose.tee-dev.yml up --build -d
sleep 10
docker compose -f docker-compose.tee-dev.yml ps
```

1. Wait for build to complete (~1–2 min on first run, faster if cached)
2. **Expected:** All four services (`tee-bootnode`, `tee-validator`, `tee-miner-1`, `tee-miner-2`) show status `running` (or `Up`)
3. **Not expected:** Any service in `Exit` or `Restarting` state

---

### 2. Overwatch loop starts and audits epochs

```bash
# After containers are running, wait ~90s for gossip mesh to form and first epoch to complete
sleep 90
docker compose -f docker-compose.tee-dev.yml logs validator | grep "\[OverwatchLoop\]"
```

1. **Expected:** At least one line `[OverwatchLoop] Waiting 35s for mesh formation...`
2. **Expected:** At least one line `[OverwatchLoop] Auditing epoch=<N>` (confirms loop advanced past startup wait)
3. **Expected:** Zero lines `[OverwatchLoop] Error (non-fatal)` (healthy run has no exceptions)

---

### 3. Validator detects miner-1 tamper every epoch (from epoch 3+)

```bash
# Wait for at least 3 complete epochs (~7min total from docker compose up, ~5min from now)
sleep 300
docker compose -f docker-compose.tee-dev.yml logs validator | grep "\[Validator\]"
```

1. **Expected for miner-1:** Lines of the form `[Validator] peer=12D3KooW<16chars> epoch=<N> score=0.00 correct=False` — one per epoch from epoch 3 onward
2. **Expected for miner-2:** Lines of the form `[Validator] peer=12D3KooW<16chars> epoch=<N> score=0.50 correct=True` — one per epoch from epoch 3 onward
3. **Not expected:** Any `score=0.50 correct=True` line for the miner-1 peer ID (the one with TAMPER_RATE=1.0)
4. **Not expected:** Any `score=0.00 correct=False` line for the miner-2 peer ID

> **Identifying which peer is which:** Run `docker inspect tee-miner-1 | python3 -c 'import sys,json; d=json.load(sys.stdin); print(d[0]["Config"]["Hostname"])'` and match the first 16 characters against log output, OR look at earlier validator log lines where peer IDs appear alongside `[GossipReceiver]` lines.

---

### 4. Overwatch independently confirms miner-1 tamper every epoch

```bash
docker compose -f docker-compose.tee-dev.yml logs validator | grep "\[Overwatch\]"
```

1. **Expected for miner-1:** Lines of the form `[Overwatch] TAMPER peer=<16chars> epoch=<N> reason=parity_mismatch` — one per epoch from epoch 3 onward (same epoch numbers as the Validator lines in test 3)
2. **Expected for miner-2:** Lines of the form `[Overwatch] PASS peer=<16chars> epoch=<N>` — one per epoch from epoch 3 onward
3. **Not expected:** Any `[Overwatch] TAMPER` line for the miner-2 peer ID
4. **Not expected:** Any `[Overwatch] PASS` line for the miner-1 peer ID (with TAMPER_RATE=1.0, every epoch should be caught)

---

### 5. Structured audit summary — quantified pass/fail

```bash
echo "=== Overwatch audit summary ===" && \
  echo "TAMPER count: $(docker compose -f docker-compose.tee-dev.yml logs validator | grep -c '\[Overwatch\] TAMPER')" && \
  echo "PASS count:   $(docker compose -f docker-compose.tee-dev.yml logs validator | grep -c '\[Overwatch\] PASS')" && \
  echo "Loop errors:  $(docker compose -f docker-compose.tee-dev.yml logs validator | grep -c '\[OverwatchLoop\] Error')"
```

1. **Expected:** `TAMPER count: 3` or higher (one per epoch, from epoch 3+; exact number depends on how long you waited)
2. **Expected:** `PASS count: 1` or higher (one per epoch for miner-2)
3. **Expected:** `Loop errors: 0`

---

### 6. No cold-start noise at INFO level

```bash
docker compose -f docker-compose.tee-dev.yml logs validator | grep -c "no_work_record"
```

1. **Expected:** `0` — cold-start misses in epochs 1-2 are suppressed to DEBUG and must not appear in INFO-level container logs

---

### 7. Both audit streams visible in a single command

```bash
docker compose -f docker-compose.tee-dev.yml logs validator | grep "\[Overwatch\]\|\[Validator\]"
```

1. **Expected:** Interleaved lines showing `[Validator]` scoring lines and `[Overwatch]` audit lines for the same epoch numbers
2. **Expected:** Pattern per epoch: `[Validator] peer=<miner-1> ... score=0.00 correct=False` then `[Validator] peer=<miner-2> ... score=0.50 correct=True` then `[Overwatch] TAMPER peer=<miner-1> ...` then `[Overwatch] PASS peer=<miner-2> ...`

---

### 8. Clean teardown

```bash
docker compose -f docker-compose.tee-dev.yml down --volumes
echo "Exit code: $?"
```

1. **Expected:** Exit code `0`
2. **Expected:** All four containers removed (verify with `docker compose -f docker-compose.tee-dev.yml ps` → empty)
3. **Expected:** Named volumes removed (no orphans visible in `docker volume ls | grep tee`)

---

## Edge Cases

### Cold-start epoch misses (epochs 1-2)

For the first 1-2 epochs after `docker compose up`, the overwatch loop may have no work records to audit (GossipSub mesh not yet formed when the first gossip messages were published). 

1. Inspect early overwatch output: `docker compose -f docker-compose.tee-dev.yml logs validator | grep "\[OverwatchLoop\]" | head -20`
2. **Expected:** `[OverwatchLoop] Waiting 35s for mesh formation...` appears once, then `[OverwatchLoop] Auditing epoch=N` appears for subsequent epochs — no TAMPER/PASS lines for epochs 1-2 is normal
3. **Not expected:** `[OverwatchLoop] Error` lines in this window

### Confirming miner-2 is never falsely flagged

```bash
MINER2_PEER=$(docker compose -f docker-compose.tee-dev.yml logs validator | grep "\[Validator\].*score=0.50" | head -1 | grep -oP 'peer=\K\S+')
docker compose -f docker-compose.tee-dev.yml logs validator | grep "\[Overwatch\] TAMPER" | grep "$MINER2_PEER"
```

1. **Expected:** No output — miner-2 (TAMPER_RATE=0.001) should never appear in a TAMPER line during a short demo run

### Overwatch and validator agree on epoch numbers

```bash
docker compose -f docker-compose.tee-dev.yml logs validator | grep "\[Overwatch\] TAMPER\|\[Validator\].*correct=False" | grep -oP 'epoch=\K[0-9]+'| sort -u
```

1. **Expected:** The same epoch numbers appear in both streams — validator and overwatch score the same epoch from different code paths

---

## Failure Signals

- **No `[Overwatch]` lines at all**: `_overwatch_epoch_loop` failed to start. Check import: `python3 -c "from subnet.server.server import _overwatch_epoch_loop; print('ok')"`. If this fails, the `nursery.start_soon` call may have been removed or the import broken.
- **`[OverwatchLoop] Auditing epoch=N` appears but no TAMPER/PASS lines**: `MockOverwatchVerifier.verify()` is failing silently, or all peers are being skipped (check self-skip logic and peer_id extraction).
- **`[OverwatchLoop] Error (non-fatal)` lines**: An exception in the overwatch loop. Read the `<exc>` message — common causes: DB file not found, MockOverwatchVerifier instantiation error, peer list empty.
- **miner-1 shows `score=0.50` instead of `score=0.00`**: TAMPER_RATE is not 1.0. Run `grep "TAMPER_RATE" docker-compose.tee-dev.yml` and confirm miner-1 entry is `"1.0"`.
- **TAMPER count is 0 after 7+ minutes**: Either the compose file wasn't rebuilt (`--build` flag missing), or miner-1's container has the old image. Run `docker compose -f docker-compose.tee-dev.yml down --volumes && docker compose -f docker-compose.tee-dev.yml up --build -d`.
- **`no_work_record` count > 0**: Cold-start log suppression is broken. Check that `_overwatch_epoch_loop` logs `no_work_record` at `logger.debug()`, not `logger.warning()` or `logger.info()`.
- **Container exits during run**: Check `docker compose -f docker-compose.tee-dev.yml logs <service>` for the failing service. Common causes: port conflict, volume permission error, import error at startup.

---

## Requirements Proved By This UAT

- **R005 (multi-node)** — Two miners assessed independently by both validator and overwatch in a live 4-container run
- **R006 (real P2P DHT/GossipSub)** — Work records travel via GossipSub from miners to validator; overwatch reads them from the shared DB populated by GossipReceiver
- **R007 (live epoch timing)** — Validator and overwatch converge on the same epoch number without a shared clock; epoch agreement confirmed by matching epoch numbers in both log streams
- **R022 (test coverage)** — Live integration coverage: two independent audit paths (validator scoring + overwatch) verified in a running multi-container environment

---

## Not Proven By This UAT

- **Restart recovery (R008)**: `docker compose restart miner-1` recovery test is deferred to S03
- **Structured JSON logs**: `docker compose logs | jq` pipeline not yet available — deferred to S03
- **Real TEE hardware**: All verification uses `MOCK_TEE=true`; hardware DCAP verification on TDX/SEV-SNP hardware is a mainnet concern
- **Chain-integrated scoring**: Validator reads from a shared SQLite mock chain, not a real Hypertensor chain — deferred to M005
- **Long-duration stability**: UAT runs 3 epochs (~7 minutes). Multi-hour or multi-day stability not tested here

---

## Notes for Tester

- **Wait time**: The most common failure mode is checking logs too early. After `docker compose up --build -d`, wait at least 7 minutes (preferably 8-9) before checking for TAMPER/PASS lines. The mock chain epoch is ~120s and the first 1-2 epochs are cold-start misses.
- **Epoch 3+ is the baseline**: Ignore epochs 1-2 for scoring assertions. From epoch 3 onward, every epoch should produce exactly one TAMPER (miner-1) and one PASS (miner-2) per audit cycle.
- **TAMPER_RATE=1.0 is demo mode**: After UAT, if you want to restore production-realistic behaviour, change miner-1's `TAMPER_RATE` back to `"0.001"` in `docker-compose.tee-dev.yml`. Don't commit the restored value as a "fix" — TESTING_LAYERS.md documents 1.0 as intentional for demo.
- **Build cache**: If you've run the demo before, `--build` is still needed to pick up any code changes since the last run. Skip `--build` only if you're certain no Python files changed.
- **Peer ID prefix**: The 16-character peer ID prefix in log lines (e.g. `12D3KooWM5J4zS17`) will differ across runs because peer IDs are generated fresh on each boot. Match by position (miner-1 = tampered, miner-2 = honest) rather than by a hardcoded prefix.
