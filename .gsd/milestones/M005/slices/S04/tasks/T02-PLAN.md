---
estimated_steps: 3
estimated_files: 3
---

# T02: Expand CHAIN.md, update TESTING_LAYERS.md, and add CI workflow

**Slice:** S04 — Chain Integration Docs + Smoke Tests
**Milestone:** M005

## Description

The `CHAIN.md` file is currently a stub with a pointer to S04 for full docs. This task replaces the stub with a complete developer walkthrough. `TESTING_LAYERS.md` gets updated to reference the new scripts from S04. A `.github/workflows/ci.yml` file adds automated Layer 1 + Layer 2 checks that run on every push/PR.

This is the documentation-and-CI task. It has no dependencies on T01 except for the list of new scripts that T01 produces (those are already named in the roadmap). T01 must be complete before this task runs so the script names are confirmed.

## Steps

1. **Replace `CHAIN.md` with the full developer walkthrough.**

   Structure the file with these sections (use `##` headings):

   **Prerequisites**
   - Python 3.11+, Docker, the subnet repo cloned
   - A Hypertensor account with testnet HTSR tokens (link to faucet: `https://discord.gg/hypertensor` → `#testnet-faucet` channel)
   - A keypair mnemonic — generate with `subkey generate` (or any Polkadot-compatible wallet); document the exact `subkey` command
   - Required env vars table: `CHAIN_ENDPOINT`, `SUBNET_ID`, `PHRASE` (or `TENSOR_PRIVATE_KEY`)

   **Step 1 — Verify chain connectivity**
   - Show `check_peers.py` command with `--chain` and `--local_rpc` variants
   - Explain exit codes and `[OK]` vs `ERROR:` output
   - Note that 0 nodes is OK before registration

   **Step 2 — Register your subnet**
   - Show `register_subnet.py` command with example values
   - Explain each `--name`, `--repo`, `--description`, `--min_stake`, `--max_stake` arg
   - Expected output: `[OK] Subnet registered: 0x...`
   - Note: record the subnet ID from the receipt for use in step 3

   **Step 3 — Register and stake your node(s)**
   - Show `register_node.py` command
   - Explain `--hotkey`, `--peer_id` (libp2p peer ID format: `12D3Koo...`), `--stake`
   - Repeat for each node (at least 2 nodes recommended)
   - Expected output: `[OK] Node registered: 0x...`

   **Step 4 — Run the full stack**
   - Show the full `docker-compose.chain.yml` command with all required env vars
   - Note: `MOCK_TEE=true` is built-in — no EPYC hardware needed
   - Per-node PHRASE env vars: `VALIDATOR_PHRASE`, `MINER1_PHRASE`, `MINER2_PHRASE`, `OVERWATCH_PHRASE`, `OVERWATCH_NODE_ID`

   **Step 5 — Monitor with check scripts**
   - `check_peers.py` — verify registered nodes
   - `check_scores.py --epoch N` — verify scores landed after epoch N
   - `check_slash.py --overwatch_node_id N --epoch N` — verify slash events
   - **`[WARN]` vs `[OK]` semantics**: `[WARN] No scores found for epoch N` means the epoch has not yet finalised or no submission has landed yet — this is normal for the first 2-3 epochs. `[OK]` means data is present. `ERROR:` means a connection failure.
   - **Expected time-to-first-submission**: Typically 2-3 epochs after validator start (1 epoch for mesh formation + 1 epoch scoring delay). If scores are not visible after 5 epochs, check `docker compose logs validator | grep "Score\|ERROR"`.

   **Step 6 — Combined smoke test**
   - `smoke_test_chain.py` command with all required args
   - Explain `[PASS]`/`[FAIL]` output and exit code semantics

   **Troubleshooting**
   - `ERROR: Cannot connect to wss://...` → check `CHAIN_ENDPOINT`; try `check_peers.py --local_rpc` to confirm local node is running
   - Compose aborts with `CHAIN_ENDPOINT is required` → ensure env vars are exported before `docker compose up`
   - Scores not appearing → wait 3+ epochs; check `docker compose logs validator | grep "[ValidatorLoop] Submitted"`
   - `[WARN] No scores found` ≠ error — see `[WARN]` vs `[OK]` semantics above

   **Important**: Remove the "Coming in M005/S04" section at the bottom of the existing stub — those scripts now exist.

2. **Update `TESTING_LAYERS.md` Layer 3 section.**

   Find the Layer 3 section (starts at `## Layer 3 — Hypertensor Testnet`). Add after the existing `check_peers.py` command block:

   ```bash
   # After each epoch — verify scores submitted to chain:
   python scripts/check_scores.py \
     --chain wss://rpc.hypertensor.app:443 \
     --subnet_id 1 \
     --epoch N
   # → [OK] Scores found for epoch N: X entries
   # → [WARN] No scores found for epoch N  ← normal for first 2-3 epochs

   # Verify slash events (set TAMPER_RATE=1.0 to force a slash):
   python scripts/check_slash.py \
     --chain wss://rpc.hypertensor.app:443 \
     --overwatch_node_id 1 \
     --epoch N
   # → [OK] 1 commit(s) found  / [OK] 1 reveal(s) found

   # Combined Layer 3 smoke test (delegates to all three check scripts):
   python scripts/smoke_test_chain.py \
     --chain wss://rpc.hypertensor.app:443 \
     --subnet_id 1 \
     --epoch N \
     --overwatch_node_id 1
   # → [PASS] check_peers.py
   # → [PASS] check_scores.py
   # → [PASS] check_slash.py
   # Exits 0 only when all three pass.
   ```

   Also add `check_scores.py`, `check_slash.py`, and `smoke_test_chain.py` to the **See also** line at the bottom of the Layer 3 section.

3. **Create `.github/workflows/ci.yml`.**

   Create the parent directory `.github/workflows/` and write `ci.yml`:

   ```yaml
   name: CI

   on:
     push:
       branches: [main]
     pull_request:
       branches: [main]

   jobs:
     ci:
       runs-on: ubuntu-latest

       steps:
         - uses: actions/checkout@v4

         - name: Set up Python
           uses: actions/setup-python@v5
           with:
             python-version: "3.11"

         - name: Install dependencies
           run: pip install -e ".[dev]"

         - name: Layer 1 — pytest
           run: pytest tests/ -x -q

         - name: Layer 2 — Docker Compose config validation
           run: |
             docker compose -f docker-compose.tee-dev.yml config > /dev/null
             echo "Layer 2 compose config valid"

         - name: Layer 3 — Chain smoke test (informational, no testnet in CI)
           # Expects exit 1 (no testnet node available in CI). Step is
           # informational only — failure here does not block the PR.
           # Run against a real testnet manually before merging chain changes.
           continue-on-error: true
           run: |
             python scripts/smoke_test_chain.py \
               --local_rpc \
               --subnet_id 1 \
               --epoch 0 \
               --overwatch_node_id 1 \
               || echo "Chain smoke test: no testnet in CI (expected)"
   ```

   Use `actions/checkout@v4` and `actions/setup-python@v5` (current stable versions). The Layer 3 step has `continue-on-error: true` to prevent CI failure when no testnet is available, matching the research doc's "skip gracefully when `CHAIN_ENDPOINT` absent" strategy.

## Must-Haves

- [ ] `CHAIN.md` has ≥ 6 sections: Prerequisites, connectivity check, register subnet, register node, run stack, monitor
- [ ] `CHAIN.md` documents `[WARN]` vs `[OK]` semantics and expected time-to-first-submission
- [ ] `CHAIN.md` no longer contains the "Coming in M005/S04" placeholder section
- [ ] `TESTING_LAYERS.md` Layer 3 section references `check_scores.py`, `check_slash.py`, and `smoke_test_chain.py`
- [ ] `.github/workflows/ci.yml` has `pytest tests/ -x -q` step and `docker compose config` step
- [ ] CI Layer 3 step has `continue-on-error: true` so CI does not fail on expected chain absence

## Verification

```bash
# CHAIN.md has registration content (not a stub):
grep -c "register_subnet\|register_node\|faucet\|\[WARN\]" CHAIN.md
# → count > 3

# CHAIN.md has no remaining stub placeholder:
grep -i "coming in M005" CHAIN.md; echo GREP_EXIT=$?
# → GREP_EXIT=1  (no match)

# TESTING_LAYERS.md references new scripts:
grep "check_scores\|check_slash\|smoke_test" TESTING_LAYERS.md | wc -l
# → count >= 3

# CI workflow exists and has required steps:
grep -c "pytest\|docker compose" .github/workflows/ci.yml
# → count >= 2

# CI Layer 3 step has continue-on-error:
grep "continue-on-error" .github/workflows/ci.yml
# → continue-on-error: true

# Layer 2 still valid:
docker compose -f docker-compose.tee-dev.yml config > /dev/null; echo EXIT=$?
# → EXIT=0
```

## Inputs

- `CHAIN.md` — existing stub (~30 lines); replace contents entirely with full walkthrough
- `TESTING_LAYERS.md` — Layer 3 section at line ~122; add new script commands after the existing `check_peers.py` block
- `.gsd/milestones/M005/slices/S04/tasks/T01-PLAN.md` (completed) — confirms the names and CLI args for `register_subnet.py`, `register_node.py`, `smoke_test_chain.py`
- `scripts/check_peers.py`, `scripts/check_scores.py`, `scripts/check_slash.py` — confirm the exact `--chain`/`--local_rpc`/`--subnet_id`/`--epoch`/`--overwatch_node_id` arg names to reference correctly in docs
- M005 roadmap success criteria — `CHAIN.md` walkthrough must be reproducible by a new developer with no prior Substrate experience

## Observability Impact

**What changes after this task:**
- `CHAIN.md` becomes the primary inspection surface for new developers — a developer following it can now verify each step produces `[OK]` output before proceeding
- `.github/workflows/ci.yml` adds two automated inspection surfaces: the pytest run log (Layer 1 pass/fail) and the Docker Compose config validation (Layer 2 pass/fail); both are visible in the GitHub Actions tab on every push/PR
- The Layer 3 CI step (`continue-on-error: true`) surfaces chain smoke test output as an informational log even when no testnet is available — agents and developers can read the step log to see `[FAIL] check_peers.py (exit 1)` and confirm graceful degradation

**How a future agent inspects this task's outputs:**
```bash
# Confirm CHAIN.md is the full walkthrough (not stub):
grep -c "register_subnet\|register_node\|faucet\|\[WARN\]" CHAIN.md
# → count > 3

# Confirm TESTING_LAYERS.md was updated:
grep "smoke_test_chain\|check_scores\|check_slash" TESTING_LAYERS.md

# Confirm CI workflow exists with required steps:
grep -n "pytest\|docker compose\|continue-on-error" .github/workflows/ci.yml
```

**Failure state visibility:**
- If `CHAIN.md` still contains "Coming in M005" → stub was not replaced; the walkthrough is incomplete
- If `.github/workflows/ci.yml` is missing → CI job never runs; chain integration is never automatically verified
- If Layer 3 CI step lacks `continue-on-error: true` → every PR fails on expected chain absence, blocking all merges

## Expected Output

- `CHAIN.md` — replaced; full developer walkthrough (~150-200 lines); 6+ sections; no stub placeholder remaining
- `TESTING_LAYERS.md` — modified Layer 3 section; adds `check_scores.py`, `check_slash.py`, `smoke_test_chain.py` command examples and See also reference
- `.github/workflows/ci.yml` — new; 4 steps: checkout, Python setup + install, pytest (Layer 1), compose config (Layer 2), chain smoke test (Layer 3, `continue-on-error: true`)
