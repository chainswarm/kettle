"""Tests for HeartbeatData v2 fields (GPU/model metrics)."""

import json

import pytest

from subnet.utils.pubsub.heartbeat import HeartbeatData


def test_heartbeat_includes_version():
    """Default version should be 1."""
    hb = HeartbeatData(epoch=1, subnet_id=1, subnet_node_id=1)
    assert hb.version == 1


def test_heartbeat_includes_models():
    """models field should accept a list of model strings."""
    hb = HeartbeatData(
        epoch=1,
        subnet_id=1,
        subnet_node_id=1,
        models=["nvidia/nemotron-3-49b"],
    )
    assert hb.models == ["nvidia/nemotron-3-49b"]


def test_heartbeat_includes_gpu_metrics():
    """GPU, VRAM, and requests_in_flight fields should be stored correctly."""
    hb = HeartbeatData(
        epoch=1,
        subnet_id=1,
        subnet_node_id=1,
        gpu="NVIDIA H100 80GB HBM3",
        gpu_uuid="GPU-abc123",
        gpu_attested=True,
        vram_total_gb=80,
        vram_used_gb=40,
        requests_in_flight=5,
        latency_p95_ms=12.5,
    )
    assert hb.gpu == "NVIDIA H100 80GB HBM3"
    assert hb.gpu_uuid == "GPU-abc123"
    assert hb.gpu_attested is True
    assert hb.vram_total_gb == 80
    assert hb.vram_used_gb == 40
    assert hb.requests_in_flight == 5
    assert hb.latency_p95_ms == 12.5


def test_heartbeat_v2_serialization_roundtrip():
    """All new v2 fields must survive a to_json / from_json roundtrip."""
    original = HeartbeatData(
        epoch=42,
        subnet_id=1,
        subnet_node_id=7,
        version=2,
        peer_id="12D3KooWABCDEF",
        models=["nvidia/nemotron-3-49b", "meta/llama-3-8b"],
        gpu="NVIDIA A100 80GB PCIe",
        gpu_uuid="GPU-deadbeef",
        gpu_attested=True,
        tee_score=0.98,
        vram_total_gb=80,
        vram_used_gb=60,
        requests_in_flight=3,
        latency_p95_ms=8.3,
        nim_version="1.2.3",
    )

    restored = HeartbeatData.from_json(original.to_json())

    assert restored.epoch == 42
    assert restored.subnet_id == 1
    assert restored.subnet_node_id == 7
    assert restored.version == 2
    assert restored.peer_id == "12D3KooWABCDEF"
    assert restored.models == ["nvidia/nemotron-3-49b", "meta/llama-3-8b"]
    assert restored.gpu == "NVIDIA A100 80GB PCIe"
    assert restored.gpu_uuid == "GPU-deadbeef"
    assert restored.gpu_attested is True
    assert restored.tee_score == pytest.approx(0.98)
    assert restored.vram_total_gb == 80
    assert restored.vram_used_gb == 60
    assert restored.requests_in_flight == 3
    assert restored.latency_p95_ms == pytest.approx(8.3)
    assert restored.nim_version == "1.2.3"


def test_heartbeat_backward_compat_no_new_fields():
    """Old heartbeats that lack v2 fields must still deserialize successfully."""
    old_payload = json.dumps({"epoch": 5, "subnet_id": 1, "subnet_node_id": 2})

    hb = HeartbeatData.from_json(old_payload)

    assert hb.epoch == 5
    assert hb.subnet_id == 1
    assert hb.subnet_node_id == 2
    # New fields should carry their defaults
    assert hb.version == 1
    assert hb.peer_id is None
    assert hb.models is None
    assert hb.gpu is None
    assert hb.gpu_uuid is None
    assert hb.gpu_attested is False
    assert hb.tee_score == 0.0
    assert hb.vram_total_gb is None
    assert hb.vram_used_gb is None
    assert hb.requests_in_flight == 0
    assert hb.latency_p95_ms == 0.0
    assert hb.nim_version is None
