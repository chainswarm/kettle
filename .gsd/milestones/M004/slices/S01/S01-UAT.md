---
id: S01
parent: M004
milestone: M004
uat_type: live-runtime
---

# S01: Multi-node epoch loop — UAT

**Milestone:** M004
**Written:** 2026-03-17

## UAT Type

- UAT mode: live-runtime
- Why this mode is sufficient: The slice goal is a running multi-container network with epoch scoring. Only a real Docker Compose run can verify DHT gossip crosses container boundaries, epoch numbers agree, and `[Validator]` scoring lines appear. Artifact-only or unit tests cannot substitute.

## Preconditions

1. Docker is running on the host machine
2. Repo is at `/home/aphex5/work/subnet-template/.gsd/worktrees/M001` (or repo root)
3. Key files present at repo root: `bootnode.key`, `alith.key`, `baltathar.key`, `charleth.key`
4. No existing containers from a prior run: `docker compose -f docker-compose.tee-dev.yml ps` shows empty
5. Unit tests pass: `python3 -m pytest tests/ -q --tb=short` → 181 passed, 1 skipped

## Smoke Test

```bash
docker compose -f docker-compose.tee-dev.yml up --build --detach
sleep 30
docker compose -f docker-compose.tee-dev.yml ps
```

**Expected:** All 4 services (`bootnode`, `validator`, `miner-1`, `miner-2`) are listed with status `Up` (or `(healthy)` if health checks are applied). No service has `Exit` or `Restarting` status.

If any service is crash-looping, check `docker compose logs <service>` before running full test cases.

---

## Test Cases

### 1. Containers start and stay up

1. Run: `docker compose -f docker-compose.tee-dev.yml up --build --detach`
2. Wait 15 seconds
3. Run: `docker compose -f docker-compose.tee-dev.yml ps`
4. **Expected:** All 4 services show `Up` status. No `Exit 1` or `Restarting` entries.

---

### 2. Miners emit epoch log lines

1. With containers running, wait at least 60 seconds after startup.
2. Run: `docker compose -f docker-compose.tee-dev.yml logs miner-1 | grep "epoch=" | tail -5`
3. **Expected:** At least 3 lines containing `epoch=N` with incrementing epoch numbers, e.g.:
   ```
   [MockMiner] epoch=14781175 n=... parity=... tampered=False
   ```
4. Run: `docker compose -f docker-compose.tee-dev.yml logs miner-2 | grep "epoch=" | tail -5`
5. **Expected:** Similar lines for miner-2.

---

### 3. Validator scores both miners at 0.50

1. With containers running, wait at least 380 seconds (≈6.3 minutes) from startup.
2. Run: `docker compose -f docker-compose.tee-dev.yml logs validator | grep "\[Validator\]" | tail -10`
3. **Expected:** Lines of the form:
   ```
   [Validator] peer=12D3KooW... epoch=N score=0.50 correct=True
   ```
   Must appear for **both** `miner-1` and `miner-2` peer IDs.
4. Verify no `score=0.00` lines persist after epoch 3 (first 1–2 epochs may be 0.00 due to GossipSub cold start — expected).

---

### 4. Epoch numbers agree across miner and validator

1. Run: `docker compose -f docker-compose.tee-dev.yml logs miner-1 | grep "epoch=" | tail -3`
2. Run: `docker compose -f docker-compose.tee-dev.yml logs validator | grep "epoch=" | tail -3`
3. **Expected:** The highest epoch number in miner-1 logs and the highest epoch number in validator logs are within ±1 of each other. They should not diverge by more than 1 epoch.

---

### 5. Gossip publish health — miners are publishing

1. Run: `docker compose -f docker-compose.tee-dev.yml logs miner-1 | grep "\[GossipPub\]" | tail -5`
2. **Expected:** Lines such as:
   ```
   [GossipPub] TEE quote published epoch=N
   [GossipPub] RATLS cert published epoch=N
   [GossipPub] Work record published epoch=N
   ```
   Must appear for miner-1. No `[GossipPub] No X to publish` WARNING lines after epoch 2.

---

### 6. Validator scoring loop active

1. Run: `docker compose -f docker-compose.tee-dev.yml logs validator | grep "\[ValidatorLoop\]" | head -5`
2. **Expected:** Lines such as:
   ```
   [ValidatorLoop] Scoring epoch=N
   ```
   Must appear at least once, confirming the validator scoring loop started.

---

### 7. Shared SQLite volume functioning (no BUSY errors)

1. Run: `docker compose -f docker-compose.tee-dev.yml logs | grep -i "database is locked\|unable to open database\|OperationalError" | head -5`
2. **Expected:** No output. Zero SQLite locking errors across all 4 containers.

---

### 8. TAMPER_RATE env var active on miners

1. Run: `docker compose -f docker-compose.tee-dev.yml exec miner-1 python3 -c "import subnet.node.mock as m; print(m.TAMPER_RATE)"`
2. **Expected:** `0.001`
3. Run: `docker compose -f docker-compose.tee-dev.yml exec validator python3 -c "import subnet.node.mock as m; print(m.TAMPER_RATE)"`
4. **Expected:** `0.0`

---

### 9. Clean shutdown

1. Run: `docker compose -f docker-compose.tee-dev.yml down --volumes`
2. **Expected:** Exit code 0. All containers removed. All volumes removed. Running `docker compose -f docker-compose.tee-dev.yml ps` shows empty output.

---

## Edge Cases

### First-epoch 0.00 score is acceptable

1. Check early validator logs: `docker compose -f docker-compose.tee-dev.yml logs validator | grep "\[Validator\]" | head -5`
2. **Expected:** First 1-2 scoring lines may show `score=0.00` — this is expected GossipSub cold-start behaviour (gossip for epoch 0 may arrive before validator mesh is formed). Score must stabilise at `0.50` by epoch 3 and remain there.
3. **Not expected:** Persistent `score=0.00` after epoch 3.

### No [Validator] lines after 6 minutes

If `docker compose logs validator | grep "\[Validator\]"` is empty after 380 seconds:

1. Check validator started its scoring loop: `docker compose logs validator | grep "ValidatorLoop"`
2. Check gossip arrived: `docker compose logs validator | grep "stored"`
3. Check for `no_ratls_cert` or `no_work_record` lines in validator logs
4. Check that `miner-1` and `miner-2` containers are Up (not crashed)
5. If `[GossipPub] No X to publish` appears in miner logs, miner_loop() didn't write to DB — check T01/T02 wiring

### Bootnode crashes after startup

The bootnode is a bootstrap-only node and has no epoch loop. It sets `reset_db=True` on start. If it crashes after the other containers connect, the network continues functioning (libp2p maintains peer connections). Only re-running `docker compose up` would re-trigger the DB reset.

---

## Failure Signals

- `sqlite3.OperationalError: database is locked` in any container log → WAL mode not applied (T01 fix)
- `unable to open database file` → Docker volume ownership is `root:root` instead of `apiuser:apiuser` (Dockerfile mkdir fix)
- `Failed to connect to any bootstrap nodes` crash loop → `_resolve_dns_multiaddr` not applied or not resolving `/dns4/bootnode` correctly
- `TypeError: BaseNodeScoring.__init__() missing 3 required positional arguments` → MockNodeScoring called without `db/subnet_id/config`
- `[Validator] peer=PeerInfo(peer_id=...` (full object string, not 16-char ID) → `hasattr(peer_info, "peer_id")` fix not applied
- All scores are `0.00` after epoch 5 → gossip not arriving (check GossipReceiver subscription and handler logs)
- `[GossipPub] No X to publish epoch=N` after epoch 2 → miner_loop() ran but didn't write to DB; check MockNodeProtocol wiring

---

## Requirements Proved By This UAT

- R005 (multi-node) — 4-container live run with scoring confirms multi-node operation
- R006 (real P2P DHT/gossip) — GossipSub proven as cross-container transport; work records travel from miner container to validator container
- R007 (live epoch timing) — Epoch numbers agree within ±1 across containers; epoch loop runs on shared network time
- R022 (integration tests) — The deferred "2-epoch docker compose cycle (Layer 2)" item in R022 is now exercised

## Not Proven By This UAT

- Tamper detection in live environment (TAMPER_RATE=1.0 → overwatch + validator flagging bad epochs) — deferred to S02
- `docker compose restart miner-1` recovery within one epoch — deferred to S03
- Structured JSON log output for `jq` pipelines — deferred to S03
- Real TEE hardware (TDX/SEV-SNP) — always deferred to mainnet; mock mode only

## Notes for Tester

- The wait of 380 seconds (≈6.3 minutes) is conservative. In practice, scoring lines appeared at epoch 14781175 which was roughly 5 epochs after startup. You can check logs earlier and see if scoring has started; the 380s wait is the worst-case timeout.
- Epoch numbers in this demo are large integers (e.g. `14781175`) because they reflect a real on-chain epoch counter in the mock chain, not a counter starting at 0.
- The 1 skipped test (`test_gramine_*`) is a pre-existing skip requiring Gramine hardware. It is not introduced by this slice and does not affect the demo.
- If you run `TAMPER_RATE=1.0` as a manual experiment during S01 UAT, expect `score=0.00` and `correct=False` in validator logs from epoch 3 onward. Full S02 UAT will formalise this verification.
