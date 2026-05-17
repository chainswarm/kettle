#!/usr/bin/env python3
"""
check_peers.py — Hypertensor chain smoke-test: enumerate registered subnet peers.

Usage examples:
  python scripts/check_peers.py --chain wss://rpc.hypertensor.app:443 --subnet_id 1
  python scripts/check_peers.py --local_rpc --subnet_id 1
  PHRASE="word word word ..." python scripts/check_peers.py --subnet_id 1

Exit codes:
  0 — connected successfully (0 nodes is valid)
  1 — connection or credential error

Credentials are read exclusively from env vars PHRASE / TENSOR_PRIVATE_KEY and
are never printed or logged.
"""

import argparse
import os
import sys

# ---------------------------------------------------------------------------
# RPC URL constants (matching the existing CLI convention in subnet/cli/)
# ---------------------------------------------------------------------------
_DEFAULT_DEV_RPC = "wss://rpc.hypertensor.app:443"
_LOCAL_RPC = "ws://127.0.0.1:9944"


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Query registered peer nodes for a Hypertensor subnet. "
            "Reads PHRASE (or TENSOR_PRIVATE_KEY) from env — never echoed."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--chain",
        metavar="URL",
        default=None,
        help=(
            "WebSocket URL of the Hypertensor RPC node. "
            f"Defaults to $DEV_RPC env var or {_DEFAULT_DEV_RPC!r}."
        ),
    )
    parser.add_argument(
        "--subnet_id",
        type=int,
        required=True,
        metavar="INT",
        help=(
            "Subnet ID to query. Values < 128000 are treated as friendly IDs and "
            "resolved to the real chain ID automatically."
        ),
    )
    parser.add_argument(
        "--local_rpc",
        action="store_true",
        help=(
            f"Shortcut: connect to the local dev node at {_LOCAL_RPC!r}. "
            "Overrides --chain and $DEV_RPC."
        ),
    )
    return parser


def main() -> None:  # noqa: C901
    parser = _build_parser()
    args = parser.parse_args()

    # ------------------------------------------------------------------
    # Resolve RPC URL (--local_rpc > --chain > $DEV_RPC > hardcoded default)
    # ------------------------------------------------------------------
    if args.local_rpc:
        # Honour $LOCAL_RPC override if set, otherwise use hardcoded constant
        url = os.environ.get("LOCAL_RPC", _LOCAL_RPC)
    elif args.chain:
        url = args.chain
    else:
        url = os.environ.get("DEV_RPC", _DEFAULT_DEV_RPC)

    # ------------------------------------------------------------------
    # Read credentials from env — never print these values
    # ------------------------------------------------------------------
    phrase = os.environ.get("PHRASE") or os.environ.get("TENSOR_PRIVATE_KEY") or ""

    # ------------------------------------------------------------------
    # Import here so import errors surface cleanly before we attempt connection
    # ------------------------------------------------------------------
    try:
        from subnet.hypertensor.chain_functions import Hypertensor
    except ImportError as exc:
        print(f"ERROR: Cannot import Hypertensor — is the subnet package installed? {exc}", file=sys.stderr)
        sys.exit(1)

    # ------------------------------------------------------------------
    # Connect — exit 1 on any connection / keypair failure
    # ------------------------------------------------------------------
    try:
        hypertensor = Hypertensor(url, phrase)
    except Exception as exc:
        print(f"ERROR: Cannot connect to {url}: {exc}", file=sys.stderr)
        sys.exit(1)

    print(f"[OK] Connected to {url}")

    # ------------------------------------------------------------------
    # Friendly-ID resolution (mirror run_node.py lines ~492-495)
    # ------------------------------------------------------------------
    subnet_id = args.subnet_id
    if subnet_id < 128000:
        real_id_result = hypertensor.get_subnet_id_from_friendly_id(subnet_id)
        if real_id_result is None:
            print(
                f"WARNING: Friendly subnet_id {subnet_id} could not be resolved — subnet may not be registered.",
                file=sys.stderr,
            )
            sys.exit(0)
        real_id = int(str(real_id_result))
        print(f"[OK] Friendly subnet_id {subnet_id} resolved to chain ID {real_id}")
    else:
        real_id = subnet_id

    # ------------------------------------------------------------------
    # Check subnet slot — None means not yet active
    # ------------------------------------------------------------------
    slot = hypertensor.get_subnet_slot(real_id)
    if slot is None:
        print("WARNING: Subnet not yet active / no slot assigned", file=sys.stderr)
        sys.exit(0)

    print(f"[OK] Subnet slot: {slot}")

    # ------------------------------------------------------------------
    # Enumerate registered peers
    # ------------------------------------------------------------------
    nodes = hypertensor.get_subnet_nodes_info_formatted(real_id)
    if nodes is None:
        nodes = []

    for node in nodes:
        peer_id = node.peer_info.peer_id if node.peer_info else "N/A"
        hotkey = node.hotkey
        stake = node.stake_balance
        node_class = node.classification
        print(f"  peer_id={peer_id}  hotkey={hotkey}  stake={stake}  class={node_class}")

    print(f"\n{len(nodes)} nodes registered")
    sys.exit(0)


if __name__ == "__main__":
    main()
