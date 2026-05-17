"""Tests for subnet.x402.app — x402-wrapped Frontier gateway."""

from __future__ import annotations

import json
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from subnet.frontier.capacity import CapacityTable
from subnet.x402.app import create_x402_app
from subnet.x402.config import X402Config
from subnet.x402.models import PricingTier


def _payment_header(amount: str = "1000000") -> str:
    return json.dumps({
        "tx_hash": "0x" + "ab" * 32,
        "network": "base-sepolia",
        "token": "USDC",
        "amount": amount,
        "payer": "0xAgentWallet",
    })


class TestX402App:
    @pytest.fixture
    def capacity(self):
        ct = CapacityTable()
        ct.update("peer-a", model="nvidia/nemotron-3-49b", load=0.3, latency_p95=890)
        return ct

    @pytest.fixture
    def config(self):
        return X402Config(
            payment_address="0xTestWallet",
            pricing_tiers=[
                PricingTier(
                    model="nvidia/nemotron-3-49b",
                    input_token_price_usd=Decimal("0.0003"),
                    output_token_price_usd=Decimal("0.0006"),
                ),
            ],
        )

    @pytest.fixture
    def client(self, capacity, config):
        app = create_x402_app(capacity_table=capacity, x402_config=config)
        return TestClient(app)

    def test_health_no_payment_needed(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    def test_models_no_payment_needed(self, client):
        resp = client.get("/v1/models")
        assert resp.status_code == 200

    def test_chat_without_payment_returns_402(self, client):
        resp = client.post(
            "/v1/chat/completions",
            json={
                "model": "nvidia/nemotron-3-49b",
                "messages": [{"role": "user", "content": "hello"}],
            },
        )
        assert resp.status_code == 402
        body = resp.json()
        assert body["paymentAddress"] == "0xTestWallet"

    def test_chat_with_payment_routes_to_node(self, client):
        resp = client.post(
            "/v1/chat/completions",
            json={
                "model": "nvidia/nemotron-3-49b",
                "messages": [{"role": "user", "content": "hello"}],
            },
            headers={"X-PAYMENT": _payment_header()},
        )
        # 501 = node selected but RA-TLS forwarding not yet implemented
        assert resp.status_code == 501
        body = resp.json()
        assert body["selected_node"] == "peer-a"

    def test_chat_with_payment_includes_receipt(self, client):
        resp = client.post(
            "/v1/chat/completions",
            json={
                "model": "nvidia/nemotron-3-49b",
                "messages": [{"role": "user", "content": "hello"}],
            },
            headers={"X-PAYMENT": _payment_header()},
        )
        assert "x-receipt" in resp.headers
        receipt = json.loads(resp.headers["x-receipt"])
        assert receipt["model"] == "nvidia/nemotron-3-49b"
        assert receipt["status"] == "settled"

    def test_app_title_is_x402(self, capacity, config):
        app = create_x402_app(capacity_table=capacity, x402_config=config)
        assert "x402" in app.title.lower()
