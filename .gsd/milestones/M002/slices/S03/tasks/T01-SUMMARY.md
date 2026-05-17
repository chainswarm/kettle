---
id: T01
parent: S03
milestone: M002
provides:
  - tests/tee/test_sealed_integration.py with 3 failing integration tests for SealedStore-in-miner
key_files:
  - tests/tee/test_sealed_integration.py
key_decisions:
  - Cross-module TEE imports (SealedStore, SealedDecryptionError, MOCK_DEV_KEY) placed inside test bodies per spec-first pattern; basic infrastructure imports (RocksDB, MockNodeProtocol) kept at module level
patterns_established:
  - Spec-first integration test pattern: tests are collectable but fail at runtime until wiring is done (T02)
  - Expected failure mode documented in module docstring: AttributeError on _sealed_store
observability_surfaces:
  - pytest --collect-only tests/tee/test_sealed_integration.py → shows 3 tests exist
  - pytest tests/tee/test_sealed_integration.py -v → shows 3 FAILED with canonical AttributeError until T02 wires _sealed_store
duration: 10m
verification_result: passed
completed_at: 2026-03-16
blocker_discovered: false
---

# T01: Write failing integration tests for SealedStore-in-miner

**Created 3 failing integration tests in `tests/tee/test_sealed_integration.py` that specify the full S03 contract for measurement-bound sealed storage in the miner runtime.**

## What Happened

Created `tests/tee/test_sealed_integration.py` following the spec-first pattern established in S02. The three test functions cover:

1. **`test_miner_seals_epoch_stats`** — After `miner_loop` runs, `miner._sealed_store.exists(f"epoch_stats:{PEER_A}:{EPOCH}")` must be True; the sealed value must decrypt to a JSON dict with `"n"` and `"parity"` keys.

2. **`test_miner_unseal_round_trip`** — The unsealed `n` and `parity` values must exactly match `result.metrics["n"]` and `result.metrics["parity"]` returned by `miner_loop`.

3. **`test_different_measurement_raises_sealed_decryption_error`** — A `SealedStore` constructed with `measurement="ff" * 32` must raise `SealedDecryptionError` when attempting to unseal data sealed by the original binary.

Fixtures copied from `tests/test_mock_node.py`: `db` (tmp_path RocksDB + `d.store.close()` teardown), `_make_proto` helper, and a `miner` fixture. A local `mine` async helper mirrors the pattern from `test_mock_node.py`.

TEE-specific imports (`SealedStore`, `SealedDecryptionError`, `MOCK_DEV_KEY`) are placed inside test bodies to guarantee `--collect-only` never fails even if module-level imports were to break.

## Verification

```
# Collection — 3 tests collected, no errors
python3 -m pytest --collect-only tests/tee/test_sealed_integration.py
→ 3 items collected in 0.01s ✓

# Runtime failures — all 3 fail as expected
python3 -m pytest tests/tee/test_sealed_integration.py -v
→ FAILED test_miner_seals_epoch_stats         (AttributeError: no '_sealed_store')
→ FAILED test_miner_unseal_round_trip          (AttributeError: no '_sealed_store')
→ FAILED test_different_measurement_raises_*  (Failed: DID NOT RAISE — no data sealed)
→ 3 failed ✓ (all runtime failures, not collection errors)

# No regression in unit tests
python3 -m pytest tests/tee/test_sealed.py -v
→ 21/21 PASSED ✓
```

## Diagnostics

- `pytest --collect-only tests/tee/test_sealed_integration.py` — verifies 3 tests exist and imports are clean
- `pytest tests/tee/test_sealed_integration.py -v` — shows current failure state; `AttributeError: 'MockNodeProtocol' object has no attribute '_sealed_store'` is the canonical blocker until T02 wires `SealedStore` into `MockNodeProtocol.miner_loop`

## Deviations

None.

## Known Issues

None. All 3 tests fail at runtime exactly as designed; they will pass once T02 is complete.

## Files Created/Modified

- `tests/tee/test_sealed_integration.py` — 3 failing integration tests specifying the S03 contract
