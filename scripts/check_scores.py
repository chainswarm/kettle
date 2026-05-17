#!/usr/bin/env python3
"""
check_scores.py — Hypertensor chain smoke-test: query SubnetConsensusSubmission for a given epoch.

Usage examples:
  python scripts/check_scores.py --chain wss://rpc.hypertensor.app:443 --subnet_id 1 --epoch 5
  python scripts/check_scores.py --local_rpc --subnet_id 1 --epoch 0
  PHRASE="word word word ..." python scripts/check_scores.py --subnet_id 1 --epoch 5

Exit codes:
  0 — connected successfully; prints [OK] with entry count or [WARN] if no scores found
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
            "Query SubnetConsensusSubmission for a Hypertensor subnet epoch. "
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
        "--epoch",
        type=int,
        required=True,
        metavar="INT",
        help="Epoch number to query SubnetConsensusSubmission for.",
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
    # Query SubnetConsensusSubmission for the given epoch
    # ------------------------------------------------------------------
    epoch = args.epoch
    result = hypertensor.get_rewards_submission(real_id, epoch)

    # ------------------------------------------------------------------
    # Inspect SCALE result — handle None / empty / decoded value
    # ------------------------------------------------------------------
    if result is None or result.value is None:
        print(f"[WARN] No scores found for epoch {epoch}", flush=True)
        sys.exit(0)

    value = result.value
    if isinstance(value, dict):
        entries = value.get("data", [])
    elif isinstance(value, list):
        entries = value
    else:
        entries = []

    if not entries:
        print(f"[WARN] No scores found for epoch {epoch}", flush=True)
        sys.exit(0)

    print(f"[OK] Scores found for epoch {epoch}: {len(entries)} entries")
    for entry in entries:
        if isinstance(entry, dict):
            print(f"  subnet_node_id={entry.get('subnet_node_id', '?')}  score={entry.get('score', '?')}")
        else:
            print(f"  {entry}")

    sys.exit(0)


if __name__ == "__main__":
    main()
