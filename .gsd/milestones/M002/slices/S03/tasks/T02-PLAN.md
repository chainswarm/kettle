---
estimated_steps: 5
estimated_files: 1
---

# T02: Wire SealedStore into MockNodeProtocol

**Slice:** S03 — Sealed Storage
**Milestone:** M002

## Description

Add `self._sealed_store` to `MockNodeProtocol.register_handlers` and call `seal_json` in `miner_loop` after generating the work record. This makes all three integration tests from T01 pass and advances R015 from "library-only" to "wired into miner runtime." No new files — only `subnet/node/mock.py` changes. The change must not affect any existing `test_mock_node.py` tests.

## Steps

1. Open `subnet/node/mock.py`. In `register_handlers`, after the `self._verifier = DcapVerifier(...)` line, add:
   ```python
   from subnet.tee.sealed import SealedStore
   from subnet.tee.backends.mock import MOCK_MEASUREMENT, MOCK_DEV_KEY
   self._sealed_store = SealedStore(
       db=self.db,
       measurement=MOCK_MEASUREMENT,
       mock_key=MOCK_DEV_KEY,
   )
   ```
   Use lazy import style (import inside the method) to match the existing pattern in `register_handlers` and `miner_loop`. Use `MOCK_DEV_KEY` from the backend module — not the module-level `_MOCK_KEY` constant — so tests that inspect `_sealed_store.measurement` see the canonical mock value.

2. In `miner_loop`, find the block where `record` dict is constructed (after `n` and `parity` are set, after the tamper injection block). Insert the seal call immediately after the record dict is defined and the tamper block concludes, before `OutputEnvelope.create`:
   ```python
   # Seal per-epoch stats for measurement-bound recovery
   _seal_key = f"epoch_stats:{self.peer_id}:{epoch}"
   self._sealed_store.seal_json(_seal_key, {"n": n, "parity": parity})
   logger.info("[MockMiner] sealed epoch_stats epoch=%d peer=%s", epoch, self.peer_id[:16])
   ```
   Use the variable name `_seal_key` (with leading underscore) to avoid shadowing the outer `_MOCK_KEY` module constant.

3. Read `tests/test_mock_node.py` to confirm no test accesses `_sealed_store` or depends on the absence of the seal call. The new `seal_json` call writes to the `"sealed"` nmap namespace in the shared `db` fixture — this is isolated from `_WORK_TOPIC` and `TEE_QUOTE_TOPIC` so no existing assertions are affected.

4. Run the full integration test file to confirm T01's three tests now pass.

5. Run the full test suite to confirm zero regressions.

## Must-Haves

- [ ] `self._sealed_store` attribute created in `register_handlers` using `MOCK_MEASUREMENT` and `MOCK_DEV_KEY` from `subnet.tee.backends.mock`
- [ ] `seal_json(f"epoch_stats:{self.peer_id}:{epoch}", {"n": n, "parity": parity})` called in `miner_loop` after the tamper block, before `OutputEnvelope.create`
- [ ] INFO log line `[MockMiner] sealed epoch_stats epoch=<n> peer=<prefix>` emitted each `miner_loop` call
- [ ] `SealedStore` instantiation uses `MOCK_DEV_KEY` (canonical import), not the local `_MOCK_KEY` constant
- [ ] All 3 integration tests in `test_sealed_integration.py` pass
- [ ] All existing `test_mock_node.py` tests pass (no regressions)
- [ ] 21 `test_sealed.py` unit tests still pass

## Verification

```bash
# New integration tests — must all pass
python3 -m pytest tests/tee/test_sealed_integration.py -v
# Expected: 3/3 PASSED

# Pre-existing mock node tests — must not regress
python3 -m pytest tests/test_mock_node.py -v
# Expected: all PASSED

# Sealed unit tests — must not regress
python3 -m pytest tests/tee/test_sealed.py -v
# Expected: 21/21 PASSED

# Full suite
python3 -m pytest tests/ --ignore=tests/hypertensor -q
# Expected: all PASSED (≥176 tests)
```

## Observability Impact

- Signals added/changed:
  - `[SealedStore] Initialised with measurement=<hex[:16]>...` (DEBUG) — logged once per `register_handlers` call
  - `[SealedStore] Sealed key=epoch_stats:… (<n> bytes)` (DEBUG) — logged on every `miner_loop` call
  - `[MockMiner] sealed epoch_stats epoch=<n> peer=<prefix>` (INFO) — new INFO line in miner loop; grep-able signal that sealing is active
- How a future agent inspects this: `db.nmap_get("sealed", f"epoch_stats:{peer_id}:{epoch}")` returns the raw encrypted blob; `miner._sealed_store.exists(f"epoch_stats:{peer_id}:{epoch}")` returns `True`; both usable in integration tests and ad hoc inspection
- Failure state exposed: `SealedDecryptionError` raised on measurement mismatch; logged as unhandled exception if not caught — visible in test output and application logs

## Inputs

- `T01-PLAN.md` + `tests/tee/test_sealed_integration.py` (created in T01) — the 3 tests that must pass after this task
- `subnet/tee/sealed/store.py` — `SealedStore.__init__` signature: `(db: RocksDB, measurement: str, mock_key: bytes)`
- `subnet/tee/backends/mock.py` — `MOCK_MEASUREMENT`, `MOCK_DEV_KEY` — canonical mock constants
- `subnet/node/mock.py` — existing `register_handlers` and `miner_loop` structure; lazy import pattern already established
- S03-RESEARCH.md constraint: use `MOCK_MEASUREMENT` (not `TeeConfig.expected_measurement`) as the sealing measurement — `expected_measurement` can be empty string in mock config

## Expected Output

- `subnet/node/mock.py` — two changes: `self._sealed_store` in `register_handlers`; `seal_json` + INFO log in `miner_loop`
- All 3 integration tests passing; full test suite green
