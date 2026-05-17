"""Tests for compute_assignment — model self-assignment for joining nodes."""

from subnet.models.assignment import compute_assignment
from subnet.models.registry import ModelConfig, ModelRegistry

# ---------------------------------------------------------------------------
# Shared sample registry (0.5 / 0.3 / 0.2)
# ---------------------------------------------------------------------------

SAMPLE_REGISTRY = ModelRegistry(
    models=[
        ModelConfig(name="nvidia/nemotron-3-8b", ratio=0.5, measurement="aa" * 48),
        ModelConfig(name="nvidia/nemotron-3-49b", ratio=0.3, measurement="bb" * 48),
        ModelConfig(name="meta/llama-3.1-70b", ratio=0.2, measurement="cc" * 48),
    ]
)


# ---------------------------------------------------------------------------
# 1. test_first_node_gets_highest_ratio
# ---------------------------------------------------------------------------


def test_first_node_gets_highest_ratio():
    """With no existing nodes, the first joiner should get the model with the
    highest ratio (nvidia/nemotron-3-8b at 0.5)."""
    result = compute_assignment(SAMPLE_REGISTRY, current_counts={}, total_nodes=0)
    assert result == "nvidia/nemotron-3-8b"


# ---------------------------------------------------------------------------
# 2. test_second_node_fills_deficit
# ---------------------------------------------------------------------------


def test_second_node_fills_deficit():
    """When nemotron-8b already has 1 node and total=1, the second node should
    go to the next highest-deficit model (nemotron-49b)."""
    current = {"nvidia/nemotron-3-8b": 1}
    result = compute_assignment(SAMPLE_REGISTRY, current_counts=current, total_nodes=1)
    assert result == "nvidia/nemotron-3-49b"


# ---------------------------------------------------------------------------
# 3. test_ten_nodes_balanced
# ---------------------------------------------------------------------------


def test_ten_nodes_balanced():
    """When 10 nodes are perfectly balanced (5/3/2), the 11th node should go
    to the model with the highest ratio (nemotron-8b at 0.5)."""
    current = {
        "nvidia/nemotron-3-8b": 5,
        "nvidia/nemotron-3-49b": 3,
        "meta/llama-3.1-70b": 2,
    }
    result = compute_assignment(SAMPLE_REGISTRY, current_counts=current, total_nodes=10)
    # All deficits are zero — fall back to highest ratio model.
    assert result == "nvidia/nemotron-3-8b"


# ---------------------------------------------------------------------------
# 4. test_deterministic_across_calls
# ---------------------------------------------------------------------------


def test_deterministic_across_calls():
    """Same inputs must always produce the same model name."""
    current = {"nvidia/nemotron-3-8b": 2, "nvidia/nemotron-3-49b": 1}
    first = compute_assignment(SAMPLE_REGISTRY, current_counts=current, total_nodes=3)
    second = compute_assignment(SAMPLE_REGISTRY, current_counts=current, total_nodes=3)
    third = compute_assignment(SAMPLE_REGISTRY, current_counts=current, total_nodes=3)
    assert first == second == third
