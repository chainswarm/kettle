# TEE Subnet Template

## What This Is

A Bittensor subnet template for the Hypertensor chain where every computation is cryptographically proven to run on real, unmodified hardware. Nodes run inside TEE-attested CVMs (AMD SEV-SNP, Intel TDX), with DCAP signature verification, hardware-level Sybil resistance, and CVE-aware firmware enforcement. The template includes an OpenAI-compatible inference gateway (frontier) and an overwatch fraud detection system. Other subnet owners can fork and adapt it for their own use cases.

## Core Value

The only subnet where every computation is cryptographically proven to run on real, unmodified hardware — zero trust required.

## Current Milestone: v1.2 TEE-Attested x402 Inference for Agents

**Goal:** Paid inference endpoint where agents cryptographically verify the gateway is honest (TEE attestation) before authorizing x402 payments. Upto scheme on Base mainnet via Coinbase facilitator.

**Target features:**
- TEE-attested x402 frontier (separate from OpenRouter frontier)
- upto scheme payments (USDC on Base, variable per output token)
- Coinbase mainnet facilitator integration (verify + settle)
- Gateway attestation endpoint (agents verify before paying)
- ACP-compatible for autonomous agents
- RA-TLS from x402 frontier to inference nodes

## Requirements

### Validated

- ✓ TEE attestation generation (Mock, TDX, SEV-SNP, Azure vTPM backends) — existing
- ✓ Identity binding (peer_id:epoch in report_data, anti-replay, anti-Sybil) — existing
- ✓ RA-TLS encrypted sessions (cert generation, session key derivation, output signing) — existing
- ✓ Sealed storage (measurement-derived keys) — existing
- ✓ DcapVerifier pipeline (debug, freshness, identity, chain, measurement, TCB) — existing
- ✓ Real DCAP signature verification (VCEK for SEV-SNP, PCK for TDX) — existing
- ✓ Hardware Sybil resistance (CHIP_ID extraction, GPU UUID tracking, dedup enforcement) — existing
- ✓ CVE-aware TCB enforcement (CacheWarp, BadRAM, minimum version policy) — existing
- ✓ Overwatch fraud detection (parity re-verification, slash extrinsics) — existing
- ✓ GossipSub pub/sub mesh (heartbeats, work records, TEE quotes) — existing
- ✓ Epoch-driven consensus loop (miner work → validator scoring → on-chain submission) — existing
- ✓ Plugin protocol architecture (BaseNodeProtocol, BaseNodeScoring, BaseOverwatchVerifier) — existing
- ✓ Frontier inference gateway (OpenAI-compatible /v1/chat/completions, capacity-based routing) — existing
- ✓ Gramine manifest template for reproducible builds — existing

### Active

- [ ] Cross-CVM libp2p persistent connections (NAT/address advertisement fix)
- [ ] Real-time monitoring dashboard (Vue.js + Tailwind) — node interactions, DHT events, attestation status, overwatch activity
- [ ] Public network explorer view + authenticated admin view
- [ ] RA-TLS forwarding from frontier to nodes (currently returns 501)
- [ ] Full NVIDIA NIM integration for GPU inference
- [ ] Multi-CVM deployment automation (2 miner CVMs + 1 overwatch CVM)

### Out of Scope

- Intel SGX support — deprecated by Intel in consumer CPUs, TDX is the successor
- Custom blockchain — using Hypertensor chain (Substrate-based)
- Mobile clients — server-side subnet infrastructure only

## Context

- **Chain:** Hypertensor (Substrate-based Bittensor chain)
- **Terminology:** Nodes (not miners), overwatch nodes (fraud detection)
- **Hardware:** AMD EPYC Milan/Genoa (SEV-SNP), Intel Xeon Sapphire Rapids+ (TDX)
- **Cloud:** Azure DCasv5 (AMD), DCesv5 (Intel, preview). Two CVMs deployed: tee-one (westeurope, 48.209.8.60), teetwo (northeurope, 40.112.65.210)
- **Networking:** libp2p (py-libp2p), GossipSub, Kademlia DHT, Trio async runtime
- **Attestation:** DCAP with real VCEK/PCK signature verification, AMD KDS cert chain
- **Known issue:** Cross-CVM libp2p connections fail after initial handshake (address advertisement / multistream negotiation)
- **GPU:** NVIDIA NIM for inference, GPU attestation via nv-attestation-sdk (H100/H200/B200), non-CC GPUs trusted via CVM code integrity

## Constraints

- **Runtime:** Python >=3.10, Trio (not asyncio) — entire codebase uses Trio structured concurrency
- **P2P:** py-libp2p pinned to git commit c4abd7c — custom fork with GossipSub fixes
- **TEE:** Real hardware required for production (MIN_TEE_SCORE=1.0 rejects mock)
- **Chain:** Hypertensor Substrate RPC — nodes must be registered on-chain with subnet_node_id
- **Dashboard:** Vue.js + Tailwind CSS, white and light green theme
- **Security:** State-of-the-art — DCAP verified, CVE-enforced, hardware-unique, no shortcuts

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| AMD SEV-SNP as primary TEE | Available now on Azure (DCasv5), Intel TDX in preview only | ✓ Good |
| Trio over asyncio | py-libp2p uses Trio; mixing runtimes adds complexity | ✓ Good |
| CHIP_ID for Sybil resistance | Hardware-fused, VCEK-signed, unforgeable — reported to chain | ✓ Good |
| ALLOW_SHARED_HARDWARE flag | Single-machine testing requires multiple nodes per CVM | ✓ Good |
| Azure vTPM path (sig_algo=0) | Azure hypervisor validates SNP report at boot, no VCEK sig in blob | ✓ Good |
| Vue.js + Tailwind for dashboard | User preference, lightweight, real-time capable with WebSocket | ✓ Good |
| x402 upto scheme for inference | Variable pricing per output token, agents pay only for what they use | — Pending |
| TEE-attested x402 frontier | Agents verify gateway honesty before paying — unique differentiator | — Pending |
| Subnet owner receives USDC | Node operators earn from HT emissions, subnet owner earns x402 revenue | — Pending |

## Evolution

This document evolves at phase transitions and milestone boundaries.

**After each phase transition** (via `/gsd:transition`):
1. Requirements invalidated? → Move to Out of Scope with reason
2. Requirements validated? → Move to Validated with phase reference
3. New requirements emerged? → Add to Active
4. Decisions to log? → Add to Key Decisions
5. "What This Is" still accurate? → Update if drifted

**After each milestone** (via `/gsd:complete-milestone`):
1. Full review of all sections
2. Core Value check — still the right priority?
3. Audit Out of Scope — reasons still valid?
4. Update Context with current state

---
*Last updated: 2026-03-25 after milestone v1.2 start*
