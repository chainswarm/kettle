---
estimated_steps: 5
estimated_files: 2
---

# T02: Add reproducible build script and .gitignore entries

**Slice:** S04 — Gramine Manifest + Reproducible Build
**Milestone:** M002

## Description

`GRAMINE.md` already documents the three-step Gramine build process, but it requires manual transcription of each command. This task wraps those steps into `scripts/build-gramine.sh` — a single, operator-runnable script that:
1. Generates `gramine.manifest` from the template
2. Signs it to produce `gramine.manifest.sgx`
3. Generates `gramine.token`
4. Extracts and prints the MRENCLAVE hash

Additionally, the three generated Gramine artifacts (`gramine.manifest`, `gramine.manifest.sgx`, `gramine.token`) must be listed in `.gitignore` — they are build outputs and should never be committed to the repo.

This task does not require Gramine to be installed. The script is verified with `bash -n` (syntax check only).

## Steps

1. **Create `scripts/` directory** if it does not exist (check with `ls scripts/` first; create only if absent).

2. **Write `scripts/build-gramine.sh`:**

   ```bash
   #!/usr/bin/env bash
   # build-gramine.sh — Reproducible Gramine manifest build for Hypertensor TEE miner
   #
   # Usage:
   #   bash scripts/build-gramine.sh
   #
   # Environment variables (with defaults):
   #   ARCH_LIBDIR  — architecture library dir (default: /lib/x86_64-linux-gnu)
   #   LOG_LEVEL    — Gramine log level (default: warning)
   #
   # Output:
   #   gramine.manifest      — generated manifest
   #   gramine.manifest.sgx  — signed manifest (contains MRENCLAVE)
   #   gramine.token         — SGX token
   #   MRENCLAVE printed to stdout at the end
   #
   # Requires: gramine-manifest, gramine-sgx-sign, gramine-sgx-get-token,
   #           gramine-sgx-sigstruct-view, python3
   #
   # After running, set EXPECTED_MEASUREMENT on validators:
   #   export EXPECTED_MEASUREMENT=<printed MRENCLAVE>

   set -euo pipefail

   ARCH_LIBDIR="${ARCH_LIBDIR:-/lib/x86_64-linux-gnu}"
   LOG_LEVEL="${LOG_LEVEL:-warning}"

   echo "[gramine-build] Step 1/4: Generating manifest from template..."
   gramine-manifest \
     -Dlog_level="$LOG_LEVEL" \
     -Darch_libdir="$ARCH_LIBDIR" \
     gramine.manifest.template > gramine.manifest
   echo "[gramine-build] gramine.manifest generated."

   echo "[gramine-build] Step 2/4: Signing manifest (requires SGX signing key)..."
   gramine-sgx-sign \
     --manifest gramine.manifest \
     --output gramine.manifest.sgx
   echo "[gramine-build] gramine.manifest.sgx signed."

   echo "[gramine-build] Step 3/4: Generating SGX token..."
   gramine-sgx-get-token \
     --output gramine.token \
     --sig gramine.manifest.sgx
   echo "[gramine-build] gramine.token generated."

   echo "[gramine-build] Step 4/4: Extracting MRENCLAVE..."
   MRENCLAVE=$(gramine-sgx-sigstruct-view --output-format=json gramine.manifest.sgx \
     | python3 -c "import sys, json; d=json.load(sys.stdin); print(d.get('enclave_hash', d.get('mr_enclave', 'not_found')))")

   echo ""
   echo "[gramine-build] ============================================"
   echo "[gramine-build] MRENCLAVE: $MRENCLAVE"
   echo "[gramine-build] Done. Set EXPECTED_MEASUREMENT=$MRENCLAVE on validators."
   echo "[gramine-build] ============================================"
   ```

   Make it executable: `chmod +x scripts/build-gramine.sh`

3. **Add entries to `.gitignore`:**
   - Read the current `.gitignore` to find the right place to append
   - Append the following block (do not duplicate if already present):
     ```
     # Gramine generated artifacts
     gramine.manifest
     gramine.manifest.sgx
     gramine.token
     ```

4. **Verify script syntax:**
   ```bash
   bash -n scripts/build-gramine.sh
   ```
   Should exit 0 with no output.

5. **Verify .gitignore entries:**
   ```bash
   grep -n "gramine\." .gitignore
   ```
   Should show all three entries.

## Must-Haves

- [ ] `scripts/build-gramine.sh` exists and is executable
- [ ] Script has `set -euo pipefail` at the top
- [ ] Script accepts `ARCH_LIBDIR` and `LOG_LEVEL` env vars with documented defaults
- [ ] Script runs all four steps: `gramine-manifest`, `gramine-sgx-sign`, `gramine-sgx-get-token`, MRENCLAVE extraction
- [ ] Script prints MRENCLAVE and "Set EXPECTED_MEASUREMENT" instruction at the end
- [ ] `bash -n scripts/build-gramine.sh` exits 0 (syntax valid)
- [ ] `.gitignore` contains `gramine.manifest`, `gramine.manifest.sgx`, `gramine.token`

## Verification

```bash
bash -n scripts/build-gramine.sh
# → exit 0, no output

grep -n "gramine\." .gitignore
# → shows gramine.manifest, gramine.manifest.sgx, gramine.token entries

ls -la scripts/build-gramine.sh
# → -rwxr-xr-x ... (executable)
```

## Inputs

- `GRAMINE.md` — documents the three manual build steps that this script automates; script is a direct automation of the existing documented process
- T01 output: `gramine.manifest.template` is now correct (no `/sealed` Protected FS mount) — the build script runs against this fixed template

## Expected Output

- `scripts/build-gramine.sh` — new executable script; syntax-valid; automates the 3-step Gramine build + MRENCLAVE extraction; accepts `ARCH_LIBDIR`/`LOG_LEVEL` env vars
- `.gitignore` — three new entries: `gramine.manifest`, `gramine.manifest.sgx`, `gramine.token`

## Observability Impact

This task produces static build tooling — no new runtime signals. However, the script itself emits structured step-by-step progress messages and surfaces the MRENCLAVE hash as its primary output.

**Inspection surfaces:**
- `bash -n scripts/build-gramine.sh` — syntax validity check; exit 0 = good, any error = bad script
- `grep -n "gramine\." .gitignore` — confirms all three artifact exclusions are present
- `ls -la scripts/build-gramine.sh` — confirms executable bit (`-rwxr-xr-x`)
- Script stdout (when run with Gramine installed): each step prints `[gramine-build] Step N/4: ...` progress lines, followed by the MRENCLAVE hash and `Set EXPECTED_MEASUREMENT=...` operator instruction

**Failure visibility:**
- If MRENCLAVE extraction fails, the script exits non-zero due to `set -euo pipefail` — the operator sees the specific failing step's stderr from `gramine-sgx-sigstruct-view`
- If `.gitignore` entries are missing, generated Gramine artifacts can accidentally get committed — `git status` will show `gramine.manifest`, `gramine.manifest.sgx`, `gramine.token` as untracked
- Syntax errors in the script are caught by `bash -n` without needing Gramine installed
