from dataclasses import asdict
import logging
from typing import List

import trio

from subnet.consensus.utils import (
    compare_consensus_data,
    did_node_attest,
    is_validator_or_attestor,
)
from subnet.hypertensor.chain_data import SubnetNodeConsensusData
from subnet.hypertensor.chain_functions import Hypertensor, SubnetNodeClass
from subnet.hypertensor.config import BLOCK_SECS
from subnet.hypertensor.mock.local_chain_functions import LocalMockHypertensor
from subnet.security.events import SecurityEventIndexer
from subnet.tee.config import get_tee_config
from subnet.tee.verifier import DcapVerifier
from subnet.utils.db.database import RocksDB
from subnet.utils.hypertensor.subnet_info_tracker_v3 import SubnetInfoTracker
from subnet.utils.pubsub.heartbeat import HEARTBEAT_TOPIC

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler()],
)
logger = logging.getLogger("consensus/1.0.0")


class Consensus:
    def __init__(
        self,
        db: RocksDB,
        subnet_id: int,
        subnet_node_id: int,
        subnet_info_tracker: SubnetInfoTracker,
        hypertensor: Hypertensor | LocalMockHypertensor,
        skip_activate_subnet: bool = False,
        start: bool = True,
    ):
        super().__init__()
        self.db = db
        self.subnet_id = subnet_id
        self.subnet_node_id = subnet_node_id
        self.subnet_info_tracker = subnet_info_tracker
        self.hypertensor = hypertensor
        self.is_subnet_active: bool = False
        self.skip_activate_subnet = skip_activate_subnet
        self.stop = trio.Event()
        # Security event indexer — records rejections/failures for audit
        self._security_indexer = SecurityEventIndexer(db=self.db)
        # TEE verifier — built once, reused per epoch
        tee_config = get_tee_config()
        self._tee_verifier = DcapVerifier(
            db=self.db, config=tee_config, security_indexer=self._security_indexer,
        )
        self._tee_min_score = tee_config.min_tee_score

    async def _main_loop(self):
        if not await self.run_activate_subnet():
            return
        if not await self.run_is_node_validator():
            return
        await self.run_forever()

    def get_validator(self, epoch: int):
        validator = self.hypertensor.get_rewards_validator(self.subnet_id, epoch)
        return validator

    async def get_scores(self, current_epoch: int, protocol=None, scoring=None) -> List[SubnetNodeConsensusData]:
        """
        Score each included subnet node.

        Two paths (F-12 unification):

        1. If protocol + scoring are provided: calls protocol.validator_call()
           and scoring.score_peer() for each node — the full scoring pipeline
           including correctness checks and TEE verification.

        2. If protocol/scoring not provided (backward compat): uses the
           heartbeat + TEE-only path (no correctness check).

        Scoring formula (path 1 — full):
            result = protocol.validator_call(peer_id, epoch-1)
            peer_score = scoring.score_peer(result, epoch-1)
            final = int(peer_score.score * 1e18)

        Scoring formula (path 2 — TEE-only):
            base_score = int(1e18)  if heartbeat present for epoch-1, else 0
            tee_score  = DcapVerifier.verify(peer_id, epoch-1).score
            final      = int(base_score * tee_score)
        """
        # Get each subnet node ID that is included onchain AND in the subnet
        included_nodes = self.hypertensor.get_min_class_subnet_nodes_formatted(
            subnet_id=self.subnet_id,
            subnet_epoch=current_epoch,
            min_class=SubnetNodeClass.Included,
        )

        check_epoch = current_epoch - 1
        consensus_score_list = []

        # ── Path 1: Full scoring via protocol + scoring (F-12) ──
        if protocol is not None and scoring is not None:
            for node in included_nodes:
                peer_id = node.peer_info.peer_id
                node_id = node.subnet_node_id
                try:
                    result = await protocol.validator_call(peer_id=peer_id, epoch=check_epoch)
                    peer_score = await scoring.score_peer(result, check_epoch)
                    final_score = int(peer_score.score * 1e18)
                    logger.info(
                        "Score node_id=%d peer_id=%s epoch=%d score=%.2f final=%d",
                        node_id, peer_id[:16], check_epoch, peer_score.score, final_score,
                    )
                    consensus_score_list.append(
                        SubnetNodeConsensusData(subnet_node_id=node_id, score=final_score)
                    )
                except Exception as exc:
                    logger.warning(
                        "Scoring error node_id=%d peer_id=%s epoch=%d: %s",
                        node_id, peer_id[:16], check_epoch, exc,
                    )
                    self._security_indexer.record_scoring_failure(
                        peer_id, check_epoch, str(exc),
                    )

            logger.info("Consensus score list epoch=%d (full path): %s", current_epoch, consensus_score_list)
            return consensus_score_list

        # ── Path 2: Heartbeat + TEE only (backward compat) ──
        BASE_SCORE = int(1e18)

        for node in included_nodes:
            peer_id = node.peer_info.peer_id
            node_id = node.subnet_node_id

            # --- Heartbeat check (base liveness) ---
            heartbeat_key = f"{check_epoch}:{peer_id}"
            has_heartbeat = self.db.nmap_get(HEARTBEAT_TOPIC, heartbeat_key) is not None
            if not has_heartbeat:
                logger.debug(
                    "No heartbeat for node_id=%d peer_id=%s epoch=%d — score=0",
                    node_id, peer_id[:16], check_epoch,
                )
                continue

            # --- TEE attestation check ---
            tee_result = self._tee_verifier.verify(peer_id=peer_id, epoch=check_epoch)

            if not tee_result.ok:
                logger.warning(
                    "TEE verify FAILED node_id=%d peer_id=%s epoch=%d reason=%s — score=0",
                    node_id, peer_id[:16], check_epoch, tee_result.rejection_reason,
                )
                continue

            tee_score = tee_result.score

            if tee_score < self._tee_min_score:
                logger.warning(
                    "TEE score %.2f below MIN_TEE_SCORE %.2f for node_id=%d — score=0",
                    tee_score, self._tee_min_score, node_id,
                )
                continue

            final_score = int(BASE_SCORE * tee_score)

            logger.info(
                "Score node_id=%d peer_id=%s epoch=%d tee_score=%.2f final=%d backend=%s",
                node_id, peer_id[:16], check_epoch, tee_score, final_score,
                tee_result.backend.value if tee_result.backend else "none",
            )

            consensus_score_list.append(
                SubnetNodeConsensusData(subnet_node_id=node_id, score=final_score)
            )

        logger.info("Consensus score list epoch=%d: %s", current_epoch, consensus_score_list)
        return consensus_score_list

    async def run_activate_subnet(self):
        """
        Verify subnet is active on-chain before starting consensus

        For initial coldkeys this will sleep until the enactment period, then proceed
        to check once per epoch after enactment starts if the owner activated the subnet
        """
        # Useful if subnet is already active and for testing
        if self.skip_activate_subnet:
            logger.info("Skipping subnet activation and attempting to start consensus")
            return True

        last_epoch = None
        subnet_active = False
        max_errors = 3
        errors_count = 0
        while not self.stop.is_set():
            epoch_data = self.hypertensor.get_epoch_data()
            current_epoch = epoch_data.epoch
            logger.info(f"Current epoch: {current_epoch}, checking subnet activation status")

            if current_epoch != last_epoch:
                subnet_info = self.hypertensor.get_formatted_subnet_info(self.subnet_id)
                if subnet_info is None or subnet_info == None:  # noqa: E711
                    # None means the subnet is likely deactivated
                    if errors_count > max_errors:
                        logger.warning("Cannot find subnet ID: %s, shutting down", self.subnet_id)
                        self.shutdown()
                        subnet_active = False
                        break
                    else:
                        logger.warning(
                            f"Cannot find subnet ID: {self.subnet_id}, trying {max_errors - errors_count} more times"
                        )
                        errors_count = errors_count + 1
                else:
                    if subnet_info.state == "Active":
                        logger.info(f"Subnet ID {self.subnet_id} is active, starting consensus")
                        subnet_active = True
                        break
                    else:
                        logger.info(
                            f"Subnet ID {self.subnet_id} is not active (state: {subnet_info.state}), waiting for activation"
                        )

                last_epoch = current_epoch

            logger.info("Waiting for subnet to be activated. Sleeping until next epoch")
            epoch_data = self.hypertensor.get_epoch_data()
            await trio.sleep(
                max(
                    0.0,
                    epoch_data.seconds_remaining,
                )
            )

        logger.info(
            f"{'Subnet is active, starting consensus' if subnet_active else 'Subnet is not active, not starting consensus'}"  # noqa: E501
        )

        return subnet_active

    async def run_is_node_validator(self):
        """
        Verify node is active on-chain before starting consensus

        Node must be classed as Idle on-chain to to start consensus

        Included nodes cannot be the elected validator or attest but must take part in consensus
        and be included in the consensus data to graduate to a Validator classed node
        """
        last_epoch = None
        while not self.stop.is_set():
            subnet_epoch_data = self.hypertensor.get_epoch_data()
            if subnet_epoch_data is None:
                await trio.sleep(BLOCK_SECS)
                continue

            current_epoch = subnet_epoch_data.epoch

            if current_epoch != last_epoch:
                nodes = self.hypertensor.get_min_class_subnet_nodes_formatted(
                    self.subnet_id, current_epoch, SubnetNodeClass.Idle
                )
                node_found = False
                for node in nodes:
                    if node.subnet_node_id == self.subnet_node_id:
                        node_found = True
                        break

                if not node_found:
                    logger.info(
                        "Subnet Node ID %s is not active on epoch %s. Trying again next epoch",
                        self.subnet_node_id,
                        current_epoch,
                    )
                else:
                    logger.info(
                        "Subnet Node ID %s is classified as active on epoch %s. Starting consensus.",
                        self.subnet_node_id,
                        current_epoch,
                    )
                    break

                last_epoch = current_epoch

            await trio.sleep(max(0, subnet_epoch_data.seconds_remaining))

        return True

    async def run_forever(self):
        """
        Loop until a new epoch to found, then run consensus logic
        """
        self._async_stop_event = trio.Event()
        last_epoch = None
        started = False
        logged_started = False

        logger.info("About to begin consensus")

        while not self.stop.is_set() and not self._async_stop_event.is_set():
            try:
                subnet_epoch_data = self.hypertensor.get_epoch_data()
                if subnet_epoch_data is None:
                    logger.info("Waiting for subnet epoch data")
                    await trio.sleep(BLOCK_SECS)
                    continue

                # Start on fresh epoch
                if started is False:
                    started = True
                    subnet_epoch_data = self.hypertensor.get_subnet_epoch_data(
                        self.subnet_info_tracker.get_subnet_slot()
                    )
                    logger.info(
                        f"Current epoch is {subnet_epoch_data.epoch}.  "
                        f"Starting consensus on next epoch in {subnet_epoch_data.seconds_remaining}s"
                    )
                    await trio.sleep(subnet_epoch_data.seconds_remaining)
                elif not logged_started:
                    logger.info("✅ Starting consensus")
                    logged_started = True

                current_epoch = self.hypertensor.get_subnet_epoch_data(self.subnet_info_tracker.get_subnet_slot()).epoch

                if current_epoch != last_epoch:
                    """
                    Add validation logic before and/or after `await run_consensus(current_epoch)`

                    The logic here should be for qualifying nodes (proving work), generating scores, etc.
                    """
                    logger.info(f"🆕 Epoch {current_epoch}")
                    last_epoch = current_epoch

                    # Attest/Validate
                    await self.run_consensus(current_epoch)

                try:
                    # Get fresh epoch
                    subnet_epoch_data = self.hypertensor.get_subnet_epoch_data(
                        self.subnet_info_tracker.get_subnet_slot()
                    )

                    logger.info(
                        f"Waiting for next epoch {current_epoch + 1} in {subnet_epoch_data.seconds_remaining} seconds"
                    )

                    with trio.move_on_after(
                        max(
                            0.0,
                            subnet_epoch_data.seconds_remaining,
                        )
                    ):
                        await self._async_stop_event.wait()
                        break

                    if self._async_stop_event.is_set():
                        break

                    pass  # Timeout reached
                except Exception:
                    logger.exception("Exception in epoch loop")
                    pass
            except Exception as e:
                logger.warning(e, exc_info=True)
                await trio.sleep(1.0)

    async def run_consensus(self, current_epoch: int):
        """
        At the start of each epoch, we check if we are validator

        Scores are likely generated and rooted from the `run_forever` function, although, any use cases are possible

        We start by:
            - Getting scores
                - Can generate scores in real-time or get from the DHT database

        If elected on-chain validator:
            - Submit scores to Hypertensor

        If attestor (non-elected on-chain validator):
            - Retrieve validators score submission from Hypertensor
            - Compare to our own
            - Attest if 100% accuracy, else do nothing
        """
        logger.info(f"[Consensus] epoch: {current_epoch}")

        # Check if we can be validator or attestor
        # This is important in case a node sets emergency validators and not having misleading
        # logs for nodes not classified as validator on-chain
        if not is_validator_or_attestor(self.hypertensor, self.subnet_id, self.subnet_node_id):
            logger.info("Not attestor or validator, moving to next epoch")
            return

        scores = await self.get_scores(current_epoch)

        if scores is None:
            return

        validator = None
        # Wait until validator is chosen
        while not self.stop.is_set():
            validator = self.get_validator(current_epoch)

            subnet_epoch_data = self.hypertensor.get_subnet_epoch_data(self.subnet_info_tracker.get_subnet_slot())
            _current_epoch = subnet_epoch_data.epoch

            if _current_epoch != current_epoch:
                logger.info(f"Validator not chosen for epoch {current_epoch}, moving to next epoch")
                validator = None
                break

            if validator is not None or validator != "None":
                break

            # Wait until next block to try again
            await trio.sleep(BLOCK_SECS)

        if validator is None or validator == None:  # noqa: E711
            return

        logger.info(f"Elected validator on epoch {current_epoch} is node ID {validator}")

        if validator == self.subnet_node_id:
            logger.info(
                f"🎖️ Acting as elected validator for epoch {current_epoch} and attempting to propose an attestation to the blockchain"  # noqa: E501
            )

            # See if attestation proposal submitted
            consensus_data = self.hypertensor.get_consensus_data_formatted(self.subnet_id, current_epoch)

            if consensus_data is not None:  # noqa: E711
                logger.info("Already submitted data, moving to next epoch")

                return

            logger.info("Preparing to attempt to propose attestation")

            if len(scores) == 0:
                """
                Add any logic here for when no scores are present.

                The blockchain allows the validator to submit an empty score. This can mean
                the subnet is in a broken state or not synced.

                If other peers also come up with the same "zero" scores, they can attest the validator
                and the validator will not accrue penalties or be slashed. The subnet itself will accrue
                penalties until it recovers (penalties decrease for every successful epoch).

                No scores are generated, likely subnet in broken state and all other nodes
                should be too, so we submit consensus with no scores.

                This will increase subnet penalties, but avoid validator penalties.

                Any successful epoch following will remove these penalties on the subnet
                """
                self.hypertensor.propose_attestation(self.subnet_id, data=[asdict(s) for s in scores])
            else:
                self.hypertensor.propose_attestation(self.subnet_id, data=[asdict(s) for s in scores])

        elif validator is not None:
            logger.info(
                f"🗳️ Attempting to act as attestor/voter for epoch {current_epoch}, attesting validator ID {validator}"
            )

            consensus_data = None  # Fetch one time once not None
            while not self.stop.is_set():
                # Check consensus data exists in case attest fails
                if consensus_data is None or consensus_data == None:  # noqa: E711
                    consensus_data = self.hypertensor.get_consensus_data_formatted(self.subnet_id, current_epoch)

                logger.debug(f"Consensus data: {consensus_data}")

                subnet_epoch_data = self.hypertensor.get_subnet_epoch_data(self.subnet_info_tracker.get_subnet_slot())
                _current_epoch = subnet_epoch_data.epoch

                # If next epoch or validator took too long, move onto next steps
                if _current_epoch != current_epoch or subnet_epoch_data.percent_complete > 0.25:
                    logger.info(
                        f"Skipping attestation, validator ID {validator} took too long to submit consensus data or next epoch"  # noqa: E501
                    )
                    break

                if consensus_data is None or consensus_data == None:  # noqa: E711
                    logger.info("Waiting for consensus data to be submitted, checking again in 1 block")
                    await trio.sleep(BLOCK_SECS)
                    continue

                """
                If this subnet doesn't utilize `prioritize_queue_node_id` or `remove_queue_node_id`, then always skip
                attestation. See https://docs.hypertensor.org/network/consensus for more information.
                """
                if (
                    consensus_data.prioritize_queue_node_id is not None
                    or consensus_data.remove_queue_node_id is not None
                ):
                    logger.info(
                        f"Skipping attestation, validator ID {validator} used prioritize_queue_node_id or remove_queue_node_id"  # noqa: E501
                    )
                    break

                validator_data = consensus_data.data

                """
                Get all of the hosters inference outputs they stored to the DHT
                """
                if 1.0 == compare_consensus_data(my_data=scores, validator_data=validator_data):
                    # Check if we already attested
                    if did_node_attest(self.subnet_node_id, consensus_data):
                        logger.debug("Already attested, moving to next epoch")
                        break

                    logger.info(
                        f"✅ Elected validator ID {validator} data matches for epoch {current_epoch}, attesting their data"
                    )

                    receipt = self.hypertensor.attest(self.subnet_id)

                    if isinstance(self.hypertensor, LocalMockHypertensor):  # don't check receipt if using mock
                        break

                    if receipt.is_success:
                        break
                    else:
                        await trio.sleep(BLOCK_SECS)
                else:
                    logger.info(
                        f"❌ Data doesn't match validator ID {validator} data for epoch {current_epoch}, moving forward with no attestation"  # noqa: E501
                    )

                    break

    async def shutdown(self):
        if not self.stop.is_set():
            self.stop.set()

        logger.info("Consensus shutdown requested")
