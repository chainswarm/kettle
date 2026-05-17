"""End-to-end integration tests for the frontier inference gateway.

Simulates the complete request flow: node lifecycle (join/leave via capacity
table), routing decisions, load balancing, model listing, auth enforcement,
and graceful degradation under node churn.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from subnet.frontier.capacity import CapacityTable
from subnet.frontier.app import create_app
from subnet.frontier.messages import NodeJoinMessage, NodeLeaveMessage


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

MODEL_A = "nvidia/nemotron-3-49b"
MODEL_B = "meta/llama3-70b"
API_KEY = "e2e-test-key"
AUTH_HEADERS = {"Authorization": f"Bearer {API_KEY}"}


def _make_chat_payload(model: str) -> dict:
    return {
        "model": model,
        "messages": [{"role": "user", "content": "ping"}],
    }


def _client_with_capacity(ct: CapacityTable) -> TestClient:
    app = create_app(capacity_table=ct, api_keys={API_KEY})
    return TestClient(app)


# ---------------------------------------------------------------------------
# Test 1 — Full request lifecycle (happy path)
# ---------------------------------------------------------------------------


class TestFullRequestLifecycle:
    """Three nodes serving two models; frontier picks least-loaded node."""

    @pytest.fixture
    def setup(self):
        ct = CapacityTable()
        # MODEL_A: two nodes
        ct.update("node-a1", model=MODEL_A, load=0.3, latency_p95=100.0)
        ct.update("node-a2", model=MODEL_A, load=0.6, latency_p95=110.0)
        # MODEL_B: one node
        ct.update("node-b1", model=MODEL_B, load=0.5, latency_p95=200.0)
        client = _client_with_capacity(ct)
        return ct, client

    def test_picks_least_loaded_node_for_model_a(self, setup):
        """Request for MODEL_A routes to node-a1 (load=0.3 < 0.6)."""
        _, client = setup
        resp = client.post(
            "/v1/chat/completions",
            headers=AUTH_HEADERS,
            json=_make_chat_payload(MODEL_A),
        )
        assert resp.status_code == 501
        body = resp.json()
        assert body["error"] == "not_implemented"
        assert body["selected_node"] == "node-a1"

    def test_picks_only_node_for_model_b(self, setup):
        """Request for MODEL_B routes to node-b1 (the only available node)."""
        _, client = setup
        resp = client.post(
            "/v1/chat/completions",
            headers=AUTH_HEADERS,
            json=_make_chat_payload(MODEL_B),
        )
        assert resp.status_code == 501
        body = resp.json()
        assert body["selected_node"] == "node-b1"


# ---------------------------------------------------------------------------
# Test 2 — Node joins via heartbeat → becomes routable
# ---------------------------------------------------------------------------


class TestNodeJoinBecomesRoutable:
    """Empty capacity table → 503; node heartbeat → 501 with selected_node."""

    def test_node_join_makes_model_routable(self):
        ct = CapacityTable()
        client = _client_with_capacity(ct)

        # No nodes yet → 503
        resp = client.post(
            "/v1/chat/completions",
            headers=AUTH_HEADERS,
            json=_make_chat_payload(MODEL_A),
        )
        assert resp.status_code == 503
        assert resp.json()["error"] == "model_unavailable"

        # Node sends heartbeat (simulated via capacity table update)
        ct.update("node-new", model=MODEL_A, load=0.2, latency_p95=90.0)

        # Same request now succeeds with the new node selected
        resp2 = client.post(
            "/v1/chat/completions",
            headers=AUTH_HEADERS,
            json=_make_chat_payload(MODEL_A),
        )
        assert resp2.status_code == 501
        body = resp2.json()
        assert body["selected_node"] == "node-new"


# ---------------------------------------------------------------------------
# Test 3 — Node leaves → no longer routable
# ---------------------------------------------------------------------------


class TestNodeLeaveStopsRouting:
    """After removing a node from the capacity table, routing returns 503."""

    def test_remove_node_causes_503(self):
        ct = CapacityTable()
        ct.update("node-gone", model=MODEL_A, load=0.4, latency_p95=150.0)
        client = _client_with_capacity(ct)

        # Confirm routing works before removal
        resp = client.post(
            "/v1/chat/completions",
            headers=AUTH_HEADERS,
            json=_make_chat_payload(MODEL_A),
        )
        assert resp.status_code == 501
        assert resp.json()["selected_node"] == "node-gone"

        # Simulate node leaving
        ct.remove("node-gone")

        # Routing should now fail
        resp2 = client.post(
            "/v1/chat/completions",
            headers=AUTH_HEADERS,
            json=_make_chat_payload(MODEL_A),
        )
        assert resp2.status_code == 503
        assert resp2.json()["error"] == "model_unavailable"


# ---------------------------------------------------------------------------
# Test 4 — Load balancing shifts with traffic
# ---------------------------------------------------------------------------


class TestLoadBalancingShifts:
    """After the 30%-load node updates to 80%, the 70%-load node is preferred."""

    def test_routing_follows_load_update(self):
        ct = CapacityTable()
        ct.update("node-low", model=MODEL_A, load=0.3, latency_p95=100.0)
        ct.update("node-high", model=MODEL_A, load=0.7, latency_p95=110.0)
        client = _client_with_capacity(ct)

        # First request → picks node-low (0.3 < 0.7)
        resp1 = client.post(
            "/v1/chat/completions",
            headers=AUTH_HEADERS,
            json=_make_chat_payload(MODEL_A),
        )
        assert resp1.status_code == 501
        assert resp1.json()["selected_node"] == "node-low"

        # node-low reports high load
        ct.update("node-low", model=MODEL_A, load=0.8, latency_p95=100.0)

        # Next request → picks node-high (0.7 < 0.8)
        resp2 = client.post(
            "/v1/chat/completions",
            headers=AUTH_HEADERS,
            json=_make_chat_payload(MODEL_A),
        )
        assert resp2.status_code == 501
        assert resp2.json()["selected_node"] == "node-high"


# ---------------------------------------------------------------------------
# Test 5 — Model listing reflects live state
# ---------------------------------------------------------------------------


class TestModelListingLiveState:
    """Removing all nodes for a model removes it from /v1/models."""

    def test_model_disappears_when_all_nodes_removed(self):
        ct = CapacityTable()
        ct.update("node-a", model=MODEL_A, load=0.3, latency_p95=100.0)
        ct.update("node-b", model=MODEL_B, load=0.5, latency_p95=200.0)
        client = _client_with_capacity(ct)

        # Both models present initially
        resp1 = client.get("/v1/models", headers=AUTH_HEADERS)
        assert resp1.status_code == 200
        model_ids = {m["id"] for m in resp1.json()["data"]}
        assert MODEL_A in model_ids
        assert MODEL_B in model_ids

        # Remove all nodes for MODEL_B
        ct.remove("node-b")

        # Only MODEL_A should remain
        resp2 = client.get("/v1/models", headers=AUTH_HEADERS)
        assert resp2.status_code == 200
        model_ids_after = {m["id"] for m in resp2.json()["data"]}
        assert MODEL_A in model_ids_after
        assert MODEL_B not in model_ids_after


# ---------------------------------------------------------------------------
# Test 6 — Auth enforcement across all endpoints
# ---------------------------------------------------------------------------


class TestAuthEnforcement:
    """/v1/models and /v1/chat/completions require auth; /health does not."""

    @pytest.fixture
    def client(self):
        ct = CapacityTable()
        ct.update("node-x", model=MODEL_A, load=0.3, latency_p95=100.0)
        return _client_with_capacity(ct)

    def test_models_without_auth_returns_401(self, client):
        resp = client.get("/v1/models")
        assert resp.status_code == 401

    def test_chat_completions_without_auth_returns_401(self, client):
        resp = client.post(
            "/v1/chat/completions",
            json=_make_chat_payload(MODEL_A),
        )
        assert resp.status_code == 401

    def test_health_without_auth_returns_200(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Test 7 — Multiple sequential requests route to different nodes
# ---------------------------------------------------------------------------


class TestSequentialRequestsDistributed:
    """Second request routes to a different node after the first node's load rises."""

    def test_sequential_requests_follow_load_updates(self):
        ct = CapacityTable()
        ct.update("node-30", model=MODEL_A, load=0.30, latency_p95=100.0)
        ct.update("node-40", model=MODEL_A, load=0.40, latency_p95=110.0)
        ct.update("node-50", model=MODEL_A, load=0.50, latency_p95=120.0)
        client = _client_with_capacity(ct)

        # Request 1 → node-30 is least loaded
        resp1 = client.post(
            "/v1/chat/completions",
            headers=AUTH_HEADERS,
            json=_make_chat_payload(MODEL_A),
        )
        assert resp1.status_code == 501
        assert resp1.json()["selected_node"] == "node-30"

        # node-30 reports increased load via heartbeat
        ct.update("node-30", model=MODEL_A, load=0.60, latency_p95=100.0)

        # Request 2 → node-40 is now least loaded
        resp2 = client.post(
            "/v1/chat/completions",
            headers=AUTH_HEADERS,
            json=_make_chat_payload(MODEL_A),
        )
        assert resp2.status_code == 501
        assert resp2.json()["selected_node"] == "node-40"


# ---------------------------------------------------------------------------
# Test 8 — Graceful degradation under node churn
# ---------------------------------------------------------------------------


class TestGracefulDegradationUnderChurn:
    """Start with 5 nodes; remove 3; remaining 2 still handle requests; remove all → 503."""

    def test_routing_survives_node_removal(self):
        ct = CapacityTable()
        nodes = [f"churn-{i}" for i in range(5)]
        for i, nid in enumerate(nodes):
            ct.update(nid, model=MODEL_A, load=0.1 * (i + 1), latency_p95=100.0)

        client = _client_with_capacity(ct)

        # Remove 3 of the 5 nodes
        for nid in nodes[:3]:
            ct.remove(nid)

        # Requests still succeed (2 nodes remain)
        remaining = {nodes[3], nodes[4]}
        for _ in range(3):
            resp = client.post(
                "/v1/chat/completions",
                headers=AUTH_HEADERS,
                json=_make_chat_payload(MODEL_A),
            )
            assert resp.status_code == 501
            assert resp.json()["selected_node"] in remaining

        # Remove the last 2 nodes
        for nid in nodes[3:]:
            ct.remove(nid)

        # Now returns 503
        resp_final = client.post(
            "/v1/chat/completions",
            headers=AUTH_HEADERS,
            json=_make_chat_payload(MODEL_A),
        )
        assert resp_final.status_code == 503
        assert resp_final.json()["error"] == "model_unavailable"


# ---------------------------------------------------------------------------
# Test 9 — NodeJoinMessage integration
# ---------------------------------------------------------------------------


class TestNodeJoinMessageIntegration:
    """NodeJoinMessage fields drive capacity table updates correctly."""

    def test_join_message_makes_node_routable(self):
        ct = CapacityTable()
        client = _client_with_capacity(ct)

        # Construct a NodeJoinMessage (as gossip handler would receive it)
        msg = NodeJoinMessage(
            peer_id="joined-node",
            gpu_type="NVIDIA A100",
            gpu_uuid="GPU-aabbcc",
            assigned_model=MODEL_A,
        )
        assert msg.type == "node_join"
        assert msg.peer_id == "joined-node"
        assert msg.assigned_model == MODEL_A

        # Simulate gossip handler: update capacity table from message fields
        ct.update(
            msg.peer_id,
            model=msg.assigned_model,
            load=0.0,
            latency_p95=0.0,
        )

        # Frontier should now route to the joined node
        resp = client.post(
            "/v1/chat/completions",
            headers=AUTH_HEADERS,
            json=_make_chat_payload(MODEL_A),
        )
        assert resp.status_code == 501
        assert resp.json()["selected_node"] == "joined-node"

    def test_leave_message_fields(self):
        """NodeLeaveMessage serialises correctly and round-trips via bytes."""
        msg = NodeLeaveMessage(peer_id="leaving-node", reason="graceful")
        assert msg.type == "node_leave"

        raw = msg.to_bytes()
        decoded = NodeLeaveMessage.from_bytes(raw)
        assert decoded.peer_id == "leaving-node"
        assert decoded.reason == "graceful"
