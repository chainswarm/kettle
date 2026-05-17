---
estimated_steps: 6
estimated_files: 5
---

# T03: Slice close — validate R016, write summary, commit

**Slice:** S04 — Gramine Manifest + Reproducible Build
**Milestone:** M002

## Description

Administrative close of S04 and M002. All implementation work is done in T01 and T02. This task:
1. Runs the full test suite to confirm the passing state
2. Marks R016 as validated in REQUIREMENTS.md
3. Marks S04 `[x]` in the M002 roadmap
4. Writes the S04-SUMMARY.md artifact
5. Commits all changes with the canonical feat message
6. Updates STATE.md to reflect M002 completion

**Prerequisite:** T01 and T02 must be complete — `tests/tee/test_gramine_manifest.py` must pass and `scripts/build-gramine.sh` must exist.

## Steps

1. **Run full test suite** to confirm green state:
   ```bash
   python3 -m pytest tests/ --ignore=tests/hypertensor -q
   ```
   Must show all tests passing. If any fail, do not proceed — diagnose and fix first.

2. **Update R016 in `.gsd/REQUIREMENTS.md`:**
   Find the line:
   ```
   **Status:** `active`
   ```
   under R016 and change it to:
   ```
   **Status:** `validated` *(M002/S04)*
   ```

3. **Mark S04 complete in `.gsd/milestones/M002/M002-ROADMAP.md`:**
   Find:
   ```
   - [ ] **S04: Gramine manifest + reproducible build**
   ```
   Change to:
   ```
   - [x] **S04: Gramine manifest + reproducible build**
   ```

4. **Write `S04-SUMMARY.md`** at `.gsd/milestones/M002/slices/S04/S04-SUMMARY.md`:

   The summary must include:
   - YAML front-matter (id, parent, milestone, provides, requires, affects, key_files, key_decisions, patterns_established, observability_surfaces, verification_result, completed_at)
   - What happened in each task (T01: manifest fix + test, T02: build script)
   - Verification commands and expected results
   - Requirements validated (R016)
   - Known limitations
   - Forward intelligence for future agents

   Use the S03-SUMMARY.md structure as a guide for the front-matter format. Key facts to include:

   **provides:**
   - `gramine.manifest.template` — fixed: removed Gramine Protected FS `/sealed` mount and dead `sgx.encrypted_files` entry; added explanatory comments for SealedStore AES-GCM model
   - `tests/tee/test_gramine_manifest.py` — 8-test CI-runnable manifest validation suite (pure Python, no Gramine needed)
   - `scripts/build-gramine.sh` — reproducible 3-step Gramine build + MRENCLAVE extraction script
   - `GRAMINE.md` — updated: `--base_path /data` in run commands; sealed storage section corrected

   **key_files:**
   - `gramine.manifest.template`
   - `tests/tee/test_gramine_manifest.py`
   - `scripts/build-gramine.sh`
   - `GRAMINE.md`

   **R016 validation explanation:** R016 requires a manifest template that pins syscalls, files, RA-TLS config, and sealed storage path. The manifest already covered syscalls, RA-TLS (`sgx.remote_attestation = "dcap"`), and file mounts. T01 fixed the sealed storage model (removed incorrect Gramine Protected FS entry; RocksDB at `/data` is the correct path). The validation test (`test_gramine_manifest.py`) makes this machine-checkable in CI.

   **Forward intelligence** must note:
   - Python version pin: manifest references `/usr/lib/python3.12/` — if the deployment system runs Python 3.11, this path will be wrong. The build script could derive the path dynamically: `python3 -c "import sys; print(sys.prefix)"`. Currently a manual concern.
   - SealedStore uses `MOCK_DEV_KEY` in tests; for real TDX, `dev_key` comes from a provisioning step. The `SealedStore` interface accepts `dev_key: bytes` — provisioning mechanism is out of scope for M002.
   - `scripts/build-gramine.sh` requires Gramine 1.6+ installed on the build host. The script is not runnable in standard CI — it's an operator tool.
   - The `gramine-direct` smoke test (`test_gramine_direct_smoke`) is skipped in CI since Gramine is not installed; it provides local-dev validation when Gramine is present.

5. **Commit all changes:**
   ```bash
   git add -A
   git commit -m "feat(tee): S04 Gramine manifest + reproducible build"
   ```

6. **Update `.gsd/STATE.md`:**
   - Set Active Slice to `none`
   - Note M002 milestone complete (all 4 slices: S01 ✅ S02 ✅ S03 ✅ S04 ✅)
   - Set Phase to `complete`
   - Update Next Action to reflect M002 completion

## Must-Haves

- [ ] Full test suite passes: `python3 -m pytest tests/ --ignore=tests/hypertensor -q` — all green
- [ ] R016 shows `validated *(M002/S04)*` in REQUIREMENTS.md
- [ ] S04 shows `[x]` in M002-ROADMAP.md
- [ ] `S04-SUMMARY.md` written with YAML front-matter and all required sections
- [ ] Commit made with message `feat(tee): S04 Gramine manifest + reproducible build`
- [ ] STATE.md updated

## Verification

```bash
python3 -m pytest tests/ --ignore=tests/hypertensor -q
# → all PASSED; no failures

grep "R016" .gsd/REQUIREMENTS.md
# → contains "validated *(M002/S04)*"

grep "S04" .gsd/milestones/M002/M002-ROADMAP.md
# → shows [x]

git log --oneline -1
# → feat(tee): S04 Gramine manifest + reproducible build
```

## Inputs

- T01 output: `gramine.manifest.template` fixed; `tests/tee/test_gramine_manifest.py` passing; `GRAMINE.md` updated
- T02 output: `scripts/build-gramine.sh` exists; `.gitignore` has Gramine artifact entries
- `.gsd/REQUIREMENTS.md` — R016 currently `active`; needs update to `validated`
- `.gsd/milestones/M002/M002-ROADMAP.md` — S04 currently `[ ]`; needs `[x]`

## Observability Impact

This task is administrative (no new runtime code). Observability surfaces affected:

- **`.gsd/REQUIREMENTS.md`** — R016 status transitions from `active` → `validated *(M002/S04)*`; greppable signal for audit: `grep "R016" .gsd/REQUIREMENTS.md`
- **`.gsd/milestones/M002/M002-ROADMAP.md`** — S04 checkbox transitions from `[ ]` → `[x]`; full milestone M002 is complete when all 4 slices show `[x]`
- **`.gsd/STATE.md`** — Active Slice transitions to `none`; Phase transitions to `complete`; a future agent reading STATE.md learns M002 is closed
- **Git log** — `git log --oneline -1` shows `feat(tee): S04 Gramine manifest + reproducible build`; this is the canonical completion signal for this slice

Failure state visibility:
- If tests fail at Step 1, the task must halt — the failing test name is self-documenting (e.g. `test_no_sealed_encrypted_mount`)
- If REQUIREMENTS.md or ROADMAP.md edits are skipped, downstream milestone tracking will show M002 incomplete
- No new runtime signals are introduced — this task closes existing signals

## Expected Output

- `.gsd/REQUIREMENTS.md` — R016 `validated *(M002/S04)*`
- `.gsd/milestones/M002/M002-ROADMAP.md` — S04 `[x]`
- `.gsd/milestones/M002/slices/S04/S04-SUMMARY.md` — complete slice summary with forward intelligence
- `.gsd/STATE.md` — M002 complete; no active slice
- Git commit: `feat(tee): S04 Gramine manifest + reproducible build`
