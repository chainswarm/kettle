# S04 — Chain Integration Docs + Smoke Tests — Research

**Date:** 2026-03-17

## Summary

S04 is low-risk, high-leverage documentation and integration plumbing. All the chain wrappers (`ChainScoreSubmitter`, `ChainOverwatchReporter`) are already built and tested. The three diagnostic scripts (`check_peers.py`, `check_scores.py`, `check_slash.py`) already exist and follow identical patterns. What's missing is:

1. **`ChainScoreSubmitter` wired into `_validator_scoring_loop`** — the class is ready; the call site is not there yet.
2. **`CHAIN.md` expanded** from stub to full developer walkthrough (registration, staking, monitoring).
3. **`scripts/register_subnet.py` and `scripts/register_node.py`** — thin wrappers around existing `Hypertensor.register_subnet()` / `register_subnet_node()` chain_functions methods, following the `check_peers.py` credential/URL pattern exactly.
4. **`scripts/smoke_test_chain.py`** — delegates to the three check scripts, exits 0 only when all pass; used in CI.
5. **CI GitHub Actions job** — Layer 1 + Layer 2 validate, chain smoke test (with a local mock or skipped in CI).

The wiring task (1) is the most structurally interesting — it requires collecting per-peer scores into a batch `List[SubnetNodeConsensusData]` and calling `submitter.submit(scores)` at the end of each epoch's peer loop. That loop currently discards the scored data. All other tasks are documentation and script authoring that directly mirrors already-established patterns.

## Recommendation

Split into two tasks: **T01** handles the two code changes (wire `ChainScoreSubmitter` into `_validator_scoring_loop` + write register/smoke-test scripts); **T02** expands `CHAIN.md` and updates `TESTING_LAYERS.md`. Keep `register_subnet.py` and `register_node.py` as interactive scripts (prompt for missing values, print receipt). `smoke_test_chain.py` is non-interactive and should be CI-safe (exit 1 on connection failure gracefully rather than crashing).

No new chain interaction patterns are needed — everything follows `check_peers.py` exactly.

## Implementation Landscape

### Key Files

- `subnet/server/server.py` — `_validator_scoring_loop` (lines ~548–616) scores each peer but currently **discards** results; must collect into `List[SubnetNodeConsensusData]` and call `submitter.submit(scores)` after the peer loop. `ChainScoreSubmitter` is already imported at line 66 (via `chain_overwatch_reporter` import). The submitter must be instantiated before the while loop, guarded by `hypertensor` being a real `Hypertensor` (not `LocalMockHypertensor`) — or simpler: always instantiate it; MOCK_TEE uses `LocalMockHypertensor` whose `propose_attestation` is a no-op.
- `subnet/consensus/chain_submitter.py` — `ChainScoreSubmitter(hypertensor, subnet_id)` — ready; `.submit(scores: List[SubnetNodeConsensusData])` returns `receipt | None`. No changes needed.
- `subnet/hypertensor/chain_data.py` — `SubnetNodeConsensusData(subnet_node_id: int, score: int)` at line 1187. The `subnet_node_id` field maps to `SubnetNodeInfo.subnet_node_id` (line 853 of chain_data.py). Score must be an integer (e.g. `int(peer_score.score * 1e18)` if peer_score is 0.0–1.0).
- `subnet/hypertensor/chain_functions.py` — `Hypertensor.register_subnet()` (line 272) and `register_subnet_node()` (line 430) are the extrinsic wrappers `register_subnet.py`/`register_node.py` will call. Both take many positional args — the scripts must accept these as CLI args with sensible defaults.
- `scripts/check_peers.py` — authoritative credential/URL pattern; `register_subnet.py`, `register_node.py`, `smoke_test_chain.py` must mirror this exactly.
- `CHAIN.md` — stub at repo root; expand to full walkthrough covering: faucet/key setup, `register_subnet.py`, `register_node.py`, running the chain stack, monitoring with the check scripts, what `[WARN]` vs `[OK]` means, expected time-to-first-submission.
- `TESTING_LAYERS.md` — Layer 3 section is already filled; update to add `check_scores.py` / `check_slash.py` commands and reference `smoke_test_chain.py`.

### Build Order

**First:** Wire `ChainScoreSubmitter` into `_validator_scoring_loop` (T01-a). This is the only code change in production code and should be verified with a unit test. The loop already has `hypertensor` and `subnet_id` in scope. The scoring loop iterates nodes, calls `protocol.validator_call()` + `scoring.score_peer()`, and logs results. After the per-node loop, collect accumulated `SubnetNodeConsensusData` objects and call `submitter.submit(scores)`. The `subnet_node_id` value comes from `node.subnet_node_id` (SubnetNodeInfo field). Score value: `peer_score.score` is a float 0.0–1.0; the chain expects an integer — convert with `int(peer_score.score * 1e18)`.

**Second:** Write `scripts/register_subnet.py` and `scripts/register_node.py` (T01-b). Mirror `check_peers.py` for credential loading and URL resolution. Call `hypertensor.register_subnet(...)` / `hypertensor.register_subnet_node(...)` from `chain_functions.py`. Print `[OK] Subnet registered: receipt.extrinsic_hash` or `ERROR: Registration failed: ...`.

**Third:** Write `scripts/smoke_test_chain.py` (T01-c). Delegates to the three existing check scripts via `subprocess.run`. Exits 0 only when all pass. Arguments mirror `check_peers.py` (--chain, --subnet_id, --local_rpc) plus `--epoch INT` for scores and `--overwatch_node_id INT` for slash. Should exit gracefully (not crash) when chain is unreachable — this is for CI which has no testnet access.

**Fourth:** Expand `CHAIN.md` and update CI config (T02). Write the full developer walkthrough. Create `.github/workflows/ci.yml` with Layer 1 (`pytest tests/`) and Layer 2 (`docker compose -f docker-compose.tee-dev.yml config`) validation steps. Chain smoke test step should be skipped (or use `--local_rpc` + expect exit 1) in CI since there's no real testnet in CI. Alternatively, make the smoke test step conditional on `CHAIN_ENDPOINT` being set and skip gracefully when absent.

### Verification Approach

```bash
# Wiring test — ChainScoreSubmitter called at end of epoch:
pytest tests/consensus/test_chain_submitter.py -v   # still 5 passed (no regression)

# New unit test for wiring (if added to test_chain_submitter.py or a server test):
# Mock hypertensor, run 2 epochs, confirm propose_attestation called with correct peer list

# Layer 1 still green:
pytest tests/ -x -q   # target: 193+ passed, 1 skipped

# smoke_test_chain.py exits 1 gracefully on no local node (not a crash):
python scripts/smoke_test_chain.py --local_rpc --subnet_id 1 --epoch 0 --overwatch_node_id 1
# → prints ERROR: Cannot connect ... for each sub-check, exits 1

# register_subnet.py prints help (doesn't crash on import):
python scripts/register_subnet.py --help
python scripts/register_node.py --help

# CHAIN.md and TESTING_LAYERS.md present and non-stub:
grep -c "register" CHAIN.md | grep -v "^0$"   # has registration content

# Layer 2 still valid:
docker compose -f docker-compose.tee-dev.yml config   # exits 0
docker compose -f docker-compose.chain.yml config 2>&1 | grep CHAIN_ENDPOINT   # guard still fires
```

## Constraints

- `ChainScoreSubmitter` is not imported in `server.py` directly — it's only the `ChainOverwatchReporter` that's imported at line 66. `ChainScoreSubmitter` import must be added to `server.py`.
- `_validator_scoring_loop` receives `hypertensor` and `subnet_id` as args — enough to construct `ChainScoreSubmitter(hypertensor, subnet_id)` before the while loop.
- `peer_score.score` is a `float` (0.0–1.0). `SubnetNodeConsensusData.score` is typed `int`. Convert with `int(peer_score.score * 1e18)` to match the chain's fixed-point representation — same as `_REWARD_WEIGHT = int(1e18)` in `chain_overwatch_reporter.py`.
- `node.subnet_node_id` (from `SubnetNodeInfo` line 853) is the integer ID for `SubnetNodeConsensusData.subnet_node_id`. This is available from the `nodes` list in the scoring loop — use it directly rather than inventing a separate ID lookup.
- Score errors (peer unreachable/exception) currently `continue` past that peer. Those peers should still be included in the submission with `score=0` — or simply omitted from the batch. Omitting (current behaviour: score only peers that respond) is fine.
- `register_subnet.py` wraps a call with many positional params (`max_cost`, `name`, `repo`, `description`, `misc`, `min_stake`, `max_stake`, `delegate_stake_percentage`, `initial_coldkeys`, `bootnodes`). The script should expose these as `--name`, `--repo`, etc. CLI args with reasonable defaults for a template subnet. `initial_coldkeys` is a list of tuples — document the format clearly.
- No `.github/` directory exists in the repo yet. CI workflow creation starts from scratch.

## Common Pitfalls

- **Missing `ChainScoreSubmitter` import in server.py** — `ChainOverwatchReporter` is imported but `ChainScoreSubmitter` is not. The planner must add `from subnet.consensus.chain_submitter import ChainScoreSubmitter` to server.py.
- **Score type mismatch** — `peer_score.score` is float; `SubnetNodeConsensusData.score` is `int`. Passing the float directly produces a dataclass with float in an int field; `asdict()` in `submit()` will serialise it as float, and the chain may reject or silently truncate. Always `int(peer_score.score * 1e18)`.
- **Submitter instantiated per-iteration instead of once** — instantiate `ChainScoreSubmitter` once before the `while` loop (same pattern as `reporter` in `_overwatch_epoch_loop` lines 640–643). Instantiating inside the loop creates a new object every iteration, which is harmless but inconsistent.
- **`smoke_test_chain.py` raises instead of exits 1** — the script delegates to sub-scripts via `subprocess.run`; if a sub-script crashes with a non-zero exit, `smoke_test_chain.py` must still exit 1 cleanly (not propagate an unhandled exception). Use `check=False` with `subprocess.run` and inspect `returncode`.
- **`register_subnet.py` echoing the phrase** — credential loading must follow the `check_peers.py` pattern: read from env, never pass to `print()`/`argparse`/logging.
