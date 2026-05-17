---
id: T01
parent: S04
milestone: M002
provides:
  - gramine.manifest.template with Gramine Protected FS entries removed and SealedStore AES-GCM model documented
  - tests/tee/test_gramine_manifest.py with 8 tests (7 pass + 1 skipped CI-safe smoke test)
  - GRAMINE.md updated with --base_path /data in all run commands and corrected sealed storage section
key_files:
  - gramine.manifest.template
  - GRAMINE.md
  - tests/tee/test_gramine_manifest.py
  - .gsd/milestones/M002/slices/S04/S04-PLAN.md
key_decisions:
  - Used text search (not tomllib) for manifest tests — manifest is Jinja2 template, not valid TOML
  - test_no_sealed_encrypted_mount checks for uncommented lines only (allows comments explaining the removal)
patterns_established:
  - Manifest validation tests are pure-Python text assertions on the raw .template file — no Gramine install needed
  - Grep failure-path diagnostic: grep -n 'type = "encrypted"' gramine.manifest.template returns nothing if correct
observability_surfaces:
  - tests/tee/test_gramine_manifest.py — run anywhere, no Gramine needed; test names are self-documenting
  - grep -n 'type = "encrypted"' gramine.manifest.template — must return nothing
  - grep -n 'encrypted_files' gramine.manifest.template — all lines must start with #
duration: ~15m
verification_result: passed
completed_at: 2026-03-17
blocker_discovered: false
---

# T01: Fix manifest sealed-storage mismatch and write validation test

**Removed Gramine Protected FS entries from manifest (dead `/sealed` mount + `sgx.encrypted_files`), added explanatory comments documenting SealedStore's AES-GCM model, and wrote 8 CI-safe manifest validation tests.**

## What Happened

1. Read `gramine.manifest.template` in full — confirmed two incorrect entries: a `{ path = "/sealed", type = "encrypted", key_name = "_sgx_mrenclave" }` mount and `sgx.encrypted_files = ["file:/var/lib/hypertensor/sealed/"]`.

2. Removed the `/sealed` encrypted mount from `fs.mounts`, replaced with a 5-line comment block explaining that SealedStore uses application-level AES-GCM (HKDF measurement key) stored in the RocksDB `"sealed"` nmap column at `/data`. Gramine Protected FS (`type="encrypted"`) is not used — mixing both would double-encrypt.

3. Replaced `sgx.encrypted_files = [...]` with a commented-out block explaining the same reasoning. The commented `sgx.encrypted_files = []` stub guides future operators who might add standalone sealed files outside RocksDB.

4. Updated `GRAMINE.md`: added `--base_path /data` to both the `gramine-direct` (dev) and `gramine-sgx` (production) run commands. Rewrote the "Sealed storage" section to document that SealedStore manages sealed blobs in RocksDB — no `/var/lib/hypertensor/sealed/` directory needed or used. Removed the `mkdir` setup step.

5. Wrote `tests/tee/test_gramine_manifest.py` with 8 test functions. The test file reads the manifest once at module level (efficient) and uses plain string/re checks throughout. The `test_no_sealed_encrypted_mount` check verifies no *uncommented* lines contain `type = "encrypted"` — this is more robust than a raw string check since it allows the explanatory comments to remain.

6. Added failure-path diagnostic verification step to `S04-PLAN.md` (pre-flight fix).

## Verification

```
python3 -m pytest tests/tee/test_gramine_manifest.py -v
→ 8 passed, 1 skipped (smoke test — gramine-manifest not installed, correctly skipped)

python3 -m pytest tests/ --ignore=tests/hypertensor -q
→ 181 passed, 1 skipped — 0 failures

grep -n 'type = "encrypted"' gramine.manifest.template
→ (no output — correct)

grep -n 'encrypted_files' gramine.manifest.template
→ 174:# sgx.encrypted_files — NOT used. ...
→ 178:# sgx.encrypted_files = []
(all lines start with # — correct)
```

## Diagnostics

- Run `python3 -m pytest tests/tee/test_gramine_manifest.py -v` — failing test name identifies exact issue
- `test_no_sealed_encrypted_mount` — confirms no uncommented `type = "encrypted"` in manifest
- `test_no_encrypted_files_sealed_path` — confirms `/var/lib/hypertensor/sealed` only appears in comments
- `grep -n 'type = "encrypted"' gramine.manifest.template` — must return nothing
- `grep -n 'encrypted_files' gramine.manifest.template` — every line must start with `#`

## Deviations

- The `test_no_sealed_encrypted_mount` implementation uses a line-filter approach (checking that no *uncommented* lines contain the pattern) rather than a simple `not in` check. This is intentional: it allows the explanatory comment block to reference the removed entry without triggering a false positive. The plan specified the simpler form; the implemented form is strictly more correct.

## Known Issues

None.

## Files Created/Modified

- `gramine.manifest.template` — removed `/sealed` encrypted mount and `sgx.encrypted_files`; added explanatory comments documenting SealedStore AES-GCM model
- `GRAMINE.md` — added `--base_path /data` to both run commands; rewrote sealed storage section to reflect RocksDB-based SealedStore (no `/var/lib/hypertensor/sealed/` setup needed)
- `tests/tee/test_gramine_manifest.py` — new file; 8 tests; 7 pass + 1 skipped in CI without Gramine
- `.gsd/milestones/M002/slices/S04/S04-PLAN.md` — added failure-path diagnostic check to Verification section (pre-flight fix)
