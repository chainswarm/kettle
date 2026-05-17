import logging
import random

from libp2p.abc import (
    IHost,
)
from libp2p.kad_dht.kad_dht import KadDHT
from libp2p.peer.id import ID as PeerID
from libp2p.pubsub.gossipsub import GossipSub
from libp2p.pubsub.pubsub import Pubsub
import trio

from subnet.config import GOSSIPSUB_PROTOCOL_ID
from subnet.utils.hypertensor.subnet_info_tracker_v3 import SubnetInfoTracker

logger = logging.getLogger("subnet.utils.connection")


def filter_compatible_peer_info(peer_info) -> bool:
    """Filter peer info to check if it has compatible addresses (TCP + IPv4)."""
    if not hasattr(peer_info, "addrs") or not peer_info.addrs:
        return False

    for addr in peer_info.addrs:
        addr_str = str(addr)
        if "/tcp/" in addr_str and "/ip4/" in addr_str and "/quic" not in addr_str:
            return True
    return False


async def maintain_connections(
    host: IHost,
    subnet_info_tracker: SubnetInfoTracker,
    gossipsub: GossipSub | None = None,
    pubsub: Pubsub | None = None,
    dht: KadDHT | None = None,
    connection_backoff_duration: float = 300.0,  # 5 minutes
    max_backoff_duration: float = 1080.0,  # 18 minutes
    retry_multiplier: float = 1.2,
    log_level: int = logging.DEBUG,
) -> None:
    """Maintain connections to ensure the host remains connected to healthy peers."""
    my_peer_id = host.get_id()

    # Track retries for each peer, and next retry time
    peer_retries: dict[PeerID, int] = {}
    peer_next_retry: dict[PeerID, float] = {}

    while True:
        try:
            # Get all peers that are expected to be in the network
            onchain_peer_ids = await subnet_info_tracker.get_all_peer_ids(force=True)
            logger.log(log_level, f"All peer IDs: {onchain_peer_ids}")

            # Get all peers that are currently connected to the host
            connected_peers = host.get_connected_peers()
            logger.log(log_level, f"Host connected peers: {connected_peers}")

            # READ INFO
            transport_addrs = host.get_transport_addrs()
            logger.log(log_level, f"Host transport addrs: {transport_addrs}")

            list_peers = host.get_peerstore().peers_with_addrs()

            # Get all peers that are in the DHT
            if dht:
                peerstore_peer_ids = dht.host.get_peerstore().peer_ids()
                logger.log(log_level, f"DHT peerstore peer IDs: {peerstore_peer_ids}")
                for peer_id in dht.routing_table.get_peer_ids():
                    if peer_id not in list_peers:
                        list_peers.append(peer_id)

            all_peers = list(set(connected_peers + list_peers))
            for peer_id in all_peers:
                try:
                    peer_info = host.get_peerstore().peer_info(peer_id)
                    logger.log(log_level, f"Peer info addresses {peer_id}: {peer_info.addrs} \n\n")
                except Exception as e:
                    logger.debug(f"Failed to get peer info for {peer_id}: {e}", exc_info=True)

            remove_peers = []

            # Remove peers that are not in the onchain peer list and are connected
            # Use list copies to avoid issues with modification during iteration
            for peer_id in list(connected_peers):
                if peer_id not in onchain_peer_ids and not peer_id.__eq__(my_peer_id):
                    remove_peers.append(peer_id)
                    connected_peers.remove(peer_id)
                    peer_retries.pop(peer_id, None)
                    peer_next_retry.pop(peer_id, None)

            # Remove peers that are not in the onchain peer list and are in the peerstore
            for peer_id in list(list_peers):
                if peer_id not in onchain_peer_ids and not peer_id.__eq__(my_peer_id):
                    remove_peers.append(peer_id)
                    list_peers.remove(peer_id)
                    peer_retries.pop(peer_id, None)
                    peer_next_retry.pop(peer_id, None)

            # Deduplicate the removal list
            remove_peers = list(set(remove_peers))

            await disconnect_peers(
                remove_peers,
                host,
                gossipsub,
                dht,
                log_level,
            )

            logger.log(log_level, f"List peers: {list_peers}")

            if len(connected_peers) < 32:
                logger.log(log_level, "Reconnecting to maintain peer connections...")

                # Find compatible peers
                compatible_peers = []
                for peer_id in list_peers:
                    try:
                        peer_info = host.get_peerstore().peer_info(peer_id)
                        if filter_compatible_peer_info(peer_info) and trio.current_time() >= peer_next_retry.get(
                            peer_id, 0
                        ):
                            compatible_peers.append(peer_id)
                    except Exception as e:
                        logger.debug(f"Failed to get peer info for {peer_id}: {e}", exc_info=True)
                        continue

                # Connect to random subset of compatible peers
                if compatible_peers:
                    logger.log(log_level, f"Compatible peers: {compatible_peers}")
                    random_peers = random.sample(compatible_peers, min(64, len(compatible_peers)))
                    logger.log(log_level, f"Random peers: {random_peers}")
                    for peer_id in random_peers:
                        if peer_id not in connected_peers and peer_id in onchain_peer_ids:
                            try:
                                peer_retries[peer_id] = peer_retries.get(peer_id, 0) + 1
                                next_retry_time = trio.current_time() + connection_backoff_duration * (
                                    peer_retries.get(peer_id, 0) ** retry_multiplier
                                )
                                if next_retry_time > max_backoff_duration:
                                    next_retry_time = max_backoff_duration
                                peer_next_retry[peer_id] = next_retry_time

                                if dht and not dht.enable_random_walk:
                                    # Only call if random walk is disabled
                                    # Otherwise `find_peer` compete for the same resources
                                    with trio.move_on_after(5):
                                        peer_info = await dht.find_peer(peer_id)
                                        if not peer_info:
                                            continue

                                with trio.move_on_after(5):
                                    peer_info = host.get_peerstore().peer_info(peer_id)
                                    logger.log(log_level, f"Adding addresses for peer: {peer_id}")
                                    host.get_peerstore().add_addrs(peer_info.peer_id, peer_info.addrs, 300)
                                    logger.log(log_level, f"Connecting to peer: {peer_id}")
                                    await host.connect(peer_info)
                                    logger.log(log_level, f"Connected to peer: {peer_id}")
                            except Exception as e:
                                logger.debug(f"Failed to connect to {peer_id}: {e}", exc_info=True)

            if gossipsub:
                # Prune disconnected peers from gossipsub mesh
                mesh_peers = set()
                for topic_peers in gossipsub.mesh.values():
                    mesh_peers.update(topic_peers)

                logger.log(log_level, f"GossipSub mesh: {gossipsub.mesh}")

                gossipsub_topic = next((t for t in gossipsub.mesh if str(t) == "heartbeat"), None)

                topic_peers = set()
                if gossipsub_topic:
                    topic_peers = gossipsub.mesh[gossipsub_topic]
                    logger.log(log_level, f"Heartbeat number of peers: {len(topic_peers)}")
                    for peer_id in topic_peers:
                        logger.log(log_level, f"Heartbeat mesh peer: {peer_id}")

                    connected_peers = set(pubsub.peers.keys())
                    subscribed_peers = pubsub.peer_topics.get("heartbeat", set())
                    valid_mesh_peers = topic_peers & connected_peers & subscribed_peers
                    stale_peers = topic_peers - valid_mesh_peers

                    logger.log(log_level, f"Pubsub Connected peers: {connected_peers}")
                    logger.log(log_level, f"Pubsub Subscribed peers: {subscribed_peers}")
                    logger.log(log_level, f"Pubsub Valid mesh peers: {valid_mesh_peers}")
                    logger.log(log_level, f"Pubsub Stale mesh peers: {stale_peers}")

                    # if stale_peers:
                    #     logger.log(
                    #         log_level,
                    #         "Removing %d stale peers from mesh for topic %s: %s",
                    #         len(stale_peers),
                    #         gossipsub_topic,
                    #         stale_peers,
                    #     )
                    #     for peer in stale_peers:
                    #         gossipsub.mesh[gossipsub_topic].discard(peer)
                    #         if gossipsub.scorer is not None:
                    #             gossipsub.scorer.on_leave_mesh(peer, gossipsub_topic)

                logger.log(log_level, f"GossipSub network health score: {gossipsub.network_health_score}")
                ###

                compatible_peers = []
                for peer_id in list_peers:
                    try:
                        peer_info = host.get_peerstore().peer_info(peer_id)
                        if filter_compatible_peer_info(peer_info):
                            compatible_peers.append(peer_id)
                    except Exception as e:
                        logger.debug(f"Failed to get peer info for {peer_id}: {e}", exc_info=True)
                        continue
                random_peers = random.sample(compatible_peers, min(64, len(compatible_peers)))
                random_peers = [p for p in random_peers if p in onchain_peer_ids and p not in topic_peers]

                await maintain_gossipsub_connections(random_peers, host, gossipsub, pubsub, log_level)

            await trio.sleep(60)
        except Exception as e:
            logger.error(f"Error maintaining connections: {e}", exc_info=True)


async def maintain_gossipsub_connections(
    peer_ids: list[PeerID],
    host: IHost,
    gossipsub: GossipSub,
    pubsub: Pubsub,
    log_level: int = logging.DEBUG,
):
    """
    Maintain connections to peers in gossipsub.
    """
    for peer_id in peer_ids:
        await maintain_single_gossipsub_connection(
            peer_id,
            host,
            gossipsub,
            pubsub,
            log_level,
        )


async def maintain_single_gossipsub_connection(
    peer_id: PeerID,
    host: IHost,
    gossipsub: GossipSub,
    pubsub: Pubsub,
    log_level: int = logging.DEBUG,
):
    try:
        # 1. Verify connection status
        # Make sure peer is connected before attempting to add to gossipsub
        if peer_id not in host.get_connected_peers():
            logger.debug(
                f"maintain_single_gossipsub_connection, Peer {peer_id} is not connected yet to add to gossipsub"  # noqa: E501
            )
            return

        # 2. Verify protocol support
        # Make sure peer supports /meshsub/1.0.0 before attempting to add to gossipsub
        try:
            protocols = host.get_peerstore().get_protocols(peer_id)
            logger.debug(
                f"maintain_single_gossipsub_connection, {peer_id} protocols: {protocols}"  # noqa: E501
            )
            if GOSSIPSUB_PROTOCOL_ID not in protocols:
                logger.debug(
                    f"maintain_single_gossipsub_connection, Peer {peer_id} does not support {GOSSIPSUB_PROTOCOL_ID} yet"  # noqa: E501
                )
                host.get_peerstore().add_protocols(peer_id, ["/meshsub/1.0.0"])
                return
        except Exception as e:
            logger.debug(
                f"maintain_single_gossipsub_connection, Failed to get protocols for {peer_id} with: {e}",
                exc_info=True,
            )
            return

        # 3. Verify blacklisting
        # Make sure peer is not blacklisted before attempting to add to gossipsub
        # If peer is blacklisted, remove it from the blacklist
        # Peers sent to this function should be verified they shouldn't be blacklisted
        if pubsub:
            is_blacklisted = pubsub.is_peer_blacklisted(peer_id)
            logger.debug(
                f"maintain_single_gossipsub_connection, {peer_id} is blacklisted: {is_blacklisted}"  # noqa: E501
            )
            if is_blacklisted:
                pubsub.remove_from_blacklist(peer_id)

        # 4. Ensure PubSub has a working stream to this peer.
        # gossipsub.add_peer() only registers the protocol — it doesn't create
        # a PubSub stream.  Without a stream, messages can't flow.  This is the
        # root cause of one-directional GossipSub on cross-CVM connections:
        # peers are connected at Swarm level but PubSub has no stream to them.
        if peer_id not in pubsub.peers:
            logger.log(
                log_level,
                f"maintain_single_gossipsub_connection, Peer {peer_id} missing PubSub stream, creating",
            )
            try:
                with trio.move_on_after(10):
                    await pubsub._handle_new_peer(peer_id)
            except Exception as e:
                logger.debug(f"maintain_single_gossipsub_connection, Failed to create PubSub stream for {peer_id}: {e}")
                return

        # 5. Verify existing gossipsub registration
        if gossipsub.peer_protocol.get(peer_id) == GOSSIPSUB_PROTOCOL_ID:
            logger.debug(
                f"maintain_single_gossipsub_connection, Peer {peer_id} is already in {GOSSIPSUB_PROTOCOL_ID}"  # noqa: E501
            )
            return

        gossipsub.add_peer(peer_id, GOSSIPSUB_PROTOCOL_ID)
        logger.log(log_level, f"maintain_single_gossipsub_connection, Added peer to gossipsub: {peer_id}")
    except Exception as e:
        logger.warning(f"maintain_single_gossipsub_connection, Failed to add peer {peer_id}: {e}")


async def disconnect_peers(
    peer_ids: list[PeerID],
    host: IHost,
    gossipsub: GossipSub | None = None,
    dht: KadDHT | None = None,
    log_level: int = logging.DEBUG,
):
    for peer_id in peer_ids:
        # Remove from host
        try:
            await host.disconnect(peer_id)
            # logger.info(
            #     f"Disconnected peer {peer_id} because they are no longer registered on-chain"  # noqa: E501
            # )

            # Clear from peerstore so we stop dialing them
            # clear_peerdata completely removes the peer record from all internal maps
            host.get_peerstore().clear_peerdata(peer_id)
            logger.log(
                log_level, f"Fully cleared peer {peer_id} from peerstore because they are no longer registered on-chain"
            )
        except Exception as e:
            logger.debug(f"Failed to disconnect peer {peer_id}: {e}", exc_info=True)
        if dht:
            # Remove from DHT routing table
            try:
                dht.routing_table.remove_peer(peer_id)
                dht.host.get_peerstore().clear_peerdata(peer_id)
                logger.log(log_level, f"Removed peer {peer_id} from routing table and cleared peerdata")
            except Exception as e:
                logger.debug(f"Failed to remove peer {peer_id}: {e}", exc_info=True)
        if gossipsub:
            # Remove from GossipSub
            try:
                gossipsub.remove_peer(peer_id)
                logger.log(
                    log_level, f"Removed peer {peer_id} from gossipsub because they are no longer registered on-chain"
                )
            except Exception as e:
                logger.debug(f"Failed to remove peer {peer_id}: {e}", exc_info=True)


async def demonstrate_random_walk_discovery(dht: KadDHT, interval: int = 30) -> None:
    """Demonstrate Random Walk peer discovery with periodic statistics."""
    while True:
        logger.info(f"Routing table size: {dht.get_routing_table_size()}")
        logger.info(f"Connected peers: {len(dht.host.get_connected_peers())}")
        logger.info(f"Peerstore size: {len(dht.host.get_peerstore().peer_ids())}")

        if dht.get_routing_table_size() > 0:
            logger.info("Peers in routing table:")
            for peer_id in dht.routing_table.get_peer_ids():
                logger.info(f"  {peer_id}")

        await trio.sleep(interval)


async def basic_maintain_connections(host: IHost, log_level: int = logging.DEBUG) -> None:
    """Maintain connections to ensure the host remains connected to healthy peers."""
    while True:
        try:
            connected_peers = host.get_connected_peers()
            list_peers = host.get_peerstore().peers_with_addrs()

            logger.log(log_level, f"Connected peers: {connected_peers}")
            logger.log(log_level, f"List peers:      {list_peers}")

            all_peers = list(set(connected_peers + list_peers))
            for peer_id in all_peers:
                try:
                    peer_info = host.get_peerstore().peer_info(peer_id)
                    logger.log(log_level, f"Peer info addresses {peer_id}: {peer_info.addrs} \n\n")
                except Exception as e:
                    logger.debug(f"Failed to get peer info for {peer_id}: {e}", exc_info=True)

            if len(connected_peers) < 20:
                logger.log(log_level, "Reconnecting to maintain peer connections...")

                # Find compatible peers
                compatible_peers = []
                for peer_id in list_peers:
                    try:
                        peer_info = host.get_peerstore().peer_info(peer_id)
                        if filter_compatible_peer_info(peer_info):
                            compatible_peers.append(peer_id)
                    except Exception:
                        continue

                # Connect to random subset of compatible peers
                if compatible_peers:
                    random_peers = random.sample(compatible_peers, min(50, len(compatible_peers)))
                    for peer_id in random_peers:
                        if peer_id not in connected_peers:
                            try:
                                with trio.move_on_after(5):
                                    peer_info = host.get_peerstore().peer_info(peer_id)
                                    await host.connect(peer_info)
                                    logger.log(log_level, f"Connected to peer: {peer_id}")
                            except Exception as e:
                                logger.debug(f"Failed to connect to {peer_id}: {e}")

            await trio.sleep(15)
        except Exception as e:
            logger.error(f"Error maintaining connections: {e}")
