# T01: RaTlsCert — self-signed cert with TeeQuote X.509 extension

**Slice:** S01 — RA-TLS miner server + validator client (mock)
**Milestone:** M002
**Estimate:** 40m

## Objective

Implement `RaTlsCert`: a self-signed X.509 certificate generator that embeds a `TeeQuote` in a custom extension (OID `1.3.6.1.4.1.99999.1`). This cert is the RA-TLS attestation artifact — serving it over TLS IS the attestation.

## Must-Haves

- [ ] `TEE_QUOTE_OID = x509.ObjectIdentifier("1.3.6.1.4.1.99999.1")` defined
- [ ] `generate_ratls_cert(quote: TeeQuote) -> RaTlsCertBundle` — ephemeral ECDSA P-256 key, self-signed cert, quote in UnrecognizedExtension
- [ ] `extract_quote_from_cert(cert_pem: bytes) -> TeeQuote` — parses OID extension, deserialises
- [ ] `get_cert_public_key_bytes(cert_pem: bytes) -> bytes` — DER public key for session derivation
- [ ] `RaTlsCertBundle` dataclass with `cert_pem`, `key_pem`, `quote`
- [ ] `RaTlsExtensionMissingError` and `RaTlsExtensionParseError` custom exceptions
- [ ] `__init__.py` exports all public symbols

## Files

- `subnet/tee/ratls/cert.py` — main implementation
- `subnet/tee/ratls/__init__.py` — re-exports

## Acceptance

- Round-trip: `extract_quote_from_cert(generate_ratls_cert(q).cert_pem)` returns a `TeeQuote` with matching `peer_id`, `nonce`, `report_data`
- Missing extension raises `RaTlsExtensionMissingError`
- Cert has `-----BEGIN CERTIFICATE-----` PEM header
- Key has PEM header

## Tasks

- [ ] **T01: RaTlsCert — self-signed cert with TeeQuote X.509 extension** `est:40m`
