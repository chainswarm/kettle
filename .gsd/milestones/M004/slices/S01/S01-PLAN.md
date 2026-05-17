# S01: Multi-node epoch loop

**Goal:** `docker compose -f docker-compose.tee-dev.yml up --build` brings up bootnode + 2 miners + validator; miners publish work records each epoch over GossipSub; validator reads, verifies, and scores them; `docker compose logs validator` shows `[Validator] peer=... epoch=N score=0.50` lines.
**Demo:** `docker compose -f docker-compose.tee-dev.yml up --build --detach` → wait ~3 epochs (≈360s) → `docker compose -f docker-compose.tee-dev.yml logs validator | grep "\[Validator\]"` outputs scoring lines with `score=0.50` for both miners.

## Must-Haves

- `docker compose -f docker-compose.tee-dev.yml up --build` succeeds without errors
- `docker compose logs validator` shows `[Validator] peer=<miner-peer-id> epoch=N score=0.50` at least once per miner after 3 epochs
- `docker compose logs miner-1` shows `[MockMiner] epoch=N n=... parity=...` lines
- Epoch numbers in miner and validator logs agree (within ±1)
- `python3 -m pytest tests/ -q --tb=short` still passes (182 tests, < 10s)
- `docker compose -f docker-compose.tee-dev.yml down --volumes` is clean

## Proof Level

- This slice proves: integration
- Real runtime required: yes (Docker multi-node network)
- Human/UAT required: no

## Verification

- `python3 -m pytest tests/ -q --tb=short` — 182 tests must pass before and after all code changes
- After `docker compose -f docker-compose.tee-dev.yml up --build --detach` and `sleep 380`:
  ```bash
  docker compose -f docker-compose.tee-dev.yml logs validator | grep "\[Validator\]" | grep "score="
  # Must show at least one line per miner with score=0.50
  docker compose -f docker-compose.tee-dev.yml logs miner-1 | grep "epoch=" | tail -3
  docker compose -f docker-compose.tee-dev.yml logs validator | grep "epoch=" | tail -3
  # Epoch numbers must agree within ±1
  ```
- `docker compose -f docker-compose.tee-dev.yml down --volumes` exits 0 with no orphaned containers

## Observability / Diagnostics

- Runtime signals:
  - `[MockMiner] epoch=N n=... parity=... tampered=False` — miner loop running
  - `[MockMiner] published ratls_cert epoch=N peer=...` — cert published
  - `[MockValidator] ratls_cert ok epoch=N peer=... score=0.5` — cert verified
  - `[Validator] peer=... epoch=N score=0.50` — scoring complete
  - `[GossipPub] TEE/RATLS/work published epoch=N` — gossip publish success
- Inspection surfaces:
  - `docker compose logs <service>` — per-container structured logs
  - `docker compose logs validator | grep -E "\[Validator\]|error|WARN"` — scoring health
  - `docker compose ps` — container health status
- Failure visibility:
  - `no_ratls_cert` or `no_work_record` in validator logs → gossip not arriving (check T02 handler topics)
  - `tee_rejected` in validator logs → mock TEE config issue (check MOCK_TEE env var)
  - No `[Validator]` lines after 3 epochs → validator scoring loop not starting (check T03 wiring)
  - SQLite BUSY errors in logs → WAL mode not applied (check T01)
- Redaction constraints: none (mock keys, no real secrets)

## Integration Closure

- Upstream surfaces consumed:
  - `subnet/node/mock.py` — `MockNodeProtocol.miner_loop()` / `validator_call()` / `MockNodeScoring`
  - `subnet/utils/gossipsub/gossip_receiver.py` — `GossipReceiver` (heartbeat handler pattern)
  - `subnet/server/server.py` — `_tee_publish_loop` pattern + nursery structure
  - `subnet/hypertensor/mock/mock_db.py` — `MockDatabase` (shared SQLite)
  - `docker-compose.tee-dev.yml` — existing skeleton with bootnode + validator + 2 miners
- New wiring introduced in this slice:
  - `_miner_epoch_loop` and `_validator_scoring_loop` nursery tasks in `Server.run()`
  - `MockNodeProtocol` instantiated and registered inside `Server.run()` for non-bootstrap nodes
  - GossipSub publish calls in `_miner_epoch_loop` (TEE_QUOTE_TOPIC, RATLS_CERT_TOPIC, mock_work)
  - GossipSub receive handlers for all three topics in `GossipReceiver`
  - Shared `mock-chain` Docker volume mounting `mock_hypertensor.db` at same path in all containers
  - `MOCK_CHAIN_DB_PATH` env var driving `MockDatabase` path selection
- What remains before the milestone is truly usable end-to-end: S02 (live tamper detection with TAMPER_RATE=1.0), S03 (restart recovery + structured JSON logs)

## Tasks

- [x] **T01: Fix MockDatabase WAL mode, env-var DB path, and env-var TAMPER_RATE** `est:30m`
  - Why: Shared SQLite across 4 Docker containers deadlocks without WAL mode; `MOCK_CHAIN_DB_PATH` env var is the mechanism for shared volume; env-var `TAMPER_RATE` enables per-container fault injection rates.
  - Files: `subnet/hypertensor/mock/mock_db.py`, `subnet/node/mock.py`
  - Do: In `mock_db.py._connect()`, add `self.conn.execute("PRAGMA journal_mode=WAL")` immediately after `sqlite3.connect(...)`. Change `MockDatabase.__init__` signature to `def __init__(self, db_path: str | None = None)` and derive the effective path as `os.getenv("MOCK_CHAIN_DB_PATH", DB_FILE) if db_path is None else db_path`. In `mock.py`, replace `TAMPER_RATE = 1 / 1000` with a try/except env-var read: `try: TAMPER_RATE = float(os.getenv("TAMPER_RATE", "0.001")); except (ValueError, TypeError): TAMPER_RATE = 0.001`. Add `import os` to both files if not present.
  - Verify: `python3 -m pytest tests/ -q --tb=short` — 182 tests must still pass. Also run `MOCK_CHAIN_DB_PATH=/tmp/test_wal.db python3 -c "from subnet.hypertensor.mock.mock_db import MockDatabase; db = MockDatabase(); print(db.db_path)"` — must print `/tmp/test_wal.db`.
  - Done when: Tests pass, `MockDatabase()` with no args uses env var path (defaults to `mock_hypertensor.db`), WAL pragma applied on connect.

- [x] **T02: Add GossipSub handlers for TEE quotes, RA-TLS certs, and work records** `est:1h`
  - Why: Work records written to a miner's local RocksDB never reach the validator's container. GossipSub is the proven cross-container transport (heartbeats already use it). The validator's `validator_call()` reads from local RocksDB — so gossip receivers must write arriving records into local RocksDB using the exact nmap key format `{epoch}:{peer_id}`.
  - Files: `subnet/utils/gossipsub/gossip_receiver.py`, `subnet/server/server.py`
  - Do:
    1. In `gossip_receiver.py`, add `_seen_tee_quotes: set[str]`, `_seen_ratls_certs: set[str]`, `_seen_work_records: set[str]` dedup sets (initialised in `__init__` alongside `_seen_heartbeats`).
    2. Add handler `_handle_tee_quote(message, from_peer)`: parse `TeeQuote.from_bytes(message.data)`, epoch = `quote.nonce`, key = `f"{epoch}:{from_peer}"`, dedup check on `_seen_tee_quotes`, then `self.db.nmap_set(TEE_QUOTE_TOPIC, key, message.data)`. Import `TeeQuote` from `subnet.tee.quote` inside the method.
    3. Add handler `_handle_ratls_cert(message, from_peer)`: parse JSON `json.loads(message.data.decode())`, epoch = `data["epoch"]`, cert_bytes = `base64.b64decode(data["cert"])`, key = `f"{epoch}:{from_peer}"`, dedup, then `self.db.nmap_set(RATLS_CERT_TOPIC, key, cert_bytes)`. Import `json`, `base64` at top of file.
    4. Add handler `_handle_work_record(message, from_peer)`: parse `OutputEnvelope.from_bytes(message.data)`, decode inner JSON to get `epoch`, key = `f"{epoch}:{from_peer}"`, dedup, then `self.db.nmap_set(_WORK_TOPIC, key, message.data)`. Import `OutputEnvelope` from `subnet.tee.ratls.envelope` and `_WORK_TOPIC` from `subnet.node.mock` inside the method.
    5. In `_handle_message`, add `elif topic == TEE_QUOTE_TOPIC:`, `elif topic == RATLS_CERT_TOPIC:`, `elif topic == _WORK_TOPIC:` dispatch cases. Import the topic constants at top: `from subnet.tee.quote import TEE_QUOTE_TOPIC, RATLS_CERT_TOPIC` and `from subnet.node.mock import _WORK_TOPIC`.
    6. In `server.py`, update the `GossipReceiver(topics=[HEARTBEAT_TOPIC])` instantiation to `topics=[HEARTBEAT_TOPIC, TEE_QUOTE_TOPIC, RATLS_CERT_TOPIC, _WORK_TOPIC]`. Add the necessary imports at the top of `server.py`: `from subnet.tee.quote import TEE_QUOTE_TOPIC, RATLS_CERT_TOPIC` and `from subnet.node.mock import _WORK_TOPIC`.
  - Verify: `python3 -m pytest tests/ -q --tb=short` — 182 tests must still pass. Optionally: `python3 -c "from subnet.utils.gossipsub.gossip_receiver import GossipReceiver; print('import ok')"`.
  - Done when: Tests pass; `GossipReceiver` subscribes to 4 topics; `_handle_message` dispatches all three new topic types; each handler stores to RocksDB with `{epoch}:{peer_id}` key format.

- [x] **T03: Wire miner and validator epoch loops into server.py** `est:1.5h`
  - Why: `MockNodeProtocol.miner_loop()` and `validator_call()` exist and pass unit tests but are never called by `Server`. This task instantiates the protocol and adds two nursery tasks that drive the mock epoch loop, making scoring appear in validator logs.
  - Files: `subnet/server/server.py`
  - Do:
    1. Add imports at top of `server.py`: `from subnet.node.mock import MockNodeProtocol, MockNodeScoring, _WORK_TOPIC` and `from subnet.tee.quote import TEE_QUOTE_TOPIC, RATLS_CERT_TOPIC, dht_key as tee_dht_key` and `import base64, json as _json`.
    2. Inside `Server.run()`, after `peer_id_str = host.get_id().to_base58()` (near the TEE publisher setup), instantiate the protocol: `protocol = MockNodeProtocol(host=host, peer_id=peer_id_str, subnet_info_tracker=subnet_info_tracker, mode="worker", db=self.db)` and call `await protocol.register_handlers()`.
    3. In the `if not self.is_bootstrap:` block (alongside the existing `_tee_publish_loop` start), add: `nursery.start_soon(_miner_epoch_loop, protocol, pubsub, self.db, peer_id_str, self.hypertensor, self.subnet_id, termination_event)` and `nursery.start_soon(_validator_scoring_loop, protocol, self.db, peer_id_str, self.hypertensor, self.subnet_id, termination_event)`.
    4. Implement `_miner_epoch_loop` as a module-level async function (alongside `_tee_publish_loop`). Pattern mirrors `_tee_publish_loop`. On each new epoch: call `await protocol.miner_loop(epoch)`, then read and gossip the three records from local DB:
       - TEE quote: `raw = self.db.nmap_get(TEE_QUOTE_TOPIC, tee_dht_key(peer_id, epoch))` → `await pubsub.publish(TEE_QUOTE_TOPIC, raw)` (raw bytes)
       - RATLS cert: `cert = db.nmap_get(RATLS_CERT_TOPIC, f"{epoch}:{peer_id}")` → wrap as `_json.dumps({"epoch": epoch, "cert": base64.b64encode(cert).decode()}).encode()` → `await pubsub.publish(RATLS_CERT_TOPIC, payload)`
       - Work record: `raw = db.nmap_get(_WORK_TOPIC, f"{epoch}:{peer_id}")` → `await pubsub.publish(_WORK_TOPIC, raw)`
       - Skip publish if any value is None (log warning). Use `move_on_after(5)` sleep between poll iterations.
    5. Implement `_validator_scoring_loop` as a module-level async function. On first call, sleep 30s to allow mesh formation and miner gossip to arrive. Then poll for epoch changes. On each new epoch `E`, if `E >= 1`, iterate over `hypertensor.get_min_class_subnet_nodes_formatted(subnet_id, E-1, SubnetNodeClass.Validator)` and for each peer with `peer_id != self_peer_id`: call `await protocol.validator_call(peer_id=node.peer_info["peer_id"], epoch=E-1)`, then `await MockNodeScoring().score_peer(result, E-1)`, then log `logger.info("[Validator] peer=%s epoch=%d score=%.2f correct=%s", peer_id[:16], E-1, peer_score.score, result.metrics.get("correct", "?"))`. Import `SubnetNodeClass` from `subnet.hypertensor.chain_functions`.
    6. Both loops should catch and log all non-Cancelled exceptions (never crash the nursery).
  - Verify: `python3 -m pytest tests/ -q --tb=short` — 182 tests must still pass. Import check: `python3 -c "from subnet.server.server import Server, _miner_epoch_loop, _validator_scoring_loop; print('ok')"`.
  - Done when: Tests pass; `_miner_epoch_loop` and `_validator_scoring_loop` are importable from `server.py`; `Server` instantiates `MockNodeProtocol` and starts both loops for non-bootstrap nodes.

- [x] **T04: Docker compose integration and end-to-end demo verification** `est:1h`
  - Why: The code changes in T01–T03 only work together in a running multi-container environment. This task wires the shared SQLite volume, correct env vars, and health check overrides into `docker-compose.tee-dev.yml`, then runs the full demo to confirm validator scoring lines appear.
  - Files: `docker-compose.tee-dev.yml`
  - Do:
    1. Add a named volume `mock-chain:` at the bottom volumes section (alongside existing `tee-*-db` volumes).
    2. Add to all four services (`bootnode`, `validator`, `miner-1`, `miner-2`) under `volumes:`: `- mock-chain:/app/mock_chain` (read-write, not :ro).
    3. Add to all four services under `environment:`: `MOCK_CHAIN_DB_PATH: "/app/mock_chain/mock_hypertensor.db"`.
    4. Override the Dockerfile health check for each service with `healthcheck: disable: true` (the Dockerfile HEALTHCHECK hits the REST API which is not served by `run_node.py`). Alternatively add `healthcheck: test: ["CMD", "true"]` with a long interval.
    5. Set `TAMPER_RATE: "0.001"` in miner-1 and miner-2 environment (not in bootnode or validator — they don't call miner_loop).
    6. Add `TAMPER_RATE: "0.0"` in validator environment to prevent validator from injecting faults in its own miner loop (validator runs both loops but should not tamper).
    7. Ensure the `bootnode` service has `reset_db=True` semantics: it starts with `--is_bootstrap` and `reset_db=True if not args.bootstrap else False` is already the logic in `run_node.py`. Since bootnode has no `--bootstrap` arg, it resets DB. Add `depends_on: [bootnode]` with a `condition: service_started` to validator and miners to ensure DB is reset before they connect.
    8. Verify the key files are all present (`bootnode.key`, `alith.key`, `baltathar.key`, `charleth.key`) at repo root.
    9. Run full verification:
       ```bash
       docker compose -f docker-compose.tee-dev.yml down --volumes 2>/dev/null || true
       docker compose -f docker-compose.tee-dev.yml up --build --detach
       sleep 380
       docker compose -f docker-compose.tee-dev.yml logs validator | grep "\[Validator\]"
       docker compose -f docker-compose.tee-dev.yml logs miner-1 | grep "epoch=" | tail -3
       docker compose -f docker-compose.tee-dev.yml logs validator | grep "epoch=" | tail -3
       docker compose -f docker-compose.tee-dev.yml down --volumes
       ```
  - Verify: `docker compose logs validator` shows at least one `[Validator] peer=... epoch=N score=0.50` line; miner and validator epoch numbers agree within ±1; `docker compose down --volumes` exits 0.
  - Done when: The full verification sequence above passes; `python3 -m pytest tests/ -q --tb=short` still passes after all file changes.

## Files Likely Touched

- `subnet/hypertensor/mock/mock_db.py`
- `subnet/node/mock.py`
- `subnet/utils/gossipsub/gossip_receiver.py`
- `subnet/server/server.py`
- `docker-compose.tee-dev.yml`
