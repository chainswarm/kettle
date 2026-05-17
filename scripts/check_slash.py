#!/usr/bin/env python3
"""
check_slash.py — Hypertensor chain smoke-test: query overwatch commits and reveals for a given epoch.

Usage examples:
  python scripts/check_slash.py --chain wss://rpc.hypertensor.app:443 --overwatch_node_id 1 --epoch 5
  python scripts/check_slash.py --local_rpc --overwatch_node_id 1 --epoch 0
  PHRASE="word word word ..." python scripts/check_slash.py --overwatch_node_id 1 --epoch 5

Exit codes:
  0 — connected successfully; prints [OK] or [WARN] for commits and reveals
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
            "Query overwatch commits and reveals on the Hypertensor chain for a given epoch. "
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
        "--overwatch_node_id",
        type=int,
        required=True,
        metavar="INT",
        help="Overwatch node ID to query commits and reveals for.",
    )
    parser.add_argument(
        "--epoch",
        type=int,
        required=True,
        metavar="INT",
        help="Epoch number to query overwatch commits and reveals for.",
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


def main() -> None:
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
    # Query overwatch commits for the given epoch + overwatch_node_id
    # ------------------------------------------------------------------
    epoch = args.epoch
    overwatch_node_id = args.overwatch_node_id

    commits_result = hypertensor.get_overwatch_commits(epoch, overwatch_node_id)
    if commits_result is None or (hasattr(commits_result, "value") and commits_result.value is None):
        print(f"[WARN] No commits found for epoch {epoch} overwatch_node_id={overwatch_node_id}", flush=True)
    else:
        value = commits_result.value if hasattr(commits_result, "value") else commits_result
        entries = value if isinstance(value, list) else ([value] if value else [])
        if not entries:
            print(f"[WARN] No commits found for epoch {epoch} overwatch_node_id={overwatch_node_id}", flush=True)
        else:
            print(f"[OK] {len(entries)} commit(s) found for epoch {epoch} overwatch_node_id={overwatch_node_id}")
            for entry in entries:
                print(f"  {entry}")

    # ------------------------------------------------------------------
    # Query overwatch reveals for the given epoch + overwatch_node_id
    # ------------------------------------------------------------------
    reveals_result = hypertensor.get_overwatch_reveals(epoch, overwatch_node_id)
    if reveals_result is None or (hasattr(reveals_result, "value") and reveals_result.value is None):
        print(f"[WARN] No reveals found for epoch {epoch} overwatch_node_id={overwatch_node_id}", flush=True)
    else:
        value = reveals_result.value if hasattr(reveals_result, "value") else reveals_result
        entries = value if isinstance(value, list) else ([value] if value else [])
        if not entries:
            print(f"[WARN] No reveals found for epoch {epoch} overwatch_node_id={overwatch_node_id}", flush=True)
        else:
            print(f"[OK] {len(entries)} reveal(s) found for epoch {epoch} overwatch_node_id={overwatch_node_id}")
            for entry in entries:
                print(f"  {entry}")

    sys.exit(0)


if __name__ == "__main__":
    main()
