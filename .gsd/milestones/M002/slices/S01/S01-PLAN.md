# S01: RA-TLS miner server + validator client (mock)

**Goal:** Miner generates a self-signed TLS cert with TeeQuote embedded in a custom X.509 extension. Validator connects, extracts the quote from the cert, runs DcapVerifier, drops connection if invalid. TLS handshake IS the attestation.
**Demo:** Unit tests prove: validator establishes connection to mock miner, rejects debug-mode cert, rejects wrong-peer cert, rejects tampered quote cert.

## Must-Haves

- `RaTlsCert` — generates self-signed cert with TeeQuote in X.509 extension OID
- `RaTlsServer` — async TLS server that serves the RA-TLS cert
- `RaTlsClient` — connects, extracts quote from server cert, runs DcapVerifier
- Mock backend: complete handshake, quote verified, session key derived
- Tests: valid → connected; debug_mode → handshake rejected; wrong identity → rejected; tampered → rejected

## Proof Level

- contract (no real network — in-process pipes), no hardware required
- Real runtime required: no
- Human/UAT required: no

## Verification

- `python3 -m pytest tests/tee/test_ratls.py -v` → all pass

## Tasks

<<<<<<< HEAD
- [x] **T01: RaTlsCert — self-signed cert with TeeQuote X.509 extension** `est:40m`
- [x] **T02: RaTlsServer + RaTlsClient — in-process TLS with quote verification** `est:45m`
- [x] **T03: Session key derivation from TLS master secret** `est:20m`
- [x] **T04: Tests — all RA-TLS scenarios** `est:40m`
=======
- [x] **T01: RaTlsCert — self-signed cert with TeeQuote X.509 extension** `est:40m`
- [x] **T02: RaTlsServer + RaTlsClient — in-process TLS with quote verification** `est:45m`
- [x] **T03: Session key derivation from TLS master secret** `est:20m`
- [x] **T04: Tests — all RA-TLS scenarios** `est:40m`
>>>>>>> gsd/M002/S01

## Files Likely Touched

- `subnet/tee/ratls/__init__.py`
- `subnet/tee/ratls/cert.py`
- `subnet/tee/ratls/server.py`
- `subnet/tee/ratls/client.py`
- `subnet/tee/ratls/session.py`
- `tests/tee/test_ratls.py`
