# S03: Overwatch Slash Extrinsic — Research

**Date:** 2026-03-17

## Summary

S03 adds a `ChainOverwatchReporter` thin-wrapper that bridges `MockOverwatchVerifier.verify()` (already running in `_overwatch_epoch_loop` in `server.py`) to the on-chain slash mechanism. The Hypertensor chain does **not** expose a `slash_node` extrinsic directly. Instead, overwatch uses a **commit-reveal** pattern: `commit_overwatch_subnet_weights` in the first phase of the overwatch epoch, then `reveal_overwatch_subnet_weights` after the cutoff block. Both methods already exist on `Hypertensor` in `chain_functions.py`. The wrapper's job is to encode the `weight` (derived from `OverwatchResult.ok` → punish/reward per subnet), hash it with a salt for commitment, then reveal.

However, examining the boundary map more carefully: the roadmap and boundary map describe S03 as producing `ChainOverwatchReporter.slash(peer_id, epoch, evidence)` — a "thin-wrapper pattern mirroring ChainScoreSubmitter." The S03 spec says "slash extrinsic fires → peer stake reduced on-chain." There is no `slash_node` extrinsic in `chain_functions.py`. The closest mechanism is `commit_overwatch_subnet_weights` / `reveal_overwatch_subnet_weights` — these affect subnet weight (and hence staking rewards) rather than slashing an individual peer's stake directly. The "slash" in the roadmap most likely means: overwatch submits a negative weight for a subnet where tamper is detected, which reduces that subnet's token emissions.

**Recommendation:** Implement `ChainOverwatchReporter` as a thin wrapper over `commit_overwatch_subnet_weights` / `reveal_overwatch_subnet_weights` following the ChainScoreSubmitter pattern exactly: constructor takes `(hypertensor, overwatch_node_id)`, `slash()` encodes the commit + submit, returns `receipt | None`. Wire it into `_overwatch_epoch_loop` so when `result.reason == "parity_mismatch"` the reporter fires. Add the `OVERWATCH_PHRASE: ${OVERWATCH_PHRASE:?...}` guard to `docker-compose.chain.yml`. Add `scripts/check_slash.py` querying overwatch state. Add unit tests (5 tests mirroring `test_chain_submitter.py`). Total: ~2 tasks, same scope as S02.

## Recommendation

Mirror the S02 pattern exactly:
- **T01:** `subnet/consensus/chain_overwatch_reporter.py` — `ChainOverwatchReporter(hypertensor, overwatch_node_id)` with `slash(peer_id, epoch, evidence)` method using `commit_overwatch_subnet_weights` / `reveal_overwatch_subnet_weights` for the extrinsic path; unit tests in `tests/consensus/test_chain_overwatch_reporter.py`
- **T02:** `scripts/check_slash.py` + `docker-compose.chain.yml` overwatch credential guard

The evidence format question (bytes vs structured, per the roadmap Key Risks) resolves to: `commit_weights` takes `Any` in `chain_functions.py`, and `OverwatchCommit` has `{subnet_id: int, weight: bytes}` — weight is a sha256 hash of `(actual_weight_int, salt_bytes)`. The salt and weight are revealed in `OverwatchReveals`. The reporter only needs to encode this; no custom format beyond the existing chain API.

## Implementation Landscape

### Key Files

- `subnet/consensus/chain_submitter.py` — the exact pattern to follow: constructor takes `(hypertensor, subnet_id)`, method does try/except, returns `receipt | None`, logs on failure. Copy this structure verbatim for the overwatch reporter.
- `subnet/node/mock.py` — `MockOverwatchVerifier.verify(peer_id, epoch)` returns `OverwatchResult(ok, reason, details)`. `reason == "parity_mismatch"` is the trigger for the slash call. `reason == "no_work_record"` is debug-only (cold start). The reporter receives this result and decides whether to fire.
- `subnet/server/server.py` — `_overwatch_epoch_loop` already calls `verifier.verify()` and logs `[Overwatch] TAMPER` but currently does **nothing** with the result on-chain. This is where `ChainOverwatchReporter.slash()` gets wired in, analogous to how `propose_attestation` is called in `run_consensus()`. The loop already has `hypertensor` and `subnet_id` in scope.
- `subnet/hypertensor/chain_functions.py` — `commit_overwatch_subnet_weights(overwatch_node_id, commit_weights)` and `reveal_overwatch_subnet_weights(overwatch_node_id, reveals)` are the two extrinsic methods available. Both follow the same retry+nonce pattern as `propose_attestation`. There is **no** `slash_node` extrinsic — the slash mechanism is the commit-reveal weight system.
- `subnet/hypertensor/chain_data.py` — `OverwatchCommit(subnet_id, weight: bytes)` and `OverwatchReveals(subnet_id, weight: int, salt: bytes)` are the data structures for the commit and reveal phases respectively.
- `subnet/hypertensor/chain_functions.py` — `get_overwatch_epoch_data()` and `in_overwatch_commit_period()` are helpers for phase timing. The reporter needs to know whether it's in the commit window or reveal window.
- `tests/consensus/test_chain_submitter.py` — the exact test pattern to mirror: 5 tests, `MagicMock`-based, covers success/failure-receipt/empty-passthrough/exception paths.
- `docker-compose.chain.yml` — add `OVERWATCH_PHRASE: ${OVERWATCH_PHRASE:?OVERWATCH_PHRASE is required (overwatch signs commit/reveal extrinsics)}` to the overwatch service (or validator service if overwatch runs on the same node). Currently no overwatch service exists in this file — the compose file needs a new service or the existing validator service needs the env var.
- `scripts/check_peers.py` and `scripts/check_scores.py` — credential loading, friendly-ID resolution, URL precedence, exit-code semantics to copy verbatim into `check_slash.py`.

### Build Order

1. **T01 — `ChainOverwatchReporter` class + unit tests** (unblocks wiring)
   - Create `subnet/consensus/chain_overwatch_reporter.py` with `ChainOverwatchReporter(hypertensor, overwatch_node_id)` 
   - Method: `slash(peer_id, epoch, evidence) → receipt | None` wrapping `commit_overwatch_subnet_weights` / `reveal_overwatch_subnet_weights`
   - Create `tests/consensus/test_chain_overwatch_reporter.py` with 5 MagicMock tests
   - Wire `ChainOverwatchReporter.slash()` into `_overwatch_epoch_loop` in `server.py` on `parity_mismatch` detection
   - Layer 1 pytest must remain green

2. **T02 — `scripts/check_slash.py` + compose guard** (independent of T01 execution, depends only on knowing the query API)
   - `scripts/check_slash.py` querying overwatch state (overwatch commits/reveals) for a given epoch using `get_overwatch_commits` / `get_overwatch_reveals` RPC methods
   - Add `OVERWATCH_PHRASE` `:?` guard to `docker-compose.chain.yml` (validator service or new overwatch service)

### Verification Approach

```bash
# T01 — unit tests pass
pytest tests/consensus/test_chain_overwatch_reporter.py -v
# → 5 passed

# T01 — Layer 1 still green
pytest tests/ -x -q
# → ~193+ passed, 1 skipped

# T02 — check_slash.py exits 1 on no local node
python3 scripts/check_slash.py --local_rpc --overwatch_node_id 1 --epoch 0
# → ERROR: Cannot connect to ws://127.0.0.1:9944: [Errno 111] Connection refused
# → EXIT=1

# T02 — compose guard fires on missing OVERWATCH_PHRASE
CHAIN_ENDPOINT=wss://... SUBNET_ID=1 VALIDATOR_PHRASE=x MINER1_PHRASE=x MINER2_PHRASE=x \
  docker compose -f docker-compose.chain.yml config 2>&1 | grep -i "OVERWATCH_PHRASE"
# → error ... required variable OVERWATCH_PHRASE is missing

# T02 — compose validates with all vars set
CHAIN_ENDPOINT=... SUBNET_ID=1 VALIDATOR_PHRASE=x MINER1_PHRASE=x MINER2_PHRASE=x OVERWATCH_PHRASE=x \
  docker compose -f docker-compose.chain.yml config
# → EXIT=0

# S03 success criterion (live testnet)
TAMPER_RATE=1.0 ... docker compose -f docker-compose.chain.yml up
# → [Overwatch] TAMPER peer=... epoch=N reason=parity_mismatch in logs
# → commit_overwatch_subnet_weights extrinsic visible in block explorer
```

## Constraints

- **No `slash_node` extrinsic exists in `Hypertensor`** — the roadmap uses "slash" loosely. The actual on-chain mechanism is `commit_overwatch_subnet_weights` / `reveal_overwatch_subnet_weights`. The reporter wraps these two calls. S04 docs must clarify this.
- **Overwatch requires `overwatch_node_id`**, not just `subnet_id`. The `register_overwatch_node(hotkey, stake_to_be_added)` extrinsic must have been called before `commit_overwatch_subnet_weights` can succeed. The compose guard (`OVERWATCH_PHRASE`) implies the overwatch node is pre-registered; registration documentation lands in S04.
- **Commit-reveal timing**: `commit_overwatch_subnet_weights` must be called before `epoch_cutoff_block` (i.e., while `in_overwatch_commit_period()` is True); `reveal_overwatch_subnet_weights` after. The reporter must respect this timing. The `_overwatch_epoch_loop` runs per epoch — the reporter should submit the commit immediately on detection, then queue the reveal. The simplest implementation: commit on detection, reveal in the same call (two sequential extrinsics). If timing is wrong, the chain rejects one silently — this is non-fatal (same error-normalisation pattern as ChainScoreSubmitter).
- **`MockOverwatchVerifier` has no session key** — it only checks math, not RA-TLS sig. The reporter only fires on `parity_mismatch`, not on `no_work_record` (cold-start) or `no_tee_quote` or `tee_quote_hash_mismatch`.
- **No `substrate_client.py` module** — per S01/S02 boundary, all chain access uses `Hypertensor(url, phrase)` directly. The reporter receives a `hypertensor` instance; it does not construct one.

## Common Pitfalls

- **`commit_weights` type mismatch** — `chain_functions.py` accepts `Any`; `OverwatchCommit.weight` is `bytes` (a sha256 hash). The chain pallet likely expects a SCALE-encoded `Vec<u8>`. Use `hashlib.sha256(weight_bytes + salt).digest()` as the commit, and pass the list of `OverwatchCommit` dicts. Confirm the exact encoding by looking at how the mock does it. If the chain rejects the commit, the error surfaces in `receipt.error_message` — the reporter logs it and returns the receipt (same as `ChainScoreSubmitter`).
- **`overwatch_node_id` vs `subnet_id`** — `commit_overwatch_subnet_weights` takes `overwatch_node_id` (the ID of the overwatch node itself), plus `commit_weights` which is a list of `{subnet_id, weight}` tuples (one per subnet being rated). Don't confuse the two IDs.
- **`TAMPER_RATE=1.0` test** — when all peers tamper every epoch, `_overwatch_epoch_loop` fires the reporter every epoch. The reporter must not crash on repeated calls. Error normalisation (None on exception) handles this.
- **Bootnode gets empty PHRASE** — same pattern as S02. The overwatch credential applies to whichever node runs the overwatch reporter (likely a dedicated overwatch service or the validator service). The bootnode should not sign overwatch extrinsics.

## Open Risks

- **Commit-reveal timing in a single epoch loop**: if the overwatch epoch length is much longer than the consensus epoch (multiplier > 1), the `_overwatch_epoch_loop` may detect tamper within a consensus epoch but the overwatch reveal window may not be open yet. The reporter needs to handle this gracefully — commit immediately, but only reveal once `in_overwatch_commit_period()` returns False. This may require the reporter to track pending commits across epochs. Simplest approach: commit and reveal in sequence; if reveal is rejected, log and move on.
- **`overwatch_node_id` is unknown at runtime** — the server doesn't currently pass `overwatch_node_id` to `_overwatch_epoch_loop`. Either add an env var `OVERWATCH_NODE_ID` or look it up from the chain using `get_overwatch_node_info_formatted()` at startup. The latter requires a registered overwatch node. For S03, env var is simpler.
- **Evidence format accepted by pallet**: The roadmap flags this as unknown. Based on the code, `commit_weights` is `Any` → the pallet accepts a list of `[{subnet_id: N, weight: bytes}]`. The reveal sends `[{subnet_id: N, weight: int, salt: bytes}]`. The "evidence" parameter in `ChainOverwatchReporter.slash(peer_id, epoch, evidence)` maps to the weight signal (punish = low weight, e.g. `0`; pass = high weight, e.g. `int(1e18)`). No structured "slash evidence" blob is needed.
