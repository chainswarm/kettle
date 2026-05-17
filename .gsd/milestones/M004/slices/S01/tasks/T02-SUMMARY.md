---
id: T02
parent: S01
milestone: M004
provides:
  - GossipReceiver subscribes to tee_quote, ratls_cert, mock_work topics and stores received data to RocksDB with {epoch}:{peer_id} keys
key_files:
  - subnet/utils/gossipsub/gossip_receiver.py
  - subnet/server/server.py
key_decisions:
  - _handle_ratls_cert stores the unwrapped PEM bytes (not the JSON envelope) — matching what validator_call reads via nmap_get(RATLS_CERT_TOPIC, key)
  - _handle_tee_quote stores raw message.data bytes (the TeeQuote.to_bytes() JSON) — dedup key uses quote.nonce as epoch
  - _handle_work_record stores raw message.data bytes (OutputEnvelope.to_bytes()) — epoch extracted from inner JSON payload via OutputEnvelope.from_bytes()
patterns_established:
  - Each handler follows the _handle_heartbeat pattern: deserialise → dedup (in-memory set + DB check) → nmap_set → update in-memory set
  - Lazy imports (from subnet.tee.quote import TeeQuote) inside handler methods avoid circular import risk at module load
  - All handlers catch parse errors and log WARNING without crashing the receive loop
observability_surfaces:
  - "TEE quote stored: epoch=N peer=<16chars>" at log_level (DEBUG by default)
  - "RATLS cert stored: epoch=N peer=<16chars>" at log_level
  - "Work record stored: epoch=N peer=<16chars>" at log_level
  - Parse failures logged as WARNING with message content; receive loop continues
  - "docker compose logs validator | grep stored" confirms records arriving from miners
duration: ~10m
verification_result: passed
completed_at: 2026-03-17
blocker_discovered: false
---

# T02: Add GossipSub handlers for TEE quotes, RA-TLS certs, and work records

**Added three GossipSub receive handlers (tee_quote, ratls_cert, mock_work) to GossipReceiver and subscribed server.py to all four topics so validator can receive miner data cross-container.**

## What Happened

Added `import base64`, `import json` at the top of `gossip_receiver.py`. Added topic constant imports (`TEE_QUOTE_TOPIC`, `RATLS_CERT_TOPIC` from `subnet.tee.quote`; `_WORK_TOPIC` from `subnet.node.mock`) at the module level alongside the existing heartbeat import.

Added three dedup sets in `__init__`: `_seen_tee_quotes`, `_seen_ratls_certs`, `_seen_work_records` (same pattern as `_seen_heartbeats`).

Added dispatch branches in `_handle_message` for the three new topics, inserted immediately after the heartbeat branch.

Implemented the three handler methods:
- `_handle_tee_quote`: deserialises via `TeeQuote.from_bytes`, uses `quote.nonce` as epoch, stores `message.data` bytes under `TEE_QUOTE_TOPIC`
- `_handle_ratls_cert`: parses JSON envelope `{"epoch": N, "cert": "<b64>"}`, base64-decodes the cert PEM, stores raw PEM bytes under `RATLS_CERT_TOPIC` — exactly what `validator_call` reads
- `_handle_work_record`: deserialises via `OutputEnvelope.from_bytes`, extracts epoch from inner JSON, stores `message.data` bytes under `_WORK_TOPIC`

In `server.py`: added two import lines (`TEE_QUOTE_TOPIC`, `RATLS_CERT_TOPIC`, `_WORK_TOPIC`) and changed `topics=[HEARTBEAT_TOPIC]` to `topics=[HEARTBEAT_TOPIC, TEE_QUOTE_TOPIC, RATLS_CERT_TOPIC, _WORK_TOPIC]`.

## Verification

```
python3 -c "from subnet.utils.gossipsub.gossip_receiver import GossipReceiver; print('import ok')"
# → import ok

python3 -c "from subnet.server.server import Server; print('import ok')"
# → import ok

python3 -m pytest tests/ -q --tb=short
# → 181 passed, 1 skipped in 5.64s  (= 182 total, all pass)
```

## Diagnostics

- `docker compose logs validator | grep "stored"` — confirms TEE/RATLS/work records received from miners
- Parse failures appear as WARNING in logs without stopping the receive loop
- Missing records in validator logs (`no_ratls_cert`, `no_work_record`) indicate gossip delivery failure, not handler bugs

## Deviations

None. Implemented exactly as planned.

## Known Issues

None.

## Files Created/Modified

- `subnet/utils/gossipsub/gossip_receiver.py` — added stdlib imports, topic constant imports, 3 dedup sets, 3 handler methods, dispatch wiring in _handle_message
- `subnet/server/server.py` — added TEE_QUOTE_TOPIC/RATLS_CERT_TOPIC/_WORK_TOPIC imports; GossipReceiver now subscribes to all 4 topics
