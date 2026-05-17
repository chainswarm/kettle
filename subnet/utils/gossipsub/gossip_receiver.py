import base64
import json
import logging

import base58
from libp2p.abc import ISubscriptionAPI
from libp2p.pubsub.gossipsub import GossipSub
from libp2p.pubsub.pb import rpc_pb2
from libp2p.pubsub.pubsub import Pubsub
import trio

from subnet.utils.db.database import RocksDB
from subnet.utils.pubsub.heartbeat import HEARTBEAT_TOPIC, HeartbeatData
from subnet.tee.quote import TEE_QUOTE_TOPIC, RATLS_CERT_TOPIC
from subnet.node.mock import _WORK_TOPIC

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("gossip_topics")


class GossipReceiver:
    """
    Manages receiving gossip messages and logic for storing in the base path db

    Params:
        gossipsub: GossipSub instance
        pubsub: Pubsub instance
        termination_event: trio.Event to signal termination
        db: RocksDB instance
        topics: list of topic strings

    Usage:
        gossip = GossipReceiver(
            gossipsub,
            pubsub,
            termination_event,
            db,
            [HEARTBEAT_TOPIC, "commit", "reveal", "custom"],
        )
        nursery.start_soon(gossip.run)  # Starts sync loop + receive loops

    Validating database entries:
        Use topic validators for validating a pubsub message.

        The use of this class is to handle what happens after the peer receives a message.

        Capture messages from topics in `_handle_message`

        See `_handle_*` functions for examples

    """

    def __init__(
        self,
        gossipsub: GossipSub,
        pubsub: Pubsub,
        termination_event: trio.Event,
        db: RocksDB,
        topics: list[str],
        log_level: int = logging.INFO,
    ):
        self.gossipsub = gossipsub
        self.pubsub = pubsub
        self.termination_event = termination_event
        self.db = db
        self.topics = topics
        self._last_epoch: int | None = None
        self.log_level = log_level
        self._seen_heartbeats: set[str] = set()  # e.g.: "epoch:peer_id"
        self._seen_tee_quotes: set[str] = set()
        self._seen_ratls_certs: set[str] = set()
        self._seen_work_records: set[str] = set()
        self._keep_epochs = 3  # keep this many epochs of data

        """
        self._seen_commits: set[str] = set()  # e.g.: "epoch:peer_id"
        self._seen_reveals: set[str] = set()  # e.g.: "epoch:peer_id"
        self._seen_customs: set[str] = set()  # e.g.: "epoch:peer_id"
        """

    async def run(self) -> None:
        """
        Main entry point - starts sync loop and receive loops for all topics.

        Call this with: nursery.start_soon(gossip.run)
        """
        async with trio.open_nursery() as nursery:
            for topic in self.topics:
                subscription = await self.pubsub.subscribe(topic)
                logger.log(self.log_level, f"Subscribed to topic: {topic}")
                nursery.start_soon(self._receive_loop, subscription)

    async def _receive_loop(self, subscription: ISubscriptionAPI) -> None:
        """Receive loop for a single topic subscription."""
        logger.log(self.log_level, "Starting gossip receive loop")
        while not self.termination_event.is_set():
            try:
                message = await subscription.get()
                await self._handle_message(message)

            except Exception:
                logger.exception("Error in gossip receive loop")
                await trio.sleep(1)

    async def _handle_message(self, message: rpc_pb2.Message) -> None:
        """Handle incoming message based on topic."""
        from_peer = base58.b58encode(message.from_id).decode()
        topic = message.topicIDs[0] if message.topicIDs else None
        logger.log(self.log_level, f"From peer: {from_peer}, topic: {topic}")

        if topic == HEARTBEAT_TOPIC:
            await self._handle_heartbeat(message, from_peer)
        elif topic == TEE_QUOTE_TOPIC:
            await self._handle_tee_quote(message, from_peer)
        elif topic == RATLS_CERT_TOPIC:
            await self._handle_ratls_cert(message, from_peer)
        elif topic == _WORK_TOPIC:
            await self._handle_work_record(message, from_peer)

        # Add custom topics and handlers here
        """
        elif topic == COMMIT_TOPIC:
            await self._handle_commit(message, from_peer)
        elif topic == REVEAL_TOPIC:
            await self._handle_reveal(message, from_peer)
        elif topic == CUSTOM_TOPIC_1:
            await self._handle_custom_1(message, from_peer)
        elif topic == CUSTOM_TOPIC_2:
            await self._handle_custom_2(message, from_peer)
        """

    """Handle Heartbeat message"""

    async def _handle_heartbeat(self, message: rpc_pb2.Message, from_peer: str) -> None:
        """Store heartbeat message if not already stored for this epoch."""
        try:
            heartbeat_data = HeartbeatData.from_json(message.data.decode("utf-8"))
        except Exception as e:
            logger.warning(f"HeartbeatData validation failed: {e}")
            return

        key = f"{heartbeat_data.epoch}:{from_peer}"

        # Fast in-memory check
        if key in self._seen_heartbeats:
            logger.log(self.log_level, f"Heartbeat already seen (cached): {key}")
            return

        # Check if already exists
        if self.db.nmap_get(HEARTBEAT_TOPIC, key) is not None:
            logger.log(self.log_level, f"Heartbeat already exists: {key}")
            return

        # Store it
        self.db.nmap_set(HEARTBEAT_TOPIC, key, message.data.decode("utf-8"))
        logger.log(
            self.log_level,
            f"Heartbeat stored: {HEARTBEAT_TOPIC}:{key} for node ID {heartbeat_data.subnet_node_id}",
        )

        # Add to in-memory set
        self._seen_heartbeats.add(key)

    async def _handle_tee_quote(self, message: rpc_pb2.Message, from_peer: str) -> None:
        from subnet.tee.quote import TeeQuote
        try:
            quote = TeeQuote.from_bytes(message.data)
            epoch = quote.nonce
        except Exception as e:
            logger.warning(f"TeeQuote parse failed: {e}")
            return

        # F-03: Verify quote's internal peer_id matches the gossip sender
        if quote.peer_id != from_peer:
            logger.warning(
                f"TEE quote peer_id mismatch: quote.peer_id={quote.peer_id[:16]} "
                f"from_peer={from_peer[:16]} — REJECTED (possible spoofing)"
            )
            return

        key = f"{epoch}:{from_peer}"
        if key in self._seen_tee_quotes or self.db.nmap_get(TEE_QUOTE_TOPIC, key) is not None:
            return
        self.db.nmap_set(TEE_QUOTE_TOPIC, key, message.data)
        self._seen_tee_quotes.add(key)
        logger.log(self.log_level, f"TEE quote stored: epoch={epoch} peer={from_peer[:16]}")

    async def _handle_ratls_cert(self, message: rpc_pb2.Message, from_peer: str) -> None:
        try:
            data = json.loads(message.data.decode())
            epoch = int(data["epoch"])
            cert_bytes = base64.b64decode(data["cert"])
        except Exception as e:
            logger.warning(f"RATLS cert parse failed: {e}")
            return

        # F-03: Verify cert's embedded quote peer_id matches the gossip sender
        try:
            from subnet.tee.ratls.cert import extract_quote_from_cert
            embedded_quote = extract_quote_from_cert(cert_bytes)
            if embedded_quote.peer_id != from_peer:
                logger.warning(
                    f"RATLS cert peer_id mismatch: cert.peer_id={embedded_quote.peer_id[:16]} "
                    f"from_peer={from_peer[:16]} — REJECTED (possible spoofing)"
                )
                return
        except Exception as e:
            logger.warning(f"RATLS cert quote extraction failed: {e} — REJECTED")
            return

        key = f"{epoch}:{from_peer}"
        if key in self._seen_ratls_certs or self.db.nmap_get(RATLS_CERT_TOPIC, key) is not None:
            return
        self.db.nmap_set(RATLS_CERT_TOPIC, key, cert_bytes)
        self._seen_ratls_certs.add(key)
        logger.log(self.log_level, f"RATLS cert stored: epoch={epoch} peer={from_peer[:16]}")

    async def _handle_work_record(self, message: rpc_pb2.Message, from_peer: str) -> None:
        from subnet.tee.ratls.envelope import OutputEnvelope
        try:
            env = OutputEnvelope.from_bytes(message.data)
            rec = json.loads(env.output.decode())
            epoch = int(rec["epoch"])
        except Exception as e:
            logger.warning(f"Work record parse failed: {e}")
            return

        # F-03: Verify work record's internal peer_id matches the gossip sender
        claimed_peer = rec.get("peer_id", "")
        if claimed_peer and claimed_peer != from_peer:
            logger.warning(
                f"Work record peer_id mismatch: claimed={claimed_peer[:16]} "
                f"from_peer={from_peer[:16]} — REJECTED (possible spoofing)"
            )
            return

        key = f"{epoch}:{from_peer}"
        if key in self._seen_work_records or self.db.nmap_get(_WORK_TOPIC, key) is not None:
            return
        self.db.nmap_set(_WORK_TOPIC, key, message.data)
        self._seen_work_records.add(key)
        logger.log(self.log_level, f"Work record stored: epoch={epoch} peer={from_peer[:16]}")

    def cleanup_old_epochs(self, current_epoch: int) -> int:
        """Remove entries from seen-sets that are older than keep_epochs. Returns count removed."""
        cutoff = current_epoch - self._keep_epochs
        removed = 0
        for seen_set in (self._seen_heartbeats, self._seen_tee_quotes,
                         self._seen_ratls_certs, self._seen_work_records):
            old_keys = {k for k in seen_set if int(k.split(":")[0]) < cutoff}
            seen_set -= old_keys
            removed += len(old_keys)
        if removed:
            logger.info("[GossipReceiver] Cleaned up %d old entries (cutoff epoch=%d)", removed, cutoff)
        return removed

    """Handle commit message (example)"""

    async def _handle_commit(self, message: rpc_pb2.Message, from_peer: str) -> None: ...

    """Handle reveal message (example)"""

    async def _handle_reveal(self, message: rpc_pb2.Message, from_peer: str) -> None: ...

    """
    Handle custom message
    (create your own validation functions for storing messages in the database)
    """

    async def _handle_custom(self, message: rpc_pb2.Message, from_peer: str) -> None: ...
