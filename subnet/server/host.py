"""Libp2p host creation and secure transport setup."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import TYPE_CHECKING

from libp2p import new_host
from libp2p.crypto.keys import KeyPair
from libp2p.crypto.x25519 import create_new_key_pair as create_new_x25519_key_pair
from libp2p.custom_types import ISecureTransport, TProtocol
from libp2p.network.config import ConnectionConfig
from libp2p.security.noise.transport import Transport as NoiseTransport
import libp2p.security.secio.transport as secio
from libp2p.security.secio.transport import Transport as SecioTransport
from libp2p.rcmgr.manager import ResourceManager
from libp2p.utils.address_validation import get_available_interfaces

from subnet.utils.pos.pos_transport import (
    PROTOCOL_ID as POS_PROTOCOL_ID,
    POSTransport,
)
from subnet.utils.pos.proof_of_stake import ProofOfStake

if TYPE_CHECKING:
    from libp2p.host.basic_host import BasicHost
    from subnet.hypertensor.chain_functions import Hypertensor
    from subnet.hypertensor.mock.local_chain_functions import LocalMockHypertensor

logger = logging.getLogger("server/1.0.0")

# Cross-internet connection config: increased timeouts for cloud VMs across regions.
# The security upgrade (Noise handshake + POS blockchain check) needs more time
# than the default 10s when traversing Azure NAT across regions (~20-50ms RTT)
# plus blockchain RPC latency for PoS validation.
CROSS_REGION_CONNECTION_CONFIG = ConnectionConfig(
    dial_timeout=30.0,                                    # 10s → 30s for cross-region TCP
    outbound_upgrade_timeout=30.0,                        # 10s → 30s for security+muxer upgrade
    inbound_upgrade_timeout=30.0,                         # 10s → 30s for inbound security+muxer
    outbound_stream_protocol_negotiation_timeout=20.0,    # 10s → 20s
    inbound_stream_protocol_negotiation_timeout=20.0,     # 10s → 20s
    max_connections_per_peer=6,                            # prevent aggressive pruning
)


def create_secure_transports(
    key_pair: KeyPair,
    proof_of_stake: ProofOfStake,
    is_bootstrap: bool,
) -> Mapping[TProtocol, ISecureTransport]:
    """Build POS-wrapped Noise + SECIO transports."""
    log_level = logging.INFO if is_bootstrap else logging.DEBUG

    pos_noise = POSTransport(
        transport=NoiseTransport(
            key_pair,
            noise_privkey=create_new_x25519_key_pair().private_key,
        ),
        pos=proof_of_stake,
        log_level=log_level,
    )

    pos_secio = POSTransport(
        transport=SecioTransport(key_pair),
        pos=proof_of_stake,
        log_level=log_level,
    )

    return {
        POS_PROTOCOL_ID: pos_noise,
        TProtocol(secio.ID): pos_secio,
    }


def create_host(
    *,
    key_pair: KeyPair,
    port: int,
    announce_ip: str | None = None,
    secure_transports: Mapping[TProtocol, ISecureTransport] | None = None,
    enable_upnp: bool = False,
    enable_mDNS: bool = False,
    enable_autotls: bool = False,
    resource_manager: ResourceManager | None = None,
    psk: str | None = None,
) -> tuple[BasicHost, list[str]]:
    """
    Create a configured libp2p host.

    Parameters
    ----------
    announce_ip : If set, add /ip4/<announce_ip>/tcp/<port> to listen addrs
                  so the host advertises its public IP to peers.

    Returns the host and the list of listen addresses.
    """
    import os
    from multiaddr import Multiaddr

    listen_addrs = get_available_interfaces(port)
    logger.info(f"Initial listen addrs: {listen_addrs}")

    host = new_host(
        key_pair=key_pair,
        listen_addrs=listen_addrs,
        sec_opt=secure_transports,
        peerstore_opt=None,
        enable_upnp=enable_upnp,
        enable_mDNS=enable_mDNS,
        enable_autotls=enable_autotls,
        resource_manager=resource_manager,
        psk=psk,
        connection_config=CROSS_REGION_CONNECTION_CONFIG,
    )

    # Patch advertised addresses: replace private/docker IPs with public IP.
    # Cloud VMs (Azure, GCP) have a public IP mapped at the infra level, but
    # the VM's NIC only has a private IP. Without this, peers see 10.x.x.x
    # and can't dial back across the internet.
    pub_ip = announce_ip or os.environ.get("ANNOUNCE_IP", "").strip()
    if pub_ip:
        public_addr = Multiaddr(f"/ip4/{pub_ip}/tcp/{port}")
        original_get_addrs = host.get_addrs

        def patched_get_addrs():
            """Return only the public address instead of private/docker IPs."""
            return [public_addr]

        host.get_addrs = patched_get_addrs

        # Also patch get_transport_addrs so the Swarm internals (connection
        # gating, signed peer records) use the public address, not 10.x.x.x.
        original_get_transport_addrs = host.get_transport_addrs

        def patched_get_transport_addrs():
            """Return only the public transport address."""
            return [public_addr]

        host.get_transport_addrs = patched_get_transport_addrs

        logger.info(f"Patched advertised address to: {public_addr}")

    return host, listen_addrs
