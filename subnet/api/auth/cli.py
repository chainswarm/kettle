"""CLI for managing API keys."""

import argparse
import sys

from tabulate import tabulate

from subnet.api.auth.manager import AuthManager


def main():
    """
    CLI entry point for managing API keys.

    python -m subnet.api.auth.cli add <owner> [--limit <qpm>]
    python -m subnet.api.auth.cli revoke <hash>
    python -m subnet.api.auth.cli list

    Examples:
        python -m subnet.api.auth.cli add bob --limit 60
        python -m subnet.api.auth.cli revoke <hash>
        python -m subnet.api.auth.cli list

    """
    parser = argparse.ArgumentParser(description="Manage API keys for RocksDB API")
    subparsers = parser.add_subparsers(dest="command", help="Commands")

    # Add command
    add_parser = subparsers.add_parser("add", help="Create a new API key")
    add_parser.add_argument("owner", help="Owner name for the key")
    add_parser.add_argument("--limit", type=int, help="Rate limit (QPM)")

    # Revoke command
    revoke_parser = subparsers.add_parser("revoke", help="Deactivate an API key")
    revoke_parser.add_argument("hash", help="Hash of the key to revoke")

    # List command
    subparsers.add_parser("list", help="List all API keys")

    args = parser.parse_args()
    manager = AuthManager()

    try:
        if args.command == "add":
            key = manager.create_key(args.owner, args.limit)
            print(f"✅ Success! New API Key created for '{args.owner}'")
            print(f"🔑 Key: {key}")
            print("⚠️  IMPORTANT: Copy this key now! It will NOT be shown again.")

        elif args.command == "revoke":
            if manager.revoke_key(args.hash):
                print(f"✅ Success! Key with hash {args.hash} has been revoked.")
            else:
                print(f"❌ Error: Key hash {args.hash} not found.")

        elif args.command == "list":
            keys = manager.list_keys()
            if not keys:
                print("No keys found.")
                return

            table_data = []
            for h, m in keys.items():
                table_data.append(
                    [h[:12] + "...", m.owner, m.qpm_limit, "Active" if m.is_active else "Revoked", m.created_at]
                )

            print(tabulate(table_data, headers=["Hash Prefix", "Owner", "QPM", "Status", "Created At"]))

        else:
            parser.print_help()

    except Exception as e:
        print(f"❌ Unexpected Error: {e}")
        sys.exit(1)
    finally:
        manager.close()


if __name__ == "__main__":
    main()
