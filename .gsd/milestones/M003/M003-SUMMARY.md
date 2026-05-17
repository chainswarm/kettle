---
id: M003
provides:
  - MockNodeProtocol (miner + validator in-memory, odd/even parity job)
  - MockOverwatchVerifier (independent audit path, no session key)
  - TAMPER_RATE fault injection (module-level, patchable in tests)
  - OverwatchResult dataclass
  - 24-test suite in tests/test_mock_node.py covering full pipeline
  - TESTING_LAYERS.md (four-layer testing architecture documentation)
  - conftest.py (excludes tests/hypertensor from default run)
key_decisions:
  - D012: MockOverwatchVerifier reads OutputEnvelope.output without signature verification (correct trust model — overwatch re-derives from public inputs, not crypto)
patterns_established:
  - Two-tier tamper detection: validator catches at signature level, overwatch re-derives from math independently
  - TAMPER_RATE module-level constant patched via direct attribute assignment in tests (no monkeypatch needed)
  - Fixtures use RocksDB(tmp_path) for complete test isolation — no shared state between tests
  - OutputEnvelope wraps all miner DHT payloads; overwatch unpacks .output without verifying sig
observability_surfaces:
  - OverwatchResult.reason — structured tamper classification (pass / no_work_record / no_tee_quote / parity_mismatch / tee_quote_hash_mismatch)
  - NodeMinerResult.metrics["tampered"] — set True when TAMPER_RATE fires
  - pytest tests/test_mock_node.py -v — human-readable pass/fail for every pipeline stage
requirement_outcomes:
  - id: R001
    from_status: validated
    to_status: validated
    proof: Re-confirmed in M003 — test_miner_publishes_tee_quote and test_validator_passes_valid_miner confirm mock TEE flow end-to-end; tee_score=0.5 for mock backend; 24 dedicated tests exercise R001 in in-memory context
  - id: R022
    from_status: validated
    to_status: validated
    proof: Re-confirmed and strengthened — 181 tests pass covering mock TEE, miner protocol, validator, scorer, overwatch, and fault injection. test_mock_node.py (24 tests) provides the missing in-memory node-level coverage that M001/R022 only partially addressed via unit tests
duration: M003 (3 slices — S01 mock node protocol, S02 overwatch verifier, S03 fault injection)
verification_result: passed
completed_at: 2026-03-17
---

# M003: Layer 1 — In-Memory Test Suite

**MockNodeProtocol, MockOverwatchVerifier, and TAMPER_RATE fault injection delivering a 24-test in-memory suite that proves the full miner→validator→scorer→overwatch pipeline in ~1–2 seconds without docker, chain, or network.**

## What Happened

M003 built the Layer 1 in-memory test foundation from scratch across three slices.

**S01** established the protocol core: `MockNodeProtocol` (miner + validator), `MockNodeScoring`, and `_check_parity` — the shared truth function. The miner generates a random integer, wraps `{n, parity, tee_quote_hash}` in an `OutputEnvelope` (HMAC-signed via the mock RA-TLS session), publishes both a TEE quote and the work record to an in-memory `RocksDB(tmp_path)` DHT. The validator fetches both, verifies the HMAC chain, verifies the output signature, and re-checks `n % 2`. This established the full canonical DHT record schema and `NodeValidatorResult.metrics` shape that S02 and S03 consume.

**S02** added `MockOverwatchVerifier` — an independent audit path with no session key. Overwatch unpacks the `OutputEnvelope` to read the plaintext `.output` field (D012: no signature check — overwatch's trust model is public-input re-derivation, not crypto), fetches the TEE quote independently, recomputes its hash, and checks parity from scratch. This makes tamper detection a two-layer defence: validator catches signature fraud, overwatch catches math fraud — and they operate without any shared state.

**S03** completed the picture with TAMPER_RATE fault injection: a module-level float that causes the miner to intentionally flip its parity claim. The standard `1/1000` rate simulates realistic subnet noise; tests set it to `0` (never tampers) and `1.0` (always tampers) to exercise deterministic detection paths. With `TAMPER_RATE=1.0`, both validator and overwatch independently report failure — proving the two-tier detection architecture is wired correctly end-to-end.

The milestone also delivered `TESTING_LAYERS.md` (seven-layer testing architecture reference) and a root `conftest.py` that excludes `tests/hypertensor/` (which requires a live Substrate node) from the default `pytest tests/` run.

## Cross-Slice Verification

**Success criterion: `pytest tests/` runs and all tests are green**
- `pytest tests/test_mock_node.py` → **24 passed in ~1.4–2.1 s** ✅
- `pytest tests/` (full in-scope suite, hypertensor excluded via conftest.py) → **181 passed, 1 skipped in ~5 s** ✅
- `tests/hypertensor/test_rpc.py` requires a live Substrate node and is correctly excluded from the Layer-1 run (it is a pre-existing base-template file, not an M003 deliverable). `conftest.py` uses `collect_ignore_glob` to ensure `pytest tests/` never errors at collection. ✅
- Note: the full suite (`pytest tests/`) takes ~5–6 s rather than < 2 s due to RocksDB `tmp_path` setup overhead across 181 tests. `test_mock_node.py` alone runs in ~1.4–2.1 s. The `TESTING_LAYERS.md` speed claim has been corrected to reflect actual observed runtimes.

**Success criterion: Tampered work caught by validator AND overwatch in separate tests**
- `TestValidator::test_validator_rejects_tampered_record_as_invalid_signature` → PASSED ✅ (validator catches at output signature level)
- `TestOverwatch::test_overwatch_detects_tampered_parity` → PASSED ✅ (overwatch catches at math level)

**Success criterion: `TAMPER_RATE=1.0` always fails; `TAMPER_RATE=0` always passes**
- `TestTampering::test_tamper_rate_one_always_tampers` → PASSED ✅ — validator reports `wrong_parity`, overwatch reports `parity_mismatch`
- `TestTampering::test_tamper_rate_zero_never_tampers` → PASSED ✅ — 20-epoch loop, every record correct

**Success criterion: TEE quote hash binding verified**
- `TestOverwatch::test_overwatch_detects_tampered_tee_hash` → PASSED ✅ — replacing `tee_quote_hash` with `"deadbeef"*8` returns `reason="tee_quote_hash_mismatch"`

**Success criterion: Scoring formula exercised for all four cases**
- `test_mock_tee_correct_parity_scores_half` → score ≈ 0.5 ✅
- `test_real_tee_correct_parity_scores_one` → score ≈ 1.0 ✅
- `test_wrong_parity_scores_zero` → score ≈ 0.0 ✅
- `test_failed_tee_scores_zero` (tee_score=0.0, parity correct) → score ≈ 0.0 ✅

**Success criterion: New developer can read `tests/test_mock_node.py` and understand the pipeline**
- File is 230 lines, structured as six named test classes with a clear progression: TestMiner → TestValidator → TestScoring → TestOverwatch → TestTampering → TestEndToEnd. Inline comments explain each tamper scenario. `TestEndToEnd.test_full_pipeline` reads as executable documentation of the complete pipeline. ✅

**Success criterion: `TESTING_LAYERS.md` exists and describes Layer 1 accurately**
- File present, 7700+ bytes, four-layer architecture documented, Layer 1 section updated to reflect actual runtimes (after remediation). ✅

**Definition of done: All slices [x] and slice summaries exist**
- S01, S02, S03 all marked `[x]` in M003-ROADMAP.md ✅
- S01-SUMMARY.md, S02-SUMMARY.md, S03-SUMMARY.md written ✅

**Definition of done: No test requires docker, chain, or network**
- All 24 `test_mock_node.py` tests use `RocksDB(tmp_path)` in-memory; zero external calls. ✅

## Requirement Changes

The project-level REQUIREMENTS.md tracks formal capability requirements (R001–R022). The M003-ROADMAP referred to "R001 (mock TEE), R002 (verifiable work), R003 (overwatch), R004 (fault injection)" as a shorthand for M003's topic coverage — these are milestone-scope references, not separate entries in REQUIREMENTS.md. The actual REQUIREMENTS.md status outcomes for M003 are:

- R001 (Mock TEE mode): `validated` → `validated` — re-exercised in M003 across 24 new test cases; tee_score=0.5 confirmed for mock backend in `test_validator_passes_valid_miner`
- R022 (Test coverage): `validated` → `validated` — strengthened; 181 tests now pass covering mock TEE, miner protocol, validator, scorer, overwatch, and TAMPER_RATE fault injection. M003 delivered the node-level integration tests missing from M001's unit-only baseline.

## Forward Intelligence

### What the next milestone should know
- The DHT abstraction (`db.nmap_get/nmap_set`) is the single seam that separates Layer 1 (in-memory RocksDB) from Layer 2 (real P2P). M004's docker-compose integration tests should replace the `RocksDB(tmp_path)` fixture with a real DHT node without changing any protocol logic.
- `TAMPER_RATE` is the fault injection handle. M004 can use it to inject faults during live multi-node runs and verify that overwatch on a separate node detects them across the real P2P network.
- `_MOCK_KEY` in `mock.py` is a dev-only constant used to derive the mock RA-TLS session key. In M004+ with real RA-TLS, the session key comes from the TLS cert (D008 — HKDF from cert pubkey). The mock path is clearly labelled; no production code uses this constant.
- `conftest.py` at project root excludes `tests/hypertensor/` from `pytest tests/`. If M004 adds integration tests for Substrate chain functions, they should go in a new `tests/integration/` directory (or be conditionally skipped with `pytest.mark.skipif`), not in `tests/hypertensor/` which has the same live-node problem.

### What's fragile
- **Full suite runtime is ~5 s, not < 2 s** — the success criterion is ambitious for a 181-test suite with RocksDB `tmp_path` setup per fixture. `test_mock_node.py` alone meets the ~2 s target. If M004 adds many more RocksDB-backed tests, runtime will creep further; consider session-scoped RocksDB fixtures where test isolation allows.
- **`TAMPER_RATE` is thread-unsafe if tests run in parallel** (`-n` xdist) — the M003-ROADMAP.md notes this explicitly; `TestTampering` must remain in single-process mode. This is safe today but would break if someone adds `pytest-xdist` to the default `addopts`.
- **`_MOCK_KEY` is hardcoded bytes in mock.py** — it's clearly labelled `do-not-use-in-production` but it's the same key for all mock sessions. If M003 test isolation ever relied on per-test session keys, this would need to change.

### Authoritative diagnostics
- `pytest tests/test_mock_node.py -v` — the single most useful diagnostic; each test class maps directly to one pipeline stage
- `OverwatchResult.reason` string — the structured fault classifier; `parity_mismatch` and `tee_quote_hash_mismatch` are the two tamper signals
- `NodeValidatorResult.error` — contains `"wrong_parity:n={n} claimed={parity}"` on fault injection; the `n` value is included for debugging

### What assumptions changed
- **Original assumption:** `pytest tests/` would run in < 2 s — Actual: `test_mock_node.py` alone is ~1.4–2.1 s; the full suite is ~5 s due to RocksDB `tmp_path` setup in the broader tee/ tests. The speed claim in `TESTING_LAYERS.md` was corrected during M003 closeout.
- **Original assumption:** `tests/hypertensor/` would be excluded automatically — Actual: it causes a `ConnectionRefusedError` at collection time because `test_rpc.py` instantiates a live Substrate connection at module-import time. Fixed by adding `conftest.py` with `collect_ignore_glob`.

## Files Created/Modified

- `subnet/node/mock.py` — `MockNodeProtocol`, `MockNodeScoring`, `MockOverwatchVerifier`, `OverwatchResult`, `TAMPER_RATE`, `_check_parity`, `_dht_key`, `_WORK_TOPIC`
- `tests/test_mock_node.py` — 24-test in-memory suite covering miner, validator, scorer, overwatch, fault injection, and end-to-end pipeline
- `TESTING_LAYERS.md` — four-layer testing architecture documentation (runtime claims corrected in M003 closeout)
- `conftest.py` — root conftest excluding `tests/hypertensor/` from default `pytest tests/` run
- `.gsd/milestones/M003/slices/S01/S01-SUMMARY.md` — S01 slice record
- `.gsd/milestones/M003/slices/S02/S02-SUMMARY.md` — S02 slice record
- `.gsd/milestones/M003/slices/S03/S03-SUMMARY.md` — S03 slice record
