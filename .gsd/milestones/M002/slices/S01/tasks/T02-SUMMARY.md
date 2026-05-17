---
id: T02
parent: S01
milestone: M002
provides:
  - RaTlsServer — RA-TLS miner-side server wrapping generate_ratls_cert; provides cert_bundle, make_ssl_context(), make_session()
  - RaTlsClient — RA-TLS validator-side client; verify_cert() extracts TeeQuote and runs DcapVerifier inline
  - RaTlsVerificationResult — dataclass (ok, score, session, quote, rejection_reason)
  - RaTlsAttestationError — ConnectionError subclass for raise-on-reject callers
key_files:
  - subnet/tee/ratls/server.py
  - subnet/tee/ratls/client.py
  - subnet/tee/ratls/__init__.py
  - tests/tee/test_ratls.py
key_decisions:
  - RaTlsClient._verify_quote_inline uses a throw-away temp RocksDB to inject the quote into DcapVerifier (bypasses DHT fetch)
  - ssl.SSLContext loaded from temp PEM files then cleaned up immediately; avoids storing key material on disk long-term
  - All rejection paths return structured rejection_reason strings (debug_mode, identity_binding_failed, nonce_mismatch, chain_verification_failed, missing_extension, parse_error) for machine-readable diagnostics
patterns_established:
  - verify_cert() is the single entry point — one call does extraction + pipeline + session derivation
  - Session key agreement: HKDF(sha256(cert_pubkey_der), peer_id:epoch) derived independently on both sides — no separate key exchange step
  - RaTlsVerificationResult.ok=False does NOT raise; RaTlsAttestationError is a separate opt-in for callers that prefer exceptions
observability_surfaces:
  - RaTlsVerificationResult.rejection_reason carries structured reason string for all rejection paths
  - Logger INFO on pass (peer_id[:16], epoch, score, backend)
  - Logger WARNING on reject (peer_id[:16], epoch, reason)
  - RaTlsVerificationResult.quote preserved for caller diagnostics (backend, measurement, peer_id visible)
duration: 0m (pre-built; discovered already implemented in slice commit 83ea546)
verification_result: passed
completed_at: 2026-03-16
blocker_discovered: false
---

# T02: RaTlsServer + RaTlsClient — in-process TLS with quote verification

**`RaTlsServer`, `RaTlsClient`, `RaTlsVerificationResult`, and `RaTlsAttestationError` implemented; 32/32 tests passing including all rejection scenarios and miner+validator key agreement.**

## What Happened

Like T01, the T02 implementation was found pre-built in the slice commit (`83ea546`). The plan file had not been written at dispatch time.

`server.py` implements:

- **`RaTlsServer`** — takes `peer_id`, `epoch`, `backend`; lazily generates the RA-TLS cert bundle via `generate_ratls_cert`; `make_ssl_context()` writes PEM to a temp dir, loads into `ssl.SSLContext(PROTOCOL_TLS_SERVER, TLSv1_3)`, and immediately deletes the temp files; `make_session()` derives an `RaTlsSession` from the cert public key

`client.py` implements:

- **`RaTlsVerificationResult`** — `ok`, `score`, `session`, `quote`, `rejection_reason`
- **`RaTlsClient`** — `verify_cert(cert_pem, peer_id, epoch)` extracts TeeQuote via `extract_quote_from_cert`, then calls `_verify_quote_inline` which spins up a throw-away temp `RocksDB`, stores the quote under `dht_key(epoch, peer_id)`, runs `DcapVerifier.verify()`, and tears down the temp DB; on pass, derives `RaTlsSession` from cert public key; all rejection paths return structured `rejection_reason`
- **`RaTlsAttestationError`** — `ConnectionError` subclass for callers that prefer raise-on-reject semantics

`__init__.py` re-exports all public symbols from `cert`, `server`, `client`, and `session`.

## Verification

```
python3 -m pytest tests/tee/test_ratls.py -v
```

**32/32 passed** (0.57s). T02-specific test groups:

| Test Class | Tests | Result |
|---|---|---|
| `TestRaTlsServer` | 4 | PASS |
| `TestRaTlsClientValid` | 4 | PASS |
| `TestRaTlsClientRejectDebugMode` | 1 | PASS |
| `TestRaTlsClientRejectWrongPeer` | 1 | PASS |
| `TestRaTlsClientRejectWrongEpoch` | 1 | PASS |
| `TestRaTlsClientRejectTamperedSig` | 2 | PASS |
| `TestMinerValidatorSessionKeyAgreement` | 3 | PASS |

Key scenarios verified:
- `test_valid_cert_ok` / `test_valid_cert_score_half` — mock backend returns score=0.5
- `test_debug_mode_cert_rejected` — `rejection_reason == "debug_mode"`
- `test_wrong_peer_id_rejected` — `rejection_reason == "identity_binding_failed"`
- `test_old_epoch_cert_rejected` — `"nonce_mismatch" in rejection_reason`
- `test_tampered_sig_rejected` — `"chain_verification_failed" in rejection_reason`
- `test_same_key_both_sides` — miner session key hex == validator session key hex
- `test_end_to_end_encrypt_decrypt` — miner encrypts → validator decrypts + sig verifies

## Diagnostics

- `RaTlsVerificationResult.rejection_reason` carries structured reason for all rejection paths — machine-readable for upstream routing logic
- `RaTlsVerificationResult.quote` preserved on both pass and fail — caller can inspect backend/measurement/peer_id without re-parsing the cert
- `[RaTlsClient]` logger lines tag every pass (INFO) and rejection (WARNING) with `peer=<prefix>... epoch=<n>` — grep-able in structured log aggregators

## Deviations

none — implementation matched the T02 spec exactly

## Known Issues

- `RaTlsClient._verify_quote_inline` creates a temp RocksDB on every `verify_cert` call. For production high-frequency calls, a long-lived in-process verifier cache would be more efficient. Not a correctness issue.

## Files Created/Modified

- `subnet/tee/ratls/server.py` — `RaTlsServer`: cert generation, ssl context, session factory
- `subnet/tee/ratls/client.py` — `RaTlsClient`, `RaTlsVerificationResult`, `RaTlsAttestationError`
- `subnet/tee/ratls/__init__.py` — re-exports all public symbols from ratls subpackage
- `tests/tee/test_ratls.py` — full RA-TLS test suite (32 tests, all pass)
- `.gsd/milestones/M002/slices/S01/tasks/T02-PLAN.md` — retroactive plan artifact (missing at dispatch)
- `.gsd/milestones/M002/slices/S01/tasks/T02-SUMMARY.md` — this file
