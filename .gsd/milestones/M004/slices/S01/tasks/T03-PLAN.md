---
estimated_steps: 6
estimated_files: 1
---

# T03: Wire miner and validator epoch loops into server.py

**Slice:** S01 — Multi-node epoch loop
**Milestone:** M004

## Description

`MockNodeProtocol.miner_loop()` and `validator_call()` pass unit tests but are never called at runtime — `Server` doesn't know they exist. This task:

1. Instantiates `MockNodeProtocol` inside `Server.run()` for non-bootstrap nodes
2. Adds `_miner_epoch_loop` — calls `protocol.miner_loop(epoch)` each epoch, then publishes the three produced records (TEE quote, RA-TLS cert, work record) over GossipSub
3. Adds `_validator_scoring_loop` — waits for peers to publish their records (~30s mesh formation + miner gossip delay), then calls `protocol.validator_call()` for each peer each epoch and logs the score

Both loops are module-level async functions that start in the nursery alongside `_tee_publish_loop`. The validator scoring loop is an independent observability layer — it does not affect `Consensus.get_scores()` (which remains unchanged).

**Key wiring constraint:** The RA-TLS cert is stored in RocksDB by `miner_loop()` as raw PEM bytes (from `server.cert_bundle.cert_pem`), but GossipSub publishes bytes. The gossip receiver (T02) expects a JSON envelope `{"epoch": N, "cert": "<b64-pem>"}`. So `_miner_epoch_loop` must wrap the cert in that envelope before publishing.

**Timing:** `_validator_scoring_loop` must wait at least 30 seconds after startup before its first poll, to allow:
- GossipSub mesh to form across 3+ nodes (degree=3 minimum)
- Miners to publish their first epoch records over gossip
- Gossip to arrive and be written to the validator's local RocksDB

## Steps

1. **Add imports at the top of `subnet/server/server.py`**:
   ```python
   import base64
   import json as _json
   from subnet.node.mock import MockNodeProtocol, MockNodeScoring, _WORK_TOPIC
   from subnet.tee.quote import TEE_QUOTE_TOPIC, RATLS_CERT_TOPIC
   from subnet.hypertensor.chain_functions import SubnetNodeClass
   ```
   Note: `TEE_QUOTE_TOPIC`, `RATLS_CERT_TOPIC`, and `_WORK_TOPIC` were already imported in T02 for the GossipReceiver topics list. The `base64` and `_json` imports are new.

2. **Instantiate and register `MockNodeProtocol`** inside `Server.run()`, in the `if not self.is_bootstrap:` block, after the `peer_id_str = host.get_id().to_base58()` line (before the TEE publisher setup):
   ```python
   # Instantiate mock node protocol
   protocol = MockNodeProtocol(
       host=host,
       peer_id=peer_id_str,
       subnet_info_tracker=subnet_info_tracker,
       mode="worker",
       db=self.db,
   )
   await protocol.register_handlers()
   scoring = MockNodeScoring()
   ```

3. **Start the epoch loop nursery tasks** in the `if not self.is_bootstrap:` block, alongside the existing `_tee_publish_loop` start:
   ```python
   nursery.start_soon(
       _miner_epoch_loop,
       protocol,
       pubsub,
       self.db,
       peer_id_str,
       self.hypertensor,
       self.subnet_id,
       termination_event,
   )
   nursery.start_soon(
       _validator_scoring_loop,
       protocol,
       scoring,
       self.db,
       peer_id_str,
       self.hypertensor,
       self.subnet_id,
       termination_event,
   )
   ```

4. **Implement `_miner_epoch_loop`** as a module-level async function (add after the existing `_tee_publish_loop` function at the bottom of the file):
   ```python
   async def _miner_epoch_loop(
       protocol: "MockNodeProtocol",
       pubsub,
       db,
       peer_id_str: str,
       hypertensor,
       subnet_id: int,
       termination_event,
   ) -> None:
       logger = logging.getLogger("miner_epoch_loop")
       last_epoch = None
       # Initial delay to allow mesh formation
       await trio.sleep(10)
       while not termination_event.is_set():
           try:
               slot = hypertensor.get_subnet_slot(subnet_id)
               epoch_data = hypertensor.get_subnet_epoch_data(int(str(slot)))
               current_epoch = epoch_data.epoch
               if current_epoch != last_epoch:
                   logger.info("[MinerLoop] New epoch %d — running miner_loop", current_epoch)
                   await protocol.miner_loop(current_epoch)
                   last_epoch = current_epoch
                   # Gossip: TEE quote
                   from subnet.tee.quote import dht_key as tee_dht_key
                   tee_key = tee_dht_key(peer_id_str, current_epoch)
                   tee_raw = db.nmap_get(TEE_QUOTE_TOPIC, tee_key)
                   if tee_raw is not None:
                       await pubsub.publish(TEE_QUOTE_TOPIC, tee_raw)
                       logger.info("[GossipPub] TEE published epoch=%d", current_epoch)
                   else:
                       logger.warning("[GossipPub] No TEE quote to publish epoch=%d", current_epoch)
                   # Gossip: RA-TLS cert (wrap in JSON envelope expected by receiver)
                   cert_key = f"{current_epoch}:{peer_id_str}"
                   cert_raw = db.nmap_get(RATLS_CERT_TOPIC, cert_key)
                   if cert_raw is not None:
                       payload = _json.dumps({
                           "epoch": current_epoch,
                           "cert": base64.b64encode(cert_raw).decode(),
                       }).encode()
                       await pubsub.publish(RATLS_CERT_TOPIC, payload)
                       logger.info("[GossipPub] RATLS cert published epoch=%d", current_epoch)
                   else:
                       logger.warning("[GossipPub] No RATLS cert to publish epoch=%d", current_epoch)
                   # Gossip: work record
                   work_raw = db.nmap_get(_WORK_TOPIC, cert_key)
                   if work_raw is not None:
                       await pubsub.publish(_WORK_TOPIC, work_raw)
                       logger.info("[GossipPub] Work record published epoch=%d", current_epoch)
                   else:
                       logger.warning("[GossipPub] No work record to publish epoch=%d", current_epoch)
               with trio.move_on_after(5):
                   await trio.sleep(5)
           except trio.Cancelled:
               raise
           except Exception as exc:
               logger.warning("[MinerLoop] Error (non-fatal): %s", exc)
               await trio.sleep(10)
       logger.info("[MinerLoop] stopped")
   ```

5. **Implement `_validator_scoring_loop`** as a module-level async function (add after `_miner_epoch_loop`):
   ```python
   async def _validator_scoring_loop(
       protocol: "MockNodeProtocol",
       scoring: "MockNodeScoring",
       db,
       self_peer_id: str,
       hypertensor,
       subnet_id: int,
       termination_event,
   ) -> None:
       logger = logging.getLogger("validator_scoring_loop")
       last_epoch = None
       # Wait for mesh formation and miner gossip propagation
       logger.info("[ValidatorLoop] Waiting 30s for mesh formation...")
       await trio.sleep(30)
       while not termination_event.is_set():
           try:
               slot = hypertensor.get_subnet_slot(subnet_id)
               epoch_data = hypertensor.get_subnet_epoch_data(int(str(slot)))
               current_epoch = epoch_data.epoch
               if current_epoch != last_epoch and current_epoch >= 1:
                   last_epoch = current_epoch
                   score_epoch = current_epoch - 1
                   logger.info("[ValidatorLoop] Scoring epoch=%d", score_epoch)
                   nodes = hypertensor.get_min_class_subnet_nodes_formatted(
                       subnet_id, score_epoch, SubnetNodeClass.Validator
                   )
                   for node in nodes:
                       peer_info = node.peer_info
                       if isinstance(peer_info, dict):
                           peer_id = peer_info.get("peer_id", "")
                       else:
                           peer_id = str(peer_info)
                       if not peer_id or peer_id == self_peer_id:
                           continue
                       try:
                           result = await protocol.validator_call(peer_id=peer_id, epoch=score_epoch)
                           peer_score = await scoring.score_peer(result, score_epoch)
                           logger.info(
                               "[Validator] peer=%s epoch=%d score=%.2f correct=%s",
                               peer_id[:16],
                               score_epoch,
                               peer_score.score,
                               result.metrics.get("correct", "?"),
                           )
                       except trio.Cancelled:
                           raise
                       except Exception as exc:
                           logger.warning("[ValidatorLoop] Score error peer=%s: %s", peer_id[:16], exc)
               with trio.move_on_after(5):
                   await trio.sleep(5)
           except trio.Cancelled:
               raise
           except Exception as exc:
               logger.warning("[ValidatorLoop] Error (non-fatal): %s", exc)
               await trio.sleep(10)
       logger.info("[ValidatorLoop] stopped")
   ```

6. Run `python3 -m pytest tests/ -q --tb=short` — must pass. Then verify imports:
   ```bash
   python3 -c "from subnet.server.server import Server, _miner_epoch_loop, _validator_scoring_loop; print('ok')"
   ```

## Must-Haves

- [ ] `MockNodeProtocol` is instantiated in `Server.run()` for non-bootstrap nodes only
- [ ] `_miner_epoch_loop` calls `protocol.miner_loop(epoch)` on each new epoch, then publishes all three records over GossipSub
- [ ] RA-TLS cert is gossipped as JSON `{"epoch": N, "cert": "<b64>"}` — matching the T02 receiver's expected format
- [ ] `_validator_scoring_loop` waits 30s on startup, then scores all peers (excluding self) on epoch change
- [ ] Validator log output includes `[Validator] peer=... epoch=N score=0.50` (when gossip data is present)
- [ ] Both loops catch non-Cancelled exceptions and continue (never crash the nursery)
- [ ] All 182 existing tests pass

## Verification

- `python3 -m pytest tests/ -q --tb=short` — 182 tests pass
- `python3 -c "from subnet.server.server import Server, _miner_epoch_loop, _validator_scoring_loop; print('ok')"` — no ImportError

## Observability Impact

- Signals added/changed:
  - `[MinerLoop] New epoch N — running miner_loop` — miner epoch fired
  - `[GossipPub] TEE/RATLS/Work published epoch=N` — gossip publish succeeded
  - `[GossipPub] No X to publish epoch=N` — WARNING: record missing from local DB after miner_loop (should not happen)
  - `[ValidatorLoop] Scoring epoch=N` — validator starting to score a completed epoch
  - `[Validator] peer=... epoch=N score=0.50 correct=True` — individual peer scored
  - `[ValidatorLoop] Score error peer=...` — WARNING: validator_call failed for this peer
- How a future agent inspects this: `docker compose logs validator | grep "\[Validator\]"` for scores; `docker compose logs miner-1 | grep "\[GossipPub\]"` for publish health
- Failure state exposed: `No X to publish` warns of missing local DB data; `Score error` warns of gossip propagation failure; `[MockValidator] no_ratls_cert` / `no_work_record` lines identify which data type failed to arrive

## Inputs

- `subnet/server/server.py` — existing `_tee_publish_loop` is the pattern to follow; nursery structure already understood
- `subnet/node/mock.py` — `MockNodeProtocol` constructor signature, `miner_loop(epoch)`, `validator_call(peer_id, epoch)`, `MockNodeScoring.score_peer(result, epoch)`
- `subnet/node/protocol.py` — `BaseNodeProtocol.__init__` signature: `(host, peer_id, subnet_info_tracker, mode, db, **kwargs)`
- `subnet/tee/quote.py` — `dht_key(peer_id, epoch)` helper returns the RocksDB key for a TEE quote
- T02 completed: gossip handlers for TEE_QUOTE_TOPIC, RATLS_CERT_TOPIC, _WORK_TOPIC are present in GossipReceiver

## Expected Output

- `subnet/server/server.py` — `MockNodeProtocol` instantiated for non-bootstrap nodes; `_miner_epoch_loop` and `_validator_scoring_loop` added as module-level functions and started in nursery
