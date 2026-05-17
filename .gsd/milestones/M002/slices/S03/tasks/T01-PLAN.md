---
estimated_steps: 4
estimated_files: 1
---

# T01: Write failing integration tests for SealedStore-in-miner

**Slice:** S03 — Sealed Storage
**Milestone:** M002

## Description

Create `tests/tee/test_sealed_integration.py` with three integration tests that assert the full S03 contract: miner seals epoch stats during `miner_loop`, same measurement can unseal, different measurement raises `SealedDecryptionError`. All three tests must be collectable but fail at run time (not import time) until T02 wires `SealedStore` into `MockNodeProtocol`. This is the spec-first pattern established in S02.

## Steps

1. Create `tests/tee/test_sealed_integration.py`. Add module docstring describing the three tests and their purpose.
2. Copy the `db` fixture and `_make_proto` helper from `tests/test_mock_node.py` (same `tmp_path` RocksDB setup, same `db.store.close()` teardown). Add a `miner` fixture that returns a `MockNodeProtocol` instance via `_make_proto(db, PEER_A, "miner")`.
3. Write the three test functions with all cross-module imports placed *inside* the test body (not at module level) so `--collect-only` never fails:
   - `test_miner_seals_epoch_stats`: call `trio.run(mine, miner)` using the local `mine` helper (same pattern as `test_mock_node.py`); then assert `miner._sealed_store.exists(f"epoch_stats:{PEER_A}:{EPOCH}")` is `True`; unseal and `json.loads` the value; assert `"n"` and `"parity"` keys are present.
   - `test_miner_unseal_round_trip`: run `miner_loop(EPOCH)` once; unseal the epoch stats key; capture `n` and `parity`; assert they match the metrics returned by `miner_loop` (`result.metrics["n"]`, `result.metrics["parity"]`).
   - `test_different_measurement_raises_sealed_decryption_error`: run `miner_loop(EPOCH)` to seal data; import `SealedStore` and `SealedDecryptionError`; construct `alt_store = SealedStore(db=miner.db, measurement="ff" * 32, mock_key=MOCK_DEV_KEY)`; assert `pytest.raises(SealedDecryptionError)` when calling `alt_store.unseal(f"epoch_stats:{PEER_A}:{EPOCH}")`. Assert only on the exception type, not the message text.
4. Run `pytest --collect-only tests/tee/test_sealed_integration.py` to confirm 3 tests collected, no syntax errors. Then run the tests and confirm they fail (not error at collection).

## Must-Haves

- [ ] File `tests/tee/test_sealed_integration.py` created
- [ ] 3 tests collected by `pytest --collect-only` with no import/syntax errors
- [ ] Tests fail at runtime (not collect time) because `miner._sealed_store` does not exist yet
- [ ] `db.store.close()` teardown present in fixture (prevents RocksDB lock errors in later runs)
- [ ] `pytest.raises(SealedDecryptionError)` asserts only on exception type, not message text
- [ ] Pre-existing 21 `test_sealed.py` tests still pass (no fixture naming collision)

## Verification

```bash
# Confirm collection succeeds
python3 -m pytest --collect-only tests/tee/test_sealed_integration.py
# Expected: 3 items collected, no errors

# Confirm tests fail (not error at collection — AttributeError is correct)
python3 -m pytest tests/tee/test_sealed_integration.py -v
# Expected: 3 FAILED with AttributeError or similar

# Confirm no regression in sealed unit tests
python3 -m pytest tests/tee/test_sealed.py -v
# Expected: 21/21 PASSED
```

## Observability Impact

- Signals added/changed: None — test file only; no runtime code changed
- How a future agent inspects this: `pytest --collect-only tests/tee/test_sealed_integration.py` to verify 3 tests exist; run them to see current failure state
- Failure state exposed: `AttributeError: 'MockNodeProtocol' object has no attribute '_sealed_store'` — the canonical error until T02 is complete

## Inputs

- `tests/test_mock_node.py` — `db` fixture pattern, `_make_proto` helper, `mine` helper, `PEER_A`, `EPOCH` constants
- `tests/tee/test_sealed.py` — `SealedDecryptionError` assertion pattern (`pytest.raises(SealedDecryptionError)` without message check)
- `subnet/tee/sealed/__init__.py` — confirms `SealedStore`, `SealedDecryptionError` are importable from `subnet.tee.sealed`
- `subnet/tee/backends/mock.py` — `MOCK_MEASUREMENT`, `MOCK_DEV_KEY` import names

## Expected Output

- `tests/tee/test_sealed_integration.py` — 3 failing integration tests that will pass after T02
