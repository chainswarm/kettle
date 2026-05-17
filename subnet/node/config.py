"""
NodeConfig — base configuration for a Hypertensor subnet node.

Fork this and extend it with your subnet-specific parameters.
The server passes this to your protocol and scoring implementations.

Example (GPU subnet):
    from subnet.node.config import NodeConfig

    class VGCNodeConfig(NodeConfig):
        gpu_category: str = "MOCK"
        kubetee_url: str = "http://localhost:8080"
        tps_baseline: float = 50.0
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class NodeConfig:
    """
    Base node configuration.

    All fields have sane defaults so the template runs out-of-the-box.
    Override in your subnet/node/config.py implementation.
    """

    # Subnet identity
    subnet_id: int = 0
    subnet_node_id: int = 0
    mode: str = "miner"        # "miner" or "validator"

    # TEE
    mock_tee: bool = True      # False = require real TDX/SEV-SNP hardware

    # Consensus
    min_score: float = 0.0     # Minimum score to be included in consensus
    score_timeout: float = 30.0  # Seconds to wait for a peer's response

    # Observability
    log_level: str = "INFO"

    def is_miner(self) -> bool:
        return self.mode == "miner"

    def is_validator(self) -> bool:
        return self.mode == "validator"
