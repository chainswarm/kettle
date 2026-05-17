"""
Scoring Pipeline Integration Tests — TEE inference cluster.

Tests the full scoring pipeline: TEE verification + GPU attestation +
inference quality checks → final score.

Coverage:
  - Perfect score: real hardware TEE (tee_score=1.0) + all checks pass
  - Mock TEE: reduced score (tee_score=0.5) + all checks pass
  - No GPU attestation: zero score, reason="gpu_not_attested"
  - Empty output: zero score, reason="empty_output"
  - Too slow: zero score, reason="too_slow"
  - Multiple failures: all failure reasons present in combined reason string
  - Failed result: success=False propagates error as reason
  - Batch scoring (score_all): correct scores for a mixed peer set
  - TEE score zero boundary: tee_score=0.0 with all other checks True → 0.0
"""

from __future__ import annotations

import pytest

from subnet.node.protocol import NodeValidatorResult
from subnet.scoring.gpu_inference import GpuInferenceScoring
from subnet.utils.db.database import RocksDB

PEER_A = "12D3KooWKxAhu5U8SreDZpokVkN6ciTBbsHxteo3Vmq6Cpuf8KEt"
PEER_B = "12D3KooWBPVJe1hUHC9JrZGXNBPVS2sJqJx4jqZm3CuFsmRKt7Np"
PEER_C = "12D3KooWQmH1ynXG7W8qhFcPvN6JroUePHC5EkzAqBH7NQZbPjSr"

EPOCH = 100_000


# ── helpers ───────────────────────────────────────────────────────────────────

def _passing_metrics(tee_score: float = 1.0) -> dict:
    """Return a metrics dict with all quality-gate flags True."""
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
    db = RocksDB(str(tmp_path / "scoring_db"))
    return GpuInferenceScoring(db=db, subnet_id=1, config=None)


# ── tests ─────────────────────────────────────────────────────────────────────

@pytest.mark.trio
async def test_perfect_score_real_hardware(scoring):
    """tee_score=1.0 + gpu_attested + all quality checks → score=1.0, reason='inference_ok'."""
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
async def test_mock_tee_reduced_score(scoring):
    """tee_score=0.5 (mock TEE) + all checks pass → score=0.5, reason='inference_ok'."""
    result = NodeValidatorResult(
        peer_id=PEER_A,
        success=True,
        metrics=_passing_metrics(tee_score=0.5),
    )
    ps = await scoring.score_peer(result, EPOCH)

    assert ps.peer_id == PEER_A
    assert ps.score == 0.5
    assert ps.reason == "inference_ok"


@pytest.mark.trio
async def test_no_gpu_attestation_zero_score(scoring):
    """gpu_attested=False → score=0.0, reason contains 'gpu_not_attested'."""
    metrics = _passing_metrics(tee_score=1.0)
    metrics["gpu_attested"] = False
    result = NodeValidatorResult(peer_id=PEER_A, success=True, metrics=metrics)

    ps = await scoring.score_peer(result, EPOCH)

    assert ps.score == 0.0
    assert "gpu_not_attested" in ps.reason


@pytest.mark.trio
async def test_empty_output_zero_score(scoring):
    """has_content=False → score=0.0, reason contains 'empty_output'."""
    metrics = _passing_metrics(tee_score=1.0)
    metrics["has_content"] = False
    result = NodeValidatorResult(peer_id=PEER_A, success=True, metrics=metrics)

    ps = await scoring.score_peer(result, EPOCH)

    assert ps.score == 0.0
    assert "empty_output" in ps.reason


@pytest.mark.trio
async def test_too_slow_zero_score(scoring):
    """reasonable_latency=False → score=0.0, reason contains 'too_slow'."""
    metrics = _passing_metrics(tee_score=1.0)
    metrics["reasonable_latency"] = False
    result = NodeValidatorResult(peer_id=PEER_A, success=True, metrics=metrics)

    ps = await scoring.score_peer(result, EPOCH)

    assert ps.score == 0.0
    assert "too_slow" in ps.reason


@pytest.mark.trio
async def test_multiple_failures_all_reasons_listed(scoring):
    """gpu_attested=False + has_content=False + reasonable_latency=False → all three reasons in combined string."""
    metrics = _passing_metrics(tee_score=1.0)
    metrics["gpu_attested"] = False
    metrics["has_content"] = False
    metrics["reasonable_latency"] = False
    result = NodeValidatorResult(peer_id=PEER_A, success=True, metrics=metrics)

    ps = await scoring.score_peer(result, EPOCH)

    assert ps.score == 0.0
    assert "gpu_not_attested" in ps.reason
    assert "empty_output" in ps.reason
    assert "too_slow" in ps.reason


@pytest.mark.trio
async def test_failed_result_propagates_error(scoring):
    """success=False with error='timeout' → score=0.0, reason='timeout'."""
    result = NodeValidatorResult(
        peer_id=PEER_A,
        success=False,
        error="timeout",
        metrics=_passing_metrics(tee_score=1.0),
    )
    ps = await scoring.score_peer(result, EPOCH)

    assert ps.score == 0.0
    assert ps.reason == "timeout"


@pytest.mark.trio
async def test_batch_scoring_score_all(scoring):
    """score_all with three mixed peers returns correct scores {1.0, 0.5, 0.0}."""
    results = [
        # Perfect peer — real hardware
        NodeValidatorResult(
            peer_id=PEER_A,
            success=True,
            metrics=_passing_metrics(tee_score=1.0),
        ),
        # Mock TEE peer
        NodeValidatorResult(
            peer_id=PEER_B,
            success=True,
            metrics=_passing_metrics(tee_score=0.5),
        ),
        # Failed peer
        NodeValidatorResult(
            peer_id=PEER_C,
            success=False,
            error="connection_refused",
            metrics={},
        ),
    ]

    scores = await scoring.score_all(results, EPOCH)

    assert set(scores.keys()) == {PEER_A, PEER_B, PEER_C}
    assert scores[PEER_A].score == 1.0
    assert scores[PEER_B].score == 0.5
    assert scores[PEER_C].score == 0.0

    # Confirm the full set of distinct score values
    score_values = {ps.score for ps in scores.values()}
    assert score_values == {1.0, 0.5, 0.0}


@pytest.mark.trio
async def test_tee_score_zero_blocks_everything(scoring):
    """tee_score=0.0 with all other checks True → score=0.0 (tee_score passed through as-is when checks all pass)."""
    result = NodeValidatorResult(
        peer_id=PEER_A,
        success=True,
        metrics=_passing_metrics(tee_score=0.0),
    )
    ps = await scoring.score_peer(result, EPOCH)

    # All quality gates pass, but tee_score itself is 0.0
    assert ps.score == 0.0
    # Reason is still "inference_ok" — the gate passed, the score is just 0.0
    assert ps.reason == "inference_ok"
