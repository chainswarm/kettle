# Hypertensor Subnet Template — Domain Knowledge

## CRITICAL: Terminology

**There are NO "miners" or "validators" in the Bittensor sense.** Hypertensor has:

- **Nodes** — Every node runs ALL roles simultaneously (work generation, peer scoring, auditing, consensus). There is no miner/validator split.
- **Overwatch nodes** — A separate, permanently registered auditor role. Not a rotation — registered independently on-chain.

Do NOT use "miner" or "validator" when referring to node types. Use "node" or "overwatch node".

## Node Classification (rotation, not type)

Nodes rotate through classes based on stake/reputation — this is a **classification**, not a node type:

| Class | Value | Meaning |
|-------|-------|---------|
| Registered | 0 | Just registered, ephemeral (1 epoch) |
| Idle | 1 | Active, waiting assignment |
| Included | 2 | Actively scoring peers |
| Validator | 3 | Eligible for per-epoch validator election |

**Validator election**: Each epoch, ONE Validator-classed node is elected by the chain to propose consensus scores. All other Included/Validator nodes attest (verify scores match theirs).

## What Every Node Does Per Epoch

Every non-bootstrap node runs these loops concurrently:
1. **TEE publish** — generate and publish attestation quote + RA-TLS cert
2. **Work generation** (miner_epoch_loop) — do work, sign result, publish to DHT
3. **Peer scoring** (validator_scoring_loop) — score all Validator-classed peers
4. **Auditing** (overwatch_epoch_loop) — verify peer work, slash if tampering detected
5. **Consensus** — if elected validator: propose scores; otherwise: attest

## Overwatch Nodes

Overwatch is a **separate registration** (`register_overwatch_node`), not a role rotation. Overwatch nodes:
- Run independently from consensus
- Re-verify all peer work each epoch
- Submit slash extrinsics on parity mismatch (commit-reveal scheme)
- Have their own stake and reputation

## Architecture

- **P2P**: py-libp2p with KadDHT, GossipSub, Noise security + POS transport wrapper
- **Data propagation**: GossipSub topics (heartbeat, tee_quote, ratls_cert, mock_work)
- **Storage**: RocksDB per-node, SQLite mock chain (dev), Substrate chain (prod)
- **TEE**: SEV-SNP via Azure vTPM (real) or MockBackend (dev)
- **Dashboard**: Vue 3 + FastAPI, reads from node's local RocksDB

## Cross-CVM Deployment

- Set `ANNOUNCE_IP=<public-ip>` on each CVM — patches libp2p Identify protocol to advertise public IP
- Nodes auto-discover peers via DHT through a well-known bootnode
- Mock chain DB must contain all participating peer registrations
