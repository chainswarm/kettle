import logging
import socket

from libp2p.abc import IHost
from libp2p.tools.utils import info_from_p2p_addr
from multiaddr import Multiaddr
import trio

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler()],
)
logger = logging.getLogger("server/1.0.0")

# Bootstrap connection parameters for cross-internet reliability.
BOOTSTRAP_CONNECT_TIMEOUT = 30.0   # seconds per attempt
BOOTSTRAP_MAX_RETRIES = 3          # retries per bootstrap address
BOOTSTRAP_RETRY_DELAY = 2.0        # seconds between retries (doubles each attempt)


def _resolve_dns_multiaddr(addr: str) -> str:
    """
    Resolve dns4/dns6 components in a multiaddr to ip4/ip6.

    py-libp2p's TCP transport calls extract_ip_from_multiaddr() which only
    handles ip4/ip6 — not dns4/dns6.  This helper resolves the hostname at
    the application layer before handing the multiaddr to libp2p, working
    around the transport limitation.

    e.g.  /dns4/bootnode/tcp/38960/p2p/<id>
       →  /ip4/172.26.0.2/tcp/38960/p2p/<id>
    """
    maddr = Multiaddr(addr)
    for dns_proto, ip_proto in (("dns4", "ip4"), ("dns6", "ip6"), ("dns", "ip4")):
        try:
            hostname = maddr.value_for_protocol(dns_proto)
        except Exception:
            continue
        if hostname:
            try:
                family = socket.AF_INET if ip_proto == "ip4" else socket.AF_INET6
                resolved_ip = socket.getaddrinfo(hostname, None, family)[0][4][0]
                resolved = addr.replace(f"/{dns_proto}/{hostname}/", f"/{ip_proto}/{resolved_ip}/")
                logger.debug(f"Resolved {addr} → {resolved}")
                return resolved
            except Exception as e:
                logger.warning(f"DNS resolution failed for {hostname}: {e}")
    return addr


async def _connect_with_retry(host: IHost, addr: str) -> bool:
    """Connect to a single bootstrap node with retry and timeout."""
    resolved_addr = _resolve_dns_multiaddr(addr)
    peer_info = info_from_p2p_addr(Multiaddr(resolved_addr))
    host.get_peerstore().add_addrs(peer_info.peer_id, peer_info.addrs, 300)

    delay = BOOTSTRAP_RETRY_DELAY
    for attempt in range(BOOTSTRAP_MAX_RETRIES + 1):
        try:
            with trio.fail_after(BOOTSTRAP_CONNECT_TIMEOUT):
                await host.connect(peer_info)
            logger.info(f"Connected to bootstrap node {addr}")
            return True
        except trio.TooSlowError:
            logger.warning(
                f"Bootstrap connect timeout ({BOOTSTRAP_CONNECT_TIMEOUT}s) "
                f"for {addr} (attempt {attempt + 1}/{BOOTSTRAP_MAX_RETRIES + 1})"
            )
        except Exception as e:
            logger.warning(
                f"Bootstrap connect failed for {addr} "
                f"(attempt {attempt + 1}/{BOOTSTRAP_MAX_RETRIES + 1}): {e}"
            )
        if attempt < BOOTSTRAP_MAX_RETRIES:
            await trio.sleep(delay)
            delay *= 2  # exponential backoff
    return False


async def connect_to_bootstrap_nodes(host: IHost, bootstrap_addrs: list[str]) -> None:
    """
    Connect to the bootstrap nodes provided in the list.

    Retries each address up to BOOTSTRAP_MAX_RETRIES times with exponential
    backoff and a per-attempt timeout, for reliability on cross-internet
    connections (e.g. Azure CVMs across regions).

    params: host: The host instance to connect to
            bootstrap_addrs: List of bootstrap node addresses

    Returns
    -------
        None

    """
    connections = 0
    for addr in bootstrap_addrs:
        if await _connect_with_retry(host, addr):
            connections += 1

    if connections == 0:
        raise Exception("Failed to connect to any bootstrap nodes")
