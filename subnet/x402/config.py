"""Configuration for the x402 payment middleware.

Loads pricing tiers, wallet address, and network settings from
environment variables with sensible defaults for development.
"""

from __future__ import annotations

import json
import os
from decimal import Decimal

from pydantic import BaseModel, Field

from subnet.x402.models import PricingTier


class X402Config(BaseModel):
    """x402 middleware configuration.

    All values can be overridden via environment variables:
      - X402_PAYMENT_ADDRESS: Wallet address for receiving payments
      - X402_ACCEPTED_NETWORKS: Comma-separated list of networks
      - X402_ACCEPTED_TOKENS: Comma-separated list of tokens
      - X402_PRICING_TIERS: JSON array of pricing tier objects
      - X402_REQUIRE_PAYMENT: Whether to require payment (disable for testing)
    """

    payment_address: str = Field(
        default="0x0000000000000000000000000000000000000000",
        description="Wallet address for receiving payments",
    )
    accepted_networks: list[str] = Field(
        default_factory=lambda: ["base-sepolia"],
    )
    accepted_tokens: list[str] = Field(
        default_factory=lambda: ["USDC"],
    )
    pricing_tiers: list[PricingTier] = Field(
        default_factory=lambda: [
            PricingTier(
                model="nvidia/nemotron-3-49b",
                input_token_price_usd=Decimal("0.0003"),
                output_token_price_usd=Decimal("0.0006"),
                max_tokens_default=256,
            ),
        ],
    )
    require_payment: bool = Field(
        default=True,
        description="Whether to require payment; False for dev/testing",
    )
    usdc_decimals: int = Field(
        default=6,
        description="Decimal places for USDC token",
    )

    @classmethod
    def from_env(cls) -> "X402Config":
        """Load configuration from environment variables."""
        kwargs: dict = {}

        if addr := os.getenv("X402_PAYMENT_ADDRESS"):
            kwargs["payment_address"] = addr

        if networks := os.getenv("X402_ACCEPTED_NETWORKS"):
            kwargs["accepted_networks"] = [n.strip() for n in networks.split(",") if n.strip()]

        if tokens := os.getenv("X402_ACCEPTED_TOKENS"):
            kwargs["accepted_tokens"] = [t.strip() for t in tokens.split(",") if t.strip()]

        if tiers_json := os.getenv("X402_PRICING_TIERS"):
            raw_tiers = json.loads(tiers_json)
            kwargs["pricing_tiers"] = [PricingTier(**t) for t in raw_tiers]

        if require := os.getenv("X402_REQUIRE_PAYMENT"):
            kwargs["require_payment"] = require.lower() in ("true", "1", "yes")

        return cls(**kwargs)

    def get_pricing_for_model(self, model: str) -> PricingTier | None:
        """Return the pricing tier for a model, or None if not priced."""
        for tier in self.pricing_tiers:
            if tier.model == model:
                return tier
        return None

    def estimate_max_cost(self, model: str, max_tokens: int, input_tokens: int = 100) -> int:
        """Estimate maximum cost in token base units (e.g. USDC micro-units).

        Returns the worst-case cost assuming all max_tokens are generated.
        The result is in the smallest token denomination (e.g. for USDC with
        6 decimals, 1_000_000 = 1 USDC).
        """
        tier = self.get_pricing_for_model(model)
        if tier is None:
            return 0

        input_cost = Decimal(input_tokens) * tier.input_token_price_usd
        output_cost = Decimal(max_tokens) * tier.output_token_price_usd
        total_usd = input_cost + output_cost

        # Convert USD to token base units (USDC has 6 decimals, so 1 USDC = 10^6)
        base_units = total_usd * Decimal(10**self.usdc_decimals)
        return int(base_units)
