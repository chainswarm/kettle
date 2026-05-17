---
estimated_steps: 6
estimated_files: 3
---

# T01: Write `scripts/check_peers.py` chain smoke-test script

**Slice:** S01 — Chain Peer Discovery
**Milestone:** M005

## Description

Create `scripts/check_peers.py` — the primary S01 proof artifact. This script instantiates `Hypertensor` directly (using the same code path `run_node.py` takes when `--no_blockchain_rpc` is false) and calls `get_subnet_nodes_info_formatted`. It prints each registered peer's key fields, handles every edge case (connection failure, no slot, empty list, friendly ID), and exits 0 on success or 1 on connection failure. Credentials are never echoed.

## Steps

1. **Create `scripts/check_peers.py`** with argparse: `--chain URL` (default: `DEV_RPC` env or `wss://rpc.hypertensor.app:443`), `--subnet_id INT` (required), `--local_rpc` flag (shortcut that sets chain to `LOCAL_RPC` constant from config, i.e. `ws://127.0.0.1:9944`).

2. **Read credentials from env** inside the script: prefer `os.environ.get("PHRASE", "")`, fall back to `os.environ.get("TENSOR_PRIVATE_KEY", "")`. Store in a local var `phrase`. Never print it. Pass it to `Hypertensor(url, phrase)`.

3. **Wrap Hypertensor construction in try/except**: catch `Exception` (websocket/connection errors), print `f"ERROR: Cannot connect to {url}: {e}"` to stderr, and `sys.exit(1)`.

4. **Friendly ID resolution**: if `args.subnet_id < 128000`, call `hypertensor.get_subnet_id_from_friendly_id(args.subnet_id)` to get the real chain ID. Use the resolved ID for all subsequent queries. (Mirror `run_node.py` lines ~492–495.)

5. **Query subnet slot**: call `hypertensor.get_subnet_slot(real_id)`. If the return is `None`, print `"WARNING: Subnet not yet active / no slot assigned"` to stderr and `sys.exit(0)` — not an error, just not running yet.

6. **Query and print nodes**: call `hypertensor.get_subnet_nodes_info_formatted(real_id)`. For each `SubnetNodeInfo` node in the result, print one line: `f"  peer_id={node.peer_info.peer_id}  hotkey={node.hotkey}  stake={node.stake_balance}  class={node.classification}"`. After the loop, print `f"\n{len(nodes)} nodes registered"`. Exit 0.

## Must-Haves

- [ ] Script exits 0 when chain is reachable — even if peer list is empty (0 nodes is valid)
- [ ] Script exits 1 when connection fails; error message includes the offending URL
- [ ] `PHRASE` / `TENSOR_PRIVATE_KEY` values never appear in any `print()` or `logger` output
- [ ] Friendly subnet_id (< 128000) is resolved before any chain query
- [ ] `get_subnet_slot` returning `None` produces a warning and clean exit 0, not a traceback
- [ ] `--local_rpc` flag works as a shortcut to `ws://127.0.0.1:9944`
- [ ] `--help` output is clear (argparse descriptions on all flags)

## Verification

```bash
# With no local node — must exit 1 with ERROR: message:
python scripts/check_peers.py --local_rpc --subnet_id 1
# Expected: "ERROR: Cannot connect to ws://127.0.0.1:9944: ..." on stderr; exit code 1

# Confirm credentials are never echoed:
PHRASE="super secret mnemonic" python scripts/check_peers.py --local_rpc --subnet_id 1 2>&1 | grep -i "super secret"
# Expected: no output

# Help works:
python scripts/check_peers.py --help
# Expected: shows --chain, --subnet_id, --local_rpc with descriptions
```

## Inputs

- `subnet/hypertensor/chain_functions.py` — `Hypertensor` class. Import `from subnet.hypertensor.chain_functions import Hypertensor`. Look at `__init__` signature: `Hypertensor(url: str, phrase: str)`. All needed methods: `get_subnet_id_from_friendly_id`, `get_subnet_slot`, `get_subnet_nodes_info_formatted`.
- `subnet/hypertensor/config.py` — `DEV_RPC`, `LOCAL_RPC` constants. Use `LOCAL_RPC` for the `--local_rpc` shortcut.
- `subnet/hypertensor/chain_data.py` — `SubnetNodeInfo` dataclass. Field access: `node.peer_info.peer_id`, `node.hotkey`, `node.stake_balance`, `node.classification`. Note: `peer_info` is a `PeerInfo` dataclass (not a dict) after `__post_init__` conversion — use attribute access, not `.get()`.
- `run_node.py` (lines ~485–500) — reference for the friendly-ID resolution pattern. Copy the `if subnet_id < 128000` branch logic.

## Observability Impact

**Signals added:**
- `[OK] Connected to <url>` printed to stdout after successful `Hypertensor` construction — confirms the WebSocket handshake succeeded
- One row per peer printed to stdout: `peer_id=…  hotkey=…  stake=…  class=…` — directly inspectable by humans and grep
- `\nN nodes registered` summary line on stdout — machine-readable count for CI assertions
- `ERROR: Cannot connect to <url>: <reason>` on stderr with exit 1 — structured failure signal for CI/CD tools
- `WARNING: Subnet not yet active / no slot assigned` on stderr with exit 0 — distinct from connection failure; inspectable via `$?` and grep

**Inspection surfaces:**
- `python scripts/check_peers.py --help` — shows all flags and defaults
- `python scripts/check_peers.py --chain <url> --subnet_id <id> 2>&1` — full output including warnings
- `echo $?` after invocation — 0 = connected (even if 0 nodes), 1 = connection failed

**Redaction constraint:** `PHRASE` / `TENSOR_PRIVATE_KEY` values are stored in a local variable `phrase` and passed directly to `Hypertensor()`; they never appear in any `print()`, `logger`, or `str()` call.

## Expected Output

- `scripts/check_peers.py` — new executable script, ~80 lines, handles all edge cases, credentials-safe
