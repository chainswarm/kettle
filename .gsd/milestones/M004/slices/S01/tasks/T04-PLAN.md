---
estimated_steps: 5
estimated_files: 1
---

# T04: Docker compose integration and end-to-end demo verification

**Slice:** S01 — Multi-node epoch loop
**Milestone:** M004

## Description

Code changes from T01–T03 are wired but not yet usable — all containers still open separate `mock_hypertensor.db` files (each container-local), so the validator's mock chain is empty when it looks for miners to score. This task:

1. Adds a shared `mock-chain` Docker named volume so all containers mount the same SQLite file
2. Sets `MOCK_CHAIN_DB_PATH` env var so `MockDatabase()` opens the shared file
3. Overrides the Dockerfile health check (which hits a REST API that `run_node.py` doesn't serve)
4. Sets `TAMPER_RATE` per-service
5. Runs the full demo and confirms `[Validator] peer=... score=0.50` lines appear

**Why the bootnode resets the DB:** `run_node.py` passes `reset_db=True if not args.bootstrap else False`. Bootnode has no `--bootstrap` arg → `reset_db=True`. This means bootnode wipes the shared DB at startup. Validators/miners start after bootnode (via `depends_on`) and register themselves with `INSERT OR REPLACE` — idempotent. This is correct and intentional.

**Health check override:** The Dockerfile contains `HEALTHCHECK CMD curl http://localhost:8000/api/v1.0/health` which fails for `run_node.py` nodes (no REST server). Override it per-service in docker-compose with `healthcheck: test: ["CMD", "true"]` to prevent Docker from marking containers as unhealthy.

## Steps

1. Open `docker-compose.tee-dev.yml`. At the bottom `volumes:` section, add `mock-chain:` alongside the existing `tee-validator-db:`, `tee-miner1-db:`, `tee-miner2-db:` entries.

2. **All four services** (`bootnode`, `validator`, `miner-1`, `miner-2`) need:
   - Under `volumes:`, add: `- mock-chain:/app/mock_chain`
   - Under `environment:`, add: `MOCK_CHAIN_DB_PATH: "/app/mock_chain/mock_hypertensor.db"`
   - Add `healthcheck: test: ["CMD", "true"]` (or `disable: true` — the `true` form is more portable across Docker versions)

3. **`miner-1` and `miner-2`** environment: add `TAMPER_RATE: "0.001"` (honest, ~1/1000 tamper rate).

4. **`validator`** environment: add `TAMPER_RATE: "0.0"` (validator's miner_loop should never tamper).

5. **`bootnode`** needs no `TAMPER_RATE` (bootstrap nodes don't run miner_loop).

6. Verify all referenced `.key` files exist at repo root:
   ```bash
   ls bootnode.key alith.key baltathar.key charleth.key
   ```
   If any are missing, the build will fail with a volume mount error.

7. Run the full end-to-end verification sequence:
   ```bash
   # Tear down any existing stack
   docker compose -f docker-compose.tee-dev.yml down --volumes 2>/dev/null || true

   # Build and start
   docker compose -f docker-compose.tee-dev.yml up --build --detach

   # Wait for 3+ epochs (epoch = 20 blocks × 6s = 120s; 3 epochs = 360s; add 20s buffer)
   sleep 380

   # Verify validator scoring output
   docker compose -f docker-compose.tee-dev.yml logs validator | grep "\[Validator\]"
   # Expected: lines like "[Validator] peer=12D3KooW... epoch=2 score=0.50 correct=True"

   # Verify miner loop running
   docker compose -f docker-compose.tee-dev.yml logs miner-1 | grep "epoch=" | tail -5
   docker compose -f docker-compose.tee-dev.yml logs validator | grep "epoch=" | tail -5
   # Epoch numbers must agree within ±1

   # Verify unit tests still pass
   python3 -m pytest tests/ -q --tb=short

   # Clean shutdown
   docker compose -f docker-compose.tee-dev.yml down --volumes
   ```

8. If validator logs show `no_ratls_cert` or `no_work_record` for all peers after 3 epochs, debug by checking:
   - `docker compose logs miner-1 | grep "\[GossipPub\]"` — confirms gossip publish attempted
   - `docker compose logs validator | grep "stored"` — confirms gossip arrived at validator receiver
   - `docker compose logs validator | grep WARN` — surfaces any parse failures in T02 handlers

## Must-Haves

- [ ] `docker-compose.tee-dev.yml` has `mock-chain` named volume declared and mounted in all 4 services
- [ ] All services have `MOCK_CHAIN_DB_PATH: "/app/mock_chain/mock_hypertensor.db"` env var
- [ ] Health check is overridden per-service so containers stay healthy
- [ ] `docker compose up --build --detach` succeeds (all containers start without crash-looping)
- [ ] After ~380s: `docker compose logs validator | grep "\[Validator\]"` shows `score=0.50` for at least one miner
- [ ] Epoch numbers in miner and validator logs agree within ±1
- [ ] `docker compose down --volumes` completes cleanly (exit 0)
- [ ] `python3 -m pytest tests/ -q --tb=short` still passes

## Verification

```bash
# Core demo check:
docker compose -f docker-compose.tee-dev.yml logs validator | grep "\[Validator\]" | grep "score="
# Must return at least one line per miner

# Epoch agreement:
diff <(docker compose -f docker-compose.tee-dev.yml logs miner-1 | grep "epoch=" | tail -1 | grep -oP 'epoch=\K[0-9]+') \
     <(docker compose -f docker-compose.tee-dev.yml logs validator | grep "epoch=" | tail -1 | grep -oP 'epoch=\K[0-9]+')
# Acceptable: empty diff or ±1

# Unit tests:
python3 -m pytest tests/ -q --tb=short
```

## Observability Impact

- Signals added/changed: No new code signals; this task wires existing signals from T01–T03 into a runnable multi-container stack
- How a future agent inspects this: `docker compose -f docker-compose.tee-dev.yml logs <service>` — all scoring, gossip, and epoch signals from T03 are visible here
- Failure state exposed: Container crash-loops visible via `docker compose ps`; `docker compose logs <service> | grep -i error` surfaces runtime failures

## Inputs

- `docker-compose.tee-dev.yml` — existing skeleton with bootnode + validator + 2 miners; no named volume for mock chain yet
- T01 completed: `MockDatabase()` reads `MOCK_CHAIN_DB_PATH` env var; WAL mode applied
- T02 completed: `GossipReceiver` handles TEE/RATLS/work gossip topics
- T03 completed: `_miner_epoch_loop` and `_validator_scoring_loop` are in `server.py` and started for non-bootstrap nodes
- `bootnode.key`, `alith.key`, `baltathar.key`, `charleth.key` present at repo root (already referenced in existing docker-compose)

## Expected Output

- `docker-compose.tee-dev.yml` — updated with `mock-chain` volume, `MOCK_CHAIN_DB_PATH` env vars, `TAMPER_RATE` per-service, health check overrides
- Running `docker compose up --build` → wait 380s → `logs validator | grep "\[Validator\]"` shows scoring lines
