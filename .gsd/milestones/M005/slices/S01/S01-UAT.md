# S01: Chain Peer Discovery — UAT

**Milestone:** M005
**Written:** 2026-03-17

## UAT Type

- UAT mode: artifact-driven + integration
- Why this mode is sufficient: All connectivity failure paths, credential redaction, and compose guard behaviour are machine-verifiable without a live testnet node. The live happy path (exit 0 + real peer rows) requires a running Hypertensor node and is deferred to testnet staging — it is called out explicitly as "requires live node" so a tester knows what to skip vs confirm.

## Preconditions

- Working directory: repo root (contains `scripts/check_peers.py`, `docker-compose.chain.yml`, `TESTING_LAYERS.md`, `CHAIN.md`)
- Python 3.x with `subnet` package importable (i.e. `pip install -e .` or existing dev env)
- Docker and Docker Compose installed and the daemon running
- No local Substrate/Hypertensor node running on port 9944 (for failure-path tests)
- `pytest` available in the environment

## Smoke Test

```bash
python3 scripts/check_peers.py --local_rpc --subnet_id 1 2>&1; echo "EXIT=$?"
```
**Expected:** Prints `ERROR: Cannot connect to ws://127.0.0.1:9944: ...` to stderr and exits 1. Confirms the script loads, resolves the endpoint, attempts connection, and fails fast with a clear message.

---

## Test Cases

### 1. Connection failure — local endpoint unreachable

```bash
python3 scripts/check_peers.py --local_rpc --subnet_id 1 2>&1
echo "EXIT=$?"
```

1. Run the command with no local Substrate node running.
2. **Expected:** stderr line starting with `ERROR: Cannot connect to ws://127.0.0.1:9944:` (any OS-level reason, e.g. `Connection refused`). Exit code = 1.

---

### 2. Connection failure — external unreachable host

```bash
python3 scripts/check_peers.py --chain wss://unreachable.example:443 --subnet_id 1 2>&1
echo "EXIT=$?"
```

1. Run against a guaranteed-unreachable hostname.
2. **Expected:** `ERROR: Cannot connect to wss://unreachable.example:443: [Errno -2] Name or service not known` (or equivalent DNS error). Exit code = 1.

---

### 3. Failure path is stderr-inspectable with ERROR: prefix

```bash
python3 scripts/check_peers.py --local_rpc --subnet_id 1 2>&1 | grep "^ERROR:"
```

1. Run and filter stderr output for lines starting with `ERROR:`.
2. **Expected:** At least one line printed — the line contains the offending URL (`ws://127.0.0.1:9944`). The `^ERROR:` prefix is machine-parseable for monitoring.

---

### 4. Credential redaction — PHRASE value never appears in any output

```bash
PHRASE="super secret mnemonic" python3 scripts/check_peers.py --local_rpc --subnet_id 1 2>&1 | grep -i "super secret"
echo "GREP_EXIT=$?"
```

1. Set `PHRASE` to a distinctive value and run.
2. Pipe all output (stdout + stderr combined) to grep searching for the phrase value.
3. **Expected:** No output from grep. `GREP_EXIT=1` (grep exits 1 when it finds nothing — this is the success condition for redaction). If grep prints anything or exits 0, the secret is leaking.

---

### 5. Credential redaction — TENSOR_PRIVATE_KEY also redacted

```bash
TENSOR_PRIVATE_KEY="another secret key" python3 scripts/check_peers.py --local_rpc --subnet_id 1 2>&1 | grep -i "another secret"
echo "GREP_EXIT=$?"
```

1. Use `TENSOR_PRIVATE_KEY` (fallback credential) instead of `PHRASE`.
2. **Expected:** `GREP_EXIT=1` — no output from grep. Confirms fallback credential is also never echoed.

---

### 6. Help text shows all three flags

```bash
python3 scripts/check_peers.py --help
```

1. Run with `--help`.
2. **Expected:** Output describes `--chain URL`, `--subnet_id INT`, and `--local_rpc` flags with descriptions. Exit code = 0.

---

### 7. docker-compose.chain.yml validates with env vars set

```bash
CHAIN_ENDPOINT=wss://rpc.hypertensor.app:443 SUBNET_ID=1 \
  docker compose -f docker-compose.chain.yml config > /dev/null
echo "COMPOSE_VALID=$?"
```

1. Supply required env vars and validate the compose file.
2. **Expected:** `COMPOSE_VALID=0` — no interpolation errors.

---

### 8. CHAIN_ENDPOINT guard fires when unset

```bash
docker compose -f docker-compose.chain.yml config 2>&1 | grep "CHAIN_ENDPOINT"
```

1. Run `docker compose config` without setting `CHAIN_ENDPOINT`.
2. **Expected:** Output contains `CHAIN_ENDPOINT` in an error message such as `required variable CHAIN_ENDPOINT is missing a value`. Docker Compose exits non-zero. No containers are started — misconfiguration surfaces before any service launches.

---

### 9. No --no_blockchain_rpc in chain compose

```bash
grep "no_blockchain_rpc" docker-compose.chain.yml
echo "GREP_EXIT=$?"
```

1. Search the chain compose file for the flag that would disable chain connectivity.
2. **Expected:** No output, `GREP_EXIT=1` — the flag is absent from all service command blocks.

---

### 10. MOCK_TEE=true in all node services

```bash
grep "MOCK_TEE" docker-compose.chain.yml | grep "true"
```

1. Count `MOCK_TEE=true` occurrences in the chain compose.
2. **Expected:** At least 4 lines (one per service: bootnode, validator, miner-1, miner-2). Confirms no EPYC hardware is required for testnet staging.

---

### 11. Layer 1 regression — pytest still green

```bash
pytest tests/ -x -q 2>&1 | tail -3
```

1. Run the full test suite with fail-fast.
2. **Expected:** Final line reports `183 passed, 1 skipped` (or more passed, same skipped). No failures or errors. Time should be under 30 seconds.

---

### 12. Layer 2 regression — tee-dev compose still valid

```bash
docker compose -f docker-compose.tee-dev.yml config > /dev/null
echo "LAYER2=$?"
```

1. Validate the existing Layer 2 compose file to confirm S01 changes did not break it.
2. **Expected:** `LAYER2=0` — compose file parses without error.

---

### 13. CHAIN.md exists at repo root

```bash
ls -la CHAIN.md && head -5 CHAIN.md
```

1. Check that `CHAIN.md` exists and has content.
2. **Expected:** File exists, size > 0. First few lines describe chain connectivity (not a blank file or placeholder).

---

### 14. TESTING_LAYERS.md Layer 3 section is populated (no placeholders)

```bash
grep "{{" TESTING_LAYERS.md
echo "GREP_EXIT=$?"
```

1. Check for unfilled template placeholders in TESTING_LAYERS.md.
2. **Expected:** No output, `GREP_EXIT=1` — all `{{...}}` placeholders have been replaced with real content.

```bash
grep "CHAIN_ENDPOINT\|check_peers\|rpc.hypertensor" TESTING_LAYERS.md | wc -l
```

3. Confirm Layer 3 section has real commands.
4. **Expected:** At least 3 lines — testnet endpoint, check_peers.py command, and compose command all appear.

---

## Edge Cases

### Friendly subnet_id below 128000

```bash
# With a live Hypertensor node at ws://127.0.0.1:9944:
python3 scripts/check_peers.py --local_rpc --subnet_id 5
```

1. Pass a friendly (< 128000) subnet ID.
2. **Expected:** Script calls `get_subnet_id_from_friendly_id(5)` before querying. If the node resolves it, proceeds to print peer list or "0 nodes registered". If resolution returns None, prints `WARNING: Friendly subnet_id 5 could not be resolved` and exits 0 (not a traceback).

### subnet_id ≥ 128000 (raw chain ID)

```bash
# With a live Hypertensor node at ws://127.0.0.1:9944:
python3 scripts/check_peers.py --local_rpc --subnet_id 130000
```

1. Pass a raw chain ID (≥ 128000).
2. **Expected:** Script skips the `get_subnet_id_from_friendly_id` branch and queries directly. Output is a peer list or "0 nodes registered" depending on chain state.

### --chain flag overrides --local_rpc

```bash
python3 scripts/check_peers.py --chain wss://rpc.hypertensor.app:443 --local_rpc --subnet_id 1 2>&1
```

1. Pass both `--chain` and `--local_rpc`.
2. **Expected:** `--chain` takes precedence. URL used is `wss://rpc.hypertensor.app:443`, not `ws://127.0.0.1:9944`. (Or the script uses argparse mutual exclusion and prints a usage error — either is acceptable; the phrase value must still not appear.)

### No credentials set — still attempts connection

```bash
unset PHRASE TENSOR_PRIVATE_KEY
python3 scripts/check_peers.py --local_rpc --subnet_id 1 2>&1
echo "EXIT=$?"
```

1. Run with no credentials in env.
2. **Expected:** Attempts to instantiate `Hypertensor(url, "")`. Either exits 1 with `ERROR: Cannot connect` (keypair creation fails before WebSocket) or exits 1 because the WebSocket is unreachable. In either case: no crash traceback printed to user, no credentials echoed (there are none), and exit code is 1.

---

## Failure Signals

- `AttributeError` or unhandled `Exception` traceback in script output → edge case not caught by try/except; a regression
- `PHRASE` or `TENSOR_PRIVATE_KEY` values appear in stdout or stderr → credential redaction failure; critical
- `--no_blockchain_rpc` appears in `docker-compose.chain.yml` → chain mode would be silently disabled; configuration regression
- `CHAIN_ENDPOINT` guard does NOT fire when `CHAIN_ENDPOINT` is unset (compose config exits 0) → misconfiguration silently passes; compose guard is broken
- `pytest tests/` reports any failure → Layer 1 regression introduced by S01 changes
- `docker compose -f docker-compose.tee-dev.yml config` exits non-zero → Layer 2 compose broken by S01 changes
- `{{` placeholders in `TESTING_LAYERS.md` → documentation was not actually updated

---

## Requirements Proved By This UAT

- R009 (chain peer discovery) — `check_peers.py` proves the Hypertensor RPC read path works end-to-end for all failure modes (connection refused, DNS failure, no slot). Full validation (exit 0 with real peer rows from live testnet) requires a registered subnet — deferred to testnet staging.

---

## Not Proven By This UAT

- **Live peer enumeration from a real registered subnet.** Test case 1–3 prove failure paths. The happy path (exit 0, prints "N nodes registered" with real rows) requires `CHAIN_ENDPOINT` pointing to a live Hypertensor node with a registered subnet. This is the testnet staging milestone proof.
- **`CHAIN_ENDPOINT` guard fires inside a running container.** The UAT confirms the compose config-time guard fires. Runtime guard (per-service shell `test -n "$CHAIN_ENDPOINT"`) would require actually starting a container without the env var set — not covered here.
- **Scoring loop uses chain peer list.** S01 delivers the RPC read path; S02 wires it into the validator's scoring loop as the epoch source of truth. The S02 UAT will prove that.

---

## Notes for Tester

- Tests 1–14 are fully automated and don't require a live Hypertensor node. Run them in sequence; expected total runtime is under 2 minutes.
- Test 11 (pytest) takes ~5-10 seconds. The `183 passed` count may increase in later milestones — any increase is fine, but failures are a regression.
- The `GREP_EXIT=1` success condition in redaction tests (tests 4 and 5) is intentional: grep exits 1 when it finds nothing, which is the desired outcome.
- Tests requiring a live node (edge cases, happy-path connectivity) should be deferred to testnet staging. Note what environment they were run in and what endpoint was used.
- `docker-compose.chain.yml` uses `MOCK_TEE=true` — you do NOT need AMD EPYC or Intel TDX hardware to run the full chain stack. Only an accessible Hypertensor testnet endpoint is required.
