#!/usr/bin/env python3
"""
register_node.py — Register a node into a Hypertensor subnet on-chain.

Usage examples:
  python scripts/register_node.py --subnet_id 1 --hotkey 5GrwvaEF... --peer_id 12D3Koo...
  python scripts/register_node.py --chain wss://rpc.hypertensor.app:443 --subnet_id 1 --hotkey 5GrwvaEF... --peer_id 12D3Koo... --stake 2000000000000000000
  PHRASE="word word word ..." python scripts/register_node.py --subnet_id 1 --hotkey 5GrwvaEF... --peer_id 12D3Koo...

Exit codes:
  0 — node registered successfully
  1 — connection error or registration failed

Credentials are read exclusively from env vars PHRASE / TENSOR_PRIVATE_KEY and
are never printed or logged.

peer_info format:
  The --peer_id argument is stored as {"peer_id": <value>, "ip": "", "port": 0}.
  This is the minimal peer_info dict accepted by register_subnet_node.
  For bootnode or client peer_info pass the full dict by editing this script.
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
            "Register a node into a Hypertensor subnet. "
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
        "--local_rpc",
        action="store_true",
        help=(
            f"Shortcut: connect to the local dev node at {_LOCAL_RPC!r}. "
            "Overrides --chain and $DEV_RPC."
        ),
    )
    parser.add_argument(
        "--subnet_id",
        type=int,
        required=True,
        metavar="INT",
        help=(
            "Subnet ID to register into. Values < 128000 are treated as friendly "
            "IDs and resolved to the real chain ID automatically."
        ),
    )
    parser.add_argument(
        "--hotkey",
        type=str,
        required=True,
        metavar="SS58",
        help="SS58 hotkey address for this node.",
    )
    parser.add_argument(
        "--peer_id",
        type=str,
        required=True,
        metavar="PEER_ID",
        help="libp2p peer ID (e.g. 12D3Koo...); stored as peer_info['peer_id'].",
    )
    parser.add_argument(
        "--stake",
        type=int,
        default=1000000000000000000,
        metavar="INT",
        help="Stake amount in planck (default: 1 HTSR = 1000000000000000000).",
    )
    return parser


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()

    # ------------------------------------------------------------------
    # Resolve RPC URL (--local_rpc > --chain > $DEV_RPC > hardcoded default)
    # ------------------------------------------------------------------
    if args.local_rpc:
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
                f"ERROR: Friendly subnet_id {subnet_id} could not be resolved — subnet may not be registered.",
                file=sys.stderr,
            )
            sys.exit(1)
        real_id = int(str(real_id_result))
        print(f"[OK] Friendly subnet_id {subnet_id} resolved to chain ID {real_id}")
    else:
        real_id = subnet_id

    # ------------------------------------------------------------------
    # Build peer_info dict
    # {"peer_id": <libp2p peer ID>, "ip": "", "port": 0}
    # Extend with bootnode_peer_info / client_peer_info by editing this script.
    # ------------------------------------------------------------------
    peer_info = {"peer_id": args.peer_id, "ip": "", "port": 0}

    # ------------------------------------------------------------------
    # Register the node
    # delegate_reward_rate=0 and max_burn_amount=100 HTSR are safe defaults.
    # ------------------------------------------------------------------
    try:
        receipt = hypertensor.register_subnet_node(
            subnet_id=real_id,
            hotkey=args.hotkey,
            peer_info=peer_info,
            delegate_reward_rate=0,
            stake_to_be_added=args.stake,
            max_burn_amount=100000000000000000000,
        )
    except Exception as exc:
        print(f"ERROR: Registration exception: {exc}", file=sys.stderr)
        sys.exit(1)

    if receipt.is_success:
        print(f"[OK] Node registered: {receipt.extrinsic_hash}")
        sys.exit(0)
    else:
        print(f"ERROR: Registration failed: {receipt.error_message}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
