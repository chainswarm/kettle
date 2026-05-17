---
estimated_steps: 6
estimated_files: 2
---

# T02: Add GossipSub handlers for TEE quotes, RA-TLS certs, and work records

**Slice:** S01 — Multi-node epoch loop
**Milestone:** M004

## Description

Work records written to a miner's local RocksDB are invisible to the validator container. GossipSub is the proven cross-container transport — heartbeats already use it end-to-end. This task adds receive handlers for the three additional data types that `MockNodeProtocol.validator_call()` needs:

1. **TEE quotes** (topic: `TEE_QUOTE_TOPIC = "tee_quote"`) — raw `TeeQuote.to_bytes()` bytes; epoch embedded in `quote.nonce`
2. **RA-TLS certs** (topic: `RATLS_CERT_TOPIC = "ratls_cert"`) — JSON envelope `{"epoch": N, "cert": "<b64>"}` wrapping the PEM bytes; epoch provided explicitly because the PEM has no parseable epoch field
3. **Work records** (topic: `_WORK_TOPIC = "mock_work"`) — raw `OutputEnvelope.to_bytes()` bytes; epoch embedded in the inner JSON payload

Each handler follows the `_handle_heartbeat` pattern: deserialise → dedup → `nmap_set` to local RocksDB with key `f"{epoch}:{from_peer}"`. The key format exactly matches what `validator_call()` passes to `nmap_get`.

The gossip `topics` list in `server.py` must also include all three new topics so `GossipReceiver.run()` subscribes to them.

## Steps

1. **`subnet/utils/gossipsub/gossip_receiver.py` — add imports**: At top of file, add `import base64`, `import json`. These are stdlib; no new dependencies.
2. **Add topic constant imports**: Near the existing `from subnet.utils.pubsub.heartbeat import HEARTBEAT_TOPIC, HeartbeatData` line, add:
   ```python
   from subnet.tee.quote import TEE_QUOTE_TOPIC, RATLS_CERT_TOPIC
   from subnet.node.mock import _WORK_TOPIC
   ```
3. **Add dedup sets in `__init__`**: After `self._seen_heartbeats: set[str] = set()`, add:
   ```python
   self._seen_tee_quotes: set[str] = set()
   self._seen_ratls_certs: set[str] = set()
   self._seen_work_records: set[str] = set()
   ```
4. **Add `_handle_tee_quote`** method:
   ```python
   async def _handle_tee_quote(self, message: rpc_pb2.Message, from_peer: str) -> None:
       from subnet.tee.quote import TeeQuote
       try:
           quote = TeeQuote.from_bytes(message.data)
           epoch = quote.nonce
       except Exception as e:
           logger.warning(f"TeeQuote parse failed: {e}")
           return
       key = f"{epoch}:{from_peer}"
       if key in self._seen_tee_quotes or self.db.nmap_get(TEE_QUOTE_TOPIC, key) is not None:
           return
       self.db.nmap_set(TEE_QUOTE_TOPIC, key, message.data)
       self._seen_tee_quotes.add(key)
       logger.log(self.log_level, f"TEE quote stored: epoch={epoch} peer={from_peer[:16]}")
   ```
5. **Add `_handle_ratls_cert`** method:
   ```python
   async def _handle_ratls_cert(self, message: rpc_pb2.Message, from_peer: str) -> None:
       try:
           data = json.loads(message.data.decode())
           epoch = int(data["epoch"])
           cert_bytes = base64.b64decode(data["cert"])
       except Exception as e:
           logger.warning(f"RATLS cert parse failed: {e}")
           return
       key = f"{epoch}:{from_peer}"
       if key in self._seen_ratls_certs or self.db.nmap_get(RATLS_CERT_TOPIC, key) is not None:
           return
       self.db.nmap_set(RATLS_CERT_TOPIC, key, cert_bytes)
       self._seen_ratls_certs.add(key)
       logger.log(self.log_level, f"RATLS cert stored: epoch={epoch} peer={from_peer[:16]}")
   ```
6. **Add `_handle_work_record`** method:
   ```python
   async def _handle_work_record(self, message: rpc_pb2.Message, from_peer: str) -> None:
       from subnet.tee.ratls.envelope import OutputEnvelope
       try:
           env = OutputEnvelope.from_bytes(message.data)
           rec = json.loads(env.output.decode())
           epoch = int(rec["epoch"])
       except Exception as e:
           logger.warning(f"Work record parse failed: {e}")
           return
       key = f"{epoch}:{from_peer}"
       if key in self._seen_work_records or self.db.nmap_get(_WORK_TOPIC, key) is not None:
           return
       self.db.nmap_set(_WORK_TOPIC, key, message.data)
       self._seen_work_records.add(key)
       logger.log(self.log_level, f"Work record stored: epoch={epoch} peer={from_peer[:16]}")
   ```
7. **Wire up `_handle_message`** dispatch: After the `if topic == HEARTBEAT_TOPIC:` block, add:
   ```python
   elif topic == TEE_QUOTE_TOPIC:
       await self._handle_tee_quote(message, from_peer)
   elif topic == RATLS_CERT_TOPIC:
       await self._handle_ratls_cert(message, from_peer)
   elif topic == _WORK_TOPIC:
       await self._handle_work_record(message, from_peer)
   ```
8. **`subnet/server/server.py` — update topic list**: Find the `GossipReceiver(` instantiation and change `topics=[HEARTBEAT_TOPIC]` to `topics=[HEARTBEAT_TOPIC, TEE_QUOTE_TOPIC, RATLS_CERT_TOPIC, _WORK_TOPIC]`. Add these imports at the top of `server.py` (alongside existing imports):
   ```python
   from subnet.tee.quote import TEE_QUOTE_TOPIC, RATLS_CERT_TOPIC
   from subnet.node.mock import _WORK_TOPIC
   ```
9. Run `python3 -m pytest tests/ -q --tb=short` — must pass.

## Must-Haves

- [ ] `GossipReceiver` subscribes to `HEARTBEAT_TOPIC`, `TEE_QUOTE_TOPIC`, `RATLS_CERT_TOPIC`, `_WORK_TOPIC` (4 topics total)
- [ ] `_handle_tee_quote` stores bytes with key `{quote.nonce}:{from_peer}` under `TEE_QUOTE_TOPIC`
- [ ] `_handle_ratls_cert` stores PEM bytes (not the JSON envelope) with key `{epoch}:{from_peer}` under `RATLS_CERT_TOPIC` — matches what `mock.py` writes in `miner_loop`
- [ ] `_handle_work_record` stores raw `OutputEnvelope.to_bytes()` with key `{epoch}:{from_peer}` under `_WORK_TOPIC` — matches what `validator_call` reads via `nmap_get`
- [ ] Each handler deduplicates (in-memory set + DB check) before writing
- [ ] All handlers catch parse errors and log a warning without crashing the receive loop
- [ ] All 182 existing tests pass

## Verification

- `python3 -m pytest tests/ -q --tb=short` — 182 tests pass
- `python3 -c "from subnet.utils.gossipsub.gossip_receiver import GossipReceiver; print('import ok')"` — no ImportError
- `python3 -c "from subnet.server.server import Server; print('import ok')"` — no ImportError

## Observability Impact

- Signals added/changed: Log lines `TEE quote stored: epoch=N peer=...`, `RATLS cert stored: epoch=N peer=...`, `Work record stored: epoch=N peer=...` at `log_level` (DEBUG by default) on each received gossip message
- How a future agent inspects this: `docker compose logs validator | grep "stored"` — confirms records arrived from miners
- Failure state exposed: Parse failures logged as WARNING; missing records in validator logs (`no_ratls_cert`, `no_work_record`) indicate gossip delivery failure

## Inputs

- `subnet/utils/gossipsub/gossip_receiver.py` — existing file with `_handle_heartbeat` pattern to follow exactly
- `subnet/server/server.py` — existing file; only the `GossipReceiver(topics=[...])` line and its imports are changed
- `subnet/tee/quote.py` — defines `TEE_QUOTE_TOPIC = "tee_quote"`, `RATLS_CERT_TOPIC = "ratls_cert"`, `TeeQuote`
- `subnet/node/mock.py` — defines `_WORK_TOPIC = "mock_work"` and `OutputEnvelope` wire format context
- `subnet/tee/ratls/envelope.py` — `OutputEnvelope.from_bytes()` / `.output` (inner JSON bytes) / `.to_bytes()`

## Expected Output

- `subnet/utils/gossipsub/gossip_receiver.py` — 3 new handler methods; `_handle_message` dispatches to them; 3 new dedup sets
- `subnet/server/server.py` — `GossipReceiver` now subscribes to all 4 topics; 2 new import lines
