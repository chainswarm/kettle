"""Integration tests: heartbeats → capacity table → frontier routing.

Tests cover the full flow from nodes announcing themselves via capacity-table
updates through to the frontier app making correct routing decisions.
"""

from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

from subnet.frontier.capacity import CapacityTable
from subnet.frontier.app import create_app


class TestFrontierRoutingIntegration:
    """Integration tests: heartbeats → capacity table → frontier routing."""

    @pytest.fixture
    def capacity(self):
        return CapacityTable(staleness_threshold=1.0)  # short for testing

    @pytest.fixture
    def client(self, capacity):
        app = create_app(capacity_table=capacity, api_keys={"test-key"})
        return TestClient(app)

    def _auth(self):
        return {"Authorization": "Bearer test-key"}

    def _post_chat(self, client, model):
        return client.post(
            "/v1/chat/completions",
            json={"model": model, "messages": [{"role": "user", "content": "hi"}]},
            headers=self._auth(),
        )

    # ------------------------------------------------------------------
    # 1. Heartbeat → Capacity → Routing flow
    # ------------------------------------------------------------------

    def test_heartbeat_flow_routes_to_least_loaded(self, capacity, client):
        """Nodes send heartbeats; frontier picks the least-loaded one."""
        capacity.update("node-a", model="llama3", load=0.7, latency_p95=200.0)
        capacity.update("node-b", model="llama3", load=0.3, latency_p95=150.0)
        capacity.update("node-c", model="llama3", load=0.5, latency_p95=175.0)

        resp = self._post_chat(client, "llama3")

        assert resp.status_code == 501  # selected but RA-TLS not yet implemented
        body = resp.json()
        assert body["selected_node"] == "node-b"  # lowest load 0.3

    def test_routing_shifts_after_load_update(self, capacity, client):
        """When the previously-cheapest node reports higher load, routing shifts."""
        capacity.update("node-a", model="mistral", load=0.2, latency_p95=100.0)
        capacity.update("node-b", model="mistral", load=0.6, latency_p95=120.0)

        resp = self._post_chat(client, "mistral")
        assert resp.status_code == 501
        assert resp.json()["selected_node"] == "node-a"

        # node-a now reports high load (new heartbeat)
        capacity.update("node-a", model="mistral", load=0.9, latency_p95=100.0)

        resp = self._post_chat(client, "mistral")
        assert resp.status_code == 501
        assert resp.json()["selected_node"] == "node-b"  # routing shifted

    def test_multiple_models_independent_routing(self, capacity, client):
        """Nodes serving different models are routed independently."""
        capacity.update("node-llama", model="llama3", load=0.4, latency_p95=100.0)
        capacity.update("node-falcon", model="falcon-7b", load=0.2, latency_p95=80.0)

        resp_llama = self._post_chat(client, "llama3")
        assert resp_llama.status_code == 501
        assert resp_llama.json()["selected_node"] == "node-llama"

        resp_falcon = self._post_chat(client, "falcon-7b")
        assert resp_falcon.status_code == 501
        assert resp_falcon.json()["selected_node"] == "node-falcon"

    # ------------------------------------------------------------------
    # 2. Model unavailable → 503
    # ------------------------------------------------------------------

    def test_model_unavailable_returns_503(self, capacity, client):
        """A request for a model no node serves returns 503 model_unavailable."""
        capacity.update("node-a", model="llama3", load=0.3, latency_p95=100.0)

        resp = self._post_chat(client, "nonexistent-model-xyz")

        assert resp.status_code == 503
        assert resp.json()["error"] == "model_unavailable"

    def test_empty_capacity_table_returns_503(self, client):
        """With no nodes registered at all, any model request returns 503."""
        resp = self._post_chat(client, "llama3")

        assert resp.status_code == 503
        assert resp.json()["error"] == "model_unavailable"

    # ------------------------------------------------------------------
    # 3. Node goes stale → evicted → requests fail
    # ------------------------------------------------------------------

    def test_stale_node_evicted_then_503(self, capacity, client):
        """Node stops heartbeating; after staleness threshold it is evicted and
        requests for its model return 503."""
        capacity.update("node-gone", model="mixtral", load=0.4, latency_p95=100.0)

        resp = self._post_chat(client, "mixtral")
        assert resp.status_code == 501  # node present initially

        # Wait past staleness_threshold (1.0 s) then evict
        time.sleep(1.1)
        evicted = capacity.evict_stale()
        assert "node-gone" in evicted

        resp = self._post_chat(client, "mixtral")
        assert resp.status_code == 503
        assert resp.json()["error"] == "model_unavailable"

    def test_surviving_node_still_routed_after_peer_eviction(self, capacity, client):
        """When one node goes stale and is evicted, a healthy peer still receives
        traffic for the same model."""
        capacity.update("node-stale", model="gemma", load=0.3, latency_p95=100.0)
        capacity.update("node-healthy", model="gemma", load=0.5, latency_p95=110.0)

        time.sleep(1.1)
        # Refresh only node-healthy (simulates it continuing to heartbeat)
        capacity.update("node-healthy", model="gemma", load=0.5, latency_p95=110.0)
        capacity.evict_stale()

        resp = self._post_chat(client, "gemma")
        assert resp.status_code == 501
        assert resp.json()["selected_node"] == "node-healthy"

    # ------------------------------------------------------------------
    # 4. Overload detection → 429
    # ------------------------------------------------------------------

    def test_all_nodes_overloaded_returns_429(self, capacity, client):
        """When every node for a model reports >90% load, request returns 429."""
        capacity.update("node-a", model="llama3", load=0.95, latency_p95=300.0)
        capacity.update("node-b", model="llama3", load=0.93, latency_p95=310.0)

        resp = self._post_chat(client, "llama3")

        assert resp.status_code == 429
        body = resp.json()
        assert body["error"] == "capacity_exceeded"
        assert body["retry_after"] == 5

    def test_one_node_below_threshold_avoids_429(self, capacity, client):
        """If at least one node is under the overload threshold, no 429 is returned."""
        capacity.update("node-a", model="llama3", load=0.95, latency_p95=300.0)
        capacity.update("node-b", model="llama3", load=0.95, latency_p95=310.0)
        capacity.update("node-c", model="llama3", load=0.5, latency_p95=150.0)

        resp = self._post_chat(client, "llama3")

        assert resp.status_code == 501  # not overloaded; node selected
        assert resp.json()["selected_node"] == "node-c"  # lowest load wins

    # ------------------------------------------------------------------
    # 5. Multiple CapacityTable instances see same state → deterministic
    # ------------------------------------------------------------------

    def test_two_capacity_tables_same_heartbeats_same_routing(self):
        """Two independent CapacityTable instances receiving the same heartbeats
        must produce the same routing decision (deterministic)."""
        table1 = CapacityTable(staleness_threshold=6.0)
        table2 = CapacityTable(staleness_threshold=6.0)

        for table in (table1, table2):
            table.update("node-a", model="phi3", load=0.6, latency_p95=90.0)
            table.update("node-b", model="phi3", load=0.2, latency_p95=80.0)
            table.update("node-c", model="phi3", load=0.8, latency_p95=110.0)

        picked1 = table1.pick_node("phi3")
        picked2 = table2.pick_node("phi3")

        assert picked1 is not None
        assert picked2 is not None
        assert picked1.peer_id == picked2.peer_id == "node-b"

    def test_two_frontiers_same_state_same_response(self):
        """Two frontier apps backed by independently-populated tables return
        the same selected_node for an identical request."""
        app1_cap = CapacityTable()
        app2_cap = CapacityTable()

        for cap in (app1_cap, app2_cap):
            cap.update("node-x", model="qwen2", load=0.4, latency_p95=100.0)
            cap.update("node-y", model="qwen2", load=0.1, latency_p95=90.0)

        client1 = TestClient(create_app(capacity_table=app1_cap, api_keys={"k"}))
        client2 = TestClient(create_app(capacity_table=app2_cap, api_keys={"k"}))

        auth = {"Authorization": "Bearer k"}
        payload = {"model": "qwen2", "messages": [{"role": "user", "content": "hi"}]}

        r1 = client1.post("/v1/chat/completions", json=payload, headers=auth)
        r2 = client2.post("/v1/chat/completions", json=payload, headers=auth)

        assert r1.status_code == r2.status_code == 501
        assert r1.json()["selected_node"] == r2.json()["selected_node"] == "node-y"

    # ------------------------------------------------------------------
    # 6. Node model switch
    # ------------------------------------------------------------------

    def test_node_switches_model(self, capacity, client):
        """A node originally serving model A sends a new heartbeat for model B.
        It must appear under model B and disappear from model A."""
        capacity.update("node-switch", model="model-a", load=0.3, latency_p95=100.0)

        # Confirm it serves model-a
        resp = self._post_chat(client, "model-a")
        assert resp.status_code == 501
        assert resp.json()["selected_node"] == "node-switch"

        # Simulate the node restarting with a different model
        capacity.update("node-switch", model="model-b", load=0.3, latency_p95=100.0)

        # model-a should now be unavailable
        resp_a = self._post_chat(client, "model-a")
        assert resp_a.status_code == 503
        assert resp_a.json()["error"] == "model_unavailable"

        # model-b should now route to the switched node
        resp_b = self._post_chat(client, "model-b")
        assert resp_b.status_code == 501
        assert resp_b.json()["selected_node"] == "node-switch"

    def test_node_switch_health_endpoint_reflects_new_model(self, capacity, client):
        """After a model switch, /health lists the new model, not the old one."""
        capacity.update("node-x", model="old-model", load=0.3, latency_p95=100.0)

        health1 = client.get("/health").json()
        assert "old-model" in health1["models"]
        assert "new-model" not in health1["models"]

        capacity.update("node-x", model="new-model", load=0.3, latency_p95=100.0)

        health2 = client.get("/health").json()
        assert "new-model" in health2["models"]
        assert "old-model" not in health2["models"]

    # ------------------------------------------------------------------
    # Additional edge-case integration tests
    # ------------------------------------------------------------------

    def test_exact_threshold_load_not_considered_overloaded(self, capacity, client):
        """Nodes at exactly 90% load are NOT overloaded (threshold is strictly >)."""
        capacity.update("node-a", model="llama3", load=0.9, latency_p95=200.0)
        capacity.update("node-b", model="llama3", load=0.9, latency_p95=200.0)

        resp = self._post_chat(client, "llama3")
        # is_overloaded uses load > threshold, so 0.9 is not > 0.9
        assert resp.status_code == 501

    def test_single_node_zero_load_selected(self, capacity, client):
        """A single node at 0% load is selected normally."""
        capacity.update("node-idle", model="deepseek", load=0.0, latency_p95=50.0)

        resp = self._post_chat(client, "deepseek")

        assert resp.status_code == 501
        assert resp.json()["selected_node"] == "node-idle"
