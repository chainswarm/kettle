import base58

IP4 = 4
IP6 = 41
TCP = 6
UDP = 17
DNS4 = 54
DNS6 = 55
DNSADDR = 56
P2P = 421
WS = 477
WSS = 478


def encode_varint(value: int) -> bytes:
    out = bytearray()
    while value >= 0x80:
        out.append((value & 0x7F) | 0x80)
        value >>= 7
    out.append(value)
    return bytes(out)


def parse_ipv6(addr: str):
    parts = addr.split("::")
    if len(parts) > 2:
        raise ValueError("Invalid IPv6")

    left = parts[0].split(":") if parts[0] else []
    right = parts[1].split(":") if len(parts) == 2 and parts[1] else []

    if len(left) + len(right) > 8:
        raise ValueError("Invalid IPv6")

    segs = [0] * 8
    for i, p in enumerate(left):
        segs[i] = int(p, 16)

    j = 8 - len(right)
    for p in right:
        segs[j] = int(p, 16)
        j += 1

    return segs


def multiaddr_to_bytes(addr: str) -> bytes:
    out = bytearray()
    parts = [p for p in addr.split("/") if p]
    i = 0

    while i < len(parts):
        proto = parts[i]
        i += 1

        if proto == "ip4":
            ip = parts[i]
            i += 1
            octets = [int(x) for x in ip.split(".")]
            out += encode_varint(IP4)
            out += bytes(octets)

        elif proto == "ip6":
            ip = parts[i]
            i += 1
            out += encode_varint(IP6)
            for seg in parse_ipv6(ip):
                out += seg.to_bytes(2, "big")

        elif proto in ("dns4", "dns6", "dnsaddr"):
            name = parts[i]
            i += 1
            proto_code = {
                "dns4": DNS4,
                "dns6": DNS6,
                "dnsaddr": DNSADDR,
            }[proto]

            name_bytes = name.encode()
            out += encode_varint(proto_code)
            out += encode_varint(len(name_bytes))
            out += name_bytes

        elif proto in ("tcp", "udp"):
            port = int(parts[i])
            i += 1
            out += encode_varint(TCP if proto == "tcp" else UDP)
            out += port.to_bytes(2, "big")

        elif proto == "ws":
            out += encode_varint(WS)

        elif proto == "wss":
            out += encode_varint(WSS)

        elif proto == "p2p":
            peer = parts[i]
            i += 1
            peer_bytes = base58.b58decode(peer)
            out += encode_varint(P2P)
            out += encode_varint(len(peer_bytes))
            out += peer_bytes

        else:
            raise ValueError(f"Unknown protocol: {proto}")

    return bytes(out)
