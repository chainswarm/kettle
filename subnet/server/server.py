import logging
import os
from functools import partial
from typing import List

from libp2p.crypto.keys import KeyPair
from libp2p.custom_types import TProtocol
from libp2p.kad_dht.kad_dht import DHTMode, KadDHT
from libp2p.pubsub.gossipsub import GossipSub
from libp2p.pubsub.pubsub import Pubsub
from libp2p.rcmgr.manager import ResourceManager
from libp2p.records.pubkey import PublicKeyValidator
from libp2p.records.validator import NamespacedValidator
from libp2p.tools.async_service import background_trio_service
import trio

from subnet.config import GOSSIPSUB_PROTOCOL_ID
from subnet.consensus.consensus import Consensus
from subnet.hypertensor.chain_functions import Hypertensor
from subnet.hypertensor.mock.local_chain_functions import LocalMockHypertensor
from subnet.node.mock import MockNodeProtocol, MockNodeScoring, _WORK_TOPIC
from subnet.server.health import health_server
from subnet.server.host import create_host, create_secure_transports
from subnet.server.loops import (
    miner_epoch_loop,
    overwatch_epoch_loop,
    tee_publish_loop,
    validator_scoring_loop,
)
from subnet.tee.config import get_tee_config
from subnet.tee.publisher import TeePublisher
from subnet.tee.quote import TEE_QUOTE_TOPIC, RATLS_CERT_TOPIC
from subnet.utils.addresses import get_public_ip_interfaces
from subnet.utils.connection import (
    basic_maintain_connections,
    demonstrate_random_walk_discovery,
    maintain_connections,
)
from subnet.utils.connections.bootstrap import connect_to_bootstrap_nodes
from subnet.utils.db.database import RocksDB
from subnet.utils.gossipsub.gossip_receiver import GossipReceiver
from subnet.utils.hypertensor.subnet_info_tracker_v3 import SubnetInfoTracker
from subnet.utils.patches import apply_all_patches
from subnet.utils.pos.proof_of_stake import ProofOfStake
from subnet.utils.protocols.ping import handle_ping
from subnet.utils.pubsub.heartbeat import HEARTBEAT_TOPIC, publish_heartbeat_loop
from subnet.utils.pubsub.pubsub_validation import (
    SyncHeartbeatMsgValidator,
    SyncPubsubTopicValidator,
)

# Apply patches for stability
apply_all_patches()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler()],
)
logger = logging.getLogger("server/1.0.0")

PING_PROTOCOL_ID = TProtocol("/ipfs/ping/1.0.0")


class Server:
    def __init__(
        self,
        *,
        ip: str | None = None,
        port: int,
        peerstore_db_path: str | None = None,
        bootstrap_addrs: List[str] | None = None,
        key_pair: KeyPair,
        db: RocksDB,
        subnet_id: int = 0,
        subnet_slot: int = 3,
        subnet_node_id: int = 0,
        hypertensor: Hypertensor | LocalMockHypertensor,
        is_bootstrap: bool = False,
        enable_pubsub_validator: bool = True,
        enable_consensus: bool = True,
        enable_proof_of_stake: bool = True,
        strict_maintain_connections: bool = True,
        # Host specific arguments
        enable_mDNS: bool = False,
        enable_upnp: bool = False,
        enable_autotls: bool = False,
        resource_manager: ResourceManager | None = None,
        psk: str | None = None,
        heartbeat_validator_log_level: int = logging.DEBUG,
        gossip_receiver_log_level: int = logging.DEBUG,
        publish_heartbeat_log_level: int = logging.DEBUG,
        maintain_connections_log_level: int = logging.DEBUG,
        **kwargs,
    ):
        logger.info(f"Server starting subnet_id={subnet_id}")
        self.ip = ip
        self.port = port
        self.bootstrap_addrs = bootstrap_addrs
        self.key_pair = key_pair
        self.subnet_id = subnet_id
        self.subnet_slot = subnet_slot
        self.subnet_node_id = subnet_node_id
        self.hypertensor = hypertensor
        self.db = db
        self.is_bootstrap = is_bootstrap
        self.enable_pubsub_validator = enable_pubsub_validator
        self.enable_consensus = enable_consensus
        self.enable_proof_of_stake = enable_proof_of_stake
        self.strict_maintain_connections = strict_maintain_connections
        # Host specific arguments
        self.enable_mDNS = enable_mDNS
        self.enable_upnp = enable_upnp
        self.enable_autotls = enable_autotls
        self.resource_manager = resource_manager
        self.psk = psk
        self.peerstore_db_path = peerstore_db_path
        self.heartbeat_validator_log_level = heartbeat_validator_log_level
        self.gossip_receiver_log_level = gossip_receiver_log_level
        self.publish_heartbeat_log_level = publish_heartbeat_log_level
        self.maintain_connections_log_level = maintain_connections_log_level

    async def run(self):
        logger.info(f"Server running subnet_id={self.subnet_id}")

        # --- Transport setup ---
        proof_of_stake = None
        secure_transports = None
        if self.enable_proof_of_stake:
            proof_of_stake = ProofOfStake(
                subnet_id=self.subnet_id,
                hypertensor=self.hypertensor,
                min_class=0,
            )
            secure_transports = create_secure_transports(
                self.key_pair, proof_of_stake, self.is_bootstrap
            )

        if self.peerstore_db_path is not None:
            raise NotImplementedError("Persistent peerstore not implemented.")

        # --- Host creation ---
        host, listen_addrs = create_host(
            key_pair=self.key_pair,
            port=self.port,
            secure_transports=secure_transports,
            enable_upnp=self.enable_upnp,
            enable_mDNS=self.enable_mDNS,
            enable_autotls=self.enable_autotls,
            resource_manager=self.resource_manager,
            psk=self.psk,
        )

        logger.info(f"Host ID: {host.get_id()}")

        termination_event = trio.Event()
        async with host.run(listen_addrs=listen_addrs), trio.open_nursery() as nursery:
            logger.info(f"Listening address: {listen_addrs}")

            # Start the peer-store cleanup task, TTL
            nursery.start_soon(host.get_peerstore().start_cleanup_task, 60)

            # Set stream handler for ping protocol (used by overwatch nodes)
            host.set_stream_handler(PING_PROTOCOL_ID, handle_ping)

            dht = KadDHT(
                host,
                DHTMode.SERVER,
                enable_random_walk=True,
                validator=NamespacedValidator({"pk": PublicKeyValidator()}),
            )

            gossipsub = GossipSub(
                protocols=[GOSSIPSUB_PROTOCOL_ID],
                degree=3,
                degree_low=2,
                degree_high=4,
                direct_peers=None,
                time_to_live=60,
                gossip_window=2,
                gossip_history=5,
                heartbeat_initial_delay=0.5,
                heartbeat_interval=2,
            )
            pubsub = Pubsub(host, gossipsub)

            async with background_trio_service(dht):
                subnet_info_tracker = SubnetInfoTracker(
                    termination_event,
                    self.subnet_id,
                    self.subnet_slot,
                    self.hypertensor,
                )

                nursery.start_soon(demonstrate_random_walk_discovery, dht, 30)

                async with background_trio_service(pubsub):
                    async with background_trio_service(gossipsub):
                        logger.info("Pubsub and GossipSub services started.")
                        await pubsub.wait_until_ready()
                        logger.info("Pubsub ready.")

                        if self.enable_pubsub_validator:
                            pubsub.set_topic_validator(
                                HEARTBEAT_TOPIC,
                                SyncPubsubTopicValidator.from_predicate_class(
                                    SyncHeartbeatMsgValidator,
                                    host.get_id(),
                                    subnet_info_tracker,
                                    self.hypertensor,
                                    self.subnet_id,
                                    proof_of_stake,
                                    log_level=self.heartbeat_validator_log_level,
                                ).validate,
                                is_async_validator=False,
                            )

                        # Connect to bootstrap nodes AFTER starting services
                        if self.bootstrap_addrs is not None:
                            await connect_to_bootstrap_nodes(host, self.bootstrap_addrs)

                        from libp2p.utils.address_validation import get_optimal_binding_address
                        optimal_addr = get_optimal_binding_address(self.port)
                        optimal_addr_with_peer = f"{optimal_addr}/p2p/{host.get_id().to_string()}"
                        logger.info(f"\nRunning peer on {optimal_addr_with_peer}\n")

                        for peer_id in host.get_peerstore().peer_ids():
                            await dht.routing_table.add_peer(peer_id)

                        # --- Background services ---
                        gossip_receiver = GossipReceiver(
                            gossipsub=gossipsub,
                            pubsub=pubsub,
                            termination_event=termination_event,
                            db=self.db,
                            topics=[HEARTBEAT_TOPIC, TEE_QUOTE_TOPIC, RATLS_CERT_TOPIC, _WORK_TOPIC],
                            log_level=self.gossip_receiver_log_level,
                        )
                        nursery.start_soon(gossip_receiver.run)

                        if self.strict_maintain_connections:
                            nursery.start_soon(
                                partial(
                                    maintain_connections,
                                    host,
                                    subnet_info_tracker,
                                    gossipsub=gossipsub,
                                    pubsub=pubsub,
                                    dht=dht,
                                    log_level=self.maintain_connections_log_level,
                                )
                            )
                        else:
                            nursery.start_soon(
                                basic_maintain_connections,
                                host,
                                self.maintain_connections_log_level,
                            )

                        if not self.is_bootstrap:
                            await self._start_node_loops(
                                nursery, host, pubsub, proof_of_stake,
                                subnet_info_tracker, termination_event,
                            )

                        await termination_event.wait()

            nursery.cancel_scope.cancel()

        print("Application shutdown complete")

    async def _start_node_loops(
        self, nursery, host, pubsub, proof_of_stake, subnet_info_tracker, termination_event
    ):
        """Start all non-bootstrap node background loops."""
        peer_id_str = host.get_id().to_base58()

        # Heartbeat publisher
        nursery.start_soon(
            publish_heartbeat_loop,
            pubsub,
            HEARTBEAT_TOPIC,
            termination_event,
            self.subnet_id,
            self.subnet_node_id,
            self.hypertensor,
            self.publish_heartbeat_log_level,
        )

        # TEE quote publisher
        tee_config = get_tee_config()
        tee_publisher = TeePublisher(
            db=self.db,
            peer_id=peer_id_str,
            config=tee_config,
        )
        nursery.start_soon(
            tee_publish_loop,
            tee_publisher,
            self.hypertensor,
            self.subnet_id,
            termination_event,
        )

        # Mock node protocol (miner/validator epoch loops)
        protocol = MockNodeProtocol(
            host=host,
            peer_id=peer_id_str,
            subnet_info_tracker=subnet_info_tracker,
            mode="worker",
            db=self.db,
        )
        await protocol.register_handlers()
        scoring = MockNodeScoring(db=self.db, subnet_id=self.subnet_id, config=None)

        nursery.start_soon(
            miner_epoch_loop,
            protocol,
            pubsub,
            self.db,
            peer_id_str,
            self.hypertensor,
            self.subnet_id,
            termination_event,
        )
        nursery.start_soon(
            validator_scoring_loop,
            protocol,
            scoring,
            self.db,
            peer_id_str,
            self.hypertensor,
            self.subnet_id,
            termination_event,
        )
        nursery.start_soon(
            overwatch_epoch_loop,
            self.db,
            peer_id_str,
            self.hypertensor,
            self.subnet_id,
            termination_event,
        )
        health_port = int(os.environ.get("HEALTH_PORT", self.port + 1000))
        nursery.start_soon(health_server, health_port)

        if self.enable_consensus:
            consensus = Consensus(
                db=self.db,
                subnet_id=self.subnet_id,
                subnet_node_id=self.subnet_node_id,
                subnet_info_tracker=subnet_info_tracker,
                hypertensor=self.hypertensor,
                skip_activate_subnet=False,
                start=True,
            )
            nursery.start_soon(consensus._main_loop)
