---
estimated_steps: 8
estimated_files: 3
---

# T01: Fix manifest sealed-storage mismatch and write validation test

**Slice:** S04 — Gramine Manifest + Reproducible Build
**Milestone:** M002

## Description

The manifest (`gramine.manifest.template`) has two incorrect entries that must be removed:
1. A `{ path = "/sealed", ..., type = "encrypted", key_name = "_sgx_mrenclave" }` mount in `fs.mounts` — this enables Gramine's Protected FS for `/sealed`, but `SealedStore` stores sealed blobs in the shared RocksDB nmap `"sealed"` column at `/data`, not in `/var/lib/hypertensor/sealed/`.
2. `sgx.encrypted_files = ["file:/var/lib/hypertensor/sealed/"]` — a dead entry pointing at a path that doesn't exist and that SealedStore doesn't use.

Leaving both in would: (a) confuse operators into creating a `/var/lib/hypertensor/sealed/` directory that does nothing, (b) make Gramine attempt to use Protected FS double-encryption on a path that already has application-level AES-GCM encryption.

This task also writes `tests/tee/test_gramine_manifest.py` — a pure-Python validation suite that runs in CI without Gramine installed. The tests assert required keys are present AND that the incorrect entries are absent (proving the fix is machine-checkable).

The manifest is a Jinja2 template — it is **not** valid TOML. Use text search / `re` on the raw file, not `tomllib`.

## Steps

1. **Read `gramine.manifest.template`** in full to locate the exact text of the two incorrect entries before editing.

2. **Fix `fs.mounts` in `gramine.manifest.template`:**
   - Remove the entire mount entry: `{ path = "/sealed", uri = "file:/var/lib/hypertensor/sealed", type = "encrypted", key_name = "_sgx_mrenclave" }`
   - Replace with a multi-line comment block:
     ```
     # NOTE: SealedStore (subnet/tee/sealed/store.py) uses application-level AES-GCM
     # encryption keyed by HKDF(measurement, dev_key) — see D008. Sealed blobs are
     # stored in the RocksDB "sealed" nmap column at /data (mounted below as allowed_files).
     # Gramine's Protected FS (type="encrypted") is NOT used here: mixing both would
     # double-encrypt and create a separate file path that SealedStore never writes.
     ```

3. **Remove `sgx.encrypted_files` from `gramine.manifest.template`:**
   - Find `sgx.encrypted_files = [...]` block
   - Replace with a commented-out version explaining the same reasoning:
     ```
     # sgx.encrypted_files — NOT used. SealedStore performs application-level sealing
     # (AES-GCM + HKDF measurement key) inside the Python process. The RocksDB at /data
     # is listed under sgx.allowed_files; Gramine does not need to re-encrypt it.
     # If you add standalone sealed files outside RocksDB, add their paths here.
     # sgx.encrypted_files = []
     ```

4. **Update `GRAMINE.md`:**
   - In the "Development mode" run command, add `--base_path /data` to the `gramine-direct` invocation (after `--no_blockchain_rpc` or before `--private_key_path`)
   - In the "Production mode" run command (step 4), add `--base_path /data` likewise
   - Update the "Sealed storage" section: change the description to explain that SealedStore (not Gramine Protected FS) provides sealed storage; remove the `mkdir /var/lib/hypertensor/sealed` setup step; document that sealed blobs live in the RocksDB at `--base_path` under the `"sealed"` column

5. **Write `tests/tee/test_gramine_manifest.py`.**

   The test file should:
   - Import `re`, `shutil`, `subprocess`, `pathlib.Path` at module level
   - Define `MANIFEST_PATH = Path(__file__).parent.parent.parent / "gramine.manifest.template"` (3 levels up from tests/tee/)
   - Define a module-level fixture `MANIFEST_TEXT = MANIFEST_PATH.read_text()` (read once)
   - Write 8 test functions:

   ```python
   def test_manifest_file_exists():
       assert MANIFEST_PATH.exists(), f"gramine.manifest.template not found at {MANIFEST_PATH}"

   def test_required_sgx_fields():
       for key in ["sgx.remote_attestation", "sgx.enclave_size", "sgx.max_threads"]:
           assert key in MANIFEST_TEXT, f"Missing required SGX field: {key}"

   def test_loader_entrypoint_present():
       assert "loader.entrypoint" in MANIFEST_TEXT

   def test_required_env_passthroughs():
       for var in ["MOCK_TEE", "TEE_BACKEND", "EXPECTED_MEASUREMENT", "MIN_TEE_SCORE", "TCB_POLICY"]:
           assert var in MANIFEST_TEXT, f"Missing env passthrough: {var}"

   def test_data_mount_present():
       # /data is the RocksDB path; must be in fs.mounts
       assert '"/data"' in MANIFEST_TEXT or "'/data'" in MANIFEST_TEXT or \
              'path = "/data"' in MANIFEST_TEXT, \
              "/data mount missing from fs.mounts"

   def test_no_sealed_encrypted_mount():
       # Gramine Protected FS for /sealed must be removed — SealedStore uses RocksDB nmap
       assert 'type = "encrypted"' not in MANIFEST_TEXT, \
           'type = "encrypted" found in manifest — Gramine Protected FS conflicts with SealedStore AES-GCM'

   def test_no_encrypted_files_sealed_path():
       # sgx.encrypted_files must not reference the sealed dir (dead entry removed)
       assert "/var/lib/hypertensor/sealed" not in MANIFEST_TEXT or \
              all(line.strip().startswith("#") 
                  for line in MANIFEST_TEXT.splitlines() 
                  if "/var/lib/hypertensor/sealed" in line), \
           "Active (uncommented) sgx.encrypted_files sealed path found — must be commented out"

   def test_trusted_files_cover_subnet():
       assert "/app/subnet/" in MANIFEST_TEXT, "sgx.trusted_files missing /app/subnet/ — subnet code must be measured"

   @pytest.mark.skipif(
       shutil.which("gramine-manifest") is None,
       reason="gramine-manifest not installed — skipping live manifest parse"
   )
   def test_gramine_direct_smoke(tmp_path):
       import subprocess, shutil
       result = subprocess.run(
           ["gramine-manifest",
            "-Dlog_level=warning",
            "-Darch_libdir=/lib/x86_64-linux-gnu",
            str(MANIFEST_PATH)],
           capture_output=True, text=True, cwd=str(MANIFEST_PATH.parent)
       )
       assert result.returncode == 0, f"gramine-manifest failed:\n{result.stderr}"
   ```

   Remember to add `import pytest` at the top.

6. **Run the tests** to confirm they pass:
   ```bash
   python3 -m pytest tests/tee/test_gramine_manifest.py -v
   ```
   All 8 tests should pass (the smoke test will be skipped if Gramine is not installed).

7. **Run the full suite** to confirm no regressions:
   ```bash
   python3 -m pytest tests/ --ignore=tests/hypertensor -q
   ```

8. **Verify the manifest no longer contains the incorrect entries** by grepping:
   ```bash
   grep -n 'type = "encrypted"' gramine.manifest.template  # should return nothing
   grep -n 'encrypted_files' gramine.manifest.template       # should only show comments
   ```

## Must-Haves

- [ ] `gramine.manifest.template` contains no uncommented `type = "encrypted"` mount
- [ ] `gramine.manifest.template` `sgx.encrypted_files` section is commented out with explanation
- [ ] `/data` mount remains in `fs.mounts` (RocksDB access preserved)
- [ ] `GRAMINE.md` includes `--base_path /data` in both run command examples
- [ ] `tests/tee/test_gramine_manifest.py` exists with 8 test functions including `test_no_sealed_encrypted_mount` and `test_no_encrypted_files_sealed_path`
- [ ] All 8 tests pass (smoke test skipped if Gramine absent — that's OK)
- [ ] Full test suite passes with no regressions

## Verification

```bash
python3 -m pytest tests/tee/test_gramine_manifest.py -v
# → 7/8 PASSED (or 8/8 if gramine-manifest installed); 0 FAILED

python3 -m pytest tests/ --ignore=tests/hypertensor -q
# → all PASSED; no regressions

grep -n 'type = "encrypted"' gramine.manifest.template
# → (no output — entry removed)
```

## Observability Impact

- Signals added/changed: `tests/tee/test_gramine_manifest.py` is the ongoing health check for manifest correctness — run it in CI to catch manifest regressions
- How a future agent inspects this: `python3 -m pytest tests/tee/test_gramine_manifest.py -v` — test names are self-documenting
- Failure state exposed: test failure names the missing/present key; grep manifest directly to confirm

## Inputs

- `gramine.manifest.template` — current state: has `/sealed` Protected FS mount and `sgx.encrypted_files` pointing to `/var/lib/hypertensor/sealed/` — both must be removed
- `GRAMINE.md` — current state: run commands do not include `--base_path /data`; sealed storage section incorrectly references `/var/lib/hypertensor/sealed/` setup
- S03-SUMMARY.md Forward Intelligence: "SealedStore shares the node's existing db (RocksDB) using a dedicated 'sealed' nmap column family. There is no separate sealed-storage database or file — S04 Gramine manifest must account for this"
- S03-SUMMARY.md Known Limitations: "Single RocksDB instance. SealedStore shares the node's existing db (RocksDB) using a dedicated 'sealed' nmap column family."

## Expected Output

- `gramine.manifest.template` — no `type = "encrypted"` mount; `sgx.encrypted_files` commented out with explanation; comment explains SealedStore AES-GCM model
- `GRAMINE.md` — `--base_path /data` in both run commands; sealed storage section updated
- `tests/tee/test_gramine_manifest.py` — new file; 8 tests; 7+ pass in CI without Gramine
