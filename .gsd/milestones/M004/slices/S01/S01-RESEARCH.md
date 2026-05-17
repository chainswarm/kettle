# Multi-node epoch loop — Research

**Date:** 2026-03-17

## Summary

S01 needs to bridge three separate gaps so that `docker compose -f docker-compose.tee-dev.yml up --build` produces a live multi-node epoch loop with validator scores visible in logs:

1. **Miner/validator work loop is not wired into `server.py`** — `MockNodeProtocol.miner_loop()` and `validator_call()` exist and are tested, but `Server` never calls them. The server runs heartbeats, TEE quote publishing, and consensus scoring, but the mock "odd/even parity" work loop is completely disconnected.

2. **Work records don't cross container boundaries** — `nmap_set`/`nmap_get` write to each node's *local* RocksDB. The validator's `DcapVerifier` and `MockNodeProtocol.validator_call()` both read from the validator's local RocksDB. Miners' work records never arrive there.

3. **Mock chain state (`mock_hypertensor.db`) is container-local** — `LocalMockHypertensor` opens a SQLite file at `./mock_hypertensor.db`. Each container gets its own copy, so the validator's mock chain only knows about itself. It cannot score miner-1 or miner-2 because they don't exist in its node registry.

**Recommended approach:** GossipSub for work-record propagation (same pattern as heartbeats — already proven to work cross-container) + shared SQLite volume (WAL mode) for mock chain state + two new coroutines (`_miner_epoch_loop`, `_validator_scoring_loop`) added to `server.py`'s trio nursery.

GossipSub is preferred over libp2p KadDHT `put_value`/`get_value` for work records because heartbeats already prove it works end-to-end. KadDHT routing tables are populated and routes converge, but the actual `put_value`/`get_value` API has not been exercised in this codebase; wiring it in S01 adds an unknown integration risk.

## Recommendation

Build in this order, verifying each stage before moving on:

1. Fix mock chain state (WAL + shared volume + expose `insert_mock_subnet_nodes` in CLI) so all containers see the same node registry.
2. Gossip work records from miners (TEE quotes are already gossipped via `_tee_publish_loop` — wait, see note below — work *records*, RA-TLS certs need separate gossip).
3. Add `_miner_epoch_loop` and `_validator_scoring_loop` coroutines to `server.py`.
4. Make `TAMPER_RATE` env-var driven.
5. Update `docker-compose.tee-dev.yml` to wire everything together.

**Note on TEE quotes and RA-TLS certs:** The existing `_tee_publish_loop` in `server.py` writes TEE quotes to the node's *local* RocksDB only. For the validator to verify them, these also need to cross the container boundary. GossipSub is the lowest-risk transport for this.

## Implementation Landscape

### Key Files

- `subnet/node/mock.py` — `MockNodeProtocol` with `miner_loop()` / `validator_call()` / `MockOverwatchVerifier`. `TAMPER_RATE` is a module-level float hardcoded to `1/1000`. Needs to read from `os.getenv("TAMPER_RATE", "0.001")`. The `_WORK_TOPIC = "mock_work"` constant names the DHT namespace already.
- `subnet/server/server.py` — Needs two new nursery tasks: `_miner_epoch_loop(protocol, hypertensor, subnet_id, termination_event)` and `_validator_scoring_loop(protocol, hypertensor, subnet_id, subnet_info_tracker, termination_event)`. The existing `_tee_publish_loop` (already in this file) is the pattern to follow for an epoch-driven loop. The server already imports `from subnet.tee.config import get_tee_config`.
- `subnet/cli/run_node.py` — `LocalMockHypertensor` is instantiated here. `insert_mock_subnet_nodes` parameter exists on `LocalMockHypertensor.__init__` but is hardcoded to `(False, 0)`. Needs a new `--insert_mock_subnet_nodes INT` CLI arg; when set, also needs all `.key` files mounted (or use shared volume instead — see below). Also needs to pass the `MockNodeProtocol` class (or a protocol factory) to `Server`.
- `subnet/hypertensor/mock/mock_db.py` — `MockDatabase._connect()` opens SQLite without WAL mode. Multi-process concurrent access (4 Docker containers sharing one file) will deadlock or corrupt without `PRAGMA journal_mode=WAL`. Add `self.conn.execute("PRAGMA journal_mode=WAL")` immediately after `sqlite3.connect(...)`.
- `subnet/utils/gossipsub/gossip_receiver.py` — `GossipReceiver._handle_message()` has handlers only for `HEARTBEAT_TOPIC`. Needs handlers for `TEE_QUOTE_TOPIC`, `RATLS_CERT_TOPIC`, and `_WORK_TOPIC`. Each handler follows the same pattern as `_handle_heartbeat`: deserialise → dedup → `nmap_set` to local RocksDB using the same key format.
- `docker-compose.tee-dev.yml` — Needs a shared named volume for `mock_hypertensor.db` (mount at `/app/mock_hypertensor.db` in each container). Needs `TAMPER_RATE=0.001` on miner-1 (honest) and optionally higher on miner-2 (for later S02 demo). Needs all `.key` files mounted in all containers so `insert_mock_subnet_nodes` can find them (or skip this and rely on shared DB self-registration). The Docker `HEALTHCHECK` in the `Dockerfile` hits `http://localhost:8000/api/v1.0/health` (the REST API), which isn't served by `run_node.py`; override it or set `HEALTHCHECK NONE` in the docker-compose service definition.
- `Dockerfile` — ENTRYPOINT `["python", "-m"]` + CMD `["subnet.api.main"]`; docker-compose overrides CMD correctly with `command:`. No change needed to Dockerfile itself, but the health check embedded in it needs to be overridden per-service in docker-compose.

### Mock Chain State Strategy (Critical Decision)

**Recommended: shared SQLite volume + self-registration**

Add a named volume `mock-chain` to docker-compose and mount it at the same path in all containers:
```yaml
volumes:
  mock-chain:

services:
  bootnode:
    volumes:
      - mock-chain:/app/mock_chain
    environment:
      MOCK_CHAIN_DB_PATH: /app/mock_chain/mock_hypertensor.db
```

Then expose `MOCK_CHAIN_DB_PATH` as an env var that `MockDatabase.__init__` reads as its `db_path`. The bootnode starts first (`depends_on` is already set), resets the DB, registers itself. Miners/validators start later, find the existing DB (no reset since they have bootstrap), and register themselves. With WAL mode, concurrent writes are safe.

This works because:
- `reset_db=True if not args.bootstrap else False` — only the bootnode resets; others append
- `insert_subnet_node` uses `INSERT OR REPLACE` — idempotent
- All nodes poll `get_min_class_subnet_nodes_formatted` at epoch boundaries, after all others have had time to register

### Gossip Protocol for Work Records

Miners need to publish three things per epoch that the validator needs:
1. TEE quote → `TEE_QUOTE_TOPIC`
2. RA-TLS cert → `RATLS_CERT_TOPIC`
3. Output envelope (the parity work record) → `_WORK_TOPIC = "mock_work"`

**Pattern** (follow heartbeat exactly):
- Define topic constants; gossip receiver subscribes in its `topics` list
- Miner calls `pubsub.publish(topic, value_bytes)` after writing to local RocksDB
- Gossip receiver on validator receives and calls `db.nmap_set(topic, key, value_bytes)`
- `validator_call()` reads from local RocksDB (unchanged — already works in unit tests via shared DB)

The miner loop in `mock.py` already writes to `self.db.nmap_set(...)`. The gossip step is an additional `await pubsub.publish(...)` call after each `nmap_set`. The server needs to pass `pubsub` to the protocol instance.

### New Coroutines in `server.py`

**`_miner_epoch_loop`** (added to nursery when not is_bootstrap):
```
similar to _tee_publish_loop:
  - poll epoch change
  - on new epoch: await protocol.miner_loop(epoch)
  - gossip outputs over pubsub
  - sleep with move_on_after
```

**`_validator_scoring_loop`** (added to nursery when not is_bootstrap):
```
- wait for epoch boundary (offset from miner loop by ~10s to allow miners to publish first)
- for each peer_id in hypertensor.get_min_class_subnet_nodes_formatted(...):
    result = await protocol.validator_call(peer_id, epoch-1)
    score = await scoring.score_peer(result, epoch-1)
    logger.info("[Validator] peer=%s epoch=%d score=%.2f ...", ...)
```

The validator scoring loop is independent from `Consensus.get_scores()`. It runs as an observability/demo layer. The existing consensus scoring (heartbeat + TEE) continues unchanged. This ensures existing Layer 1 tests keep passing.

### Build Order

1. **`mock_db.py`** — WAL mode (1 line) + env-var DB path. Unblocks shared chain state.
2. **`mock.py`** — `TAMPER_RATE = float(os.getenv("TAMPER_RATE", "0.001"))` (1 line). Isolated.
3. **`gossip_receiver.py`** — Add handlers for TEE_QUOTE_TOPIC, RATLS_CERT_TOPIC, mock_work. Pattern is identical to heartbeat handler. Unblocks cross-container work record propagation.
4. **`server.py`** — Add `_miner_epoch_loop` and `_validator_scoring_loop`; pass pubsub to protocol; instantiate `MockNodeProtocol`. Wires everything.
5. **`run_node.py`** — Add `MOCK_CHAIN_DB_PATH` env var read + CLI args for mock chain path.
6. **`docker-compose.tee-dev.yml`** — Add shared volume, env vars, health check overrides, all key file mounts.

### Verification Approach

```bash
# Bring up the stack
docker compose -f docker-compose.tee-dev.yml up --build --detach

# Wait 2+ epochs (epoch = 20 blocks × 6s = 120s)
sleep 260

# Validator logs must show scoring lines
docker compose -f docker-compose.tee-dev.yml logs validator | grep -E "\[Validator\]|score=|epoch="

# Miner logs must show miner_loop execution
docker compose -f docker-compose.tee-dev.yml logs miner-1 | grep -E "\[MockMiner\]|epoch=|published"

# Epoch numbers must agree (compare last epoch in each)
docker compose -f docker-compose.tee-dev.yml logs miner-1 | grep "epoch=" | tail -3
docker compose -f docker-compose.tee-dev.yml logs miner-2 | grep "epoch=" | tail -3
docker compose -f docker-compose.tee-dev.yml logs validator | grep "epoch=" | tail -3

# Unit tests must still pass
python3 -m pytest tests/ -q --tb=short   # target: 181 passed in < 10s

# Clean shutdown
docker compose -f docker-compose.tee-dev.yml down --volumes
```

**Success signal**: Validator logs show `[Validator] peer=<miner-1-peer-id> epoch=N score=0.50` at least once. Epoch numbers in miner and validator logs agree (within ±1 for in-progress epochs).

## Constraints

- `EPOCH_LENGTH = 20` blocks × `BLOCK_SECS = 6s` = **120 seconds per epoch**. Two epochs must elapse (≥240s) before the validator has scored a full epoch. Build and convergence time means the first score may appear at epoch ~3 (≥360s after `up`).
- `LocalMockHypertensor` uses `get_block_number() = int(time.time() // 6)` — purely wall-clock. All containers share the host clock via Docker, so epoch numbers will agree with no additional synchronisation.
- The gossip mesh (GossipSub) requires ≥3 peers subscribed to a topic before messages route reliably (degree=3 in server.py). With only 4 nodes total (bootnode doesn't subscribe to content topics), the mesh is exactly at minimum. Boosting `degree_low` to 1 or ensuring all non-bootstrap nodes subscribe to the same topics before publishing will prevent dropped messages.
- `RocksDB` opens per-container at `/tmp/<random>` or `/app/db`. The shared SQLite volume is separate from RocksDB — no conflict.
- `MockNodeProtocol.validator_call()` calls `self.db.nmap_get(RATLS_CERT_TOPIC, ...)` synchronously expecting data published by the miner in the same epoch. Timing window: validator loop should run after enough time for gossip to arrive (add `await trio.sleep(15)` offset at start of validator scoring loop).

## Common Pitfalls

- **Bootnode reset race** — `reset_db=True` for bootnode runs at container start. Validators/miners also start shortly after (depends_on only waits for container launch, not readiness). If validator starts before bootnode writes the DB, it may open a newly created empty file. Fix: add a `healthcheck` or simple retry loop in `LocalMockHypertensor.__init__` when bootstrapping with an existing DB.
- **GossipSub topic subscription timing** — Nodes must subscribe to a topic before publishing to it. The gossip receiver subscribes in `run()`. If miner_loop fires before gossip receiver has subscribed on the validator, the message is lost. The initial `await trio.sleep(1)` in `publish_heartbeat_loop` is the pattern; add a larger initial delay (e.g., 30s) to `_miner_epoch_loop` to allow all nodes to form the mesh.
- **SQLite WAL mode on shared volume** — Docker named volumes with SQLite WAL mode work correctly, but the WAL file (`mock_hypertensor.db-wal`) must be on the same volume as the main file. The named volume handles this automatically.
- **`insert_subnet_node` with `INSERT OR REPLACE` overwrites node data** — If a node restarts, it calls `insert_subnet_node` again, which is idempotent. Classification `start_epoch` is set to current epoch at registration time; this means a restarted node will have a later `start_epoch` and may miss the current epoch's scoring window.
- **Validator scoring loop vs. consensus scoring** — `Consensus.get_scores()` runs after every epoch and calls `hypertensor.get_min_class_subnet_nodes_formatted(...)`. If the validator scoring loop also runs at epoch boundaries, they must not interfere. Keep them as independent nursery tasks; `Consensus` is read-only from the mock DB perspective.
- **`TAMPER_RATE` as float env var** — `float(os.getenv("TAMPER_RATE", "0.001"))` raises `ValueError` if set to an invalid string. Add a try/except fallback.

## Open Risks

- **GossipSub reliability at 4-node minimum** — The default GossipSub degree of 3 with degree_high=4 means the mesh is at its exact lower bound. If the bootnode doesn't participate in content topics (it has `is_bootstrap=True` so the heartbeat loop doesn't start), only 3 non-bootstrap nodes subscribe. Any single connection drop causes message loss. May need to lower `degree` and `degree_low` in server.py's GossipSub config, or enable the bootnode to subscribe to content topics.
- **SQLite concurrent writes under stress** — WAL mode handles concurrent reads + single writer. With 4 processes writing at epoch boundaries (all at once), SQLite will serialize writes gracefully, but `SQLITE_BUSY` retries may cause delays. The mock chain code doesn't have retry logic. If writes happen infrequently (once per epoch boundary, staggered), this is unlikely to be a problem in practice.
- **MockNodeProtocol not connected to a libp2p host** — In unit tests, `MockNodeProtocol` is instantiated without a real host (`p.host = None`). In `server.py`, it will be instantiated with a real host. The protocol's `miner_loop` does not use `self.host`, so this is safe for S01. Future protocol implementations that open streams will need proper host wiring.
