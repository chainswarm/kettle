---
id: T02
parent: S02
milestone: M002
provides:
  - subnet/tee/ratls/envelope.py — WorkEnvelope, OutputEnvelope, TeeDecryptionError
  - subnet/tee/quote.py — RATLS_CERT_TOPIC constant
  - subnet/tee/ratls/__init__.py — three new symbols exported
key_files:
  - subnet/tee/ratls/envelope.py
  - subnet/tee/quote.py
  - subnet/tee/ratls/__init__.py
key_decisions:
  - TeeDecryptionError wraps InvalidTag at the envelope boundary; protocol callers never import from cryptography.exceptions directly
  - OutputEnvelope.verify signed payload is request_id.encode() + b":" + output — replay protection is structural, not a separate guard
  - from_bytes uses d.get(key, default) on all fields for forwards-compat deserialization
patterns_established:
  - Bytes fields serialized to JSON via base64.b64encode/b64decode; empty string default decodes to b"" cleanly
  - WorkEnvelope.create generates request_id = os.urandom(16).hex() (32 hex chars) per call
observability_surfaces:
  - "python3 -c \"from subnet.tee.ratls import WorkEnvelope, OutputEnvelope, TeeDecryptionError; print('ok')\"" — confirms exports wired
  - TeeDecryptionError message: "authentication failed: ciphertext tampered or wrong key" — stable string for log filtering
  - RATLS_CERT_TOPIC = "ratls_cert" — grep-stable DHT key constant
duration: ~10 minutes
verification_result: passed
completed_at: 2026-03-16
blocker_discovered: false
---

# T02: Implement envelope.py and add RATLS_CERT_TOPIC to quote.py

**Created `WorkEnvelope`, `OutputEnvelope`, `TeeDecryptionError` in `envelope.py` and added `RATLS_CERT_TOPIC` to `quote.py`; 12 non-integration envelope tests pass, 32 RA-TLS tests unaffected.**

## What Happened

- Wrote `subnet/tee/ratls/envelope.py` (~140 lines) with:
  - `TeeDecryptionError(Exception)` — catches `cryptography.exceptions.InvalidTag` at the AES-GCM boundary and re-raises with a stable message
  - `WorkEnvelope` dataclass: `create()` generates a fresh `request_id = os.urandom(16).hex()` per call, encrypts a JSON payload `{request_id, work_item}` via `session.encrypt()`; `decrypt()` wraps `InvalidTag` → `TeeDecryptionError`; `to_bytes()`/`from_bytes()` use base64 JSON with `d.get()` defaults
  - `OutputEnvelope` dataclass: `create()` signs `request_id.encode() + b":" + output` via `session.sign()`; `verify()` reconstructs the same payload and calls `session.verify_signature()`; same base64 JSON wire format
- Added `RATLS_CERT_TOPIC = "ratls_cert"` immediately after `TEE_QUOTE_TOPIC` in `subnet/tee/quote.py`
- Updated `subnet/tee/ratls/__init__.py`: prepended `from subnet.tee.ratls.envelope import ...` import and added three symbols to `__all__`

## Verification

```
# Non-integration envelope tests — 12/12 passed
python3 -m pytest tests/tee/test_envelope.py::TestWorkEnvelope \
                  tests/tee/test_envelope.py::TestOutputEnvelope \
                  tests/tee/test_envelope.py::TestRatlsCertTopic -v
# 12 passed in 0.05s

# Regression check — 32/32 still pass
python3 -m pytest tests/tee/test_ratls.py -v
# 32 passed in 0.57s

# Import smoke test
python3 -c "from subnet.tee.ratls import WorkEnvelope, OutputEnvelope, TeeDecryptionError; print('ok')"
# ok
```

Integration tests (`TestMockProtocolSignedOutput`) still fail as expected — T03 wires `MockNodeProtocol`.

## Diagnostics

- `python3 -c "from subnet.tee.ratls import WorkEnvelope, OutputEnvelope, TeeDecryptionError; print('ok')"` — clean import proves exports wired
- `TeeDecryptionError` message `"authentication failed: ciphertext tampered or wrong key"` — stable for log filtering
- `RATLS_CERT_TOPIC` — grep for it in DHT publish/fetch sites to find all cert storage points

## Deviations

None. Implementation follows the plan exactly.

## Known Issues

None.

## Files Created/Modified

- `subnet/tee/ratls/envelope.py` — new module; `WorkEnvelope`, `OutputEnvelope`, `TeeDecryptionError`
- `subnet/tee/quote.py` — added `RATLS_CERT_TOPIC = "ratls_cert"` after `TEE_QUOTE_TOPIC`
- `subnet/tee/ratls/__init__.py` — added three new exports and updated `__all__`
