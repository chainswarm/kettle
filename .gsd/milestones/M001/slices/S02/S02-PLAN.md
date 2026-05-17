# S02: Full DCAP verifier — pipeline, TCB policy, consensus integration

**Goal:** Validators verify the complete quote pipeline in mock mode. All attack scenarios tested. `get_scores()` applies `tee_score` multiplier. S03's docker-compose can call into the real `Consensus` class.
**Demo:** 79 unit tests pass. Consensus `get_scores()` uses `DcapVerifier`.

## Must-Haves

- `DcapVerifier.verify(peer_id, epoch)` → `VerificationResult(score, ok, reason)`
- Rejection pipeline: missing → debug → nonce → identity → chain → measurement → TCB
- `Consensus.get_scores()` wired: `score = int(1e18 * tee_score)`
- `MIN_TEE_SCORE` enforced in consensus

## Proof Level

- This slice proves: contract (unit tests + integration tests, no running network)
- Real runtime required: no
- Human/UAT required: no

## Verification

- `cd /home/aphex5/work/subnet-template && python3 -m pytest tests/tee/ -v` → 79 passed
- Done when: all 79 tests green, consensus wired

## Tasks

- [x] **T01: DcapVerifier — full 7-step pipeline** `est:45m`
- [x] **T02: Wire verifier into Consensus.get_scores()** `est:20m`
- [x] **T03: Tests — all rejection + pass paths** `est:45m`

## Files Touched

- `subnet/tee/verifier.py`
- `subnet/consensus/consensus.py`
- `subnet/tee/__init__.py`
- `tests/tee/test_verifier.py`
- `tests/tee/test_consensus_integration.py`
