# S04: Gramine Manifest + Reproducible Build

**Goal:** Fix the manifest's sealed-storage mismatch, write a CI-runnable manifest validation test, add a reproducible build script, and close R016 — so `gramine.manifest.template` is correct, testable, and buildable without manual steps.
**Demo:** `python3 -m pytest tests/tee/test_gramine_manifest.py -v` passes (pure Python, no Gramine installed); `bash -n scripts/build-gramine.sh` validates the build script; `gramine.manifest.template` no longer references Gramine Protected FS for `/sealed` (the SealedStore path mismatch is fixed); R016 is `validated *(M002/S04)*`.

## Must-Haves

- `sgx.encrypted_files` pointing to `/var/lib/hypertensor/sealed/` is removed from the manifest (SealedStore uses RocksDB nmap at `/data`, not Gramine Protected FS)
- The `type = "encrypted"` `/sealed` mount is removed and replaced with a comment explaining application-level sealing via SealedStore AES-GCM
- `tests/tee/test_gramine_manifest.py` passes in CI (no Gramine installation required)
- `scripts/build-gramine.sh` automates the 3-step Gramine build + MRENCLAVE extraction
- `GRAMINE.md` documents `--base_path /data` for Gramine-mode execution
- R016 marked `validated *(M002/S04)*`

## Proof Level

- This slice proves: contract + operational
- Real runtime required: no (manifest tests are pure Python; build script checked with bash -n)
- Human/UAT required: no

## Verification

- `python3 -m pytest tests/tee/test_gramine_manifest.py -v` — all tests pass (pure Python, no Gramine needed)
- `bash -n scripts/build-gramine.sh` — script syntax valid
- `python3 -m pytest tests/ --ignore=tests/hypertensor -q` — full suite passes with no regressions
- **Failure-path diagnostic:** On test failure, inspect the failing assertion message (test names are self-documenting: `test_no_sealed_encrypted_mount` names the exact offending text). Confirm directly with `grep -n 'type = "encrypted"' gramine.manifest.template` (must return no output) and `grep -n 'encrypted_files' gramine.manifest.template` (all lines must start with `#`). If `test_gramine_direct_smoke` fails when Gramine is installed, run `gramine-manifest -Dlog_level=warning -Darch_libdir=/lib/x86_64-linux-gnu gramine.manifest.template` directly and read stderr for the manifest parse error.

## Observability / Diagnostics

- Runtime signals: no new runtime signals (manifest is a static file; tests are pure Python assertions)
- Inspection surfaces: `tests/tee/test_gramine_manifest.py` — canonical check that manifest is syntactically correct and covers required keys; run anywhere
- Failure visibility: test failure message names the missing/present key; grep the manifest template directly to confirm
- Redaction constraints: none

## Integration Closure

- Upstream surfaces consumed: `gramine.manifest.template`, `GRAMINE.md`, `subnet/tee/sealed/store.py` (confirms RocksDB nmap model), `subnet/cli/run_node.py` (confirms `--base_path` arg)
- New wiring introduced in this slice: `scripts/build-gramine.sh` (automates manifest → signed manifest → MRENCLAVE); `.gitignore` entries for generated Gramine artifacts
- What remains before the milestone is truly usable end-to-end: nothing — S04 is the final M002 slice; after it, M002 is complete

## Tasks

- [x] **T01: Fix manifest sealed-storage mismatch and write validation test** `est:45m`
  - Why: The manifest declares `/sealed` as a Gramine Protected FS mount and `sgx.encrypted_files` pointing to `/var/lib/hypertensor/sealed/` — but SealedStore uses application-level AES-GCM in the shared RocksDB nmap column at `/data`, not Gramine's Protected FS. This is a dead / incorrect entry that would silently confuse operators. The validation test makes the correct manifest state machine-checkable in CI.
  - Files: `gramine.manifest.template`, `GRAMINE.md`, `tests/tee/test_gramine_manifest.py`
  - Do:
    1. In `gramine.manifest.template`, remove the `{ path = "/sealed", uri = "file:/var/lib/hypertensor/sealed", type = "encrypted", key_name = "_sgx_mrenclave" }` mount entry from `fs.mounts`
    2. Add a comment block in its place explaining: SealedStore uses application-level AES-GCM keyed by `HKDF(measurement, dev_key)`, stored in the RocksDB nmap `"sealed"` column at `/data`. Gramine's Protected FS (`type = "encrypted"`) is not used — mixing both would double-encrypt. The `/data` allowed_files entry already covers RocksDB access.
    3. Remove `sgx.encrypted_files = ["file:/var/lib/hypertensor/sealed/"]` from the manifest (or replace with a commented-out block explaining the same reasoning)
    4. In `GRAMINE.md`, update both run command examples (direct + SGX) to include `--base_path /data` as a required flag; update the "Sealed storage" section to explain that SealedStore (not Gramine Protected FS) provides sealing semantics, and remove the `mkdir /var/lib/hypertensor/sealed` setup step (no longer needed)
    5. Write `tests/tee/test_gramine_manifest.py` with the following tests (use text search / `re` on the raw template file — it is a Jinja2 template, NOT valid TOML):
       - `test_required_sgx_fields`: asserts `sgx.remote_attestation`, `sgx.enclave_size`, `sgx.max_threads` are present
       - `test_loader_entrypoint_present`: asserts `loader.entrypoint` is present
       - `test_required_env_passthroughs`: asserts `MOCK_TEE`, `TEE_BACKEND`, `EXPECTED_MEASUREMENT`, `MIN_TEE_SCORE`, `TCB_POLICY` are all configured as passthrough
       - `test_data_mount_present`: asserts `/data` appears in `fs.mounts` (RocksDB path)
       - `test_no_sealed_encrypted_mount`: asserts `type = "encrypted"` does NOT appear in the manifest (Gramine Protected FS removed)
       - `test_no_encrypted_files_sealed_path`: asserts `sgx.encrypted_files` does NOT reference `/var/lib/hypertensor/sealed` (mismatch removed)
       - `test_trusted_files_cover_subnet`: asserts `/app/subnet/` appears in `sgx.trusted_files`
       - `test_gramine_direct_smoke` (conditional): if `shutil.which("gramine-manifest")` returns a path, run `gramine-manifest -Dlog_level=warning -Darch_libdir=/lib/x86_64-linux-gnu gramine.manifest.template` and assert exit code 0; skip automatically if Gramine is not installed
  - Verify: `python3 -m pytest tests/tee/test_gramine_manifest.py -v`
  - Done when: 7+ tests pass (8 if Gramine installed); manifest no longer contains `type = "encrypted"` for `/sealed` or `sgx.encrypted_files` pointing to the sealed dir; `GRAMINE.md` includes `--base_path /data` in run commands

- [x] **T02: Add reproducible build script and .gitignore entries** `est:20m`
  - Why: The three manual build steps in GRAMINE.md need to be a single automated script so the build is reproducible and operator-runnable without transcription errors. Generated Gramine artifacts must be `.gitignore`d so they never accidentally get committed.
  - Files: `scripts/build-gramine.sh`, `.gitignore`
  - Do:
    1. Create `scripts/build-gramine.sh` (chmod +x). The script should:
       - Accept `ARCH_LIBDIR` (default: `/lib/x86_64-linux-gnu`) and `LOG_LEVEL` (default: `warning`) as env vars
       - Step 1: `gramine-manifest -Dlog_level=$LOG_LEVEL -Darch_libdir=$ARCH_LIBDIR gramine.manifest.template > gramine.manifest`
       - Step 2: `gramine-sgx-sign --manifest gramine.manifest --output gramine.manifest.sgx`
       - Step 3: `gramine-sgx-get-token --output gramine.token --sig gramine.manifest.sgx`
       - Step 4: Extract and print MRENCLAVE using `gramine-sgx-sigstruct-view --output-format=json gramine.manifest.sgx | python3 -c "import sys, json; d=json.load(sys.stdin); print(d.get('enclave_hash', d.get('mr_enclave', 'not_found')))"`
       - Add `set -euo pipefail` at the top
       - Add a usage block at the top with comments for each step
       - Print a summary line at the end: `echo "[gramine-build] MRENCLAVE: $MRENCLAVE"` and `echo "[gramine-build] Done. Set EXPECTED_MEASUREMENT=$MRENCLAVE on validators."`
    2. Add `.gitignore` entries (append to existing `.gitignore`):
       ```
       # Gramine generated artifacts
       gramine.manifest
       gramine.manifest.sgx
       gramine.token
       ```
  - Verify: `bash -n scripts/build-gramine.sh` (syntax check, no Gramine needed); confirm `.gitignore` contains the three entries
  - Done when: `bash -n scripts/build-gramine.sh` exits 0; `.gitignore` contains `gramine.manifest`, `gramine.manifest.sgx`, `gramine.token` entries; script has `set -euo pipefail`, accepts `ARCH_LIBDIR`/`LOG_LEVEL` env vars, prints MRENCLAVE at the end

- [x] **T03: Slice close — validate R016, write summary, commit** `est:20m`
  - Why: Complete the slice by marking R016 validated (the manifest test + build script + GRAMINE.md docs together satisfy the requirement), writing the S04-SUMMARY, and committing all changes.
  - Files: `.gsd/REQUIREMENTS.md`, `.gsd/milestones/M002/M002-ROADMAP.md`, `.gsd/milestones/M002/slices/S04/S04-SUMMARY.md`, `.gsd/STATE.md`
  - Do:
    1. Run full test suite: `python3 -m pytest tests/ --ignore=tests/hypertensor -q` — confirm all pass including `test_gramine_manifest.py`
    2. In `.gsd/REQUIREMENTS.md`, update R016 status line to `validated *(M002/S04)*`
    3. In `.gsd/milestones/M002/M002-ROADMAP.md`, mark S04 `[x]`
    4. Write `S04-SUMMARY.md` covering: what was done (3 artifacts), what was fixed (sealed mismatch), what tests prove (manifest correctness, no Gramine needed), what R016 validation means, forward intelligence for future agents
    5. Commit: `git add -A && git commit -m "feat(tee): S04 Gramine manifest + reproducible build"`
    6. Update `.gsd/STATE.md`: set Active Slice to none / M002 complete, note M002 milestone complete
  - Verify: `python3 -m pytest tests/ --ignore=tests/hypertensor -q` — all pass; `git log --oneline -1` shows the commit
  - Done when: full suite green; R016 shows `validated *(M002/S04)*`; S04 marked `[x]` in roadmap; commit pushed

## Files Likely Touched

- `gramine.manifest.template` — remove `/sealed` encrypted mount and `sgx.encrypted_files`; add explanatory comments
- `GRAMINE.md` — add `--base_path /data` to run commands; update sealed storage section
- `tests/tee/test_gramine_manifest.py` — new file: 7–8 tests for manifest correctness
- `scripts/build-gramine.sh` — new file: reproducible 3-step build + MRENCLAVE extraction
- `.gitignore` — add 3 Gramine generated artifact entries
- `.gsd/REQUIREMENTS.md` — R016 → validated
- `.gsd/milestones/M002/M002-ROADMAP.md` — S04 `[x]`
- `.gsd/milestones/M002/slices/S04/S04-SUMMARY.md` — new file: slice summary
- `.gsd/STATE.md` — update active slice / milestone state
