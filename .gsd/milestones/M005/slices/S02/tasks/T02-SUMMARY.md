---
id: T02
parent: S02
milestone: M005
provides:
  - scripts/check_scores.py verification CLI querying SubnetConsensusSubmission for a given epoch
  - docker-compose.chain.yml per-node PHRASE vars with :? guards for validator, miner-1, miner-2
key_files:
  - scripts/check_scores.py
  - docker-compose.chain.yml
key_decisions:
  - x-chain-env anchor PHRASE set to "" (empty literal) so bootnode stays optional; per-service overrides take precedence for signing nodes
  - check_scores.py WARN path exits 0 (not 1) for empty/None result — distinguishes "epoch not finalised" from connection failure
patterns_established:
  - check_scores.py mirrors check_peers.py credential loading (PHRASE / TENSOR_PRIVATE_KEY), friendly-ID resolution, ERROR:/exit-1 connection failure, and URL precedence exactly
  - docker-compose per-service PHRASE override pattern: add PHRASE key in environment block after <<: *chain-env to override the anchor value
observability_surfaces:
  - "python3 scripts/check_scores.py --chain $CHAIN_ENDPOINT --subnet_id $SUBNET_ID --epoch $EPOCH → [OK] N entries / [WARN] No scores found / ERROR: Cannot connect"
  - "docker compose -f docker-compose.chain.yml config → fails fast with 'required variable VALIDATOR_PHRASE is missing' when credentials absent"
duration: ~20m
verification_result: passed
completed_at: 2026-03-17
blocker_discovered: false
---

# T02: Add check_scores.py verification script and compose per-node credentials

**Created `scripts/check_scores.py` querying `SubnetConsensusSubmission` and hardened `docker-compose.chain.yml` with per-node `:?`-guarded PHRASE vars for validator and miners.**

## What Happened

**`scripts/check_scores.py`** mirrors `check_peers.py` exactly: same credential loading (`PHRASE`/`TENSOR_PRIVATE_KEY` from env, never echoed), same friendly-ID resolution (`< 128000` → `get_subnet_id_from_friendly_id` → `int(str(result))`), same `ERROR: Cannot connect to {url}: {exc}` + exit 1 on connection failure. Adds `--epoch INT` (required) argument. Calls `hypertensor.get_rewards_submission(real_id, epoch)` and handles None/empty SCALE result as `[WARN] No scores found for epoch N` (exit 0), non-empty as `[OK] Scores found for epoch N: {N} entries` (exit 0).

**`docker-compose.chain.yml`** changes: (1) header comment updated to document `VALIDATOR_PHRASE`, `MINER1_PHRASE`, `MINER2_PHRASE` as required vars; (2) `x-chain-env` anchor `PHRASE` changed from `${PHRASE:-}` to `""` so bootnode stays optional and per-service overrides are authoritative; (3) validator, miner-1, miner-2 services each have `PHRASE: ${SERVICE_PHRASE:?...}` added in their `environment:` block with a descriptive error message; (4) bootnode left unchanged (does not sign extrinsics).

## Verification

All 6 slice-level checks passed:

```
# check_scores.py exits 1 on connection failure
python3 scripts/check_scores.py --local_rpc --subnet_id 1 --epoch 0 2>&1; echo EXIT=$?
→ ERROR: Cannot connect to ws://127.0.0.1:9944: [Errno 111] Connection refused
→ EXIT=1  ✅

# credential redaction
PHRASE="super secret mnemonic" python3 scripts/check_scores.py --local_rpc --subnet_id 1 --epoch 0 2>&1 | grep -i "super secret"; echo GREP_EXIT=$?
→ GREP_EXIT=1  ✅

# compose guard fires on missing VALIDATOR_PHRASE
CHAIN_ENDPOINT=wss://... SUBNET_ID=1 docker compose -f docker-compose.chain.yml config 2>&1 | grep -i "VALIDATOR_PHRASE"
→ error while interpolating services.validator.environment.PHRASE: required variable VALIDATOR_PHRASE is missing ...  ✅

# compose validates with all vars set
CHAIN_ENDPOINT=... SUBNET_ID=1 VALIDATOR_PHRASE="word" MINER1_PHRASE="word" MINER2_PHRASE="word" docker compose -f docker-compose.chain.yml config > /dev/null; echo EXIT=$?
→ EXIT=0  ✅

# Layer 2 unaffected
docker compose -f docker-compose.tee-dev.yml config > /dev/null; echo EXIT=$?
→ EXIT=0  ✅

# Layer 1 still green
pytest tests/ -x -q
→ 188 passed, 1 skipped  ✅
```

## Diagnostics

- `python3 scripts/check_scores.py --chain $CHAIN_ENDPOINT --subnet_id $SUBNET_ID --epoch $EPOCH` — authoritative check for whether scores landed on-chain; run after stack reaches first epoch
- `[OK] Scores found for epoch N: N entries` + one line per `subnet_node_id/score` confirms submission
- `[WARN] No scores found for epoch N` (exit 0) means epoch not yet finalised or validator hasn't submitted
- `ERROR: Cannot connect to ...` (exit 1) means chain unreachable or bad URL
- Credentials (`VALIDATOR_PHRASE`, `MINER1_PHRASE`, `MINER2_PHRASE`, `PHRASE`, `TENSOR_PRIVATE_KEY`) are loaded from env into local vars only and never appear in any output

## Deviations

None — implemented exactly as planned.

## Known Issues

None.

## Files Created/Modified

- `scripts/check_scores.py` — new; ~155 lines; queries SubnetConsensusSubmission; all check_peers.py patterns applied
- `docker-compose.chain.yml` — modified; header comment updated; x-chain-env anchor PHRASE changed to ""; validator/miner-1/miner-2 get per-service PHRASE :? guards; bootnode left optional
