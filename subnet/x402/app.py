"""x402 Frontier application — OpenAI-compatible gateway with payment layer.

Wraps the existing Frontier gateway (subnet.frontier.app) with x402
payment middleware so autonomous agents can pay per-request for inference.
"""

from __future__ import annotations

from fastapi import FastAPI

from subnet.frontier.app import create_app as create_frontier_app
from subnet.frontier.capacity import CapacityTable
from subnet.x402.config import X402Config
from subnet.x402.middleware import X402PaymentMiddleware
from subnet.x402.verification import OnChainVerifier


def create_x402_app(
    capacity_table: CapacityTable,
    x402_config: X402Config,
    *,
    api_keys: set[str] | None = None,
    on_chain_verifier: OnChainVerifier | None = None,
) -> FastAPI:
    """Create the x402-wrapped Frontier gateway.

    Parameters
    ----------
    capacity_table:
        Live routing table populated from node heartbeats.
    x402_config:
        x402 payment configuration (pricing, wallet, networks).
    api_keys:
        Allowed Bearer tokens for the underlying frontier.
        When ``None``, bearer auth is disabled (x402 is the auth layer).
    on_chain_verifier:
        Optional on-chain transaction verifier.  Falls back to
        MockOnChainVerifier for development.
    """
    app = create_frontier_app(capacity_table=capacity_table, api_keys=api_keys)

    # Override app metadata for the x402 variant
    app.title = "x402 Frontier Inference Gateway"
    app.description = "OpenAI-compatible inference with x402 payment protocol"

    # Add x402 payment middleware
    app.add_middleware(
        X402PaymentMiddleware,
        config=x402_config,
        on_chain_verifier=on_chain_verifier,
    )

    return app
