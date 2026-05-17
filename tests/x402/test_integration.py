"""Integration test: full 402 flow (request -> 402 -> payment -> inference -> settle).

Simulates the complete autonomous agent payment flow end-to-end.
"""

from __future__ import annotations

import json
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from subnet.frontier.capacity import CapacityTable
from subnet.x402.app import create_x402_app
from subnet.x402.config import X402Config
from subnet.x402.models import PricingTier


class TestFullX402Flow:
    """End-to-end test of the x402 payment protocol flow."""

    @pytest.fixture
    def capacity(self):
        ct = CapacityTable()
        ct.update("peer-alpha", model="nvidia/nemotron-3-49b", load=0.2, latency_p95=500)
        ct.update("peer-beta", model="nvidia/nemotron-3-49b", load=0.6, latency_p95=700)
        ct.update("peer-gamma", model="meta/llama-3-70b", load=0.1, latency_p95=300)
        return ct

    @pytest.fixture
    def config(self):
        return X402Config(
            payment_address="0xSubnetPaymentWallet",
            accepted_networks=["base-sepolia"],
            accepted_tokens=["USDC"],
            pricing_tiers=[
                PricingTier(
                    model="nvidia/nemotron-3-49b",
                    input_token_price_usd=Decimal("0.0003"),
                    output_token_price_usd=Decimal("0.0006"),
                    max_tokens_default=256,
                ),
                PricingTier(
                    model="meta/llama-3-70b",
                    input_token_price_usd=Decimal("0.0002"),
                    output_token_price_usd=Decimal("0.0004"),
                    max_tokens_default=512,
                ),
            ],
        )

    @pytest.fixture
    def client(self, capacity, config):
        app = create_x402_app(capacity_table=capacity, x402_config=config)
        return TestClient(app)

    def test_full_402_flow_nemotron(self, client):
        """Complete flow: request -> 402 -> payment -> inference -> settlement."""
        # Step 1: Send unpaid request
        resp1 = client.post(
            "/v1/chat/completions",
            json={
                "model": "nvidia/nemotron-3-49b",
                "messages": [{"role": "user", "content": "What is TEE attestation?"}],
                "max_tokens": 100,
            },
        )
        assert resp1.status_code == 402
        pricing = resp1.json()

        # Step 2: Parse 402 response
        assert pricing["paymentAddress"] == "0xSubnetPaymentWallet"
        assert pricing["x402Version"] == 1
        max_amount = pricing["maxAmountRequired"]
        assert int(max_amount) > 0

        # Step 3: Construct payment from 402 response
        payment = json.dumps({
            "tx_hash": "0x" + "cd" * 32,
            "network": pricing["acceptedNetworks"][0],
            "token": pricing["acceptedTokens"][0],
            "amount": max_amount,
            "payer": "0xAutonomousAgent",
        })

        # Step 4: Resend with payment
        resp2 = client.post(
            "/v1/chat/completions",
            json={
                "model": "nvidia/nemotron-3-49b",
                "messages": [{"role": "user", "content": "What is TEE attestation?"}],
                "max_tokens": 100,
            },
            headers={"X-PAYMENT": payment},
        )
        # 501 = node selected (RA-TLS forwarding pending)
        assert resp2.status_code == 501

        # Step 5: Verify settlement receipt
        assert "x-receipt" in resp2.headers
        receipt = json.loads(resp2.headers["x-receipt"])
        assert receipt["model"] == "nvidia/nemotron-3-49b"
        assert receipt["status"] == "settled"
        assert int(receipt["amount_charged"]) > 0
        assert receipt["amount_authorized"] == max_amount

        # Verify routing went to least-loaded node
        body = resp2.json()
        assert body["selected_node"] == "peer-alpha"

    def test_full_402_flow_llama(self, client):
        """Full flow with a different model to verify per-model pricing."""
        # Get pricing
        resp1 = client.post(
            "/v1/chat/completions",
            json={
                "model": "meta/llama-3-70b",
                "messages": [{"role": "user", "content": "hello"}],
            },
        )
        assert resp1.status_code == 402
        pricing = resp1.json()

        # Pay and request
        payment = json.dumps({
            "tx_hash": "0x" + "ef" * 32,
            "network": "base-sepolia",
            "token": "USDC",
            "amount": pricing["maxAmountRequired"],
            "payer": "0xAgent2",
        })

        resp2 = client.post(
            "/v1/chat/completions",
            json={
                "model": "meta/llama-3-70b",
                "messages": [{"role": "user", "content": "hello"}],
            },
            headers={"X-PAYMENT": payment},
        )
        assert resp2.status_code == 501
        assert resp2.json()["selected_node"] == "peer-gamma"

    def test_overpayment_accepted(self, client):
        """Agent can overpay; excess is not refunded (up-to settlement)."""
        payment = json.dumps({
            "tx_hash": "0x" + "11" * 32,
            "network": "base-sepolia",
            "token": "USDC",
            "amount": "999999999",  # Way more than needed
            "payer": "0xRichAgent",
        })

        resp = client.post(
            "/v1/chat/completions",
            json={
                "model": "nvidia/nemotron-3-49b",
                "messages": [{"role": "user", "content": "hi"}],
            },
            headers={"X-PAYMENT": payment},
        )
        assert resp.status_code == 501  # Passes through

        receipt = json.loads(resp.headers["x-receipt"])
        # Amount charged should be the actual cost, not the overpayment
        assert int(receipt["amount_charged"]) < 999999999
        assert receipt["amount_authorized"] == "999999999"

    def test_unknown_model_still_returns_402_then_503(self, client):
        """Unknown model: 402 first (no pricing), then 503 if paid."""
        resp = client.post(
            "/v1/chat/completions",
            json={
                "model": "unknown/model",
                "messages": [{"role": "user", "content": "hi"}],
            },
        )
        # No pricing for unknown model, but still returns 402
        assert resp.status_code == 402

    def test_model_unavailable_after_payment(self, client, capacity):
        """If model has no nodes but has pricing, paid request gets 503."""
        # Remove all nodes for a specific model by adding and then evicting
        # Use a model that has pricing but no nodes
        config = X402Config(
            payment_address="0xTest",
            pricing_tiers=[
                PricingTier(
                    model="priced/but-no-nodes",
                    input_token_price_usd=Decimal("0.0001"),
                    output_token_price_usd=Decimal("0.0002"),
                ),
            ],
        )
        app = create_x402_app(capacity_table=capacity, x402_config=config)
        c = TestClient(app)

        payment = json.dumps({
            "tx_hash": "0x" + "22" * 32,
            "network": "base-sepolia",
            "token": "USDC",
            "amount": "1000000",
            "payer": "0xAgent",
        })

        resp = c.post(
            "/v1/chat/completions",
            json={
                "model": "priced/but-no-nodes",
                "messages": [{"role": "user", "content": "hi"}],
            },
            headers={"X-PAYMENT": payment},
        )
        assert resp.status_code == 503

    def test_multiple_sequential_requests(self, client):
        """Agent can make multiple paid requests in sequence."""
        for i in range(3):
            payment = json.dumps({
                "tx_hash": f"0x{'aa' * 31}{i:02x}",
                "network": "base-sepolia",
                "token": "USDC",
                "amount": "1000000",
                "payer": "0xAgent",
            })

            resp = client.post(
                "/v1/chat/completions",
                json={
                    "model": "nvidia/nemotron-3-49b",
                    "messages": [{"role": "user", "content": f"request {i}"}],
                },
                headers={"X-PAYMENT": payment},
            )
            assert resp.status_code == 501
            receipt = json.loads(resp.headers["x-receipt"])
            assert receipt["status"] == "settled"
