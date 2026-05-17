---
id: S01-ASSESSMENT
slice: S01
milestone: M002
assessed_at: 2026-03-16
verdict: roadmap_unchanged
---

# S01 Roadmap Assessment — M002

## Verdict: Roadmap unchanged

The remaining slice ordering, descriptions, and risk labels are still accurate. No rewrites needed.

## Success Criteria Coverage

- `Validator establishes RA-TLS; handshake fails if attestation invalid → ✅ S01 (done)`
- `Work items encrypted end-to-end to enclave session key → S02` ✓ covered
- `Miner output signed by session key; tampering detected → S02` ✓ covered
- `Sealed storage: re-keyed binary cannot unseal previous binary's state → S03` ✓ covered
- `All features in mock mode; real TDX path documented with gramine.manifest.template → S04` ✓ covered

All five success criteria have at least one remaining owning slice. Coverage is sound.

## Risk Retired

S01 was `risk:high`. The stated risk — "RA-TLS libraries (gramine-ratls, Intel RATS-TLS) have complex C dependencies — Python bindings thin" — is **fully retired**. The implementation bypassed C bindings entirely by using Python's `cryptography` library for ECDSA/AES-GCM/HMAC and running `DcapVerifier` inline via a temp RocksDB. No gramine-ratls or RATS-TLS dependency is needed.

## Impact on Remaining Slices

**S02 (Input encryption + output signing, risk:medium):**
Starts from a higher base than the plan assumed. `RaTlsSession.encrypt()`, `decrypt()`, `sign()`, and `verify()` are already implemented and proven across 32 tests. S02's scope is now purely integration work: wire validator to call `session.encrypt(work_item)` before sending, wire miner to call `session.decrypt()` then `session.sign(output)` after processing, wire validator to call `session.verify(output, sig)` before accepting. The description in the roadmap ("validator encrypts work item to enclave session key; miner decrypts, processes, signs output; validator verifies signature") remains correct — the integration layer is the work.

**S03 (Sealed storage, risk:medium):**
Unaffected. S01 confirmed it is independent of RA-TLS — no shared code, no shared state. Scope and risk unchanged.

**S04 (Gramine manifest + reproducible build, risk:high):**
Unaffected. Risk is still real: Gramine manifest measurement changes with every Python dependency change. Hermetic build remains the challenge. Depends on S01/S02/S03 as stated.

## Requirements

Coverage remains sound across R011–R017, R021:
- R011, R012, R013 — `validated` (S01)
- R014 — S02 owns this (output signing)
- R015 — S03 owns this (sealed storage)
- R016 — S04 owns this (Gramine)
- R017 — active; Rust stub still in scope for S04 docs
- R021 — S04 owns CollateralCache DHT-backed implementation

No requirement ownership changed. No new requirements surfaced. No requirements invalidated.

## Known Fragility to Carry Forward

- **Temp RocksDB per `verify_cert()` call** (D007): acceptable at epoch cadence, will show under load. S02 does not increase call frequency — no action needed in S02. Flag for production optimization before high-frequency paths are added.
- **OID placeholder** (D009): `1.3.6.1.4.1.99999.1` is a single constant in `cert.py`. Not a blocker for any remaining slice. Production task only.
