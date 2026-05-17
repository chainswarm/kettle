# S02: Input Encryption + Output Signing — UAT

**Milestone:** M002
**Written:** 2026-03-16

## UAT Type

- UAT mode: artifact-driven
- Why this mode is sufficient: All S02 behavior is exercised in-process via pytest — no live sockets, no real TLS, no hardware TEE. The `MockNodeProtocol` integration tests (`TestMockProtocolSignedOutput`) exercise the full publish → fetch → verify → score path in a single pytest process using an in-memory RocksDB. The envelope contract tests (`TestWorkEnvelope`, `TestOutputEnvelope`) prove the cryptographic properties directly. There is no human-visible UI or live daemon to drive.

## Preconditions

- Python 3.12+ with dependencies installed (`pip install -e .` or equivalent)
- `cryptography` package available (used by RaTlsSession for AES-GCM and HMAC)
- No environment variables required (all tests use `MOCK_TEE=true` path implicitly via MockBackend)

## Smoke Test

```bash
python3 -m pytest tests/tee/test_envelope.py -v
# Expected: 16/16 PASSED in < 1s
```

If this passes, S02 is functional.

## Test Cases

### 1. WorkEnvelope round-trip

```bash
python3 -m pytest tests/tee/test_envelope.py::TestWorkEnvelope -v
```

1. `test_create_decrypt_roundtrip` — creates a `WorkEnvelope` from a session key, decrypts it with the same session, asserts round-trip fidelity
2. `test_request_id_is_unique` — creates two envelopes, asserts `request_id` values differ (random generation)
3. `test_tampered_ciphertext_raises_tee_decryption_error` — mutates one byte of the ciphertext, asserts `TeeDecryptionError` is raised
4. `test_to_bytes_from_bytes_roundtrip` — serializes to bytes and deserializes, asserts all fields preserved
5. `test_from_bytes_extra_fields_ignored` — adds unknown JSON fields, asserts deserialization succeeds (forwards-compat)

**Expected:** 5/5 PASSED

### 2. OutputEnvelope replay protection

```bash
python3 -m pytest tests/tee/test_envelope.py::TestOutputEnvelope -v
```

1. `test_create_verify_valid` — creates `OutputEnvelope`, verifies with same session → `True`
2. `test_tampered_output_fails_verify` — mutates `.output` bytes, verifies → `False`
3. `test_tampered_signature_fails_verify` — mutates `.signature` bytes, verifies → `False`
4. `test_replay_protection` — takes a valid envelope's signature, constructs new envelope with different `request_id` and same signature, verifies → `False`
5. `test_to_bytes_from_bytes_roundtrip` — serializes and deserializes, asserts all fields preserved

**Expected:** 5/5 PASSED

### 3. RATLS_CERT_TOPIC constant

```bash
python3 -m pytest tests/tee/test_envelope.py::TestRatlsCertTopic -v
```

1. `test_constant_value` — imports `RATLS_CERT_TOPIC` from `subnet.tee.quote`, asserts value is `"ratls_cert"`
2. `test_dht_key_format` — calls `dht_key(epoch, peer_id)`, asserts format is `"{epoch}:{peer_id}"`

**Expected:** 2/2 PASSED

### 4. MockNodeProtocol signed output integration

```bash
python3 -m pytest tests/tee/test_envelope.py::TestMockProtocolSignedOutput -v
```

1. `test_miner_publishes_cert_and_signed_output` — runs miner loop, checks `RATLS_CERT_TOPIC` DHT key is set; checks `_WORK_TOPIC` DHT value parses as valid `OutputEnvelope`
2. `test_validator_verifies_signed_output` — runs miner then validator, asserts `result.success=True` and `result.metrics["tee_score"] > 0`
3. `test_no_cert_score_zero` — validator runs without cert in DHT, asserts `result.success=False` and `result.error="no_ratls_cert"`
4. `test_tampered_output_signature_score_zero` — miner runs, work record output is mutated in-place (signature unchanged), validator asserts `result.success=False` and `result.error="output_signature_invalid"`

**Expected:** 4/4 PASSED

## Edge Cases

### Tampered ciphertext raises TeeDecryptionError (not a silent wrong result)

```bash
python3 -m pytest tests/tee/test_envelope.py::TestWorkEnvelope::test_tampered_ciphertext_raises_tee_decryption_error -v
```

**Expected:** PASSED — `TeeDecryptionError` raised with message `"authentication failed: ciphertext tampered or wrong key"`

### Replay: valid signature on different request_id fails

```bash
python3 -m pytest tests/tee/test_envelope.py::TestOutputEnvelope::test_replay_protection -v
```

**Expected:** PASSED — `verify()` returns `False` (not an exception)

### Zero regressions in RA-TLS suite

```bash
python3 -m pytest tests/tee/test_ratls.py -q
```

**Expected:** 32/32 PASSED — S02 changes do not affect S01 behavior

### Full suite green

```bash
python3 -m pytest tests/ --ignore=tests/hypertensor -q
```

**Expected:** 173/173 PASSED (`tests/hypertensor/test_rpc.py` excluded — requires live node on port 9944; pre-existing collection error unrelated to S02)

## Failure Signals

- `ModuleNotFoundError: No module named 'subnet.tee.ratls.envelope'` — `envelope.py` not created or not importable
- `ImportError: cannot import name 'RATLS_CERT_TOPIC'` — constant not added to `quote.py`
- `TeeDecryptionError` not raised on tamper — `InvalidTag` not being caught in `decrypt()`
- `OutputEnvelope.verify()` returns `True` on tampered output — signed payload construction wrong (request_id not included)
- `test_no_cert_score_zero` fails — validator not checking `RATLS_CERT_TOPIC` before accepting work
- `test_tampered_output_signature_score_zero` fails — validator not calling `output_env.verify(session)` before parsing output
- `tests/tee/test_ratls.py` regressions — S01 session/cert/client code broken by imports or `__init__.py` changes

## Requirements Proved By This UAT

- **R014 — Signed outputs**: `TestMockProtocolSignedOutput::test_validator_verifies_signed_output` proves the full signing + verification flow end-to-end; `test_tampered_output_signature_score_zero` proves tampered outputs produce `score=0.0`; `TestOutputEnvelope::test_replay_protection` proves replay protection is structural (different `request_id` → `verify()` returns `False`)
- **R013 — Enclave-to-enclave encrypted channels** (partial): `TestWorkEnvelope` proves AES-GCM encryption and `TeeDecryptionError` on tamper; the validator→miner encrypted dispatch path (WorkEnvelope) is proven at the unit level but not yet wired into MockNodeProtocol flow

## Not Proven By This UAT

- **R013 full flow** — Validator→miner WorkEnvelope dispatch is not wired into MockNodeProtocol. WorkEnvelope is unit-tested but the bidirectional encrypt→transmit→decrypt call pattern requires a live transport (M004+).
- **Live TLS socket** — S02 tests are in-process only. No actual TLS handshake occurs; cert exchange uses DHT bytes. Real RA-TLS TLS handshake integration is M004 scope.
- **Real TEE hardware** — All tests use MockBackend (`MOCK_TEE=true`). AES-GCM and HMAC are standard crypto but the session key derives from a mock cert (not a hardware-attested cert).
- **Cert expiry / rotation** — No test covers what happens when a cert from a previous epoch is left in DHT and a validator fetches it for the wrong epoch. The epoch-binding in `dht_key` prevents accidental use but no explicit expiry test exists.
- **High-frequency `verify_cert` performance** — `RaTlsClient` allocates a temp RocksDB per call (D007). Not stress-tested in S02; flag for M004 load testing.

## Notes for Tester

- `tests/hypertensor/test_rpc.py` will fail with a `CollectionError` if not excluded — it requires a live Hypertensor node on port 9944. Always run with `--ignore=tests/hypertensor` for local testing. This is pre-existing and unrelated to S02.
- The mock `request_id` is deterministic: `f"mock:{epoch}:{peer_id[:8]}"`. In a real validator flow, `request_id` would be a random nonce from `WorkEnvelope.create()`. The mock implementation intentionally simplifies this.
- `MockOverwatchVerifier` reads `OutputEnvelope.output` without checking the signature — this is correct by design. Overwatch is a public audit path with no session key. If you add a new overwatch test that checks signatures, it will fail by design.
