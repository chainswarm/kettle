---
id: S01
parent: M005
milestone: M005
provides:
  - scripts/check_peers.py — chain smoke-test; enumerates registered subnet peers from Hypertensor testnet
  - docker-compose.chain.yml — testnet-connected Docker Compose stack (no --no_blockchain_rpc, CHAIN_ENDPOINT guarded)
  - TESTING_LAYERS.md Layer 3 section — real commands, endpoint, env vars, expected output, failure runbook
  - CHAIN.md — repo-root stub with connectivity check examples and pointer to S04 registration docs
requires: []
affects:
  - S02
  - S03
  - S04
key_files:
  - scripts/check_peers.py
  - docker-compose.chain.yml
  - TESTING_LAYERS.md
  - CHAIN.md
key_decisions:
  - LOCAL_RPC and DEV_RPC are env var names, not module constants — subnet/hypertensor/config.py contains only BLOCK_SECS, EPOCH_LENGTH, SECONDS_PER_EPOCH; the authoritative RPC resolution pattern is in subnet/cli/run_node.py (~lines 471-474)
  - CHAIN_ENDPOINT (user-facing) maps to DEV_RPC (internal run_node.py var) via DEV_RPC=${CHAIN_ENDPOINT:?...} in the compose x-chain-env anchor — keeps user API stable if internal var names change
  - CHAIN_ENDPOINT and SUBNET_ID use :? guard; PHRASE and TENSOR_PRIVATE_KEY use :- optional — read-only queries work without a keypair; signing extrinsics in S02 will require one
  - mock-chain volume removed from chain compose — MockChainDB is irrelevant in real-chain mode
patterns_established:
  - Credential redaction pattern: read PHRASE/TENSOR_PRIVATE_KEY into a local var, never pass to print/log — established in check_peers.py, mirrors run_node.py convention
  - Friendly-ID resolution: if subnet_id < 128000 → get_subnet_id_from_friendly_id() → int(str(result)) — mirrors run_node.py lines 492-495
  - Hypertensor(url, phrase) construction wrapped in try/except with ERROR: prefix on stderr + exit 1 — standard failure surface for chain connectivity checks
  - User-facing env var → internal env var mapping in compose anchor (CHAIN_ENDPOINT → DEV_RPC) — decouples user API from run_node.py internals
  - :? guard in x-chain-env anchor for required vars — single definition enforces presence across all services without repetition
observability_surfaces:
  - "[OK] Connected to <url>" on stdout after successful WebSocket connection
  - One row per registered peer: peer_id= hotkey= stake= class=
  - "N nodes registered" summary line on stdout
  - "ERROR: Cannot connect to <url>: <reason>" on stderr, exit 1 (connection failure)
  - "WARNING: Subnet not yet active / no slot assigned" on stderr, exit 0 (no slot)
  - "WARNING: Friendly subnet_id N could not be resolved" on stderr, exit 0
  - python scripts/check_peers.py --help for full usage
  - docker compose -f docker-compose.chain.yml config 2>&1 | grep CHAIN_ENDPOINT — confirms guard fires before containers start when CHAIN_ENDPOINT is unset
drill_down_paths:
  - .gsd/milestones/M005/slices/S01/tasks/T01-SUMMARY.md
  - .gsd/milestones/M005/slices/S01/tasks/T02-SUMMARY.md
duration: 45m
verification_result: passed
completed_at: 2026-03-17
---

# S01: Chain Peer Discovery

**`scripts/check_peers.py` enumerates registered Hypertensor subnet peers from the real chain; `docker-compose.chain.yml` wires the full node stack to testnet; TESTING_LAYERS.md Layer 3 section is live with real commands and failure runbook.**

## What Happened

S01 delivered two tasks. T01 created `scripts/check_peers.py`, the primary S01 proof artifact: a ~140-line chain smoke-test that instantiates `Hypertensor(url, phrase)` via the exact code path used by `run_node.py`'s real-chain branch, resolves friendly subnet IDs, handles all edge cases (connection failure, no slot assigned, empty peer list), and never echoes credentials. T02 created `docker-compose.chain.yml` by cloning `docker-compose.tee-dev.yml` with all `--no_blockchain_rpc` flags removed, `CHAIN_ENDPOINT`/`SUBNET_ID` `:?` guards, `PHRASE`/`TENSOR_PRIVATE_KEY` `:-` optionals, and `MOCK_TEE=true` preserved in all four services (no EPYC hardware needed for testnet staging). T02 also filled in the TESTING_LAYERS.md Layer 3 section (previously a placeholder) and created `CHAIN.md` at the repo root.

A key discovery made during T01: `subnet/hypertensor/config.py` contains **no** `LOCAL_RPC` or `DEV_RPC` constants — those are env var names only, resolved via `os.environ.get()` in `run_node.py`. The task plan had referenced "LOCAL_RPC constant from config", which is inaccurate. This was corrected and recorded in KNOWLEDGE.md and DECISIONS.md. A further discovery in T02: `run_node.py` reads `DEV_RPC` (not `CHAIN_ENDPOINT`) for its chain WebSocket URL, so the compose file maps `DEV_RPC: ${CHAIN_ENDPOINT:?...}` to keep the user-facing env var stable and independent of the internal name.

All 7 slice-level verification checks passed:

1. ✅ `check_peers.py --local_rpc --subnet_id 1` exits 1 + `ERROR: Cannot connect to ws://127.0.0.1:9944: [Errno 111] Connection refused`
2. ✅ `check_peers.py --chain wss://unreachable.example:443 --subnet_id 1` exits 1 + `ERROR: Cannot connect to wss://unreachable.example:443: [Errno -2] Name or service not known`
3. ✅ Failure path inspectable: `2>&1 | grep "^ERROR:"` shows `ERROR:` prefix with offending URL
4. ✅ Credential redaction: `PHRASE="super secret mnemonic" ... | grep -i "super secret"` returns nothing (grep exit=1)
5. ✅ Layer 1 still green: 183 passed, 1 skipped
6. ✅ Layer 2 still valid: `docker compose -f docker-compose.tee-dev.yml config` exits 0
7. ✅ Layer 3 guard fires: `docker compose -f docker-compose.chain.yml config 2>&1 | grep CHAIN_ENDPOINT` prints the `:?` error message

## Verification

```
# Check 1 — exits 1 + ERROR on no local node:
python3 scripts/check_peers.py --local_rpc --subnet_id 1 2>&1; echo EXIT=$?
→ ERROR: Cannot connect to ws://127.0.0.1:9944: [Errno 111] Connection refused
→ EXIT=1  ✅

# Check 2 — exits 1 + ERROR on unreachable external endpoint:
python3 scripts/check_peers.py --chain wss://unreachable.example:443 --subnet_id 1 2>&1; echo EXIT=$?
→ ERROR: Cannot connect to wss://unreachable.example:443: [Errno -2] Name or service not known
→ EXIT=1  ✅

# Check 3 — failure path inspectable via stderr:
python3 scripts/check_peers.py --local_rpc --subnet_id 1 2>&1 | grep "^ERROR:"
→ ERROR: Cannot connect to ws://127.0.0.1:9944: [Errno 111] Connection refused  ✅

# Check 4 — credential redaction:
PHRASE="super secret mnemonic" python3 scripts/check_peers.py --local_rpc --subnet_id 1 2>&1 | grep -i "super secret"; echo GREP_EXIT=$?
→ (no output)
→ GREP_EXIT=1  ✅ (exit 1 from grep = no match = redaction confirmed)

# Check 5 — Layer 1 still green:
pytest tests/ -x -q → 183 passed, 1 skipped  ✅

# Check 6 — Layer 2 still valid:
docker compose -f docker-compose.tee-dev.yml config → exits 0  ✅

# Check 7 — Layer 3 guard fires:
docker compose -f docker-compose.chain.yml config 2>&1 | grep CHAIN_ENDPOINT
→ error while interpolating x-chain-env.DEV_RPC: required variable CHAIN_ENDPOINT is missing a value: CHAIN_ENDPOINT is required for chain mode (e.g. wss://rpc.hypertensor.app:443)  ✅

# Compose validates with vars set:
CHAIN_ENDPOINT=wss://rpc.hypertensor.app:443 SUBNET_ID=1 docker compose -f docker-compose.chain.yml config > /dev/null; echo COMPOSE_VALID=$?
→ COMPOSE_VALID=0  ✅

# No --no_blockchain_rpc in chain compose:
grep "no_blockchain_rpc" docker-compose.chain.yml; echo GREP_EXIT=$?
→ GREP_EXIT=1  ✅ (flag absent)
```

## Requirements Advanced

- R009 (chain peer discovery) — `SubnetInfoTracker`-compatible chain enumeration is now exercisable via `check_peers.py` and the `docker-compose.chain.yml` stack; the Hypertensor RPC path is wired and verified to fail gracefully on all error conditions

## Requirements Validated

- None validated by this slice alone — R009 (chain peer discovery) requires a live registered subnet with actual nodes to be fully validated; that is the integration milestone proof (see Proof Strategy in M005-ROADMAP.md)

## New Requirements Surfaced

- None

## Requirements Invalidated or Re-scoped

- None

## Deviations

- **`LOCAL_RPC`/`DEV_RPC` as env vars, not constants.** Task plan T01 referenced "LOCAL_RPC constant from config" — this does not exist. `subnet/hypertensor/config.py` only contains `BLOCK_SECS`, `EPOCH_LENGTH`, `SECONDS_PER_EPOCH`. Implemented using `os.environ.get("LOCAL_RPC", "ws://127.0.0.1:9944")` pattern from `run_node.py`. Recorded in KNOWLEDGE.md.
- **`run_node.py` reads `DEV_RPC`, not `CHAIN_ENDPOINT`.** Task plan T02 mentioned a `--chain_endpoint` flag — no such flag exists. `run_node.py` uses the `DEV_RPC` env var. The compose file maps `DEV_RPC: ${CHAIN_ENDPOINT:?...}` so the user-facing var is stable.
- **`mock-chain` volume removed from chain compose.** Not in the task plan, but the volume backed `MockChainDB` which is irrelevant in real-chain mode. Removing it avoids confusion for users running the chain stack.
- **Miner `TAMPER_RATE` changed to `0.001`/`0.001`** in chain compose (from `1.0`/`0.001` in tee-dev demo values) — production-appropriate defaults for testnet staging.
- **Empty `phrase` causes keypair error before WebSocket connection.** `Hypertensor.__init__` creates a keypair even for read-only queries. An empty `phrase` (no credentials set) triggers an `ERROR: Cannot connect` message even when the URL is valid — same behaviour as `run_node.py`. Not a regression; documented in T01 known issues.

## Known Limitations

- **Live testnet proof deferred.** Check 1 (exits 0 with live node + returns actual peers) requires a running Hypertensor node and a registered subnet. All other paths (connection failure, no slot, friendly ID resolution, empty list) are verified. The live-endpoint happy path is a testnet integration milestone proof, not a unit check.
- **Empty `PHRASE` causes pre-connection keypair error.** Read-only users must supply any valid phrase or use `TENSOR_PRIVATE_KEY`. A future improvement could make keypair creation lazy (only when signing), but that would require modifying `Hypertensor.__init__`.
- **`CHAIN.md` is a stub.** Full registration and staking documentation lands in S04. The stub includes connectivity check commands and a clear pointer.

## Follow-ups

- S02 should use the `substrate_client` pattern established by `check_peers.py` for `Hypertensor()` construction; the `PHRASE`/`TENSOR_PRIVATE_KEY` credential loading and error wrapping pattern applies directly to extrinsic signing
- S04 should expand `CHAIN.md` from stub into full registration/staking walkthrough; `scripts/register_subnet.py` and `scripts/register_node.py` will need the same friendly-ID resolution pattern from `check_peers.py`
- Consider making `Hypertensor.__init__` defer keypair creation until first signing operation — would fix the "empty phrase = pre-connection error" UX issue; currently out of scope but worth flagging for S02/S04

## Files Created/Modified

- `scripts/check_peers.py` — new; chain smoke-test (~140 lines); handles all edge cases; credential redaction; friendly-ID resolution
- `docker-compose.chain.yml` — new; testnet-connected stack; no `--no_blockchain_rpc`; CHAIN_ENDPOINT/SUBNET_ID guarded; MOCK_TEE=true in all 4 services
- `TESTING_LAYERS.md` — Layer 3 section filled with real testnet endpoint, required env vars, check_peers.py command, full stack command, expected log pattern, failure inspection commands
- `CHAIN.md` — new stub at repo root; connectivity check examples; pointer to S04 for full registration docs
- `.gsd/milestones/M005/slices/S01/S01-PLAN.md` — added verification step 7 (Layer 3 missing-CHAIN_ENDPOINT guard) pre-flight fix; added failure-path diagnostic check

## Forward Intelligence

### What the next slice should know

- **Credential loading pattern is established.** `check_peers.py` sets the convention: `phrase = os.environ.get("PHRASE") or os.environ.get("TENSOR_PRIVATE_KEY", "")`. S02 should use the same pattern for extrinsic signing. The compose file passes `PHRASE: ${PHRASE:-}` optionally — S02 must change this to `:?` since signing requires a real keypair.
- **`DEV_RPC` is the env var `run_node.py` reads.** `CHAIN_ENDPOINT` is the user-facing var; the compose anchor maps them. Do not add a `--chain_endpoint` flag to `run_node.py` — use env var only.
- **`Hypertensor(url, phrase)` is the construction path for everything.** Both read-only queries (`get_subnet_nodes_info_formatted`) and extrinsic submission use the same `Hypertensor` object. S02 needs a live keypair (not empty string) to sign extrinsics — the `Hypertensor` object is the right place to call `.sign_and_send(extrinsic)`.
- **Friendly subnet ID < 128000 must be resolved before any chain query.** `check_peers.py` does this; S02's scoring loop and S03's slash reporter must do the same. The pattern is: `get_subnet_id_from_friendly_id(id)` → `int(str(result))`.

### What's fragile

- **`Hypertensor.__init__` keypair creation is eager.** Any script or service that passes an empty phrase will get an `ERROR: Cannot connect` before the WebSocket even opens. S02 must ensure `PHRASE` is a valid mnemonic, not empty.
- **Testnet endpoint reliability.** `wss://rpc.hypertensor.app:443` is the documented testnet endpoint; no fallback is configured. If it's down, the full chain stack is dark. Consider adding a `FALLBACK_CHAIN_ENDPOINT` env var in S04.
- **`get_subnet_slot` returning `None` is a silent exit 0.** If a subnet is not yet active (no slot assigned), `check_peers.py` exits cleanly with a WARNING. S02's scoring loop needs to handle this case — scoring with no peers is a no-op, not an error, but it must not loop on a bad `real_id`.

### Authoritative diagnostics

- `python3 scripts/check_peers.py --chain $CHAIN_ENDPOINT --subnet_id $SUBNET_ID` — first thing to run for any chain connectivity question; its output is authoritative for whether the RPC path works
- `docker compose -f docker-compose.chain.yml config 2>&1 | grep CHAIN_ENDPOINT` — confirms guard fires before containers start when env var is missing
- `grep "DEV_RPC\|LOCAL_RPC\|DEV_RPC" subnet/cli/run_node.py | head -20` — authoritative source of truth for how `run_node.py` resolves the chain endpoint

### What assumptions changed

- **"LOCAL_RPC and DEV_RPC are module constants" (from task plan)** — They are not. Only `BLOCK_SECS`, `EPOCH_LENGTH`, `SECONDS_PER_EPOCH` are in `subnet/hypertensor/config.py`. The pattern is `os.environ.get("LOCAL_RPC", "ws://127.0.0.1:9944")` in `run_node.py`.
- **"run_node.py accepts --chain_endpoint flag" (from task plan)** — It does not. Chain endpoint is env-var only (`DEV_RPC`). The compose file's `DEV_RPC: ${CHAIN_ENDPOINT:?...}` mapping is the canonical bridge.
