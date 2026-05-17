"""Epoch-driven background loops: TEE publishing, mining, validator scoring, overwatch."""

from __future__ import annotations

import base64
import json as _json
import logging
import os as _os
from typing import TYPE_CHECKING

import trio

from subnet.hypertensor.chain_functions import SubnetNodeClass
from subnet.hypertensor.chain_data import SubnetNodeConsensusData
from subnet.consensus.chain_overwatch_reporter import ChainOverwatchReporter
from subnet.consensus.chain_submitter import ChainScoreSubmitter
from subnet.node.mock import MockOverwatchVerifier, _WORK_TOPIC
from subnet.tee.quote import TEE_QUOTE_TOPIC, RATLS_CERT_TOPIC

if TYPE_CHECKING:
    from subnet.node.mock import MockNodeProtocol, MockNodeScoring
    from subnet.tee.publisher import TeePublisher


async def tee_publish_loop(
    tee_publisher: TeePublisher,
    hypertensor,
    subnet_id: int,
    termination_event,
) -> None:
    """
    Publish a TEE attestation quote to the DHT once per epoch.

    Runs alongside the heartbeat loop. On each epoch boundary, generates
    a fresh quote bound to (peer_id, epoch) and stores it via nmap_set.

    The quote is published at the start of the epoch so validators can
    fetch it during consensus scoring at the end of the epoch.
    """
    logger = logging.getLogger("tee_publish_loop")

    last_epoch = None
    while not termination_event.is_set():
        try:
            slot = hypertensor.get_subnet_slot(subnet_id)
            epoch_data = hypertensor.get_subnet_epoch_data(int(str(slot)))
            current_epoch = epoch_data.epoch

            if current_epoch != last_epoch:
                logger.info("[TEE] New epoch %d — publishing quote", current_epoch)
                quote = tee_publisher.publish(epoch=current_epoch)
                logger.info(
                    "[TEE] Published: backend=%s measurement=%s... epoch=%d",
                    quote.backend.value,
                    quote.measurement[:16],
                    current_epoch,
                )
                last_epoch = current_epoch

            # Poll every 5 seconds for epoch change
            with trio.move_on_after(5):
                await trio.sleep(5)

        except trio.Cancelled:
            break
        except Exception as exc:
            logger.warning("[TEE] Publish error (non-fatal): %s", exc)
            await trio.sleep(10)

    logger.info("[TEE] Publish loop stopped")


async def miner_epoch_loop(
    protocol: MockNodeProtocol,
    pubsub,
    db,
    peer_id_str: str,
    hypertensor,
    subnet_id: int,
    termination_event,
) -> None:
    """
    Run miner_loop() once per epoch and gossip all three produced records
    (TEE quote, RA-TLS cert, work record) to the mesh.

    Starts with a 10 s delay to allow mesh formation before the first publish.
    """
    from subnet.tee.quote import dht_key as tee_dht_key

    loop_logger = logging.getLogger("miner_epoch_loop")
    last_epoch = None
    # Initial delay to allow mesh formation
    await trio.sleep(10)
    while not termination_event.is_set():
        try:
            slot = hypertensor.get_subnet_slot(subnet_id)
            epoch_data = hypertensor.get_subnet_epoch_data(int(str(slot)))
            current_epoch = epoch_data.epoch
            if current_epoch != last_epoch:
                loop_logger.info("[MinerLoop] New epoch %d — running miner_loop", current_epoch,
                                 extra={"epoch": current_epoch})
                await protocol.miner_loop(current_epoch)
                last_epoch = current_epoch
                # Gossip: TEE quote
                tee_key = tee_dht_key(current_epoch, peer_id_str)
                tee_raw = db.nmap_get(TEE_QUOTE_TOPIC, tee_key)
                if tee_raw is not None:
                    await pubsub.publish(TEE_QUOTE_TOPIC, tee_raw)
                    loop_logger.info("[GossipPub] TEE published epoch=%d", current_epoch,
                                     extra={"epoch": current_epoch})
                else:
                    loop_logger.warning("[GossipPub] No TEE quote to publish epoch=%d", current_epoch)
                # Gossip: RA-TLS cert (wrap in JSON envelope expected by receiver)
                cert_key = f"{current_epoch}:{peer_id_str}"
                cert_raw = db.nmap_get(RATLS_CERT_TOPIC, cert_key)
                if cert_raw is not None:
                    payload = _json.dumps({
                        "epoch": current_epoch,
                        "cert": base64.b64encode(cert_raw).decode(),
                    }).encode()
                    await pubsub.publish(RATLS_CERT_TOPIC, payload)
                    loop_logger.info("[GossipPub] RATLS cert published epoch=%d", current_epoch,
                                     extra={"epoch": current_epoch})
                else:
                    loop_logger.warning("[GossipPub] No RATLS cert to publish epoch=%d", current_epoch)
                # Gossip: work record
                work_raw = db.nmap_get(_WORK_TOPIC, cert_key)
                if work_raw is not None:
                    await pubsub.publish(_WORK_TOPIC, work_raw)
                    loop_logger.info("[GossipPub] Work record published epoch=%d", current_epoch,
                                     extra={"epoch": current_epoch})
                else:
                    loop_logger.warning("[GossipPub] No work record to publish epoch=%d", current_epoch)
            with trio.move_on_after(5):
                await trio.sleep(5)
        except trio.Cancelled:
            raise
        except Exception as exc:
            loop_logger.warning("[MinerLoop] Error (non-fatal): %s", exc)
            await trio.sleep(10)
    loop_logger.info("[MinerLoop] stopped")


async def validator_scoring_loop(
    protocol: MockNodeProtocol,
    scoring: MockNodeScoring,
    db,
    self_peer_id: str,
    hypertensor,
    subnet_id: int,
    termination_event,
) -> None:
    """
    Score all subnet peers once per epoch.

    Waits 30 s on startup for GossipSub mesh formation and miner gossip
    propagation, then on each new epoch scores epoch-1 for every non-self peer.
    """
    loop_logger = logging.getLogger("validator_scoring_loop")
    last_epoch = None
    submitter = ChainScoreSubmitter(hypertensor, subnet_id)
    # Wait for mesh formation and miner gossip propagation
    loop_logger.info("[ValidatorLoop] Waiting 30s for mesh formation...")
    await trio.sleep(30)
    while not termination_event.is_set():
        try:
            slot = hypertensor.get_subnet_slot(subnet_id)
            epoch_data = hypertensor.get_subnet_epoch_data(int(str(slot)))
            current_epoch = epoch_data.epoch
            if current_epoch != last_epoch and current_epoch >= 1:
                last_epoch = current_epoch
                score_epoch = current_epoch - 1
                loop_logger.info("[ValidatorLoop] Scoring epoch=%d", score_epoch)
                nodes = hypertensor.get_min_class_subnet_nodes_formatted(
                    subnet_id, score_epoch, SubnetNodeClass.Validator
                )
                scores = []
                for node in nodes:
                    peer_info = node.peer_info
                    if isinstance(peer_info, dict):
                        peer_id = peer_info.get("peer_id", "")
                    elif hasattr(peer_info, "peer_id"):
                        peer_id = peer_info.peer_id
                    else:
                        peer_id = str(peer_info)
                    if not peer_id or peer_id == self_peer_id:
                        continue
                    try:
                        result = await protocol.validator_call(peer_id=peer_id, epoch=score_epoch)
                        peer_score = await scoring.score_peer(result, score_epoch)
                        loop_logger.info(
                            "[Validator] peer=%s epoch=%d score=%.2f correct=%s",
                            peer_id[:16],
                            score_epoch,
                            peer_score.score,
                            result.metrics.get("correct", "?"),
                            extra={
                                "epoch": score_epoch,
                                "peer": peer_id[:16],
                                "score": round(peer_score.score, 2),
                            },
                        )
                        scores.append(SubnetNodeConsensusData(
                            subnet_node_id=node.subnet_node_id,
                            score=int(peer_score.score * 1e18),
                        ))
                    except trio.Cancelled:
                        raise
                    except Exception as exc:
                        loop_logger.warning("[ValidatorLoop] Score error peer=%s: %s", peer_id[:16], exc)
                if scores:
                    submitter.submit(scores)
                    loop_logger.info("[ValidatorLoop] Submitted scores epoch=%d count=%d", score_epoch, len(scores))
            with trio.move_on_after(5):
                await trio.sleep(5)
        except trio.Cancelled:
            raise
        except Exception as exc:
            loop_logger.warning("[ValidatorLoop] Error (non-fatal): %s", exc)
            await trio.sleep(10)
    loop_logger.info("[ValidatorLoop] stopped")


async def overwatch_epoch_loop(
    db,
    self_peer_id: str,
    hypertensor,
    subnet_id: int,
    termination_event,
) -> None:
    """
    Independent overwatch audit — re-checks parity math for every peer each epoch.

    Waits 35 s on startup (slightly more than validator's 30 s) so work records
    from the miner's miner_epoch_loop are available when overwatch first runs.
    Logs [Overwatch] TAMPER when parity_mismatch is detected, [Overwatch] PASS
    on clean audit. no_work_record on first 1-2 epochs (cold start) is DEBUG only.
    """
    loop_logger = logging.getLogger("overwatch_epoch_loop")
    last_epoch = None
    loop_logger.info("[OverwatchLoop] Waiting 35s for mesh formation...")
    await trio.sleep(35)
    # --- overwatch reporter setup (guarded) ---
    # OVERWATCH_NODE_ID activates on-chain slash extrinsics.
    # OVERWATCH_PHRASE (optional) signs those extrinsics with a dedicated keypair;
    # if absent, falls back to the node's own hypertensor keypair.
    _overwatch_node_id_str = _os.environ.get("OVERWATCH_NODE_ID", "")
    if _overwatch_node_id_str.isdigit():
        _overwatch_phrase = _os.environ.get("OVERWATCH_PHRASE", "")
        if _overwatch_phrase:
            try:
                from subnet.hypertensor.chain_functions import Hypertensor as _Hypertensor
                _ow_hypertensor = _Hypertensor(hypertensor.url, _overwatch_phrase)
                loop_logger.info("[OverwatchLoop] Using dedicated OVERWATCH_PHRASE keypair for slash extrinsics")
            except Exception as _exc:
                loop_logger.warning(
                    "[OverwatchLoop] Failed to init overwatch keypair from OVERWATCH_PHRASE (%s) — falling back to node keypair",
                    _exc,
                )
                _ow_hypertensor = hypertensor
        else:
            _ow_hypertensor = hypertensor
        reporter = ChainOverwatchReporter(_ow_hypertensor, int(_overwatch_node_id_str), subnet_id)
    else:
        reporter = None
    while not termination_event.is_set():
        try:
            slot = hypertensor.get_subnet_slot(subnet_id)
            epoch_data = hypertensor.get_subnet_epoch_data(int(str(slot)))
            current_epoch = epoch_data.epoch
            if current_epoch != last_epoch and current_epoch >= 1:
                last_epoch = current_epoch
                score_epoch = current_epoch - 1
                loop_logger.info("[OverwatchLoop] Auditing epoch=%d", score_epoch)
                nodes = hypertensor.get_min_class_subnet_nodes_formatted(
                    subnet_id, score_epoch, SubnetNodeClass.Validator
                )
                verifier = MockOverwatchVerifier(db=db)
                for node in nodes:
                    peer_info = node.peer_info
                    if isinstance(peer_info, dict):
                        peer_id = peer_info.get("peer_id", "")
                    elif hasattr(peer_info, "peer_id"):
                        peer_id = peer_info.peer_id
                    else:
                        peer_id = str(peer_info)
                    if not peer_id or peer_id == self_peer_id:
                        continue
                    try:
                        result = verifier.verify(peer_id, score_epoch)
                        if result.ok:
                            loop_logger.info(
                                "[Overwatch] PASS peer=%s epoch=%d",
                                peer_id[:16], score_epoch,
                                extra={"epoch": score_epoch, "peer": peer_id[:16]},
                            )
                        elif result.reason == "no_work_record":
                            loop_logger.debug(
                                "[OverwatchLoop] no_work_record peer=%s epoch=%d (cold start)",
                                peer_id[:16], score_epoch,
                            )
                        else:
                            loop_logger.warning(
                                "[Overwatch] TAMPER peer=%s epoch=%d reason=%s",
                                peer_id[:16], score_epoch, result.reason,
                                extra={"epoch": score_epoch, "peer": peer_id[:16], "reason": result.reason},
                            )
                            if result.reason == "parity_mismatch" and reporter is not None:
                                reporter.slash(peer_id, score_epoch, result.details)
                    except trio.Cancelled:
                        raise
                    except Exception as exc:
                        loop_logger.warning("[OverwatchLoop] Audit error peer=%s: %s", peer_id[:16], exc)
            with trio.move_on_after(5):
                await trio.sleep(5)
        except trio.Cancelled:
            raise
        except Exception as exc:
            loop_logger.warning("[OverwatchLoop] Error (non-fatal): %s", exc)
            await trio.sleep(10)
    loop_logger.info("[OverwatchLoop] stopped")
