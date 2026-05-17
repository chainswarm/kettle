# M002: Confidential Compute — RA-TLS + Input Encryption + Sealed Storage

**Vision:** Every byte of work sent to a miner is encrypted to the enclave. The TLS connection to a miner IS the attestation — no separate quote exchange. Miner state is sealed so only the exact approved binary can read it. This is the layer that makes the subnet genuinely private and tamper-proof, not just attestation-checked.

## Success Criteria

- Validator establishes RA-TLS connection to miner; TLS handshake fails if attestation invalid
- Work items are encrypted end-to-end to the enclave session key
- Miner output is signed by the session key; tampering detected by validator
- Sealed storage: a re-keyed miner binary cannot read the previous binary's sealed state
- All features work in mock mode; real TDX path documented with gramine.manifest.template

## Key Risks

- RA-TLS libraries (gramine-ratls, Intel RATS-TLS) have complex C dependencies — Python bindings thin
- Gramine manifest measurement changes on every Python dependency change — need hermetic build
- RA-TLS adds ~200ms to first connection — acceptable for epoch-cadence scoring

## Slices

- [x] **S01: RA-TLS miner server + validator client (mock)** `risk:high` `depends:[]`
  > After this: validator establishes RA-TLS to mock miner; TLS cert IS the attestation; invalid cert dropped at handshake — tested with mock backend.

- [x] **S02: Input encryption + output signing** `risk:medium` `depends:[S01]`
  > After this: validator encrypts work item to enclave session key; miner decrypts, processes, signs output; validator verifies signature — tested end-to-end in mock mode.

- [x] **S03: Sealed storage** `risk:medium` `depends:[S01]`
  > After this: miner state sealed with measurement-derived key; different binary = different key = cannot unseal — tested with mock measurement change.

- [x] **S04: Gramine manifest + reproducible build** `risk:high` `depends:[S01,S02,S03]`
  > After this: `gramine-sgx python run_node.py` or `gramine-direct python run_node.py` produces a known measurement; manifest template pins syscalls, files, RA-TLS config.

## Requirement Coverage

- Covers: R011–R017, R021
