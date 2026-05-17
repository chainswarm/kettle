---
id: T01
parent: S01
milestone: M002
provides:
  - RaTlsCert — self-signed X.509 cert generator with embedded TeeQuote (OID 1.3.6.1.4.1.99999.1)
  - extract_quote_from_cert — extracts and deserialises TeeQuote from a cert's custom extension
  - get_cert_public_key_bytes — DER public key extraction for session key derivation
  - RaTlsCertBundle dataclass (cert_pem, key_pem, quote)
  - RaTlsExtensionMissingError / RaTlsExtensionParseError custom exceptions
key_files:
  - subnet/tee/ratls/cert.py
  - subnet/tee/ratls/__init__.py
key_decisions:
  - Use cryptography.x509.UnrecognizedExtension to embed raw JSON bytes as the OID value — no extra DER wrapping layer needed
  - OID 1.3.6.1.4.1.99999.1 as placeholder enterprise arc; documented as needing proper registration for production
  - Cert validity 24h aligned to epoch window; freshness checked via quote.nonce == epoch, not cert expiry
  - Subject CN = "ratls-{peer_id[:16]}" (human-readable, not security-relevant)
patterns_established:
  - RA-TLS pattern: self-signed cert + embedded quote = single artifact for both TLS and attestation
  - Round-trip: generate_ratls_cert(quote) → cert_pem → extract_quote_from_cert → same TeeQuote fields
observability_surfaces:
  - RaTlsExtensionMissingError / RaTlsExtensionParseError carry OID dotted string in message for diagnostics
  - RaTlsCertBundle.quote preserved for caller inspection (backend, measurement, peer_id visible)
duration: 0m (pre-built; discovered already implemented in slice commit 83ea546)
verification_result: passed
completed_at: 2026-03-16
blocker_discovered: false
---

# T01: RaTlsCert — self-signed cert with TeeQuote X.509 extension

**`generate_ratls_cert` and `extract_quote_from_cert` implemented with full round-trip and 8 targeted tests passing.**

## What Happened

The T01 implementation was found pre-built in `subnet/tee/ratls/cert.py` as part of the S01 slice commit (`83ea546`). The plan file had not been written at dispatch time, so T01 was dispatched without a local plan — the implementation existed and was complete.

`cert.py` implements:

- **`TEE_QUOTE_OID`** — `x509.ObjectIdentifier("1.3.6.1.4.1.99999.1")`, the custom extension OID
- **`generate_ratls_cert(quote)`** — generates an ephemeral ECDSA P-256 key, builds a self-signed X.509 cert (validity 24h, CN=`ratls-{peer_id[:16]}`), and embeds `quote.to_bytes()` as a `cryptography.x509.UnrecognizedExtension` under `TEE_QUOTE_OID`
- **`extract_quote_from_cert(cert_pem)`** — loads the PEM cert, fetches the extension by OID, reads `.value.value` (raw bytes), deserialises with `TeeQuote.from_bytes()`
- **`get_cert_public_key_bytes(cert_pem)`** — returns DER-encoded SubjectPublicKeyInfo for HKDF session key derivation
- **`RaTlsCertBundle`** dataclass, **`RaTlsExtensionMissingError`**, **`RaTlsExtensionParseError`**

`__init__.py` re-exports all public symbols.

## Verification

```
python3 -m pytest tests/tee/test_ratls.py -v
```

**32/32 passed** (0.57s). T01-specific tests (8 in `TestRaTlsCertGeneration`):

| Test | Result |
|---|---|
| `test_bundle_has_cert_pem` | PASS |
| `test_bundle_has_key_pem` | PASS |
| `test_bundle_quote_is_tee_quote` | PASS |
| `test_cert_contains_tee_quote_extension` | PASS |
| `test_extract_quote_round_trip` | PASS |
| `test_extract_quote_identity_still_valid` | PASS |
| `test_missing_extension_raises` | PASS |
| `test_get_cert_public_key_bytes` | PASS |

Round-trip verified: `extract_quote_from_cert(generate_ratls_cert(q).cert_pem)` returns identical `peer_id`, `nonce`, `report_data`, `backend`.

## Diagnostics

- `RaTlsExtensionMissingError` message includes OID dotted string — identifies missing extension in cert inspection tools
- `extract_quote_from_cert` wraps deserialisation failures in `RaTlsExtensionParseError` with the original exception chained
- `RaTlsCertBundle.quote` field lets callers inspect the embedded quote's backend/measurement without re-parsing the cert

## Deviations

none — implementation matched the T01 spec exactly

## Known Issues

none

## Files Created/Modified

- `subnet/tee/ratls/cert.py` — `generate_ratls_cert`, `extract_quote_from_cert`, `get_cert_public_key_bytes`, `RaTlsCertBundle`, error classes
- `subnet/tee/ratls/__init__.py` — re-exports all public symbols from cert, server, client, session
- `.gsd/milestones/M002/slices/S01/tasks/T01-PLAN.md` — retroactive plan artifact (missing at dispatch)
- `.gsd/milestones/M002/slices/S01/tasks/T01-SUMMARY.md` — this file
