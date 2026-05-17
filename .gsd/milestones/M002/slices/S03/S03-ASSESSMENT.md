---
id: S03-ASSESSMENT
slice: S03
milestone: M002
assessed_at: 2026-03-16
verdict: roadmap_unchanged
---

# Roadmap Assessment after S03

## Verdict

**Roadmap is unchanged.** S04 proceeds as planned.

## Success-Criterion Coverage

- Validator establishes RA-TLS connection; handshake fails if attestation invalid → ✅ S01 (complete)
- Work items encrypted end-to-end to enclave session key → ✅ S02 (complete)
- Miner output signed by session key; tampering detected → ✅ S02 (complete)
- Sealed storage: re-keyed binary cannot unseal previous binary's state → ✅ S03 (complete, this slice)
- All features in mock mode; real TDX path documented with gramine.manifest.template → **S04** (remaining owner)

All five criteria have an owning slice. Coverage check passes.

## Did S03 Retire Its Risk?

Yes. `SealedStore` measurement-bound isolation is proven by 3 integration tests (seal, round-trip unseal, measurement-mismatch rejection). No residual risk carried forward to S04 beyond what was already scoped there.

## New Inputs for S04

S03 surfaced three concrete facts that are within S04's existing scope — no scope change needed:

1. **Shared RocksDB path.** `SealedStore` uses the `"sealed"` nmap column in the node's existing RocksDB instance (not a separate file). The Gramine manifest must grant the miner binary read/write access to that shared DB path.
2. **Measurement pin sync.** `_seal_key = HKDF(measurement, dev_key)` is derived at construction. If the manifest's pinned measurement drifts from the running binary's actual measurement, every `unseal` call silently fails with `SealedDecryptionError`. The manifest template must encode measurement as a build-time parameter.
3. **MOCK_DEV_KEY is a placeholder.** Real TDX provisioning (e.g. remote attestation to a key server) is out of M002 scope — already noted in R016. No action required.

## Requirement Coverage

- **R015 (Sealed storage):** `validated` — closed by this slice.
- **R016 (Gramine support):** `active` → owned by S04. Still sound.
- **R017 (Rust/Go single binary):** `active` → S04 or later. No change.
- **R008, R021:** `deferred` — unchanged.

No requirement ownership changed. Remaining roadmap provides credible coverage for all active requirements.
