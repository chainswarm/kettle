#!/usr/bin/env python3
"""
register_subnet.py — Register a new Hypertensor subnet on-chain.

Usage examples:
  python scripts/register_subnet.py --name "my-subnet"
  python scripts/register_subnet.py --chain wss://rpc.hypertensor.app:443 --name "my-subnet" --repo "https://github.com/..."
  PHRASE="word word word ..." python scripts/register_subnet.py --name "my-subnet"

Exit codes:
  0 — subnet registered successfully
  1 — connection error or registration failed

Credentials are read exclusively from env vars PHRASE / TENSOR_PRIVATE_KEY and
are never printed or logged.

Notes:
  --initial_coldkeys and --bootnodes are not currently exposed as CLI args;
  edit the script directly if you need non-empty values for those parameters.
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
            "Register a new subnet on the Hypertensor chain. "
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
        "--name",
        type=str,
        required=True,
        metavar="STR",
        help="Human-readable name of the subnet (required).",
    )
    parser.add_argument(
        "--repo",
        type=str,
        default="",
        metavar="STR",
        help="Repository URL for the subnet (default: empty string).",
    )
    parser.add_argument(
        "--description",
        type=str,
        default="",
        metavar="STR",
        help="Short description of the subnet (default: empty string).",
    )
    parser.add_argument(
        "--misc",
        type=str,
        default="",
        metavar="STR",
        help="Miscellaneous metadata field (default: empty string).",
    )
    parser.add_argument(
        "--max_cost",
        type=int,
        default=100000000000000000000,
        metavar="INT",
        help="Maximum registration cost in planck (default: 100 HTSR).",
    )
    parser.add_argument(
        "--min_stake",
        type=int,
        default=1000000000000000000,
        metavar="INT",
        help="Minimum node stake in planck (default: 1 HTSR).",
    )
    parser.add_argument(
        "--max_stake",
        type=int,
        default=100000000000000000000,
        metavar="INT",
        help="Maximum node stake in planck (default: 100 HTSR).",
    )
    parser.add_argument(
        "--delegate_stake_percentage",
        type=int,
        default=10,
        metavar="INT",
        help="Percentage of rewards delegated to stakers (default: 10).",
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
    # Register the subnet
    # initial_coldkeys and bootnodes use empty lists by default.
    # Extend this script if you need non-empty values.
    # ------------------------------------------------------------------
    try:
        receipt = hypertensor.register_subnet(
            max_cost=args.max_cost,
            name=args.name,
            repo=args.repo,
            description=args.description,
            misc=args.misc,
            min_stake=args.min_stake,
            max_stake=args.max_stake,
            delegate_stake_percentage=args.delegate_stake_percentage,
            initial_coldkeys=[],
            bootnodes=[],
        )
    except Exception as exc:
        print(f"ERROR: Registration exception: {exc}", file=sys.stderr)
        sys.exit(1)

    if receipt.is_success:
        print(f"[OK] Subnet registered: {receipt.extrinsic_hash}")
        sys.exit(0)
    else:
        print(f"ERROR: Registration failed: {receipt.error_message}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
