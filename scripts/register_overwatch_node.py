#!/usr/bin/env python3
"""
register_overwatch_node.py — Register an overwatch node on the Hypertensor chain.

Overwatch nodes audit validators and submit slash extrinsics when parity mismatches
are detected. They are a distinct node class from miners and validators, registered
via the Network::register_overwatch_node extrinsic.

Usage examples:
  python scripts/register_overwatch_node.py --hotkey 5GrwvaEF...
  python scripts/register_overwatch_node.py --chain wss://rpc.hypertensor.app:443 --hotkey 5GrwvaEF... --stake 2000000000000000000
  PHRASE="word word word ..." python scripts/register_overwatch_node.py --hotkey 5GrwvaEF...

After registration you will receive an overwatch_node_id in the receipt.
Set OVERWATCH_NODE_ID=<id> and OVERWATCH_PHRASE="<mnemonic>" in docker-compose.chain.yml
(or as env vars) to activate on-chain slash reporting.

Exit codes:
  0 — overwatch node registered successfully
  1 — connection error or registration failed

Credentials are read exclusively from env vars PHRASE / TENSOR_PRIVATE_KEY and
are never printed or logged.
"""

import argparse
import os
import sys

_DEFAULT_DEV_RPC = "wss://rpc.hypertensor.app:443"
_LOCAL_RPC = "ws://127.0.0.1:9944"


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Register an overwatch node on the Hypertensor chain. "
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
        "--hotkey",
        type=str,
        required=True,
        metavar="SS58",
        help="SS58 hotkey address for the overwatch node.",
    )
    parser.add_argument(
        "--stake",
        type=int,
        default=1000000000000000000,
        metavar="INT",
        help="Stake amount in planck (default: 1 HTSR = 1_000_000_000_000_000_000).",
    )
    return parser


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()

    # Resolve RPC URL
    if args.local_rpc:
        url = os.environ.get("LOCAL_RPC", _LOCAL_RPC)
    elif args.chain:
        url = args.chain
    else:
        url = os.environ.get("DEV_RPC", _DEFAULT_DEV_RPC)

    # Read credentials from env — never print these values
    phrase = os.environ.get("PHRASE") or os.environ.get("TENSOR_PRIVATE_KEY") or ""

    try:
        from subnet.hypertensor.chain_functions import Hypertensor
    except ImportError as exc:
        print(f"ERROR: Cannot import Hypertensor — is the subnet package installed? {exc}", file=sys.stderr)
        sys.exit(1)

    try:
        hypertensor = Hypertensor(url, phrase)
    except Exception as exc:
        print(f"ERROR: Cannot connect to {url}: {exc}", file=sys.stderr)
        sys.exit(1)

    print(f"[OK] Connected to {url}")

    try:
        receipt = hypertensor.register_overwatch_node(
            hotkey=args.hotkey,
            stake_to_be_added=args.stake,
        )
    except Exception as exc:
        print(f"ERROR: Registration exception: {exc}", file=sys.stderr)
        sys.exit(1)

    if receipt is None:
        print("ERROR: No receipt returned — extrinsic may not have been submitted.", file=sys.stderr)
        sys.exit(1)

    if receipt.is_success:
        print(f"[OK] Overwatch node registered: {receipt.extrinsic_hash}")
        print()
        print("Next steps:")
        print("  1. Note the overwatch_node_id from the on-chain event (query via Polkadot.js or check_slash.py)")
        print("  2. Set in docker-compose.chain.yml (or env):")
        print("       OVERWATCH_NODE_ID=<id>")
        print("       OVERWATCH_PHRASE=\"<your mnemonic>\"")
        sys.exit(0)
    else:
        print(f"ERROR: Registration failed: {receipt.error_message}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
