"""Payment verification for x402 protocol.

Validates incoming payment headers: checks that the transaction hash,
network, token, and amount are valid and sufficient for the requested
inference operation.

NOTE: In production, this would verify on-chain transaction status via
an RPC provider.  For now, verification checks structural validity and
amount sufficiency, with a pluggable verifier for on-chain checks.
"""

from __future__ import annotations

import json
import logging
from typing import Protocol

from subnet.x402.config import X402Config
from subnet.x402.models import PaymentHeader, PaymentValidationResult

logger = logging.getLogger(__name__)


class OnChainVerifier(Protocol):
    """Protocol for on-chain payment verification.

    Implementations should check transaction status on the actual
    blockchain network.
    """

    async def verify_transaction(self, tx_hash: str, network: str, expected_amount: int) -> bool:
        """Return True if the transaction is confirmed and amount matches."""
        ...


class MockOnChainVerifier:
    """Development verifier that accepts all structurally valid payments."""

    async def verify_transaction(self, tx_hash: str, network: str, expected_amount: int) -> bool:
        """Accept any transaction with a non-empty hash."""
        return bool(tx_hash and len(tx_hash) >= 10)


def parse_payment_header(raw_header: str) -> PaymentHeader | None:
    """Parse the X-PAYMENT header value into a PaymentHeader.

    The header value is a JSON string containing payment proof fields.
    Returns None if parsing fails.
    """
    try:
        data = json.loads(raw_header)
        return PaymentHeader(**data)
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        logger.debug("Failed to parse X-PAYMENT header: %s", exc)
        return None


async def validate_payment(
    raw_header: str | None,
    *,
    config: X402Config,
    model: str,
    max_tokens: int,
    input_tokens: int = 100,
    on_chain_verifier: OnChainVerifier | None = None,
) -> PaymentValidationResult:
    """Validate an x402 payment header against the request parameters.

    Checks:
    1. Header is present and parseable
    2. Network is accepted
    3. Token is accepted
    4. Amount is sufficient for the requested model/tokens
    5. On-chain verification (if verifier provided)
    """
    if raw_header is None:
        return PaymentValidationResult(valid=False, error="missing X-PAYMENT header")

    payment = parse_payment_header(raw_header)
    if payment is None:
        return PaymentValidationResult(valid=False, error="malformed X-PAYMENT header")

    # Check network
    if payment.network not in config.accepted_networks:
        return PaymentValidationResult(
            valid=False,
            payment=payment,
            error=f"unsupported network: {payment.network}",
        )

    # Check token
    if payment.token not in config.accepted_tokens:
        return PaymentValidationResult(
            valid=False,
            payment=payment,
            error=f"unsupported token: {payment.token}",
        )

    # Check amount sufficiency
    required_amount = config.estimate_max_cost(model, max_tokens, input_tokens)
    try:
        paid_amount = int(payment.amount)
    except (ValueError, TypeError):
        return PaymentValidationResult(
            valid=False,
            payment=payment,
            error="invalid payment amount",
        )

    if paid_amount < required_amount:
        return PaymentValidationResult(
            valid=False,
            payment=payment,
            error=f"insufficient payment: {paid_amount} < {required_amount}",
        )

    # Calculate how many output tokens the payment authorizes
    tier = config.get_pricing_for_model(model)
    if tier is not None and tier.output_token_price_usd > 0:
        from decimal import Decimal

        paid_dec = Decimal(paid_amount)
        input_cost = Decimal(input_tokens) * tier.input_token_price_usd * Decimal(10**config.usdc_decimals)
        remaining = paid_dec - input_cost
        per_token = tier.output_token_price_usd * Decimal(10**config.usdc_decimals)
        max_tokens_authorized = int(remaining / per_token) if per_token > 0 else max_tokens
    else:
        max_tokens_authorized = max_tokens

    # On-chain verification (optional)
    if on_chain_verifier is not None:
        verified = await on_chain_verifier.verify_transaction(
            payment.tx_hash,
            payment.network,
            required_amount,
        )
        if not verified:
            return PaymentValidationResult(
                valid=False,
                payment=payment,
                error="on-chain verification failed",
            )

    return PaymentValidationResult(
        valid=True,
        payment=payment,
        max_tokens_authorized=max_tokens_authorized,
    )
