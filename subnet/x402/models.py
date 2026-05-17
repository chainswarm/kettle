"""Pydantic models for the x402 payment protocol.

Defines the request/response schemas for HTTP 402 payment negotiation,
payment headers, pricing tiers, and settlement receipts.
"""

from __future__ import annotations

import time
import uuid
from decimal import Decimal
from typing import Any, Optional

from pydantic import BaseModel, Field


class PricingTier(BaseModel):
    """Pricing for a specific model."""

    model: str
    input_token_price_usd: Decimal = Field(
        description="Price per input token in USD (micro-cents precision)",
    )
    output_token_price_usd: Decimal = Field(
        description="Price per output token in USD (micro-cents precision)",
    )
    max_tokens_default: int = Field(
        default=256,
        description="Default max output tokens if not specified in request",
    )


class PaymentRequiredResponse(BaseModel):
    """HTTP 402 response body sent when payment is needed.

    Compatible with the x402 protocol: includes pricing info, accepted
    payment methods, and a payment address.
    """

    x402_version: int = Field(default=1, alias="x402Version")
    error: str = "payment_required"
    description: str = "Payment required for inference"
    payment_address: str = Field(
        description="Wallet address to send payment to",
        alias="paymentAddress",
    )
    pricing: dict[str, Any] = Field(
        description="Per-model pricing information",
    )
    accepted_networks: list[str] = Field(
        default_factory=lambda: ["base-sepolia"],
        description="Accepted blockchain networks",
        alias="acceptedNetworks",
    )
    accepted_tokens: list[str] = Field(
        default_factory=lambda: ["USDC"],
        description="Accepted payment tokens",
        alias="acceptedTokens",
    )
    max_amount_required: str = Field(
        description="Maximum payment amount for this request (in token base units)",
        alias="maxAmountRequired",
    )

    model_config = {"populate_by_name": True}


class PaymentHeader(BaseModel):
    """Parsed x402 payment header from an incoming request.

    The client sends payment proof in the X-PAYMENT header as a JSON
    object containing the transaction hash, network, amount, and a
    signature proving authorization.
    """

    tx_hash: str = Field(description="Transaction hash on the payment network")
    network: str = Field(description="Blockchain network (e.g. base-sepolia)")
    token: str = Field(default="USDC", description="Payment token symbol")
    amount: str = Field(description="Payment amount in token base units")
    payer: str = Field(description="Payer wallet address")
    signature: str = Field(
        default="",
        description="EIP-712 typed data signature authorizing the payment",
    )


class SettlementReceipt(BaseModel):
    """Receipt returned after successful inference with payment settlement.

    Included in the response headers so the agent can track spending.
    """

    receipt_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    tx_hash: str
    model: str
    input_tokens: int
    output_tokens: int
    amount_charged: str = Field(
        description="Actual amount charged in token base units",
    )
    amount_authorized: str = Field(
        description="Amount the payer authorized",
    )
    timestamp: float = Field(default_factory=time.time)
    status: str = "settled"


class PaymentValidationResult(BaseModel):
    """Result of validating an incoming payment header."""

    valid: bool
    payment: Optional[PaymentHeader] = None
    error: Optional[str] = None
    max_tokens_authorized: int = 0
