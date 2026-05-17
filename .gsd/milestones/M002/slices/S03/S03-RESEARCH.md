# S03: Sealed Storage — Research

**Date:** 2026-03-17

## Summary

S03 was fully pre-built before this research pass — mirroring the S01/S02 pattern. `SealedStore` (`subnet/tee/sealed/store.py`) implements R015 completely at the library level: AES-256-GCM encryption with a 12-byte random nonce, key derived via `HKDF-SHA256(HMAC(mock_key, measurement))`, values stored in RocksDB under the `"sealed"` nmap namespace, `SealedDecryptionError` raised on any measurement mismatch or ciphertext corruption. 21 unit tests in `tests/tee/test_sealed.py` are present and passing, covering seal/unseal round-trips, measurement-binding rejection, overwrite, delete/exists, JSON helpers, and fresh-nonce invariants.

The miner-runtime integration is also pre-built: `MockNodeProtocol.register_handlers` instantiates `SealedStore(db=self.db, measurement=MOCK_MEASUREMENT, mock_key=MOCK_DEV_KEY)` → `self._sealed_store`, and `miner_loop` calls `self._sealed_store.seal_json(f"epoch_stats:{peer_id}:{epoch}", {"n": n, "parity": parity})` after the tamper-injection block and before `OutputEnvelope.create`. Three integration tests in `tests/tee/test_sealed_integration.py` exercise the full S03 contract end-to-end: epoch stats exist in sealed storage after `miner_loop`, unsealed values round-trip to the exact metrics dict, and a `SealedStore` constructed with a different measurement raises `SealedDecryptionError`.

Verified state as of this research pass: **176/176 tests passing** (5.23 s). R015 is `validated *(M002/S03)*`. The S03-PLAN.md shows all three tasks T01–T03 marked `[x]`. No implementation work is required for this slice — the research pass confirms everything is complete and consistent.

## Recommendation

The slice is done. No implementation work is required. The S03 contract (R015: measurement-bound sealed storage, measurement-change rejection, miner-runtime integration) is fully delivered. The only residual concerns are three open risks inherited by S04 (Gramine manifest filesystem path, measurement-pin synchronisation, and the production hardware sealing gap) — these are S04 scope and do not block S03 closure.

## Don't Hand-Roll

| Problem | Existing Solution | Why Use It |
|---------|------------------|------------|
| AES-256-GCM encryption + auth tag | `cryptography.hazmat.primitives.ciphers.aead.AESGCM` | Already used by `SealedStore`; random nonce + auth tag in one call; battle-tested; already a hard dep from S01 |
| Key derivation from measurement | `cryptography.hazmat.primitives.kdf.hkdf.HKDF` | Standard NIST primitive; deterministic given identical inputs; already in `SealedStore._derive_seal_key` |
| Mock measurement constant | `subnet.tee.backends.mock.MOCK_MEASUREMENT` | `sha256("mock-tee-v1").hexdigest()` — canonical; import it, never hardcode the string |
| Mock HMAC dev key | `subnet.tee.backends.mock.MOCK_DEV_KEY` | Canonical dev-mode bytes consistent across all mock TEE components; same bytes as `_MOCK_KEY` in `mock.py` but the exported API is `MOCK_DEV_KEY` |
| Persistent K/V under a namespace | `RocksDB.nmap_set / nmap_get / nmap_delete / nmap_exists` | `"sealed"` is the registered nmap column; all TEE modules share this pattern |

## Existing Code and Patterns

- `subnet/tee/sealed/store.py` — `SealedStore`: `seal(key, plaintext)` / `unseal(key) → bytes|None` / `seal_json` / `unseal_json` / `delete` / `exists`. Uses `_SEALED_NMAP = "sealed"` as RocksDB namespace; 12-byte random nonce prepended to each ciphertext blob; `key.encode()` passed as AAD so the key string is bound into the authentication tag. Key derivation: `HKDF(HMAC(mock_key, measurement))`. `SealedDecryptionError(RuntimeError)` raised on wrong measurement or corrupted ciphertext. `measurement` property returns the hex string used at construction.
- `subnet/tee/sealed/__init__.py` — re-exports `SealedStore`, `SealedDecryptionError`; module docstring includes usage example showing measurement-mismatch pattern and the canonical import path.
- `subnet/tee/backends/mock.py` — `MOCK_MEASUREMENT = sha256("mock-tee-v1").hexdigest()` and `MOCK_DEV_KEY = b"mock-tee-dev-key-do-not-use-in-production-!!"`. These are the canonical constants for all mock-mode sealed storage. Never hardcode these values elsewhere.
- `subnet/node/mock.py` — `MockNodeProtocol.register_handlers`: imports `SealedStore`, `MOCK_MEASUREMENT`, `MOCK_DEV_KEY`; instantiates `SealedStore(db=self.db, measurement=MOCK_MEASUREMENT, mock_key=MOCK_DEV_KEY)` → `self._sealed_store`. `miner_loop`: calls `self._sealed_store.seal_json(f"epoch_stats:{self.peer_id}:{epoch}", {"n": n, "parity": parity})` after the tamper-detection block, before `OutputEnvelope.create`; logs `[MockMiner] sealed epoch_stats epoch=<n>` at INFO. The seal is unconditional — no graceful degradation.
- `tests/tee/test_sealed.py` — 21 unit tests across 6 classes: `TestSealUnsealRoundTrip` (4), `TestMeasurementBinding` (4), `TestSealOverwrite` (2), `TestDeleteExists` (6), `TestJsonHelpers` (4), `TestFreshNonce` (1). Canonical isolated proofs of `SealedStore` correctness. The `TestMeasurementBinding` class is the canonical pattern for measurement-change tests — use it as the reference when adding new measurement-binding tests.
- `tests/tee/test_sealed_integration.py` — 3 integration tests wiring `SealedStore` into `MockNodeProtocol.miner_loop`: `test_miner_seals_epoch_stats`, `test_miner_unseal_round_trip`, `test_different_measurement_raises_sealed_decryption_error`. These are the S03 acceptance tests and must remain 3/3 green.
- `subnet/utils/db/database.py` — `RocksDB.nmap_set/get/delete/exists`; `SealedStore` delegates entirely to these. The same `self.db` instance is shared between `SealedStore` and all other TEE components — single DB, no second file handle.

## Constraints

- `SealedStore` takes `db: RocksDB` — must be the same `self.db` already on `MockNodeProtocol`. Do not create a second RocksDB instance pointing to the same path (file-lock conflict).
- `measurement` parameter must be the miner's own measurement (`MOCK_MEASUREMENT` in mock mode), not `TeeConfig.expected_measurement`. The config field can be empty string (validator-side skip); the sealing measurement must be non-empty and stable across restarts.
- All sealed blobs share the `"sealed"` RocksDB nmap column. Key naming convention is `"{feature}:{peer_id}:{epoch}"` — peer_id scopes per-miner, epoch scopes per-round. Follow this for any future sealed keys to avoid collision.
- `SealedDecryptionError` is a `RuntimeError` subclass. Tests must use `pytest.raises(SealedDecryptionError)` — do **not** assert on message text (the embedded `cryptography` exception repr is unstable across versions).
- `seal_json` is called unconditionally in every `miner_loop`. If `_sealed_store` is not initialised, `miner_loop` raises `AttributeError`. No graceful degradation — sealed storage failure is a miner failure (correctness invariant by design).
- The seal call is placed **after** the tamper injection block so tampered data is what gets sealed, preserving demo fidelity.
- `SealedStore.__init__` runs HKDF key derivation once at construction (~1 ms). Instantiate once in `register_handlers`, not per-epoch.

## Common Pitfalls

- **Initialising `SealedStore` per-epoch** — `__init__` runs HKDF. Instantiate once in `register_handlers`, store as `self._sealed_store`. Per-epoch construction is ~1 ms overhead per call and is semantically incorrect (the store is a stateful object, not a per-call helper).
- **Using `TeeConfig.expected_measurement` as the sealing measurement** — can be empty string in mock mode, producing a sealing key derived from the empty string. Always use `MOCK_MEASUREMENT` (mock) or the live measurement from the running quote (production TDX/SEV-SNP path).
- **Asserting `SealedDecryptionError` message text** — the embedded `cryptography` exception repr is unstable across library versions. Only `pytest.raises(SealedDecryptionError)`, never check the message string.
- **Missing `db.store.close()` in test fixture teardown** — RocksDB holds a file lock; missing `close()` causes `PermissionError` on subsequent test runs in the same process. Copy the `yield + close()` fixture pattern from `test_sealed.py` exactly.
- **Using `_MOCK_KEY` (module-local in `mock.py`) instead of importing `MOCK_DEV_KEY`** — same bytes, but `MOCK_DEV_KEY` is the documented public API. Always import from `subnet.tee.backends.mock`.
- **Placing the seal call before the tamper injection block** — would seal the pre-tamper value, hiding the tamper in sealed storage. Seal must go after the tamper block so the sealed record matches what was published.
- **AAD key binding** — `seal()` passes `key.encode()` as AAD to `AESGCM.encrypt`. If the key string changes between seal and unseal calls, AAD mismatch also raises `SealedDecryptionError`, which can be confused with a measurement mismatch. The key must be identical on both sides.

## Open Risks

- **Real TDX sealing gap** — `SealedStore` is software-only in mock mode. On TDX/SEV-SNP, the sealing key should derive from the hardware's measurement-bound key register (TDX: `TDREPORT`'s `SEAM_ATTRIBUTES`; SEV-SNP: `VCEK`). The API is ready (`mock_key: bytes` is the injection point); the hardware provisioning mechanism is out of scope for M002. S04 must document the production path in the Gramine manifest.
- **No backup / migration API for sealed data** — if the measurement changes (binary update, Python dep bump that shifts Gramine measurement in S04), sealed data from the previous measurement is permanently inaccessible. R015 states "backup / migration is explicit and auditable" — current code has no migration tooling. Flagged for a future milestone.
- **Shared RocksDB path for Gramine manifest** — S04 must ensure the manifest filesystem allowlist covers the RocksDB path used by `SealedStore` (same path as the DHT/local DB). If the manifest uses `sgx.encrypted_files` for sealed storage separately from the DHT directory, the manifest must be split accordingly.
- **Measurement-pin sync** — `_seal_key = HKDF(measurement, dev_key)` is derived at construction. If the Gramine manifest's pinned measurement drifts from the running binary's actual measurement, every `unseal` call will silently fail with `SealedDecryptionError`. The manifest template must encode measurement as a build-time parameter (S04 scope).
- **Key nmap collision** — no collision risk today (single sealed-storage user: mock miner). Future miner extensions adding sealed keys must follow the `"{feature}:{peer_id}:{epoch}"` naming convention in the shared `"sealed"` nmap column.
- **Test isolation on CI** — RocksDB temp paths use `tmp_path` (pytest fixture). Parallel CI test runs are safe (each gets a unique `tmp_path`). But `db.store.close()` must be in the fixture teardown or CI leaves locked stores across test sessions.

## Verification (confirmed this research pass)

```bash
# S03 integration tests
python3 -m pytest tests/tee/test_sealed_integration.py -v
# → 3/3 PASSED

# Pre-existing sealed unit tests
python3 -m pytest tests/tee/test_sealed.py -v
# → 21/21 PASSED

# Full suite
python3 -m pytest tests/ --ignore=tests/hypertensor -q
# → 176/176 PASSED (5.23 s)
```

## Skills Discovered

| Technology | Skill | Status |
|------------|-------|--------|
| Python / pytest | (built-in) | installed |
| `cryptography` (HKDF, AESGCM) | (already used in S01–S02) | installed |
| `rocksdict` (RocksDB Python bindings) | (already used throughout codebase) | installed |

No external skills are needed for this slice. All cryptographic primitives (`HKDF`, `AESGCM`) are provided by `cryptography` — already a hard dependency from S01. No new packages, no new skills.

## Sources

- `subnet/tee/sealed/store.py` docstring — security model, storage format, mock vs. real hardware semantics, key derivation spec (source: project codebase, confirmed current)
- `subnet/tee/sealed/__init__.py` — usage example showing measurement-mismatch pattern and canonical import (source: project codebase)
- `tests/tee/test_sealed.py` — 21 unit tests; `TestMeasurementBinding` class for canonical measurement-change test pattern; 21/21 passing (source: project codebase, verified)
- `tests/tee/test_sealed_integration.py` — 3 integration tests; full S03 runtime contract; 3/3 passing (source: project codebase, verified)
- `subnet/node/mock.py` — `MockNodeProtocol.register_handlers` + `miner_loop` seal call; full wiring implementation (source: project codebase, confirmed current)
- `subnet/tee/backends/mock.py` — `MOCK_MEASUREMENT`, `MOCK_DEV_KEY` canonical constants (source: project codebase)
- S03-PLAN.md — T01–T03 all `[x]`; full implementation scope and constraints; confirmed complete (source: GSD artifacts)
- R015 in `REQUIREMENTS.md` — `validated *(M002/S03)*` — "Persistent miner state sealed with measurement hash; only same binary can unseal; backup/migration explicit and auditable" (source: GSD artifacts)
- S01-SUMMARY.md Forward Intelligence — `RaTlsSession` and RocksDB patterns established in S01 that S03 builds on (source: GSD artifacts)
- S03-SUMMARY.md — complete slice summary with YAML frontmatter confirming 176/176 passing and R015 validated (source: GSD artifacts)
