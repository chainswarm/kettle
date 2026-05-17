# S03: Sealed Storage

**Goal:** Wire `SealedStore` into `MockNodeProtocol.miner_loop` so measurement-bound sealed storage is demonstrated in the miner runtime — not just as a standalone library. Prove that a different enclave binary (different measurement) cannot unseal state written by the original binary.
**Demo:** `python3 -m pytest tests/tee/test_sealed.py tests/tee/test_sealed_integration.py -v` — 21 + 3 tests pass; the integration test shows `SealedDecryptionError` when measurement changes between epochs.

## Must-Haves

- `SealedStore` is initialised once in `MockNodeProtocol.register_handlers` (not per-epoch) and stored as `self._sealed_store`
- Miner seals per-epoch stats (`{n, parity}`) under key `epoch_stats:{peer_id}:{epoch}` on every `miner_loop` call
- Miner unseals stats from prior epoch on retry path; returns cached values without regenerating if the sealed key exists (demonstrates real usage)
- Integration test `tests/tee/test_sealed_integration.py` proves: seal under measurement A → `SealedDecryptionError` when measurement changes to B
- Integration test proves: miner can unseal its own epoch stats within the same measurement (round-trip in `miner_loop`)
- Integration test proves: `SealedDecryptionError` is raised explicitly (not caught silently)
- R015 advanced to `validated *(M002/S03)*` in `REQUIREMENTS.md`
- 21 pre-existing `test_sealed.py` tests remain green; full 173-test suite + new tests pass

## Proof Level

- This slice proves: integration — `SealedStore` wired into the miner runtime path; measurement-change failure exercised end-to-end through `MockNodeProtocol`
- Real runtime required: no — in-memory RocksDB + trio, same as all prior slices
- Human/UAT required: no

## Verification

```bash
# New integration tests
python3 -m pytest tests/tee/test_sealed_integration.py -v
# → 3/3 PASSED

# Pre-existing sealed unit tests (must not regress)
python3 -m pytest tests/tee/test_sealed.py -v
# → 21/21 PASSED

# Mock node integration (must not regress after mock.py changes)
python3 -m pytest tests/test_mock_node.py -v
# → all PASSED

# Full suite
python3 -m pytest tests/ --ignore=tests/hypertensor -q
# → all PASSED (≥176 tests)
```

## Observability / Diagnostics

- Runtime signals: `[SealedStore] Sealed key=epoch_stats:…` (DEBUG) on every `miner_loop` seal call; `[SealedStore] Unsealed key=…` (DEBUG) on cache-hit unseal; `[MockMiner] sealed epoch_stats epoch=<n>` (INFO) after sealing
- Inspection surfaces: `db.nmap_get("sealed", "epoch_stats:{peer_id}:{epoch}")` — returns raw encrypted blob; non-None = sealed, None = not sealed; opaque bytes confirm key derivation is active
- Failure visibility: `SealedDecryptionError` carries `key=…` and `measurement mismatch or corruption` in message — stable prefix for log filtering; integration test asserts on `pytest.raises(SealedDecryptionError)`, not message text
- Redaction constraints: sealed blobs are opaque ciphertext — no secrets in logs; `_seal_key` is never logged (only `measurement[:16]` in DEBUG line from `SealedStore.__init__`)

## Integration Closure

- Upstream surfaces consumed: `subnet/tee/sealed/store.py` (`SealedStore`, `SealedDecryptionError`), `subnet/tee/backends/mock.py` (`MOCK_MEASUREMENT`, `MOCK_DEV_KEY`), `subnet/utils/db/database.py` (`RocksDB`), `subnet/node/mock.py` (`MockNodeProtocol.register_handlers` + `miner_loop`)
- New wiring introduced in this slice: `MockNodeProtocol._sealed_store` attribute initialised in `register_handlers`; `miner_loop` seals `epoch_stats` JSON after generating the work record
- What remains before the milestone is truly usable end-to-end: S04 (Gramine manifest + reproducible build) — ties S01–S03 into a runnable `gramine-direct python run_node.py` invocation with a pinned measurement

## Tasks

- [x] **T01: Write failing integration tests for SealedStore-in-miner** `est:20m`
  - Why: Establishes the acceptance contract before any implementation. Tests must fail with `AttributeError` or `ImportError` until T02 wires `SealedStore` into `MockNodeProtocol`. The failing tests prevent silent success if wiring is omitted.
  - Files: `tests/tee/test_sealed_integration.py`
  - Do: Create `tests/tee/test_sealed_integration.py` with three test cases using the same `db` / `_make_proto` pattern from `tests/test_mock_node.py`. Import `SealedStore`, `SealedDecryptionError` from `subnet.tee.sealed` and `MOCK_MEASUREMENT` from `subnet.tee.backends.mock`. Import `_sealed_store` attribute reference from `MockNodeProtocol` — this will fail at runtime until T02.
    - **Test 1 `test_miner_seals_epoch_stats`**: run `register_handlers` + `miner_loop(epoch=42000)` on a miner; assert `miner._sealed_store.exists(f"epoch_stats:{PEER_A}:42000")` is `True`; unseal and JSON-decode the value; assert `"n"` and `"parity"` keys are present.
    - **Test 2 `test_miner_unseal_round_trip`**: run `miner_loop` twice on the same epoch; assert the second call returns `success=True` and that the sealed store still has the key (idempotent seal). Assert the unsealed JSON matches what the first call would have produced by round-tripping through the `_sealed_store`.
    - **Test 3 `test_different_measurement_raises_sealed_decryption_error`**: run `miner_loop(epoch=42000)` to seal data under `MOCK_MEASUREMENT`; construct a second `SealedStore` with `measurement="ff"*32` (alt measurement) on the *same* `db`; assert `pytest.raises(SealedDecryptionError)` when calling `unseal(f"epoch_stats:{PEER_A}:42000")` on the alt store — this is the core "different binary = different key" property.
    - Place all DB teardown (`db.store.close()`) in the fixture, matching the pattern in `test_sealed.py`.
    - Confirm `pytest --collect-only tests/tee/test_sealed_integration.py` succeeds (no import errors at collect time — put runtime imports inside test functions if needed).
  - Verify: `python3 -m pytest tests/tee/test_sealed_integration.py -v` — 3 tests collected; at least Test 1 and Test 3 fail with `AttributeError: 'MockNodeProtocol' object has no attribute '_sealed_store'` (or similar). Test 2 may also fail. All three must not pass yet.
  - Done when: `pytest --collect-only tests/tee/test_sealed_integration.py` shows 3 tests; running them produces failures (not collection errors or syntax errors); `test_sealed.py` 21 tests still pass.

- [x] **T02: Wire SealedStore into MockNodeProtocol** `est:25m`
  - Why: Makes the integration tests pass by adding `_sealed_store` to `register_handlers` and sealing `epoch_stats` JSON in `miner_loop`. This is the main S03 implementation task — the "different binary = different key" property becomes exercisable through the miner runtime path.
  - Files: `subnet/node/mock.py`
  - Do:
    1. In `register_handlers`, after setting up `self._backend` and `self._tee_config`, import and instantiate `SealedStore`: `from subnet.tee.sealed import SealedStore; from subnet.tee.backends.mock import MOCK_MEASUREMENT, MOCK_DEV_KEY`. Create `self._sealed_store = SealedStore(db=self.db, measurement=MOCK_MEASUREMENT, mock_key=MOCK_DEV_KEY)`. Use `MOCK_DEV_KEY` (not `_MOCK_KEY`) — `MOCK_DEV_KEY` is the canonical import from `subnet.tee.backends.mock`; they are the same bytes but the named import is the documented API.
    2. In `miner_loop`, after the work record dict `record` is created (step 4 of the existing loop — after `n` and `parity` are set, before `OutputEnvelope.create`), seal the epoch stats: construct `seal_key = f"epoch_stats:{self.peer_id}:{epoch}"` and call `self._sealed_store.seal_json(seal_key, {"n": n, "parity": parity})`. Add an INFO log: `logger.info("[MockMiner] sealed epoch_stats epoch=%d peer=%s", epoch, self.peer_id[:16])`.
    3. The seal call goes *after* the tamper injection block (so tampered data is what gets sealed, preserving demo fidelity). This means the sealed stats reflect exactly what was published — correct or tampered.
    4. Do NOT add an unseal-on-retry path in this slice — the integration test only needs `exists` + `unseal` on the test side (not a miner retry loop). Keep the miner_loop change minimal and focused.
    5. Verify no existing `test_mock_node.py` tests are affected — the new `seal_json` call has no externally visible effect on the existing DHT records or validator results.
  - Verify:
    ```bash
    python3 -m pytest tests/tee/test_sealed_integration.py -v   # → 3/3 PASSED
    python3 -m pytest tests/test_mock_node.py -v                 # → all PASSED (no regressions)
    python3 -m pytest tests/tee/test_sealed.py -v               # → 21/21 PASSED
    python3 -m pytest tests/ --ignore=tests/hypertensor -q       # → all PASSED
    ```
  - Done when: 3 integration tests pass; 21 sealed unit tests pass; `test_mock_node.py` shows no regressions; full suite clean.

- [x] **T03: Slice close — requirements, summary, UAT, roadmap** `est:20m`
  - Why: Closes the slice with required GSD artifacts: marks R015 validated, records what was built, UAT evidence, updates roadmap and STATE.
  - Files: `REQUIREMENTS.md`, `.gsd/milestones/M002/M002-ROADMAP.md`, `.gsd/milestones/M002/slices/S03/S03-SUMMARY.md`, `.gsd/milestones/M002/slices/S03/S03-UAT.md`, `.gsd/STATE.md`
  - Do:
    1. Update `REQUIREMENTS.md` R015 status from `validated *(M002)*` to `validated *(M002/S03)*`.
    2. Mark `M002-ROADMAP.md` S03 checkbox `[x]`.
    3. Write `S03-SUMMARY.md` (YAML frontmatter + narrative) following S02-SUMMARY.md structure — record what was built, what tests pass, requirements validated, deviations, known limitations, forward intelligence for S04.
    4. Write `S03-UAT.md` capturing the three integration test results and the full-suite pass count as evidence.
    5. Update `STATE.md` to reflect S03 complete, new test count, and S04 pending.
    6. Commit: `feat(S03): sealed storage — SealedStore wired into MockNodeProtocol; R015 validated`
  - Verify: `python3 -m pytest tests/ --ignore=tests/hypertensor -q` — all pass (≥176); `M002-ROADMAP.md` shows `[x] **S03`; `REQUIREMENTS.md` shows R015 `validated *(M002/S03)*`; `S03-SUMMARY.md` exists and has YAML frontmatter.
  - Done when: All slice artifacts written; roadmap and requirements updated; commit made; full suite green.

## Files Likely Touched

- `tests/tee/test_sealed_integration.py` — new: 3 integration tests for SealedStore-in-miner
- `subnet/node/mock.py` — add `self._sealed_store` in `register_handlers`; seal epoch stats in `miner_loop`
- `REQUIREMENTS.md` — R015 status update
- `.gsd/milestones/M002/M002-ROADMAP.md` — mark S03 `[x]`
- `.gsd/milestones/M002/slices/S03/S03-SUMMARY.md` — new slice summary
- `.gsd/milestones/M002/slices/S03/S03-UAT.md` — new UAT evidence
- `.gsd/STATE.md` — updated status
