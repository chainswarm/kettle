---
id: T02
parent: S04
milestone: M002
provides:
  - scripts/build-gramine.sh — executable 4-step Gramine build automation (manifest → sign → token → MRENCLAVE extraction)
  - .gitignore entries for gramine.manifest, gramine.manifest.sgx, gramine.token
key_files:
  - scripts/build-gramine.sh
  - .gitignore
key_decisions:
  - Script matches GRAMINE.md documented steps exactly — no deviations from documented process
  - MRENCLAVE extraction uses python3 inline JSON parse to handle both 'enclave_hash' and 'mr_enclave' key names from gramine-sgx-sigstruct-view (version-robust)
patterns_established:
  - Gramine build scripts are verified with `bash -n` (syntax only) in CI — Gramine toolchain not required for CI validation
  - Explicit gitignore entries for generated artifacts alongside the existing `*.manifest` PyInstaller glob — both are needed for clarity and correctness
observability_surfaces:
  - bash -n scripts/build-gramine.sh — syntax validity (exit 0 = good)
  - grep -n "gramine\\." .gitignore — confirms artifact exclusions present
  - ls -la scripts/build-gramine.sh — confirms executable bit
  - Script stdout (when run): step-by-step [gramine-build] progress + MRENCLAVE hash + EXPECTED_MEASUREMENT operator instruction
duration: ~5 minutes
verification_result: passed
completed_at: 2026-03-17
blocker_discovered: false
---

# T02: Add reproducible build script and .gitignore entries

**Created `scripts/build-gramine.sh` — a 4-step executable that automates Gramine manifest generation, signing, token creation, and MRENCLAVE extraction from the fixed template; added `gramine.manifest`, `gramine.manifest.sgx`, `gramine.token` to `.gitignore`.**

## What Happened

- Created `scripts/` directory (did not exist)
- Wrote `scripts/build-gramine.sh` exactly per plan — `set -euo pipefail`, `ARCH_LIBDIR`/`LOG_LEVEL` env vars with defaults, 4 numbered steps with `[gramine-build]` progress messages, MRENCLAVE extraction via `gramine-sgx-sigstruct-view --output-format=json` + inline python3 JSON parse, final `Set EXPECTED_MEASUREMENT=...` operator instruction
- Set executable bit (`chmod +x`)
- Appended Gramine artifact block to `.gitignore` (no pre-existing Gramine entries found; `*.manifest` PyInstaller glob already existed but explicit named entries are still required for `.manifest.sgx` and `.token`)
- Fixed pre-flight issue: added `## Observability Impact` section to T02-PLAN.md

## Verification

```
bash -n scripts/build-gramine.sh
→ EXIT 0, no output (syntax valid)

grep -n "gramine\." .gitignore
→ 168:gramine.manifest
→ 169:gramine.manifest.sgx
→ 170:gramine.token

ls -la scripts/build-gramine.sh
→ -rwxrwxr-x 1 aphex5 aphex5 2065 Mar 17 09:11 scripts/build-gramine.sh

python3 -m pytest tests/tee/test_gramine_manifest.py -v
→ 8 passed, 1 skipped (smoke test skipped — no Gramine installed, expected)

python3 -m pytest tests/ --ignore=tests/hypertensor -q
→ 181 passed, 1 skipped — no regressions
```

## Diagnostics

- `bash -n scripts/build-gramine.sh` — primary syntax check, no Gramine needed
- `grep -n "gramine\." .gitignore` — confirm all three artifact entries present
- `ls -la scripts/build-gramine.sh` — confirm executable bit set
- When run with Gramine: each step emits `[gramine-build] Step N/4: ...` to stdout; on failure `set -euo pipefail` ensures non-zero exit and the specific failed step's stderr is visible
- If MRENCLAVE key name changes in a future Gramine release: the python3 inline parse checks both `enclave_hash` and `mr_enclave` keys, prints `not_found` if neither present (signals mismatch without silent failure)

## Deviations

None. Script content, env var names, step ordering, and output format all match the plan verbatim.

## Known Issues

None.

## Files Created/Modified

- `scripts/build-gramine.sh` — new executable; 4-step Gramine build automation; accepts ARCH_LIBDIR/LOG_LEVEL env vars; prints MRENCLAVE and EXPECTED_MEASUREMENT operator instruction
- `.gitignore` — appended `# Gramine generated artifacts` block with `gramine.manifest`, `gramine.manifest.sgx`, `gramine.token`
- `.gsd/milestones/M002/slices/S04/tasks/T02-PLAN.md` — added `## Observability Impact` section (pre-flight fix)
