from dataclasses import asdict
from typing import List, Optional
import logging

from subnet.hypertensor.chain_data import SubnetNodeConsensusData

logger = logging.getLogger(__name__)


class ChainScoreSubmitter:
    def __init__(self, hypertensor, subnet_id: int):
        self.hypertensor = hypertensor
        self.subnet_id = subnet_id

    def submit(self, scores: List[SubnetNodeConsensusData]):
        """
        Sign and broadcast a propose_attestation extrinsic with the given scores.

        :param scores: List of SubnetNodeConsensusData with pre-computed integer scores.
                       Empty list is valid — passes through to chain unchanged.
        :returns: ExtrinsicReceipt on success, None on failure or exception.
        """
        data = [asdict(s) for s in scores]
        try:
            receipt = self.hypertensor.propose_attestation(self.subnet_id, data=data)
            if receipt is not None and not receipt.is_success:
                logger.error(f"⚠️ Score submission failed: {receipt.error_message}")
            return receipt
        except Exception as exc:
            logger.error(f"Score submission exception: {exc}", exc_info=True)
            return None
