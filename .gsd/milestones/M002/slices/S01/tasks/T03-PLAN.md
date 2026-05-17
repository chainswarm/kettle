# T03: Session key derivation from TLS master secret

**Retroactive plan artifact** — implementation was pre-built in slice commit 83ea546 alongside T01/T02.

## Goal

Implement `RaTlsSession`: after the RA-TLS handshake both miner and validator independently derive
an identical session key from the ephemeral cert's public key. The key ties to identity (peer_id)
and time (epoch) so it rotates automatically each epoch.

## Must-Haves

- `subnet/tee/ratls/session.py` — `RaTlsSession` class
- Key derivation: `HKDF-SHA256(ikm=sha256(cert_pubkey_der), salt=<fixed>, info=f"{peer_id}:{epoch}")`
- AES-256-GCM encrypt/decrypt (work item encryption, R013)
- HMAC-SHA256 sign/verify (output signing, R014)
- Both miner (`RaTlsServer.make_session`) and validator (`RaTlsClient.verify_cert`) derive
  the same key from the cert public key — no separate key exchange

## Notes

"TLS master secret" in the title refers to the cert's ephemeral public key, which IS the TLS
handshake key material in TLS 1.3. For the contract-level proof (in-process, no real sockets)
deriving from `sha256(cert_pubkey_der)` is semantically equivalent and avoids needing live sockets.

## Tasks

- [x] **T03: Session key derivation from TLS master secret** `est:20m`
