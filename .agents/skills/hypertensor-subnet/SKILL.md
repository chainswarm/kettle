---
name: hypertensor-subnet
description: Use when working on Hypertensor subnet code, docs, architecture, chain integration, node behavior, Overwatch, TEE attestation, or terminology in this repository. Enforces Hypertensor-native language and template architecture assumptions.
---

# Hypertensor Subnet

Use this skill before changing or explaining Hypertensor subnet behavior in this repo.

## Terminology

- Say **node**, not miner or validator, when describing participant software.
- Say **Overwatch node** for the separately registered auditor role.
- Treat **Validator** as a rotating chain classification/election status, not a permanent node type.
- If external docs mention miners/validators, translate the concept back to Hypertensor terms before editing repo docs or code comments.

## Chain Model

Every non-bootstrap node may run these duties concurrently:

1. Publish TEE quote and RA-TLS certificate.
2. Generate work and publish signed results.
3. Score peers in the active chain classification set.
4. Audit peer work and submit slash evidence when parity fails.
5. Participate in consensus: elected Validator-class node proposes scores; other eligible nodes attest.

Node classes are chain rotation states:

| Class | Value | Meaning |
|---|---:|---|
| Registered | 0 | Just registered, ephemeral |
| Idle | 1 | Active, waiting assignment |
| Included | 2 | Actively scoring peers |
| Validator | 3 | Eligible for per-epoch validator election |

## Architecture Assumptions

- P2P uses py-libp2p with KadDHT, GossipSub, Noise security, and POS transport wrapping.
- Local development may use SQLite mock chain state; production talks to the Hypertensor/Substrate chain.
- Per-node state lives in RocksDB unless a file says otherwise.
- TEE backends include a mock backend for development and real CVM/TEE backends for deployment.
- Dashboard code is Vue 3 plus API/server code that reads node-local state.

## Work Rules

- Preserve deterministic consensus and scoring behavior. Do not add wall-clock, random, network-order, or floating-point nondeterminism to score-critical paths.
- Keep Overwatch separate from normal node rotation.
- For cross-CVM networking, check `ANNOUNCE_IP`, bootnode discovery, DHT behavior, and mock-chain registration consistency.
- Before broad changes, read `CLAUDE.md`, `ARCHITECTURE.md`, `CHAIN.md`, and the relevant `subnet/` module.
