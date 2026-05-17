# S01: Chain Peer Discovery

**Milestone:** M005 — Layer 3: Hypertensor Chain Integration
**Slice risk:** `high`
**Depends on:** none

## Goal

`SubnetInfoTracker.get_peers()` returns nodes read from the Hypertensor testnet chain (not a config file or mock DB). A standalone script `scripts/check_peers.py` proves chain connectivity and node enumeration end-to-end. The full Docker Compose stack can optionally run against testnet by swapping env vars. Layer 1 (`pytest tests/`) and Layer 2 (`docker-compose.tee-dev.yml`) remain green — the chain path is opt-in.

## Demo

```bash
# Prove chain connectivity:
python scripts/check_peers.py \
  --chain wss://rpc.hypertensor.app:443 \
  --subnet_id 1
# Output: node list (or "0 nodes registered" if subnet is empty) — exits 0 either way

# Full stack against testnet (opt-in):
CHAIN_ENDPOINT=wss://rpc.hypertensor.app:443 \
SUBNET_ID=1 PHRASE="word word word ..." \
docker compose -f docker-compose.chain.yml up

# Layers 1 & 2 still green:
pytest tests/
docker compose -f docker-compose.tee-dev.yml up --build
```

## Proof Level

- This slice proves: integration — real chain RPC call returns structured peer data
- Real runtime required: yes, for chain connectivity verification (testnet); no for Layer 1/2 regression
- Human/UAT required: no — script exit code and output are machine-verifiable

## Must-Haves

- `scripts/check_peers.py` exits 0 when chain is reachable; prints node count even if 0
- Credentials (`PHRASE`, `TENSOR_PRIVATE_KEY`) read from env, never printed or logged
- Friendly subnet ID (< 128000) resolved to real chain ID before queries
- `get_subnet_slot` returning `None` gives a clear human-readable message, not a traceback
- `docker-compose.chain.yml` drops `--no_blockchain_rpc`; reads `CHAIN_ENDPOINT`/`SUBNET_ID`/`PHRASE` from env
- `TESTING_LAYERS.md` Layer 3 section filled with real testnet endpoint and commands
- `pytest tests/` still green after all changes

## Verification

```bash
# 1. Script exits 0 on reachable endpoint (use local node if testnet is down):
python scripts/check_peers.py --chain ws://127.0.0.1:9944 --subnet_id 1
# → exits 0, prints "N nodes registered" (N may be 0)

# 2. Script exits 1 on unreachable endpoint with clear error message:
python scripts/check_peers.py --chain wss://unreachable.example:443 --subnet_id 1
# → exits 1, prints "ERROR: Cannot connect to chain endpoint ..."

# 3. Failure path is inspectable — stderr shows ERROR: prefix + offending URL:
python scripts/check_peers.py --local_rpc --subnet_id 1 2>&1 | grep "^ERROR:"
# → "ERROR: Cannot connect to ws://127.0.0.1:9944: ..." (with no local node)

# 4. Credential redaction — phrase value must not appear in output:
PHRASE="super secret mnemonic" python scripts/check_peers.py --local_rpc --subnet_id 1 2>&1 | grep -i "super secret"
# → no output (exit 1 from the grep is expected — that means redaction works)

# 5. Layer 1 still green:
pytest tests/ -x -q

# 6. Layer 2 still green:
docker compose -f docker-compose.tee-dev.yml config  # validates the unchanged compose file

# 7. Layer 3 guard fires with a clear error when CHAIN_ENDPOINT is missing (not silent):
docker compose -f docker-compose.chain.yml config 2>&1 | grep -i "CHAIN_ENDPOINT"
# → Docker Compose prints "variable is not set" or :? guard message — confirms misconfiguration surfaces before containers start
```

## Observability / Diagnostics

- Runtime signals: `check_peers.py` prints `[OK] Connected`, node rows, and final count to stdout; errors to stderr with `ERROR:` prefix
- Inspection surfaces: `python scripts/check_peers.py --help` for usage; `--chain` / `--subnet_id` / `--local_rpc` flags
- Failure visibility: connection errors caught and re-raised as human-readable messages with the offending endpoint URL; `get_subnet_slot=None` printed as a distinct warning (not a crash)
- Redaction constraints: `PHRASE` / `TENSOR_PRIVATE_KEY` values never appear in any print/log output

## Integration Closure

- Upstream surfaces consumed: `subnet/hypertensor/chain_functions.py` (`Hypertensor` class), `subnet/hypertensor/config.py` (`DEV_RPC`, `LOCAL_RPC`), `subnet/hypertensor/chain_data.py` (`SubnetNodeInfo`)
- New wiring introduced: `docker-compose.chain.yml` passes `CHAIN_ENDPOINT`/`SUBNET_ID`/`PHRASE` into node processes and drops `--no_blockchain_rpc`; `check_peers.py` exercises the same instantiation path as `run_node.py`'s real-chain branch
- What remains before the milestone is truly usable end-to-end: S02 (score extrinsic), S03 (slash extrinsic), S04 (CHAIN.md + registration scripts + CI job)

## Tasks

- [x] **T01: Write `scripts/check_peers.py` chain smoke-test script** `est:45m`
  - Why: This is the primary S01 proof artifact. Proves `Hypertensor` can connect to testnet and return structured peer data. Exercises the exact code path that `run_node.py` uses when `--no_blockchain_rpc` is false.
  - Files: `scripts/check_peers.py` (new), `subnet/hypertensor/chain_functions.py` (read-only reference), `subnet/hypertensor/config.py` (read-only reference)
  - Do: Create `scripts/check_peers.py` with argparse (`--chain`, `--subnet_id`, `--local_rpc` shortcut flag). Read `PHRASE` / `TENSOR_PRIVATE_KEY` from env (prefer `PHRASE`; fall back to `TENSOR_PRIVATE_KEY`; pass empty string if neither set — read-only queries don't need a keypair). Wrap `Hypertensor(url, phrase)` construction in try/except, print `ERROR: Cannot connect to <url>: <reason>` and exit 1. If `subnet_id < 128000`, call `get_subnet_id_from_friendly_id(subnet_id)` to resolve to real chain ID (mirror the logic in `run_node.py` lines 492–495). Call `get_subnet_slot(real_id)`; if None, print `"WARNING: Subnet not yet active / no slot assigned"` and exit 0 (not an error). Call `get_subnet_nodes_info_formatted(real_id)`. For each node, print `peer_id | hotkey | stake | classification`. Print final line `"N nodes registered"`. Exit 0. Never print `PHRASE` or `TENSOR_PRIVATE_KEY` values.
  - Verify: `python scripts/check_peers.py --local_rpc --subnet_id 1` exits 0 (with local node running) or gives `ERROR: Cannot connect` and exits 1 (no local node) — both are correct per-path. `grep -i phrase scripts/check_peers.py` must return no lines that print the phrase value.
  - Done when: script file exists, is executable, handles all edge cases (conn fail, None slot, empty peer list, friendly ID), and credentials are never echoed

- [x] **T02: Add `docker-compose.chain.yml` and update `TESTING_LAYERS.md`** `est:30m`
  - Why: `check_peers.py` proves the RPC read path; this task wires the full node stack to optionally use the real chain and documents Layer 3 in `TESTING_LAYERS.md` so the milestone's operational verification story is complete.
  - Files: `docker-compose.chain.yml` (new), `TESTING_LAYERS.md` (update Layer 3 section), `CHAIN.md` (new stub)
  - Do: Create `docker-compose.chain.yml` by cloning `docker-compose.tee-dev.yml`. For every service's `command:` block, remove `--no_blockchain_rpc`. Add env var pass-through: `CHAIN_ENDPOINT`, `SUBNET_ID`, `PHRASE` (or `TENSOR_PRIVATE_KEY`) for each service that runs a node process. Add a `x-chain-check` or `command` guard: if `CHAIN_ENDPOINT` is unset, print an error and exit — use a shell `test -n "$CHAIN_ENDPOINT" || { echo "ERROR: CHAIN_ENDPOINT is required"; exit 1; }` prefix in the command. Keep `MOCK_TEE=true` in all services (no EPYC hardware needed for testnet staging). In `TESTING_LAYERS.md`, fill in the Layer 3 section with: testnet endpoint (`wss://rpc.hypertensor.app:443`), required env vars, `scripts/check_peers.py` command, `docker compose -f docker-compose.chain.yml up` command, and expected validator log pattern (`"Synced: epoch=N"`). Create `CHAIN.md` as a stub: 2–3 sentences explaining that registration/staking docs will land in S04, with a pointer to `scripts/check_peers.py` for connectivity verification.
  - Verify: `docker compose -f docker-compose.chain.yml config` validates without error. `grep "no_blockchain_rpc" docker-compose.chain.yml` returns empty. `grep "CHAIN_ENDPOINT" docker-compose.chain.yml` returns at least one line per node service. `pytest tests/ -x -q` still green.
  - Done when: `docker-compose.chain.yml` validates, has no `--no_blockchain_rpc`, passes env vars to all node services; `TESTING_LAYERS.md` Layer 3 section is no longer a placeholder; `CHAIN.md` exists with a stub

## Files Likely Touched

- `scripts/check_peers.py` (new)
- `docker-compose.chain.yml` (new)
- `TESTING_LAYERS.md`
- `CHAIN.md` (new stub)
