---
slice: S02
status: complete
commit: 162d44d
tests_added: 27
tests_total: 79
---

# S02 Summary: DcapVerifier + consensus integration

## What was built

- `subnet/tee/verifier.py` — `DcapVerifier` with 7-step rejection pipeline:
  1. Quote missing in DHT → `quote_not_found`
  2. `debug_mode=True` → `debug_mode`
  3. `nonce != epoch` → `nonce_mismatch` (replay protection)
  4. `report_data != sha256(peer_id:epoch)` → `identity_binding_failed` (Sybil)
  5. HMAC invalid (mock) / chain stub (TDX/SEV-SNP) → `chain_verification_failed`
  6. Measurement mismatch → `measurement_mismatch`
  7. TCB policy → 0.0 / 0.5 / 1.0

- `VerificationResult(score, ok, rejection_reason, quote, backend)` — structured for diagnostics

- `subnet/consensus/consensus.py` — `get_scores()` wired:
  - heartbeat check (base liveness)
  - `DcapVerifier.verify(peer_id, epoch-1)` per node
  - `score = int(1e18 * tee_score)`
  - `MIN_TEE_SCORE` gate: nodes below threshold excluded

- `subnet/server/server.py` — `_tee_publish_loop` started alongside heartbeat loop

- `docker-compose.tee-dev.yml` — 1 bootnode + 1 validator + 2 miners, `MOCK_TEE=true`

## Score semantics

| Scenario | tee_score | final |
|---|---|---|
| Mock backend, all checks pass | 0.5 | int(0.5e18) |
| Real TDX, UpToDate TCB | 1.0 | int(1e18) |
| Real TDX, strict, SW hardening | 0.0 | 0 |
| Any rejection | 0.0 | excluded |

## Tests

27 tests added: `tests/tee/test_verifier.py` (19), `tests/tee/test_consensus_integration.py` (8)
