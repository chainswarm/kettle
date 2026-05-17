"""
subnet.node — The user-implementation zone.

This is where you put your subnet-specific code when forking subnet-template.

Hypertensor subnets have two node roles (configured at startup via --mode):
  miner     — runs the workload, handles incoming requests from validators
  validator — calls miners, scores them, submits scores to the chain

Both roles run on the same node binary. The Server class wires the
DHT, heartbeat, and pubsub plumbing, then calls into THIS package
for the subnet-specific behaviour.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

HOW TO FORK:

1. Fork subnet-template on GitHub (or copy this repo).
2. Delete subnet/node/mock.py (the default stub).
3. Implement YOUR protocol in subnet/node/protocol.py:
       class MyProtocol(BaseNodeProtocol):
           async def miner_loop(...) — what miners do each epoch
           async def validator_call(...) — how validators call miners
4. Implement YOUR scoring in subnet/node/scoring.py:
       class MyScoring(BaseNodeScoring):
           async def score_peer(...) — returns 0.0 to 1.0
5. Implement YOUR config in subnet/node/config.py.
6. Run: docker compose up --build
   The Server class will automatically use your implementations.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

See subnet/node/mock.py for the minimal working example.
See https://docs.hypertensor.org/build-a-subnet for the full guide.
"""

from subnet.node.protocol import BaseNodeProtocol, NodeMinerResult, NodeValidatorResult
from subnet.node.scoring import BaseNodeScoring, PeerScore
from subnet.node.config import NodeConfig

__all__ = [
    "BaseNodeProtocol",
    "NodeMinerResult",
    "NodeValidatorResult",
    "BaseNodeScoring",
    "PeerScore",
    "NodeConfig",
]
