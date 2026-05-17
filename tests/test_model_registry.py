"""Tests for ModelRegistry — owner-defined model ratios and measurements."""

import pytest

from subnet.models.registry import ModelConfig, ModelRegistry

# ---------------------------------------------------------------------------
# Shared sample registry
# ---------------------------------------------------------------------------

SAMPLE_REGISTRY = ModelRegistry(
    models=[
        ModelConfig(name="nvidia/nemotron-3-8b", ratio=0.5, measurement="aa" * 48),
        ModelConfig(name="nvidia/nemotron-3-49b", ratio=0.3, measurement="bb" * 48),
        ModelConfig(name="meta/llama-3.1-70b", ratio=0.2, measurement="cc" * 48),
    ]
)


# ---------------------------------------------------------------------------
# 1. test_model_config_fields
# ---------------------------------------------------------------------------


def test_model_config_fields():
    cfg = ModelConfig(
        name="nvidia/nemotron-3-8b",
        ratio=0.5,
        measurement="aa" * 48,
    )
    assert cfg.name == "nvidia/nemotron-3-8b"
    assert cfg.ratio == 0.5
    assert cfg.measurement == "aa" * 48
    assert cfg.target_p95_ms == 5000.0


# ---------------------------------------------------------------------------
# 2. test_model_config_ratio_validation
# ---------------------------------------------------------------------------


def test_model_config_ratio_validation():
    with pytest.raises((ValueError, TypeError)):
        ModelConfig(name="bad", ratio=1.5, measurement="aa" * 48)

    with pytest.raises((ValueError, TypeError)):
        ModelConfig(name="bad", ratio=-0.1, measurement="aa" * 48)


# ---------------------------------------------------------------------------
# 3. test_ratios_sum_to_one
# ---------------------------------------------------------------------------


def test_ratios_sum_to_one():
    # Must not raise — the sample registry ratios sum to 1.0
    registry = ModelRegistry(
        models=[
            ModelConfig(name="nvidia/nemotron-3-8b", ratio=0.5, measurement="aa" * 48),
            ModelConfig(name="nvidia/nemotron-3-49b", ratio=0.3, measurement="bb" * 48),
            ModelConfig(name="meta/llama-3.1-70b", ratio=0.2, measurement="cc" * 48),
        ]
    )
    assert len(registry.models) == 3


# ---------------------------------------------------------------------------
# 4. test_ratios_not_sum_to_one_raises
# ---------------------------------------------------------------------------


def test_ratios_not_sum_to_one_raises():
    with pytest.raises(ValueError):
        ModelRegistry(
            models=[
                ModelConfig(name="nvidia/nemotron-3-8b", ratio=0.5, measurement="aa" * 48),
                ModelConfig(name="nvidia/nemotron-3-49b", ratio=0.4, measurement="bb" * 48),
                # sum = 0.9 — should raise
            ]
        )


# ---------------------------------------------------------------------------
# 5. test_measurement_for_model
# ---------------------------------------------------------------------------


def test_measurement_for_model():
    assert SAMPLE_REGISTRY.measurement_for("nvidia/nemotron-3-8b") == "aa" * 48
    assert SAMPLE_REGISTRY.measurement_for("nvidia/nemotron-3-49b") == "bb" * 48
    assert SAMPLE_REGISTRY.measurement_for("meta/llama-3.1-70b") == "cc" * 48
    assert SAMPLE_REGISTRY.measurement_for("unknown/model") is None


# ---------------------------------------------------------------------------
# 6. test_target_count
# ---------------------------------------------------------------------------


def test_target_count():
    counts = SAMPLE_REGISTRY.target_counts(10)
    # 50% of 10 = 5, 30% of 10 = 3, 20% of 10 = 2
    assert counts["nvidia/nemotron-3-8b"] == 5
    assert counts["nvidia/nemotron-3-49b"] == 3
    assert counts["meta/llama-3.1-70b"] == 2
    assert sum(counts.values()) == 10


# ---------------------------------------------------------------------------
# 7. test_target_count_rounds_correctly
# ---------------------------------------------------------------------------


def test_target_count_rounds_correctly():
    # 7 nodes with 50/30/20 ratio:
    # 0.5*7=3.5, 0.3*7=2.1, 0.2*7=1.4 — naive floor gives 3+2+1=6, one lost
    counts = SAMPLE_REGISTRY.target_counts(7)
    total = sum(counts.values())
    assert total == 7, f"Expected 7 total nodes, got {total}: {counts}"


# ---------------------------------------------------------------------------
# 8. test_deficit_model
# ---------------------------------------------------------------------------


def test_deficit_model():
    # nemotron-49b: target=3 actual=2  → deficit=1
    # llama:        target=2 actual=1  → deficit=1
    # tie → lexicographic → "meta/llama-3.1-70b" < "nvidia/nemotron-3-49b"
    current = {
        "nvidia/nemotron-3-8b": 5,   # at target
        "nvidia/nemotron-3-49b": 2,  # deficit 1
        "meta/llama-3.1-70b": 1,    # deficit 1
    }
    result = SAMPLE_REGISTRY.highest_deficit_model(current, total_nodes=9)
    assert result == "meta/llama-3.1-70b"


# ---------------------------------------------------------------------------
# 9. test_deficit_model_all_satisfied
# ---------------------------------------------------------------------------


def test_deficit_model_all_satisfied():
    # All at target for total_nodes=10 — pick highest ratio model
    current = {
        "nvidia/nemotron-3-8b": 5,
        "nvidia/nemotron-3-49b": 3,
        "meta/llama-3.1-70b": 2,
    }
    result = SAMPLE_REGISTRY.highest_deficit_model(current, total_nodes=10)
    assert result == "nvidia/nemotron-3-8b"
