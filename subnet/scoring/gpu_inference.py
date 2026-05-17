"""
GpuInferenceScoring — scoring for TEE inference cluster nodes.

Scores a peer only when ALL of the following are satisfied:
  1. The validator call succeeded (result.success=True)
  2. GPU attestation passed (metrics["gpu_attested"]=True)
  3. The prompt was matched (metrics["prompt_match"]=True)
  4. The output is non-empty (metrics["has_content"]=True)
  5. Latency is within bounds (metrics["reasonable_latency"]=True)

The final score is the TEE score from metrics["tee_score"] (float in [0,1]).
Any failing check produces score=0.0 with a comma-separated reason string.
"""

from __future__ import annotations

import logging
from typing import List

from subnet.node.protocol import NodeValidatorResult
from subnet.node.scoring import BaseNodeScoring, PeerScore

logger = logging.getLogger(__name__)


class GpuInferenceScoring(BaseNodeScoring):
    """
    Scoring class for TEE inference cluster nodes.

    Requires both TEE attestation and GPU attestation to grant a non-zero
    score.  All quality gates (prompt_match, has_content, reasonable_latency)
    must also pass before the tee_score is returned as the final score.

    Expected metrics keys in NodeValidatorResult.metrics:
      tee_score         : float — TEE attestation score (0.0–1.0)
      gpu_attested      : bool  — True if GPU attestation passed
      prompt_match      : bool  — True if the response matched the sent prompt
      has_content       : bool  — True if the response body is non-empty
      reasonable_latency: bool  — True if response time is within threshold
    """

    async def score_peer(
        self, result: NodeValidatorResult, epoch: int
    ) -> PeerScore:
        if not result.success:
            return PeerScore(
                peer_id=result.peer_id,
                score=0.0,
                reason=result.error or "failed",
            )

        tee_score: float = result.metrics.get("tee_score", 0.0)
        gpu_attested: bool = result.metrics.get("gpu_attested", False)
        prompt_match: bool = result.metrics.get("prompt_match", False)
        has_content: bool = result.metrics.get("has_content", False)
        reasonable_latency: bool = result.metrics.get("reasonable_latency", False)

        reasons: List[str] = []
        if not gpu_attested:
            reasons.append("gpu_not_attested")
        if not prompt_match:
            reasons.append("wrong_prompt")
        if not has_content:
            reasons.append("empty_output")
        if not reasonable_latency:
            reasons.append("too_slow")

        if reasons:
            return PeerScore(
                peer_id=result.peer_id,
                score=0.0,
                reason=",".join(reasons),
            )

        return PeerScore(
            peer_id=result.peer_id,
            score=tee_score,
            reason="inference_ok",
        )
