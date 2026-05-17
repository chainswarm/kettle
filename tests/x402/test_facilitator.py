"""Tests for subnet.x402.facilitator — facilitator API client."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from subnet.x402.facilitator import FacilitatorClient, FacilitatorError
from subnet.x402.models import PaymentPayload


@pytest.fixture
def payment() -> PaymentPayload:
    return PaymentPayload(
        scheme="upto",
        network="base-sepolia",
        payload={"signature": "0xdeadbeef"},
    )


@pytest.fixture
def client() -> FacilitatorClient:
    return FacilitatorClient("https://facilitator.example.com")


def _mock_async_client(post_return: object | None = None, post_side_effect: Exception | None = None) -> AsyncMock:
    """Create a mock httpx.AsyncClient context manager."""
    mock = AsyncMock()
    if post_side_effect:
        mock.post = AsyncMock(side_effect=post_side_effect)
    else:
        mock.post = AsyncMock(return_value=post_return)
    mock.__aenter__ = AsyncMock(return_value=mock)
    mock.__aexit__ = AsyncMock(return_value=False)
    return mock


def _mock_response(*, status_code: int = 200, json_data: dict | None = None, text: str = "") -> MagicMock:
    """Create a mock httpx.Response."""
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    if json_data is not None:
        resp.json.return_value = json_data
    resp.text = text
    return resp


class TestFacilitatorVerify:
    """Tests for FacilitatorClient.verify()."""

    def test_verify_success(self, client, payment):
        """Successful verification returns SettlementResponse with success=True."""
        resp = _mock_response(json_data={"success": True, "payer": "0xpayer", "amount_settled": "100"})
        mock = _mock_async_client(post_return=resp)

        with patch("subnet.x402.facilitator.httpx.AsyncClient", return_value=mock):
            result = asyncio.run(client.verify(
                payment, pay_to="0xreceiver", resource="/v1/chat/completions", network="base-sepolia",
            ))
        assert result.success is True
        assert result.payer == "0xpayer"

    def test_verify_failure_response(self, client, payment):
        """Verification returning success=False is handled correctly."""
        resp = _mock_response(json_data={"success": False, "error": "invalid signature"})
        mock = _mock_async_client(post_return=resp)

        with patch("subnet.x402.facilitator.httpx.AsyncClient", return_value=mock):
            result = asyncio.run(client.verify(
                payment, pay_to="0xreceiver", resource="/test", network="base-sepolia",
            ))
        assert result.success is False
        assert result.error == "invalid signature"

    def test_verify_http_error(self, client, payment):
        """Non-200 status raises FacilitatorError."""
        resp = _mock_response(status_code=500, text="Internal Server Error")
        mock = _mock_async_client(post_return=resp)

        with patch("subnet.x402.facilitator.httpx.AsyncClient", return_value=mock):
            with pytest.raises(FacilitatorError) as exc_info:
                asyncio.run(client.verify(
                    payment, pay_to="0xreceiver", resource="/test", network="base-sepolia",
                ))
        assert exc_info.value.status_code == 500

    def test_verify_network_error(self, client, payment):
        """Network failure raises httpx error."""
        mock = _mock_async_client(post_side_effect=httpx.ConnectError("Connection refused"))

        with patch("subnet.x402.facilitator.httpx.AsyncClient", return_value=mock):
            with pytest.raises(httpx.ConnectError):
                asyncio.run(client.verify(
                    payment, pay_to="0xreceiver", resource="/test", network="base-sepolia",
                ))


class TestFacilitatorSettle:
    """Tests for FacilitatorClient.settle()."""

    def test_settle_success(self, client, payment):
        """Successful settlement returns transaction hash."""
        resp = _mock_response(json_data={
            "success": True, "transaction_hash": "0xtxhash123",
            "payer": "0xpayer", "amount_settled": "100",
        })
        mock = _mock_async_client(post_return=resp)

        with patch("subnet.x402.facilitator.httpx.AsyncClient", return_value=mock):
            result = asyncio.run(client.settle(
                payment, pay_to="0xreceiver", resource="/test", network="base-sepolia",
            ))
        assert result.success is True
        assert result.transaction_hash == "0xtxhash123"

    def test_settle_http_error(self, client, payment):
        """Non-200 status raises FacilitatorError."""
        resp = _mock_response(status_code=400, text="Bad Request")
        mock = _mock_async_client(post_return=resp)

        with patch("subnet.x402.facilitator.httpx.AsyncClient", return_value=mock):
            with pytest.raises(FacilitatorError) as exc_info:
                asyncio.run(client.settle(
                    payment, pay_to="0xreceiver", resource="/test", network="base-sepolia",
                ))
        assert exc_info.value.status_code == 400
