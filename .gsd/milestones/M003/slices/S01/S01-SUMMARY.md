# S01: Mock node protocol + scoring

## What Was Built

`subnet/node/mock.py` — the complete in-memory mock subnet protocol, implementing:

- **`MockNodeProtocol`** (extends `BaseNodeProtocol`): miner and validator in one class, mode-switched at construction.
  - `miner_loop(epoch)`: generates a random integer `n`, computes parity (`n % 2`), publishes a mock TEE quote to `TEE_QUOTE_TOPIC`, wraps `{epoch, peer_id, n, parity, tee_quote_hash}` in an `OutputEnvelope` (HMAC-signed), and stores it to `_WORK_TOPIC` in the in-memory RocksDB DHT.
  - `validator_call(peer_id, epoch)`: fetches the TEE quote, verifies the mock HMAC chain, fetches the `OutputEnvelope` from `_WORK_TOPIC`, verifies the output signature, re-checks `n % 2`, returns `NodeValidatorResult` with `{tee_score, n, parity, correct}`.
- **`MockNodeScoring`** (extends `BaseNodeScoring`): `score_peer(result, epoch)` → `tee_score × parity_score` where parity_score is 1.0 if correct, 0.0 if not.
- **`_check_parity(n)`** — pure helper, the shared truth function used by miner, validator, and overwatch.
- **`_dht_key(epoch, peer_id)`** — canonical DHT key format `"{epoch}:{peer_id}"`.
- **`_WORK_TOPIC`** — DHT topic constant `"mock_work"`.
- **`TAMPER_RATE`** — module-level float (default `1/1000`) consumed by S03.

## Tests Delivered

`tests/test_mock_node.py` — 24 tests covering:
- `test_check_parity_even`, `test_check_parity_odd` — pure unit tests for `_check_parity`.
- `TestMiner` (4 tests) — miner succeeds, publishes work to DHT, parity is correct, TEE quote is published.
- `TestValidator` (5 tests) — valid miner passes, rejects missing quote, rejects missing work, rejects tampered record (invalid signature), rejects wrong epoch.
- `TestScoring` (4 tests) — mock TEE correct parity → 0.5, real TEE correct parity → 1.0, wrong parity → 0.0, failed TEE → 0.0.

## Boundary Map Outputs (for S02, S03)

- **`_WORK_TOPIC` DHT record schema**: `{epoch, peer_id, n, parity, tee_quote_hash}` — packed in an `OutputEnvelope`
- **`NodeValidatorResult.metrics` shape**: `{tee_score, n, parity, correct}`
- **`MockNodeProtocol.miner_loop()`** — the entry point S03's fault injection wraps via `TAMPER_RATE`
- **`_check_parity()`** — consumed by S02's `MockOverwatchVerifier` and S03's tamper logic

## Verification

`pytest tests/test_mock_node.py` → **24 passed in 1.38 s** ✅
