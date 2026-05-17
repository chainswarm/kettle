---
created: 2026-03-24T22:51:00.924Z
title: Fix cross-CVM libp2p persistent connections
area: networking
files:
  - subnet/server/host.py
  - subnet/server/server.py
  - subnet/utils/pos/pos_transport.py
---

## Problem

When running nodes across two Azure CVMs (tee-one in westeurope, teetwo in northeurope), the libp2p connection from miner2→bootnode establishes at TCP level but the multistream security handshake fails:

```
MultiselectClient handshake: write failed: fail to write to multiselect communicator
Connection State: established=False, handshake=False
```

Sequence of events:
1. miner2 TCP-connects to bootnode's public IP (48.209.8.60:38960) — succeeds
2. POS (Proof of Stake) check passes — bootnode logs `Proof of stake from 12D3KooWKxAhu5U8: True`
3. Noise/SECIO security handshake fails — connection never reaches `established=True`
4. Bootnode tries to dial back to miner2 using private IP (10.0.0.4) — unreachable

Azure CVMs have public IPs mapped at infrastructure level but the VM NIC only has private IP (10.0.0.x). `ANNOUNCE_IP` env var + `get_addrs()` patch was added to advertise public IPs, but the initial handshake still fails.

Same-machine nodes (tee-one bootnode + miner1 + overwatch) form mesh fine with 2 connected peers each. Only cross-internet connections fail.

Tested with `--disable_proof_of_stake` — same failure, ruling out POS as the cause.

## Solution

Investigate root causes in order:
1. **Noise handshake timeout** — cross-region latency (~20ms) may exceed py-libp2p's default negotiate_timeout. Try increasing `negotiate_timeout` parameter in `new_host()`.
2. **Identify protocol address exchange** — even with `get_addrs()` patched, the Identify protocol may send `listen_addrs` directly. Need to check if py-libp2p sends listen_addrs or get_addrs() results during Identify.
3. **Simultaneous connect** — both sides may try to connect at once, causing a connection race. libp2p has connection gating for this but py-libp2p may not implement it properly.
4. **Alternative approach** — WireGuard tunnel between CVMs would bypass all Azure networking quirks and give each node a stable routable IP.
5. **Alternative approach** — Use libp2p relay/circuit protocol if direct connections can't be made reliable.
