import hashlib
import logging
import os
from dataclasses import asdict
from typing import Optional

from subnet.hypertensor.chain_data import OverwatchCommit, OverwatchReveals
from subnet.tee.sealed.store import SealedStore

logger = logging.getLogger(__name__)

_PUNISH_WEIGHT = 0
_REWARD_WEIGHT = int(1e18)


def _make_salt_key(epoch: int, peer_id: str) -> str:
    return f"overwatch_salt:{epoch}:{peer_id}"


class ChainOverwatchReporter:
    def __init__(self, hypertensor, overwatch_node_id: int, subnet_id: int,
                 sealed_store: Optional[SealedStore] = None):
        self.hypertensor = hypertensor
        self.overwatch_node_id = overwatch_node_id
        self.subnet_id = subnet_id
        self._sealed_store = sealed_store

    def slash(self, peer_id: str, epoch: int, evidence=None) -> object:
        salt = os.urandom(32)
        weight_int = _PUNISH_WEIGHT

        # Persist salt before commit (F-06)
        if self._sealed_store is not None:
            salt_key = _make_salt_key(epoch, peer_id)
            self._sealed_store.seal(salt_key, salt)
            logger.info("[Overwatch] Salt persisted: key=%s", salt_key)

        # Persist evidence alongside the salt (F-19)
        if evidence is not None and self._sealed_store is not None:
            evidence_key = f"overwatch_evidence:{epoch}:{peer_id}"
            import json
            self._sealed_store.seal(evidence_key, json.dumps(evidence).encode())
            logger.info("[Overwatch] Evidence stored: key=%s", evidence_key)

        weight_bytes = weight_int.to_bytes(16, byteorder="big")
        commit_hash = hashlib.sha256(weight_bytes + salt).digest()

        commit_weights = [asdict(OverwatchCommit(subnet_id=self.subnet_id, weight=commit_hash))]
        reveals = [asdict(OverwatchReveals(subnet_id=self.subnet_id, weight=weight_int, salt=salt))]

        logger.info(
            "[Overwatch] Submitting slash commit peer=%s epoch=%d subnet_id=%d",
            peer_id[:16] if peer_id else "?",
            epoch,
            self.subnet_id,
        )
        try:
            commit_receipt = self.hypertensor.commit_overwatch_subnet_weights(
                self.overwatch_node_id, commit_weights
            )
            if commit_receipt is not None and not commit_receipt.is_success:
                logger.error(
                    "Overwatch commit failed: %s", commit_receipt.error_message
                )
                return commit_receipt

            reveal_receipt = self.hypertensor.reveal_overwatch_subnet_weights(
                self.overwatch_node_id, reveals
            )

            # Only clean up salt after confirmed successful reveal
            reveal_ok = reveal_receipt is not None and reveal_receipt.is_success
            if not reveal_ok:
                if reveal_receipt is not None:
                    logger.error(
                        "Overwatch reveal failed: %s (salt preserved for retry)",
                        reveal_receipt.error_message,
                    )
            elif self._sealed_store is not None:
                salt_key = _make_salt_key(epoch, peer_id)
                self._sealed_store.delete(salt_key)

            return reveal_receipt
        except Exception as exc:
            logger.error("Overwatch extrinsic exception: %s", exc, exc_info=True)
            return None
