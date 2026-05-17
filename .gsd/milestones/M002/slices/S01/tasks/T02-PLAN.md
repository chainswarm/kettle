# T02: RaTlsServer + RaTlsClient — in-process TLS with quote verification

## Goal

Implement `RaTlsServer` (miner side) and `RaTlsClient` (validator side) so that quote verification flows through the TLS cert — no separate attestation exchange needed.

## Must-Haves

- `RaTlsServer`: wraps `generate_ratls_cert`, exposes `cert_bundle`, `make_ssl_context()`, `make_session()`
- `RaTlsClient.verify_cert(cert_pem, peer_id, epoch)` → `RaTlsVerificationResult`
  - Extracts TeeQuote via `extract_quote_from_cert`
  - Runs `DcapVerifier` pipeline inline (bypass DHT fetch, inject quote directly)
  - Returns `ok=True` + `RaTlsSession` on pass; `ok=False` + `rejection_reason` on fail
- `RaTlsAttestationError` exception class for callers that prefer raise-on-reject
- `RaTlsVerificationResult` dataclass: `ok`, `score`, `session`, `quote`, `rejection_reason`
- All rejection paths return structured `rejection_reason` strings: `debug_mode`, `identity_binding_failed`, `nonce_mismatch:*`, `chain_verification_failed:*`, `missing_extension:*`, `parse_error:*`

## Implementation Notes

- `RaTlsClient._verify_quote_inline` uses a throw-away temp `RocksDB` to inject the quote into `DcapVerifier` without touching the real DHT
- `RaTlsServer.make_ssl_context()` writes PEM to temp files, loads into `ssl.SSLContext(PROTOCOL_TLS_SERVER)`, then deletes the temp files
- Session key derived identically on both sides: `HKDF(sha256(cert_pubkey_der), peer_id:epoch)` — tested in `TestMinerValidatorSessionKeyAgreement`

## Test Coverage Targets

- `TestRaTlsServer`: bundle generation, lazy generation, session creation, ssl context
- `TestRaTlsClientValid`: ok=True, score=0.5, session derived, quote embedded
- `TestRaTlsClientRejectDebugMode`: debug_mode cert → reject
- `TestRaTlsClientRejectWrongPeer`: wrong peer_id → identity_binding_failed
- `TestRaTlsClientRejectWrongEpoch`: old epoch → nonce_mismatch
- `TestRaTlsClientRejectTamperedSig`: tampered sig → chain_verification_failed
- `TestMinerValidatorSessionKeyAgreement`: both sides derive identical session key

## Files

- `subnet/tee/ratls/server.py` — `RaTlsServer`
- `subnet/tee/ratls/client.py` — `RaTlsClient`, `RaTlsAttestationError`, `RaTlsVerificationResult`
- `subnet/tee/ratls/__init__.py` — re-exports all public symbols
- `tests/tee/test_ratls.py` — test suite (pre-written, all must pass)
