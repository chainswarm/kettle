---
id: S03
parent: M005
milestone: M005
provides:
  - ChainOverwatchReporter(hypertensor, overwatch_node_id, subnet_id) with commit+reveal slash logic
  - 5 unit tests covering all error paths (commit+reveal success, commit failure, reveal failure, exception→None)
  - _overwatch_epoch_loop wired to call reporter.slash() on parity_mismatch behind OVERWATCH_NODE_ID guard
  - scripts/check_slash.py diagnostic script querying on-chain overwatch commits and reveals
  - OVERWATCH_PHRASE :? compose guard and OVERWATCH_NODE_ID :- pass-through in docker-compose.chain.yml validator service
requires:
  - slice: S02
    provides: ChainScoreSubmitter thin-wrapper pattern (constructor signature, receipt|None contract, exception normalisation); PHRASE per-service :? compose guard pattern
affects:
  - S04
key_files:
  - subnet/consensus/chain_overwatch_reporter.py
  - tests/consensus/test_chain_overwatch_reporter.py
  - subnet/server/server.py
  - scripts/check_slash.py
  - docker-compose.chain.yml
key_decisions:
  - D008: constructor takes (hypertensor, overwatch_node_id, subnet_id) — subnet_id required to build commit_weights list; cannot be deferred to slash() call
  - D009: reporter guarded behind OVERWATCH_NODE_ID env var; None when unset; MOCK_TEE mode structurally unaffected
  - D010: OVERWATCH_PHRASE added to validator service (not a separate overwatch service) — _overwatch_epoch_loop runs inside the validator node
patterns_established:
  - ChainOverwatchReporter mirrors ChainScoreSubmitter exactly: constructor(hypertensor, id, subnet_id), method returns receipt|None, exception caught+logged with exc_info=True
  - Commit-reveal pattern: fresh os.urandom(32) salt per slash; sha256(weight_bytes + salt) as commit hash; _PUNISH_WEIGHT=0 / _REWARD_WEIGHT=int(1e18)
  - Reporter instantiated once before the while-loop (not per-iteration) via OVERWATCH_NODE_ID env var
  - Compose guards: :? for required signing credentials, :- for optional pass-throughs that enable feature toggles
  - Diagnostic scripts: URL precedence (--local_rpc > --chain > $DEV_RPC > hardcoded), EXIT=1 on connection failure, [OK]/[WARN] stdout, credentials from env only
observability_surfaces:
  - logger.info("[Overwatch] Submitting slash commit peer=... epoch=... subnet_id=...") before commit
  - logger.error("⚠️ Overwatch commit failed: {error_message}") on is_success=False commit
  - logger.error("⚠️ Overwatch reveal failed: {error_message}") on is_success=False reveal
  - logger.error("Overwatch extrinsic exception: ...", exc_info=True) on unexpected exception
  - python3 scripts/check_slash.py --chain $ENDPOINT --overwatch_node_id $ID --epoch $N → [OK] N commit(s) / [OK] N reveal(s) / [WARN] No commits found; EXIT=1 on connection failure
  - docker compose -f docker-compose.chain.yml config → fails with required variable OVERWATCH_PHRASE is missing if guard triggers
drill_down_paths:
  - .gsd/milestones/M005/slices/S03/tasks/T01-SUMMARY.md
  - .gsd/milestones/M005/slices/S03/tasks/T02-SUMMARY.md
duration: 35m
verification_result: passed
completed_at: 2026-03-17
---

# S03: Overwatch Slash Extrinsic

**`ChainOverwatchReporter` commit+reveal slash wrapper wired into `_overwatch_epoch_loop`; `check_slash.py` diagnostic script; `OVERWATCH_PHRASE` compose guard; 193 passed, 1 skipped.**

## What Happened

S03 closed the gap between `parity_mismatch` detection (already logged in `_overwatch_epoch_loop`) and on-chain slash action (previously missing entirely).

**T01** created `subnet/consensus/chain_overwatch_reporter.py` — a thin wrapper mirroring `ChainScoreSubmitter` exactly. The `slash(peer_id, epoch, evidence)` method generates a fresh 32-byte salt, computes `sha256(weight_bytes + salt)` as the commit hash, submits `commit_overwatch_subnet_weights`, then `reveal_overwatch_subnet_weights`. A `parity_mismatch` maps to `_PUNISH_WEIGHT = 0`. The method returns the reveal receipt on success, the commit receipt early if commit fails (`is_success=False`), and `None` on any exception. All three failure paths are logged at `ERROR` level with `exc_info=True` for the exception path.

The reporter was wired into `server.py`'s `_overwatch_epoch_loop` with a single structural guard: the reporter is instantiated once before the `while` loop only when `OVERWATCH_NODE_ID` is set in the environment. When unset (MOCK_TEE mode), `reporter=None` and the `parity_mismatch` branch is completely unaffected — no new parameter was added to the loop, no call site changed. Five unit tests cover all paths: success, commit failure (reveal not called), reveal failure, exception→None, and receipt-type verification.

**T02** created `scripts/check_slash.py` following the `check_scores.py` template exactly: same URL precedence chain (`--local_rpc > --chain > $DEV_RPC > hardcoded default`), same credential handling (env-only, never echoed), same `[OK]`/`[WARN]` exit codes. The script accepts `--overwatch_node_id INT` and `--epoch INT` and queries `get_overwatch_commits` + `get_overwatch_reveals` from the chain.

`docker-compose.chain.yml` received `OVERWATCH_PHRASE: ${OVERWATCH_PHRASE:?...}` (required `:?` guard) and `OVERWATCH_NODE_ID: ${OVERWATCH_NODE_ID:-}` (optional `:-` pass-through) on the validator service, following the D007 pattern established by S02. The header comment was updated to document both new variables. Layer 2 (`docker-compose.tee-dev.yml`) is completely unaffected.

## Verification

All 7 slice-level checks and 3 failure-path inline verifications passed:

```
pytest tests/consensus/test_chain_overwatch_reporter.py -v   → 5 passed
pytest tests/ -x -q                                          → 193 passed, 1 skipped

python3 scripts/check_slash.py --local_rpc --overwatch_node_id 1 --epoch 0
→ ERROR: Cannot connect to ws://127.0.0.1:9944: [Errno 111] Connection refused
→ EXIT=1  ✓

PHRASE="super secret mnemonic" python3 scripts/check_slash.py --overwatch_node_id 1 --epoch 0 2>&1 | grep -i "super secret"
→ GREP_EXIT=1  ✓

CHAIN_ENDPOINT=wss://example SUBNET_ID=1 VALIDATOR_PHRASE=x MINER1_PHRASE=x MINER2_PHRASE=x \
  docker compose -f docker-compose.chain.yml config 2>&1 | grep -i "OVERWATCH_PHRASE"
→ error while interpolating ... required variable OVERWATCH_PHRASE is missing  ✓

CHAIN_ENDPOINT=wss://example SUBNET_ID=1 VALIDATOR_PHRASE=x MINER1_PHRASE=x MINER2_PHRASE=x OVERWATCH_PHRASE=x \
  docker compose -f docker-compose.chain.yml config → EXIT=0  ✓

docker compose -f docker-compose.tee-dev.yml config → EXIT=0  ✓

# Failure-path verifications
slash() returns None on chain exception  ✓
Reveal not called when commit fails; commit receipt returned  ✓
reporter=None when OVERWATCH_NODE_ID unset  ✓
```

## Requirements Advanced

- R011 (slash extrinsic) — `ChainOverwatchReporter.slash()` implements the full commit+reveal protocol for on-chain slash submission; wired into detection loop; operational diagnostic script available

## Requirements Validated

- None newly validated in this slice — R011 moves to validated when a live testnet run with `TAMPER_RATE=1.0` confirms the slash lands on-chain (S04 scope)

## New Requirements Surfaced

- None

## Requirements Invalidated or Re-scoped

- None

## Deviations

None. Both tasks followed their plans exactly.

## Known Limitations

- Slash extrinsic fires per-subnet (weight=0 for any tamper in the subnet), not per-peer. The `peer_id` and `epoch` args are logged only. The Hypertensor `commit_overwatch_subnet_weights` API accepts subnet-level weights, not per-peer slash targets. If per-peer slashing is needed, the pallet API must be extended.
- `check_slash.py` queries `get_overwatch_commits` / `get_overwatch_reveals` — if these RPC methods are not present on the connected node version, the script will raise an `AttributeError`. Pin the testnet node version before S04 live testing.
- Live testnet confirmation (slash visible on-chain after `TAMPER_RATE=1.0` run) is deferred to S04 / human UAT — S03 proof level is contract only.
- `ChainScoreSubmitter.submit()` is still not wired into the validator epoch loop — that wiring is explicitly deferred to S04.

## Follow-ups

- S04 must wire `ChainScoreSubmitter.submit(scores)` into the validator epoch loop (the class is ready; the call is deferred).
- S04 live testnet run: `TAMPER_RATE=1.0` → confirm `[OK] 1 commit(s) found` via `check_slash.py` → validates R011.
- S04 `CHAIN.md` should document `check_slash.py` usage: `--local_rpc` for development, `--chain $ENDPOINT` for testnet, expected latency between `parity_mismatch` detection and commit landing.
- `smoke_test_chain.py` (S04) should call `check_slash.py` after a forced tamper to verify the full detection→slash→chain pipeline end-to-end in CI.

## Files Created/Modified

- `subnet/consensus/chain_overwatch_reporter.py` — new; `ChainOverwatchReporter` class (~70 lines); commit+reveal slash logic; `_PUNISH_WEIGHT=0` / `_REWARD_WEIGHT=int(1e18)`
- `tests/consensus/test_chain_overwatch_reporter.py` — new; 5 unit tests covering all required paths
- `subnet/server/server.py` — module-level import added; reporter instantiation (7 lines) before while-loop; `reporter.slash()` call (2 lines) in `parity_mismatch` branch
- `scripts/check_slash.py` — new; diagnostic script querying `get_overwatch_commits` + `get_overwatch_reveals`; exits 1 on connection failure, 0 on `[OK]`/`[WARN]`
- `docker-compose.chain.yml` — modified; header comment updated; validator service `environment:` gets `OVERWATCH_PHRASE: ${OVERWATCH_PHRASE:?...}` and `OVERWATCH_NODE_ID: ${OVERWATCH_NODE_ID:-}`

## Forward Intelligence

### What the next slice should know

- `ChainOverwatchReporter.slash()` accepts `evidence=None` — the evidence arg is logged but not serialised into the commit hash. If S04 needs evidence stored on-chain, a new overload or separate extrinsic call is required.
- The thin-wrapper pattern is now established three times (S01 `check_peers.py`, S02 `ChainScoreSubmitter`, S03 `ChainOverwatchReporter`). Any new chain interaction should follow this pattern: constructor takes `(hypertensor, id, subnet_id)`, single method returns `receipt | None`, exceptions caught at the wrapper boundary.
- `OVERWATCH_NODE_ID` is currently passed as a plain integer. If the overwatch node ID changes across epochs (e.g. re-registration), the reporter must be reconstructed — the current code does not handle dynamic node IDs.
- All three diagnostic scripts (`check_peers.py`, `check_scores.py`, `check_slash.py`) share identical URL-resolution and credential-redaction patterns. `smoke_test_chain.py` (S04) should delegate to these scripts rather than reimplementing the patterns.

### What's fragile

- `get_overwatch_commits` / `get_overwatch_reveals` RPC method names — if the Hypertensor pallet renames these (API churn noted as a key risk in M005), `check_slash.py` will break with an `AttributeError`. Verify method names against the pinned Hypertensor tag before the S04 live run.
- Salt entropy: `os.urandom(32)` is correct but the salt is not persisted. If the process crashes between commit and reveal, the reveal can never be reconstructed. For production, salt should be stored (sealed storage or DHT) before the commit is broadcast.

### Authoritative diagnostics

- `docker compose logs validator | grep "\[Overwatch\]"` — first signal that detection+slash fired; look for `[Overwatch] TAMPER` (pre-existing) followed by `[Overwatch] Submitting slash commit` (S03 new).
- `⚠️ Overwatch commit/reveal failed:` in validator logs — chain-level rejection; receipt.error_message gives the pallet error code.
- `python3 scripts/check_slash.py --chain $ENDPOINT --overwatch_node_id $ID --epoch $N` — ground truth on-chain; `[OK] 1 commit(s)` confirms the extrinsic landed.

### What assumptions changed

- Original boundary map specified `ChainOverwatchReporter(hypertensor, overwatch_node_id)` (two args). Implementation adds `subnet_id` as the third constructor arg (D008) because `commit_overwatch_subnet_weights` requires a `subnet_id` inside the commit weights list. S04 must use the three-arg constructor.
- Evidence format: S03 plan mentioned "confirm bytes vs structured at implementation time." The implementation uses `OverwatchCommit(subnet_id, weight=commit_hash_bytes)` — `weight` is a bytes field (sha256 digest). S04 must not expect a structured evidence dict in the commit.
