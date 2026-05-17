# S03: Fault injection

## What Was Built

`TAMPER_RATE` fault injection in `subnet/node/mock.py` — a module-level float that controls how often the miner intentionally sends wrong parity, enabling deterministic validation of the detection pipeline.

**Implementation:**
- `TAMPER_RATE: float = 1/1000` — module-level constant (default ~0.1% of epochs).
- In `MockNodeProtocol.miner_loop()`: after computing the correct parity, `if random.random() < TAMPER_RATE` flips the parity claim and sets `tampered=True` in `NodeMinerResult.metrics`.
- The DHT record contains the (possibly wrong) claimed parity; the correct `n` is always published, so overwatch and validator can independently detect the lie.

**`NodeMinerResult.metrics`** gains the `tampered: bool` field set by S03 when fault injection fires.

**Test pattern:** Tests patch `mock_module.TAMPER_RATE` directly (module attribute assignment), restore via `try/finally`.

## Tests Delivered

`TestTampering` (2 tests in `tests/test_mock_node.py`):
- `test_tamper_rate_zero_never_tampers` — 20-epoch loop with `TAMPER_RATE=0`; every record has correct parity ✅.
- `test_tamper_rate_one_always_tampers` — `TAMPER_RATE=1.0`; single epoch mined, validator returns `success=False` with `"wrong_parity"` in error, overwatch returns `ok=False, reason="parity_mismatch"` ✅.

## Cross-Detection Proof

With `TAMPER_RATE=1.0`, tampered work is caught by **two independent layers**:
1. **Validator** — detects at signature level first: re-derives correct parity, finds mismatch → `wrong_parity` error.
2. **Overwatch** — detects at math level independently (no session key): `_check_parity(n) != claimed_parity` → `parity_mismatch`.

This proves the two-tier detection architecture is working end-to-end.

## Verification

`pytest tests/test_mock_node.py::TestTampering` → **2 passed** ✅
`pytest tests/test_mock_node.py::TestEndToEnd::test_tampered_parity_caught_by_both` → **1 passed** ✅
