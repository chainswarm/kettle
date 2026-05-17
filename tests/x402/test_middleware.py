"""Tests for subnet.x402.middleware — payment gating logic."""

from __future__ import annotations

import json
from decimal import Decimal

import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from subnet.x402.config import X402Config
from subnet.x402.middleware import X402PaymentMiddleware
from subnet.x402.models import PricingTier


def _make_test_app(config: X402Config | None = None) -> FastAPI:
    """Create a minimal FastAPI app with x402 middleware for testing."""
    app = FastAPI()

    cfg = config or X402Config(
        payment_address="0xTestWallet",
        pricing_tiers=[
            PricingTier(
                model="test/model",
                input_token_price_usd=Decimal("0.0001"),
                output_token_price_usd=Decimal("0.0002"),
            ),
        ],
    )

    @app.post("/v1/chat/completions")
    async def chat_completions():
        return JSONResponse(
            status_code=200,
            content={"choices": [{"message": {"content": "hello"}}]},
        )

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    app.add_middleware(X402PaymentMiddleware, config=cfg)
    return app


def _payment_header(amount: str = "1000000", tx_hash: str = "0x" + "ab" * 32) -> str:
    return json.dumps({
        "tx_hash": tx_hash,
        "network": "base-sepolia",
        "token": "USDC",
        "amount": amount,
        "payer": "0xAgentWallet",
    })


class TestX402Middleware:
    @pytest.fixture
    def client(self):
        return TestClient(_make_test_app())

    def test_health_bypasses_payment(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200

    def test_unpaid_request_returns_402(self, client):
        resp = client.post(
            "/v1/chat/completions",
            json={"model": "test/model", "messages": [{"role": "user", "content": "hi"}]},
        )
        assert resp.status_code == 402
        body = resp.json()
        assert body["error"] == "payment_required"
        assert body["paymentAddress"] == "0xTestWallet"
        assert "maxAmountRequired" in body

    def test_402_includes_pricing_headers(self, client):
        resp = client.post(
            "/v1/chat/completions",
            json={"model": "test/model", "messages": [{"role": "user", "content": "hi"}]},
        )
        assert resp.headers.get("x-payment-required") == "true"
        assert resp.headers.get("x-payment-address") == "0xTestWallet"
        assert resp.headers.get("x-payment-networks") == "base-sepolia"
        assert resp.headers.get("x-payment-tokens") == "USDC"

    def test_paid_request_passes_through(self, client):
        resp = client.post(
            "/v1/chat/completions",
            json={"model": "test/model", "messages": [{"role": "user", "content": "hi"}]},
            headers={"X-PAYMENT": _payment_header()},
        )
        assert resp.status_code == 200
        assert "x-receipt" in resp.headers

    def test_insufficient_payment_returns_402(self, client):
        resp = client.post(
            "/v1/chat/completions",
            json={"model": "test/model", "messages": [{"role": "user", "content": "hi"}]},
            headers={"X-PAYMENT": _payment_header(amount="1")},
        )
        assert resp.status_code == 402
        assert "insufficient" in resp.headers.get("x-payment-error", "")

    def test_malformed_payment_returns_402(self, client):
        resp = client.post(
            "/v1/chat/completions",
            json={"model": "test/model", "messages": [{"role": "user", "content": "hi"}]},
            headers={"X-PAYMENT": "not-json"},
        )
        assert resp.status_code == 402

    def test_wrong_network_returns_402(self, client):
        payment = json.dumps({
            "tx_hash": "0x" + "ab" * 32,
            "network": "ethereum-mainnet",
            "token": "USDC",
            "amount": "1000000",
            "payer": "0xAgentWallet",
        })
        resp = client.post(
            "/v1/chat/completions",
            json={"model": "test/model", "messages": [{"role": "user", "content": "hi"}]},
            headers={"X-PAYMENT": payment},
        )
        assert resp.status_code == 402
        assert "unsupported network" in resp.headers.get("x-payment-error", "")

    def test_payment_disabled_passes_through(self):
        config = X402Config(
            payment_address="0xTestWallet",
            require_payment=False,
        )
        client = TestClient(_make_test_app(config))
        resp = client.post(
            "/v1/chat/completions",
            json={"model": "test/model", "messages": [{"role": "user", "content": "hi"}]},
        )
        assert resp.status_code == 200

    def test_settlement_receipt_in_response(self, client):
        resp = client.post(
            "/v1/chat/completions",
            json={"model": "test/model", "messages": [{"role": "user", "content": "hi"}]},
            headers={"X-PAYMENT": _payment_header()},
        )
        assert resp.status_code == 200
        receipt = json.loads(resp.headers["x-receipt"])
        assert receipt["status"] == "settled"
        assert receipt["model"] == "test/model"
        assert "receipt_id" in receipt
        assert "amount_charged" in receipt
