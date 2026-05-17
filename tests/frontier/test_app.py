"""Tests for subnet.frontier.app — OpenAI-compatible FastAPI gateway."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from subnet.frontier.capacity import CapacityTable
from subnet.frontier.app import create_app


class TestFrontierApp:
    """Integration tests for the Frontier FastAPI application."""

    @pytest.fixture
    def capacity(self):
        ct = CapacityTable()
        ct.update("peer-a", model="nvidia/nemotron-3-49b", load=0.3, latency_p95=890)
        ct.update("peer-b", model="nvidia/nemotron-3-49b", load=0.7, latency_p95=920)
        return ct

    @pytest.fixture
    def client(self, capacity):
        app = create_app(capacity_table=capacity, api_keys={"test-key"})
        return TestClient(app)

    # ------------------------------------------------------------------
    # /health
    # ------------------------------------------------------------------

    def test_health(self, client):
        """GET /health returns 200 with status=ok and models list."""
        resp = client.get("/health")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"
        assert "models" in body
        assert isinstance(body["models"], list)
        assert "nvidia/nemotron-3-49b" in body["models"]

    # ------------------------------------------------------------------
    # /v1/models
    # ------------------------------------------------------------------

    def test_models_list(self, client):
        """GET /v1/models returns 200 with OpenAI models list format."""
        resp = client.get("/v1/models", headers={"Authorization": "Bearer test-key"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["object"] == "list"
        assert "data" in body
        model_ids = [m["id"] for m in body["data"]]
        assert "nvidia/nemotron-3-49b" in model_ids

    def test_models_list_no_auth(self, client):
        """GET /v1/models without auth returns 401."""
        resp = client.get("/v1/models")
        assert resp.status_code == 401

    def test_models_list_bad_key(self, client):
        """GET /v1/models with wrong key returns 401."""
        resp = client.get("/v1/models", headers={"Authorization": "Bearer wrong-key"})
        assert resp.status_code == 401

    # ------------------------------------------------------------------
    # /v1/chat/completions
    # ------------------------------------------------------------------

    def test_chat_completions_no_auth(self, client):
        """POST /v1/chat/completions without auth returns 401."""
        resp = client.post(
            "/v1/chat/completions",
            json={
                "model": "nvidia/nemotron-3-49b",
                "messages": [{"role": "user", "content": "hello"}],
            },
        )
        assert resp.status_code == 401

    def test_chat_completions_unknown_model(self, client):
        """POST /v1/chat/completions with unknown model returns 503."""
        resp = client.post(
            "/v1/chat/completions",
            headers={"Authorization": "Bearer test-key"},
            json={
                "model": "unknown/model-xyz",
                "messages": [{"role": "user", "content": "hello"}],
            },
        )
        assert resp.status_code == 503
        body = resp.json()
        assert body["error"] == "model_unavailable"

    def test_chat_completions_overloaded(self, capacity, client):
        """POST /v1/chat/completions when all nodes >90% load returns 429."""
        # Drive all nodes to overloaded state
        capacity.update("peer-a", model="nvidia/nemotron-3-49b", load=0.95, latency_p95=890)
        capacity.update("peer-b", model="nvidia/nemotron-3-49b", load=0.95, latency_p95=920)

        resp = client.post(
            "/v1/chat/completions",
            headers={"Authorization": "Bearer test-key"},
            json={
                "model": "nvidia/nemotron-3-49b",
                "messages": [{"role": "user", "content": "hello"}],
            },
        )
        assert resp.status_code == 429
        body = resp.json()
        assert body["error"] == "capacity_exceeded"
        assert body["retry_after"] == 5

    def test_chat_completions_routes_to_node(self, capacity, client):
        """POST /v1/chat/completions with available model returns 501 with selected_node."""
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
        # Least-loaded node should be peer-a (load=0.3 vs peer-b 0.7)
        assert body["selected_node"] == "peer-a"

    # ------------------------------------------------------------------
    # Auth disabled (api_keys=None)
    # ------------------------------------------------------------------

    def test_no_auth_required_when_api_keys_none(self, capacity):
        """When api_keys=None, no bearer token is required."""
        app = create_app(capacity_table=capacity, api_keys=None)
        c = TestClient(app)
        resp = c.get("/v1/models")
        assert resp.status_code == 200

    def test_health_no_auth_required(self, client):
        """/health should not require auth even when api_keys is configured."""
        resp = client.get("/health")
        assert resp.status_code == 200
