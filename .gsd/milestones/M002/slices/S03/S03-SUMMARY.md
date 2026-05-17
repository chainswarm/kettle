---
id: S03
parent: M002
milestone: M002
provides:
  - subnet/node/mock.py — MockNodeProtocol._sealed_store attribute (SealedStore, init in register_handlers); seal_json("epoch_stats:{peer_id}:{epoch}") called in miner_loop after tamper block
  - tests/tee/test_sealed_integration.py — 3 integration tests proving sealed storage in miner runtime (seal, round-trip unseal, measurement-mismatch rejection)
  - .gsd/REQUIREMENTS.md — R015 validated *(M002/S03)*
requires:
  - slice: S01
    provides: SealedStore pre-built in subnet/tee/sealed/store.py; MOCK_DEV_KEY, MOCK_MEASUREMENT in subnet/tee/backends/mock.py
  - slice: S02
    note: independent — S03 has no dependency on S02 (sealed storage touches only mock.py + sealed/store.py)
affects:
  - S04 — Gramine manifest must expose the sealed storage path (e.g. /tmp/sealed.db) and pin the measurement hash so SealedStore key derivation matches across restarts
key_files:
  - subnet/node/mock.py
  - tests/tee/test_sealed_integration.py
  - subnet/tee/sealed/store.py
key_decisions:
  - none new in this slice — all sealed storage architectural decisions (AES-GCM, measurement-derived key, RocksDB nmap column, SealedDecryptionError boundary) were baked into the pre-built SealedStore (S01)
patterns_established:
  - _sealed_store init pattern — SealedStore instantiated once in register_handlers alongside other TEE components (_publisher, _verifier); shared across all epochs via self._sealed_store; no per-epoch construction
  - epoch_stats:{peer_id}:{epoch} key naming convention — miner-scoped sealed data uses this composite key; peer_id scopes per-miner, epoch scopes per-round; stable prefix for grep-based inspection
  - seal immediately after work — seal_json called directly after the tamper-detection block, before OutputEnvelope.create; stats are sealed before the work record is published
observability_surfaces:
  - "[MockMiner] sealed epoch_stats epoch=<n>" — INFO log after every successful seal_json call in miner_loop
  - db.nmap_get("sealed", "epoch_stats:{peer_id}:{epoch}") — returns opaque encrypted blob; non-None confirms sealing is active; None = not yet sealed for this epoch
  - SealedDecryptionError — raised when a different-measurement store attempts unseal; carries key=... and "measurement mismatch or corruption" in message; stable prefix for log filtering
  - "[SealedStore] Sealed key=epoch_stats:..." — DEBUG log from SealedStore.__init__ (measurement[:16] shown, _seal_key never logged)
drill_down_paths:
  - .gsd/milestones/M002/slices/S03/tasks/T01-SUMMARY.md
  - .gsd/milestones/M002/slices/S03/tasks/T02-SUMMARY.md
duration: ~3 tasks (T01: spec-first tests, T02: wiring, T03: slice close)
verification_result: passed
completed_at: 2026-03-16
---

# S03: Sealed Storage

**SealedStore wired into MockNodeProtocol miner runtime — epoch stats sealed per-miner-per-epoch with measurement-bound key; 3 integration tests confirm seal, round-trip unseal, and measurement-mismatch rejection; R015 validated; 176/176 tests green.**

## What Happened

S03 demonstrated measurement-bound sealed storage in the miner runtime across three tasks:

**T01 — Spec-first integration tests:** Wrote 3 failing integration tests in `tests/tee/test_sealed_integration.py` before any wiring existed. Tests assert the full S03 contract: (1) `epoch_stats` key is sealed into RocksDB after `miner_loop`; (2) round-trip unseal returns original JSON; (3) a `SealedStore` instantiated with a different measurement raises `SealedDecryptionError`. Cross-module TEE imports placed inside test bodies so `pytest --collect-only` succeeds cleanly before implementation.

**T02 — Wiring:** Updated `subnet/node/mock.py` in two places:
- `register_handlers`: instantiates `SealedStore(db, MOCK_MEASUREMENT, MOCK_DEV_KEY)` → `self._sealed_store`; lazy import pattern matches existing TEE component style
- `miner_loop`: calls `self._sealed_store.seal_json(key, {"n": n, "parity": parity})` immediately after the tamper block, before `OutputEnvelope.create`; logs `[MockMiner] sealed epoch_stats epoch=<n>` at INFO

All 3 integration tests passed; zero regressions in the 176-test suite.

**T03 — Slice close:** Updated `REQUIREMENTS.md` (R015 → `validated *(M002/S03)*`), marked `M002-ROADMAP.md` S03 `[x]`, wrote slice artifacts, committed.

## Verification

```bash
# S03 integration tests
python3 -m pytest tests/tee/test_sealed_integration.py -v
# → 3/3 PASSED (test_miner_seals_epoch_stats, test_miner_sealed_epoch_stats_round_trip, test_different_measurement_raises_sealed_decryption_error)

# Pre-existing sealed unit tests (no regression)
python3 -m pytest tests/tee/test_sealed.py -v
# → 21/21 PASSED

# Mock node integration (no regression after mock.py changes)
python3 -m pytest tests/test_mock_node.py -v
# → all PASSED

# Full suite
python3 -m pytest tests/ --ignore=tests/hypertensor -q
# → 176/176 PASSED
```

## Requirements Advanced

- None at the "advanced" stage — R015 moved directly to validated.

## Requirements Validated

- **R015 — Sealed storage:** `SealedStore.seal_json("epoch_stats:{peer_id}:{epoch}", {...})` in `miner_loop` proves measurement-bound persistence. `SealedDecryptionError` raised on measurement mismatch proves cross-binary isolation. Validated by `tests/tee/test_sealed_integration.py` (3/3 passing).

## New Requirements Surfaced

- None discovered during this slice.

## Requirements Invalidated or Re-scoped

- None.

## Deviations

None. Pre-built `SealedStore` API matched the task plan exactly. The `_MOCK_KEY` module constant in `mock.py` was superseded by `MOCK_DEV_KEY` from `subnet.tee.backends.mock` (canonical import) — this was flagged in T02 as a deliberate decision to use the canonical source, not a deviation from plan.

## Known Limitations

- **No hardware sealing API.** `SealedStore` uses `MOCK_MEASUREMENT` and `MOCK_DEV_KEY` — not a real TDX/SGX sealing key derived from hardware. The mock measurement is a constant bytes value; real measurement changes on every build artifact change.
- **No backup / migration API for sealed data.** If the measurement changes (e.g. after a Python dependency update), sealed data from the previous measurement cannot be unsealed. There is no export/re-seal migration path. R015 notes this is "explicit and auditable" — the limitation is by design, but tooling does not yet exist.
- **Single RocksDB instance.** `SealedStore` shares the node's existing `db` (RocksDB) using a dedicated `"sealed"` nmap column family. There is no separate sealed-storage database or file — S04 Gramine manifest must account for this shared path when configuring filesystem allowlists.

## Forward Intelligence

### What S04 should know
- The `"sealed"` nmap column in the shared RocksDB is where all sealed blobs live. The Gramine manifest must grant the miner binary read/write access to the RocksDB path (wherever `db = RocksDB(...)` is constructed with `"sealed"` column) and must pin the measurement hash to match `MOCK_MEASUREMENT` (or its real hardware equivalent).
- `SealedStore.__init__` derives `_seal_key = HKDF(measurement, dev_key)` at construction time. If the Gramine manifest measurement pin mismatches the running binary's measurement, every `seal_json` call will succeed (seal uses the wrong key) but every `unseal` call from a correctly-measured binary will fail with `SealedDecryptionError`. This is the desired isolation behavior — but it means the manifest measurement must be kept in sync with the build artifact.
- `MOCK_DEV_KEY` is a placeholder. For real TDX, the dev_key will come from a provisioning step (e.g. remote attestation to a key server, or a hardware-derived root). The `SealedStore` interface accepts `dev_key: bytes` — the real provisioning mechanism is out of scope for M002.

### What's fragile
- `seal_json` is called unconditionally in every `miner_loop` iteration. If `SealedStore` construction in `register_handlers` fails (e.g. wrong column name), `self._sealed_store` will be unset and `miner_loop` will raise `AttributeError`. There is no graceful degradation — sealed storage failure = miner failure. This is intentional: sealed storage is a required contract, not an optional feature.

### Authoritative diagnostics
- `python3 -m pytest tests/tee/test_sealed_integration.py -v` — canonical S03 health check; 3/3 green = S03 contract intact
- `db.nmap_get("sealed", "epoch_stats:{peer_id}:{epoch}")` — returns opaque ciphertext blob; non-None = sealed; None = not yet sealed for this epoch
- `miner._sealed_store.exists("epoch_stats:{peer_id}:{epoch}")` — True after miner_loop runs
- `SealedDecryptionError` message prefix: `measurement mismatch or corruption` — stable string for log filtering
