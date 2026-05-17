"""Model registry — owner-defined model ratios and TEE measurements."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ModelConfig:
    """Immutable configuration for a single model in the registry.

    Attributes:
        name: Model identifier (e.g. "nvidia/nemotron-3-49b").
        ratio: Fraction of the cluster that should run this model (0.0–1.0).
        measurement: SHA-384 hex digest of the model artefact (96 characters).
        target_p95_ms: Target p95 inference latency in milliseconds used for
            scoring.  Defaults to 5000 ms.
    """

    name: str
    ratio: float
    measurement: str
    target_p95_ms: float = 5000.0

    def __post_init__(self) -> None:
        if not (0.0 <= self.ratio <= 1.0):
            raise ValueError(
                f"ModelConfig.ratio must be in [0.0, 1.0], got {self.ratio!r}"
            )


class ModelRegistry:
    """Registry of models published on-chain by the subnet owner.

    Parameters:
        models: Ordered list of :class:`ModelConfig` instances.  The ratios
            must sum to 1.0 (within ±0.01 tolerance).
    """

    _RATIO_TOLERANCE: float = 0.01

    def __init__(self, models: list[ModelConfig]) -> None:
        self.models: list[ModelConfig] = list(models)
        self._validate_ratios()
        # Build a fast name → ModelConfig index.
        self._by_name: dict[str, ModelConfig] = {m.name: m for m in self.models}

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def _validate_ratios(self) -> None:
        total = sum(m.ratio for m in self.models)
        if abs(total - 1.0) > self._RATIO_TOLERANCE:
            raise ValueError(
                f"Model ratios must sum to 1.0 (±{self._RATIO_TOLERANCE}), "
                f"got {total:.6f}"
            )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def measurement_for(self, model_name: str) -> str | None:
        """Return the SHA-384 measurement for *model_name*, or None."""
        cfg = self._by_name.get(model_name)
        return cfg.measurement if cfg is not None else None

    def target_counts(self, total_nodes: int) -> dict[str, int]:
        """Compute target node count per model from ratios.

        Uses the largest-remainder method so that the counts always sum
        exactly to *total_nodes* with no lost nodes.
        """
        if total_nodes <= 0:
            return {m.name: 0 for m in self.models}

        # Step 1 — floor counts and fractional remainders.
        floors: list[int] = []
        remainders: list[tuple[float, int]] = []  # (remainder, original_index)
        for i, m in enumerate(self.models):
            exact = m.ratio * total_nodes
            f = int(exact)
            floors.append(f)
            remainders.append((exact - f, i))

        # Step 2 — distribute leftover slots to models with largest remainder.
        leftover = total_nodes - sum(floors)
        # Sort descending by remainder; tie-break by index for stability.
        remainders.sort(key=lambda x: (-x[0], x[1]))
        for k in range(leftover):
            idx = remainders[k][1]
            floors[idx] += 1

        return {self.models[i].name: floors[i] for i in range(len(self.models))}

    def highest_deficit_model(
        self,
        current_counts: dict[str, int],
        total_nodes: int,
    ) -> str:
        """Return the model with the largest (target − actual) deficit.

        The target is computed via ``target_counts(total_nodes + 1)`` to
        account for the node that is about to join.

        Tie-breaking rules:
          1. Largest deficit wins.
          2. On a tie, lexicographic model name (deterministic).
          3. When all deficits are zero or negative, return the model with
             the highest ratio.
        """
        targets = self.target_counts(total_nodes + 1)

        best_name: str | None = None
        best_deficit: float = float("-inf")

        for m in self.models:
            actual = current_counts.get(m.name, 0)
            deficit = targets[m.name] - actual

            if best_name is None:
                best_name = m.name
                best_deficit = deficit
                continue

            if deficit > best_deficit:
                best_name = m.name
                best_deficit = deficit
            elif deficit == best_deficit:
                # Tie-break: lexicographic model name.
                if m.name < best_name:
                    best_name = m.name

        # If no model has a positive deficit, fall back to highest-ratio model.
        if best_deficit <= 0:
            best_name = max(self.models, key=lambda m: m.ratio).name

        assert best_name is not None  # models list is non-empty by construction
        return best_name
