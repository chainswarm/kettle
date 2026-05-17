"""Tests for the /attestation endpoint and RA-TLS forwarder integration."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from fastapi.testclient import TestClient

from subnet.frontier.app import ChatCompletionRequest, create_app
from subnet.frontier.capacity import CapacityTable, NodeEntry
from subnet.frontier.forwarder import ForwardingError, RaTlsForwarder
from subnet.tee.backends.mock import MockBackend


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_backend():
    return MockBackend()


@pytest.fixture
def capacity():
    ct = CapacityTable()
    ct.update("peer-a", model="nvidia/nemotron-3-49b", load=0.3, latency_p95=890)
    ct.update("peer-b", model="nvidia/nemotron-3-49b", load=0.7, latency_p95=920)
    return ct


# ---------------------------------------------------------------------------
# /attestation endpoint tests
# ---------------------------------------------------------------------------


class TestAttestationEndpoint:
    """Tests for GET /attestation."""

    def test_attestation_with_mock_backend(self, capacity, mock_backend):
        """GET /attestation returns valid quote JSON with mock backend."""
        app = create_app(
            capacity_table=capacity,
            tee_backend=mock_backend,
            gateway_peer_id="gateway-peer-001",
            epoch_fn=lambda: 42,
        )
        client = TestClient(app)
        resp = client.get("/attestation")
        assert resp.status_code == 200
        body = resp.json()
        assert body["backend"] == "mock"
        assert body["peer_id"] == "gateway-peer-001"
        assert body["epoch"] == 42
        assert "measurement" in body
        assert "report_data" in body
        assert "sig" in body
        assert "timestamp" in body
        assert body["debug_mode"] is False

    def test_attestation_without_backend(self, capacity):
        """GET /attestation returns 503 when no TEE backend configured."""
        app = create_app(capacity_table=capacity)
        client = TestClient(app)
        resp = client.get("/attestation")
        assert resp.status_code == 503
        body = resp.json()
        assert body["error"] == "attestation_unavailable"

    def test_attestation_without_peer_id(self, capacity, mock_backend):
        """GET /attestation returns 503 when gateway_peer_id is missing."""
        app = create_app(
            capacity_table=capacity,
            tee_backend=mock_backend,
            # gateway_peer_id not set
            epoch_fn=lambda: 1,
        )
        client = TestClient(app)
        resp = client.get("/attestation")
        assert resp.status_code == 503

    def test_attestation_without_epoch_fn(self, capacity, mock_backend):
        """GET /attestation returns 503 when epoch_fn is missing."""
        app = create_app(
            capacity_table=capacity,
            tee_backend=mock_backend,
            gateway_peer_id="gw-001",
            # epoch_fn not set
        )
        client = TestClient(app)
        resp = client.get("/attestation")
        assert resp.status_code == 503

    def test_attestation_backend_error(self, capacity):
        """GET /attestation returns 500 when backend raises."""
        bad_backend = MagicMock()
        bad_backend.generate_quote.side_effect = RuntimeError("hardware failure")
        app = create_app(
            capacity_table=capacity,
            tee_backend=bad_backend,
            gateway_peer_id="gw-001",
            epoch_fn=lambda: 1,
        )
        client = TestClient(app)
        resp = client.get("/attestation")
        assert resp.status_code == 500
        assert resp.json()["error"] == "attestation_failed"

    def test_attestation_is_unauthenticated(self, capacity, mock_backend):
        """GET /attestation works without auth even when api_keys is set."""
        app = create_app(
            capacity_table=capacity,
            api_keys={"secret-key"},
            tee_backend=mock_backend,
            gateway_peer_id="gw-001",
            epoch_fn=lambda: 1,
        )
        client = TestClient(app)
        resp = client.get("/attestation")
        assert resp.status_code == 200

    def test_attestation_contains_hardware_id(self, capacity, mock_backend):
        """Quote response includes hardware_id field from the backend."""
        app = create_app(
            capacity_table=capacity,
            tee_backend=mock_backend,
            gateway_peer_id="gw-001",
            epoch_fn=lambda: 10,
        )
        client = TestClient(app)
        resp = client.get("/attestation")
        body = resp.json()
        assert "hardware_id" in body
        # MockBackend generates a non-empty hardware_id
        assert len(body["hardware_id"]) > 0


# ---------------------------------------------------------------------------
# Forwarder unit tests
# ---------------------------------------------------------------------------


class TestRaTlsForwarder:
    """Tests for RaTlsForwarder."""

    def test_forwarding_error_attributes(self):
        """ForwardingError stores peer_id, reason, and is_timeout."""
        err = ForwardingError("peer-123", "timeout: read", is_timeout=True)
        assert err.peer_id == "peer-123"
        assert err.reason == "timeout: read"
        assert err.is_timeout is True
        assert "peer-123" in str(err)

    def test_forwarding_error_default_not_timeout(self):
        """ForwardingError defaults to is_timeout=False."""
        err = ForwardingError("peer-456", "connection refused")
        assert err.is_timeout is False

    @pytest.mark.asyncio
    async def test_forward_success(self):
        """Successful forwarding returns parsed JSON from miner."""
        mock_response = httpx.Response(
            200,
            json={"choices": [{"message": {"content": "hello"}}]},
            request=httpx.Request("POST", "http://peer-a:8000/v1/chat/completions"),
        )

        forwarder = RaTlsForwarder()
        node = NodeEntry(peer_id="peer-a", model="test-model", load=0.3, latency_p95=100)
        request = ChatCompletionRequest(
            model="test-model",
            messages=[{"role": "user", "content": "hello"}],
        )

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_response):
            result = await forwarder.forward(node=node, request=request)
            assert result["choices"][0]["message"]["content"] == "hello"

    @pytest.mark.asyncio
    async def test_forward_timeout(self):
        """Timeout during forwarding raises ForwardingError with is_timeout=True."""
        forwarder = RaTlsForwarder()
        node = NodeEntry(peer_id="peer-slow", model="test-model", load=0.1, latency_p95=100)
        request = ChatCompletionRequest(
            model="test-model",
            messages=[{"role": "user", "content": "hello"}],
        )

        with patch(
            "httpx.AsyncClient.post",
            new_callable=AsyncMock,
            side_effect=httpx.ReadTimeout("read timed out"),
        ):
            with pytest.raises(ForwardingError) as exc_info:
                await forwarder.forward(node=node, request=request)
            assert exc_info.value.is_timeout is True
            assert exc_info.value.peer_id == "peer-slow"

    @pytest.mark.asyncio
    async def test_forward_connection_error(self):
        """Connection error raises ForwardingError with is_timeout=False."""
        forwarder = RaTlsForwarder()
        node = NodeEntry(peer_id="peer-down", model="test-model", load=0.1, latency_p95=100)
        request = ChatCompletionRequest(
            model="test-model",
            messages=[{"role": "user", "content": "hello"}],
        )

        with patch(
            "httpx.AsyncClient.post",
            new_callable=AsyncMock,
            side_effect=httpx.ConnectError("connection refused"),
        ):
            with pytest.raises(ForwardingError) as exc_info:
                await forwarder.forward(node=node, request=request)
            assert exc_info.value.is_timeout is False

    @pytest.mark.asyncio
    async def test_forward_http_error(self):
        """HTTP 500 from miner raises ForwardingError."""
        mock_response = httpx.Response(
            500,
            json={"error": "internal"},
            request=httpx.Request("POST", "http://peer-err:8000/v1/chat/completions"),
        )

        forwarder = RaTlsForwarder()
        node = NodeEntry(peer_id="peer-err", model="test-model", load=0.1, latency_p95=100)
        request = ChatCompletionRequest(
            model="test-model",
            messages=[{"role": "user", "content": "hello"}],
        )

        with patch("httpx.AsyncClient.post", new_callable=AsyncMock, return_value=mock_response):
            with pytest.raises(ForwardingError) as exc_info:
                await forwarder.forward(node=node, request=request)
            assert "http_error" in exc_info.value.reason

    def test_custom_base_url_fn(self):
        """Custom base_url_fn is used for URL resolution."""
        custom_fn = lambda node: f"https://{node.peer_id}.example.com"
        forwarder = RaTlsForwarder(base_url_fn=custom_fn)
        node = NodeEntry(peer_id="peer-x", model="m", load=0.1, latency_p95=100)
        url = forwarder._base_url_fn(node)
        assert url == "https://peer-x.example.com"


# ---------------------------------------------------------------------------
# Chat completions with forwarder integration tests
# ---------------------------------------------------------------------------


class TestChatCompletionsWithForwarder:
    """Tests for /v1/chat/completions with RA-TLS forwarder."""

    @pytest.fixture
    def mock_forwarder(self):
        """Create a mock forwarder that returns a canned response."""
        fwd = MagicMock(spec=RaTlsForwarder)
        fwd.forward = AsyncMock(return_value={
            "choices": [{"message": {"role": "assistant", "content": "test response"}}],
            "model": "nvidia/nemotron-3-49b",
        })
        return fwd

    def test_chat_completions_with_forwarder_success(self, capacity, mock_forwarder):
        """Successful forwarding returns 200 with miner response."""
        app = create_app(
            capacity_table=capacity,
            api_keys={"test-key"},
            forwarder=mock_forwarder,
        )
        client = TestClient(app)
        resp = client.post(
            "/v1/chat/completions",
            headers={"Authorization": "Bearer test-key"},
            json={
                "model": "nvidia/nemotron-3-49b",
                "messages": [{"role": "user", "content": "hello"}],
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["choices"][0]["message"]["content"] == "test response"
        assert resp.headers.get("x-selected-node") is not None

    def test_chat_completions_forwarding_error_returns_502(self, capacity):
        """ForwardingError (non-timeout) returns 502."""
        fwd = MagicMock(spec=RaTlsForwarder)
        fwd.forward = AsyncMock(
            side_effect=ForwardingError("peer-a", "connection refused")
        )
        app = create_app(
            capacity_table=capacity,
            api_keys={"test-key"},
            forwarder=fwd,
        )
        client = TestClient(app)
        resp = client.post(
            "/v1/chat/completions",
            headers={"Authorization": "Bearer test-key"},
            json={
                "model": "nvidia/nemotron-3-49b",
                "messages": [{"role": "user", "content": "hello"}],
            },
        )
        assert resp.status_code == 502
        body = resp.json()
        assert body["error"] == "forwarding_error"
        assert "selected_node" in body

    def test_chat_completions_timeout_returns_504(self, capacity):
        """ForwardingError with is_timeout=True returns 504."""
        fwd = MagicMock(spec=RaTlsForwarder)
        fwd.forward = AsyncMock(
            side_effect=ForwardingError("peer-a", "read timeout", is_timeout=True)
        )
        app = create_app(
            capacity_table=capacity,
            api_keys={"test-key"},
            forwarder=fwd,
        )
        client = TestClient(app)
        resp = client.post(
            "/v1/chat/completions",
            headers={"Authorization": "Bearer test-key"},
            json={
                "model": "nvidia/nemotron-3-49b",
                "messages": [{"role": "user", "content": "hello"}],
            },
        )
        assert resp.status_code == 504
        body = resp.json()
        assert body["error"] == "gateway_timeout"

    def test_chat_completions_without_forwarder_returns_501(self, capacity):
        """Without forwarder, /v1/chat/completions returns 501 (backward compat)."""
        app = create_app(
            capacity_table=capacity,
            api_keys={"test-key"},
        )
        client = TestClient(app)
        resp = client.post(
            "/v1/chat/completions",
            headers={"Authorization": "Bearer test-key"},
            json={
                "model": "nvidia/nemotron-3-49b",
                "messages": [{"role": "user", "content": "hello"}],
            },
        )
        assert resp.status_code == 501
        body = resp.json()
        assert body["error"] == "not_implemented"
        assert "selected_node" in body

    def test_chat_completions_selected_node_header(self, capacity, mock_forwarder):
        """X-Selected-Node header is present in successful response."""
        app = create_app(
            capacity_table=capacity,
            api_keys={"test-key"},
            forwarder=mock_forwarder,
        )
        client = TestClient(app)
        resp = client.post(
            "/v1/chat/completions",
            headers={"Authorization": "Bearer test-key"},
            json={
                "model": "nvidia/nemotron-3-49b",
                "messages": [{"role": "user", "content": "hello"}],
            },
        )
        # Least-loaded node is peer-a
        assert resp.headers.get("x-selected-node") == "peer-a"
