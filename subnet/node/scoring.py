"""
BaseNodeScoring — abstract base class for subnet scoring mechanisms.

The scoring mechanism transforms NodeValidatorResult metrics into a
0.0–1.0 score for each peer. This score is used by consensus to
determine subnet rewards.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

HOW TO IMPLEMENT:

    from subnet.node.scoring import BaseNodeScoring, PeerScore
    from subnet.node.protocol import NodeValidatorResult

    class VGCScoring(BaseNodeScoring):

        GPU_BASELINES = {"A100": 60.0, "H100": 90.0, "MOCK": 50.0}
        GPU_MULTIPLIERS = {"A100": 1.0, "H100": 1.5, "MOCK": 1.0}

        async def score_peer(
            self, result: NodeValidatorResult, epoch: int
        ) -> PeerScore:
            if not result.success:
                return PeerScore(peer_id=result.peer_id, score=0.0, reason="unreachable")

            tps = result.metrics.get("tps", 0.0)
            gpu = result.metrics.get("gpu_category", "MOCK")
            baseline = self.GPU_BASELINES.get(gpu, 50.0)
            multiplier = self.GPU_MULTIPLIERS.get(gpu, 1.0)

            normalised = min(tps / baseline, 1.0) * multiplier
            return PeerScore(peer_id=result.peer_id, score=normalised)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

See subnet/node/mock.py for the minimal working example.
"""

from __future__ import annotations

import abc
import logging
from dataclasses import dataclass
from typing import Dict, List, Optional

from subnet.node.protocol import NodeValidatorResult

logger = logging.getLogger(__name__)


@dataclass
class PeerScore:
    """
    Score assigned to a single peer by the validator.

    Fields
    ------
    peer_id  : the scored peer
    score    : float in [0.0, 1.0] — higher is better
    reason   : optional human-readable explanation (for dashboards/logs)
    """

    peer_id: str
    score: float
    reason: Optional[str] = None

    def __post_init__(self):
        if not 0.0 <= self.score <= 1.0:
            raise ValueError(f"score must be in [0,1], got {self.score} for {self.peer_id}")


class BaseNodeScoring(abc.ABC):
    """
    Abstract base class for subnet scoring mechanisms.

    Subclass this and implement score_peer().
    The consensus loop will call score_peer() for each active peer
    after validator_call() has collected results.

    Parameters available via self:
      self.db         — RocksDB instance
      self.subnet_id  — current subnet ID
      self.config     — NodeConfig instance (your extended config)
    """

    def __init__(self, db, subnet_id: int, config, **kwargs) -> None:
        self.db = db
        self.subnet_id = subnet_id
        self.config = config
        self._extra = kwargs

    @abc.abstractmethod
    async def score_peer(
        self, result: NodeValidatorResult, epoch: int
    ) -> PeerScore:
        """
        Score a single peer based on their validator_call result.

        Called once per peer per epoch. Must return quickly (seconds).

        Parameters
        ----------
        result  : NodeValidatorResult from validator_call() for this peer
        epoch   : current subnet epoch number

        Returns
        -------
        PeerScore with score in [0.0, 1.0]:
          0.0  — peer failed to respond or produced invalid results
          0.5  — peer passed TEE attestation in mock mode
          1.0  — peer passed real hardware attestation and produced valid results
        """

    async def score_all(
        self, results: List[NodeValidatorResult], epoch: int
    ) -> Dict[str, PeerScore]:
        """
        Score all peers in an epoch. Default: calls score_peer() for each.

        Override if you need cross-peer normalisation (e.g. relative ranking).
        """
        scores: Dict[str, PeerScore] = {}
        for result in results:
            try:
                ps = await self.score_peer(result, epoch)
                scores[result.peer_id] = ps
                logger.debug(
                    "[Scoring] peer=%s score=%.3f reason=%s",
                    result.peer_id[:16], ps.score, ps.reason,
                )
            except Exception as exc:
                logger.warning("[Scoring] error scoring %s: %s", result.peer_id[:16], exc)
                scores[result.peer_id] = PeerScore(
                    peer_id=result.peer_id, score=0.0, reason=f"scoring_error:{exc}"
                )
        return scores
