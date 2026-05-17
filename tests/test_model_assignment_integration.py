"""
Integration tests for model self-assignment flow.

Tests the full pipeline: ModelRegistry config → network state →
compute_assignment() → correct model for a joining node.

Covers:
  1. Empty network — first node gets highest-ratio model
  2. Gradual fill — 10 nodes join sequentially, final distribution matches 5/3/2
  3. Rebalancing — owner changes ratios, over-represented nodes detect deficit
  4. Single model registry — every node gets that model
  5. Two models equal ratio — deterministic lexicographic tie-break
  6. Large cluster (100 nodes, 5 models) — final counts within ±1 of target
  7. Measurement lookup — registry returns correct measurement after assignment
"""

import pytest

from subnet.models.assignment import compute_assignment
from subnet.models.registry import ModelConfig, ModelRegistry

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_M = "aa" * 48  # dummy 96-char SHA-384 placeholder


def _meas(tag: str) -> str:
    """Return a deterministic 96-char hex string keyed on *tag*."""
    char = tag[0]
    return char * 96


def _registry(*specs: tuple[str, float, str]) -> ModelRegistry:
    """Build a ModelRegistry from (name, ratio, measurement_tag) tuples."""
    models = [
        ModelConfig(name=name, ratio=ratio, measurement=_meas(meas_tag))
        for name, ratio, meas_tag in specs
    ]
    return ModelRegistry(models=models)


# ---------------------------------------------------------------------------
# 1. Empty network — first node gets highest-ratio model
# ---------------------------------------------------------------------------


def test_first_node_empty_network():
    """No existing nodes: first joiner should receive the model with ratio 0.5."""
    registry = _registry(
        ("model/alpha", 0.5, "a"),
        ("model/beta", 0.3, "b"),
        ("model/gamma", 0.2, "c"),
    )
    assigned = compute_assignment(registry, current_counts={}, total_nodes=0)
    assert assigned == "model/alpha"


# ---------------------------------------------------------------------------
# 2. Gradual fill — 10 nodes join sequentially, final distribution is 5/3/2
# ---------------------------------------------------------------------------


def test_gradual_fill_ten_nodes_sequential():
    """Simulate 10 nodes joining one at a time; final counts must equal 5/3/2."""
    registry = _registry(
        ("model/alpha", 0.5, "a"),
        ("model/beta", 0.3, "b"),
        ("model/gamma", 0.2, "c"),
    )

    counts: dict[str, int] = {}

    for i in range(10):
        assigned = compute_assignment(registry, current_counts=counts, total_nodes=i)
        counts[assigned] = counts.get(assigned, 0) + 1

    assert counts == {
        "model/alpha": 5,
        "model/beta": 3,
        "model/gamma": 2,
    }, f"Unexpected distribution after 10 sequential joins: {counts}"


# ---------------------------------------------------------------------------
# 3. Rebalancing — owner shifts ratios, over-represented nodes detect deficit
# ---------------------------------------------------------------------------


def test_rebalancing_after_ratio_change():
    """
    10 nodes are balanced at 50/30/20 under old ratios.
    Owner updates registry to 30/30/40.
    Nodes that re-compute should detect which model now has the highest deficit
    so they know to switch.

    With 10 nodes at old distribution (alpha=5, beta=3, gamma=2) and new
    targets for 10 nodes being alpha=3, beta=3, gamma=4:
      - alpha deficit = 3 - 5 = -2  (over-represented)
      - beta  deficit = 3 - 3 =  0
      - gamma deficit = 4 - 2 =  2  (highest deficit → nodes should move here)
    """
    new_registry = _registry(
        ("model/alpha", 0.30, "a"),
        ("model/beta", 0.30, "b"),
        ("model/gamma", 0.40, "c"),
    )

    # Current distribution reflects the old 50/30/20 balance.
    current_counts = {
        "model/alpha": 5,
        "model/beta": 3,
        "model/gamma": 2,
    }
    total_nodes = 10

    # Check new targets.
    targets = new_registry.target_counts(total_nodes)
    assert targets["model/alpha"] == 3
    assert targets["model/beta"] == 3
    assert targets["model/gamma"] == 4

    # An 11th node joining (or a node re-evaluating) should be directed to gamma.
    assigned = compute_assignment(new_registry, current_counts=current_counts, total_nodes=total_nodes)
    assert assigned == "model/gamma", (
        f"Expected gamma (highest deficit under new ratios) but got {assigned!r}"
    )

    # Confirm alpha is over-represented: its deficit is negative.
    alpha_deficit = targets["model/alpha"] - current_counts["model/alpha"]
    gamma_deficit = targets["model/gamma"] - current_counts["model/gamma"]
    assert alpha_deficit < 0, "alpha should be over-represented"
    assert gamma_deficit > 0, "gamma should have a deficit"
    assert gamma_deficit > alpha_deficit


# ---------------------------------------------------------------------------
# 4. Single model registry — every node gets that one model
# ---------------------------------------------------------------------------


def test_single_model_registry():
    """With only one model at 100%, every joining node is assigned to it."""
    registry = ModelRegistry(
        models=[ModelConfig(name="model/solo", ratio=1.0, measurement=_meas("s"))]
    )

    counts: dict[str, int] = {}
    for i in range(20):
        assigned = compute_assignment(registry, current_counts=counts, total_nodes=i)
        assert assigned == "model/solo", f"Node {i} got {assigned!r} instead of 'model/solo'"
        counts["model/solo"] = counts.get("model/solo", 0) + 1

    assert counts == {"model/solo": 20}


# ---------------------------------------------------------------------------
# 5. Two models equal ratio — deterministic lexicographic tie-break
# ---------------------------------------------------------------------------


def test_two_models_equal_ratio_alternates():
    """
    Two models at 50/50.  Assignment must be deterministic and must perfectly
    alternate so that every even-numbered node goes to one model and every
    odd-numbered node to the other.

    The concrete tie-breaking path:
      - target_counts(1) distributes the single slot via largest-remainder;
        when remainders are equal, the lower index in the registry wins.
        With registry order [zebra, apple], zebra (index 0) gets the first slot.
      - Subsequent nodes strictly alternate due to the deficit oscillation.
    """
    registry = _registry(
        ("model/zebra", 0.5, "z"),
        ("model/apple", 0.5, "a"),
    )

    # First node: largest-remainder with equal 0.5 remainders → index-0 wins → zebra.
    first = compute_assignment(registry, current_counts={}, total_nodes=0)
    assert first == "model/zebra", f"Expected 'model/zebra' (index-0 tie-break), got {first!r}"

    # Simulate 10 nodes joining.
    counts: dict[str, int] = {}
    for i in range(10):
        assigned = compute_assignment(registry, current_counts=counts, total_nodes=i)
        counts[assigned] = counts.get(assigned, 0) + 1

    # Each model should have exactly 5 nodes.
    assert counts.get("model/apple", 0) == 5, f"apple count: {counts}"
    assert counts.get("model/zebra", 0) == 5, f"zebra count: {counts}"

    # All calls with the same state produce the same result (determinism).
    same_counts = {"model/apple": 2, "model/zebra": 1}
    results = {compute_assignment(registry, current_counts=same_counts, total_nodes=3) for _ in range(5)}
    assert len(results) == 1, f"Non-deterministic assignment: {results}"


# ---------------------------------------------------------------------------
# 6. Large cluster — 100 nodes, 5 models, final counts within ±1 of target
# ---------------------------------------------------------------------------


def test_large_cluster_100_nodes_five_models():
    """
    Registry: 5 models at 40/25/20/10/5.
    100 nodes join sequentially.
    Each model's final count must be within ±1 of its ideal target.
    """
    registry = _registry(
        ("model/m1", 0.40, "1"),
        ("model/m2", 0.25, "2"),
        ("model/m3", 0.20, "3"),
        ("model/m4", 0.10, "4"),
        ("model/m5", 0.05, "5"),
    )

    counts: dict[str, int] = {}
    for i in range(100):
        assigned = compute_assignment(registry, current_counts=counts, total_nodes=i)
        counts[assigned] = counts.get(assigned, 0) + 1

    # Verify total.
    assert sum(counts.values()) == 100

    # Each model's actual count must be within ±1 of its ideal.
    ideal = {
        "model/m1": 40,
        "model/m2": 25,
        "model/m3": 20,
        "model/m4": 10,
        "model/m5": 5,
    }
    for name, target in ideal.items():
        actual = counts.get(name, 0)
        assert abs(actual - target) <= 1, (
            f"{name}: expected ~{target}, got {actual} (diff={actual - target})"
        )


# ---------------------------------------------------------------------------
# 7. Measurement lookup — registry returns correct measurement after assignment
# ---------------------------------------------------------------------------


def test_measurement_lookup_after_assignment():
    """
    After compute_assignment() returns a model name, the registry must return
    the correct SHA-384 measurement for that model.  This is what validators
    compare against the TEE attestation quote.
    """
    # Build registry with distinct measurements per model.
    meas_alpha = "a" * 96
    meas_beta = "b" * 96
    meas_gamma = "c" * 96

    registry = ModelRegistry(
        models=[
            ModelConfig(name="model/alpha", ratio=0.5, measurement=meas_alpha),
            ModelConfig(name="model/beta", ratio=0.3, measurement=meas_beta),
            ModelConfig(name="model/gamma", ratio=0.2, measurement=meas_gamma),
        ]
    )

    expected_measurements = {
        "model/alpha": meas_alpha,
        "model/beta": meas_beta,
        "model/gamma": meas_gamma,
    }

    # Simulate 6 nodes joining; each should get the right measurement.
    counts: dict[str, int] = {}
    for i in range(6):
        assigned = compute_assignment(registry, current_counts=counts, total_nodes=i)
        measurement = registry.measurement_for(assigned)

        assert measurement is not None, f"Node {i}: measurement_for({assigned!r}) returned None"
        assert measurement == expected_measurements[assigned], (
            f"Node {i}: assigned {assigned!r}, expected measurement "
            f"{expected_measurements[assigned]!r}, got {measurement!r}"
        )
        counts[assigned] = counts.get(assigned, 0) + 1

    # Unknown model must return None (safety check for validators).
    assert registry.measurement_for("model/unknown") is None

    # Verify at least two distinct models were assigned across 6 nodes.
    assert len(counts) >= 2, "Expected multiple models assigned across 6 nodes"
