"""Tests for CapacityTable — frontier routing component."""

import time
import pytest

from subnet.frontier.capacity import CapacityTable, NodeEntry


# ---------------------------------------------------------------------------
# test_update_and_lookup
# ---------------------------------------------------------------------------

def test_update_and_lookup():
    table = CapacityTable()
    table.update("peer-1", model="llama3", load=0.5, latency_p95=120.0)

    nodes = table.nodes_for_model("llama3")
    assert len(nodes) == 1
    node = nodes[0]
    assert node.peer_id == "peer-1"
    assert node.model == "llama3"
    assert node.load == 0.5
    assert node.latency_p95 == 120.0


# ---------------------------------------------------------------------------
# test_least_loaded_routing
# ---------------------------------------------------------------------------

def test_least_loaded_routing():
    table = CapacityTable()
    table.update("peer-a", model="gpt4", load=0.8, latency_p95=200.0)
    table.update("peer-b", model="gpt4", load=0.2, latency_p95=150.0)
    table.update("peer-c", model="gpt4", load=0.5, latency_p95=180.0)

    picked = table.pick_node("gpt4")
    assert picked is not None
    assert picked.peer_id == "peer-b"
    assert picked.load == 0.2


# ---------------------------------------------------------------------------
# test_pick_node_unknown_model_returns_none
# ---------------------------------------------------------------------------

def test_pick_node_unknown_model_returns_none():
    table = CapacityTable()
    result = table.pick_node("nonexistent-model")
    assert result is None


# ---------------------------------------------------------------------------
# test_stale_node_removed
# ---------------------------------------------------------------------------

def test_stale_node_removed():
    table = CapacityTable(staleness_threshold=0.1)
    table.update("peer-stale", model="mistral", load=0.3, latency_p95=100.0)

    # Confirm it's present before sleeping
    assert len(table.nodes_for_model("mistral")) == 1

    time.sleep(0.15)

    evicted = table.evict_stale()
    assert "peer-stale" in evicted
    assert len(table.nodes_for_model("mistral")) == 0


# ---------------------------------------------------------------------------
# test_remove_node
# ---------------------------------------------------------------------------

def test_remove_node():
    table = CapacityTable()
    table.update("peer-x", model="falcon", load=0.4, latency_p95=90.0)
    assert len(table.nodes_for_model("falcon")) == 1

    table.remove("peer-x")
    assert len(table.nodes_for_model("falcon")) == 0


# ---------------------------------------------------------------------------
# test_multiple_models
# ---------------------------------------------------------------------------

def test_multiple_models():
    table = CapacityTable()
    table.update("peer-1", model="llama3", load=0.3, latency_p95=100.0)
    table.update("peer-2", model="mixtral", load=0.6, latency_p95=130.0)
    table.update("peer-3", model="llama3", load=0.7, latency_p95=110.0)

    llama_nodes = table.nodes_for_model("llama3")
    mixtral_nodes = table.nodes_for_model("mixtral")

    assert len(llama_nodes) == 2
    assert len(mixtral_nodes) == 1
    assert mixtral_nodes[0].peer_id == "peer-2"

    peer_ids_llama = {n.peer_id for n in llama_nodes}
    assert peer_ids_llama == {"peer-1", "peer-3"}


# ---------------------------------------------------------------------------
# test_all_models
# ---------------------------------------------------------------------------

def test_all_models():
    table = CapacityTable()
    table.update("peer-1", model="llama3", load=0.3, latency_p95=100.0)
    table.update("peer-2", model="mixtral", load=0.6, latency_p95=130.0)
    table.update("peer-3", model="llama3", load=0.7, latency_p95=110.0)
    table.update("peer-4", model="gpt4", load=0.1, latency_p95=200.0)

    models = table.all_models()
    assert isinstance(models, set)
    assert models == {"llama3", "mixtral", "gpt4"}


# ---------------------------------------------------------------------------
# test_overloaded_check
# ---------------------------------------------------------------------------

def test_overloaded_check():
    table = CapacityTable()

    # No nodes for model — not overloaded (no nodes means empty, not all-above)
    assert table.is_overloaded("llama3") is False

    # All nodes above threshold
    table.update("peer-1", model="llama3", load=0.95, latency_p95=100.0)
    table.update("peer-2", model="llama3", load=0.92, latency_p95=110.0)
    assert table.is_overloaded("llama3", threshold=0.9) is True

    # Add a node below threshold — no longer all overloaded
    table.update("peer-3", model="llama3", load=0.5, latency_p95=90.0)
    assert table.is_overloaded("llama3", threshold=0.9) is False
