# Coding Conventions

**Analysis Date:** 2026-03-24

## Naming Patterns

**Files:**
- Use `snake_case.py` for all Python modules: `chain_functions.py`, `gossip_receiver.py`, `gpu_inference.py`
- Protobuf-generated files use `*_pb2.py` suffix: `mock_protocol_pb2.py`
- Test files use `test_` prefix: `test_capacity.py`, `test_model_assignment.py`
- `__init__.py` files exist in every package directory

**Functions:**
- Use `snake_case` for all functions and methods: `compute_assignment()`, `score_peer()`, `evict_stale()`
- Private/internal methods use single underscore prefix: `_handle_message()`, `_validate_ratios()`, `_make_nested_key()`
- Helper functions in tests use underscore prefix: `_passing_metrics()`, `_make_record()`, `_dht_key()`

**Variables:**
- Use `snake_case` for local variables and instance attributes: `peer_id`, `tee_score`, `current_counts`
- Module-level constants use `UPPER_SNAKE_CASE`: `SCORE_REAL_HARDWARE`, `GOSSIPSUB_PROTOCOL_ID`, `HEARTBEAT_TOPIC`
- Test constants use `UPPER_SNAKE_CASE`: `PEER_A`, `PEER_B`, `EPOCH`, `MODEL_A`, `API_KEY`

**Classes:**
- Use `PascalCase` for all classes: `CapacityTable`, `GpuInferenceScoring`, `NodeEntry`, `ModelRegistry`
- Dataclasses and Pydantic models follow the same convention: `PeerScore`, `NodeJoinMessage`, `HealthResponse`
- Test classes use `Test` prefix: `TestFrontierApp`, `TestTeeQuoteValidation`, `TestAuthEnforcement`

**Type Aliases:**
- Use `TProtocol` from libp2p (external convention)

## Code Style

**Formatting:**
- **Ruff** (Black-compatible) is the primary formatter, configured in `pyproject.toml`
- Line length: **120 characters** (Ruff config)
- Pre-commit also runs **Black** (rev 23.12.1) — legacy; Ruff formatter is the primary tool
- Note: pre-commit `.pre-commit-config.yaml` uses flake8 with `max-line-length=100` — conflicts with Ruff's 120. Ruff is authoritative.

**Linting:**
- **Ruff** lint rules enabled: `F` (Pyflakes), `E` (pycodestyle errors), `W` (pycodestyle warnings), `I` (isort), `D` (pydocstyle)
- Numerous pydocstyle rules are **ignored**: D100-D107 (missing docstrings for modules/classes/methods), D200, D203, D204, D205, D212, D400, D401, D412, D415
- This means: docstrings are NOT required on every module, class, or function — but when present, they should follow Google/NumPy style
- `__init__.py` and `*_pb2*.py` files are excluded from linting

**Type Checking:**
- **mypy** is configured with strict settings in `pyproject.toml`: `disallow_untyped_defs = true`, `strict_equality = true`, `check_untyped_defs = true`
- **pyrefly** (Meta's type checker) is also configured as a dev dependency
- `ignore_missing_imports = true` — third-party stubs are not enforced

**Pre-commit Hooks (`.pre-commit-config.yaml`):**
- trailing-whitespace, end-of-file-fixer, check-yaml, check-json, check-toml
- check-added-large-files, check-merge-conflict, debug-statements, mixed-line-ending
- Black (formatting), isort (import sorting), flake8 (linting), mypy (type checking)

## Import Organization

**Order (enforced by Ruff isort):**
1. `from __future__ import annotations` (when used — common pattern)
2. Standard library imports: `import json`, `import logging`, `import time`
3. Third-party imports: `import pytest`, `from fastapi import ...`, `from pydantic import ...`
4. First-party imports: `from subnet.xxx import ...`, `from tests.xxx import ...`

**Configuration (`pyproject.toml` `[tool.ruff.lint.isort]`):**
- `force-wrap-aliases = true`
- `combine-as-imports = true`
- `known-first-party = ["subnet", "tests"]`
- `force-to-top = ["pytest"]` — pytest imports go first within their group
- `force-sort-within-sections = true`

**Path Aliases:**
- No path aliases configured. All imports use full dotted paths: `from subnet.utils.db.database import RocksDB`

**Common Import Patterns:**
```python
# Standard pattern for source files
from __future__ import annotations
import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from subnet.node.protocol import NodeValidatorResult
from subnet.node.scoring import BaseNodeScoring, PeerScore

logger = logging.getLogger(__name__)
```

```python
# Standard pattern for test files
from __future__ import annotations
import pytest
from subnet.frontier.capacity import CapacityTable
from subnet.frontier.app import create_app
```

## Error Handling

**Patterns:**

1. **Return error objects instead of raising** — Scoring and protocol layers return result dataclasses with `success=False` and `error` string rather than raising exceptions:
   ```python
   # subnet/node/protocol.py
   return NodeValidatorResult(peer_id=peer_id, success=False, error="timeout")
   ```

2. **Catch-and-score-zero in score_all** — The `BaseNodeScoring.score_all()` method in `subnet/node/scoring.py` catches all exceptions from `score_peer()` and returns `PeerScore(score=0.0, reason=f"scoring_error:{exc}")`:
   ```python
   except Exception as exc:
       logger.warning("[Scoring] error scoring %s: %s", result.peer_id[:16], exc)
       scores[result.peer_id] = PeerScore(peer_id=result.peer_id, score=0.0, reason=f"scoring_error:{exc}")
   ```

3. **Assertions for programming errors** — Use `assert` for invariants that should never be violated:
   ```python
   # subnet/utils/db/database.py
   assert base_path is not None, "Path must be specified"
   ```

4. **ValueError for invalid inputs** — Pydantic validation and dataclass `__post_init__` raise `ValueError`:
   ```python
   # subnet/node/scoring.py
   if not 0.0 <= self.score <= 1.0:
       raise ValueError(f"score must be in [0,1], got {self.score} for {self.peer_id}")
   ```

5. **HTTPException for API errors** — FastAPI routes raise `HTTPException` for auth failures:
   ```python
   # subnet/frontier/app.py
   raise HTTPException(status_code=401, detail="missing authorization header")
   ```

6. **JSONResponse for business-logic errors** — Frontier returns structured error responses:
   ```python
   return JSONResponse(status_code=503, content={"error": "model_unavailable"})
   return JSONResponse(status_code=429, content={"error": "capacity_exceeded", "retry_after": 5})
   ```

7. **try/except KeyError for dict lookups** — RocksDB wrapper catches KeyError and returns defaults:
   ```python
   # subnet/utils/db/database.py
   try:
       return self.store[key]
   except KeyError:
       return default
   ```

8. **tenacity retry for chain calls** — `subnet/hypertensor/chain_functions.py` uses tenacity decorators for RPC retries:
   ```python
   from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_fixed
   ```

## Logging

**Framework:** Python standard `logging` module

**Logger Creation Patterns:**

1. **`__name__` loggers** (preferred for library code):
   ```python
   logger = logging.getLogger(__name__)
   ```
   Used in: `subnet/tee/verifier.py`, `subnet/node/mock.py`, `subnet/node/protocol.py`, `subnet/node/scoring.py`, `subnet/hypertensor/chain_functions.py`

2. **Named loggers** (for server/subsystem identification):
   ```python
   logger = logging.getLogger("server/1.0.0")
   logger = logging.getLogger("consensus/1.0.0")
   ```
   Used in: `subnet/server/server.py`, `subnet/consensus/consensus.py`

**Log Setup:**
- `logging.basicConfig()` called at module level in server/consensus entry points with format: `"%(asctime)s - %(name)s - %(levelname)s - %(message)s"`
- JSON structured logging available via `subnet/utils/logging.py` (`JsonFormatter`) activated by `LOG_JSON=true` environment variable
- JsonFormatter outputs: `{"timestamp": "...", "level": "...", "logger": "...", "message": "...", ...extra_fields}`

**Log Level Conventions:**
- `WARNING` for rejection/failure reasons (TEE verification failures, scoring errors)
- `INFO` for operational flow (startup, epoch changes)
- `DEBUG` for per-peer scoring details

**Structured Logging Pattern:**
```python
logger.debug(
    "[Scoring] peer=%s score=%.3f reason=%s",
    result.peer_id[:16], ps.score, ps.reason,
)
```

**When to Log:**
- Log at WARNING when rejecting a peer (TEE failure, attestation failure)
- Log at DEBUG for individual scoring results
- Use `extra={"key": value}` kwargs with JsonFormatter for queryable structured fields

## Comments

**When to Comment:**
- Section dividers in source files use comment blocks with `# ──` or `# ===` or `# ---`:
  ```python
  # ── helpers ───────────────────────────────────────────────────────────────────
  # =========================================================================
  # Simple key:value storage
  # =========================================================================
  # ------------------------------------------------------------------
  # Endpoints
  # ------------------------------------------------------------------
  ```
- Inline comments explain non-obvious logic, especially scoring formulas and verification pipelines

**Docstrings:**
- Module-level docstrings are present on most files (triple-quoted, descriptive)
- Class docstrings describe purpose and key attributes
- Function docstrings use **Google/NumPy hybrid style** with `Parameters`, `Returns`, `Fields` sections:
  ```python
  def compute_assignment(
      registry: ModelRegistry,
      current_counts: dict[str, int],
      total_nodes: int,
  ) -> str:
      """Compute which model this joining node should run.  Deterministic.

      Parameters:
          registry: The subnet's model registry (ratios + measurements).
          current_counts: Mapping of model name -> current number of nodes.
          total_nodes: Total number of nodes currently in the cluster.

      Returns:
          The name of the model with the highest current deficit.
      """
  ```
- Dataclass docstrings use `Fields` or `Attributes` sections with `------` underlines
- Test function docstrings are concise single-line descriptions of expected behavior

**TSDoc/JSDoc:** N/A (Python-only codebase)

## Function Design

**Size:**
- Functions are generally short (10-40 lines). Largest files are `chain_functions.py` (2452 lines) and `chain_data.py` (1684 lines) which are data-heavy RPC wrappers.

**Parameters:**
- Use keyword-only arguments (`*`) for mutation methods with multiple params to prevent accidental partial updates:
  ```python
  def update(self, peer_id: str, *, model: str, load: float, latency_p95: float) -> None:
  ```
- Dataclass constructors use positional + keyword args
- Factory functions accept `**kwargs` for extensibility

**Return Values:**
- Use dataclasses for structured returns: `PeerScore`, `VerificationResult`, `NodeMinerResult`, `NodeValidatorResult`
- Use `Optional[T]` / `T | None` for lookups that may fail: `pick_node() -> Optional[NodeEntry]`
- Use `dict` for batch results: `score_all() -> Dict[str, PeerScore]`

## Module Design

**Exports:**
- No `__all__` usage detected. Modules export everything at top level.
- Public API is defined by what's imported; private helpers use underscore prefix.

**Barrel Files:**
- `__init__.py` files are mostly empty or minimal. No barrel re-exports detected.
- Each module is imported by its full path: `from subnet.frontier.capacity import CapacityTable`

## Data Modeling

**Pydantic models** for:
- API request/response schemas (`subnet/api/models.py`)
- GossipSub messages (`subnet/frontier/messages.py`)
- Configuration via `pydantic-settings` (`subnet/api/config.py`)

**Dataclasses** for:
- Internal data structures: `PeerScore`, `NodeEntry`, `VerificationResult`, `EpochData`
- Protocol results: `NodeMinerResult`, `NodeValidatorResult`
- Use `frozen=True` for immutable configs: `ModelConfig`

**Abstract Base Classes** for extensibility:
- `BaseNodeProtocol` (`subnet/node/protocol.py`) — protocol interface
- `BaseNodeScoring` (`subnet/node/scoring.py`) — scoring interface

## Type Annotations

**Usage:** Type annotations are used consistently throughout the codebase.
- Function signatures are fully annotated: `def score_peer(self, result: NodeValidatorResult, epoch: int) -> PeerScore:`
- Class attributes are annotated in dataclasses and Pydantic models
- Modern union syntax (`str | None`) used alongside legacy `Optional[str]` — both are present
- `from __future__ import annotations` used in newer files for forward references
- `Dict`, `List`, `Optional` from `typing` coexist with built-in `dict`, `list`, `str | None` — newer files prefer built-in syntax

---

*Convention analysis: 2026-03-24*
