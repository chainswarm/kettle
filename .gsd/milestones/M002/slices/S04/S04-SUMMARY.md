---
id: S04
parent: M002
milestone: M002
provides:
  - gramine.manifest.template — fixed: removed Gramine Protected FS /sealed mount and dead sgx.encrypted_files entry; added explanatory comments documenting SealedStore AES-GCM model; correct sealed storage path is /data (RocksDB)
  - tests/tee/test_gramine_manifest.py — 8-test CI-runnable manifest validation suite (pure Python, no Gramine installed needed); covers sgx.remote_attestation, allowed_files, thread_num, sgx.debug, /data mount, /tmp mount, python3 entry, and absence of dead Protected FS entries
  - scripts/build-gramine.sh — reproducible 4-step Gramine build + MRENCLAVE extraction script (manifest → sign → token → extract); version-robust MRENCLAVE extraction handles both 'enclave_hash' and 'mr_enclave' key names
  - GRAMINE.md — updated: --base_path /data in run commands; sealed storage section corrected to describe SealedStore AES-GCM model rather than Gramine Protected FS
requires:
  - slice: S01
    note: RA-TLS config (sgx.remote_attestation = "dcap") is pinned in the manifest
  - slice: S03
    note: SealedStore uses RocksDB at /data — this is the correct sealed storage path referenced in the manifest
affects:
  - none downstream within M002 — this is the final slice
key_files:
  - gramine.manifest.template
  - tests/tee/test_gramine_manifest.py
  - scripts/build-gramine.sh
  - GRAMINE.md
key_decisions:
  - Used text search (not tomllib) for manifest tests — manifest is a Jinja2 template with {{...}} syntax, not valid TOML; tomllib would fail to parse it
  - test_no_sealed_encrypted_mount checks only uncommented lines — allows comments explaining the removal; grep pattern anchored to exclude lines starting with '#'
  - MRENCLAVE extraction uses python3 inline JSON parse checking both 'enclave_hash' and 'mr_enclave' keys — version-robust across Gramine releases without requiring different script versions
  - build-gramine.sh follows GRAMINE.md documented steps exactly — no deviations; operator tool, not CI tool
patterns_established:
  - Manifest validation tests are pure-Python text assertions on the raw .template file — no Gramine install needed; run anywhere with python3 -m pytest
  - Gramine build scripts verified with bash -n (syntax only) in CI — Gramine toolchain not required for CI syntax validation
  - Explicit gitignore entries for generated Gramine artifacts alongside existing glob — both *.manifest PyInstaller glob and specific gramine.manifest/gramine.manifest.sgx/gramine.token entries coexist
observability_surfaces:
  - python3 -m pytest tests/tee/test_gramine_manifest.py -v — canonical CI check; test names are self-documenting (test_no_sealed_encrypted_mount, test_has_dcap_attestation, etc.)
  - bash -n scripts/build-gramine.sh — syntax validation; passes with no output on success
  - grep -n 'type = "encrypted"' gramine.manifest.template — must return nothing (no uncommented encrypted mounts)
  - grep -n 'encrypted_files' gramine.manifest.template — all matching lines must start with '#' (comments only)
  - When run with Gramine installed: each step emits [gramine-build] Step N/4: ... to stdout; set -euo pipefail ensures non-zero exit on any failure
drill_down_paths:
  - .gsd/milestones/M002/slices/S04/tasks/T01-SUMMARY.md
  - .gsd/milestones/M002/slices/S04/tasks/T02-SUMMARY.md
duration: ~3 tasks (T01: manifest fix + test, T02: build script, T03: slice close)
verification_result: passed
completed_at: 2026-03-17
---

# S04: Gramine Manifest + Reproducible Build

**Fixed manifest's Gramine Protected FS mismatch, wrote 8-test CI-runnable manifest validation suite, added 4-step reproducible build script with MRENCLAVE extraction, corrected GRAMINE.md; R016 validated; 181/181 tests green.**

## What Happened

S04 corrected the manifest's sealed storage model and made the manifest validatable in CI across two implementation tasks:

**T01 — Manifest fix + validation tests:** The manifest incorrectly referenced Gramine Protected FS (an encrypted-file-system feature) for `/var/lib/hypertensor/sealed` via both a `type = "encrypted"` fs mount and an `sgx.encrypted_files` entry. SealedStore does not use Gramine Protected FS — it implements its own AES-GCM encryption on top of plain RocksDB at `/data`. Both dead entries were removed; explanatory comments were added documenting the SealedStore model. GRAMINE.md was updated to use `--base_path /data` in run commands. Eight CI-safe manifest validation tests were written in `tests/tee/test_gramine_manifest.py` (pure Python text assertions on the `.template` file — no Gramine install needed). 7 pass unconditionally; 1 (`test_gramine_direct_smoke`) skips in CI when Gramine is not installed.

**T02 — Reproducible build script:** Created `scripts/build-gramine.sh` — a 4-step executable script automating: manifest generation via `gramine-manifest`, signing via `gramine-sgx-sign`, token creation via `gramine-sgx-get-token`, and MRENCLAVE extraction via `gramine-sgx-sigstruct-view`. MRENCLAVE extraction uses an inline Python3 JSON parse that handles both `enclave_hash` and `mr_enclave` key names (version-robust across Gramine releases). Three Gramine artifact files (`gramine.manifest`, `gramine.manifest.sgx`, `gramine.token`) were added to `.gitignore` alongside the existing `*.manifest` glob.

**T03 — Slice close:** Ran full test suite (181 passed, 1 skipped — all green), updated R016 to `validated *(M002/S04)*`, marked S04 `[x]` in M002-ROADMAP.md (completing all 4 slices), wrote slice artifacts, updated STATE.md.

## Verification

```bash
# Full test suite — must show all green
python3 -m pytest tests/ --ignore=tests/hypertensor -q
# → 181 passed, 1 skipped

# S04-specific manifest validation suite
python3 -m pytest tests/tee/test_gramine_manifest.py -v
# → 7 passed, 1 skipped (test_gramine_direct_smoke skipped — Gramine not installed in CI)

# Build script syntax check
bash -n scripts/build-gramine.sh
# → no output (clean)

# Confirm manifest has no dead Protected FS entries
grep -n 'type = "encrypted"' gramine.manifest.template
# → no output (correct)
grep -n 'encrypted_files' gramine.manifest.template
# → all lines start with '#' (comments only)

# Confirm R016 validated
grep "R016" .gsd/REQUIREMENTS.md
# → contains "validated *(M002/S04)*"

# Confirm S04 complete in roadmap
grep "S04" .gsd/milestones/M002/M002-ROADMAP.md
# → shows [x]
```

## Requirements Validated

- **R016** — Gramine support (Python miner in TDX): manifest pins allowed syscalls, file paths, RA-TLS config (`sgx.remote_attestation = "dcap"`), and sealed storage path (`/data`). T01 fixed the sealed storage model (removed incorrect Gramine Protected FS entry; SealedStore AES-GCM at `/data` is correct). `test_gramine_manifest.py` makes this machine-checkable in CI.

## Known Limitations

1. **Python version pin:** `gramine.manifest.template` references `/usr/lib/python3.12/` — if the deployment system runs Python 3.11, this path will be wrong. The build script could derive the path dynamically (`python3 -c "import sys; print(sys.prefix)"`). Currently a manual concern requiring operator attention on deployment.

2. **SealedStore dev_key provisioning:** `SealedStore` accepts `dev_key: bytes`. Tests use `MOCK_DEV_KEY`. For real TDX deployments, `dev_key` comes from a provisioning step outside the enclave. Provisioning mechanism is out of scope for M002.

3. **Build script requires Gramine 1.6+ on host:** `scripts/build-gramine.sh` is an operator tool, not a CI artifact. It cannot run in standard CI — use `bash -n` for syntax validation only.

4. **gramine-direct smoke test skipped in CI:** `test_gramine_direct_smoke` skips when Gramine is not installed. It provides local-dev validation when Gramine is present. CI relies on the 7 pure-Python manifest assertion tests instead.

## Forward Intelligence

For any agent working on Gramine integration, real TDX deployment, or manifest evolution:

- **Manifest tests are the source of truth for correctness.** Before touching `gramine.manifest.template`, run `python3 -m pytest tests/tee/test_gramine_manifest.py -v`. Test names are self-documenting: failure in `test_has_dcap_attestation` means `sgx.remote_attestation = "dcap"` is missing; `test_no_sealed_encrypted_mount` means a `type = "encrypted"` mount was added back.

- **SealedStore does NOT use Gramine Protected FS.** This was the core mismatch fixed in T01. SealedStore is pure-Python AES-GCM encryption on top of RocksDB. The sealed data lives at `/data` (the RocksDB path), not in a Gramine-managed encrypted filesystem. Do not add `sgx.encrypted_files` or `type = "encrypted"` mounts back to the manifest.

- **The `gramine-sgx-sigstruct-view` JSON output format varies by Gramine version.** The build script checks both `enclave_hash` and `mr_enclave` key names. If a future Gramine release changes the key name again, add it to the Python3 inline list in `scripts/build-gramine.sh` Step 4.

- **Python path in manifest must match deployment host.** If the CI/build environment uses a different Python minor version than 3.12, update the manifest's `/usr/lib/python3.12/` references. Consider making the path dynamic via the build script: `PYTHON_LIB=$(python3 -c "import sysconfig; print(sysconfig.get_path('stdlib'))")`.

- **Measurement changes on any dependency change.** If Python stdlib, miner code, or any file in the `sgx.trusted_files` list changes, MRENCLAVE changes. `scripts/build-gramine.sh` re-derives MRENCLAVE on each run — use it after dependency updates to get the new hash for pinning in `GRAMINE.md`.
