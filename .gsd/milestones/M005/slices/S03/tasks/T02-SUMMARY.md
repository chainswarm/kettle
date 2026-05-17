---
id: T02
parent: S03
milestone: M005
provides:
  - scripts/check_slash.py diagnostic script querying overwatch commits and reveals on-chain
  - OVERWATCH_PHRASE :? compose guard on validator service in docker-compose.chain.yml
  - OVERWATCH_NODE_ID optional pass-through in validator service environment
key_files:
  - scripts/check_slash.py
  - docker-compose.chain.yml
key_decisions:
  - check_slash.py credential redaction mirrors check_scores.py exactly — PHRASE/TENSOR_PRIVATE_KEY read from env, never echoed in stdout or stderr
  - OVERWATCH_PHRASE added as required (:?) guard rather than optional (:-) to force explicit credential provisioning even if OVERWATCH_NODE_ID is later added; operators must set it consciously
  - OVERWATCH_NODE_ID added as optional pass-through (${OVERWATCH_NODE_ID:-}) so the reporter guard in _overwatch_epoch_loop works without breaking MOCK_TEE mode where node ID is absent
patterns_established:
  - Diagnostic scripts follow check_scores.py template exactly: URL precedence (--local_rpc > --chain > $DEV_RPC > hardcoded default), EXIT=1 on connection failure, PHRASE/TENSOR_PRIVATE_KEY from env only, [OK]/[WARN] output to stdout
  - Compose credential guards use :? syntax for required vars and :- for optional pass-throughs; header comment documents all vars with purpose and optionality
observability_surfaces:
  - "python3 scripts/check_slash.py --chain $CHAIN_ENDPOINT --overwatch_node_id $OVERWATCH_NODE_ID --epoch $EPOCH → [OK] N commit(s) / [OK] N reveal(s) confirms slash landed on chain; [WARN] No commits found means slash not yet fired or epoch too old; EXIT=1 means RPC unreachable"
  - "docker compose -f docker-compose.chain.yml config → fails with 'required variable OVERWATCH_PHRASE is missing' if guard triggers; EXIT=0 confirms all required vars are set"
duration: 20m
verification_result: passed
completed_at: 2026-03-17
blocker_discovered: false
---

# T02: Add check_slash.py diagnostic script and OVERWATCH_PHRASE compose guard

**Created `scripts/check_slash.py` (queries on-chain overwatch commits+reveals) and added `OVERWATCH_PHRASE` :? guard + `OVERWATCH_NODE_ID` pass-through to the validator service in `docker-compose.chain.yml`.**

## What Happened

Created `scripts/check_slash.py` following the `check_scores.py` template exactly. The script accepts `--overwatch_node_id INT` and `--epoch INT` as required arguments, resolves the RPC URL with the same precedence chain (`--local_rpc > --chain > $DEV_RPC > hardcoded default`), reads credentials from `PHRASE`/`TENSOR_PRIVATE_KEY` env vars only (never echoed), and prints `[OK] N commit(s)` / `[WARN] No commits found` for both commits and reveals results. Connection failure exits with code 1 and `ERROR: Cannot connect to {url}: ...` on stderr.

Updated `docker-compose.chain.yml` in two places:
1. Header comment: added `OVERWATCH_PHRASE` to the required variables list with explanation; added `OVERWATCH_NODE_ID` to the optional section; updated the usage example `docker compose up` command to include `OVERWATCH_PHRASE`.
2. Validator service `environment:` block: added `OVERWATCH_PHRASE: ${OVERWATCH_PHRASE:?...}` guard and `OVERWATCH_NODE_ID: ${OVERWATCH_NODE_ID:-}` optional pass-through immediately after the existing `PHRASE:` line.

Pre-flight fixes applied: added `## Observability Impact` section to T02-PLAN.md documenting the new inspection surfaces, failure states, and redaction constraints.

## Verification

```
# check_slash.py exits 1 on no local node
python3 scripts/check_slash.py --local_rpc --overwatch_node_id 1 --epoch 0
→ ERROR: Cannot connect to ws://127.0.0.1:9944: [Errno 111] Connection refused
→ EXIT=1  ✓

# Credential redaction
PHRASE="super secret mnemonic" python3 scripts/check_slash.py --overwatch_node_id 1 --epoch 0 2>&1 | grep -i "super secret"
→ GREP_EXIT=1  ✓

# Compose guard fires on missing OVERWATCH_PHRASE
CHAIN_ENDPOINT=wss://example SUBNET_ID=1 VALIDATOR_PHRASE=x MINER1_PHRASE=x MINER2_PHRASE=x \
  docker compose -f docker-compose.chain.yml config 2>&1 | grep -i "OVERWATCH_PHRASE"
→ error while interpolating services.validator.environment.OVERWATCH_PHRASE: required variable OVERWATCH_PHRASE is missing ...  ✓

# Compose validates with all vars set
CHAIN_ENDPOINT=wss://example SUBNET_ID=1 VALIDATOR_PHRASE=x MINER1_PHRASE=x MINER2_PHRASE=x OVERWATCH_PHRASE=x \
  docker compose -f docker-compose.chain.yml config
→ EXIT=0  ✓

# Layer 2 unaffected
docker compose -f docker-compose.tee-dev.yml config
→ EXIT=0  ✓

# T01 reporter tests still pass
pytest tests/consensus/test_chain_overwatch_reporter.py -v
→ 5 passed  ✓

# Full suite green
pytest tests/ -x -q
→ 193 passed, 1 skipped  ✓
```

## Diagnostics

- **On-chain slash inspection:** `python3 scripts/check_slash.py --chain $CHAIN_ENDPOINT --overwatch_node_id $OVERWATCH_NODE_ID --epoch $EPOCH` — `[OK] N commit(s) found` confirms the commit extrinsic from T01's `reporter.slash()` landed; `[WARN] No commits found` means the slash was not triggered or the epoch is outside the chain window.
- **Compose misconfiguration:** `docker compose -f docker-compose.chain.yml config` without `OVERWATCH_PHRASE` set produces a human-readable error identifying the missing variable before any container starts.
- **Credential safety:** `PHRASE`/`TENSOR_PRIVATE_KEY` values in `check_slash.py` are read from env only; grep for the literal value in all output returns GREP_EXIT=1.

## Deviations

None — implementation follows T02-PLAN.md exactly.

## Known Issues

None.

## Files Created/Modified

- `scripts/check_slash.py` — new; diagnostic script querying `get_overwatch_commits` + `get_overwatch_reveals`; exits 1 on connection failure, 0 on [OK]/[WARN]
- `docker-compose.chain.yml` — modified; header comment updated with OVERWATCH_PHRASE + OVERWATCH_NODE_ID docs; validator service environment gets OVERWATCH_PHRASE :? guard and OVERWATCH_NODE_ID :- pass-through
- `.gsd/milestones/M005/slices/S03/tasks/T02-PLAN.md` — modified; added ## Observability Impact section (pre-flight fix)
