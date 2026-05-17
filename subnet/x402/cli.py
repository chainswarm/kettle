"""CLI entry point for the x402 frontier gateway."""

import argparse
import logging
import os

import uvicorn

from subnet.frontier.capacity import CapacityTable
from subnet.x402.app import create_x402_app
from subnet.x402.config import X402Config


def main() -> None:
    """Start the x402 frontier gateway."""
    parser = argparse.ArgumentParser(
        description="x402 Frontier — OpenAI-compatible inference with payment",
    )
    parser.add_argument("--port", type=int, default=8402)
    parser.add_argument("--host", type=str, default="0.0.0.0")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(levelname)8s  %(asctime)s  %(name)s  %(message)s",
    )

    # Load x402 config from environment
    x402_config = X402Config.from_env()

    # Optional bearer auth on top of x402 (usually not needed when x402 is the gate)
    api_keys_str = os.getenv("FRONTIER_API_KEYS", "")
    api_keys = set(k.strip() for k in api_keys_str.split(",") if k.strip()) or None

    # Create capacity table (populated by heartbeat handler in production)
    capacity_table = CapacityTable(
        staleness_threshold=float(os.getenv("FRONTIER_STALENESS_S", "6.0")),
    )

    app = create_x402_app(
        capacity_table=capacity_table,
        x402_config=x402_config,
        api_keys=api_keys,
    )

    logging.getLogger(__name__).info(
        "Starting x402 frontier on %s:%d (payment=%s)",
        args.host,
        args.port,
        "required" if x402_config.require_payment else "disabled",
    )

    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
