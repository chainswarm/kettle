"""
Tests for GpuInferenceScoring.

All tests are async (trio) and use a tmp_path-backed RocksDB fixture.
"""

from __future__ import annotations

import pytest

from subnet.node.protocol import NodeValidatorResult
from subnet.scoring.gpu_inference import GpuInferenceScoring

PEER_A = "12D3KooWKxAhu5U8SreDZpokVkN6ciTBbsHxteo3Vmq6Cpuf8KEt"
EPOCH = 42_000


# ── helpers ───────────────────────────────────────────────────────────────────

def _passing_metrics(tee_score: float = 1.0) -> dict:
    """All quality-gate flags True; tee_score configurable."""
    return {
        "tee_score": tee_score,
        "gpu_attested": True,
        "prompt_match": True,
        "has_content": True,
        "reasonable_latency": True,
    }


# ── fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def scoring(tmp_path):
    from subnet.utils.db.database import RocksDB
    db = RocksDB(str(tmp_path / "test_db"))
    return GpuInferenceScoring(db=db, subnet_id=1, config=None)


# ── tests ─────────────────────────────────────────────────────────────────────

@pytest.mark.trio
async def test_full_score_with_gpu_attestation(scoring):
    """All checks pass + tee_score=1.0 → score=1.0, reason='inference_ok'."""
    result = NodeValidatorResult(
        peer_id=PEER_A,
        success=True,
        metrics=_passing_metrics(tee_score=1.0),
    )
    ps = await scoring.score_peer(result, EPOCH)

    assert ps.peer_id == PEER_A
    assert ps.score == 1.0
    assert ps.reason == "inference_ok"


@pytest.mark.trio
async def test_zero_score_without_gpu_attestation(scoring):
    """gpu_attested=False → score=0.0, reason contains 'gpu_not_attested'."""
    metrics = _passing_metrics()
    metrics["gpu_attested"] = False
    result = NodeValidatorResult(peer_id=PEER_A, success=True, metrics=metrics)

    ps = await scoring.score_peer(result, EPOCH)

    assert ps.score == 0.0
    assert "gpu_not_attested" in ps.reason


@pytest.mark.trio
async def test_zero_score_failed_result(scoring):
    """success=False → score=0.0 regardless of metrics."""
    result = NodeValidatorResult(
        peer_id=PEER_A,
        success=False,
        error="connection_refused",
        metrics=_passing_metrics(),
    )
    ps = await scoring.score_peer(result, EPOCH)

    assert ps.score == 0.0
    assert ps.reason == "connection_refused"


@pytest.mark.trio
async def test_mock_tee_score(scoring):
    """tee_score=0.5, all checks pass → score=0.5."""
    result = NodeValidatorResult(
        peer_id=PEER_A,
        success=True,
        metrics=_passing_metrics(tee_score=0.5),
    )
    ps = await scoring.score_peer(result, EPOCH)

    assert ps.score == 0.5
    assert ps.reason == "inference_ok"


@pytest.mark.trio
async def test_multiple_failures(scoring):
    """gpu_attested=False + has_content=False → reason contains both failures."""
    metrics = _passing_metrics()
    metrics["gpu_attested"] = False
    metrics["has_content"] = False
    result = NodeValidatorResult(peer_id=PEER_A, success=True, metrics=metrics)

    ps = await scoring.score_peer(result, EPOCH)

    assert ps.score == 0.0
    assert "gpu_not_attested" in ps.reason
    assert "empty_output" in ps.reason
