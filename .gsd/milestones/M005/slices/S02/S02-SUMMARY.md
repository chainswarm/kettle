---
id: S02
parent: M005
milestone: M005
provides:
  - ChainScoreSubmitter class wrapping propose_attestation with asdict serialisation and error normalisation
  - scripts/check_scores.py querying SubnetConsensusSubmission for a given epoch (5 signal states)
  - docker-compose.chain.yml per-service PHRASE :? guards for validator, miner-1, miner-2
requires:
  - slice: S01
    provides: Hypertensor(url, phrase) construction pattern, credential redaction pattern, friendly-ID resolution, docker-compose.chain.yml base structure
affects:
  - S03
key_files:
  - subnet/consensus/chain_submitter.py
  - tests/consensus/test_chain_submitter.py
  - tests/consensus/__init__.py
  - scripts/check_scores.py
  - docker-compose.chain.yml
key_decisions:
  - ChainScoreSubmitter does NOT own retry logic — delegates entirely to Hypertensor.propose_attestation(); retry lives inside Hypertensor
  - Empty score list is NOT short-circuited; passes data=[] to propose_attestation as the chain allows it
  - asdict(s) on SubnetNodeConsensusData is the only serialisation step — produces {"subnet_node_id": N, "score": M}; no additional encoding in the submitter
  - x-chain-env anchor PHRASE set to "" (empty literal) so bootnode stays optional; per-service :? overrides are authoritative for signing nodes
  - check_scores.py WARN path exits 0 (not 1) for empty/None result — distinguishes "epoch not yet finalised" from connection failure
patterns_established:
  - thin-wrapper pattern: ChainScoreSubmitter owns serialisation (asdict) + error normalisation (None on exception, receipt on is_success=False); all retry/nonce logic stays in Hypertensor
  - check_scores.py mirrors check_peers.py exactly: credential loading (PHRASE/TENSOR_PRIVATE_KEY from env, never echoed), friendly-ID resolution (< 128000 → get_subnet_id_from_friendly_id → int(str(result))), ERROR:/exit-1 on connection failure, URL precedence (--local_rpc > --chain > $DEV_RPC > hardcoded default)
  - docker-compose per-service PHRASE override: add PHRASE key in environment block after <<: *chain-env to override the anchor value
observability_surfaces:
  - logger.error("⚠️ Score submission failed: <error_message>") on receipt.is_success=False
  - logger.error("Score submission exception: <exc>", exc_info=True) on unexpected exception from propose_attestation
  - python3 scripts/check_scores.py --chain $CHAIN_ENDPOINT --subnet_id $SUBNET_ID --epoch $EPOCH → [OK] N entries / [WARN] No scores found / ERROR: Cannot connect
  - docker compose -f docker-compose.chain.yml config → fails fast with "required variable VALIDATOR_PHRASE is missing" when credentials absent
drill_down_paths:
  - .gsd/milestones/M005/slices/S02/tasks/T01-SUMMARY.md
  - .gsd/milestones/M005/slices/S02/tasks/T02-SUMMARY.md
duration: ~30m (T01: ~10m, T02: ~20m)
verification_result: passed
completed_at: 2026-03-17
---

# S02: Score Submission Extrinsic

**Thin `ChainScoreSubmitter` wrapper around `propose_attestation` with 5 unit tests; `check_scores.py` CLI for querying on-chain scores; per-node `:?`-guarded PHRASE vars in `docker-compose.chain.yml`. 188 tests passing.**

## What Happened

**T01** created `subnet/consensus/chain_submitter.py` with `ChainScoreSubmitter(hypertensor, subnet_id)`. The `submit(scores)` method converts `List[SubnetNodeConsensusData]` to dicts via `dataclasses.asdict`, delegates to `hypertensor.propose_attestation(subnet_id, data=...)`, logs `⚠️ Score submission failed:` on `is_success=False`, and catches/logs/returns-None on exceptions. No retry logic is duplicated — that lives inside `Hypertensor`. Created `tests/consensus/` package with 5 `MagicMock`-based tests covering all required paths: success (returns receipt), failure receipt (returns receipt, logs error), empty-list pass-through (calls through with `data=[]`), and exception recovery (returns None). Total test count rose from 183 to 188 (1 skipped).

**T02** created `scripts/check_scores.py` mirroring every `check_peers.py` pattern exactly: same credential loading (`PHRASE`/`TENSOR_PRIVATE_KEY` from env, never echoed), same friendly-ID resolution (`< 128000` → `get_subnet_id_from_friendly_id` → `int(str(result))`), same `ERROR: Cannot connect to {url}: {exc}` + exit 1 on connection failure. Added `--epoch INT` (required) argument. Calls `hypertensor.get_rewards_submission(real_id, epoch)` and handles None/empty SCALE result as `[WARN] No scores found for epoch N` (exit 0), non-empty as `[OK] Scores found for epoch N: {N} entries` (exit 0). Updated `docker-compose.chain.yml`: header comment documents new required vars; `x-chain-env` anchor `PHRASE` changed to `""` (bootnode optional); validator, miner-1, and miner-2 each have `PHRASE: ${SERVICE_PHRASE:?...}` added with descriptive error messages; bootnode left unchanged (does not sign extrinsics).

## Verification

All 9 verification checks passed:

```
# T01 — ChainScoreSubmitter unit tests
pytest tests/consensus/test_chain_submitter.py -v
→ 5 passed in 0.03s  ✅

# T01 — exception path returns None
python3 -c "...ht.propose_attestation.side_effect = Exception('network down')..."
→ PASS: exception swallowed, returned None  ✅

# T01 — failed receipt returned (not None), error logged
python3 -c "...receipt.is_success=False..."
→ PASS: failed receipt returned correctly  ✅

# Layer 1 still green
pytest tests/ -x -q
→ 188 passed, 1 skipped  ✅

# T02 — check_scores.py exits 1 + ERROR on no local node
python3 scripts/check_scores.py --local_rpc --subnet_id 1 --epoch 0
→ ERROR: Cannot connect to ws://127.0.0.1:9944: [Errno 111] Connection refused
→ EXIT=1  ✅

# T02 — credential redaction
PHRASE="super secret mnemonic" python3 scripts/check_scores.py ... | grep -i "super secret"
→ GREP_EXIT=1  ✅

# T02 — compose guard fires on missing VALIDATOR_PHRASE
CHAIN_ENDPOINT=wss://... SUBNET_ID=1 docker compose -f docker-compose.chain.yml config 2>&1 | grep -i "VALIDATOR_PHRASE"
→ error while interpolating ... required variable VALIDATOR_PHRASE is missing ...  ✅

# T02 — compose validates with all vars set
CHAIN_ENDPOINT=... SUBNET_ID=1 VALIDATOR_PHRASE=... MINER1_PHRASE=... MINER2_PHRASE=... docker compose -f docker-compose.chain.yml config
→ EXIT=0  ✅

# T02 — Layer 2 unaffected
docker compose -f docker-compose.tee-dev.yml config
→ EXIT=0  ✅
```

## Requirements Advanced

- R010 (score extrinsic) — `ChainScoreSubmitter.submit()` is the production submission path; unit-tested contract established; real runtime proof (scores visible in chain state) completes at M005 integration milestone

## Requirements Validated

- R022 (test coverage) — 188 tests passing, 1 skipped; 5 new unit tests cover ChainScoreSubmitter contract

## New Requirements Surfaced

- None

## Requirements Invalidated or Re-scoped

- None

## Deviations

None — both tasks implemented exactly as planned.

## Known Limitations

- **No live chain proof yet**: `check_scores.py` can only prove connection failure without a running testnet node. Scores visible in chain state (`[OK] Scores found for epoch N`) requires a live testnet run — this is intentionally deferred to the M005 integration milestone, not a per-slice gate.
- **`ChainScoreSubmitter` is not yet wired into the validator epoch loop**: The class exists and is tested, but the validator's consensus loop still does not call it. Wiring it to the live epoch loop is an M005 integration concern after S03 and S04 complete.
- **`check_scores.py` WARN path on empty result**: For epochs before any submission or before election, the script exits 0 with `[WARN]` — this is correct behaviour but may confuse operators who expect immediate output after deploying. The S04 `CHAIN.md` should document the expected time-to-first-submission.

## Follow-ups

- **S03** must import `ChainScoreSubmitter` for slash reporting context; the thin-wrapper pattern is the interface contract to honour
- **Wiring `ChainScoreSubmitter` into validator epoch loop**: After S03 lands, the integration step in S04 or a dedicated task should call `submitter.submit(scores)` at end of each epoch; the submitter is ready but not yet called in production
- **`CHAIN.md` S04 docs**: Should cover `check_scores.py` usage, what `[WARN]` means vs `[OK]`, expected time-to-first-submission, and how to read `SubnetConsensusSubmission` directly via `substrate.query`

## Files Created/Modified

- `subnet/consensus/chain_submitter.py` — new; `ChainScoreSubmitter` class (~32 lines); thin wrapper around `propose_attestation`
- `tests/consensus/__init__.py` — new; empty init for test package
- `tests/consensus/test_chain_submitter.py` — new; 5 unit tests (~80 lines) covering all paths
- `scripts/check_scores.py` — new; ~155 lines; queries `SubnetConsensusSubmission`; all `check_peers.py` patterns applied
- `docker-compose.chain.yml` — modified; header updated; `x-chain-env` anchor `PHRASE` changed to `""`; validator/miner-1/miner-2 get per-service `PHRASE` `:?` guards; bootnode left optional

## Forward Intelligence

### What the next slice should know
- `ChainScoreSubmitter(hypertensor, subnet_id).submit(scores)` is the interface S03 should treat as stable. It returns `receipt | None`: receipt on both success and failure (check `receipt.is_success`), None only on exception. Do not change this contract without updating tests.
- `check_scores.py` is the authoritative diagnostic tool post-submission. After S03 and S04, it should be called in `scripts/smoke_test_chain.py` to confirm both scores and slash events landed.
- The compose per-service PHRASE pattern is now established. S03's `ChainOverwatchReporter` will also need a keypair — follow the same `PHRASE: ${OVERWATCH_PHRASE:?...}` pattern in the overwatch service environment block.
- `get_rewards_submission(real_id, epoch)` returns a SCALE-decoded object; the `.value` attribute may be `None` (no submission), a `dict` with `"data"` key, or a `list`. `check_scores.py` handles all three — copy this pattern if S03 needs to query slash state.

### What's fragile
- `asdict(s)` on `SubnetNodeConsensusData` — if the dataclass fields change (rename, add required fields), the submitted dict format changes silently and the chain may reject it. S03 and S04 should pin to the current field names `{"subnet_node_id": N, "score": M}` and add a test if the dataclass evolves.
- `docker-compose.chain.yml` anchor override pattern (`<<: *chain-env` + per-service `PHRASE:`) — YAML merge keys are evaluated before override keys in strict-merge parsers. If compose behaviour changes, the `PHRASE` override may silently fall through to the anchor value. The `:?` guard is the safety net.

### Authoritative diagnostics
- `python3 scripts/check_scores.py --chain $CHAIN_ENDPOINT --subnet_id $SUBNET_ID --epoch $EPOCH` — primary signal for whether submission landed; `[OK]` with entries is the target state after each epoch
- `docker compose -f docker-compose.chain.yml config` — confirms per-node credential guards fire; run before `docker compose up` on any new environment
- `pytest tests/consensus/test_chain_submitter.py -v` — confirms the submission contract is intact after any refactor; should remain 5 passed

### What assumptions changed
- Original boundary map assumed S02 would produce `ChainScoreSubmitter.submit(peer_id, score, epoch)` (per-node signature). Actual implementation uses `submit(scores: List[SubnetNodeConsensusData])` (batch submission) to match `propose_attestation`'s actual API shape. S03 should consume the batch interface, not a per-node one.
- Original plan noted `x-chain-env` anchor `PHRASE` as `${PHRASE:-}`. Changed to `""` (literal empty) so bootnode gets an empty string (valid for read-only chain queries) while validator and miners require their per-service phrase. The `:-` form would silently pick up any ambient `PHRASE` env var if set, which could cause a mismatch between what the operator thinks is running and what is actually signing.
