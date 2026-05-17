---
id: T03
parent: S01
milestone: M004
provides:
  - MockNodeProtocol instantiated in Server.run() for non-bootstrap nodes
  - _miner_epoch_loop module-level async function: runs miner_loop(epoch) each new epoch and gossips TEE quote, RA-TLS cert (JSON envelope), and work record over GossipSub
  - _validator_scoring_loop module-level async function: waits 30s on startup then scores all non-self peers per epoch using validator_call() + MockNodeScoring.score_peer()
key_files:
  - subnet/server/server.py
key_decisions:
  - Used `dht_key(epoch, peer_id)` argument order (epoch first, peer_id second) — the plan snippet had them reversed; corrected by reading subnet/tee/quote.py and subnet/tee/publisher.py to confirm canonical order
  - Moved `from subnet.tee.quote import dht_key as tee_dht_key` import inside _miner_epoch_loop body to avoid any circular import risk (consistent with lazy-import pattern used in T02 handlers)
  - SubnetNodeClass imported at module level (from subnet.hypertensor.chain_functions import SubnetNodeClass) — needed for _validator_scoring_loop; no circular import issue
  - `base64` and `json as _json` added as module-level imports (not lazy) — they are stdlib and safe at module load
patterns_established:
  - RA-TLS cert gossipped as JSON envelope `{"epoch": N, "cert": "<b64>"}` matching T02 GossipReceiver handler expected format
  - Both loops follow the _tee_publish_loop pattern: poll for epoch change, do work on new epoch, sleep 5s, catch non-Cancelled exceptions and continue
  - protocol instantiation (MockNodeProtocol + await register_handlers()) placed just before nursery.start_soon() calls so protocol is ready before loops start
observability_surfaces:
  - "[MinerLoop] New epoch N — running miner_loop" — per-epoch miner trigger
  - "[GossipPub] TEE/RATLS cert/Work record published epoch=N" — successful gossip publish
  - "[GossipPub] No X to publish epoch=N" — WARNING: DB record missing after miner_loop (should not happen)
  - "[ValidatorLoop] Scoring epoch=N" — validator starting per-epoch scoring pass
  - "[Validator] peer=... epoch=N score=0.50 correct=True" — individual peer scored
  - "[ValidatorLoop] Score error peer=..." — WARNING: validator_call failed for this peer
  - Commands: `docker compose logs miner-1 | grep "\[GossipPub\]"` and `docker compose logs validator | grep "\[Validator\]"`
duration: ~10min
verification_result: passed
completed_at: 2026-03-17
blocker_discovered: false
---

# T03: Wire miner and validator epoch loops into server.py

**Wired MockNodeProtocol epoch loops into Server.run(): miners now gossip TEE quotes, RA-TLS certs, and work records each epoch; validators score peers and emit `[Validator] peer=... score=0.50` log lines.**

## What Happened

`_miner_epoch_loop` and `_validator_scoring_loop` were added as module-level async functions in `subnet/server/server.py`, following the existing `_tee_publish_loop` pattern. `MockNodeProtocol` is now instantiated inside `Server.run()` for all non-bootstrap nodes, with `await protocol.register_handlers()` called before the loops start.

The miner loop calls `protocol.miner_loop(epoch)` on each new epoch then reads the three produced records from RocksDB (TEE quote, RA-TLS cert, work record) and publishes them over GossipSub. The RA-TLS cert is wrapped in a `{"epoch": N, "cert": "<b64>"}` JSON envelope matching the format T02's `_handle_ratls_cert` receiver expects.

The validator scoring loop waits 30 seconds on startup (mesh formation + miner gossip propagation), then on each new epoch scores epoch-1 for all non-self peers returned by `get_min_class_subnet_nodes_formatted(..., SubnetNodeClass.Validator)`.

One deviation from the plan snippet was corrected: `dht_key(peer_id_str, current_epoch)` was written as `dht_key(current_epoch, peer_id_str)` to match the actual function signature `dht_key(epoch: int, peer_id: str) -> str` in `subnet/tee/quote.py`.

## Verification

```
python3 -c "from subnet.server.server import Server, _miner_epoch_loop, _validator_scoring_loop; print('ok')"
# → ok

python3 -m pytest tests/ -q --tb=short
# → 181 passed, 1 skipped (gramine test — pre-existing skip)
```

182 items collected; all pass.

## Diagnostics

- `docker compose logs miner-1 | grep "\[GossipPub\]"` — check per-epoch gossip publish health
- `docker compose logs validator | grep "\[Validator\]"` — check per-peer scoring output
- `docker compose logs validator | grep "no_ratls_cert\|no_work_record"` — diagnose gossip propagation failures
- If `[GossipPub] No X to publish epoch=N` appears, miner_loop() did not write to DB — check T01/T02 handlers
- If no `[Validator]` lines after ~40s, check that ValidatorLoop started (non-bootstrap node) and that epoch >= 1

## Deviations

- Plan snippet called `tee_dht_key(peer_id_str, current_epoch)` but `dht_key()` signature is `(epoch, peer_id)` (epoch first). Fixed in implementation by reading `subnet/tee/quote.py` directly.

## Known Issues

None.

## Files Created/Modified

- `subnet/server/server.py` — Added `base64`, `_json` imports; expanded mock imports to include `MockNodeProtocol`, `MockNodeScoring`, `SubnetNodeClass`; instantiated `MockNodeProtocol` + `MockNodeScoring` in `Server.run()` non-bootstrap block; added `_miner_epoch_loop` and `_validator_scoring_loop` as module-level async functions
