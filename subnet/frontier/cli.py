"""CLI entry point for the frontier router."""
import argparse
import logging
import os
import uvicorn
from subnet.frontier.app import create_app
from subnet.frontier.capacity import CapacityTable


def main() -> None:
    """Main entry point for the frontier CLI."""
    parser = argparse.ArgumentParser(description="TEE Inference Frontier")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--host", type=str, default="0.0.0.0")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    api_keys_str = os.getenv("FRONTIER_API_KEYS", "")
    api_keys = set(k.strip() for k in api_keys_str.split(",") if k.strip()) or None
    capacity_table = CapacityTable(
        staleness_threshold=float(os.getenv("FRONTIER_STALENESS_S", "6.0")),
    )
    app = create_app(capacity_table=capacity_table, api_keys=api_keys)
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
