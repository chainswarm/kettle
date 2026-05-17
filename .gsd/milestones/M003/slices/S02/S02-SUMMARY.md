# S02: Overwatch verifier

## What Was Built

`MockOverwatchVerifier` in `subnet/node/mock.py` — an independent audit path that verifies miner work without any session key.

**Trust model:** Overwatch cannot call `OutputEnvelope.verify()` (it has no session key). It unpacks the envelope to access the plaintext `.output` field and re-derives correctness from public inputs only.

**`MockOverwatchVerifier.verify(peer_id, epoch) → OverwatchResult`:**
1. Fetches the work record from `_WORK_TOPIC` via `db.nmap_get`.
2. Unpacks the `OutputEnvelope` to read the plaintext `{n, parity, tee_quote_hash}`.
3. Fetches the TEE quote from `TEE_QUOTE_TOPIC`; if missing → `OverwatchResult(ok=False, reason="no_tee_quote")`.
4. Recomputes expected hash: `sha256(quote_bytes).hexdigest()`.
5. Compares to the `tee_quote_hash` embedded in the work record; mismatch → `tee_quote_hash_mismatch`.
6. Re-derives expected parity: `_check_parity(n)`.
7. Compares to claimed parity; mismatch → `parity_mismatch`.
8. On all checks pass → `OverwatchResult(ok=True, reason="pass")`.

**`OverwatchResult` dataclass:** `ok: bool`, `reason: str`, `details: dict`.

## Tests Delivered

`TestOverwatch` (5 tests in `tests/test_mock_node.py`):
- `test_overwatch_passes_valid_work` — happy path, `ok=True, reason="pass"`.
- `test_overwatch_fails_no_record` — no DHT entry, `ok=False, reason="no_work_record"`.
- `test_overwatch_detects_tampered_parity` — parity flipped inside OutputEnvelope, `reason="parity_mismatch"`, `details.claimed != details.expected`.
- `test_overwatch_detects_tampered_tee_hash` — `tee_quote_hash` replaced with `"deadbeef"*8`, `reason="tee_quote_hash_mismatch"`.
- `test_overwatch_fails_no_tee_quote` — TEE quote removed from DHT, `ok=False`.

## Decision Reference

D012 — `MockOverwatchVerifier` reads `OutputEnvelope.output` without signature verification. This is correct: overwatch's trust model is re-deriving the expected result from public inputs, not validating crypto that requires a private session key.

## Verification

`pytest tests/test_mock_node.py::TestOverwatch` → **5 passed** ✅
`pytest tests/test_mock_node.py::TestEndToEnd` → **2 passed** ✅ (overwatch leg of end-to-end pipeline)
