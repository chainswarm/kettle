"""Tests for subnet.x402.models."""

from __future__ import annotations

from decimal import Decimal

import pytest

from subnet.x402.models import (
    PaymentHeader,
    PaymentRequiredResponse,
    PaymentValidationResult,
    PricingTier,
    SettlementReceipt,
)


class TestPricingTier:
    def test_default_max_tokens(self):
        tier = PricingTier(
            model="test/model",
            input_token_price_usd=Decimal("0.0001"),
            output_token_price_usd=Decimal("0.0002"),
        )
        assert tier.max_tokens_default == 256

    def test_custom_max_tokens(self):
        tier = PricingTier(
            model="test/model",
            input_token_price_usd=Decimal("0.0001"),
            output_token_price_usd=Decimal("0.0002"),
            max_tokens_default=512,
        )
        assert tier.max_tokens_default == 512


class TestPaymentRequiredResponse:
    def test_serialization_with_aliases(self):
        resp = PaymentRequiredResponse(
            paymentAddress="0xabc",
            pricing={"model": "test"},
            maxAmountRequired="1000",
        )
        data = resp.model_dump(by_alias=True)
        assert data["x402Version"] == 1
        assert data["paymentAddress"] == "0xabc"
        assert data["maxAmountRequired"] == "1000"
        assert data["error"] == "payment_required"

    def test_default_networks_and_tokens(self):
        resp = PaymentRequiredResponse(
            paymentAddress="0xabc",
            pricing={},
            maxAmountRequired="0",
        )
        assert "base-sepolia" in resp.accepted_networks
        assert "USDC" in resp.accepted_tokens


class TestPaymentHeader:
    def test_parse_payment(self):
        header = PaymentHeader(
            tx_hash="0x123",
            network="base-sepolia",
            token="USDC",
            amount="5000",
            payer="0xagent",
        )
        assert header.tx_hash == "0x123"
        assert header.network == "base-sepolia"
        assert header.amount == "5000"

    def test_default_token(self):
        header = PaymentHeader(
            tx_hash="0x123",
            network="base-sepolia",
            amount="5000",
            payer="0xagent",
        )
        assert header.token == "USDC"


class TestSettlementReceipt:
    def test_receipt_has_uuid(self):
        receipt = SettlementReceipt(
            tx_hash="0x123",
            model="test/model",
            input_tokens=10,
            output_tokens=50,
            amount_charged="1000",
            amount_authorized="2000",
        )
        assert receipt.receipt_id  # non-empty UUID
        assert receipt.status == "settled"
        assert receipt.timestamp > 0


class TestPaymentValidationResult:
    def test_valid_result(self):
        result = PaymentValidationResult(valid=True, max_tokens_authorized=256)
        assert result.valid is True
        assert result.error is None

    def test_invalid_result(self):
        result = PaymentValidationResult(valid=False, error="insufficient payment")
        assert result.valid is False
        assert result.error == "insufficient payment"
