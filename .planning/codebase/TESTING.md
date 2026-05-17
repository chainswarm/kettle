# Testing Patterns

**Analysis Date:** 2026-03-24

## Test Framework

**Runner:**
- pytest >= 7.0.0
- Config: `pyproject.toml` section `[tool.pytest.ini_options]`

**Async Framework:**
- pytest-trio (primary) — tests use `@pytest.mark.trio` for async
- pytest-asyncio also listed as test dependency but trio is the convention in test files

**Additional Plugins:**
- pytest-xdist (parallel execution)
- pytest-timeout (test timeout enforcement)
- pytest-rerunfailures (flaky test retry)
- pytest-mock (mock fixtures)

**Run Commands:**
```bash
pytest                           # Run all tests (default: tests/ directory)
pytest tests/                    # Explicit test directory
pytest -n auto                   # Parallel execution with xdist
pytest tests/hypertensor         # Chain integration tests (requires live Substrate node)
tox                              # Full multi-Python test matrix
tox -e py310-lint                # Lint-only environment
```

**Pytest Configuration (`pyproject.toml`):**
```ini
addopts = "-v --showlocals --durations 50 --maxfail 10"
testpaths = ["tests"]
log_date_format = "%m-%d %H:%M:%S"
log_format = "%(levelname)8s  %(asctime)s  %(filename)20s  %(message)s"
markers = [
    "slow: mark test as slow",
    "flaky: mark test as flaky (may fail intermittently)",
]
xfail_strict = true
```

## Test File Organization

**Location:** Tests live in a top-level `tests/` directory, mirroring the `subnet/` package structure.

**Naming:**
- Test files: `test_*.py` (always prefixed)
- Test classes: `Test*` (PascalCase with Test prefix)
- Test functions: `test_*` (snake_case with test_ prefix)

**Structure:**
```
tests/
├── __init__.py
├── api/
│   ├── __init__.py
│   └── test_populate_db.py
├── consensus/
│   ├── __init__.py
│   ├── test_chain_overwatch_reporter.py
│   ├── test_chain_submitter.py
│   ├── test_consensus_utils.py
│   └── test_overwatch_salt.py
├── frontier/
│   ├── __init__.py
│   ├── test_app.py
│   ├── test_capacity.py
│   ├── test_e2e_flow.py
│   ├── test_messages.py
│   └── test_routing_integration.py
├── hypertensor/
│   ├── __init__.py
│   ├── test_mock_db.py
│   └── test_rpc.py              # Requires live Substrate node
├── tee/
│   ├── __init__.py
│   ├── test_consensus_integration.py
│   ├── test_envelope.py
│   ├── test_gpu_attestation.py
│   ├── test_gramine_manifest.py
│   ├── test_mock_backend.py
│   ├── test_publisher.py
│   ├── test_quote.py
│   ├── test_ratls.py
│   ├── test_sealed.py
│   └── test_verifier.py
├── mock_nim_server.py            # Test helper (not a test file)
├── test_example.py
├── test_gossip_validation.py
├── test_gpu_scoring.py
├── test_heartbeat_v2.py
├── test_json_logging.py
├── test_mock_node.py
├── test_model_assignment.py
├── test_model_assignment_integration.py
├── test_model_registry.py
├── test_overwatch_integration.py
└── test_scoring_integration.py
```

**Conftest:**
- Root `conftest.py` at project root: excludes `tests/hypertensor/*` from default collection (requires live Substrate node)
- No subdirectory conftest files

## Test Structure

**Two main patterns coexist:**

### Pattern 1: Module-level functions with section dividers (unit tests)

Used in: `tests/test_model_assignment.py`, `tests/test_capacity.py`, `tests/frontier/test_messages.py`, `tests/test_heartbeat_v2.py`

```python
"""Tests for CapacityTable — frontier routing component."""

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
    assert nodes[0].peer_id == "peer-1"


# ---------------------------------------------------------------------------
# test_least_loaded_routing
# ---------------------------------------------------------------------------

def test_least_loaded_routing():
    table = CapacityTable()
    table.update("peer-a", model="gpt4", load=0.8, latency_p95=200.0)
    table.update("peer-b", model="gpt4", load=0.2, latency_p95=150.0)

    picked = table.pick_node("gpt4")
    assert picked is not None
    assert picked.peer_id == "peer-b"
```

### Pattern 2: Test classes with fixtures (integration tests)

Used in: `tests/frontier/test_app.py`, `tests/frontier/test_routing_integration.py`, `tests/frontier/test_e2e_flow.py`, `tests/test_gossip_validation.py`

```python
"""Integration tests for the Frontier FastAPI application."""

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
        return ct

    @pytest.fixture
    def client(self, capacity):
        app = create_app(capacity_table=capacity, api_keys={"test-key"})
        return TestClient(app)

    def test_health(self, client):
        """GET /health returns 200 with status=ok."""
        resp = client.get("/health")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"
```

### Pattern 3: Async tests with `@pytest.mark.trio`

Used in: `tests/test_scoring_integration.py`, `tests/test_gpu_scoring.py`, `tests/test_gossip_validation.py`

```python
@pytest.fixture
def scoring(tmp_path):
    db = RocksDB(str(tmp_path / "scoring_db"))
    return GpuInferenceScoring(db=db, subnet_id=1, config=None)


@pytest.mark.trio
async def test_perfect_score_real_hardware(scoring):
    """tee_score=1.0 + all quality checks -> score=1.0."""
    result = NodeValidatorResult(
        peer_id=PEER_A,
        success=True,
        metrics=_passing_metrics(tee_score=1.0),
    )
    ps = await scoring.score_peer(result, EPOCH)
    assert ps.score == 1.0
    assert ps.reason == "inference_ok"
```

## Test Docstrings

Every test function has a concise docstring explaining expected behavior:
```python
def test_first_node_gets_highest_ratio():
    """With no existing nodes, the first joiner should get the model with the
    highest ratio (nvidia/nemotron-3-8b at 0.5)."""
```

Format: one-line or two-line description of the scenario and expected outcome. Many use the pattern `"input_condition -> expected_output"`:
```python
"""tee_score=1.0 + gpu_attested + all quality checks -> score=1.0, reason='inference_ok'."""
```

## Fixtures

**Common Fixture Patterns:**

1. **`tmp_path`-backed RocksDB** — Used for any test needing database:
   ```python
   @pytest.fixture
   def scoring(tmp_path):
       db = RocksDB(str(tmp_path / "test_db"))
       return GpuInferenceScoring(db=db, subnet_id=1, config=None)
   ```

2. **RocksDB with cleanup** — Some tests explicitly close the store:
   ```python
   @pytest.fixture
   def db(tmp_path):
       database = RocksDB(base_path=str(tmp_path / "gossip_test"))
       yield database
       database.store.close()
   ```

3. **FastAPI TestClient** — For API integration tests:
   ```python
   @pytest.fixture
   def client(self, capacity):
       app = create_app(capacity_table=capacity, api_keys={"test-key"})
       return TestClient(app)
   ```

4. **CapacityTable** — Pre-populated or empty:
   ```python
   @pytest.fixture
   def capacity(self):
       return CapacityTable(staleness_threshold=1.0)
   ```

5. **Fixture chaining** — `client` depends on `capacity`:
   ```python
   @pytest.fixture
   def capacity(self): ...

   @pytest.fixture
   def client(self, capacity): ...
   ```

**Fixture Location:**
- Defined inline in test files (either at module level or inside test classes)
- No shared `conftest.py` fixtures in subdirectories
- Root `conftest.py` only contains collection exclusion, no fixtures

## Mocking

**Framework:** `unittest.mock.MagicMock` (standard library) + `pytest-mock` available

**Patterns:**

1. **MagicMock for libp2p objects** — Complex P2P infrastructure is mocked:
   ```python
   from unittest.mock import MagicMock

   @pytest.fixture
   def receiver(db):
       return GossipReceiver(
           gossipsub=MagicMock(),
           pubsub=MagicMock(),
           termination_event=trio.Event(),
           db=db,
           topics=[TEE_QUOTE_TOPIC, RATLS_CERT_TOPIC, _WORK_TOPIC],
       )
   ```

2. **Mock GossipSub messages** — Helper functions build fake messages:
   ```python
   def make_gossip_message(from_peer: str, topic: str, data: bytes):
       msg = MagicMock()
       msg.from_id = base58.b58decode(from_peer)
       msg.topicIDs = [topic]
       msg.data = data
       return msg
   ```

3. **Inline fake classes** — Small fake data objects for consensus tests:
   ```python
   class FakeData:
       attests = [1, 2]
       subnet_nodes = [1, 2, 3, 4]
   assert get_attestation_ratio(FakeData()) == 0.5
   ```

**What to Mock:**
- libp2p infrastructure (gossipsub, pubsub, host)
- Network transports and connections
- Substrate/blockchain RPC calls (excluded from default test run)

**What NOT to Mock:**
- Business logic (scoring, routing, model assignment)
- Data structures (CapacityTable, ModelRegistry, RocksDB)
- FastAPI application (use TestClient instead)
- Pydantic serialization/deserialization

## Test Helpers

**Helper functions** are defined at module level with underscore prefix:

```python
# Common helper pattern — build valid metrics dict
def _passing_metrics(tee_score: float = 1.0) -> dict:
    return {
        "tee_score": tee_score,
        "gpu_attested": True,
        "prompt_match": True,
        "has_content": True,
        "reasonable_latency": True,
    }
```

```python
# Helper for building test registries
def _registry(*specs: tuple[str, float, str]) -> ModelRegistry:
    models = [
        ModelConfig(name=name, ratio=ratio, measurement=_meas(meas_tag))
        for name, ratio, meas_tag in specs
    ]
    return ModelRegistry(models=models)
```

```python
# Helper for API request shortcuts
def _post_chat(self, client, model):
    return client.post(
        "/v1/chat/completions",
        json={"model": model, "messages": [{"role": "user", "content": "hi"}]},
        headers=self._auth(),
    )
```

**Test constants** at module level:
```python
PEER_A = "12D3KooWKxAhu5U8SreDZpokVkN6ciTBbsHxteo3Vmq6Cpuf8KEt"
PEER_B = "12D3KooWBPVJe1hUHC9JrZGXNBPVS2sJqJx4jqZm3CuFsmRKt7Np"
EPOCH = 100_000
MODEL_A = "nvidia/nemotron-3-49b"
API_KEY = "e2e-test-key"
AUTH_HEADERS = {"Authorization": f"Bearer {API_KEY}"}
```

## Coverage

**Requirements:**
- Codecov target: **80%** (project and patch)
- Threshold: 2% below target allowed
- Config: `codecov.yaml`

**Ignored paths:** `tests/`, `setup.py`, `**/__init__.py`, `docs/`

**View Coverage:**
```bash
pytest --cov=subnet tests/        # Generate coverage report
```

## Test Types

**Unit Tests:**
- Scope: Single class or function in isolation
- Examples: `tests/test_capacity.py`, `tests/test_model_assignment.py`, `tests/frontier/test_messages.py`, `tests/test_heartbeat_v2.py`, `tests/test_json_logging.py`
- Pattern: Direct instantiation, no fixtures needed beyond `tmp_path`
- Focus: Data structures, serialization roundtrips, pure logic

**Integration Tests:**
- Scope: Multiple components working together through realistic flows
- Examples: `tests/frontier/test_e2e_flow.py`, `tests/frontier/test_routing_integration.py`, `tests/test_scoring_integration.py`, `tests/test_model_assignment_integration.py`
- Pattern: Build a full subsystem (CapacityTable + FastAPI app + TestClient), exercise realistic scenarios
- Focus: Heartbeat -> capacity -> routing flows; scoring pipeline; model assignment across cluster

**Chain Tests (excluded by default):**
- Scope: Real Substrate RPC calls
- Location: `tests/hypertensor/`
- Requirement: Live Substrate node at `ws://127.0.0.1:9944`
- Excluded from default collection via `conftest.py`: `collect_ignore_glob = ["tests/hypertensor/*"]`
- Run separately: `pytest tests/hypertensor -n auto --timeout=1200`

**E2E Tests:**
- `tests/frontier/test_e2e_flow.py` — Full request lifecycle: node join/leave, load balancing, auth enforcement, graceful degradation
- Uses FastAPI `TestClient` for HTTP-level testing

## Common Assertion Patterns

**Direct equality:**
```python
assert ps.score == 1.0
assert ps.reason == "inference_ok"
assert resp.status_code == 200
```

**Containment:**
```python
assert "gpu_not_attested" in ps.reason
assert "nvidia/nemotron-3-49b" in body["models"]
```

**Set equality:**
```python
assert models == {"llama3", "mixtral", "gpt4"}
score_values = {ps.score for ps in scores.values()}
assert score_values == {1.0, 0.5, 0.0}
```

**Approximate equality (for floats):**
```python
assert restored.tee_score == pytest.approx(0.98)
assert restored.latency_p95_ms == pytest.approx(8.3)
```

**None checks:**
```python
assert result is None
assert picked is not None
assert measurement is not None
```

**Within tolerance (for distribution tests):**
```python
assert abs(actual - target) <= 1, (
    f"{name}: expected ~{target}, got {actual} (diff={actual - target})"
)
```

## Async Testing

**Pattern:** Use `@pytest.mark.trio` decorator for all async tests:
```python
@pytest.mark.trio
async def test_honest_quote_accepted(self, receiver, db, backend):
    """Quote from peer A with peer_id=A should be stored."""
    quote = backend.generate_quote(peer_id=PEER_A, epoch=EPOCH)
    msg = make_gossip_message(PEER_A, TEE_QUOTE_TOPIC, quote.to_bytes())
    await receiver._handle_message(msg)

    stored = db.nmap_get(TEE_QUOTE_TOPIC, f"{EPOCH}:{PEER_A}")
    assert stored is not None
```

**Note:** Sync tests do NOT use any async marker — the codebase mixes sync and async tests within the same file when appropriate.

## Error Testing

**Pattern:** Assert score=0.0 and check reason string for expected failure keywords:
```python
@pytest.mark.trio
async def test_no_gpu_attestation_zero_score(scoring):
    """gpu_attested=False -> score=0.0, reason contains 'gpu_not_attested'."""
    metrics = _passing_metrics(tee_score=1.0)
    metrics["gpu_attested"] = False
    result = NodeValidatorResult(peer_id=PEER_A, success=True, metrics=metrics)

    ps = await scoring.score_peer(result, EPOCH)

    assert ps.score == 0.0
    assert "gpu_not_attested" in ps.reason
```

**HTTP error testing:**
```python
def test_chat_completions_no_auth(self, client):
    """POST /v1/chat/completions without auth returns 401."""
    resp = client.post("/v1/chat/completions", json={...})
    assert resp.status_code == 401
```

## Writing New Tests

**For a new unit test:**
1. Create `tests/test_{feature}.py`
2. Add module-level docstring describing the test suite
3. Define constants (PEER_A, EPOCH, etc.) and helpers at module level
4. Write `test_` functions with descriptive docstrings
5. Use section dividers `# ---` between test functions

**For a new integration test:**
1. Create `tests/{subsystem}/test_{flow}.py`
2. Use a test class `class Test{FlowName}:`
3. Define fixtures for the component graph (db -> scoring, capacity -> client)
4. Write scenario-based tests with clear Arrange/Act/Assert structure
5. Group related tests with comment section dividers

**For a new async test:**
1. Add `@pytest.mark.trio` decorator
2. Use `async def test_*` signature
3. Use `await` for all async calls
4. Fixtures can be sync (pytest handles the bridging)

---

*Testing analysis: 2026-03-24*
