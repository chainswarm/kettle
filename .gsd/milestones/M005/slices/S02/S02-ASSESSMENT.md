# S02 Roadmap Assessment

**Verdict:** Roadmap still sound — minor boundary map corrections applied.

## What S02 Actually Built

- `ChainScoreSubmitter(hypertensor, subnet_id).submit(scores: List[SubnetNodeConsensusData])` — batch interface (not per-node `submit(peer_id, score, epoch)` as originally spec'd); this matches `propose_attestation`'s actual API shape
- `scripts/check_scores.py` — full `check_peers.py` pattern parity
- Per-service `:?`-guarded PHRASE vars in `docker-compose.chain.yml` for validator, miner-1, miner-2
- 5 unit tests; 188 total tests passing (1 skipped)
- **Not built:** `substrate_client.py` module (never existed; was a spec artefact)

## Concrete Inaccuracies Fixed in Boundary Map

1. **S02→S03 "Produces"**: Updated from `submit(peer_id, score, epoch)` to the real batch signature `submit(scores: List[SubnetNodeConsensusData])`. Added explicit note that `substrate_client.py` does not exist — S03 constructs `Hypertensor` directly.
2. **S03→S04 "Consumes"**: Removed reference to `S02 substrate_client` (does not exist). Replaced with `ChainScoreSubmitter` thin-wrapper pattern and `Hypertensor` construction pattern.
3. **S04→done "Produces"**: Added explicit ownership of wiring `ChainScoreSubmitter.submit()` into the validator epoch loop — S02 intentionally deferred this; S04 must land it.
4. **S04→done "Consumes"**: Named the batch interface field contract (`{"subnet_node_id": N, "score": M}`) and the diagnostic scripts that feed `smoke_test_chain.py`.

## Success Criterion Coverage

- `SubnetInfoTracker reads peer list from chain` → S01 ✅ done
- `Validator submits submit_score each epoch; scores in chain state` → **S04** (submitter ready; wiring + live proof owned by S04)
- `Token emissions proportional to peer scores` → **S04** (live testnet proof)
- `Overwatch submits slash_node; stake slashed` → **S03**
- `Node registration and staking flow in CHAIN.md` → **S04**
- `MOCK_TEE=true works on testnet` → **S04** (smoke test)
- `Layer 1 + Layer 2 still green` → **S03, S04** (regression guard)

All criteria covered. No blocking gaps.

## Risk Retirement

S02 was `risk:high`. It retired the extrinsic-signing design risk (thin-wrapper pattern established, credential-loading pattern parity confirmed, compose guard pattern solid). Residual risk: `asdict(s)` field contract (`{"subnet_node_id": N, "score": M}`) — flagged in forward intelligence; S04 should add a guard if the dataclass evolves.

## Requirement Coverage

Unchanged and sound:
- R010 (score extrinsic) — `ChainScoreSubmitter` is the production path; unit-tested contract established; live chain proof deferred to M005 integration milestone (S04)
- R022 (test coverage) — 188 passing, 1 skipped; 5 new unit tests

No requirements invalidated, newly surfaced, or re-scoped.
