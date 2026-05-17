# S02: Input Encryption + Output Signing

**Goal:** Validator encrypts work items to the enclave session key; miner decrypts, processes, and signs output; validator verifies signature before accepting result — all proven in-process with no live TLS sockets.
**Demo:** `python3 -m pytest tests/tee/test_envelope.py -v` — all envelope + mock protocol integration tests pass. WorkEnvelope round-trip proven; OutputEnvelope replay protection proven; MockNodeProtocol publishes signed output and degrades to score=0.0 when cert or signature is missing.

## Must-Haves

- `WorkEnvelope` in `subnet/tee/ratls/envelope.py` — AES-256-GCM encrypted work item via `RaTlsSession.encrypt`; embeds a validator-generated `request_id`; `TeeDecryptionError` raised on tamper
- `OutputEnvelope` in `subnet/tee/ratls/envelope.py` — HMAC-SHA256 signed miner output bound to `request_id` via `session.sign(request_id + ":" + output)`; replay detection: different `request_id` → `verify()` returns False
- `RATLS_CERT_TOPIC = "ratls_cert"` added to `subnet/tee/quote.py` following existing DHT key convention
- `MockNodeProtocol.miner_loop` publishes `cert_pem` to `RATLS_CERT_TOPIC` DHT key and stores work record as a signed `OutputEnvelope`
- `MockNodeProtocol.validator_call` fetches cert from DHT, verifies via `RaTlsClient`, derives session, verifies `OutputEnvelope` signature; no cert → `score=0.0`; invalid signature → `score=0.0`
- No new dependencies: all crypto from `RaTlsSession`; serialization via stdlib `json` + `base64`
- R014 (Signed outputs) validated; all 32 existing RA-TLS tests still pass

## Proof Level

- This slice proves: contract + integration (in-process)
- Real runtime required: no — in-process DHT (`db.nmap_set/get`) throughout
- Human/UAT required: no

## Verification

```bash
# Run slice verification target (all envelope + integration tests)
python3 -m pytest tests/tee/test_envelope.py -v

# Confirm zero regressions in existing RA-TLS suite
python3 -m pytest tests/tee/test_ratls.py -v

# Full suite sanity
python3 -m pytest tests/ -q
```

Expected: `tests/tee/test_envelope.py` — all tests pass; `tests/tee/test_ratls.py` — 32/32 still pass.

## Observability / Diagnostics

- Runtime signals:
  - `[MockMiner] published ratls_cert epoch=<n> peer=<prefix>...` — INFO log when cert published to DHT
  - `[MockMiner] signed output request_id=<id> epoch=<n>` — INFO log on OutputEnvelope creation
  - `[MockValidator] ratls_cert ok epoch=<n> peer=<prefix>... score=<s>` — INFO log on cert verify pass
  - `[MockValidator] no_ratls_cert epoch=<n> peer=<prefix>...` — WARNING log on missing cert
  - `[MockValidator] output_signature_invalid epoch=<n> peer=<prefix>...` — WARNING on bad sig
  - `[RaTlsClient]` existing PASS/REJECT structured logs (from S01)
- Inspection surfaces:
  - `db.nmap_get(RATLS_CERT_TOPIC, dht_key(epoch, peer_id))` — cert present in DHT?
  - `db.nmap_get(_WORK_TOPIC, dht_key(epoch, peer_id))` → `OutputEnvelope.from_bytes()` — inspect signed record
  - `TeeDecryptionError` message: `"authentication failed: ciphertext tampered or wrong key"`
  - `NodeValidatorResult.error` field: `no_ratls_cert`, `ratls_cert_rejected:<reason>`, `output_signature_invalid`
- Failure visibility:
  - `NodeValidatorResult.error` is the primary failure signal; structured string with prefix
  - `RaTlsVerificationResult.rejection_reason` preserved from S01 for cert failures
  - `OutputEnvelope.verify()` returns `False` (no exception); caller controls scoring response
- Redaction constraints: `session_key_hex` must not be logged; `cert_pem` may appear in DHT bytes (acceptable — public key is not secret)

## Integration Closure

- Upstream surfaces consumed:
  - `subnet/tee/ratls/session.py` — `RaTlsSession.encrypt`, `decrypt`, `sign`, `verify_signature`
  - `subnet/tee/ratls/server.py` — `RaTlsServer.cert_bundle.cert_pem`, `RaTlsServer.make_session()`
  - `subnet/tee/ratls/client.py` — `RaTlsClient.verify_cert(cert_pem, peer_id, epoch)` → `result.session`
  - `subnet/tee/quote.py` — `TEE_QUOTE_TOPIC`, `dht_key()` pattern
  - `subnet/node/mock.py` — `MockNodeProtocol` (miner_loop + validator_call)
- New wiring introduced in this slice:
  - `envelope.py` → imported by `mock.py` for miner signing and validator verification
  - `RATLS_CERT_TOPIC` → DHT key used by miner (publish) and validator (fetch)
  - `RaTlsClient.verify_cert` wired into `validator_call` (first live call in MockNodeProtocol)
- What remains before the milestone is truly usable end-to-end:
  - S03: Sealed storage (R015) — independent of S02
  - S04: Gramine manifest + reproducible build (R016) — ties S01–S03 into a real enclave

## Tasks

- [x] **T01: Write failing tests for envelope protocol and MockNodeProtocol integration** `est:30m`
  - Why: Defines the acceptance contract for this slice before any implementation exists. Tests are the spec — they fail now, and T02/T03 make them pass.
  - Files: `tests/tee/test_envelope.py`
  - Do: Write `TestWorkEnvelope` (create/decrypt round-trip, `TeeDecryptionError` on tamper, to_bytes/from_bytes, extra-field forwards-compat); `TestOutputEnvelope` (create/verify, tampered output → False, tampered sig → False, replay — different `request_id` → False, to_bytes/from_bytes); `TestRatlsCertTopic` (RATLS_CERT_TOPIC constant value, dht_key format); `TestMockProtocolSignedOutput` (full integration: miner publishes cert + signed output, validator score > 0; no cert in DHT → score=0.0 / error `no_ratls_cert`; tampered output envelope → score=0.0 / error `output_signature_invalid`). Import fixtures from existing test_ratls.py pattern (`TeeConfig.__new__`, `MockBackend`, `MOCK_KEY`). Tests import from paths that don't yet exist — that's expected and correct.
  - Verify: `python3 -m pytest tests/tee/test_envelope.py -v` — all tests collected and failing with `ImportError` or `ModuleNotFoundError` (not runtime assertion failures from logic bugs)
  - Done when: Test file exists, all tests are collected by pytest, and failures are import-level (not logic errors in the test itself)

- [x] **T02: Implement envelope.py and add RATLS_CERT_TOPIC to quote.py** `est:45m`
  - Why: Closes the envelope contract: `WorkEnvelope`, `OutputEnvelope`, `TeeDecryptionError`, and `RATLS_CERT_TOPIC` make all non-integration tests in `test_envelope.py` pass.
  - Files: `subnet/tee/ratls/envelope.py`, `subnet/tee/quote.py`, `subnet/tee/ratls/__init__.py`
  - Do: (1) In `subnet/tee/ratls/envelope.py`: implement `TeeDecryptionError(Exception)`; `WorkEnvelope(request_id: str, ciphertext: bytes)` with `create(work_item, session)` → random 16-byte hex `request_id`, JSON payload `{request_id, work_item: b64}` encrypted via `session.encrypt()`; `decrypt(session)` → catches `cryptography.exceptions.InvalidTag` and re-raises as `TeeDecryptionError`, returns `(request_id, work_item)`; `to_bytes()`/`from_bytes()` JSON+base64 with `d.get()` for optional fields; `OutputEnvelope(request_id: str, output: bytes, signature: bytes)` with `create(request_id, output, session)` → `session.sign(request_id.encode() + b":" + output)`; `verify(session)` → `session.verify_signature(request_id.encode() + b":" + output, signature)`; `to_bytes()`/`from_bytes()` same pattern. (2) In `subnet/tee/quote.py`: add `RATLS_CERT_TOPIC = "ratls_cert"` below `TEE_QUOTE_TOPIC`. (3) In `subnet/tee/ratls/__init__.py`: export `WorkEnvelope`, `OutputEnvelope`, `TeeDecryptionError`.
  - Verify: `python3 -m pytest tests/tee/test_envelope.py::TestWorkEnvelope tests/tee/test_envelope.py::TestOutputEnvelope tests/tee/test_envelope.py::TestRatlsCertTopic -v` — all pass. `python3 -m pytest tests/tee/test_ratls.py -v` — 32/32 still pass (no regressions).
  - Done when: All non-mock-protocol envelope tests pass; zero regressions in test_ratls.py

- [x] **T03: Wire MockNodeProtocol — miner publishes cert_pem, validator verifies signed output** `est:45m`
  - Why: Closes the integration loop: MockNodeProtocol demonstrates the full S02 protocol in-process. This is the subnet owner's reference implementation and the final evidence that R014 is validated.
  - Files: `subnet/node/mock.py`, `REQUIREMENTS.md`
  - Do: (1) In `miner_loop`: import `RaTlsServer`, `OutputEnvelope`, `RATLS_CERT_TOPIC` from the ratls package; after publishing TEE quote, create `RaTlsServer(peer_id, epoch, backend)`, call `server.cert_bundle.cert_pem`, publish cert_pem to `db.nmap_set(RATLS_CERT_TOPIC, _dht_key(epoch, peer_id), cert_pem)`; call `server.make_session()` for the session; after computing `record` dict, create `request_id = f"mock:{epoch}:{peer_id[:8]}"`, create `OutputEnvelope.create(request_id, json.dumps(record).encode(), session)`, store `output_env.to_bytes()` in `_WORK_TOPIC` DHT instead of raw JSON; log INFO on cert publish and signing. (2) In `validator_call`: after passing TEE quote check, fetch `cert_raw = db.nmap_get(RATLS_CERT_TOPIC, _dht_key(epoch, peer_id))`; if `None` → log WARNING, return `NodeValidatorResult(success=False, metrics={"tee_score": 0.0}, error="no_ratls_cert")`; call `RaTlsClient(config=self._tee_config).verify_cert(cert_raw, peer_id, epoch)`; if not `ra_result.ok` → return `NodeValidatorResult(success=False, metrics={"tee_score": 0.0}, error=f"ratls_cert_rejected:{ra_result.rejection_reason}")`; get `session = ra_result.session`; fetch raw work record; parse `OutputEnvelope.from_bytes(raw)`; call `output_env.verify(session)`; if False → log WARNING, return `NodeValidatorResult(success=False, metrics={"tee_score": tee.score}, error="output_signature_invalid")`; parse `json.loads(output_env.output.decode())` for `n`, `parity`; continue existing parity check. (3) Update `REQUIREMENTS.md`: R014 status → `validated (M002/S02)`.
  - Verify: `python3 -m pytest tests/tee/test_envelope.py -v` — all tests pass including `TestMockProtocolSignedOutput`. `python3 -m pytest tests/tee/ -v` — all RA-TLS + envelope tests pass. `python3 -m pytest tests/ -q` — full suite passes.
  - Done when: All `test_envelope.py` tests pass including mock protocol integration, full test suite green, R014 marked validated in REQUIREMENTS.md

## Files Likely Touched

- `subnet/tee/ratls/envelope.py` — new file
- `subnet/tee/quote.py` — add `RATLS_CERT_TOPIC`
- `subnet/tee/ratls/__init__.py` — export new symbols
- `subnet/node/mock.py` — miner_loop + validator_call + MockOverwatchVerifier wiring
- `tests/tee/test_envelope.py` — new file
- `tests/test_mock_node.py` — update for new OutputEnvelope work record format
- `REQUIREMENTS.md` — R014 validated
