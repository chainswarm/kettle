"""
BaseNodeProtocol — abstract base class for subnet node protocols.

A protocol defines HOW nodes communicate — what a miner does when asked
to perform work, and what a validator sends/receives.

In Hypertensor, each node is BOTH miner and validator depending on its
startup mode (--mode miner|validator). The same protocol class handles both:

  Miner side:   register_handlers() + miner_loop() (per epoch)
  Validator side: validator_call(peer_id) (called during consensus scoring)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

HOW TO IMPLEMENT:

    from subnet.node.protocol import BaseNodeProtocol, NodeMinerResult, NodeValidatorResult

    class VGCProtocol(BaseNodeProtocol):

        # Called once at startup. Register your libp2p stream handlers here.
        async def register_handlers(self) -> None:
            self.host.set_stream_handler(
                "/vgc/inference/1.0.0",
                self._handle_inference_request,
            )

        # Called each epoch for miners. Run your workload here.
        async def miner_loop(self, epoch: int) -> NodeMinerResult:
            tps = await self.run_benchmark()
            return NodeMinerResult(success=True, metrics={"tps": tps})

        # Called by validators to score a peer. Returns the peer's result.
        async def validator_call(
            self, peer_id: str, epoch: int
        ) -> NodeValidatorResult:
            tps = await self.call_remote_benchmark(peer_id)
            return NodeValidatorResult(peer_id=peer_id, metrics={"tps": tps})

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

See subnet/node/mock.py for the minimal working example.
"""

from __future__ import annotations

import abc
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


@dataclass
class NodeMinerResult:
    """
    Result from a miner's per-epoch workload.

    Fields
    ------
    success  : True if the epoch completed without error
    metrics  : dict of metric name → value (e.g. {"tps": 97.3, "latency": 12.1})
    error    : human-readable error message if success=False
    """

    success: bool = True
    metrics: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None


@dataclass
class NodeValidatorResult:
    """
    Result from a validator's call to a single peer.

    Fields
    ------
    peer_id  : the peer that was called
    success  : True if the peer responded
    metrics  : dict of metric name → value (passed to BaseNodeScoring.score_peer)
    error    : human-readable error if success=False
    """

    peer_id: str
    success: bool = True
    metrics: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None


class BaseNodeProtocol(abc.ABC):
    """
    Abstract base class for subnet node protocols.

    Subclass this and implement the abstract methods.
    The server will call:
      1. register_handlers() at startup (both miner and validator modes)
      2. miner_loop(epoch) each epoch if mode == "miner"
      3. validator_call(peer_id, epoch) for each peer if mode == "validator"

    Parameters available in all methods via self:
      self.host              — libp2p IHost
      self.peer_id           — this node's peer ID (string)
      self.subnet_info_tracker — SubnetInfoTracker
      self.mode              — "miner" or "validator"
      self.db                — RocksDB instance
    """

    def __init__(
        self,
        host,
        peer_id: str,
        subnet_info_tracker,
        mode: str,
        db,
        **kwargs,
    ) -> None:
        self.host = host
        self.peer_id = peer_id
        self.subnet_info_tracker = subnet_info_tracker
        self.mode = mode
        self.db = db
        self._extra = kwargs

    async def register_handlers(self) -> None:
        """
        Register libp2p stream handlers at startup.

        Called once after the host is ready, before the epoch loop starts.
        Default: no-op. Override to register your protocol ID handlers.
        """
        pass

    @abc.abstractmethod
    async def miner_loop(self, epoch: int) -> NodeMinerResult:
        """
        Run one epoch of miner work.

        Called by the server's epoch loop when mode=="miner".
        Should be non-blocking (use await for I/O).

        Returns NodeMinerResult with success=True and your metrics.
        """

    @abc.abstractmethod
    async def validator_call(
        self, peer_id: str, epoch: int
    ) -> NodeValidatorResult:
        """
        Call a peer to get their work result (validator side).

        Called by the server's consensus loop when mode=="validator".
        Should contact the peer via libp2p (self.host.new_stream) and
        return their metrics for scoring.

        Returns NodeValidatorResult. If the peer is unreachable:
          return NodeValidatorResult(peer_id=peer_id, success=False)
        """
