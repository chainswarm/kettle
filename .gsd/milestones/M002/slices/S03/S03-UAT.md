# S03 UAT — Sealed Storage

**Date:** 2026-03-16
**Platform:** Python 3.x, in-memory RocksDB (plyvel mock), MOCK_MEASUREMENT + MOCK_DEV_KEY
**Branch:** gsd/M002/S03
**Test file:** `tests/tee/test_sealed_integration.py`

## Integration Test Evidence

| # | Test | Assertion | Result |
|---|------|-----------|--------|
| 1 | `test_miner_seals_epoch_stats` | `db.nmap_get("sealed", f"epoch_stats:{peer_id}:{epoch}")` is not None after `miner_loop` | ✅ PASSED |
| 2 | `test_miner_sealed_epoch_stats_round_trip` | `json.loads(miner._sealed_store.unseal(key))` returns `{"n": <int>, "parity": "even"\|"odd"}` matching the miner's computed stats | ✅ PASSED |
| 3 | `test_different_measurement_raises_sealed_decryption_error` | `SealedStore(db, different_measurement, MOCK_DEV_KEY).unseal(key)` raises `SealedDecryptionError` | ✅ PASSED |

## Regression Evidence

| Suite | Count | Result |
|-------|-------|--------|
| `tests/tee/test_sealed.py` (pre-existing sealed unit tests) | 21/21 | ✅ PASSED |
| `tests/test_mock_node.py` (mock node integration) | all | ✅ PASSED |
| Full suite (`tests/ --ignore=tests/hypertensor`) | **176/176** | ✅ PASSED |

## Commands Run

```bash
# Integration tests
python3 -m pytest tests/tee/test_sealed_integration.py -v
# → 3 passed in <1s

# Pre-existing sealed unit tests
python3 -m pytest tests/tee/test_sealed.py -v
# → 21 passed

# Full suite
python3 -m pytest tests/ --ignore=tests/hypertensor -q
# → 176 passed in 4.97s
```

## Observability Confirmed

- `[MockMiner] sealed epoch_stats epoch=<n>` INFO log emitted after each `miner_loop` seal
- `db.nmap_get("sealed", key)` returns opaque ciphertext blob (non-None) — confirms encryption is active
- `SealedDecryptionError` raised with `measurement mismatch or corruption` message on cross-measurement unseal attempt

## Requirements

- R015 — Sealed storage: **validated** *(M002/S03)*
