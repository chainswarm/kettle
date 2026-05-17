# S02 — Research: Input Encryption + Output Signing

**Date:** 2026-03-16

## Summary

S02 is the **integration slice**. The cryptographic primitives (`RaTlsSession.encrypt`, `decrypt`, `sign`, `verify_signature`) were fully delivered in S01 — 32/32 tests pass and cover every failure path. What S02 must add is the **protocol-level wiring**: typed wire envelopes, cert transport via DHT, and a demonstration in MockNodeProtocol that subnet owners can follow.

The core technical question is: how does the validator get the miner's RA-TLS cert in mock mode (no live TLS socket)? The answer is DHT publication: miner publishes `cert_pem` to a new `ratls_cert` DHT topic alongside the TEE quote; validator fetches, verifies, derives session, then verifies signed output. This closes the loop without live networking.

The second key question is output **replay protection**: `session.sign(output_bytes)` alone doesn't bind the output to a specific work request — a miner could replay a previous valid signed output. The fix is to include a validator-generated `request_id` nonce in the signed payload: `session.sign(request_id.encode() + b":" + output_bytes)`. S01 left this open; S02 closes it.

## Recommendation

Add a thin `envelope.py` module in `subnet/tee/ratls/` with `WorkEnvelope` (encrypted work item + request_id) and `OutputEnvelope` (output + request-bound signature). Add `RATLS_CERT_TOPIC` to the DHT key helpers. Update `MockNodeProtocol` to publish cert_pem and use signed outputs. Write tests covering the full protocol-level flow plus the replay scenario.

Do **not** add a new live socket layer — the in-process contract proof pattern established by S01 is correct and sufficient. The envelope API is what subnet owners integrate into their actual protocol; transport is their concern.

## Don't Hand-Roll

| Problem | Existing Solution | Why Use It |
|---------|------------------|------------|
| AES-256-GCM encryption | `RaTlsSession.encrypt/decrypt` | Already implemented, nonce management done, InvalidTag on tamper |
| HMAC-SHA256 output signing | `RaTlsSession.sign/verify_signature` | Already implemented, `compare_digest` timing-safe |
| Session key derivation | `RaTlsSession.__init__` (HKDF-SHA256) | Both sides derive identically from cert pubkey; no extra messages |
| Wire serialisation | Python `dataclasses` + `json` + `base64` | No extra deps; human-readable for debugging; compatible with DHT bytes storage |
| Cert generation | `RaTlsServer.cert_bundle` + `RaTlsServer.make_session()` | Lazy generation, temp PEM handling already correct |
| Cert verification | `RaTlsClient.verify_cert()` | Full 7-step DcapVerifier pipeline inline, structured rejection reasons |

## Existing Code and Patterns

- `subnet/tee/ratls/session.py` — **primary S02 dependency**. `RaTlsSession(cert_public_key_der, peer_id, epoch)` → `encrypt(bytes)→bytes`, `decrypt(bytes)→bytes`, `sign(bytes)→bytes`, `verify_signature(bytes, bytes)→bool`. Session key is 32-byte HKDF-SHA256 derived from cert pubkey. Reuse directly — do not re-implement.

- `subnet/tee/ratls/server.py` — `RaTlsServer.make_session()` gives the miner its session handle. `RaTlsServer.cert_bundle.cert_pem` is what gets published to DHT.

- `subnet/tee/ratls/client.py` — `RaTlsClient.verify_cert(cert_pem, peer_id, epoch)` → `RaTlsVerificationResult.session`. The `.session` field is `None` on rejection. Callers must guard on `.ok` before using `.session`.

- `subnet/tee/quote.py` — `TEE_QUOTE_TOPIC`, `dht_key(epoch, peer_id)` pattern. New `RATLS_CERT_TOPIC = "ratls_cert"` should be added here following the same convention. The `dht_key` helper is reusable for cert storage.

- `subnet/node/mock.py` — `MockNodeProtocol` is the reference integration target. Miner side: `miner_loop` → publish quote + cert, sign work result. Validator side: `validator_call` → fetch cert, verify, fetch work record, verify output signature. `MockOverwatchVerifier` does not use session keys — it's public-data-only, so it's not affected by S02 changes.

- `tests/tee/test_ratls.py` — Pattern to follow: `@pytest.fixture` for `backend`, `mock_config`, `bundle`; `TeeConfig.__new__(TeeConfig)` for config without env vars; in-process proof without sockets.

## Constraints

- **No new dependencies**: all needed crypto is in `cryptography` (already installed). `base64`, `json`, `os`, `dataclasses` from stdlib. Do not add msgpack, protobuf, or any new package.
- **In-process testing only**: no live TLS sockets in the test suite. S01 established this constraint — it's correct at the contract proof level. Live integration is out of scope until S04.
- **DHT key convention**: `f"{epoch}:{peer_id}"` is the canonical key format (`dht_key()` helper). Use it for cert storage as well.
- **`RaTlsSession` is epoch-scoped**: one session per `(cert, peer_id, epoch)` tuple. All work items in an epoch share the same session key — this is intentional. Each `encrypt()` call generates a fresh random nonce, so ciphertexts differ even for identical plaintexts.
- **`RaTlsVerificationResult.session` is None on rejection**: every caller of `verify_cert()` must check `.ok` before accessing `.session`. This is already the S01 convention.
- **Merge conflict in REQUIREMENTS.md**: `HEAD` branch shows R014 `validated *(M002)*` and R015 `validated *(M002)*`. The `gsd/M002/S01` branch shows R015 `validated (M002/S02)`. R014 is the S02 target; R015 (sealed storage) is S03's target. Resolve conflict to HEAD markers when updating requirements.

## Common Pitfalls

- **Signing output_bytes alone is insufficient** — `session.sign(output_bytes)` does not bind the output to a specific work request. A miner could reuse a valid signed output from a previous epoch (same session if the cert is reused — shouldn't happen, but defensive design is cheap). Fix: sign over `request_id + ":" + output_bytes` where `request_id` is a validator-generated nonce included in the `WorkEnvelope`. The miner echoes the request_id in the `OutputEnvelope`.

- **DHT cert epoch mismatch** — If a miner publishes its cert_pem to DHT keyed by `ratls_cert:{epoch}:{peer_id}`, and then regenerates its cert mid-epoch, the DHT cert and the session key will diverge. Mitigation: cert is generated once per epoch (lazy via `RaTlsServer.cert_bundle`), published once, and stable for the epoch window.

- **WorkEnvelope vs transport encryption confusion** — S02's work item encryption is an *application-layer* concern, not a TLS-layer concern. The envelope is encrypted to the session key (derived from the miner's cert). This is independent of whether the data travels over a TLS socket. Subnet owners who use live sockets get both; in-process tests prove the application-layer property without the socket.

- **`TeeConfig.__new__(TeeConfig)` pattern** — tests use this to construct `TeeConfig` without triggering env-var parsing. Follow this pattern exactly for S02 test fixtures.

- **`from_bytes` must tolerate extra fields** — `WorkEnvelope.from_bytes` and `OutputEnvelope.from_bytes` should use `d.get(key, default)` for optional fields, matching how `TeeQuote.from_bytes` is implemented. Forwards-compatible deserialization.

## Open Risks

- **Cert-over-DHT adds a new DHT write per epoch per miner** — currently only `tee_quote` is published. Adding `ratls_cert` doubles the per-epoch write. This is acceptable at subnet scale (dozens of miners, not millions), but worth noting in the S02 summary.

- **`MockNodeProtocol` now has two integration paths** — with and without RA-TLS cert. If the cert DHT key is missing (e.g., old miner or mock without ratls enabled), `validator_call` must degrade gracefully (fall back to raw tee_score without signature verification) rather than crashing. S02 should define whether this fallback is `score=0.0` or `score=tee_score * 0.5` — recommend `score=0.0` (no signed output = no trust in the result).

- **`InvalidTag` exception surface** — `session.decrypt()` raises `cryptography.exceptions.InvalidTag` on tampered ciphertext. The `WorkEnvelope.decrypt()` wrapper must catch this and raise a domain-specific exception (`TeeDecryptionError`) so protocol code doesn't need to import `cryptography.exceptions` directly.

## Skills Discovered

| Technology | Skill | Status |
|------------|-------|--------|
| Python cryptography (AES-GCM, HMAC, HKDF) | stdlib + cryptography | installed (already used in session.py) |
| No additional skills needed | — | — |

## Sources

- S01 implementation: `subnet/tee/ratls/session.py`, `server.py`, `client.py`, `cert.py`, `__init__.py`
- S01 test suite: `tests/tee/test_ratls.py` — 32/32 pass; pattern to follow for S02 tests
- S01 forward intelligence: `.gsd/milestones/M002/slices/S01/S01-SUMMARY.md` — `RaTlsSession` is the primary S02 API; `DcapVerifier` pipeline is settled; `result.session` is None on rejection
- Mock protocol integration target: `subnet/node/mock.py` — `MockNodeProtocol` + `MockNodeScoring` + `MockOverwatchVerifier`
- DHT key convention: `subnet/tee/quote.py` — `TEE_QUOTE_TOPIC`, `dht_key()` pattern to replicate for `RATLS_CERT_TOPIC`
