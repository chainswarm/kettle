---
estimated_steps: 4
estimated_files: 1
---

# T01: Write failing tests for envelope protocol and MockNodeProtocol integration

**Slice:** S02 — Input Encryption + Output Signing
**Milestone:** M002

## Description

Write the complete test suite for S02 before any implementation exists. Tests are the spec — they define exactly what `WorkEnvelope`, `OutputEnvelope`, `TeeDecryptionError`, `RATLS_CERT_TOPIC`, and the wired `MockNodeProtocol` must do. All tests will fail initially (import errors from missing modules). T02 and T03 make them pass.

The test file covers four areas:
1. `WorkEnvelope` — create/decrypt round-trip, tamper detection (`TeeDecryptionError`), serialization, forwards-compat deserialization
2. `OutputEnvelope` — create/verify, tampered output → False, tampered sig → False, replay protection (different `request_id` → False), serialization
3. `RATLS_CERT_TOPIC` — constant value and DHT key format
4. `MockNodeProtocol` integration — full round-trip, no cert → score=0.0, tampered output envelope → score=0.0

## Steps

1. Create `tests/tee/test_envelope.py` with standard imports and fixtures mirroring `tests/tee/test_ratls.py` — use `TeeConfig.__new__(TeeConfig)` pattern, `MockBackend`, `MOCK_KEY`, shared `bundle` fixture (`RaTlsServer.cert_bundle`), and `session` fixture (`RaTlsServer.make_session()`).

2. Write `TestWorkEnvelope` with tests:
   - `test_create_decrypt_roundtrip`: `WorkEnvelope.create(b"work payload", session)` → `decrypt(session)` returns `("...", b"work payload")`; request_id is non-empty
   - `test_request_id_is_unique`: two `.create()` calls produce different `request_id` values
   - `test_tampered_ciphertext_raises_tee_decryption_error`: flip one byte in `envelope.ciphertext` → `decrypt()` raises `TeeDecryptionError`
   - `test_to_bytes_from_bytes_roundtrip`: `WorkEnvelope.from_bytes(envelope.to_bytes())` preserves `request_id` and `ciphertext`
   - `test_from_bytes_extra_fields_ignored`: inject extra JSON key → `from_bytes` does not raise

3. Write `TestOutputEnvelope` with tests:
   - `test_create_verify_valid`: `OutputEnvelope.create(request_id, output, session).verify(session)` returns `True`
   - `test_tampered_output_fails_verify`: flip one byte in `output_env.output` → `verify()` returns `False`
   - `test_tampered_signature_fails_verify`: flip one byte in `output_env.signature` → `verify()` returns `False`
   - `test_replay_protection`: create envelope with `request_id="A"`, construct identical envelope with `request_id="B"` but same output+sig → `verify()` returns `False` (signature is bound to original request_id)
   - `test_to_bytes_from_bytes_roundtrip`: `OutputEnvelope.from_bytes(envelope.to_bytes())` preserves all three fields

4. Write `TestRatlsCertTopic` and `TestMockProtocolSignedOutput`:
   - `TestRatlsCertTopic`: `test_constant_value` (`RATLS_CERT_TOPIC == "ratls_cert"`); `test_dht_key_format` (`dht_key(14780500, peer_id) == f"14780500:{peer_id}"`)
   - `TestMockProtocolSignedOutput` using an in-memory DB (`MockNodeProtocol` fixtures from existing node tests or a minimal inline setup): `test_miner_publishes_cert_and_signed_output` (after `miner_loop`, `db.nmap_get(RATLS_CERT_TOPIC, ...)` is not None, `db.nmap_get(_WORK_TOPIC, ...)` parses as valid `OutputEnvelope`); `test_validator_verifies_signed_output` (after miner_loop + validator_call, `result.success == True` and `result.metrics["tee_score"] > 0`); `test_no_cert_score_zero` (delete cert from DHT before validator_call → `result.success == False` and `result.error == "no_ratls_cert"`); `test_tampered_output_signature_score_zero` (overwrite OutputEnvelope bytes with a corrupted signature → `result.error == "output_signature_invalid"`)

## Must-Haves

- [ ] Test file is collected by pytest without syntax errors
- [ ] All tests in `TestWorkEnvelope` and `TestOutputEnvelope` cover the named scenarios (tamper, replay, serialization)
- [ ] `TestRatlsCertTopic` asserts exact constant value `"ratls_cert"` and dht_key format
- [ ] `TestMockProtocolSignedOutput` covers the three key outcomes: pass, no-cert, bad-sig
- [ ] No test has a `pass` body — every test has at least one `assert` statement
- [ ] Fixtures follow `TeeConfig.__new__(TeeConfig)` pattern (no env-var side effects)

## Verification

- `python3 -m pytest tests/tee/test_envelope.py --collect-only` — all tests collected, no collection errors
- `python3 -m pytest tests/tee/test_envelope.py -v` — all tests fail with `ImportError`/`ModuleNotFoundError` (acceptable — module doesn't exist yet); zero tests fail with `SyntaxError` or assertion logic errors within the test itself

## Observability Impact

- Signals added/changed: None (test-only task)
- How a future agent inspects this: `python3 -m pytest tests/tee/test_envelope.py --collect-only` lists all test names; a future agent can run `pytest -v` to see which tests still fail
- Failure state exposed: Test names act as the acceptance contract; a failing test name is self-documenting (e.g., `FAILED test_replay_protection`)

## Inputs

- `tests/tee/test_ratls.py` — fixture patterns to follow: `TeeConfig.__new__`, `MockBackend`, `MOCK_KEY`, `bundle`, `mock_config`
- `subnet/tee/ratls/session.py` — `RaTlsSession` API (encrypt/decrypt/sign/verify_signature)
- `subnet/tee/ratls/server.py` — `RaTlsServer.cert_bundle`, `RaTlsServer.make_session()`
- `subnet/node/mock.py` — `MockNodeProtocol`, `_WORK_TOPIC`, `_dht_key` internals needed for DB inspection in integration tests

## Expected Output

- `tests/tee/test_envelope.py` — complete test suite (~40 tests), all failing due to missing imports; ready for T02/T03 to make pass
