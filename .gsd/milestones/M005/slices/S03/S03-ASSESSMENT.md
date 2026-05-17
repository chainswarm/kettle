---
id: S03-ASSESSMENT
parent: M005/S03
assessed_at: 2026-03-17
verdict: roadmap_unchanged
---

# Roadmap Assessment After S03

## Verdict: Roadmap Confirmed — S04 Unchanged

S03 delivered exactly what the roadmap specified. No slice reordering, splitting, or addition is warranted.

## Success-Criterion Coverage

All M005 success criteria remain covered by S04:

- `SubnetInfoTracker reads peer list from chain` → ✅ retired S01
- `Validator submits submit_score each epoch; scores in chain state` → S04 (wiring deferred; class ready)
- `Token emissions proportional to peer scores` → S04 (live testnet run)
- `Overwatch submits slash_node; stake slashed` → S04 (live TAMPER_RATE=1.0 confirmation)
- `CHAIN.md documents registration, staking, running` → S04
- `MOCK_TEE=true still works on testnet` → structurally confirmed; S04 verifies in CI
- `Layer 1 and Layer 2 still green` → S04 CI job

Coverage check: **passes**.

## What S03 Actually Built (vs. Plan)

- Delivered as specified: `ChainOverwatchReporter.slash()`, `check_slash.py`, `OVERWATCH_PHRASE` guard, 5 unit tests, wiring into `_overwatch_epoch_loop`.
- One documented deviation (D008): constructor is `(hypertensor, overwatch_node_id, subnet_id)` — three args, not two. The S03→S04 boundary map in the roadmap was updated to reflect the actual constructor signature, evidence format (bytes not structured dict), and the additional deliverables (`check_slash.py`, `OVERWATCH_NODE_ID` pass-through). This is a documentation correction only; S04's work scope does not change.

## Risk Assessment

- No new risks surfaced. The fragile items noted in S03 (RPC method name stability for `get_overwatch_commits`/`get_overwatch_reveals`, salt non-persistence across crashes) are known and documented — both are appropriate to address in S04 live testing rather than by adding new slices.
- `ChainScoreSubmitter.submit()` is still not wired into the validator epoch loop — this is explicitly S04's job and remains on track.

## Requirement Coverage

- R011 (slash extrinsic): advanced by S03 (implementation complete, contract-verified); moves to `validated` after S04 live testnet confirmation.
- R009, R010, R012: unchanged; S04 owns the live validation pass for all three.
- No requirements invalidated, re-scoped, or newly surfaced.

## Conclusion

S04 is next. Its scope is unchanged: wire `ChainScoreSubmitter.submit(scores)` into the validator epoch loop, write `CHAIN.md`, produce registration/node scripts and `smoke_test_chain.py`, run the live testnet confirmation for all deferred proof criteria.
