# S02: Score Submission Extrinsic — Research

**Date:** 2026-03-17

## Summary

The score submission machinery is almost entirely implemented. `Consensus.run_consensus()` in `subnet/consensus/consensus.py` already does exactly what S02 requires: it calls `hypertensor.propose_attestation(subnet_id, data=...)` when the node is the elected validator, and `hypertensor.attest(subnet_id)` when it is an attestor. Both paths are wired into `Server.run()` via `nursery.start_soon(consensus._main_loop)` when `enable_consensus=True`. In chain mode (`--no_blockchain_rpc` absent), `self.hypertensor` is a real `Hypertensor` instance, so those calls land on-chain.

The gaps S02 must close are: (1) a `ChainScoreSubmitter` wrapper class per the boundary map — a thin, testable layer around `propose_attestation`; (2) per-node credential wiring in `docker-compose.chain.yml` — the current compose passes a single `PHRASE` to all services, but each registered node has a different hotkey and needs its own mnemonic for signing; (3) a `scripts/check_scores.py` verification script that queries `SubnetConsensusSubmission` to confirm scores landed on-chain after an epoch.

The extrinsic name is `propose_attestation` (pallet module `"Network"`), not `submit_score`. This is Hypertensor's two-phase consensus: elected validator proposes, other validators attest. Score format is `List[{"subnet_node_id": int, "score": int}]` where score is `int(1e18 * tee_score)` — already the output of `Consensus.get_scores()`.

## Recommendation

Three focused tasks, no new substrate patterns needed — all patterns exist in `chain_functions.py` and `consensus.py`:

1. **`ChainScoreSubmitter`** — a thin class in `subnet/consensus/chain_submitter.py` wrapping `propose_attestation`. Needed by boundary map (S03 consumes it), testable without a live chain, and clean separation of submission logic from the epoch loop. Mirror the `propose_attestation` error-handling pattern (`receipt.is_success` check, `logger.error` on failure).

2. **`scripts/check_scores.py`** — queries `SubnetConsensusSubmission` for a given epoch; the primary verification artifact for this slice. Mirrors `check_peers.py` patterns (credential redaction, friendly-ID resolution, structured stdout/stderr).

3. **`docker-compose.chain.yml` credential hardening** — change `PHRASE: ${PHRASE:-}` to per-service env var overrides (`VALIDATOR_PHRASE`, `MINER1_PHRASE`, `MINER2_PHRASE`). The validator's PHRASE must be `:?` since it signs `propose_attestation`. Attestors (`attest()` is also a signed extrinsic) similarly need real keypairs.

## Implementation Landscape

### Key Files

- `subnet/hypertensor/chain_functions.py` — `Hypertensor.propose_attestation(subnet_id, data, ...)` at line 173; already handles SCALE encoding, nonce fetching, `wait_for_inclusion`, retry with `tenacity`. No changes needed. `Hypertensor.attest(subnet_id, ...)` at line 234. `get_rewards_validator(subnet_id, epoch)` queries `SubnetElectedValidator` at line 1378. `get_rewards_submission(subnet_id, epoch)` queries `SubnetConsensusSubmission` at line 1431. `get_consensus_data_formatted(subnet_id, epoch)` at line 2344 returns a `ConsensusData` dataclass.

- `subnet/consensus/consensus.py` — `Consensus.run_consensus(current_epoch)` contains the full validator/attestor logic (~lines 265–420). Calls `get_scores()` → `propose_attestation(subnet_id, data=[asdict(s) for s in scores])` when elected. Already handles empty-scores case and attestation comparison. No changes needed unless adding `ChainScoreSubmitter` call here (optional refactor).

- `subnet/hypertensor/chain_data.py` — `SubnetNodeConsensusData(subnet_node_id: int, score: int)` at line 1187. This is the score element format. `asdict()` → `{"subnet_node_id": N, "score": M}` is what `propose_attestation` receives as `data`.

- `subnet/server/server.py` — `Consensus` is instantiated and started at lines 408–417 when `enable_consensus=True`. `hypertensor` is passed in; in chain mode it is a real `Hypertensor` instance. No changes needed here.

- `subnet/cli/run_node.py` — line 31: `PHRASE = os.getenv("PHRASE")`. Lines 476–490: phrase resolution priority: `--phrase` arg > `--tensor_private_key` arg > `PHRASE` env var. Per-service PHRASE is the right lever in compose.

- `docker-compose.chain.yml` — `x-chain-env` anchor has `PHRASE: ${PHRASE:-}` (optional, same value for all services). Must become per-service with `:?` for any node that signs extrinsics (validator + all attestors = all non-bootnode services).

- `scripts/check_peers.py` — pattern source for `check_scores.py`. Credential redaction, friendly-ID resolution, error exit conventions all apply unchanged.

### New Files

- `subnet/consensus/chain_submitter.py` — `ChainScoreSubmitter(hypertensor, subnet_id)` with `.submit(scores: List[SubnetNodeConsensusData]) -> ExtrinsicReceipt | None`. Thin wrapper; all real work is in `Hypertensor.propose_attestation`.

- `scripts/check_scores.py` — queries `SubnetConsensusSubmission` for a given epoch; verifies scores landed after running compose stack.

- `tests/consensus/test_chain_submitter.py` — unit tests for `ChainScoreSubmitter`; mock `Hypertensor` to verify correct params, receipt handling, empty-score edge case.

### Build Order

1. **`ChainScoreSubmitter` class + unit tests first** — zero chain dependency; can be verified with `pytest -x -q`. Establishes the interface S03 will consume. Takes ≤1h.

2. **`scripts/check_scores.py`** — no new patterns beyond `check_peers.py`; straightforward. Primary slice verification artifact.

3. **`docker-compose.chain.yml` per-node credentials** — last because it requires understanding which services need which phrase. Update the compose anchor + per-service overrides + update the header comment block to document `VALIDATOR_PHRASE`, `MINER1_PHRASE`, `MINER2_PHRASE`.

### Verification Approach

```bash
# Layer 1 — unit tests must still pass
pytest tests/ -x -q
# → 183+ passed, 0 failed

# ChainScoreSubmitter unit tests
pytest tests/consensus/test_chain_submitter.py -v

# check_scores.py error path (no chain running)
python3 scripts/check_scores.py --local_rpc --subnet_id 1 --epoch 0 2>&1; echo EXIT=$?
# → ERROR: Cannot connect to ws://127.0.0.1:9944: ... 
# → EXIT=1

# check_scores.py credential redaction
PHRASE="super secret mnemonic" python3 scripts/check_scores.py --local_rpc --subnet_id 1 --epoch 0 2>&1 \
  | grep -i "super secret"; echo GREP_EXIT=$?
# → GREP_EXIT=1 (no match = redacted)

# docker-compose credential guard fires
CHAIN_ENDPOINT=wss://rpc.hypertensor.app:443 SUBNET_ID=1 \
  docker compose -f docker-compose.chain.yml config 2>&1 | grep VALIDATOR_PHRASE
# → error: required variable VALIDATOR_PHRASE is missing

# Live integration (requires testnet): check_scores.py returns scores post-epoch
PHRASE="..." python3 scripts/check_scores.py \
  --chain wss://rpc.hypertensor.app:443 --subnet_id 1 --epoch N
# → [OK] Scores found for epoch N: N entries
# → subnet_node_id=1 score=500000000000000000
```

## Constraints

- **`propose_attestation` composes the call outside the retry block** (line ~188). The nonce is fetched *inside* the retry. This is intentional — `compose_call` is idempotent; nonce must be fresh per attempt. `ChainScoreSubmitter` must not re-compose between retries. Follow the existing pattern exactly.

- **`Hypertensor.__init__` creates keypair eagerly** — an empty or missing phrase raises before the WebSocket opens. `PHRASE` must be non-empty for all services that sign extrinsics. This is the credentialing constraint documented in S01 Forward Intelligence.

- **`get_rewards_validator` returns a raw SCALE result** — `Consensus.run_consensus()` compares it with `self.subnet_node_id` directly. If the chain returns a SCALE-wrapped int, the comparison `validator == self.subnet_node_id` may silently miss. The existing code at line ~330 uses `if validator == self.subnet_node_id:` — check what `int(str(result))` vs raw result does. The existing consensus logic already handles this (has been working in mock mode), so S02 should not change this logic, only wrap it.

- **Score format is `u128` integer, not float** — `int(1e18 * tee_score)` is the expected encoding. `ChainScoreSubmitter` must receive `List[SubnetNodeConsensusData]` with pre-computed integer scores, not raw floats.

- **`asdict(s)` on `SubnetNodeConsensusData`** produces `{"subnet_node_id": N, "score": M}` which matches `propose_attestation`'s `data` param type. No SCALE serialization needed at the Python level — `substrateinterface` handles it.

## Common Pitfalls

- **Same `PHRASE` for all nodes in compose** — `x-chain-env` propagates to all 4 services. All 4 would sign as the same hotkey. The chain would see extrinsics from a single account claiming to be multiple nodes. Use per-service `PHRASE` environment override (e.g., `PHRASE: ${VALIDATOR_PHRASE:?...}` in the validator service's `environment:` block, NOT in the shared anchor).

- **`get_rewards_validator` returns `None` before validator is elected** — `Consensus.run_consensus()` already handles this in a polling loop. `ChainScoreSubmitter` should not call `get_rewards_validator` — that is the `Consensus` layer's job. `ChainScoreSubmitter` is purely a submission wrapper.

- **Empty score list is valid** — `propose_attestation(subnet_id, data=[])` is allowed by the chain and means "subnet in broken state, no nodes scored." The existing `Consensus.run_consensus()` handles this case (submits empty list). `ChainScoreSubmitter.submit([])` must not short-circuit or raise; it must call through.

- **`attest()` also requires a signed keypair** — attestors are not just observers. `attest()` at line 234 is also a signed extrinsic. Miners in the compose stack that reach `SubnetNodeClass.Validator` (after graduation) will also attest. All non-bootnode services need a valid `PHRASE`.

## Open Risks

- **Validator election timing**: The chain elects one validator per epoch via `SubnetElectedValidator`. If no node has `SubnetNodeClass.Validator` class yet (all are `Idle` or `Included`), `get_rewards_validator` may return `None` indefinitely. The existing `Consensus.run_is_node_validator()` guards against this — but the first few epochs after registration may produce no submissions. Not a code bug; document expected behavior in `CHAIN.md`.

- **`int(str(result))` for `get_rewards_validator` return value** — the raw `result` is a SCALE object. The existing `Consensus.get_validator()` does NOT call `int(str(...))` before comparing. If the SCALE object equality comparison with `self.subnet_node_id` (an int) fails silently (no elected validator path triggers), propose_attestation never fires. Should be verified with a real testnet run — this is the integration smoke test.

## Sources

- `subnet/consensus/consensus.py` — `run_consensus()` is the authoritative source for the propose/attest flow; `get_scores()` for score computation
- `subnet/hypertensor/chain_functions.py` — `propose_attestation()` and `attest()` for exact call params and retry semantics
- `subnet/hypertensor/chain_data.py` — `SubnetNodeConsensusData` for score wire format
- `scripts/check_peers.py` — canonical pattern for all `check_*.py` scripts (credential redaction, error exits, friendly-ID resolution)
