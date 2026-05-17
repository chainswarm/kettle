# Codebase Structure

**Analysis Date:** 2026-03-24

## Directory Layout

```
subnet-template/
├── subnet/                    # Main Python package
│   ├── api/                   # REST API for inspecting node state
│   │   ├── auth/              # API key auth + rate limiting
│   │   ├── routers/v1/        # Versioned HTTP route handlers
│   │   ├── config.py          # API settings
│   │   ├── dependencies.py    # FastAPI lifespan (RocksDB init)
│   │   ├── main.py            # FastAPI app + uvicorn entry
│   │   └── models.py          # Pydantic response models
│   ├── cli/                   # CLI entry points
│   │   ├── crypto/            # keygen, keyview commands
│   │   ├── hypertensor/       # Blockchain registration commands
│   │   │   ├── keys/          # Key generation/view
│   │   │   ├── node/          # Node registration
│   │   │   └── subnet/        # Subnet registration + activation
│   │   └── run_node.py        # Primary node entry point
│   ├── consensus/             # On-chain consensus logic
│   │   ├── consensus.py       # Consensus main loop (validator election, attestation)
│   │   ├── chain_submitter.py # Score submission to chain
│   │   ├── chain_overwatch_reporter.py  # Overwatch slash extrinsics
│   │   └── utils.py           # Consensus data comparison helpers
│   ├── frontier/              # OpenAI-compatible inference gateway
│   │   ├── app.py             # FastAPI app factory
│   │   ├── capacity.py        # CapacityTable (routing state)
│   │   ├── cli.py             # Frontier CLI entry
│   │   └── messages.py        # NodeJoin/NodeLeave GossipSub messages
│   ├── hypertensor/           # Blockchain client (Substrate RPC)
│   │   ├── chain_functions.py # Hypertensor class (all RPC calls)
│   │   ├── chain_data.py      # On-chain data classes
│   │   ├── config.py          # Block timing constants
│   │   ├── helpers.py         # Formatting helpers
│   │   └── mock/              # LocalMockHypertensor for testing
│   │       ├── local_chain_functions.py
│   │       └── mock_db.py
│   ├── models/                # Model registry + assignment
│   │   ├── registry.py        # ModelRegistry, ModelConfig
│   │   └── assignment.py      # compute_assignment()
│   ├── node/                  # Protocol/scoring plugin interfaces
│   │   ├── protocol.py        # BaseNodeProtocol ABC
│   │   ├── scoring.py         # BaseNodeScoring ABC
│   │   ├── overwatch.py       # BaseOverwatchVerifier ABC
│   │   ├── mock.py            # MockNodeProtocol, MockNodeScoring, MockOverwatchVerifier
│   │   └── config.py          # NodeConfig
│   ├── protocols/             # libp2p protocol definitions
│   │   ├── mock_protocol.py   # Stream handler for mock protocol
│   │   └── pb/                # Protobuf definitions
│   ├── scoring/               # Concrete scoring implementations
│   │   └── gpu_inference.py   # GpuInferenceScoring
│   ├── server/                # libp2p server orchestration
│   │   ├── server.py          # Server class (main orchestrator)
│   │   ├── host.py            # create_host(), create_secure_transports()
│   │   ├── loops.py           # Background loops (miner, validator, overwatch, TEE)
│   │   └── health.py          # HTTP health endpoint
│   ├── tee/                   # Trusted Execution Environment
│   │   ├── backends/          # TEE backend implementations
│   │   │   ├── base.py        # TeeBackendBase ABC
│   │   │   ├── mock.py        # MockBackend (HMAC-based)
│   │   │   ├── tdx.py         # Intel TDX backend
│   │   │   ├── sev_snp.py     # AMD SEV-SNP (/dev/sev-guest)
│   │   │   ├── sev_snp_azure.py  # Azure vTPM SEV-SNP
│   │   │   └── __init__.py    # get_backend() factory
│   │   ├── ratls/             # Remote Attestation TLS
│   │   │   ├── cert.py        # X.509 cert generation + parsing
│   │   │   ├── client.py      # RaTlsClient (validator side)
│   │   │   ├── server.py      # RaTlsServer (miner side)
│   │   │   ├── session.py     # RaTlsSession (key derivation + crypto)
│   │   │   └── envelope.py    # WorkEnvelope + OutputEnvelope
│   │   ├── sealed/            # Sealed storage (TEE-protected persistence)
│   │   │   └── store.py       # SealedStore
│   │   ├── config.py          # TeeConfig (env var based)
│   │   ├── publisher.py       # TeePublisher (DHT quote publisher)
│   │   ├── verifier.py        # DcapVerifier (full verification pipeline)
│   │   ├── quote.py           # TeeQuote schema, TeeBackend/TcbStatus enums
│   │   └── gpu_attestation.py # GPU attestation helpers
│   ├── utils/                 # Cross-cutting utilities
│   │   ├── connections/       # Bootstrap node connection logic
│   │   ├── crypto/            # Key storage helpers
│   │   ├── db/                # RocksDB wrapper
│   │   │   └── database.py    # RocksDB class
│   │   ├── gossipsub/         # GossipSub message handling
│   │   │   ├── gossiper.py    # Gossiper (not currently used)
│   │   │   ├── gossip_receiver.py  # GossipReceiver (message dispatch + storage)
│   │   │   └── gossip_fallback.py
│   │   ├── host/              # libp2p host helpers
│   │   ├── hypertensor/       # SubnetInfoTracker versions
│   │   ├── pos/               # Proof-of-Stake transport
│   │   │   ├── proof_of_stake.py  # ProofOfStake checker
│   │   │   ├── pos_transport.py   # POS-wrapped secure transport
│   │   │   └── exceptions.py
│   │   ├── protocols/         # Protocol helpers (ping)
│   │   ├── pubsub/            # PubSub utilities
│   │   │   ├── heartbeat.py   # HeartbeatData + publish loop
│   │   │   ├── pubsub_validation.py  # Topic validators
│   │   │   └── custom_score_params.py
│   │   ├── addresses.py       # IP address helpers
│   │   ├── connection.py      # Connection maintenance loops
│   │   ├── dht.py             # DHT utilities
│   │   ├── logging.py         # JsonFormatter
│   │   └── patches.py         # libp2p stability patches
│   └── config.py              # Global config (GOSSIPSUB_PROTOCOL_ID)
├── tests/                     # Test suite
│   ├── api/                   # API tests
│   ├── consensus/             # Consensus tests
│   ├── frontier/              # Frontier gateway tests
│   ├── hypertensor/           # Blockchain client tests
│   ├── tee/                   # TEE tests (verifier, publisher, ratls, sealed, etc.)
│   ├── test_example.py        # Basic smoke test
│   ├── test_gossip_validation.py
│   ├── test_gpu_scoring.py
│   ├── test_heartbeat_v2.py
│   ├── test_mock_node.py
│   ├── test_model_assignment.py
│   ├── test_model_assignment_integration.py
│   ├── test_model_registry.py
│   ├── test_overwatch_integration.py
│   ├── test_scoring_integration.py
│   └── conftest.py            # Root conftest (in project root)
├── scripts/                   # Operational scripts
│   ├── check_peers.py
│   ├── check_scores.py
│   ├── check_slash.py
│   ├── register_node.py
│   ├── register_overwatch_node.py
│   ├── register_subnet.py
│   └── smoke_test_chain.py
├── examples/                  # Example implementations
│   └── gpu-inference/
│       └── protocol.py        # GPU inference protocol example
├── kata/                      # Kata container configs
├── docs/                      # Documentation
│   ├── superpowers/           # Design specs and plans
│   │   ├── plans/
│   │   └── specs/
│   └── testing/               # Testing documentation
├── docker-compose.yml         # Basic compose
├── docker-compose.chain.yml   # Full chain compose
├── docker-compose.chain-local.yml  # Local chain compose
├── docker-compose.peers.yml   # Multi-peer compose
├── docker-compose.tee-dev.yml # TEE development compose
├── docker-compose.tee-real.yml # TEE production compose
├── Dockerfile                 # Container image
├── gramine.manifest.template  # Gramine SGX manifest
├── Makefile                   # Build/test targets
├── pyproject.toml             # Project config (deps, tools, scripts)
├── conftest.py                # Root pytest conftest
├── tox.ini                    # Tox config
├── *.key                      # Pre-generated test key files (bootnode, alith, etc.)
└── .env.example               # Environment variable template
```

## Directory Purposes

**`subnet/node/`:**
- Purpose: THE extension point for subnet developers. Contains abstract base classes that define the protocol contract.
- Contains: `BaseNodeProtocol`, `BaseNodeScoring`, `BaseOverwatchVerifier` ABCs and the `MockNode*` reference implementations
- Key files: `subnet/node/protocol.py` (miner/validator contract), `subnet/node/scoring.py` (score computation), `subnet/node/mock.py` (working example)

**`subnet/server/`:**
- Purpose: Network server orchestration — creates libp2p host, wires all services, runs background loops
- Contains: Server class, host factory, epoch-driven loops
- Key files: `subnet/server/server.py` (Server class), `subnet/server/loops.py` (miner_epoch_loop, validator_scoring_loop, overwatch_epoch_loop, tee_publish_loop)

**`subnet/tee/`:**
- Purpose: TEE attestation system — quote generation, verification, RA-TLS key exchange, output signing
- Contains: Multi-backend quote system, RA-TLS protocol, DCAP verifier, sealed storage
- Key files: `subnet/tee/quote.py` (TeeQuote schema), `subnet/tee/verifier.py` (DcapVerifier), `subnet/tee/ratls/session.py` (session keys), `subnet/tee/ratls/envelope.py` (work/output envelopes)

**`subnet/consensus/`:**
- Purpose: On-chain consensus participation — score submission, attestation voting, overwatch slashing
- Contains: Consensus main loop, chain submitter, overwatch reporter
- Key files: `subnet/consensus/consensus.py` (Consensus class with `run_forever` + `run_consensus`)

**`subnet/frontier/`:**
- Purpose: OpenAI-compatible inference gateway for external API consumers
- Contains: FastAPI app, capacity-based routing table, GossipSub messages for cluster membership
- Key files: `subnet/frontier/app.py` (create_app factory), `subnet/frontier/capacity.py` (CapacityTable)

**`subnet/hypertensor/`:**
- Purpose: Blockchain (Substrate) RPC client for all on-chain interactions
- Contains: Full RPC wrapper, data classes, mock implementation
- Key files: `subnet/hypertensor/chain_functions.py` (Hypertensor class), `subnet/hypertensor/mock/local_chain_functions.py` (LocalMockHypertensor)

**`subnet/utils/db/`:**
- Purpose: Local key-value storage for gossip-received data
- Contains: RocksDB wrapper with simple, nested, and named-map storage
- Key files: `subnet/utils/db/database.py` (RocksDB class)

**`subnet/utils/gossipsub/`:**
- Purpose: Receiving and storing GossipSub messages from the mesh
- Contains: GossipReceiver (dispatches by topic, stores to DB), Gossiper (not currently used)
- Key files: `subnet/utils/gossipsub/gossip_receiver.py`

**`subnet/utils/pubsub/`:**
- Purpose: PubSub message types and validation
- Contains: HeartbeatData schema, heartbeat publish loop, topic validators
- Key files: `subnet/utils/pubsub/heartbeat.py`, `subnet/utils/pubsub/pubsub_validation.py`

**`subnet/utils/pos/`:**
- Purpose: Proof-of-Stake transport layer — gates libp2p connections on on-chain stake
- Key files: `subnet/utils/pos/proof_of_stake.py`, `subnet/utils/pos/pos_transport.py`

**`subnet/models/`:**
- Purpose: Model registry for multi-model inference clusters. Ratio-based assignment.
- Key files: `subnet/models/registry.py` (ModelRegistry, ModelConfig), `subnet/models/assignment.py`

**`subnet/scoring/`:**
- Purpose: Concrete scoring implementations beyond the mock
- Key files: `subnet/scoring/gpu_inference.py` (GpuInferenceScoring)

## Key File Locations

**Entry Points:**
- `subnet/cli/run_node.py`: Primary node startup (CLI args -> Server -> trio.run)
- `subnet/api/main.py`: REST API server (FastAPI + uvicorn)
- `subnet/frontier/cli.py`: Inference gateway (FastAPI + uvicorn)

**Configuration:**
- `subnet/config.py`: Global config (GossipSub protocol ID)
- `subnet/tee/config.py`: TEE configuration from env vars (backend, measurements, TCB policy)
- `subnet/hypertensor/config.py`: Block timing constants
- `subnet/api/config.py`: API settings (port, CORS, auth)
- `subnet/node/config.py`: Node configuration
- `pyproject.toml`: Dependencies, CLI scripts, tool config

**Core Logic:**
- `subnet/server/server.py`: Server orchestrator (creates host, starts all services)
- `subnet/server/loops.py`: Four epoch-driven background loops
- `subnet/node/protocol.py`: BaseNodeProtocol ABC (the protocol contract)
- `subnet/node/scoring.py`: BaseNodeScoring ABC (the scoring contract)
- `subnet/node/mock.py`: Reference implementations of Protocol, Scoring, Overwatch
- `subnet/consensus/consensus.py`: Consensus loop (validator election + attestation)
- `subnet/tee/verifier.py`: DcapVerifier (7-step verification pipeline)
- `subnet/tee/ratls/session.py`: HKDF key derivation, AES-GCM, HMAC-SHA256
- `subnet/tee/ratls/envelope.py`: WorkEnvelope + OutputEnvelope wire protocol

**Testing:**
- `tests/`: Test suite (mirrored structure to `subnet/`)
- `conftest.py`: Root conftest with shared fixtures

## Naming Conventions

**Files:**
- Snake_case for all Python files: `chain_functions.py`, `gossip_receiver.py`
- `__init__.py` in every package (some re-export, some empty)
- Protobuf generated files in `pb/` directories: `mock_protocol_pb2.py`

**Directories:**
- Snake_case for all directories: `gossipsub/`, `proof_of_stake/` (as `pos/`), `sev_snp`
- Versioned trackers: `subnet_info_tracker_v3.py`, `subnet_info_tracker_v4.py`
- Versioned routers: `routers/v1/`

**Classes:**
- PascalCase: `BaseNodeProtocol`, `MockNodeScoring`, `DcapVerifier`, `CapacityTable`
- ABCs prefixed with `Base`: `BaseNodeProtocol`, `BaseNodeScoring`, `BaseOverwatchVerifier`, `TeeBackendBase`

**Constants:**
- UPPER_SNAKE_CASE: `TEE_QUOTE_TOPIC`, `HEARTBEAT_TOPIC`, `GOSSIPSUB_PROTOCOL_ID`
- Private constants with underscore prefix: `_WORK_TOPIC`, `_MOCK_KEY`, `_HKDF_SALT`

## Where to Add New Code

**New Subnet Protocol (custom work + scoring):**
- Create a new file at `subnet/node/my_protocol.py` implementing `BaseNodeProtocol`
- Create scoring at `subnet/scoring/my_scoring.py` implementing `BaseNodeScoring`
- Create overwatch at `subnet/node/my_overwatch.py` implementing `BaseOverwatchVerifier`
- Wire into `subnet/server/server.py` `_start_node_loops()` method (replace `MockNodeProtocol`/`MockNodeScoring`/`MockOverwatchVerifier`)
- Tests go in `tests/` mirroring structure: `tests/test_my_protocol.py`

**New TEE Backend:**
- Add `subnet/tee/backends/my_backend.py` implementing `TeeBackendBase`
- Register in factory: `subnet/tee/backends/__init__.py` `get_backend()`
- Add corresponding `TeeBackend` enum value to `subnet/tee/quote.py`
- Add chain verification method to `subnet/tee/verifier.py` `_verify_chain()`
- Tests: `tests/tee/test_my_backend.py`

**New GossipSub Topic:**
- Define topic constant in the relevant module
- Add handler method to `subnet/utils/gossipsub/gossip_receiver.py`
- Add topic to the topics list in `subnet/server/server.py` (GossipReceiver constructor)
- Add corresponding seen-set for deduplication

**New API Endpoint:**
- Add route handler in `subnet/api/routers/v1/` (new file or extend existing)
- Register in `subnet/api/routers/v1/__init__.py`
- Tests: `tests/api/`

**New Frontier Feature:**
- Extend `subnet/frontier/app.py` with new endpoints
- Add routing logic to `subnet/frontier/capacity.py`
- Tests: `tests/frontier/`

**New Consensus Logic:**
- Extend `subnet/consensus/consensus.py` `get_scores()` or `run_consensus()`
- Chain interaction helpers go in `subnet/consensus/chain_submitter.py` or new file

**New Utility:**
- Place in `subnet/utils/` under appropriate subdirectory
- If cross-cutting, add to `subnet/utils/` directly
- Tests: `tests/` at top level or in matching subdirectory

## Special Directories

**`subnet/hypertensor/mock/`:**
- Purpose: Local mock blockchain for testing without RPC
- Generated: No
- Committed: Yes
- Key files: `local_chain_functions.py` (LocalMockHypertensor), `mock_db.py` (shared in-memory DB)

**`subnet/utils/gossipsub/pb/` and `subnet/protocols/pb/`:**
- Purpose: Protobuf generated code
- Generated: Yes (from .proto files)
- Committed: Yes

**`kata/`:**
- Purpose: Kata container configuration for CVM-based TEE deployments
- Generated: No
- Committed: Yes

**`.gsd/`:**
- Purpose: GSD project management state (milestones, slices, tasks)
- Generated: Yes (by GSD tooling)
- Committed: Yes

**`*.key` files (root):**
- Purpose: Pre-generated Ed25519 private keys for local multi-node testing
- Generated: No (static test fixtures)
- Committed: Yes (not secrets -- test-only keys)

---

*Structure analysis: 2026-03-24*
