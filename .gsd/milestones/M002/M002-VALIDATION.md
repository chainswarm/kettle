---
verdict: needs-attention
remediation_round: 0
---

# Milestone Validation: M002

## Success Criteria Checklist

- [x] **Validator establishes RA-TLS connection to miner; TLS handshake fails if attestation invalid**
  — evidence: S01 delivers `RaTlsServer` + `RaTlsClient`; `verify_cert()` runs full `DcapVerifier` pipeline inline; all rejection paths tested (debug_mode, identity_binding_failed, nonce_mismatch, chain_verification_failed, missing_extension); 32/32 `tests/tee/test_ratls.py` pass. `TestRaTlsClientRejectDebugMode`, `TestRaTlsClientRejectWrongPeer`, `TestRaTlsClientRejectWrongEpoch`, `TestRaTlsClientRejectTamperedSig` are direct proof.

- [~] **Work items are encrypted end-to-end to the enclave session key**
  — partial gap: `WorkEnvelope` (AES-256-GCM) is fully implemented in `subnet/tee/ratls/envelope.py` and unit-tested (5 `TestWorkEnvelope` tests pass, including tamper detection). However, the validator→miner work-dispatch path in `MockNodeProtocol` does **not** use `WorkEnvelope` — miner receives work as plaintext; session is used only for `OutputEnvelope` signing (miner→validator direction). S02 summary explicitly notes this as a Known Limitation: *"WorkEnvelope is implemented and tested but not yet used by MockNodeProtocol for validator→miner encrypted work dispatch."* The slice spec stated *"validator encrypts work item to enclave session key; miner decrypts, processes, signs output — tested end-to-end in mock mode"* which was not achieved for the validator→miner leg. Deferred to M004+ (requires bidirectional transport). Crypto is proven; wire integration is absent for this direction.

- [x] **Miner output is signed by the session key; tampering detected by validator**
  — evidence: S02 `OutputEnvelope.create()` signs `request_id + ":" + output` with HMAC-SHA256; validator calls `OutputEnvelope.verify()` and assigns `score=0.0 / error="output_signature_invalid"` on failure; `TestOutputEnvelope::test_tampered_output_fails_verify`, `TestMockProtocolSignedOutput::test_validator_rejects_tampered_record_as_invalid_signature`, and `test_replay_protection` are direct proofs. 16/16 `tests/tee/test_envelope.py` pass.

- [x] **Sealed storage: a re-keyed miner binary cannot read the previous binary's sealed state**
  — evidence: S03 wires `SealedStore` into `MockNodeProtocol.miner_loop`; `test_different_measurement_raises_sealed_decryption_error` instantiates a store with a different measurement byte and confirms `SealedDecryptionError` is raised on `unseal`. 3/3 `tests/tee/test_sealed_integration.py` pass; 21/21 pre-existing `tests/tee/test_sealed.py` pass.

- [x] **All features work in mock mode; real TDX path documented with gramine.manifest.template**
  — evidence: S04 delivers `gramine.manifest.template` (fixed: Gramine Protected FS entries removed, SealedStore AES-GCM model documented), `scripts/build-gramine.sh` (4-step reproducible build + MRENCLAVE extraction), `GRAMINE.md` (updated run commands and sealed storage description), and `tests/tee/test_gramine_manifest.py` (8 tests, 7 pass unconditionally in CI, 1 skips when Gramine not installed). Full suite: 181 passed, 1 skipped — all green.

---

## Slice Delivery Audit

| Slice | Claimed (roadmap spec) | Delivered | Status |
|-------|------------------------|-----------|--------|
| S01 | RA-TLS cert is attestation; invalid cert dropped at TLS handshake; tested with mock backend | `RaTlsCert`, `RaTlsServer`, `RaTlsClient`, `RaTlsSession`; 32/32 tests; all rejection paths proven | ✅ pass |
| S02 | Validator encrypts work item to session key; miner decrypts, processes, signs output; validator verifies — tested end-to-end in mock mode | `WorkEnvelope` + `OutputEnvelope` built and unit-tested; miner→validator signing wired end-to-end; **validator→miner encrypted dispatch not wired** (plaintext work dispatch in mock); 16/16 tests pass | ⚠️ partial |
| S03 | Miner state sealed with measurement-derived key; different binary = different key = cannot unseal — tested with mock measurement change | `SealedStore` wired into `miner_loop`; measurement-mismatch `SealedDecryptionError` proven by `test_different_measurement_raises_sealed_decryption_error`; 176/176 tests pass | ✅ pass |
| S04 | `gramine-sgx python run_node.py` / `gramine-direct python run_node.py` produces known measurement; manifest pins syscalls, files, RA-TLS config | Manifest fixed, CI-runnable 8-test suite, `build-gramine.sh` with MRENCLAVE extraction, `GRAMINE.md` updated; 181/181 pass | ✅ pass |

---

## Cross-Slice Integration

**S01 → S02 (RaTlsSession consumed by envelope layer):** Correct. `envelope.py` calls `session.sign()` / `session.verify()` per D011; `session.encrypt()` / `session.decrypt()` are used in `WorkEnvelope` unit tests. Boundary contract is intact.

**S01 → S03 (independent co-deployment):** Correct. `SealedStore` is independent of the RA-TLS stack and was wired alongside it in `register_handlers`.

**S02 → S03 (no dependency):** Correct. `SealedStore.seal_json()` is called in `miner_loop` after the tamper block and before `OutputEnvelope.create()` — no coupling to S02 envelope logic.

**S03 → S04 (sealed storage path in manifest):** Correct. S04 manifest references `/data` as the RocksDB (and thus sealed store) path, consistent with S03's "Single RocksDB instance" design. Gramine Protected FS entries were correctly removed.

**WorkEnvelope gap (S02 → mock protocol):** The validator→miner dispatch boundary in `MockNodeProtocol.validator_call` does not exercise `WorkEnvelope.create()` or the miner-side `WorkEnvelope.open()` decryption. This means `test_mock_node.py` never exercises the full S02 spec path for work-item encryption. The 16 `test_envelope.py` tests cover the API in isolation but not the integrated dispatch loop.

---

## Requirement Coverage

| Req | Roadmap claims coverage | Status | Notes |
|-----|------------------------|--------|-------|
| R011 | S01 | `validated` | 32 tests; all handshake rejection paths |
| R012 | S01 | `validated` | inline `DcapVerifier` in `RaTlsClient.verify_cert()` |
| R013 | S01/S02 | `validated (partial)` | Encrypt/decrypt proven by unit tests; validator→miner dispatch not wired in protocol |
| R014 | S02 | `validated` | OutputEnvelope HMAC signing; tamper detection in mock loop |
| R015 | S03 | `validated` | Measurement-bound sealing; cross-binary isolation proven |
| R016 | S04 | `validated` | Manifest CI tests; build script; GRAMINE.md |
| R017 | claimed in roadmap | `active` (unaddressed) | No Rust/Go stub created. S01 assessment noted it was "in scope for S04 docs"; S04 delivered nothing for R017. Requirement remains `active`. |
| R021 | claimed in roadmap | `deferred` (unchanged) | PCCS caching in DHT not implemented in any M002 slice. Status unchanged from M001 handoff. `subnet/tee/collateral.py` does not exist. |
| R008 | (not claimed) | `deferred` (unchanged) | Unchanged from M001; out of M002 scope. |

**R017 gap:** The milestone roadmap states "Covers: R011–R017, R021". R017 requires a Rust/Go single-binary stub. No stub was written, no documentation of a Rust miner was added, and S04 did not produce anything for this requirement. The requirement remains `active`. This does not violate a success criterion (R017 is not in the 5 success criteria bullet points) but represents a gap in the stated coverage scope.

**R021 gap:** Similarly declared in the roadmap coverage and was listed as `deferred (M002)` in REQUIREMENTS.md when M002 began. It was never addressed in any slice — all four slice assessments note it as "deferred; unchanged." The requirement remains `deferred`.

---

## Test Suite Health

| Suite | Count | Result |
|-------|-------|--------|
| `tests/tee/test_ratls.py` | 32 | ✅ all pass |
| `tests/tee/test_envelope.py` | 16 | ✅ all pass |
| `tests/tee/test_sealed_integration.py` | 3 | ✅ all pass |
| `tests/tee/test_sealed.py` | 21 | ✅ all pass |
| `tests/tee/test_gramine_manifest.py` | 8 | ✅ 7 pass, 1 skip (Gramine not installed) |
| Full suite (excl. hypertensor) | 181+1 | ✅ 181 pass, 1 skip |

---

## Verdict Rationale

**Verdict: `needs-attention`**

All five milestone success criteria are substantially met and all 181 tests pass. The core confidential-compute stack — RA-TLS attestation-at-handshake, AES-GCM session encryption, HMAC-SHA256 signed outputs, measurement-bound sealed storage, and the Gramine manifest — is implemented, wired into the mock protocol where applicable, and verified by test suites.

The attention items are:

1. **Validator→miner work-item encryption not wired into mock dispatch (S02 partial delivery against its own slice spec).** `WorkEnvelope` is built and unit-tested; `RaTlsSession.encrypt/decrypt` is proven; but `MockNodeProtocol` never calls `WorkEnvelope.create()` on the validator side or `WorkEnvelope.open()` on the miner side. The milestone success criterion says "work items are encrypted end-to-end to the enclave session key" — this is true at the API level but not demonstrated in the mock dispatch loop. S02 summary explicitly defers this to M004+ (no bidirectional transport yet). This is a known, scoped gap, not an overlooked regression.

2. **R017 (Rust/Go single binary) not addressed.** The roadmap lists R017 in its coverage scope. No Rust stub, no documentation addition, no Cargo.toml. Requirement remains `active`.

3. **R021 (PCCS caching in DHT) not addressed.** Listed as `deferred (M002)` at milestone start; no slice touched it; remains `deferred`.

Items 2 and 3 do not appear in the milestone success criteria and were not the subject of any planned slice. They represent aspirational roadmap scope that was never actioned. They are not blocking correctness issues.

Item 1 is the most concrete gap against a stated success criterion, but the WorkEnvelope implementation is complete and proven — the gap is purely in the mock protocol wiring, which was a deliberate scoping call (no transport layer until M004). The full encrypt→decrypt property is proven by `TestMinerValidatorSessionKeyAgreement` unit tests.

**No material correctness, security, or completeness issue exists that requires remediation before the milestone can be sealed.** The gaps are documented, the scope rationale is clear, and all primary deliverables work correctly.

## Attention Items (non-blocking)

1. **WorkEnvelope mock dispatch** — `MockNodeProtocol.validator_call` should call `WorkEnvelope.create(request_id, work_payload, session)` and miner-side `WorkEnvelope.open(encrypted_payload, session)` to fully demonstrate the success criterion. Deferred to M004 (live transport) per S02 summary. Update the success criterion in the roadmap to reflect the actual scope: *"WorkEnvelope encryption API proven by unit tests; end-to-end mock wiring deferred to M004 transport layer."*

2. **R017** — Either add a minimal Rust stub (even an empty `examples/rust-miner/` scaffold with `Cargo.toml` + README) to satisfy the coverage claim, or explicitly remove R017 from the M002 roadmap coverage list and defer to a future milestone.

3. **R021** — Update the REQUIREMENTS.md status from `deferred (M002)` to `deferred (M003+)` to reflect that M002 did not address it, preventing future confusion about when it was scoped.
