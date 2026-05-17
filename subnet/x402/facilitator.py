"""HTTP client for the x402 facilitator API.

The facilitator is an external service that verifies payment signatures and
optionally settles them on-chain.  This client wraps the two key endpoints:
- POST /verify — check that a payment payload is valid
- POST /settle — execute the on-chain transfer
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from subnet.x402.models import PaymentPayload, SettlementResponse

logger = logging.getLogger(__name__)


class FacilitatorError(Exception):
    """Raised when the facilitator API returns a non-success response."""

    def __init__(self, status_code: int, detail: str) -> None:
        self.status_code = status_code
        self.detail = detail
        super().__init__(f"Facilitator error {status_code}: {detail}")


class FacilitatorClient:
    """Async HTTP client for the x402 facilitator service.

    Parameters
    ----------
    base_url:
        Facilitator API base URL (e.g. ``https://x402.org/facilitator``).
    timeout:
        Request timeout in seconds.
    """

    def __init__(self, base_url: str, timeout: float = 30.0) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout

    async def verify(
        self,
        payment: PaymentPayload,
        *,
        pay_to: str,
        resource: str,
        network: str,
        scheme: str = "upto",
    ) -> SettlementResponse:
        """Verify a payment payload with the facilitator.

        Parameters
        ----------
        payment:
            The decoded payment from the client's X-PAYMENT header.
        pay_to:
            The receiver wallet address.
        resource:
            The resource URL being paid for.
        network:
            The blockchain network.
        scheme:
            The payment scheme.

        Returns
        -------
        SettlementResponse with success=True if the payment is valid.

        Raises
        ------
        FacilitatorError
            If the facilitator returns a non-200 response.
        httpx.HTTPError
            On network-level failures.
        """
        body: dict[str, Any] = {
            "payment": payment.model_dump(),
            "payTo": pay_to,
            "resource": resource,
            "network": network,
            "scheme": scheme,
        }

        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.post(f"{self._base_url}/verify", json=body)

        if resp.status_code != 200:
            detail = resp.text[:500]
            logger.warning("Facilitator /verify failed: %d %s", resp.status_code, detail)
            raise FacilitatorError(resp.status_code, detail)

        return SettlementResponse.model_validate(resp.json())

    async def settle(
        self,
        payment: PaymentPayload,
        *,
        pay_to: str,
        resource: str,
        network: str,
        scheme: str = "upto",
    ) -> SettlementResponse:
        """Settle a payment via the facilitator (execute on-chain transfer).

        Parameters
        ----------
        payment:
            The decoded payment from the client's X-PAYMENT header.
        pay_to:
            The receiver wallet address.
        resource:
            The resource URL being paid for.
        network:
            The blockchain network.
        scheme:
            The payment scheme.

        Returns
        -------
        SettlementResponse with transaction_hash if settlement succeeded.

        Raises
        ------
        FacilitatorError
            If the facilitator returns a non-200 response.
        httpx.HTTPError
            On network-level failures.
        """
        body: dict[str, Any] = {
            "payment": payment.model_dump(),
            "payTo": pay_to,
            "resource": resource,
            "network": network,
            "scheme": scheme,
        }

        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.post(f"{self._base_url}/settle", json=body)

        if resp.status_code != 200:
            detail = resp.text[:500]
            logger.warning("Facilitator /settle failed: %d %s", resp.status_code, detail)
            raise FacilitatorError(resp.status_code, detail)

        return SettlementResponse.model_validate(resp.json())
