---
estimated_steps: 8
estimated_files: 2
---

# T02: Add check_scores.py verification script and compose per-node credentials

**Slice:** S02 — Score Submission Extrinsic
**Milestone:** M005

## Description

Two deliverables in one task — both are small pattern-following work with no internal dependency:

1. **`scripts/check_scores.py`** — queries `SubnetConsensusSubmission` for a given epoch to verify scores landed on-chain. This is the primary S02 slice verification artifact. Mirrors `check_peers.py` patterns exactly: credential redaction, friendly-ID resolution, `ERROR:` prefix on stderr + exit 1 for connection failures, `[OK]` prefix on stdout for success.

2. **`docker-compose.chain.yml` per-node credential hardening** — the current compose passes a single `PHRASE: ${PHRASE:-}` (optional) to all 4 services via the `x-chain-env` anchor. All 4 nodes would sign as the same hotkey. Change to per-service `PHRASE` overrides with `:?` guards for the validator and miners (they sign extrinsics), leave bootnode optional.

**Key patterns from `check_peers.py`:**
- Credentials loaded: `phrase = os.environ.get("PHRASE") or os.environ.get("TENSOR_PRIVATE_KEY") or ""`
- Friendly-ID resolution: `if subnet_id < 128000: real_id = int(str(hypertensor.get_subnet_id_from_friendly_id(subnet_id)))`
- Connection failure: `try: hypertensor = Hypertensor(url, phrase) except Exception as exc: print(f"ERROR: Cannot connect to {url}: {exc}", file=sys.stderr); sys.exit(1)`
- RPC URL resolution: `--local_rpc` > `--chain` arg > `$DEV_RPC` env var > hardcoded default

## Steps

1. **Create `scripts/check_scores.py`:**

   Add `--epoch INT` required argument alongside the existing `--subnet_id`, `--chain`, `--local_rpc` args from `check_peers.py`.

   After connecting and resolving `real_id`, call:
   ```python
   result = hypertensor.get_rewards_submission(real_id, args.epoch)
   ```
   `get_rewards_submission` is at `chain_functions.py` ~line 1431; it queries `"Network"`, `"SubnetConsensusSubmission"`, `[subnet_id, epoch]`.

   Output format:
   - If `result is None` or the SCALE value is empty/None: print `[WARN] No scores found for epoch {epoch}` to stdout; exit 0
   - If result has entries: print `[OK] Scores found for epoch {epoch}: {N} entries` + one line per entry; exit 0
   - Connection failure: `ERROR: Cannot connect to {url}: {exc}` to stderr; exit 1

   The `result` from `get_rewards_submission` is a SCALE object. Print `str(result)` to inspect. If it has a `.value` attribute (SCALE decoded dict), iterate over entries. The exact structure will be visible in the raw SCALE output — print it clearly so a future agent can parse it.

   Use this pattern for result inspection (works for SCALE objects with or without decoded value):
   ```python
   if result is None or result.value is None:
       print(f"[WARN] No scores found for epoch {epoch}", flush=True)
       sys.exit(0)
   value = result.value
   if isinstance(value, dict):
       entries = value.get("data", [])
   elif isinstance(value, list):
       entries = value
   else:
       entries = []
   print(f"[OK] Scores found for epoch {epoch}: {len(entries)} entries")
   for entry in entries:
       print(f"  subnet_node_id={entry.get('subnet_node_id', '?')}  score={entry.get('score', '?')}")
   ```

2. **Verify check_scores.py error path** — `python3 scripts/check_scores.py --local_rpc --subnet_id 1 --epoch 0 2>&1; echo EXIT=$?` must print `ERROR: Cannot connect to ws://127.0.0.1:9944: ...` and exit 1.

3. **Verify credential redaction** — `PHRASE="super secret mnemonic" python3 scripts/check_scores.py --local_rpc --subnet_id 1 --epoch 0 2>&1 | grep -i "super secret"; echo GREP_EXIT=$?` must output `GREP_EXIT=1`.

4. **Update `docker-compose.chain.yml`** per-service PHRASE overrides:

   In the `x-chain-env` anchor, change `PHRASE: ${PHRASE:-}` to `PHRASE: ""` (or remove it entirely — the per-service overrides below will take precedence). Keep `TENSOR_PRIVATE_KEY: ${TENSOR_PRIVATE_KEY:-}` in the anchor since it's an alternative to PHRASE and can remain optional.

   In each service's `environment:` block, add a per-service override *after* `<<: *chain-env`:
   - `validator`: `PHRASE: ${VALIDATOR_PHRASE:?VALIDATOR_PHRASE is required (validator signs propose_attestation extrinsics)}`
   - `miner-1`: `PHRASE: ${MINER1_PHRASE:?MINER1_PHRASE is required (miner-1 signs attest extrinsics)}`
   - `miner-2`: `PHRASE: ${MINER2_PHRASE:?MINER2_PHRASE is required (miner-2 signs attest extrinsics)}`
   - `bootnode`: leave as-is (bootnode does not sign extrinsics)

   Update the compose header comment block to document the new env vars:
   ```
   # Required environment variables:
   #   CHAIN_ENDPOINT     — Hypertensor testnet WebSocket URL
   #   SUBNET_ID          — Subnet friendly ID
   #   VALIDATOR_PHRASE   — Mnemonic for the validator node (signs propose_attestation)
   #   MINER1_PHRASE      — Mnemonic for miner-1 (signs attest)
   #   MINER2_PHRASE      — Mnemonic for miner-2 (signs attest)
   #
   # Optional:
   #   TENSOR_PRIVATE_KEY — Alternative to PHRASE for any service
   ```

5. **Verify compose guard fires** — `CHAIN_ENDPOINT=wss://rpc.hypertensor.app:443 SUBNET_ID=1 docker compose -f docker-compose.chain.yml config 2>&1 | grep -i "VALIDATOR_PHRASE"` must show the `:?` error message.

6. **Verify compose validates with all vars** — `CHAIN_ENDPOINT=wss://rpc.hypertensor.app:443 SUBNET_ID=1 VALIDATOR_PHRASE="word" MINER1_PHRASE="word" MINER2_PHRASE="word" docker compose -f docker-compose.chain.yml config > /dev/null; echo EXIT=$?` must exit 0.

7. **Verify Layer 2 unaffected** — `docker compose -f docker-compose.tee-dev.yml config > /dev/null; echo EXIT=$?` must exit 0.

8. **Verify Layer 1 still green** — `pytest tests/ -x -q` → 183+ passed.

## Must-Haves

- [ ] `check_scores.py` accepts `--chain URL`, `--local_rpc`, `--subnet_id INT`, `--epoch INT` (epoch is required)
- [ ] `check_scores.py` uses credential redaction: `phrase = os.environ.get("PHRASE") or os.environ.get("TENSOR_PRIVATE_KEY") or ""`; phrase is NEVER passed to print/log
- [ ] `check_scores.py` resolves friendly subnet IDs < 128000 via `get_subnet_id_from_friendly_id` → `int(str(result))`
- [ ] `check_scores.py` exits 1 with `ERROR: Cannot connect to {url}: ...` on stderr for connection failures
- [ ] `check_scores.py` exits 0 with `[WARN] No scores found for epoch N` if result is None/empty
- [ ] `check_scores.py` exits 0 with `[OK] Scores found for epoch N: N entries` if result has data
- [ ] compose `validator` service uses `PHRASE: ${VALIDATOR_PHRASE:?...}` override
- [ ] compose `miner-1` service uses `PHRASE: ${MINER1_PHRASE:?...}` override
- [ ] compose `miner-2` service uses `PHRASE: ${MINER2_PHRASE:?...}` override
- [ ] compose header comment block updated to document new required vars
- [ ] `docker-compose.tee-dev.yml` is not modified

## Verification

```bash
# check_scores.py exits 1 on connection failure
python3 scripts/check_scores.py --local_rpc --subnet_id 1 --epoch 0 2>&1; echo EXIT=$?
# → ERROR: Cannot connect to ws://127.0.0.1:9944: ...
# → EXIT=1

# credential redaction
PHRASE="super secret mnemonic" python3 scripts/check_scores.py --local_rpc --subnet_id 1 --epoch 0 2>&1 \
  | grep -i "super secret"; echo GREP_EXIT=$?
# → GREP_EXIT=1

# compose guard fires on missing VALIDATOR_PHRASE
CHAIN_ENDPOINT=wss://rpc.hypertensor.app:443 SUBNET_ID=1 \
  docker compose -f docker-compose.chain.yml config 2>&1 | grep -i "VALIDATOR_PHRASE"
# → error: required variable VALIDATOR_PHRASE is missing ...

# compose validates with all vars
CHAIN_ENDPOINT=wss://rpc.hypertensor.app:443 SUBNET_ID=1 \
  VALIDATOR_PHRASE="word word word" MINER1_PHRASE="word word word" MINER2_PHRASE="word word word" \
  docker compose -f docker-compose.chain.yml config > /dev/null; echo EXIT=$?
# → EXIT=0

# Layer 2 unaffected
docker compose -f docker-compose.tee-dev.yml config > /dev/null; echo EXIT=$?
# → EXIT=0

# Layer 1 still green
pytest tests/ -x -q
# → 183+ passed, 0 failed
```

## Observability Impact

- Signals added/changed: `check_scores.py` provides a CLI inspection surface for chain score state — prints `[OK]` / `[WARN]` / `ERROR:` lines that are parseable by grep; per-node PHRASE in compose ensures each node appears as a distinct hotkey in block explorer
- How a future agent inspects this: `python3 scripts/check_scores.py --chain $CHAIN_ENDPOINT --subnet_id $SUBNET_ID --epoch $EPOCH` — authoritative for whether scores landed; run after compose stack reaches first epoch
- Failure state exposed: `[WARN] No scores found` exit 0 distinguishes "epoch not yet finalised" from connection failure (exit 1)

## Inputs

- `scripts/check_peers.py` — canonical pattern for credential redaction, friendly-ID resolution, error exits, URL resolution; copy structure exactly
- `subnet/hypertensor/chain_functions.py` ~line 1431 — `get_rewards_submission(subnet_id, epoch)` queries `"Network"`, `"SubnetConsensusSubmission"`, `[subnet_id, epoch]`; returns a SCALE result object
- `docker-compose.chain.yml` — current file to be updated; `x-chain-env` anchor at top; 4 service blocks
- S01 Forward Intelligence — `PHRASE`/`TENSOR_PRIVATE_KEY` credential loading pattern; `CHAIN_ENDPOINT` → `DEV_RPC` mapping is already correct; only PHRASE needs per-service override

## Expected Output

- `scripts/check_scores.py` — new; ~120 lines; query `SubnetConsensusSubmission` for given epoch; all `check_peers.py` patterns applied; credential redaction confirmed
- `docker-compose.chain.yml` — modified; `validator`, `miner-1`, `miner-2` services each have `PHRASE: ${SERVICEn_PHRASE:?...}` in their `environment:` block; header comment updated
