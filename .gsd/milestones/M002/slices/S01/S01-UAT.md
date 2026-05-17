# S01: RA-TLS miner server + validator client (mock) — UAT

**Milestone:** M002
**Written:** 2026-03-16

## UAT Type

- UAT mode: artifact-driven
- Why this mode is sufficient: S01 proof level is "contract (in-process pipes, no real network)". All behaviour — valid handshake, all rejection scenarios, session key agreement, encrypt/decrypt, sign/verify — is deterministically exercised by the pytest suite without human interaction or a running server. Hardware is not required.

## Preconditions

- Python 3.12+ with dependencies installed (`pip install -e ".[dev]"`)
- `MOCK_TEE=true` (default; no TEE hardware required)
- No running servers needed — all tests are in-process

## Smoke Test

```bash
python3 -m pytest tests/tee/test_ratls.py -v
```

Expected: `32 passed` with no skips or warnings.

## Test Cases

### 1. Valid RA-TLS handshake

1. `RaTlsServer("peer-A", epoch=1, backend="mock")` generates cert bundle
2. `RaTlsClient().verify_cert(bundle.cert_pem, "peer-A", epoch=1)`
3. **Expected:** `result.ok == True`, `result.score == 0.5` (mock backend), `result.session` is non-None, `result.rejection_reason` is None

### 2. Debug mode cert rejected

1. Generate cert with mock quote where `debug_mode=True`
2. `RaTlsClient().verify_cert(debug_cert_pem, peer_id, epoch)`
3. **Expected:** `result.ok == False`, `result.rejection_reason == "debug_mode"`

### 3. Wrong peer identity rejected

1. Generate cert for peer-A
2. `RaTlsClient().verify_cert(peer_a_cert_pem, peer_id="peer-B", epoch=1)`
3. **Expected:** `result.ok == False`, `result.rejection_reason == "identity_binding_failed"`

### 4. Stale epoch cert rejected

1. Generate cert for epoch=1
2. `RaTlsClient().verify_cert(epoch1_cert_pem, peer_id, epoch=5)`
3. **Expected:** `result.ok == False`, `"nonce_mismatch" in result.rejection_reason`

### 5. Tampered quote cert rejected

1. Generate cert with valid quote; flip bytes in the cert extension
2. `RaTlsClient().verify_cert(tampered_cert_pem, peer_id, epoch)`
3. **Expected:** `result.ok == False`, `"chain_verification_failed" in result.rejection_reason`

### 6. Missing extension cert rejected

1. Generate a standard self-signed TLS cert (no TeeQuote extension)
2. `RaTlsClient().verify_cert(plain_cert_pem, peer_id, epoch)`
3. **Expected:** `result.ok == False`, `"missing_extension" in result.rejection_reason`

### 7. Miner+validator session key agreement

1. `server = RaTlsServer(PEER_ID, EPOCH, "mock")`; `miner_session = server.make_session()`
2. `result = RaTlsClient().verify_cert(server.cert_bundle.cert_pem, PEER_ID, EPOCH)`
3. `validator_session = result.session`
4. **Expected:** `miner_session.session_key_hex == validator_session.session_key_hex`

### 8. End-to-end encrypt/decrypt

1. Miner session encrypts `b"hello work item"` → `ciphertext`
2. Validator session decrypts `ciphertext` → `plaintext`
3. Miner session signs `b"miner output"` → `sig`
4. Validator session verifies `(b"miner output", sig)` → `True`
5. Validator session verifies `(b"tampered output", sig)` → `False`
6. **Expected:** all assertions hold

## Edge Cases

### SSL context creation

1. `server.make_ssl_context()` is called
2. **Expected:** returns `ssl.SSLContext`; no PEM files left in temp dir after the call

### Lazy cert generation

1. `RaTlsServer` constructed; no calls yet
2. Access `server.cert_bundle` twice
3. **Expected:** same object returned both times (generated once, not regenerated)

### RaTlsAttestationError opt-in

1. Call `RaTlsClient().verify_cert(debug_cert_pem, ...)` — returns `result.ok == False`
2. Raise manually: `if not result.ok: raise RaTlsAttestationError(result.rejection_reason)`
3. **Expected:** `RaTlsAttestationError` is a `ConnectionError` subclass

## Failure Signals

- Any test failure in `tests/tee/test_ratls.py` — indicates regression in cert generation, quote embedding, DcapVerifier pipeline, session key derivation, or AES/HMAC primitives
- `ImportError` from `subnet.tee.ratls` — indicates broken `__init__.py` re-exports
- `RaTlsExtensionMissingError` when it should not be raised — cert format regression
- `result.ok == True` on a debug/tampered/wrong-peer cert — attestation enforcement regression (critical)

## Requirements Proved By This UAT

- R011 — RA-TLS server on miner: `RaTlsServer` generates a valid RA-TLS cert; `make_ssl_context()` produces a usable TLS context; the TLS cert carries the DCAP quote as its X.509 extension
- R012 — RA-TLS client on validator: `RaTlsClient.verify_cert()` runs the full DcapVerifier pipeline; all four rejection scenarios (debug, wrong peer, stale epoch, tampered, missing extension) drop the connection before any data is exchanged
- R013 — Enclave-to-enclave encrypted channels: miner and validator independently derive identical session keys from the cert public key; AES-256-GCM encryption + HMAC-SHA256 signing proven end-to-end; tampered output detected

## Not Proven By This UAT

- Real TLS socket handshake — tests use in-process cert PEM exchange, not actual TCP/TLS connections. `RaTlsServer.make_ssl_context()` is verified to produce a valid `ssl.SSLContext` object; network-level TLS is exercised in S04 (Gramine) runtime integration.
- Real hardware attestation — mock backend used throughout (score=0.5). Hardware TDX/SEV-SNP path is verified architecturally in M001 and exercised on hardware separately.
- PCCS collateral freshness (R008, R021) — deferred to M002 CollateralCache; DcapVerifier uses mock chain in these tests.
- High-frequency load / concurrent verify_cert() calls — temp RocksDB allocation is not stress-tested; epoch-cadence use assumed.
- R014 (signed outputs) — HMAC signing API is proven here as part of RaTlsSession; the full signed-output workflow (miner signs each output, validator verifies before accepting) is wired up in S02.

## Notes for Tester

- All 32 tests are fully automated; no manual steps required.
- `result.score == 0.5` is correct for mock backend — this is the expected three-tier score for mock attestation (0.0 = no attestation, 0.5 = mock, 1.0 = hardware DCAP).
- The temp RocksDB created during `verify_cert()` is cleaned up automatically; `/tmp/ratls-*` dirs are ephemeral and should not accumulate between test runs.
- `RaTlsSession.session_key_hex` is intentionally available for test assertions but should not appear in production logs.
