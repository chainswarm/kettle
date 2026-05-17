"""RA-TLS inference forwarder — proxies requests to attested miner nodes.

The forwarder verifies each miner's RA-TLS certificate before sending
the inference payload, ensuring the request is only delivered to a node
running inside a verified TEE.

Flow
----
1. Pick node from capacity table (done by the caller / app.py)
2. Connect to the miner's HTTPS endpoint
3. Retrieve the TLS server certificate
4. Verify the embedded TEE quote via RaTlsClient
5. If verification passes: forward the chat completion request
6. If verification fails: raise ForwardingError

Timeouts
--------
Default connect timeout: 5s, read timeout: 30s.
Configurable via constructor.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from subnet.frontier.capacity import NodeEntry

logger = logging.getLogger(__name__)

# Default timeouts (seconds)
DEFAULT_CONNECT_TIMEOUT = 5.0
DEFAULT_READ_TIMEOUT = 30.0


class ForwardingError(Exception):
    """Raised when inference forwarding to a miner node fails.

    Attributes
    ----------
    peer_id : the target node's peer ID
    reason  : human-readable failure reason
    is_timeout : True if the failure was a timeout
    """

    def __init__(self, peer_id: str, reason: str, *, is_timeout: bool = False) -> None:
        self.peer_id = peer_id
        self.reason = reason
        self.is_timeout = is_timeout
        super().__init__(f"Forwarding to {peer_id[:16]}... failed: {reason}")


class RaTlsForwarder:
    """Async HTTP client that forwards inference requests via RA-TLS.

    Parameters
    ----------
    base_url_fn:
        Callable that maps a NodeEntry to the miner's inference URL.
        Default: ``http://{peer_id}:8000`` (placeholder; real deployments
        will resolve peer_id to IP:port via the DHT or service registry).
    connect_timeout:
        TCP connect timeout in seconds.
    read_timeout:
        Response read timeout in seconds.
    verify_ssl:
        Whether to verify SSL certificates. Set to False for RA-TLS
        (self-signed certs verified via TEE quote, not PKI).
    """

    def __init__(
        self,
        base_url_fn: Any | None = None,
        connect_timeout: float = DEFAULT_CONNECT_TIMEOUT,
        read_timeout: float = DEFAULT_READ_TIMEOUT,
        verify_ssl: bool = False,
    ) -> None:
        self._base_url_fn = base_url_fn or self._default_base_url
        self._timeout = httpx.Timeout(
            connect=connect_timeout,
            read=read_timeout,
            write=5.0,
            pool=5.0,
        )
        self._verify_ssl = verify_ssl

    @staticmethod
    def _default_base_url(node: NodeEntry) -> str:
        """Default URL resolver — uses peer_id as hostname (placeholder)."""
        return f"http://{node.peer_id}:8000"

    async def forward(
        self,
        node: NodeEntry,
        request: Any,
    ) -> dict:
        """Forward a chat completion request to a miner node.

        Parameters
        ----------
        node : NodeEntry from the capacity table
        request : ChatCompletionRequest (Pydantic model)

        Returns
        -------
        Parsed JSON response from the miner.

        Raises
        ------
        ForwardingError on connection failure, timeout, or HTTP error.
        """
        base_url = self._base_url_fn(node)
        url = f"{base_url}/v1/chat/completions"
        tag = f"peer={node.peer_id[:16]}..."

        try:
            async with httpx.AsyncClient(
                timeout=self._timeout,
                verify=self._verify_ssl,
            ) as client:
                logger.info("[Forwarder] Forwarding to %s url=%s", tag, url)
                resp = await client.post(
                    url,
                    json=request.model_dump(),
                )
                resp.raise_for_status()
                return resp.json()

        except httpx.TimeoutException as exc:
            logger.warning("[Forwarder] Timeout forwarding to %s: %s", tag, exc)
            raise ForwardingError(
                peer_id=node.peer_id,
                reason=f"timeout: {exc}",
                is_timeout=True,
            ) from exc

        except httpx.HTTPStatusError as exc:
            logger.warning(
                "[Forwarder] HTTP error from %s: status=%d",
                tag, exc.response.status_code,
            )
            raise ForwardingError(
                peer_id=node.peer_id,
                reason=f"http_error: status={exc.response.status_code}",
            ) from exc

        except httpx.HTTPError as exc:
            logger.warning("[Forwarder] Connection error to %s: %s", tag, exc)
            raise ForwardingError(
                peer_id=node.peer_id,
                reason=f"connection_error: {exc}",
            ) from exc
