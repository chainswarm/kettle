"""x402 Payment Required middleware for FastAPI.

Intercepts incoming requests to payment-protected endpoints. If no valid
X-PAYMENT header is present, returns HTTP 402 with pricing information
so the client (typically an autonomous agent using @x402/fetch) can
construct and submit payment.

When a valid payment is present, the request proceeds to the underlying
handler and a settlement receipt is returned in the response headers.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from typing import Any

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import JSONResponse

from subnet.x402.config import X402Config
from subnet.x402.models import PaymentRequiredResponse, SettlementReceipt
from subnet.x402.verification import MockOnChainVerifier, OnChainVerifier, validate_payment

logger = logging.getLogger(__name__)

# Endpoints that require x402 payment
PAYMENT_REQUIRED_PATHS = {"/v1/chat/completions"}


class X402PaymentMiddleware(BaseHTTPMiddleware):
    """FastAPI middleware implementing the x402 payment protocol.

    When a request hits a payment-required endpoint without a valid
    X-PAYMENT header, returns 402 with pricing details.  When payment
    is valid, passes through to the handler and attaches settlement
    receipt headers.
    """

    def __init__(
        self,
        app: Any,
        *,
        config: X402Config,
        on_chain_verifier: OnChainVerifier | None = None,
    ) -> None:
        super().__init__(app)
        self.config = config
        self.on_chain_verifier = on_chain_verifier or MockOnChainVerifier()

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        """Process request through x402 payment gate."""
        # Only gate payment-required endpoints
        if request.url.path not in PAYMENT_REQUIRED_PATHS:
            return await call_next(request)

        # Skip payment check if disabled (dev mode)
        if not self.config.require_payment:
            return await call_next(request)

        # Parse request body to determine model and max_tokens
        try:
            body = await request.json()
        except Exception:
            return JSONResponse(
                status_code=400,
                content={"error": "invalid request body"},
            )

        model = body.get("model", "")
        max_tokens = body.get("max_tokens", 256)
        messages = body.get("messages", [])

        # Rough input token estimate (4 chars per token)
        input_text = " ".join(m.get("content", "") for m in messages if isinstance(m, dict))
        input_tokens = max(len(input_text) // 4, 1)

        # Check for X-PAYMENT header
        payment_header = request.headers.get("x-payment")

        validation = await validate_payment(
            payment_header,
            config=self.config,
            model=model,
            max_tokens=max_tokens,
            input_tokens=input_tokens,
            on_chain_verifier=self.on_chain_verifier,
        )

        if not validation.valid:
            return self._build_402_response(model, max_tokens, input_tokens, validation.error)

        # Payment valid -- proceed to handler
        # Store payment info in request state for downstream use
        request.state.x402_payment = validation.payment
        request.state.x402_max_tokens = validation.max_tokens_authorized
        request.state.x402_input_tokens = input_tokens

        response = await call_next(request)

        # Attach settlement receipt header
        if validation.payment is not None:
            receipt = SettlementReceipt(
                receipt_id=str(uuid.uuid4()),
                tx_hash=validation.payment.tx_hash,
                model=model,
                input_tokens=input_tokens,
                output_tokens=max_tokens,  # Actual count from inference in production
                amount_charged=str(
                    self.config.estimate_max_cost(model, max_tokens, input_tokens),
                ),
                amount_authorized=validation.payment.amount,
                timestamp=time.time(),
            )
            response.headers["X-RECEIPT"] = receipt.model_dump_json()

        return response

    def _build_402_response(
        self,
        model: str,
        max_tokens: int,
        input_tokens: int,
        error: str | None = None,
    ) -> JSONResponse:
        """Build the 402 Payment Required response with pricing info."""
        tier = self.config.get_pricing_for_model(model)
        if tier is not None:
            pricing = {
                "model": model,
                "inputTokenPriceUsd": str(tier.input_token_price_usd),
                "outputTokenPriceUsd": str(tier.output_token_price_usd),
                "estimatedMaxTokens": max_tokens,
                "estimatedInputTokens": input_tokens,
            }
        else:
            pricing = {
                "model": model,
                "error": "no pricing available for this model",
            }

        max_cost = self.config.estimate_max_cost(model, max_tokens, input_tokens)

        body = PaymentRequiredResponse(
            paymentAddress=self.config.payment_address,
            pricing=pricing,
            acceptedNetworks=self.config.accepted_networks,
            acceptedTokens=self.config.accepted_tokens,
            maxAmountRequired=str(max_cost),
        )

        headers = {
            "X-PAYMENT-REQUIRED": "true",
            "X-PAYMENT-ADDRESS": self.config.payment_address,
            "X-PAYMENT-AMOUNT": str(max_cost),
            "X-PAYMENT-NETWORKS": ",".join(self.config.accepted_networks),
            "X-PAYMENT-TOKENS": ",".join(self.config.accepted_tokens),
        }
        if error:
            headers["X-PAYMENT-ERROR"] = error

        return JSONResponse(
            status_code=402,
            content=body.model_dump(by_alias=True),
            headers=headers,
        )
