---
id: T02
parent: S01
milestone: M005
provides:
  - docker-compose.chain.yml testnet-connected Docker Compose stack
  - TESTING_LAYERS.md Layer 3 section with real commands and observability runbook
  - CHAIN.md stub at repo root
  - S01-PLAN.md updated with failure-path diagnostic check (pre-flight fix)
key_files:
  - docker-compose.chain.yml
  - TESTING_LAYERS.md
  - CHAIN.md
  - .gsd/milestones/M005/slices/S01/S01-PLAN.md
key_decisions:
  - DEV_RPC (not CHAIN_ENDPOINT) is what run_node.py reads for the chain WebSocket URL; docker-compose.chain.yml maps DEV_RPC=${CHAIN_ENDPOINT:?...} so the user-facing env var (CHAIN_ENDPOINT) differs from the internal one (DEV_RPC)
  - CHAIN_ENDPOINT and SUBNET_ID use :? guard syntax so Docker Compose aborts with a clear error before any container starts if they are unset
  - PHRASE and TENSOR_PRIVATE_KEY use :- (optional) because read-only queries work without them and only signing extrinsics requires a key
  - mock-chain volume removed from chain compose — not needed when connected to real chain
  - Shell guard (test -n "$$CHAIN_ENDPOINT" || ...) added per-service as belt-and-suspenders in addition to the x-chain-env anchor guard
patterns_established:
  - Map user-facing env vars to internal run_node.py env vars in the compose anchor (DEV_RPC = CHAIN_ENDPOINT); this keeps the user API stable if internal var names change
  - Use :? guard in x-chain-env anchor for required vars — single definition enforces presence across all services without repeating it
observability_surfaces:
  - "docker compose -f docker-compose.chain.yml config 2>&1 | grep CHAIN_ENDPOINT — shows :? guard error when CHAIN_ENDPOINT is unset, confirming misconfiguration surfaces before containers start"
  - "docker compose -f docker-compose.chain.yml logs bootnode 2>&1 | grep 'ERROR:\\|Cannot connect' — shows WebSocket error if CHAIN_ENDPOINT is set to an unreachable endpoint"
  - "python scripts/check_peers.py --chain $CHAIN_ENDPOINT --subnet_id $SUBNET_ID — pre-flight connectivity check before running the full stack"
duration: 25m
verification_result: passed
completed_at: 2026-03-17
blocker_discovered: false
---

# T02: Add `docker-compose.chain.yml` and update `TESTING_LAYERS.md`

**Created `docker-compose.chain.yml` (testnet-connected Docker Compose stack), updated `TESTING_LAYERS.md` Layer 3 with real commands and failure-state runbook, and created `CHAIN.md` stub.**

## What Happened

Read `docker-compose.tee-dev.yml` and `run_node.py` to understand the base stack and how chain connectivity is configured. Key finding: `run_node.py` reads `DEV_RPC` (not `CHAIN_ENDPOINT`) from env for the chain WebSocket URL. The compose file maps `DEV_RPC: ${CHAIN_ENDPOINT:?...}` so the user-facing var is `CHAIN_ENDPOINT` and the internal var stays as-is.

Created `docker-compose.chain.yml` by cloning the tee-dev stack with:
- All `--no_blockchain_rpc` flags removed from every service command
- `x-chain-env` anchor with `CHAIN_ENDPOINT`/`SUBNET_ID` `:?` guards and `PHRASE`/`TENSOR_PRIVATE_KEY` `:-` optionals
- `MOCK_TEE=true` inherited by all services — no EPYC hardware needed
- `mock-chain` volume removed (irrelevant in real-chain mode); fresh named volumes for persistence
- Per-service shell guard (`test -n "$$CHAIN_ENDPOINT"`) as belt-and-suspenders

Updated `TESTING_LAYERS.md` Layer 3 section: replaced placeholder stub with real testnet endpoint, required env vars, step-0 connectivity check via `scripts/check_peers.py`, full `docker compose -f docker-compose.chain.yml up` command, expected validator log pattern, and failure-state inspection commands.

Created `CHAIN.md` at repo root with connectivity check examples and pointer to S04 for full registration/staking docs.

Fixed S01-PLAN.md pre-flight issue: added verification step 7 to check that the Layer 3 missing-CHAIN_ENDPOINT guard fires with a clear message (not silently).

## Verification

```
# Compose validates:
CHAIN_ENDPOINT=wss://rpc.hypertensor.app:443 SUBNET_ID=1 \
  docker compose -f docker-compose.chain.yml config > /dev/null
→ OK

# No --no_blockchain_rpc in chain compose:
grep "no_blockchain_rpc" docker-compose.chain.yml
→ OK: flag absent

# CHAIN_ENDPOINT unset → clear error, non-zero exit:
docker compose -f docker-compose.chain.yml config 2>&1 | grep -i "CHAIN_ENDPOINT"
→ "error while interpolating x-chain-env.DEV_RPC: required variable CHAIN_ENDPOINT is missing..."

# MOCK_TEE=true in all 4 services:
grep "MOCK_TEE" docker-compose.chain.yml | grep "true"
→ 4 matches

# No placeholders in TESTING_LAYERS.md:
grep "{{" TESTING_LAYERS.md
→ OK: no placeholders

# CHAIN.md exists:
ls CHAIN.md → OK

# Layer 1 regression:
pytest tests/ -x -q → 183 passed, 1 skipped

# Layer 2 compose still valid:
docker compose -f docker-compose.tee-dev.yml config → OK

# Slice check 2 (exits 1 on unreachable):
python3 scripts/check_peers.py --chain wss://unreachable.example:443 --subnet_id 1
→ ERROR: Cannot connect ..., exit=1

# Slice check 3 (failure path inspectable):
python3 scripts/check_peers.py --local_rpc --subnet_id 1 2>&1 | grep "^ERROR:"
→ ERROR: Cannot connect to ws://127.0.0.1:9944: [Errno 111] Connection refused

# Slice check 4 (credential redaction):
PHRASE="super secret mnemonic" python3 scripts/check_peers.py --local_rpc --subnet_id 1 2>&1 | grep -i "super secret"
→ no output (grep exit=1 — redaction confirmed)
```

## Diagnostics

- `docker compose -f docker-compose.chain.yml config 2>&1 | grep CHAIN_ENDPOINT` — confirms missing-var guard fires before containers start
- `python scripts/check_peers.py --chain $CHAIN_ENDPOINT --subnet_id $SUBNET_ID` — Step 0 connectivity check before running the full stack
- `docker compose -f docker-compose.chain.yml logs <service> 2>&1 | grep "ERROR:\|Cannot connect"` — surfaces WebSocket failures at node startup
- `CHAIN_ENDPOINT=... SUBNET_ID=... docker compose -f docker-compose.chain.yml config > /dev/null && echo "OK"` — validates compose file with env vars set

## Deviations

- `run_node.py` does not accept `--chain_endpoint` flag; it reads `DEV_RPC` from env. The compose file maps `DEV_RPC=${CHAIN_ENDPOINT}` so the user-facing var is stable. Task plan step 3 mentioned checking whether flags or env vars are used — confirmed: env var only.
- `mock-chain` volume removed from chain compose (it backed the `MockChainDB` which is irrelevant when using the real chain). The task plan didn't mention this but it would cause confusion to include it.
- Miner `TAMPER_RATE` changed from `1.0`/`0.001` (tee-dev demo values) to `0.001`/`0.001` in chain compose — production-appropriate defaults for testnet staging.

## Known Issues

None.

## Files Created/Modified

- `docker-compose.chain.yml` — new; testnet-connected stack, no --no_blockchain_rpc, CHAIN_ENDPOINT/SUBNET_ID guarded, MOCK_TEE=true in all services
- `TESTING_LAYERS.md` — Layer 3 section replaced with real commands, endpoints, expected output, and failure-state inspection
- `CHAIN.md` — new stub at repo root with connectivity check and pointer to S04
- `.gsd/milestones/M005/slices/S01/S01-PLAN.md` — added verification step 7 (Layer 3 missing-CHAIN_ENDPOINT guard) to satisfy pre-flight diagnostic check requirement
