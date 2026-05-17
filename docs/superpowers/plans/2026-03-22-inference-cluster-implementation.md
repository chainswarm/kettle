# TEE Inference Cluster — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the TEE inference cluster design — a decentralized OpenRouter backend with TEE+GPU attested inference nodes, smart frontier router, Kata container isolation, and owner-defined model ratios.

**Architecture:** P2P mesh (libp2p) with smart frontier router, Kata containers on CVM, NVIDIA NIM for inference, dual CPU+GPU attestation, self-computed model assignment from on-chain ratios.

**Tech Stack:** Python 3.12, trio (async), libp2p, FastAPI (frontier), httpx (NIM client), NVIDIA NIM + nv-attestation-sdk, Kata Containers, RocksDB, Hypertensor chain.

**Spec:** [`docs/superpowers/specs/2026-03-22-tee-inference-cluster-design.md`](../specs/2026-03-22-tee-inference-cluster-design.md)

---

## Phase overview

| Phase | Name | Depends on | What it delivers |
|-------|------|-----------|-----------------|
| 1 | Heartbeat v2 + Model Registry | — | Extended heartbeat with GPU/model metrics, on-chain model config |
| 2 | GPU Attestation | — | nv-attestation-sdk integration in scoring pipeline |
| 3 | Frontier Router | Phase 1 | OpenAI-compatible API, capacity table, least-loaded routing |
| 4 | Kata Integration | — | Container runtime config, dm-verity, OPA policy |
| 5 | Node Lifecycle | Phases 1-4 | Join/leave/rebalance, model self-assignment, end-to-end flow |

---

## Phase 1: Heartbeat v2 + Model Registry

### Task 1.1: Extend HeartbeatData with GPU and model fields

**Files:**
- Modify: `subnet/utils/pubsub/heartbeat.py`
- Test: `tests/test_heartbeat_v2.py`

- [ ] **Step 1: Write failing test for new heartbeat fields**

```python
# tests/test_heartbeat_v2.py
import pytest
from subnet.utils.pubsub.heartbeat import HeartbeatData


class TestHeartbeatV2:

    def test_heartbeat_includes_version(self):
        hb = HeartbeatData(epoch=1, subnet_id=1, subnet_node_id=1)
        assert hb.version == 1

    def test_heartbeat_includes_models(self):
        hb = HeartbeatData(
            epoch=1, subnet_id=1, subnet_node_id=1,
            models=["nvidia/nemotron-3-49b"],
        )
        assert hb.models == ["nvidia/nemotron-3-49b"]

    def test_heartbeat_includes_gpu_metrics(self):
        hb = HeartbeatData(
            epoch=1, subnet_id=1, subnet_node_id=1,
            gpu="H100",
            gpu_uuid="GPU-abc123",
            vram_total_gb=80,
            vram_used_gb=45,
            requests_in_flight=3,
            latency_p95_ms=890,
        )
        assert hb.gpu == "H100"
        assert hb.vram_total_gb == 80
        assert hb.requests_in_flight == 3

    def test_heartbeat_v2_serialization_roundtrip(self):
        hb = HeartbeatData(
            epoch=1, subnet_id=1, subnet_node_id=1,
            version=1,
            models=["nvidia/nemotron-3-49b"],
            gpu="H100",
            gpu_uuid="GPU-abc123",
            tee_score=1.0,
            vram_total_gb=80,
            vram_used_gb=45,
            requests_in_flight=3,
            latency_p95_ms=890,
        )
        restored = HeartbeatData.from_json(hb.to_json())
        assert restored.version == 1
        assert restored.models == ["nvidia/nemotron-3-49b"]
        assert restored.gpu == "H100"
        assert restored.tee_score == 1.0
        assert restored.requests_in_flight == 3

    def test_heartbeat_backward_compat_no_new_fields(self):
        """Old heartbeats without new fields should still deserialize."""
        hb = HeartbeatData(epoch=1, subnet_id=1, subnet_node_id=1)
        restored = HeartbeatData.from_json(hb.to_json())
        assert restored.models is None
        assert restored.gpu is None
        assert restored.version == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_heartbeat_v2.py -v`
Expected: FAIL — `HeartbeatData` doesn't accept new fields.

- [ ] **Step 3: Add new fields to HeartbeatData**

In `subnet/utils/pubsub/heartbeat.py`, extend the `HeartbeatData` class:

```python
class HeartbeatData(BaseModel):
    # Existing fields
    epoch: int
    subnet_id: int
    subnet_node_id: int
    # v2 fields (optional for backward compat)
    version: int = 1
    peer_id: str | None = None  # redundant with envelope, but aids debugging
    models: list[str] | None = None  # list for future multi-model support
    gpu: str | None = None
    gpu_uuid: str | None = None
    gpu_attested: bool = False
    tee_score: float = 0.0
    vram_total_gb: int | None = None
    vram_used_gb: int | None = None
    requests_in_flight: int = 0
    latency_p95_ms: float = 0.0
    nim_version: str | None = None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_heartbeat_v2.py -v && python3 -m pytest tests/ -x -q`
Expected: All new tests PASS, all 260 existing tests PASS.

- [ ] **Step 5: Commit**

```bash
git add subnet/utils/pubsub/heartbeat.py tests/test_heartbeat_v2.py
git commit -m "feat: extend HeartbeatData with GPU/model metrics (v2)"
```

---

### Task 1.2: Model registry config

**Files:**
- Create: `subnet/models/registry.py`
- Create: `subnet/models/__init__.py`
- Test: `tests/test_model_registry.py`

- [ ] **Step 1: Write failing tests for model registry**

```python
# tests/test_model_registry.py
import pytest
from subnet.models.registry import ModelConfig, ModelRegistry


class TestModelConfig:

    def test_model_config_fields(self):
        mc = ModelConfig(
            name="nvidia/nemotron-3-49b",
            ratio=0.3,
            measurement="e5f6a7b8" * 12,
        )
        assert mc.name == "nvidia/nemotron-3-49b"
        assert mc.ratio == 0.3
        assert len(mc.measurement) == 96  # SHA-384 hex

    def test_model_config_ratio_validation(self):
        with pytest.raises(ValueError):
            ModelConfig(name="test", ratio=1.5, measurement="a" * 96)
        with pytest.raises(ValueError):
            ModelConfig(name="test", ratio=-0.1, measurement="a" * 96)


class TestModelRegistry:

    def _sample_registry(self):
        return ModelRegistry(models=[
            ModelConfig(name="nvidia/nemotron-3-8b", ratio=0.5, measurement="aa" * 48),
            ModelConfig(name="nvidia/nemotron-3-49b", ratio=0.3, measurement="bb" * 48),
            ModelConfig(name="meta/llama-3.1-70b", ratio=0.2, measurement="cc" * 48),
        ])

    def test_ratios_sum_to_one(self):
        reg = self._sample_registry()
        assert abs(reg.total_ratio - 1.0) < 0.01

    def test_ratios_not_sum_to_one_raises(self):
        with pytest.raises(ValueError, match="sum to 1.0"):
            ModelRegistry(models=[
                ModelConfig(name="a", ratio=0.5, measurement="aa" * 48),
                ModelConfig(name="b", ratio=0.3, measurement="bb" * 48),
            ])

    def test_measurement_for_model(self):
        reg = self._sample_registry()
        assert reg.measurement_for("nvidia/nemotron-3-49b") == "bb" * 48
        assert reg.measurement_for("unknown") is None

    def test_target_count(self):
        reg = self._sample_registry()
        counts = reg.target_counts(total_nodes=10)
        assert counts["nvidia/nemotron-3-8b"] == 5
        assert counts["nvidia/nemotron-3-49b"] == 3
        assert counts["meta/llama-3.1-70b"] == 2

    def test_target_count_rounds_correctly(self):
        reg = self._sample_registry()
        counts = reg.target_counts(total_nodes=7)
        assert sum(counts.values()) == 7  # must not lose nodes

    def test_deficit_model(self):
        reg = self._sample_registry()
        current = {"nvidia/nemotron-3-8b": 5, "nvidia/nemotron-3-49b": 2, "meta/llama-3.1-70b": 1}
        model = reg.highest_deficit_model(current, total_nodes=10)
        # nemotron-49b: target=3, actual=2 → deficit=1
        # llama-70b: target=2, actual=1 → deficit=1
        # Tie: lexicographic → "meta/llama-3.1-70b" < "nvidia/nemotron-3-49b"
        assert model == "meta/llama-3.1-70b"

    def test_deficit_model_all_satisfied(self):
        reg = self._sample_registry()
        current = {"nvidia/nemotron-3-8b": 5, "nvidia/nemotron-3-49b": 3, "meta/llama-3.1-70b": 2}
        model = reg.highest_deficit_model(current, total_nodes=10)
        # All satisfied — pick the one with highest ratio (most useful to add to)
        assert model == "nvidia/nemotron-3-8b"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_model_registry.py -v`
Expected: FAIL — module doesn't exist.

- [ ] **Step 3: Implement ModelConfig and ModelRegistry**

```python
# subnet/models/__init__.py
# (empty)

# subnet/models/registry.py
"""Model registry — owner-defined model ratios and measurements."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ModelConfig:
    """Single model entry in the registry."""
    name: str
    ratio: float  # 0.0-1.0
    measurement: str  # SHA-384 hex (96 chars)
    target_p95_ms: float = 5000.0  # target latency for scoring

    def __post_init__(self):
        if not 0.0 <= self.ratio <= 1.0:
            raise ValueError(f"ratio must be in [0,1], got {self.ratio}")


class ModelRegistry:
    """Immutable snapshot of the on-chain model configuration."""

    def __init__(self, models: list[ModelConfig]):
        self.models = models
        self.total_ratio = sum(m.ratio for m in models)
        if abs(self.total_ratio - 1.0) > 0.01:
            raise ValueError(
                f"Model ratios must sum to 1.0, got {self.total_ratio}"
            )
        self._by_name = {m.name: m for m in models}

    def measurement_for(self, model_name: str) -> str | None:
        mc = self._by_name.get(model_name)
        return mc.measurement if mc else None

    def target_counts(self, total_nodes: int) -> dict[str, int]:
        """Compute target node count per model from ratios."""
        raw = {m.name: m.ratio * total_nodes for m in self.models}
        # Floor all, then distribute remainder by largest fractional part
        floored = {k: int(v) for k, v in raw.items()}
        remainder = total_nodes - sum(floored.values())
        fractions = sorted(
            raw.keys(),
            key=lambda k: raw[k] - floored[k],
            reverse=True,
        )
        for i in range(remainder):
            floored[fractions[i]] += 1
        return floored

    def highest_deficit_model(
        self, current_counts: dict[str, int], total_nodes: int,
    ) -> str:
        """Return the model with the largest deficit (target - actual)."""
        targets = self.target_counts(total_nodes + 1)  # +1 for the joining node
        deficits = {}
        for m in self.models:
            actual = current_counts.get(m.name, 0)
            deficits[m.name] = targets[m.name] - actual
        max_deficit = max(deficits.values())
        # Tie-break: lexicographic (deterministic)
        candidates = sorted(
            k for k, v in deficits.items() if v == max_deficit
        )
        return candidates[0]
```

- [ ] **Step 4: Run tests**

Run: `python3 -m pytest tests/test_model_registry.py -v && python3 -m pytest tests/ -x -q`
Expected: All PASS.

- [ ] **Step 5: Commit**

```bash
git add subnet/models/ tests/test_model_registry.py
git commit -m "feat: add ModelRegistry for owner-defined model ratios"
```

---

## Phase 2: GPU Attestation

### Task 2.1: GPU attestation verifier

**Files:**
- Create: `subnet/tee/gpu_attestation.py`
- Test: `tests/tee/test_gpu_attestation.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/tee/test_gpu_attestation.py
import pytest
from subnet.tee.gpu_attestation import GpuAttestationResult, verify_gpu_mock


class TestGpuAttestationResult:

    def test_result_ok(self):
        r = GpuAttestationResult(ok=True, gpu_uuid="GPU-abc", gpu_type="H100")
        assert r.ok
        assert r.score == 1.0

    def test_result_fail(self):
        r = GpuAttestationResult(ok=False, reason="no_gpu_device")
        assert not r.ok
        assert r.score == 0.0


class TestMockGpuAttestation:

    def test_mock_always_passes(self):
        result = verify_gpu_mock()
        assert result.ok
        assert result.gpu_type == "MockGPU"

    def test_mock_uuid_is_deterministic(self):
        r1 = verify_gpu_mock()
        r2 = verify_gpu_mock()
        assert r1.gpu_uuid == r2.gpu_uuid
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/tee/test_gpu_attestation.py -v`
Expected: FAIL — module doesn't exist.

- [ ] **Step 3: Implement GPU attestation module**

```python
# subnet/tee/gpu_attestation.py
"""GPU attestation — verify NVIDIA GPU device identity.

Production: uses nv-attestation-sdk to verify H100/H200/B200 device
identity certificates (silicon-fused ECC-384 key).

Development: mock verifier returns a passing result.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class GpuAttestationResult:
    ok: bool
    gpu_uuid: str = ""
    gpu_type: str = ""
    reason: Optional[str] = None

    @property
    def score(self) -> float:
        return 1.0 if self.ok else 0.0


def verify_gpu_mock() -> GpuAttestationResult:
    """Mock GPU attestation — always passes. For development only."""
    return GpuAttestationResult(
        ok=True,
        gpu_uuid="GPU-mock-00000000-0000-0000-0000-000000000000",
        gpu_type="MockGPU",
    )


def verify_gpu_nvidia(gpu_index: int = 0) -> GpuAttestationResult:
    """Verify NVIDIA GPU device identity via nv-attestation-sdk.

    Requires:
    - NVIDIA H100/H200/B200 GPU with confidential computing enabled
    - nv-attestation-sdk installed (pip install nv-attestation-sdk)

    Returns GpuAttestationResult with ok=True if the GPU passes
    device identity verification against NVIDIA's Root CA.
    """
    try:
        from nv_attestation_sdk import attestation  # type: ignore[import-untyped]

        client = attestation.Attestation()
        client.set_name("subnet-gpu-attestation")
        client.set_nonce("subnet-gpu-nonce")  # TODO: epoch-based nonce

        evidence = client.get_evidence()
        if evidence is None:
            return GpuAttestationResult(ok=False, reason="no_gpu_evidence")

        # Verify against NVIDIA Remote Attestation Service (NRAS)
        result = client.verify_evidence(evidence)
        if not result:
            return GpuAttestationResult(ok=False, reason="gpu_verification_failed")

        # Extract GPU info from attestation claims
        claims = client.get_claims()
        gpu_uuid = claims.get("x-nv-gpu-uuid", "unknown")
        gpu_type = claims.get("x-nv-gpu-model", "unknown")

        return GpuAttestationResult(ok=True, gpu_uuid=gpu_uuid, gpu_type=gpu_type)

    except ImportError:
        return GpuAttestationResult(ok=False, reason="nv_attestation_sdk_not_installed")
    except Exception as exc:
        return GpuAttestationResult(ok=False, reason=f"gpu_attestation_error:{exc}")
```

- [ ] **Step 4: Run tests**

Run: `python3 -m pytest tests/tee/test_gpu_attestation.py -v && python3 -m pytest tests/ -x -q`
Expected: All PASS.

- [ ] **Step 5: Commit**

```bash
git add subnet/tee/gpu_attestation.py tests/tee/test_gpu_attestation.py
git commit -m "feat: add GPU attestation module (mock + NVIDIA nv-attestation-sdk)"
```

---

### Task 2.2: Integrate GPU attestation into scoring

**Files:**
- Modify: `subnet/node/scoring.py` — add `gpu_attestation_score` to `PeerScore`
- Create: `examples/gpu-inference/scoring.py` — `GpuInferenceScoring` with GPU attestation
- Test: `tests/test_gpu_scoring.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_gpu_scoring.py
import pytest
from subnet.node.protocol import NodeValidatorResult
from subnet.scoring.gpu_inference import GpuInferenceScoring


class TestGpuInferenceScoring:

    @pytest.fixture
    def scoring(self, tmp_path):
        from subnet.utils.db.database import RocksDB
        db = RocksDB(str(tmp_path / "test_db"))
        return GpuInferenceScoring(db=db, subnet_id=1, config=None)

    @pytest.mark.trio
    async def test_full_score_with_gpu_attestation(self, scoring):
        result = NodeValidatorResult(
            peer_id="peer1", success=True,
            metrics={
                "tee_score": 1.0,
                "gpu_attested": True,
                "prompt_match": True,
                "has_content": True,
                "reasonable_latency": True,
            },
        )
        score = await scoring.score_peer(result, epoch=1)
        assert score.score == 1.0

    @pytest.mark.trio
    async def test_zero_score_without_gpu_attestation(self, scoring):
        result = NodeValidatorResult(
            peer_id="peer1", success=True,
            metrics={
                "tee_score": 1.0,
                "gpu_attested": False,
                "prompt_match": True,
                "has_content": True,
                "reasonable_latency": True,
            },
        )
        score = await scoring.score_peer(result, epoch=1)
        assert score.score == 0.0
        assert "gpu_not_attested" in score.reason
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_gpu_scoring.py -v`
Expected: FAIL.

- [ ] **Step 3: Update GpuInferenceScoring to check gpu_attested**

In `examples/gpu-inference/protocol.py`, update the `GpuInferenceScoring.score_peer()` method to include `gpu_attested` check:

```python
async def score_peer(self, result, epoch):
    if not result.success:
        return PeerScore(peer_id=result.peer_id, score=0.0, reason=result.error or "failed")

    tee_score = result.metrics.get("tee_score", 0.0)
    gpu_attested = result.metrics.get("gpu_attested", False)
    prompt_match = result.metrics.get("prompt_match", False)
    has_content = result.metrics.get("has_content", False)
    reasonable_latency = result.metrics.get("reasonable_latency", False)

    reasons = []
    if not gpu_attested:
        reasons.append("gpu_not_attested")
    if not prompt_match:
        reasons.append("wrong_prompt")
    if not has_content:
        reasons.append("empty_output")
    if not reasonable_latency:
        reasons.append("too_slow")

    if reasons:
        return PeerScore(peer_id=result.peer_id, score=0.0, reason=",".join(reasons))

    return PeerScore(peer_id=result.peer_id, score=tee_score, reason="inference_ok")
```

- [ ] **Step 4: Run tests**

Run: `python3 -m pytest tests/test_gpu_scoring.py -v && python3 -m pytest tests/ -x -q`
Expected: All PASS.

- [ ] **Step 5: Commit**

```bash
git add examples/gpu-inference/protocol.py tests/test_gpu_scoring.py
git commit -m "feat: integrate GPU attestation into inference scoring"
```

---

## Phase 3: Frontier Router

### Task 3.1: Capacity table

**Files:**
- Create: `subnet/frontier/capacity.py`
- Create: `subnet/frontier/__init__.py`
- Test: `tests/frontier/test_capacity.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/frontier/test_capacity.py
import time
import pytest
from subnet.frontier.capacity import CapacityTable


class TestCapacityTable:

    def test_update_and_lookup(self):
        ct = CapacityTable(staleness_threshold=6.0)
        ct.update("peer-a", model="nvidia/nemotron-3-49b", load=0.3, latency_p95=890)
        nodes = ct.nodes_for_model("nvidia/nemotron-3-49b")
        assert len(nodes) == 1
        assert nodes[0].peer_id == "peer-a"
        assert nodes[0].load == 0.3

    def test_least_loaded_routing(self):
        ct = CapacityTable()
        ct.update("peer-a", model="m1", load=0.7, latency_p95=100)
        ct.update("peer-b", model="m1", load=0.3, latency_p95=100)
        ct.update("peer-c", model="m1", load=0.5, latency_p95=100)
        best = ct.pick_node("m1")
        assert best.peer_id == "peer-b"  # lowest load

    def test_pick_node_unknown_model_returns_none(self):
        ct = CapacityTable()
        assert ct.pick_node("unknown") is None

    def test_stale_node_removed(self):
        ct = CapacityTable(staleness_threshold=0.1)
        ct.update("peer-a", model="m1", load=0.3, latency_p95=100)
        time.sleep(0.15)
        ct.evict_stale()
        assert ct.pick_node("m1") is None

    def test_remove_node(self):
        ct = CapacityTable()
        ct.update("peer-a", model="m1", load=0.3, latency_p95=100)
        ct.remove("peer-a")
        assert ct.pick_node("m1") is None

    def test_multiple_models(self):
        ct = CapacityTable()
        ct.update("peer-a", model="m1", load=0.3, latency_p95=100)
        ct.update("peer-b", model="m2", load=0.5, latency_p95=200)
        assert ct.pick_node("m1").peer_id == "peer-a"
        assert ct.pick_node("m2").peer_id == "peer-b"

    def test_all_models(self):
        ct = CapacityTable()
        ct.update("peer-a", model="m1", load=0.3, latency_p95=100)
        ct.update("peer-b", model="m2", load=0.5, latency_p95=200)
        assert set(ct.all_models()) == {"m1", "m2"}

    def test_overloaded_check(self):
        ct = CapacityTable()
        ct.update("peer-a", model="m1", load=0.95, latency_p95=100)
        ct.update("peer-b", model="m1", load=0.92, latency_p95=100)
        assert ct.is_overloaded("m1", threshold=0.9)
        assert not ct.is_overloaded("m1", threshold=0.99)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/frontier/test_capacity.py -v`
Expected: FAIL — module doesn't exist.

- [ ] **Step 3: Implement CapacityTable**

```python
# subnet/frontier/__init__.py
# (empty)

# subnet/frontier/capacity.py
"""In-memory capacity table — tracks node load for least-loaded routing."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from threading import Lock


@dataclass
class NodeEntry:
    peer_id: str
    model: str
    load: float  # 0.0-1.0
    latency_p95: float  # ms
    last_seen: float = field(default_factory=time.monotonic)


class CapacityTable:
    """Thread-safe capacity table built from heartbeats."""

    def __init__(self, staleness_threshold: float = 6.0):
        self._nodes: dict[str, NodeEntry] = {}
        self._lock = Lock()
        self._staleness = staleness_threshold

    def update(self, peer_id: str, *, model: str, load: float, latency_p95: float) -> None:
        with self._lock:
            self._nodes[peer_id] = NodeEntry(
                peer_id=peer_id, model=model,
                load=load, latency_p95=latency_p95,
                last_seen=time.monotonic(),
            )

    def remove(self, peer_id: str) -> None:
        with self._lock:
            self._nodes.pop(peer_id, None)

    def evict_stale(self) -> list[str]:
        now = time.monotonic()
        evicted = []
        with self._lock:
            for pid, entry in list(self._nodes.items()):
                if now - entry.last_seen > self._staleness:
                    del self._nodes[pid]
                    evicted.append(pid)
        return evicted

    def nodes_for_model(self, model: str) -> list[NodeEntry]:
        with self._lock:
            return [e for e in self._nodes.values() if e.model == model]

    def pick_node(self, model: str) -> NodeEntry | None:
        nodes = self.nodes_for_model(model)
        if not nodes:
            return None
        return min(nodes, key=lambda n: n.load)

    def all_models(self) -> set[str]:
        with self._lock:
            return {e.model for e in self._nodes.values()}

    def is_overloaded(self, model: str, threshold: float = 0.9) -> bool:
        nodes = self.nodes_for_model(model)
        return bool(nodes) and all(n.load >= threshold for n in nodes)
```

- [ ] **Step 4: Run tests**

Run: `python3 -m pytest tests/frontier/test_capacity.py -v && python3 -m pytest tests/ -x -q`
Expected: All PASS.

- [ ] **Step 5: Commit**

```bash
git add subnet/frontier/ tests/frontier/
git commit -m "feat: add CapacityTable for frontier routing"
```

---

### Task 3.2: Frontier FastAPI application

**Files:**
- Create: `subnet/frontier/app.py`
- Test: `tests/frontier/test_app.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/frontier/test_app.py
import pytest
from unittest.mock import AsyncMock, patch
from fastapi.testclient import TestClient
from subnet.frontier.app import create_app
from subnet.frontier.capacity import CapacityTable


class TestFrontierApp:

    @pytest.fixture
    def capacity(self):
        ct = CapacityTable()
        ct.update("peer-a", model="nvidia/nemotron-3-49b", load=0.3, latency_p95=890)
        ct.update("peer-b", model="nvidia/nemotron-3-49b", load=0.7, latency_p95=920)
        return ct

    @pytest.fixture
    def client(self, capacity):
        app = create_app(capacity_table=capacity, api_keys={"test-key"})
        return TestClient(app)

    def test_health(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    def test_models_list(self, client):
        resp = client.get("/v1/models", headers={"Authorization": "Bearer test-key"})
        assert resp.status_code == 200
        models = resp.json()["data"]
        assert any(m["id"] == "nvidia/nemotron-3-49b" for m in models)

    def test_chat_completions_no_auth(self, client):
        resp = client.post("/v1/chat/completions", json={
            "model": "nvidia/nemotron-3-49b",
            "messages": [{"role": "user", "content": "hello"}],
        })
        assert resp.status_code == 401

    def test_chat_completions_unknown_model(self, client):
        resp = client.post(
            "/v1/chat/completions",
            json={"model": "unknown", "messages": [{"role": "user", "content": "hi"}]},
            headers={"Authorization": "Bearer test-key"},
        )
        assert resp.status_code == 503

    def test_chat_completions_overloaded(self, client, capacity):
        capacity.update("peer-a", model="nvidia/nemotron-3-49b", load=0.95, latency_p95=890)
        capacity.update("peer-b", model="nvidia/nemotron-3-49b", load=0.95, latency_p95=920)
        resp = client.post(
            "/v1/chat/completions",
            json={"model": "nvidia/nemotron-3-49b", "messages": [{"role": "user", "content": "hi"}]},
            headers={"Authorization": "Bearer test-key"},
        )
        assert resp.status_code == 429
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/frontier/test_app.py -v`
Expected: FAIL — module doesn't exist.

- [ ] **Step 3: Implement FastAPI frontier app**

```python
# subnet/frontier/app.py
"""Frontier — OpenAI-compatible API gateway for TEE inference cluster."""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, HTTPException, Header, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from subnet.frontier.capacity import CapacityTable

logger = logging.getLogger("frontier")


class ChatCompletionRequest(BaseModel):
    model: str
    messages: list[dict[str, Any]]
    max_tokens: int = 256
    temperature: float = 0.7
    stream: bool = False


def create_app(
    capacity_table: CapacityTable,
    api_keys: set[str] | None = None,
) -> FastAPI:
    app = FastAPI(title="TEE Inference Frontier")

    def _check_auth(authorization: str | None):
        if api_keys is None:
            return
        if not authorization or not authorization.startswith("Bearer "):
            raise HTTPException(status_code=401, detail="Missing API key")
        key = authorization.removeprefix("Bearer ").strip()
        if key not in api_keys:
            raise HTTPException(status_code=401, detail="Invalid API key")

    @app.get("/health")
    async def health():
        return {"status": "ok", "models": list(capacity_table.all_models())}

    @app.get("/v1/models")
    async def list_models(authorization: str | None = Header(None)):
        _check_auth(authorization)
        models = capacity_table.all_models()
        return {
            "object": "list",
            "data": [
                {"id": m, "object": "model", "owned_by": "tee-subnet"}
                for m in sorted(models)
            ],
        }

    @app.post("/v1/chat/completions")
    async def chat_completions(
        req: ChatCompletionRequest,
        authorization: str | None = Header(None),
    ):
        _check_auth(authorization)

        # Check overload
        if capacity_table.is_overloaded(req.model):
            return JSONResponse(
                status_code=429,
                content={"error": "capacity_exceeded", "retry_after": 5},
            )

        # Pick least-loaded node
        node = capacity_table.pick_node(req.model)
        if node is None:
            return JSONResponse(
                status_code=503,
                content={"error": "model_unavailable", "model": req.model},
            )

        # TODO: Forward request to node via RA-TLS connection pool
        # For now, return the selected node info (placeholder)
        logger.info(
            "[Frontier] routing model=%s → peer=%s load=%.0f%%",
            req.model, node.peer_id[:16], node.load * 100,
        )

        return JSONResponse(
            status_code=501,
            content={
                "error": "not_implemented",
                "detail": "RA-TLS forwarding not yet implemented",
                "selected_node": node.peer_id,
            },
        )

    return app
```

- [ ] **Step 4: Run tests**

Run: `python3 -m pytest tests/frontier/test_app.py -v && python3 -m pytest tests/ -x -q`
Expected: All PASS.

- [ ] **Step 5: Commit**

```bash
git add subnet/frontier/app.py tests/frontier/test_app.py
git commit -m "feat: add Frontier FastAPI app with OpenAI-compatible endpoints"
```

---

### Task 3.3: Frontier CLI entry point

**Files:**
- Create: `subnet/frontier/cli.py`
- Modify: `pyproject.toml` — add `run_frontier` entry point

- [ ] **Step 1: Create frontier CLI**

```python
# subnet/frontier/cli.py
"""CLI entry point for the frontier router."""

import argparse
import logging
import os

import uvicorn

from subnet.frontier.app import create_app
from subnet.frontier.capacity import CapacityTable


def main():
    parser = argparse.ArgumentParser(description="TEE Inference Frontier")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--host", type=str, default="0.0.0.0")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO)

    api_keys_str = os.getenv("FRONTIER_API_KEYS", "")
    api_keys = set(k.strip() for k in api_keys_str.split(",") if k.strip()) or None

    capacity_table = CapacityTable(
        staleness_threshold=float(os.getenv("FRONTIER_STALENESS_S", "6.0")),
    )

    app = create_app(capacity_table=capacity_table, api_keys=api_keys)

    # TODO: Start GossipSub heartbeat listener in background
    # to populate capacity_table from mesh heartbeats

    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Add entry point to pyproject.toml**

Add to `[project.scripts]`:
```toml
run_frontier = "subnet.frontier.cli:main"
```

- [ ] **Step 3: Verify import works**

Run: `python3 -c "from subnet.frontier.cli import main; print('OK')"`
Expected: OK

- [ ] **Step 4: Commit**

```bash
git add subnet/frontier/cli.py pyproject.toml
git commit -m "feat: add frontier CLI entry point"
```

---

## Phase 4: Kata Integration

### Task 4.1: Kata container configuration

**Files:**
- Create: `kata/policy.rego`
- Create: `kata/kata-config.toml`
- Create: `kata/README.md`

This phase is infrastructure/config, not Python code. No TDD — just configuration files.

- [ ] **Step 1: Create OPA policy that blocks exec/attach**

```rego
# kata/policy.rego
# OPA policy for Kata Containers — blocks runtime tampering
#
# With default allow = false, only explicitly allowed actions pass.
# ExecProcessRequest and SignalProcessRequest are NOT in the allow
# list, so they are implicitly denied.
package kata

default allow = false

# Allow container lifecycle operations only
allow {
    input.action == "CreateContainerRequest"
}
allow {
    input.action == "StartContainerRequest"
}
allow {
    input.action == "StopContainerRequest"
}
allow {
    input.action == "RemoveContainerRequest"
}

# ExecProcessRequest — NOT allowed (no rule → denied by default)
# SignalProcessRequest — NOT allowed (no rule → denied by default)
```

- [ ] **Step 2: Create Kata runtime config snippet**

```toml
# kata/kata-config.toml
# Kata Containers runtime configuration for TEE inference nodes
# Merge with /etc/kata-containers/configuration.toml

[hypervisor.qemu]
confidential_guest = true
firmware = "/opt/kata/share/kata-containers/kata-containers.img"

[agent.kata]
policy_file = "/etc/kata-containers/policy.rego"
enable_dm_verity = true
```

- [ ] **Step 3: Create Kata README**

Document: prerequisites (Kata installed, CVM host), how to apply policy, how to verify dm-verity is active, how to test that exec is blocked.

- [ ] **Step 4: Commit**

```bash
git add kata/
git commit -m "feat: add Kata container config with OPA policy (blocks exec)"
```

---

## Phase 5: Node Lifecycle

### Task 5.1: Model self-assignment

**Files:**
- Create: `subnet/models/assignment.py`
- Test: `tests/test_model_assignment.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_model_assignment.py
import pytest
from subnet.models.registry import ModelConfig, ModelRegistry
from subnet.models.assignment import compute_assignment


class TestModelAssignment:

    @pytest.fixture
    def registry(self):
        return ModelRegistry(models=[
            ModelConfig(name="nvidia/nemotron-3-8b", ratio=0.5, measurement="aa" * 48),
            ModelConfig(name="nvidia/nemotron-3-49b", ratio=0.3, measurement="bb" * 48),
            ModelConfig(name="meta/llama-3.1-70b", ratio=0.2, measurement="cc" * 48),
        ])

    def test_first_node_gets_highest_ratio(self, registry):
        current = {}
        model = compute_assignment(registry, current_counts=current, total_nodes=0)
        assert model == "nvidia/nemotron-3-8b"

    def test_second_node_still_highest_ratio(self, registry):
        current = {"nvidia/nemotron-3-8b": 1}
        model = compute_assignment(registry, current_counts=current, total_nodes=1)
        # target for 2 nodes: 8b=1, 49b=1, 70b=0 → 49b has deficit
        assert model == "nvidia/nemotron-3-49b"

    def test_ten_nodes_balanced(self, registry):
        current = {
            "nvidia/nemotron-3-8b": 5,
            "nvidia/nemotron-3-49b": 3,
            "meta/llama-3.1-70b": 2,
        }
        # All at target — adding 11th node should go to highest ratio
        model = compute_assignment(registry, current_counts=current, total_nodes=10)
        # target for 11: 8b=5.5→6, 49b=3.3→3, 70b=2.2→2 → 8b has deficit
        assert model == "nvidia/nemotron-3-8b"

    def test_deterministic_across_calls(self, registry):
        current = {"nvidia/nemotron-3-8b": 2, "nvidia/nemotron-3-49b": 1}
        m1 = compute_assignment(registry, current_counts=current, total_nodes=3)
        m2 = compute_assignment(registry, current_counts=current, total_nodes=3)
        assert m1 == m2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_model_assignment.py -v`
Expected: FAIL — module doesn't exist.

- [ ] **Step 3: Implement compute_assignment**

```python
# subnet/models/assignment.py
"""Model self-assignment — nodes compute their own model from on-chain ratios."""

from __future__ import annotations

from subnet.models.registry import ModelRegistry


def compute_assignment(
    registry: ModelRegistry,
    current_counts: dict[str, int],
    total_nodes: int,
) -> str:
    """Compute which model this joining node should run.

    Deterministic: given the same registry and current_counts,
    always returns the same model. No randomness, no coordination.
    """
    return registry.highest_deficit_model(current_counts, total_nodes)
```

- [ ] **Step 4: Run tests**

Run: `python3 -m pytest tests/test_model_assignment.py -v && python3 -m pytest tests/ -x -q`
Expected: All PASS.

- [ ] **Step 5: Commit**

```bash
git add subnet/models/assignment.py tests/test_model_assignment.py
git commit -m "feat: add model self-assignment from on-chain ratios"
```

---

### Task 5.2: Node join/leave GossipSub messages

**Files:**
- Create: `subnet/frontier/messages.py`
- Test: `tests/frontier/test_messages.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/frontier/test_messages.py
import json
import pytest
from subnet.frontier.messages import NodeJoinMessage, NodeLeaveMessage


class TestNodeMessages:

    def test_join_roundtrip(self):
        msg = NodeJoinMessage(
            peer_id="12D3KooW...",
            gpu_type="H100",
            gpu_uuid="GPU-abc",
            assigned_model="nvidia/nemotron-3-49b",
        )
        restored = NodeJoinMessage.from_bytes(msg.to_bytes())
        assert restored.peer_id == "12D3KooW..."
        assert restored.assigned_model == "nvidia/nemotron-3-49b"

    def test_leave_roundtrip(self):
        msg = NodeLeaveMessage(peer_id="12D3KooW...", reason="graceful")
        restored = NodeLeaveMessage.from_bytes(msg.to_bytes())
        assert restored.peer_id == "12D3KooW..."
        assert restored.reason == "graceful"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/frontier/test_messages.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement messages**

```python
# subnet/frontier/messages.py
"""GossipSub messages for node lifecycle events."""

from __future__ import annotations

import json
from dataclasses import dataclass


@dataclass
class NodeJoinMessage:
    peer_id: str
    gpu_type: str
    gpu_uuid: str
    assigned_model: str

    def to_bytes(self) -> bytes:
        return json.dumps({
            "type": "node_join",
            "peer_id": self.peer_id,
            "gpu_type": self.gpu_type,
            "gpu_uuid": self.gpu_uuid,
            "assigned_model": self.assigned_model,
        }).encode()

    @classmethod
    def from_bytes(cls, data: bytes) -> NodeJoinMessage:
        d = json.loads(data)
        return cls(
            peer_id=d["peer_id"],
            gpu_type=d["gpu_type"],
            gpu_uuid=d["gpu_uuid"],
            assigned_model=d["assigned_model"],
        )


@dataclass
class NodeLeaveMessage:
    peer_id: str
    reason: str = "graceful"

    def to_bytes(self) -> bytes:
        return json.dumps({
            "type": "node_leave",
            "peer_id": self.peer_id,
            "reason": self.reason,
        }).encode()

    @classmethod
    def from_bytes(cls, data: bytes) -> NodeLeaveMessage:
        d = json.loads(data)
        return cls(peer_id=d["peer_id"], reason=d.get("reason", "graceful"))
```

- [ ] **Step 4: Run tests**

Run: `python3 -m pytest tests/frontier/test_messages.py -v && python3 -m pytest tests/ -x -q`
Expected: All PASS.

- [ ] **Step 5: Commit**

```bash
git add subnet/frontier/messages.py tests/frontier/test_messages.py
git commit -m "feat: add node join/leave GossipSub messages"
```

---

## Summary

| Phase | Tasks | New files | Test files |
|-------|-------|-----------|------------|
| 1: Heartbeat + Registry | 1.1, 1.2 | `heartbeat.py` (mod), `models/registry.py` | `test_heartbeat_v2.py`, `test_model_registry.py` |
| 2: GPU Attestation | 2.1, 2.2 | `tee/gpu_attestation.py` | `test_gpu_attestation.py`, `test_gpu_scoring.py` |
| 3: Frontier | 3.1, 3.2, 3.3 | `frontier/capacity.py`, `frontier/app.py`, `frontier/cli.py` | `test_capacity.py`, `test_app.py` |
| 4: Kata | 4.1 | `kata/policy.rego`, `kata/kata-config.toml` | (config, no unit tests) |
| 5: Lifecycle | 5.1, 5.2 | `models/assignment.py`, `frontier/messages.py` | `test_model_assignment.py`, `test_messages.py` |

**Total: 9 tasks, 10 new files, 8 test files.**

Each phase is independently testable and committable. Phase 3 depends on Phase 1 (heartbeat data feeds capacity table). Phase 5 depends on Phase 2 (GPU attestation for join flow). All other phases are independent.

**Note on `tests/frontier/__init__.py`:** Create empty `__init__.py` files in `tests/frontier/` and `subnet/models/` when creating the first file in those directories. Existing test subdirectories follow this pattern.

**Note on GpuInferenceScoring location:** The scoring class should live at `subnet/scoring/gpu_inference.py` (inside the `subnet` package), not in `examples/`. Create `subnet/scoring/__init__.py` as well.

---

## Deferred tasks (not in this plan, tracked for next iteration)

These components are specified in the design but require the foundation from Phases 1-5 before implementation:

| Task | Spec reference | Why deferred |
|------|---------------|-------------|
| **RA-TLS forwarding** (frontier → node) | Spec §5, §6 | Requires connection pool management, RA-TLS session reuse. Existing `subnet/tee/ratls/` provides primitives. |
| **SSE streaming pass-through** | Spec §5 "Streaming" | Requires RA-TLS forwarding to work first. FastAPI + httpx both support SSE. |
| **X-TEE-Proof header** | Spec §5 "Proof header" | Requires OutputEnvelope from RA-TLS response. Format: `{attestation_quote, output_signature, gpu_device_cert}`. |
| **Full scoring formula** (uptime + latency_factor) | Spec §4 "Scoring" | `uptime = heartbeats_received / expected`. `latency_factor = min(1.0, target_p95 / actual_p95)`. Requires heartbeat v2 data. |
| **DHT model_assignment publish** | Spec §4 "How it works" step 3 | Node publishes `model_assignment:{peer_id} → model_name` to DHT after self-assignment. |
| **On-chain ratio polling** | Spec §4 "Rebalancing" | Nodes poll chain for ratio changes, re-run self-assignment. Uses existing epoch polling pattern. |
| **Per-model measurement verification** | Spec §4 "Model verification" | Extend `DcapVerifier` to accept a `ModelRegistry` and check measurement against the assigned model's expected value. |
| **Connection pool management** | Spec §5 "Connection pooling" | Maintain persistent RA-TLS connections, re-establish on epoch boundary or heartbeat failure. |
