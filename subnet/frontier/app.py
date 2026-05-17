"""Frontier FastAPI application — OpenAI-compatible inference gateway.

Routes chat-completion requests to the least-loaded node in the capacity
table.  When an RaTlsForwarder is provided, requests are forwarded to
miner nodes via RA-TLS verified channels.  Without a forwarder, the
routing logic returns 501 with the selected peer_id (development mode).

The optional /attestation endpoint exposes the gateway's own TEE quote,
proving to callers that the gateway itself runs inside a TEE.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Optional

from fastapi import Depends, FastAPI, Header, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from subnet.frontier.capacity import CapacityTable
from subnet.tee.backends.base import TeeBackendBase

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Request schema
# ---------------------------------------------------------------------------


class ChatCompletionRequest(BaseModel):
    model: str
    messages: list[dict]
    max_tokens: int = 256
    temperature: float = 0.7
    stream: bool = False


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def create_app(
    capacity_table: CapacityTable,
    api_keys: set[str] | None = None,
    tee_backend: TeeBackendBase | None = None,
    gateway_peer_id: str | None = None,
    epoch_fn: Callable[[], int] | None = None,
    forwarder: "Optional[RaTlsForwarder]" = None,
) -> FastAPI:
    """Create and return the configured FastAPI application.

    Parameters
    ----------
    capacity_table:
        Live routing table populated from node heartbeats.
    api_keys:
        Allowed Bearer tokens.  When ``None``, authentication is disabled.
    tee_backend:
        TEE backend for generating the gateway's own attestation quote.
        When ``None``, the ``/attestation`` endpoint returns 503.
    gateway_peer_id:
        The gateway's own libp2p peer ID (used in attestation quotes).
    epoch_fn:
        Callable returning the current epoch number.
    forwarder:
        RA-TLS forwarder for proxying inference requests to miner nodes.
        When ``None``, chat completions return 501 (development mode).
    """
    # Lazy import to avoid circular dependency at module level
    from subnet.frontier.forwarder import RaTlsForwarder, ForwardingError

    app = FastAPI(title="Frontier Inference Gateway", version="0.2.0")

    # ------------------------------------------------------------------
    # Auth dependency
    # ------------------------------------------------------------------

    async def require_auth(authorization: str | None = Header(default=None)) -> None:
        """Raise 401 if api_keys is configured and the token is missing/invalid."""
        if api_keys is None:
            return
        if authorization is None:
            raise HTTPException(status_code=401, detail="missing authorization header")
        scheme, _, token = authorization.partition(" ")
        if scheme.lower() != "bearer" or token not in api_keys:
            raise HTTPException(status_code=401, detail="invalid or missing bearer token")

    # ------------------------------------------------------------------
    # Endpoints
    # ------------------------------------------------------------------

    @app.get("/health")
    async def health() -> dict[str, Any]:
        """Unauthenticated health check — returns status and available models."""
        return {"status": "ok", "models": sorted(capacity_table.all_models())}

    @app.get("/attestation")
    async def attestation() -> JSONResponse:
        """Return the gateway's own TEE attestation quote.

        This endpoint is unauthenticated — anyone can verify the gateway
        runs inside a TEE.  Returns 503 if no TEE backend is configured.
        """
        if tee_backend is None or gateway_peer_id is None or epoch_fn is None:
            return JSONResponse(
                status_code=503,
                content={"error": "attestation_unavailable", "detail": "TEE backend not configured"},
            )

        try:
            epoch = epoch_fn()
            quote = tee_backend.generate_quote(peer_id=gateway_peer_id, epoch=epoch)
            return JSONResponse(
                status_code=200,
                content={
                    "backend": quote.backend.value,
                    "measurement": quote.measurement,
                    "report_data": quote.report_data,
                    "peer_id": quote.peer_id,
                    "epoch": quote.nonce,
                    "timestamp": quote.timestamp,
                    "debug_mode": quote.debug_mode,
                    "hardware_id": quote.hardware_id,
                    "sig": quote.sig,
                },
            )
        except Exception as exc:
            logger.error("[Frontier] Failed to generate attestation quote: %s", exc)
            return JSONResponse(
                status_code=500,
                content={"error": "attestation_failed", "detail": str(exc)},
            )

    @app.get("/v1/models", dependencies=[Depends(require_auth)])
    async def list_models() -> dict[str, Any]:
        """OpenAI-compatible models list."""
        models = sorted(capacity_table.all_models())
        return {
            "object": "list",
            "data": [
                {
                    "id": m,
                    "object": "model",
                    "owned_by": "frontier",
                }
                for m in models
            ],
        }

    @app.post("/v1/chat/completions", dependencies=[Depends(require_auth)])
    async def chat_completions(request: ChatCompletionRequest) -> JSONResponse:
        """Route a chat-completion request to the least-loaded available node.

        Returns
        -------
        200  success              -- forwarded response from miner node
        429  capacity_exceeded    -- all nodes for the model exceed 90% load
        501  not_implemented      -- no forwarder configured (dev mode)
        502  forwarding_error     -- RA-TLS verification or connection failure
        503  model_unavailable    -- no nodes serve the requested model
        504  gateway_timeout      -- miner node did not respond in time
        """
        model = request.model
        nodes = capacity_table.nodes_for_model(model)

        if not nodes:
            return JSONResponse(
                status_code=503,
                content={"error": "model_unavailable"},
            )

        if capacity_table.is_overloaded(model):
            return JSONResponse(
                status_code=429,
                content={"error": "capacity_exceeded", "retry_after": 5},
            )

        node = capacity_table.pick_node(model)
        # pick_node always returns a value here (we already confirmed nodes exist
        # and not all are overloaded), but guard for type safety.
        if node is None:  # pragma: no cover
            return JSONResponse(
                status_code=503,
                content={"error": "model_unavailable"},
            )

        # If no forwarder, return 501 (development mode / backward compat)
        if forwarder is None:
            return JSONResponse(
                status_code=501,
                content={"error": "not_implemented", "selected_node": node.peer_id},
            )

        # Forward via RA-TLS
        try:
            result = await forwarder.forward(node=node, request=request)
            return JSONResponse(
                status_code=200,
                content=result,
                headers={"X-Selected-Node": node.peer_id},
            )
        except ForwardingError as exc:
            if exc.is_timeout:
                return JSONResponse(
                    status_code=504,
                    content={
                        "error": "gateway_timeout",
                        "detail": str(exc),
                        "selected_node": node.peer_id,
                    },
                    headers={"X-Selected-Node": node.peer_id},
                )
            return JSONResponse(
                status_code=502,
                content={
                    "error": "forwarding_error",
                    "detail": str(exc),
                    "selected_node": node.peer_id,
                },
                headers={"X-Selected-Node": node.peer_id},
            )

    return app
