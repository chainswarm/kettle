# S02: Live tamper detection demo — Research

**Date:** 2026-03-17

## Summary

S02 is targeted, not deep. The hard infrastructure work is done in S01: GossipSub transport is proven, `MockOverwatchVerifier` is fully implemented in `subnet/node/mock.py`, and the validator scoring loop already produces `score=0.00 correct=False` when it catches a wrong parity claim. What's missing is two wiring tasks:

1. `MockOverwatchVerifier` is never called in a running server. `server.py` has `_validator_scoring_loop` and `_miner_epoch_loop` but no `_overwatch_epoch_loop`. The class exists, works in tests, and produces the exact log lines the demo needs (`parity_mismatch`) — it just isn't hooked into the nursery.

2. `TAMPER_RATE` on miner-1 is `0.001` (1-in-1000). The milestone DoD requires demo verification with `TAMPER_RATE=1.0` (every epoch tampered). The compose file needs updating and a verification recipe.

After these two tasks, the demo observes: miner-1 flagged every epoch by both validator (`score=0.00 correct=False`) and overwatch (`[Overwatch] TAMPER ... parity_mismatch`); miner-2 passes cleanly every epoch (`score=0.50 correct=True`, `[Overwatch] PASS`).

## Recommendation

Write `_overwatch_epoch_loop` in `server.py` following the exact pattern of `_validator_scoring_loop` — poll epoch, score epoch-1, iterate non-self peers, call `MockOverwatchVerifier.verify()`, emit `[Overwatch] TAMPER` or `[Overwatch] PASS` log lines. Wire it with `nursery.start_soon`. Then update `TAMPER_RATE` on miner-1 to `1.0` in the compose file with a comment marking the production value (`0.001`). Finally verify with a live `docker compose up` and update `TESTING_LAYERS.md`.

No new libraries. No new protocols. No architectural decisions.

## Implementation Landscape

### Key Files

- `subnet/node/mock.py` — `MockOverwatchVerifier.verify(peer_id, epoch) → OverwatchResult`. Fully implemented. Reads `_WORK_TOPIC` and `TEE_QUOTE_TOPIC` from RocksDB (`db.nmap_get`). Logs `[Overwatch] PASS ...` on success, returns `OverwatchResult(ok=False, reason="parity_mismatch")` when n%2 disagrees with the miner's claim. Does NOT need the RA-TLS session key — independent audit by design.

- `subnet/server/server.py` — Has `_validator_scoring_loop` (lines ~370–430) and `_miner_epoch_loop` (~300–370) as module-level async functions. Both are wired via `nursery.start_soon` inside `Server.run()` at the non-bootstrap block (~line 330). The new `_overwatch_epoch_loop` goes here as a third module-level function and a third `nursery.start_soon` call.

- `docker-compose.tee-dev.yml` — `miner-1` has `TAMPER_RATE: "0.001"`. Change to `"1.0"` for the demo. `miner-2` stays `"0.001"` (honest reference). Validator has `TAMPER_RATE: "0.0"` — leave as-is (validator doesn't tamper).

- `TESTING_LAYERS.md` — Layer 2 section currently says `TAMPER_RATE=0.001` and promises overwatch audit; update to reflect `TAMPER_RATE=1.0` demo, actual log lines, and verification commands.

### Build Order

**T01 first — the overwatch loop.** This is the only non-trivial code change. Everything else depends on being able to observe overwatch output.

Write `_overwatch_epoch_loop` in `server.py`:
```python
async def _overwatch_epoch_loop(
    db,
    self_peer_id: str,
    hypertensor,
    subnet_id: int,
    termination_event,
) -> None:
```
Pattern: copy `_validator_scoring_loop`, remove the `protocol`/`scoring` args, replace `validator_call + score_peer` with `MockOverwatchVerifier(db=db).verify(peer_id, score_epoch)`. Log `[Overwatch] TAMPER` when `not result.ok` (include `result.reason`), `[Overwatch] PASS` when `result.ok`. Same 30–35s startup wait, same epoch-1 scoring, same peer iteration via `hypertensor.get_min_class_subnet_nodes_formatted`. Same `hasattr(peer_info, "peer_id")` pattern for peer extraction.

Wire in `Server.run()` alongside the other two loops:
```python
nursery.start_soon(
    _overwatch_epoch_loop,
    self.db,
    peer_id_str,
    self.hypertensor,
    self.subnet_id,
    termination_event,
)
```

**T02 — compose update.** Change `TAMPER_RATE: "0.001"` → `"1.0"` for miner-1 only (keep miner-2 honest). Add a comment with the production value. This is a one-line change.

**T03 — verify + document.** Run `docker compose up --build`, wait for epoch 3+, confirm expected log lines, update `TESTING_LAYERS.md`.

### Verification Approach

```bash
# Build and bring up the stack
docker compose -f docker-compose.tee-dev.yml up --build -d

# Wait ~60s for mesh formation and first scored epochs, then:

# Validator detects tamper in miner-1 every epoch
docker compose -f docker-compose.tee-dev.yml logs validator | grep "\[Validator\]"
# Expected:
#   [Validator] peer=<miner-1-prefix> epoch=N score=0.00 correct=False
#   [Validator] peer=<miner-2-prefix> epoch=N score=0.50 correct=True

# Overwatch independently confirms parity_mismatch on miner-1
docker compose -f docker-compose.tee-dev.yml logs validator | grep "\[Overwatch\]"
# Expected:
#   [Overwatch] TAMPER peer=<miner-1-prefix> epoch=N reason=parity_mismatch
#   [Overwatch] PASS peer=<miner-2-prefix> epoch=N

# Unit tests still green
python3 -m pytest tests/ -q --tb=short
# Expected: 181 passed, 1 skipped

# Tear down
docker compose -f docker-compose.tee-dev.yml down --volumes
```

## Constraints

- **Overwatch loop skips first 1–2 epochs** — same GossipSub cold-start miss as validator (no retransmit). With `TAMPER_RATE=1.0`, from epoch 3 onward every epoch is flagged. Don't count from epoch 1.
- **`MockOverwatchVerifier` has no session key** — it skips `OutputEnvelope.verify(session)`. This is intentional: overwatch only checks the math, not the signature. The validator loop does the sig check.
- **Peer list from mock chain** — `get_min_class_subnet_nodes_formatted(..., SubnetNodeClass.Validator)` returns all registered nodes including miners (mock chain doesn't distinguish classes). This is the same data source as the validator loop — the overwatch loop's peer iteration will work identically.
- **All non-bootstrap containers run overwatch** — miners also run `_overwatch_epoch_loop`. This is correct by design (any node can audit). The primary demo observability is in `docker compose logs validator`.

## Common Pitfalls

- **`MockOverwatchVerifier` import** — it's in `subnet.node.mock`, same module as `MockNodeProtocol`. Already imported at the top of `server.py` as `from subnet.node.mock import MockNodeProtocol, MockNodeScoring, _WORK_TOPIC`. Add `MockOverwatchVerifier` to this import.
- **Startup wait alignment** — use 35s (slightly more than validator's 30s) so work records from the miner's `_miner_epoch_loop` are available when overwatch first runs. Both depend on the same gossip flow.
- **No-work-record on first pass** — `MockOverwatchVerifier.verify()` returns `OverwatchResult(ok=False, reason="no_work_record")` if the gossip hasn't arrived yet. Log this at DEBUG level (not WARNING) to avoid noise on cold start. The validator loop has the same issue and silently handles it.
- **`TAMPER_RATE=1.0` means miner-1 fails TEE-quote-hash check** — no. `TAMPER_RATE` only flips the parity string in the work record. The TEE quote and its hash in the work record are still valid. Overwatch finds `parity_mismatch` (step 3), not `tee_quote_hash_mismatch` (step 4).
