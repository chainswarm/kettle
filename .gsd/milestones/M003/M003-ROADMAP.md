# M003: Layer 1 — In-Memory Test Suite

**Vision:** Every subnet behaviour — miner, validator, overwatch, fault injection, TEE attestation, scoring — is provable in under 2 seconds with `pytest`, zero docker, zero chain. This is the foundation. If Layer 1 doesn't pass, nothing else matters.

## Success Criteria

- `pytest tests/` runs in < 2 seconds and all tests are green
- Tampered work (wrong parity) is caught by validator AND overwatch in separate tests
- `TAMPER_RATE=1.0` always fails; `TAMPER_RATE=0` always passes
- TEE quote hash binding is verified: publishing a different quote breaks overwatch
- Scoring formula is exercised for all four cases: mock/real TEE × correct/wrong parity
- A new subnet developer can read `tests/test_mock_node.py` and understand the full pipeline end-to-end

## Key Risks / Unknowns

- Test isolation — each test needs a fresh `tmp_path` db or tests bleed into each other
- `TAMPER_RATE` as a module-level variable is thread-safe in pytest but must be restored after each test

## Proof Strategy

- TEE hash binding → proven in `TestOverwatch.test_overwatch_detects_tampered_tee_hash`
- Fault injection → proven in `TestTampering.test_tamper_rate_one_always_tampers`
- End-to-end pipeline → proven in `TestEndToEnd.test_full_pipeline`

## Verification Classes

- Contract verification: 155+ pytest tests covering all node types
- Integration verification: none (in-memory, no real network)
- Operational verification: none
- UAT / human verification: `pytest tests/ -v` output readable by a new developer

## Milestone Definition of Done

- All tests green
- `test_mock_node.py` covers: miner, validator, scorer, overwatch, fault injection, end-to-end
- No test requires docker, chain, or network access
- `TESTING_LAYERS.md` exists and describes Layer 1 accurately

## Requirement Coverage

- Covers: R001 (mock TEE), R002 (verifiable work), R003 (overwatch), R004 (fault injection)
- Leaves for later: chain integration (M005), real P2P (M004)

## Slices

- [x] **S01: Mock node protocol + scoring** `risk:high` `depends:[]`
  > After this: `pytest tests/test_mock_node.py` runs and miner/validator/scorer tests pass
- [x] **S02: Overwatch verifier** `risk:medium` `depends:[S01]`
  > After this: overwatch independently verifies work without session key; tamper detection tests pass
- [x] **S03: Fault injection** `risk:low` `depends:[S01]`
  > After this: `TAMPER_RATE` controls how often miner sends bad data; caught by both validator and overwatch

## Boundary Map

### S01 → S02

Produces:
- `_WORK_TOPIC` DHT record schema: `{epoch, peer_id, n, parity, tee_quote_hash}`
- `NodeValidatorResult.metrics` shape: `{tee_score, n, parity, correct}`

Consumes:
- nothing (first slice)

### S01 → S03

Produces:
- `MockNodeProtocol.miner_loop()` — the function fault injection wraps

Consumes:
- nothing (first slice)

### S03 → done

Produces:
- `TAMPER_RATE` module-level constant, patchable in tests
- `tampered` field in `NodeMinerResult.metrics`

Consumes:
- `_check_parity()` from S01
