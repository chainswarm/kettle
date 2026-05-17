"""
BaseOverwatchVerifier — abstract base class for subnet overwatch.

Overwatch independently audits miner outputs. It runs separately from
the validator scoring loop and can submit slash extrinsics for fraudulent work.

HOW TO IMPLEMENT:

    from subnet.node.overwatch import BaseOverwatchVerifier, OverwatchResult

    class MyOverwatchVerifier(BaseOverwatchVerifier):
        def verify(self, peer_id: str, epoch: int) -> OverwatchResult:
            # Fetch work record from DHT
            # Re-check the work independently
            # Return OverwatchResult(ok=True/False, reason="...")
"""

from __future__ import annotations

import abc
import logging
from dataclasses import dataclass, field
from typing import Any, Dict

logger = logging.getLogger(__name__)


@dataclass
class OverwatchResult:
    """Result from overwatch verification of a single peer's work."""
    ok: bool
    reason: str
    details: Dict[str, Any] = field(default_factory=dict)

    def __bool__(self) -> bool:
        return self.ok


class BaseOverwatchVerifier(abc.ABC):
    """
    Abstract base class for subnet overwatch verifiers.

    Subclass this and implement verify(). The server's overwatch loop
    calls verify() for each peer each epoch.
    """

    def __init__(self, db, config=None, **kwargs) -> None:
        self.db = db
        self.config = config
        self._extra = kwargs

    @abc.abstractmethod
    def verify(self, peer_id: str, epoch: int) -> OverwatchResult:
        """
        Verify a single peer's work for the given epoch.

        Returns OverwatchResult with ok=True if the work is valid.
        If ok=False, reason should describe the failure (e.g. "parity_mismatch").
        """
