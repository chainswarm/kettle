# S04: Gramine Manifest + Reproducible Build — Research

**Date:** 2026-03-16

## Summary

The core artifacts for S04 are substantially pre-built: `gramine.manifest.template` and `GRAMINE.md` already exist at the repo root. The manifest is detailed — it covers syscall allowlist, file mounts, env var passthrough, RA-TLS DCAP config, and sealed storage. However, there is a concrete mismatch between the manifest's storage model and how `SealedStore` actually works that must be fixed before R016 can be marked validated.

**Pre-existing gaps identified:**
1. **Sealed storage path mismatch.** The manifest declares `sgx.encrypted_files = ["file:/var/lib/hypertensor/sealed/"]` — a separate directory that does not exist. `SealedStore` stores sealed blobs in the shared RocksDB (`/data`) under the `"sealed"` nmap column, not in a separate path. The Gramine-level `encrypted_files` entry is therefore dead.
2. **No build script.** `GRAMINE.md` documents the three-command build process, but there is no `Makefile` target or script that automates it reproducibly (template → manifest → signed manifest → MRENCLAVE extraction).
3. **No CI-runnable manifest validation test.** The test suite has no check that the manifest is syntactically valid or covers required paths — a typo in the manifest is invisible until someone tries to run `gramine-manifest`.
4. **R016 not yet validated.** The requirement is `active`, with no coverage test.

## What Already Exists

| Artifact | Path | State |
|---|---|---|
| Manifest template | `gramine.manifest.template` | Exists; mostly correct; 1 fix needed |
| Build docs | `GRAMINE.md` | Exists; accurate |
| Gramine env var passthrough | in manifest | Complete: MOCK_TEE, TEE_BACKEND, EXPECTED_MEASUREMENT, etc. |
| Syscall allowlist | in manifest | Complete: Python + libp2p networking |
| RA-TLS SGX config | `sgx.remote_attestation = "dcap"` in manifest | Correct |
| File mounts | in manifest | `/lib`, `/usr`, `/app`, `/data`, `/tmp`, `/certs`, SGX devices | Complete |
| Trusted files | in manifest | Python stdlib + `subnet/` measured | Complete |
| GRAMINE.md | `GRAMINE.md` | Complete: direct + SGX steps, sealed dir setup, measurement extraction |

## The Sealed Storage Mismatch (Must Fix)

`SealedStore` (S01/S03) does **application-level** AES-GCM encryption keyed by `HKDF(measurement, dev_key)`. It stores ciphertext blobs in RocksDB (at `base_path`) under the `"sealed"` nmap column. It does not use a separate file path.

Gramine's `sgx.encrypted_files` is a **file-system-level** SGX sealing mechanism (Intel Protected FS). If the sealed data is in RocksDB, the correct approach is:
- Mount the RocksDB path (`/data`) as `allowed_files` — ✅ already done
- Remove `sgx.encrypted_files` pointing to `/var/lib/hypertensor/sealed/` — ❌ currently wrong
- Optionally keep `/var/lib/hypertensor/sealed/` as a future hook for a standalone sealed file (document clearly)

The fix: remove the `sgx.encrypted_files` entry (or comment it out with explanation) and add a manifest comment explaining that application-level sealing via `SealedStore` (AES-GCM + HKDF measurement key) is what provides sealed storage semantics, not Gramine's encrypted FS.

Alternatively: map `--base_path /data` in the manifest's entrypoint args so the RocksDB always lands at `/data` in Gramine mode, preventing random `/tmp/<n>` paths. This makes the mount deterministic.

## Build Script Gap

The three manual steps in `GRAMINE.md`:
```
gramine-manifest -D... gramine.manifest.template > gramine.manifest
gramine-sgx-sign --manifest gramine.manifest --output gramine.manifest.sgx
gramine-sgx-get-token ...
```

Should be a `make gramine` target (or `scripts/build-gramine.sh`) that:
1. Takes `ARCH_LIBDIR` (default `/lib/x86_64-linux-gnu`) and `LOG_LEVEL` (default `warning`) as env vars
2. Runs all three steps in order
3. Extracts and prints MRENCLAVE at the end

This makes the build reproducible in CI and operator docs.

## Testing Approach (No Hardware Required)

Real SGX cannot run in CI. Two stubs that can run anywhere:

1. **Manifest syntax test (`tests/tee/test_gramine_manifest.py`):** Parse `gramine.manifest.template` as a TOML-like file and assert required keys are present (`sgx.remote_attestation`, `loader.entrypoint`, specific env var passthroughs, `/data` mount, `TEE_BACKEND` passthrough). This catches typos without Gramine installed.

2. **`gramine-direct` smoke test (conditional):** If `gramine-direct` is on `PATH`, run `gramine-manifest` + `gramine-direct python3 -c "import subnet.tee; print('ok')"` to confirm the manifest allows basic Python + subnet imports. Skipped automatically if Gramine is not installed (`pytest.importorskip` style).

Both tests can pass in standard CI. R016 is validated by the manifest correctness test + the `gramine-direct` path documented in `GRAMINE.md` (tested manually; CI cannot verify SGX attestation itself).

## RocksDB Path for Gramine

`run_node.py` picks `base_path` from `--base_path` arg, defaulting to `/tmp/<random>`. Under Gramine, `/tmp` is `tmpfs` (ephemeral). Correct Gramine operation requires:
```
gramine-direct python3 -m subnet.cli.run_node --base_path /data ...
```
The build script / GRAMINE.md should document `--base_path /data` explicitly.

## Recommendation

Three-task pass:

**T01 — Fix manifest + add validation test:**
- Remove / fix `sgx.encrypted_files` mismatch
- Add manifest comment explaining SealedStore vs Gramine encrypted FS
- Write `tests/tee/test_gramine_manifest.py` (pure Python, no Gramine needed) asserting required manifest keys
- Update `GRAMINE.md` to document `--base_path /data` flag

**T02 — Add build script + MRENCLAVE extraction:**
- Add `Makefile.gramine` (or `make gramine` target in main Makefile) with:
  - `gramine-manifest` → `gramine.manifest`
  - `gramine-sgx-sign` → `gramine.manifest.sgx`
  - MRENCLAVE print
- Add `.gitignore` entries for generated `gramine.manifest`, `gramine.manifest.sgx`, `gramine.token`

**T03 — Slice close:**
- Mark R016 → `validated *(M002/S04)*`
- Write S04-SUMMARY, S04-UAT
- Mark roadmap `[x]`
- Commit `feat(tee): S04 Gramine manifest + reproducible build`

## Don't Hand-Roll

| Problem | Existing Solution |
|---|---|
| Manifest template structure | `gramine.manifest.template` — already complete, needs one fix |
| Build commands | `GRAMINE.md` — already documented; wrap into script |
| Python key presence test | `tomllib` (stdlib 3.11+) or simple regex on the template text |
| Gramine install check in test | `shutil.which("gramine-direct")` — skip if absent |

## Constraints

- The manifest is already present — S04 is **not** writing a new manifest from scratch. It's auditing, fixing one path issue, and adding automation.
- R016 status: `active`. S04 closes it.
- `gramine-manifest` requires Gramine to be installed. Tests must degrade gracefully when Gramine is absent.
- `sgx.encrypted_files` in Gramine uses Intel's Protected FS (separate from `SealedStore`'s AES-GCM). Mixing both would double-encrypt. The manifest should use one or the other, not both, for the same path.
- `--base_path /data` must be passed when running under Gramine so RocksDB lands in the persistent (non-tmpfs) mount, not in ephemeral `/tmp`.

## Open Risks

- **Python version pin in manifest.** The manifest references `/usr/lib/python3.12/` as a trusted file. If the system runs Python 3.11, this path is wrong. The build script must derive the path from the running Python (`python3 -c "import sys; print(sys.prefix)"`).
- **Gramine version.** Manifest syntax is stable across Gramine 1.5+, but `sgx.remote_attestation = "dcap"` requires Gramine 1.4+. GRAMINE.md already says Gramine 1.6+.
- **libp2p syscall coverage.** The manifest's syscall allowlist was hand-curated. A future libp2p update may use a syscall not in the list (e.g., `io_uring_*`). The `gramine-direct` smoke test will surface this immediately; the SGX path will surface it at startup.

## Sources

- `gramine.manifest.template` — pre-existing manifest; inspected inline
- `GRAMINE.md` — pre-existing build docs; inspected inline
- `subnet/tee/sealed/store.py` — confirms SealedStore uses RocksDB nmap, not a separate file path
- `subnet/node/mock.py` — confirms `self.db` (shared RocksDB) is passed to `SealedStore`
- `subnet/cli/run_node.py` — confirms `--base_path` arg and default `/tmp/<random>`
- S03-SUMMARY.md — "SealedStore shares the node's existing db (RocksDB) using a dedicated `"sealed"` nmap column family. There is no separate sealed-storage database or file — S04 Gramine manifest must account for this"
