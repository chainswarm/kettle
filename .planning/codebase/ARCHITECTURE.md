# Architecture

**Analysis Date:** 2026-03-24

## Pattern Overview

**Overall:** Decentralized peer-to-peer subnet with epoch-driven consensus, TEE attestation, and a plugin-style protocol/scoring abstraction.

**Key Characteristics:**
- libp2p-based P2P networking with GossipSub pub/sub and Kademlia DHT
- Epoch-driven lifecycle: miner work, validator scoring, consensus attestation, and overwatch audit all gate on epoch boundaries
- Abstract base classes (Protocol, Scoring, Overwatch) define the extension points; `MockNode*` implementations serve as the reference/template
- Trio-based async concurrency (structured nurseries, not asyncio)
- RocksDB named-map (nmap) as the local DHT for gossip-received data (heartbeats, TEE quotes, RA-TLS certs, work records)
- Blockchain integration via Substrate RPC (Hypertensor chain) for on-chain consensus, staking, and slashing

## Layers

**CLI / Entry Points:**
- Purpose: Parse arguments, initialize dependencies, launch the Server
- Location: `subnet/cli/`
- Contains: `run_node.py` (primary entry), crypto key commands, hypertensor registration commands
- Depends on: `subnet/server/server.py`, `subnet/hypertensor/`, `subnet/utils/db/`
- Used by: End users, Docker containers

**Server (Networking Core):**
- Purpose: Create libp2p host, wire GossipSub/DHT/PubSub, start all background loops
- Location: `subnet/server/`
- Contains: `server.py` (Server class orchestrator), `host.py` (libp2p host factory), `loops.py` (epoch-driven background loops), `health.py` (HTTP health check)
- Depends on: libp2p, all other subnet modules
- Used by: CLI layer

**Node Protocol Layer:**
- Purpose: Define WHAT work miners do and HOW validators score it. This is the primary extension point for subnet developers.
- Location: `subnet/node/`
- Contains: `protocol.py` (BaseNodeProtocol ABC), `scoring.py` (BaseNodeScoring ABC), `overwatch.py` (BaseOverwatchVerifier ABC), `mock.py` (reference implementation), `config.py`
- Depends on: `subnet/tee/`, `subnet/utils/db/`
- Used by: `subnet/server/loops.py`, `subnet/consensus/`

**Consensus Layer:**
- Purpose: On-chain score submission and attestation voting
- Location: `subnet/consensus/`
- Contains: `consensus.py` (Consensus main loop), `chain_submitter.py` (ChainScoreSubmitter), `chain_overwatch_reporter.py` (ChainOverwatchReporter), `utils.py`
- Depends on: `subnet/hypertensor/`, `subnet/tee/verifier.py`, `subnet/utils/db/`
- Used by: `subnet/server/server.py`

**TEE (Trusted Execution Environment):**
- Purpose: Hardware attestation generation, verification, RA-TLS session keys, output signing
- Location: `subnet/tee/`
- Contains: `quote.py` (TeeQuote schema), `config.py` (TeeConfig), `publisher.py` (TeePublisher), `verifier.py` (DcapVerifier), `backends/` (mock/tdx/sev-snp), `ratls/` (cert/session/envelope), `sealed/` (sealed storage), `gpu_attestation.py`
- Depends on: `subnet/utils/db/`, cryptography library
- Used by: `subnet/node/mock.py`, `subnet/consensus/consensus.py`, `subnet/server/loops.py`

**Frontier (Inference Gateway):**
- Purpose: OpenAI-compatible HTTP gateway that routes inference requests to least-loaded cluster nodes
- Location: `subnet/frontier/`
- Contains: `app.py` (FastAPI app factory), `capacity.py` (CapacityTable), `messages.py` (GossipSub join/leave messages), `cli.py` (entry point)
- Depends on: FastAPI, pydantic
- Used by: External API consumers

**Hypertensor (Blockchain Client):**
- Purpose: Substrate RPC wrapper for on-chain interactions (registration, staking, consensus extrinsics, epoch data)
- Location: `subnet/hypertensor/`
- Contains: `chain_functions.py` (Hypertensor class), `chain_data.py` (data classes), `config.py`, `helpers.py`, `mock/` (LocalMockHypertensor for testing)
- Depends on: `substrate-interface`, `scalecodec`
- Used by: Nearly all other layers

**Utilities:**
- Purpose: Cross-cutting concerns (DB, gossip, host, pubsub, crypto, connections, PoS)
- Location: `subnet/utils/`
- Contains: `db/database.py` (RocksDB wrapper), `gossipsub/` (GossipReceiver), `pubsub/heartbeat.py` (HeartbeatData), `pos/proof_of_stake.py` (ProofOfStake), `connections/`, `host/`, `crypto/`, `logging.py`, `patches.py`
- Depends on: libp2p, RocksDB
- Used by: Server, Consensus, Node layers

**Scoring Implementations:**
- Purpose: Concrete scoring strategies beyond the mock
- Location: `subnet/scoring/`
- Contains: `gpu_inference.py` (GpuInferenceScoring)
- Depends on: `subnet/node/scoring.py` base class
- Used by: Validators running GPU inference subnets

**Models (Cluster Assignment):**
- Purpose: Model registry, ratio-based assignment for multi-model clusters
- Location: `subnet/models/`
- Contains: `registry.py` (ModelRegistry, ModelConfig), `assignment.py` (compute_assignment)
- Depends on: Nothing (self-contained)
- Used by: Frontier routing, node join logic

**REST API:**
- Purpose: HTTP API for inspecting RocksDB state (peers, nmaps, keys, health)
- Location: `subnet/api/`
- Contains: `main.py` (FastAPI app), `config.py`, `dependencies.py`, `models.py`, `auth/` (API key + rate limiting), `routers/v1/` (health, keys, nmaps, peers)
- Depends on: FastAPI, `subnet/utils/db/`
- Used by: Operators, dashboards

## Data Flow

**Miner Epoch Work (per epoch):**

1. `miner_epoch_loop` in `subnet/server/loops.py` detects new epoch via `hypertensor.get_subnet_epoch_data()`
2. Calls `protocol.miner_loop(epoch)` (e.g., `MockNodeProtocol.miner_loop()` in `subnet/node/mock.py`)
3. Miner generates RA-TLS cert + TEE quote (via `RaTlsServer` in `subnet/tee/ratls/server.py`)
4. Miner performs work (random number + parity check in mock), wraps output in `OutputEnvelope` signed with session key
5. Stores TEE quote, RA-TLS cert, and work record to local RocksDB via `db.nmap_set()`
6. `miner_epoch_loop` gossips all three records to the mesh via `pubsub.publish()` on topics: `tee_quote`, `ratls_cert`, `mock_work`

**Gossip Reception:**

1. `GossipReceiver.run()` in `subnet/utils/gossipsub/gossip_receiver.py` subscribes to all topics
2. Incoming messages are dispatched by topic to `_handle_heartbeat`, `_handle_tee_quote`, `_handle_ratls_cert`, `_handle_work_record`
3. Each handler validates sender identity (F-03 peer_id match), deduplicates via in-memory seen-sets, and stores to RocksDB nmap

**Validator Scoring (per epoch):**

1. `validator_scoring_loop` in `subnet/server/loops.py` waits 30s for mesh formation, then detects new epoch
2. Fetches all subnet nodes from chain: `hypertensor.get_min_class_subnet_nodes_formatted()`
3. For each peer: calls `protocol.validator_call(peer_id, epoch)` which:
   - Fetches RA-TLS cert from local DB (received via gossip)
   - Verifies TEE quote via `DcapVerifier.verify()` (identity binding, chain verification, measurement, TCB policy)
   - Verifies RA-TLS cert via `RaTlsClient.verify_cert()`
   - Fetches work record, verifies `OutputEnvelope` HMAC signature
   - Re-checks correctness (e.g., parity math)
4. Calls `scoring.score_peer(result, epoch)` to produce a `PeerScore` (0.0-1.0)
5. `ChainScoreSubmitter.submit()` broadcasts `propose_attestation` extrinsic to chain

**Consensus Attestation:**

1. `Consensus._main_loop()` in `subnet/consensus/consensus.py` waits for subnet activation, then loops per epoch
2. Computes scores via `get_scores()` (two paths: full protocol+scoring or heartbeat+TEE-only)
3. If elected validator: submits `propose_attestation` to chain
4. If attestor: fetches validator's submission, compares to own scores, attests if 100% match

**Overwatch Audit:**

1. `overwatch_epoch_loop` in `subnet/server/loops.py` waits 35s, then audits each peer each epoch
2. `MockOverwatchVerifier.verify()` fetches work record, re-checks math, verifies TEE quote hash, optionally verifies OutputEnvelope HMAC
3. On `parity_mismatch`: `ChainOverwatchReporter.slash()` submits commit/reveal overwatch extrinsic to chain

**State Management:**
- Local state: RocksDB named maps (nmap) keyed by topic + `{epoch}:{peer_id}`
- Network state: GossipSub pub/sub for data dissemination, Kademlia DHT for peer discovery
- On-chain state: Substrate blockchain via Hypertensor RPC (subnet info, node registration, consensus data, staking)
- In-memory state: `CapacityTable` (frontier), `ProofOfStake` caches, `GossipReceiver` seen-sets

## Key Abstractions

**BaseNodeProtocol (Plugin Interface):**
- Purpose: Defines the work a miner does and how a validator queries it
- Location: `subnet/node/protocol.py`
- Pattern: Abstract base class with `register_handlers()`, `miner_loop(epoch)`, `validator_call(peer_id, epoch)`
- Example implementation: `MockNodeProtocol` in `subnet/node/mock.py`

**BaseNodeScoring (Plugin Interface):**
- Purpose: Transforms validator call results into 0.0-1.0 scores
- Location: `subnet/node/scoring.py`
- Pattern: Abstract base class with `score_peer(result, epoch)` and optional `score_all(results, epoch)`
- Example implementations: `MockNodeScoring` in `subnet/node/mock.py`, `GpuInferenceScoring` in `subnet/scoring/gpu_inference.py`

**BaseOverwatchVerifier (Plugin Interface):**
- Purpose: Independent audit of miner work for fraud detection
- Location: `subnet/node/overwatch.py`
- Pattern: Abstract base class with `verify(peer_id, epoch)` returning `OverwatchResult`
- Example implementation: `MockOverwatchVerifier` in `subnet/node/mock.py`

**TeeQuote (Data Schema):**
- Purpose: Normalized attestation quote that works across all TEE backends
- Location: `subnet/tee/quote.py`
- Pattern: Dataclass with identity binding (report_data = sha256(peer_id:epoch) + cert_pubkey_hash), JSON serialization, backend-agnostic

**TeeBackendBase (Strategy Pattern):**
- Purpose: Abstract interface for TEE hardware/mock backends
- Location: `subnet/tee/backends/base.py`
- Implementations: `MockBackend` (`subnet/tee/backends/mock.py`), `TdxBackend` (`subnet/tee/backends/tdx.py`), `SevSnpBackend` (`subnet/tee/backends/sev_snp.py`), `SevSnpAzureBackend` (`subnet/tee/backends/sev_snp_azure.py`)
- Factory: `get_backend()` in `subnet/tee/backends/__init__.py`

**RaTlsSession (Session Key):**
- Purpose: Ephemeral per-epoch session key for encryption (AES-GCM) and signing (HMAC-SHA256)
- Location: `subnet/tee/ratls/session.py`
- Pattern: HKDF-SHA256 key derivation from cert public key + peer_id + epoch

**OutputEnvelope / WorkEnvelope (Wire Protocol):**
- Purpose: Encrypted work items (validator-to-miner) and signed outputs (miner-to-validator)
- Location: `subnet/tee/ratls/envelope.py`
- Pattern: Request-ID binding for replay protection, AES-GCM encryption, HMAC-SHA256 signing

**Hypertensor (Blockchain Client):**
- Purpose: All on-chain interactions
- Location: `subnet/hypertensor/chain_functions.py`
- Pattern: Facade over Substrate RPC with retry logic (tenacity). `LocalMockHypertensor` in `subnet/hypertensor/mock/local_chain_functions.py` for testing.

**RocksDB (Local Storage):**
- Purpose: Named-map key-value store for gossip data, heartbeats, TEE quotes, work records
- Location: `subnet/utils/db/database.py`
- Pattern: Namespaced keys (`nmap:{topic}:{key}` -> value), prefix-scan for range queries

## Entry Points

**`subnet/cli/run_node.py` (run_node):**
- Location: `subnet/cli/run_node.py`
- Triggers: `python -m subnet.cli.run_node` or `run_node` CLI command
- Responsibilities: Parse args, load keys, connect to blockchain or create mock, initialize RocksDB, construct and run Server

**`subnet/api/main.py` (run_api):**
- Location: `subnet/api/main.py`
- Triggers: `python -m subnet.api.main` or `run_api` CLI command
- Responsibilities: Serve REST API for inspecting RocksDB state (peers, nmaps, health)

**`subnet/frontier/cli.py` (run_frontier):**
- Location: `subnet/frontier/cli.py`
- Triggers: `python -m subnet.frontier.cli` or `run_frontier` CLI command
- Responsibilities: Serve OpenAI-compatible inference gateway with capacity-based routing

**`subnet/server/server.py` (Server.run):**
- Location: `subnet/server/server.py`
- Triggers: Called by `run_node` after initialization
- Responsibilities: Create libp2p host, start DHT/GossipSub/PubSub, launch all background loops (heartbeat, TEE publish, miner, validator, overwatch, consensus, health)

## Error Handling

**Strategy:** Non-fatal error tolerance with logging. Most background loops catch all exceptions, log at WARNING, sleep, and retry.

**Patterns:**
- All epoch loops follow: `try: ... except trio.Cancelled: raise except Exception: logger.warning(...); await trio.sleep(10)` -- ensuring cancellation propagates but other errors do not crash the node
- TEE verification pipeline: Never raises; returns `VerificationResult` with `score=0.0` and `rejection_reason` string
- Chain interactions: `ChainScoreSubmitter.submit()` and `ChainOverwatchReporter.slash()` catch all exceptions, log, return None
- GossipReceiver handlers: Parse failures logged at WARNING, message silently dropped

## Cross-Cutting Concerns

**Logging:** Python `logging` module throughout. `JsonFormatter` available via `LOG_JSON=true` env var for structured logging in `subnet/utils/logging.py`. Operational loggers (`miner_epoch_loop`, `validator_scoring_loop`, `overwatch_epoch_loop`) can have JSON formatting independently.

**Validation:** PubSub topic validators (`SyncHeartbeatMsgValidator` in `subnet/utils/pubsub/pubsub_validation.py`) validate messages before delivery. GossipReceiver performs F-03 peer_id matching to reject spoofed messages.

**Authentication:** Proof-of-Stake transport wrapper (`subnet/utils/pos/pos_transport.py`) gates libp2p connections on on-chain stake verification. API layer uses API key auth (`subnet/api/auth/`). Frontier uses Bearer token auth.

**Concurrency:** Trio structured concurrency. All async code uses `trio.open_nursery()`, `trio.Event`, `trio.sleep()`. No asyncio. The codebase patches some libp2p internals for stability (`subnet/utils/patches.py`).

---

*Architecture analysis: 2026-03-24*
