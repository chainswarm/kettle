"""Model self-assignment — compute which model a joining node should run."""

from __future__ import annotations

from subnet.models.registry import ModelRegistry


def compute_assignment(
    registry: ModelRegistry,
    current_counts: dict[str, int],
    total_nodes: int,
) -> str:
    """Compute which model this joining node should run.  Deterministic.

    Parameters:
        registry: The subnet's model registry (ratios + measurements).
        current_counts: Mapping of model name → current number of nodes
            already running that model.
        total_nodes: Total number of nodes currently in the cluster
            (before this node joins).

    Returns:
        The name of the model with the highest current deficit relative to its
        target allocation.
    """
    return registry.highest_deficit_model(current_counts, total_nodes)
