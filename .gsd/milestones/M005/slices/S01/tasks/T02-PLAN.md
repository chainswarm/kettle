---
estimated_steps: 5
estimated_files: 4
---

# T02: Add `docker-compose.chain.yml` and update `TESTING_LAYERS.md`

**Slice:** S01 — Chain Peer Discovery
**Milestone:** M005

## Description

Wire the full node Docker Compose stack to optionally run against the Hypertensor testnet. Create `docker-compose.chain.yml` as a testnet-ready variant of `docker-compose.tee-dev.yml`: it drops `--no_blockchain_rpc` from all node commands and reads `CHAIN_ENDPOINT`, `SUBNET_ID`, and `PHRASE`/`TENSOR_PRIVATE_KEY` from env. `MOCK_TEE=true` stays — no EPYC hardware needed. Then update `TESTING_LAYERS.md` to fill the Layer 3 section with real commands, and create a minimal `CHAIN.md` stub.

## Steps

1. **Copy `docker-compose.tee-dev.yml` to `docker-compose.chain.yml`**. Diff the two files conceptually — the only changes needed are: (a) remove `--no_blockchain_rpc` from every service's `command:`; (b) add env var pass-through for `CHAIN_ENDPOINT`, `SUBNET_ID`, `PHRASE` / `TENSOR_PRIVATE_KEY`; (c) add a startup guard.

2. **Remove `--no_blockchain_rpc`** from the `command:` line of every service in `docker-compose.chain.yml` that starts a node process. Use `grep -n "no_blockchain_rpc" docker-compose.tee-dev.yml` to find all occurrences, then remove each one from the chain variant.

3. **Add env var pass-through and startup guard** to each node service's `environment:` block:
   ```yaml
   environment:
     CHAIN_ENDPOINT: ${CHAIN_ENDPOINT:?CHAIN_ENDPOINT is required for chain mode}
     SUBNET_ID: ${SUBNET_ID:?SUBNET_ID is required for chain mode}
     PHRASE: ${PHRASE:-}
     TENSOR_PRIVATE_KEY: ${TENSOR_PRIVATE_KEY:-}
     MOCK_TEE: "true"
   ```
   The `${VAR:?message}` syntax causes Docker Compose to abort with an error message if the variable is unset. `PHRASE` and `TENSOR_PRIVATE_KEY` are optional individually (the node reads them internally).
   Also ensure each node's `command:` passes `--chain_endpoint $CHAIN_ENDPOINT` and `--subnet_id $SUBNET_ID` (or verify that the node reads these from env directly — check `run_node.py`'s arg parsing to confirm which approach is used). If the node reads from env already, no command flag change is needed beyond removing `--no_blockchain_rpc`.

4. **Update `TESTING_LAYERS.md` Layer 3 section** with:
   - Required env vars (`CHAIN_ENDPOINT`, `SUBNET_ID`, `PHRASE`)
   - Connectivity check: `python scripts/check_peers.py --chain $CHAIN_ENDPOINT --subnet_id $SUBNET_ID`
   - Full stack command: `CHAIN_ENDPOINT=wss://rpc.hypertensor.app:443 SUBNET_ID=1 PHRASE="..." docker compose -f docker-compose.chain.yml up`
   - Expected validator log pattern: `"Synced: epoch=N, pct=..."` with real chain epoch numbers
   - Note that `MOCK_TEE=true` is built-in — no AMD EPYC hardware required for testnet staging

5. **Create `CHAIN.md`** stub at the repo root:
   ```markdown
   # Chain Integration

   > Full registration, staking, running, and monitoring docs will be added in M005/S04.

   ## Quick connectivity check

   ```bash
   python scripts/check_peers.py \
     --chain wss://rpc.hypertensor.app:443 \
     --subnet_id <SUBNET_ID>
   ```

   ## Running against testnet

   See `TESTING_LAYERS.md` → Layer 3 section for full commands.
   ```

## Must-Haves

- [ ] `docker compose -f docker-compose.chain.yml config` exits 0 (valid YAML/schema)
- [ ] `grep "no_blockchain_rpc" docker-compose.chain.yml` returns empty (none present)
- [ ] `CHAIN_ENDPOINT` unset causes `docker compose -f docker-compose.chain.yml config` or `up` to fail with a clear message (not silently use empty string)
- [ ] `MOCK_TEE=true` is set in all node services in `docker-compose.chain.yml`
- [ ] `TESTING_LAYERS.md` Layer 3 section contains real endpoint, commands, and expected output — no placeholder text remains
- [ ] `CHAIN.md` exists at repo root with stub content
- [ ] `pytest tests/ -x -q` still green (no regressions from file changes)

## Verification

```bash
# Compose file is valid:
docker compose -f docker-compose.chain.yml config > /dev/null && echo "OK"

# No_blockchain_rpc is gone from chain compose:
grep "no_blockchain_rpc" docker-compose.chain.yml && echo "FAIL: flag found" || echo "OK: flag absent"

# Missing CHAIN_ENDPOINT produces an error (not silent):
docker compose -f docker-compose.chain.yml config 2>&1 | grep -i "CHAIN_ENDPOINT" || true
# (Will show the :? error message when CHAIN_ENDPOINT is unset)

# MOCK_TEE is present:
grep "MOCK_TEE" docker-compose.chain.yml | grep "true"

# Layer 3 section updated (no more placeholder text):
grep -i "{{" TESTING_LAYERS.md && echo "FAIL: placeholder found" || echo "OK"

# Layer 1 regression check:
pytest tests/ -x -q
```

## Inputs

- `docker-compose.tee-dev.yml` — base file to clone. Read it carefully before editing. Note all service names and which ones run node processes (bootnode, validator, miner-*). Preserve healthcheck and volume config unchanged.
- `T01-PLAN.md` summary / `scripts/check_peers.py` — produced by T01. Reference its `--chain` and `--subnet_id` flags in the TESTING_LAYERS.md commands.
- `TESTING_LAYERS.md` — existing file. Find the Layer 3 section and replace placeholder content with real instructions.
- `run_node.py` — check whether `CHAIN_ENDPOINT` is already read from env (look for `os.getenv("CHAIN_ENDPOINT")` or an `--chain_endpoint` arg in `argparse`). This determines whether the chain compose file needs to pass it as a command flag or just as an env var.

## Observability Impact

- Signals added/changed: `CHAIN_ENDPOINT unset` error surfaces at `docker compose up` time (before any container starts), preventing silent misconfiguration
- How a future agent inspects this: `docker compose -f docker-compose.chain.yml config` validates env var presence; `TESTING_LAYERS.md` Layer 3 section is the operational runbook
- Failure state exposed: if `CHAIN_ENDPOINT` is wrong, `Hypertensor.__init__` raises at node startup — node container exits with a clear WebSocket error in its logs

## Expected Output

- `docker-compose.chain.yml` — new file; valid compose YAML; no `--no_blockchain_rpc`; env-var guarded
- `TESTING_LAYERS.md` — Layer 3 section updated with real commands
- `CHAIN.md` — new stub file at repo root
