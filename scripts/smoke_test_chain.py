#!/usr/bin/env python3
"""
smoke_test_chain.py — Run all chain smoke-test scripts and report pass/fail.

Delegates to check_peers.py, check_scores.py, and check_slash.py.
Each sub-check runs as a subprocess; individual errors are printed by the
delegated script. This script summarises results and exits 0 (all pass)
or 1 (any fail).

Usage examples:
  python scripts/smoke_test_chain.py --local_rpc --subnet_id 1 --epoch 0 --overwatch_node_id 1
  python scripts/smoke_test_chain.py --chain wss://rpc.hypertensor.app:443 --subnet_id 1 --epoch 5 --overwatch_node_id 1

Exit codes:
  0 — all sub-checks passed
  1 — one or more sub-checks failed (or chain unreachable)

Sub-checks never raise unhandled exceptions — each runs with check=False and
failures are captured as [FAIL] lines with the script's exit code.
"""

import argparse
import os
import subprocess
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# RPC URL constants (matching the existing CLI convention in subnet/cli/)
# ---------------------------------------------------------------------------
_DEFAULT_DEV_RPC = "wss://rpc.hypertensor.app:443"
_LOCAL_RPC = "ws://127.0.0.1:9944"

# Resolve scripts directory relative to this file
_SCRIPTS_DIR = Path(__file__).parent


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run all chain smoke-test sub-checks (check_peers, check_scores, check_slash) "
            "and print [PASS] / [FAIL] for each. Exits 0 if all pass, 1 if any fail."
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
        help="Subnet ID to check (passed to check_peers and check_scores).",
    )
    parser.add_argument(
        "--epoch",
        type=int,
        required=True,
        metavar="INT",
        help="Epoch number to check (passed to check_scores and check_slash).",
    )
    parser.add_argument(
        "--overwatch_node_id",
        type=int,
        required=True,
        metavar="INT",
        help="Overwatch node ID to check (passed to check_slash).",
    )
    return parser


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()

    # ------------------------------------------------------------------
    # Resolve RPC URL flag to pass through to sub-scripts
    # (--local_rpc > --chain > $DEV_RPC > hardcoded default)
    # ------------------------------------------------------------------
    if args.local_rpc:
        url_flag = "--local_rpc"
    elif args.chain:
        url_flag = f"--chain={args.chain}"
    else:
        url = os.environ.get("DEV_RPC", _DEFAULT_DEV_RPC)
        url_flag = f"--chain={url}"

    # ------------------------------------------------------------------
    # Sub-checks: (script_name, extra_args)
    # ------------------------------------------------------------------
    sub_checks = [
        (
            "check_peers.py",
            [url_flag, "--subnet_id", str(args.subnet_id)],
        ),
        (
            "check_scores.py",
            [url_flag, "--subnet_id", str(args.subnet_id), "--epoch", str(args.epoch)],
        ),
        (
            "check_slash.py",
            [url_flag, "--overwatch_node_id", str(args.overwatch_node_id), "--epoch", str(args.epoch)],
        ),
    ]

    failed = []
    for script_name, extra_args in sub_checks:
        script_path = str(_SCRIPTS_DIR / script_name)
        cmd = [sys.executable, script_path] + extra_args
        result = subprocess.run(cmd, check=False, capture_output=False)
        if result.returncode == 0:
            print(f"[PASS] {script_name}")
        else:
            print(f"[FAIL] {script_name} (exit {result.returncode})")
            failed.append(script_name)

    if failed:
        sys.exit(1)
    else:
        sys.exit(0)


if __name__ == "__main__":
    main()
