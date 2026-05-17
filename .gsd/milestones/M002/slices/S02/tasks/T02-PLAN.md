---
estimated_steps: 5
estimated_files: 3
---

# T02: Implement envelope.py and add RATLS_CERT_TOPIC to quote.py

**Slice:** S02 — Input Encryption + Output Signing
**Milestone:** M002

## Description

Implement the two wire-envelope types (`WorkEnvelope`, `OutputEnvelope`) and the `TeeDecryptionError` domain exception in a new `subnet/tee/ratls/envelope.py` module. Add `RATLS_CERT_TOPIC` to `subnet/tee/quote.py`. Export all new public symbols from `subnet/tee/ratls/__init__.py`.

This task closes all non-integration tests in `test_envelope.py`: `TestWorkEnvelope`, `TestOutputEnvelope`, and `TestRatlsCertTopic`. The `TestMockProtocolSignedOutput` tests remain failing until T03 wires `MockNodeProtocol`.

### Design constraints

- **No new dependencies**: all crypto through `RaTlsSession.encrypt/decrypt/sign/verify_signature`. Serialization via stdlib `json` + `base64`.
- **`TeeDecryptionError`** wraps `cryptography.exceptions.InvalidTag` — protocol code must not import from `cryptography.exceptions` directly.
- **`WorkEnvelope.from_bytes` and `OutputEnvelope.from_bytes`** use `d.get(key, default)` for optional fields (forwards-compatible, matches `TeeQuote.from_bytes` pattern).
- **Replay protection** is in `OutputEnvelope.verify`: the signed payload is `request_id.encode() + b":" + output`. Changing either component invalidates the HMAC.
- **`WorkEnvelope.create`** generates `request_id = os.urandom(16).hex()` — 32-char hex string, unique per call, deterministically separable from the work item in the JSON payload.

## Steps

1. Create `subnet/tee/ratls/envelope.py`:
   - `TeeDecryptionError(Exception)` — docstring: "Raised when AES-GCM authentication tag is invalid — ciphertext tampered or session key mismatch."
   - `@dataclass WorkEnvelope(request_id: str, ciphertext: bytes)`:
     - `create(cls, work_item: bytes, session: RaTlsSession) -> WorkEnvelope`: generate `request_id = os.urandom(16).hex()`; build JSON payload `{"request_id": request_id, "work_item": base64.b64encode(work_item).decode()}`; return `cls(request_id=request_id, ciphertext=session.encrypt(payload.encode()))`
     - `decrypt(self, session: RaTlsSession) -> tuple[str, bytes]`: catch `cryptography.exceptions.InvalidTag` → raise `TeeDecryptionError`; parse JSON from `session.decrypt(self.ciphertext)`; return `(d["request_id"], base64.b64decode(d["work_item"]))`
     - `to_bytes(self) -> bytes`: JSON with `ciphertext` as base64
     - `from_bytes(cls, data: bytes) -> WorkEnvelope`: `d.get()` for all fields
   - `@dataclass OutputEnvelope(request_id: str, output: bytes, signature: bytes)`:
     - `create(cls, request_id: str, output: bytes, session: RaTlsSession) -> OutputEnvelope`: signed payload = `request_id.encode() + b":" + output`; `sig = session.sign(payload)`; return `cls(request_id=request_id, output=output, signature=sig)`
     - `verify(self, session: RaTlsSession) -> bool`: payload = `self.request_id.encode() + b":" + self.output`; return `session.verify_signature(payload, self.signature)`
     - `to_bytes(self) -> bytes`: JSON with `output` and `signature` as base64
     - `from_bytes(cls, data: bytes) -> OutputEnvelope`: `d.get()` for optional fields (default `""` → `base64.b64decode("")` = `b""`)
   - Module docstring explaining the full protocol (validator → miner WorkEnvelope, miner → validator OutputEnvelope with request_id binding)

2. Add to `subnet/tee/quote.py` after `TEE_QUOTE_TOPIC`:
   ```python
   RATLS_CERT_TOPIC = "ratls_cert"
   ```
   No other changes to `quote.py` — `dht_key()` is already reusable as-is.

3. Update `subnet/tee/ratls/__init__.py` to export:
   - `WorkEnvelope`, `OutputEnvelope`, `TeeDecryptionError` from `subnet.tee.ratls.envelope`
   - Add to `__all__`: `"WorkEnvelope"`, `"OutputEnvelope"`, `"TeeDecryptionError"`

4. Verify all non-integration envelope tests pass and no regressions in existing suite.

5. If any test reveals a design issue (e.g., bytes vs str handling in `from_bytes` for empty signature), fix it in `envelope.py` rather than the test.

## Must-Haves

- [ ] `TeeDecryptionError` is a plain `Exception` subclass (not `ValueError`, not `cryptography.exceptions.InvalidTag`)
- [ ] `WorkEnvelope.decrypt` raises `TeeDecryptionError` (not `InvalidTag`) on tampered ciphertext
- [ ] `OutputEnvelope.verify` returns `False` when `request_id` differs from the one used at signing — replay protection is structural (not a separate check)
- [ ] `from_bytes` on both classes uses `d.get(key, default)` for optional fields
- [ ] `RATLS_CERT_TOPIC = "ratls_cert"` is a top-level constant in `subnet/tee/quote.py`
- [ ] All three new symbols exported from `subnet/tee/ratls/__init__.py` and in `__all__`
- [ ] Zero regressions in `tests/tee/test_ratls.py` (32/32 still pass)

## Verification

```bash
# Envelope-only tests (non-integration)
python3 -m pytest tests/tee/test_envelope.py::TestWorkEnvelope \
                  tests/tee/test_envelope.py::TestOutputEnvelope \
                  tests/tee/test_envelope.py::TestRatlsCertTopic -v

# No regressions
python3 -m pytest tests/tee/test_ratls.py -v

# Integration tests still fail (expected — MockNodeProtocol not yet wired)
python3 -m pytest tests/tee/test_envelope.py::TestMockProtocolSignedOutput -v
# Expected: ImportError or AttributeError on new mock.py fields
```

## Observability Impact

- Signals added/changed:
  - `TeeDecryptionError` is a new stable error type importable from `subnet.tee.ratls` — protocol code catches it without importing `cryptography.exceptions`
  - `RATLS_CERT_TOPIC` is a stable DHT key constant — future agents can grep for it to find all DHT publish/fetch sites
- How a future agent inspects this: `python3 -c "from subnet.tee.ratls import WorkEnvelope, OutputEnvelope, TeeDecryptionError; print('ok')"` — clean import proves exports are wired
- Failure state exposed: `TeeDecryptionError` message is `"authentication failed: ciphertext tampered or wrong key"` — structured string for log filtering

## Inputs

- `subnet/tee/ratls/session.py` — `RaTlsSession.encrypt(bytes) -> bytes`, `decrypt(bytes) -> bytes`, `sign(bytes) -> bytes`, `verify_signature(bytes, bytes) -> bool`; the session is the only crypto primitive used
- `subnet/tee/quote.py` — `TEE_QUOTE_TOPIC`, `dht_key()` — follow exactly for `RATLS_CERT_TOPIC` placement
- `subnet/tee/ratls/__init__.py` — existing `__all__` list; append to it
- `tests/tee/test_envelope.py` (from T01) — the spec this task must satisfy

## Expected Output

- `subnet/tee/ratls/envelope.py` — new module (~90 lines); `WorkEnvelope`, `OutputEnvelope`, `TeeDecryptionError`
- `subnet/tee/quote.py` — `RATLS_CERT_TOPIC = "ratls_cert"` added
- `subnet/tee/ratls/__init__.py` — three new exports added
- `TestWorkEnvelope`, `TestOutputEnvelope`, `TestRatlsCertTopic` — all passing
- `tests/tee/test_ratls.py` — 32/32 still passing
