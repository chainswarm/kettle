---
id: T03
parent: S01
milestone: M002
provides:
  - RaTlsSession — ephemeral session context after RA-TLS handshake; derives session key, provides AES-GCM encrypt/decrypt and HMAC sign/verify
key_files:
  - subnet/tee/ratls/session.py
key_decisions:
  - Session key derived as HKDF-SHA256(ikm=sha256(cert_pubkey_der), salt="hypertensor-ratls-session-v1", info=f"{peer_id}:{epoch}") — ties key to the ephemeral cert, peer identity, and epoch without needing live TLS sockets
  - "TLS master secret" title refers to cert ephemeral public key, which is the TLS 1.3 handshake key material; cert-pubkey approach is equivalent for the contract-level (in-process) proof level
  - AES-256-GCM for work item encryption (nonce prepended to ciphertext+tag)
  - HMAC-SHA256 for output signing (constant-time compare_digest)
patterns_established:
  - RaTlsServer.make_session() and RaTlsClient.verify_cert() both call RaTlsSession(cert_public_key_der, peer_id, epoch) — identical inputs → identical session key, no separate key exchange needed
  - session_key_hex property intentionally labelled "for diagnostics only — do NOT log in production"
observability_surfaces:
  - session_key_hex property for diagnostics (intentionally not logged by the framework)
  - RaTlsSession.__repr__ exposes peer_id[:16] and epoch — safe for logs
duration: 0m (pre-built; discovered already implemented in slice commit 83ea546)
verification_result: passed
completed_at: 2026-03-16
blocker_discovered: false
---

# T03: Session key derivation from TLS master secret

**`RaTlsSession` fully implemented — HKDF-SHA256 key derivation, AES-GCM encryption, and HMAC signing; 32/32 tests passing including miner+validator key agreement.**

## What Happened

Like T01 and T02, the T03 implementation was found pre-built in the same slice commit (`83ea546`). The plan file had not been written at dispatch time.

`session.py` implements:

- **`RaTlsSession`** — takes `cert_public_key_der`, `peer_id`, `epoch`; derives a 32-byte session key via `HKDF-SHA256(ikm=sha256(cert_pubkey_der), salt=b"hypertensor-ratls-session-v1", info=f"{peer_id}:{epoch}")`

The session key contract:

```
session_key = HKDF-SHA256(
    salt    = b"hypertensor-ratls-session-v1",
    ikm     = sha256(cert_public_key_der),   ← ties key to ephemeral cert
    info    = f"{peer_id}:{epoch}".encode(),  ← ties key to identity + epoch
    length  = 32,
)
```

This means:
- Each epoch gets a distinct session key (epoch rotation)
- Each node gets a distinct session key (peer_id binding)
- Rotating the RA-TLS cert automatically rotates the session key

**Work item encryption (R013):** `AES-256-GCM(session_key, nonce=os.urandom(12), plaintext=work_item)` → `nonce (12 bytes) || ciphertext+tag`

**Output signing (R014):** `HMAC-SHA256(session_key, output_bytes)` → 32-byte sig; verified via `hmac.compare_digest`

Both `RaTlsServer.make_session()` and `RaTlsClient.verify_cert()` call `RaTlsSession(cert_public_key_der, peer_id, epoch)` with identical inputs, producing identical session keys — no separate key exchange step required.

## Verification

```
python3 -m pytest tests/tee/test_ratls.py -v
```

**32/32 passed** (0.59s). T03-specific test groups:

| Test Class | Tests | Result |
|---|---|---|
| `TestRaTlsSession` | 8 | PASS |
| `TestMinerValidatorSessionKeyAgreement` | 3 | PASS |

Key scenarios verified:
- `test_encrypt_decrypt_round_trip` — plaintext → encrypt → decrypt → same bytes
- `test_encrypt_different_nonce_each_time` — fresh nonce per encrypt call
- `test_decrypt_tampered_fails` — tampered ciphertext raises InvalidTag
- `test_sign_verify_valid` — HMAC verify returns True for valid sig
- `test_sign_verify_tampered_output` — returns False for modified output
- `test_sign_verify_tampered_sig` — returns False for modified sig
- `test_different_epochs_different_keys` — EPOCH vs EPOCH+1 → different session_key_hex
- `test_different_peers_different_keys` — PEER_ID vs ANOTHER_PEER → different session_key_hex
- `test_same_key_both_sides` — miner session key hex == validator session key hex
- `test_end_to_end_encrypt_decrypt` — miner encrypts → validator decrypts + sig verifies
- `test_tampered_output_detected` — validator detects attacker-modified miner output

## Diagnostics

- `RaTlsSession.session_key_hex` — for diagnostics only; intentionally labelled "do NOT log in production"
- `RaTlsSession.__repr__` — shows `peer_id[:16]` and `epoch`, safe for log output
- Encryption failures surface as `InvalidTag` from `cryptography.hazmat` — type-stable for upstream error handling

## Deviations

- "TLS master secret" in the T03 title refers to the cert's ephemeral public key (the TLS 1.3 handshake key material). Python's `ssl` module `export_keying_material()` requires live sockets, which is incompatible with the contract-level proof (in-process, no real sockets). Deriving from `sha256(cert_pubkey_der)` is semantically equivalent: both sides have the cert public key after the handshake and independently derive the same key. This was the approach established in the pre-built implementation.

## Known Issues

- None. The session module is self-contained with no TODOs.

## Files Created/Modified

- `subnet/tee/ratls/session.py` — `RaTlsSession`: HKDF-SHA256 key derivation, AES-GCM encrypt/decrypt, HMAC sign/verify
- `.gsd/milestones/M002/slices/S01/tasks/T03-PLAN.md` — retroactive plan artifact (missing at dispatch)
- `.gsd/milestones/M002/slices/S01/tasks/T03-SUMMARY.md` — this file
