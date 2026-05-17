# Chain Peer Discovery — Research (M005/S01)

**Date:** 2026-03-17

## Summary

S01 replaces `--no_blockchain_rpc` / `LocalMockHypertensor` with the real `Hypertensor` client so that `SubnetInfoTracker` reads the peer list from the Hypertensor testnet chain. The good news: **the infrastructure is already entirely complete**. The `Hypertensor` class (`subnet/hypertensor/chain_functions.py`) wraps `py-substrate-interface` (pinned to `hayotensor/py-polkadot-sdk@hypertensor`) and already implements every method that `SubnetInfoTracker` calls — `get_subnet_nodes_info_formatted`, `get_bootnodes_formatted`, `get_all_overwatch_nodes_info_formatted`, `get_subnet_epoch_data`, `get_subnet_slot`, `get_epoch_length`. The `SubnetInfoTracker` (v3) accepts `Hypertensor | LocalMockHypertensor` as its `hypertensor` arg, so swapping backends is a drop-in.

The only work in S01 is:
1. A `scripts/check_peers.py` smoke-test that instantiates `Hypertensor` against the testnet endpoint and calls `get_subnet_nodes_info_formatted(subnet_id)`, printing each node's `peer_id`, `hotkey`, `stake_balance`, and `classification`.
2. Wiring the Docker Compose stack (`docker-compose.tee-dev.yml`) to support a `CHAIN_ENDPOINT` + `SUBNET_ID` + `PHRASE`/`TENSOR_PRIVATE_KEY` path that drops `--no_blockchain_rpc` and uses the real `Hypertensor` backend, while keeping `--no_blockchain_rpc` as the default for local dev (Layer 2 stays green).
3. Updating `TESTING_LAYERS.md` Layer 3 section with the actual testnet endpoint and commands.

No new classes, no new abstractions. The chain client (`Hypertensor`) is already in use by `run_node.py` for the `--local_rpc` / `--no no_blockchain_rpc=False` path.

## Recommendation

Write `scripts/check_peers.py` first — it proves the chain RPC works and is the primary S01 deliverable. Then add the `docker-compose.chain.yml` (or extend `tee-dev` with a conditional) so the full node stack can run against testnet. Keep `--no_blockchain_rpc` the default; the chain path is opt-in via env vars.

The `SubnetInfoTracker` v3 (`subnet/utils/hypertensor/subnet_info_tracker_v3.py`) is what `server.py` already imports — **no changes needed to SubnetInfoTracker itself**. The switch from mock to real chain happens entirely in the instantiation site in `run_node.py` (the `if not args.no_blockchain_rpc:` branch already does it).

## Implementation Landscape

### Key Files

- `subnet/hypertensor/chain_functions.py` — `Hypertensor` class. Has all required methods. No changes needed for S01.
- `subnet/hypertensor/config.py` — `BLOCK_SECS=6`, `EPOCH_LENGTH=20`. `DEV_RPC` / `LOCAL_RPC` constants referenced by `run_node.py` via `os.getenv`.
- `subnet/.env.example` — `DEV_RPC="wss://rpc.hypertensor.app:443"`, `PHRASE="..."`. The real testnet endpoint is already documented here.
- `subnet/cli/run_node.py` — instantiation site. `if not args.no_blockchain_rpc:` branch creates `Hypertensor(rpc, phrase)`. The `if args.subnet_id < 128000:` block resolves friendly IDs (≤128000 → real chain ID via `FriendlyUidSubnetId` storage). Both paths pass `hypertensor` into `Server`.
- `subnet/utils/hypertensor/subnet_info_tracker_v3.py` — `SubnetInfoTracker`. Type hint is `Hypertensor | LocalMockHypertensor`. No change needed — both backends expose identical public API.
- `subnet/server/server.py` — imports `SubnetInfoTracker` from `v3`. Constructs with `(termination_event, subnet_id, subnet_slot, hypertensor)`. `subnet_slot` comes from `hypertensor.get_subnet_slot(subnet_id)` — both backends implement this.
- `docker-compose.tee-dev.yml` — all services currently pass `--no_blockchain_rpc`. Needs a companion compose file (or env-conditional command) for the chain path.
- `tests/hypertensor/test_rpc.py` — integration tests for `Hypertensor` against `ws://127.0.0.1:9944`. Uses `LOCAL_RPC`. These are excluded from `pytest tests/` by default; they're the reference for how chain queries are made.
- **`scripts/check_peers.py`** — does not exist yet. Must be created. Primary S01 deliverable.

### Build Order

1. **`scripts/check_peers.py`** — prove the chain RPC returns a usable peer list. This is the S01 verification command. Once this script passes against testnet, S01's chain-read requirement is proven. Write this first.

2. **`docker-compose.chain.yml`** (new file) — clone of `tee-dev` but without `--no_blockchain_rpc`; instead, reads `CHAIN_ENDPOINT`, `SUBNET_ID`, `PHRASE`/`TENSOR_PRIVATE_KEY` from env. Adds a startup check that aborts gracefully if `CHAIN_ENDPOINT` is unset. `MOCK_TEE=true` stays — no hardware required.

3. **`TESTING_LAYERS.md` update** — fill in the Layer 3 section with the actual testnet endpoint, real commands using the new compose file, and `scripts/check_peers.py` output.

4. **`CHAIN.md`** (optional stub for S01, full content is S04) — a brief note pointing to registration scripts that will be added in S04; keeps S01 scope tight.

### Verification Approach

```bash
# 1. Check peers from chain directly:
python scripts/check_peers.py \
  --chain wss://rpc.hypertensor.app:443 \
  --subnet_id <SUBNET_ID>

# Expected output: list of nodes with peer_id, hotkey, classification, stake
# If subnet has no registered nodes yet, output is []  (still a valid pass — proves connectivity)

# 2. Run the full node stack against testnet:
CHAIN_ENDPOINT=wss://rpc.hypertensor.app:443 \
SUBNET_ID=<ID> \
PHRASE="<mnemonic>" \
docker compose -f docker-compose.chain.yml up

# Validator logs should show subnet_info_tracker syncing epoch data from chain:
# "Synced: epoch=N, pct=..." with real chain epoch numbers

# 3. Layer 1 + 2 still green:
pytest tests/
docker compose -f docker-compose.tee-dev.yml up --build
```

## Constraints

- `py-substrate-interface` is pinned to `hayotensor/py-polkadot-sdk@hypertensor` (not pypi). This fork is what adds Hypertensor-specific RPC methods (`network_getSubnetNodesInfo`, `network_getBootnodes`, etc.). Do not upgrade to upstream `substrate-interface` — it won't have these methods.
- `Hypertensor.__init__` connects to the WebSocket immediately. If the endpoint is unreachable, it raises at construction time. `check_peers.py` should wrap in try/except and give a clear error.
- `subnet_id < 128000` triggers friendly-ID resolution via `FriendlyUidSubnetId` storage. If the testnet subnet uses an internal ID ≥ 128000, the friendly-ID lookup is skipped. The script should handle both cases (already in `run_node.py` lines 492–495).
- `BLOCK_SECS=6` is hardcoded in `subnet/hypertensor/config.py`. If the testnet uses a different block time, `EpochData.seconds_remaining` will be wrong. This is not an S01 concern but worth noting for S04 docs.
- Keypair credentials must not be logged. `run_node.py` already handles this; `check_peers.py` should follow the same pattern (read from env, never print).

## Common Pitfalls

- **Empty peer list is not an error** — if the testnet subnet hasn't had nodes register yet, `get_subnet_nodes_info_formatted` returns `[]`. The script should treat this as a successful connection and print `"0 nodes registered"` rather than exit non-zero.
- **Friendly ID vs real ID** — The test subnet may use a friendly ID (e.g. `1`) while the chain stores it internally as `128001`. Always pass the result of `get_subnet_id_from_friendly_id()` to subsequent queries if the input is < 128000.
- **`get_subnet_slot` may return `None`** — The `SubnetInfoTracker._update_data` already handles this (returns early). `check_peers.py` should handle it too with a clear message ("Subnet not yet active / no slot assigned").
- **WebSocket reconnect** — `Hypertensor` uses `with self.interface as _interface:` context manager pattern with `@retry`. This is already battle-tested in the codebase. Don't add another retry layer.

## Open Risks

- Testnet endpoint `wss://rpc.hypertensor.app:443` availability is not guaranteed — if it is down, S01 cannot be validated. Mitigation: check with `wscat` or `websocat` before starting, and add a `--local_rpc` path in `check_peers.py` for local node testing.
- Testnet subnet may need to be registered first (S04 docs cover this, but it's a prerequisite to S01 validation). If no subnet is registered, `get_subnet_slot` returns `None`. S01 only needs to prove the read path works; an empty list is an acceptable result.

## Forward Intelligence

The following information is specifically for downstream slices (S02, S03):

- **`Hypertensor.propose_attestation`** and **`Hypertensor.attest`** are the extrinsic methods for S02 score submission. They use `self.interface.compose_call("Network", "propose_attestation", ...)` followed by `create_signed_extrinsic` + `submit_extrinsic`. The pattern is identical across all write methods in `chain_functions.py`.
- **Keypair** is stored as `self.keypair` (ECDSA). The hotkey is `self.keypair.ss58_address`. Loaded from mnemonic or private key — never from env directly in the class; caller (run_node.py) handles that.
- **`SubnetInfoTracker.nodes`** is already `List[SubnetNodeInfo]` with `.peer_info.peer_id`, `.hotkey`, `.stake_balance`, `.classification`. This is what the validator uses to determine which peers to score. S02 will read `SubnetNodeInfo.subnet_node_id` to compose score extrinsics.
