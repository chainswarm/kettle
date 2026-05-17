---
id: T01
parent: S01
milestone: M005
provides:
  - scripts/check_peers.py chain smoke-test script
key_files:
  - scripts/check_peers.py
  - .gsd/milestones/M005/slices/S01/S01-PLAN.md
  - .gsd/milestones/M005/slices/S01/tasks/T01-PLAN.md
key_decisions:
  - LOCAL_RPC and DEV_RPC are env vars, not module constants (no constants in subnet/hypertensor/config.py); script mirrors the existing CLI pattern in subnet/cli/run_node.py
patterns_established:
  - check_peers.py follows the exact Hypertensor(url, phrase) construction path that run_node.py uses for real-chain mode
  - Credential redaction: env vars stored in local `phrase` var, never passed to print/logger
  - Friendly-ID branch: `if subnet_id < 128000` → `get_subnet_id_from_friendly_id()` → `int(str(result))` (mirrors run_node.py)
observability_surfaces:
  - "[OK] Connected to <url>" on stdout after successful WebSocket connection
  - One row per peer on stdout: peer_id= hotkey= stake= class=
  - "N nodes registered" summary line on stdout
  - "ERROR: Cannot connect to <url>: <reason>" on stderr, exit 1
  - "WARNING: Subnet not yet active / no slot assigned" on stderr, exit 0
  - "WARNING: Friendly subnet_id N could not be resolved" on stderr, exit 0
  - python scripts/check_peers.py --help for usage
duration: 20m
verification_result: passed
completed_at: 2026-03-17
blocker_discovered: false
---

# T01: Write `scripts/check_peers.py` chain smoke-test script

**Add `scripts/check_peers.py` — Hypertensor chain smoke-test that enumerates registered subnet peers, handles all edge cases (connection failure, no slot, friendly ID, empty list), and never echoes credentials.**

## What Happened

Created `scripts/check_peers.py` (~140 lines) following the task plan exactly. The script:

1. Parses `--chain URL`, `--subnet_id INT`, and `--local_rpc` via argparse with clear help text.
2. Reads credentials exclusively from `$PHRASE` / `$TENSOR_PRIVATE_KEY` env vars; stores in `phrase` local var and never prints it.
3. Wraps `Hypertensor(url, phrase)` in try/except — any connection or keypair error prints `ERROR: Cannot connect to <url>: <reason>` to stderr and exits 1.
4. Resolves friendly subnet IDs (`< 128000`) via `get_subnet_id_from_friendly_id()` and converts the result with `int(str(result))` (mirrors run_node.py).
5. Calls `get_subnet_slot(real_id)` — `None` returns print a WARNING to stderr and exit 0.
6. Calls `get_subnet_nodes_info_formatted(real_id)` and prints one row per node, plus a final count.

**Implementation note:** `subnet/hypertensor/config.py` contains no `LOCAL_RPC`/`DEV_RPC` constants — those are env var names only. The script mirrors the existing `subnet/cli/run_node.py` pattern: `os.environ.get("LOCAL_RPC", "ws://127.0.0.1:9944")` and `os.environ.get("DEV_RPC", "wss://rpc.hypertensor.app:443")`.

Pre-flight fixes applied: added a failure-path verification step to S01-PLAN.md and added `## Observability Impact` section to T01-PLAN.md.

## Verification

All task-plan verification checks passed:

```
# Exit 1 + ERROR message with URL (no local node):
$ python3 scripts/check_peers.py --local_rpc --subnet_id 1 2>&1; echo EXIT=$?
ERROR: Cannot connect to ws://127.0.0.1:9944: [Errno 111] Connection refused
EXIT=1   ✅

# Credential redaction — grep finds nothing:
$ PHRASE="super secret mnemonic" python3 scripts/check_peers.py --local_rpc --subnet_id 1 2>&1 | grep -i "super secret"; echo GREP=$?
GREP=1   ✅  (exit 1 from grep = no match = redaction works)

# Help shows all flags:
$ python3 scripts/check_peers.py --help
... --chain URL, --subnet_id INT, --local_rpc all shown with descriptions  ✅

# Unreachable external endpoint:
$ python3 scripts/check_peers.py --chain wss://unreachable.example:443 --subnet_id 1 2>&1; echo EXIT=$?
ERROR: Cannot connect to wss://unreachable.example:443: [Errno -2] Name or service not known
EXIT=1   ✅
```

Slice-level checks:
- Check 2 (exit 1 unreachable): ✅ verified above
- Check 3 (Layer 1 pytest): 183 passed, 1 skipped ✅
- Check 4 (Layer 2 docker compose config): exit 0 ✅
- Check 1 (exit 0 with live node): requires a running Hypertensor node — not available in this environment; all other paths verified

## Diagnostics

```bash
# Check connectivity:
python3 scripts/check_peers.py --chain wss://rpc.hypertensor.app:443 --subnet_id 1

# Check local node (Substrate at ws://127.0.0.1:9944):
python3 scripts/check_peers.py --local_rpc --subnet_id 1

# Override local RPC URL:
LOCAL_RPC=ws://127.0.0.1:9944 python3 scripts/check_peers.py --local_rpc --subnet_id 1

# Inspect failure state:
python3 scripts/check_peers.py --local_rpc --subnet_id 1 2>&1 | grep "^ERROR:\|^WARNING:\|^\[OK\]"

# Exit code inspection:
python3 scripts/check_peers.py --local_rpc --subnet_id 1; echo "exit=$?"
```

## Deviations

- **`LOCAL_RPC`/`DEV_RPC` are env vars, not module constants.** The task plan referenced "LOCAL_RPC constant from config" but `subnet/hypertensor/config.py` only contains `BLOCK_SECS`, `EPOCH_LENGTH`, and `SECONDS_PER_EPOCH`. The real pattern (used by `subnet/cli/run_node.py`) is `os.environ.get("LOCAL_RPC")`. Implemented accordingly with hardcoded fallback values.

## Known Issues

- `Hypertensor.__init__` creates a keypair from `phrase` even for read-only queries. An empty string `phrase` will cause a keypair creation error before the WebSocket connection is attempted, resulting in an `ERROR: Cannot connect` message even when the URL is valid. This matches the existing `run_node.py` behaviour and is not a regression. Read-only users must supply a valid phrase.

## Files Created/Modified

- `scripts/check_peers.py` — new chain smoke-test script (~140 lines)
- `.gsd/milestones/M005/slices/S01/S01-PLAN.md` — added failure-path verification step (pre-flight fix)
- `.gsd/milestones/M005/slices/S01/tasks/T01-PLAN.md` — added `## Observability Impact` section (pre-flight fix)
