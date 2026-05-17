# External Integrations

**Analysis Date:** 2026-03-24

## APIs & External Services

**NVIDIA NIM (GPU Inference):**
- Purpose: LLM inference server (OpenAI-compatible API)
- Container image: `nvcr.io/nim/meta/llama-3.2-1b-instruct:latest`
- Client: `httpx` (optional `[gpu]` extra)
- Configuration:
  - `NIM_BASE_URL` env var (e.g., `http://nim:8000`)
  - `NIM_MODEL` env var (e.g., `meta/llama-3.2-1b-instruct`)
  - `NGC_API_KEY` for container registry auth
- Health endpoint: `GET /v1/health/ready`
- Inference endpoint: `POST /v1/chat/completions` (OpenAI-compatible)
- Used in: `examples/gpu-inference/docker-compose.gpu-inference.yml`, referenced in `subnet/scoring/gpu_inference.py`

**NVIDIA GPU Attestation SDK:**
- Purpose: Hardware attestation of NVIDIA GPUs (H100/H200/B200)
- SDK: `nv-attestation-sdk` (runtime import, not in `pyproject.toml` dependencies)
- Client code: `subnet/tee/gpu_attestation.py`
- Verification: Local device attestation via `nv_attestation.Devices.GPU`
- Result: JWT-like token with GPU UUID and GPU name claims
- Mock path: `verify_gpu_mock()` returns deterministic passing result for dev/CI

**Intel PCCS (Provisioning Certification Caching Service):**
- Purpose: DCAP collateral retrieval for TDX/SGX quote verification
- Configuration: `PCCS_URL` env var (empty = use Intel's public PCS)
- Used in: `subnet/tee/config.py` -> `TeeConfig.pccs_url`
- Required only for real TDX hardware verification

## Blockchain / Substrate

**Hypertensor Chain (Primary Integration):**
- Purpose: Decentralized consensus, node registration, score submission, slashing
- Protocol: Substrate/Polkadot JSON-RPC over WebSocket
- SDK: `substrate-interface` (custom fork at `github.com/hayotensor/py-polkadot-sdk`, branch `hypertensor`)
- Client: `subnet/hypertensor/chain_functions.py` -> `Hypertensor` class
- Connection env vars:
  - `DEV_RPC` - WebSocket URL (e.g., `ws://127.0.0.1:9944` or `wss://rpc.hypertensor.app:443`)
  - `LOCAL_RPC` - Local dev chain URL
  - `LIVE_RPC` - Production chain URL
  - `PHRASE` - Mnemonic for signing extrinsics
  - `TENSOR_PRIVATE_KEY` - Alternative to mnemonic
- Key operations:
  - `propose_attestation()` - Validator submits consensus scores
  - `attest()` - Miner attests to validator proposal
  - Overwatch commit/reveal for slashing (`subnet/consensus/chain_overwatch_reporter.py`)
  - Subnet registration and activation (`scripts/register_subnet.py`)
  - Node registration (`scripts/register_node.py`)
  - Overwatch node registration (`scripts/register_overwatch_node.py`)
- Block time: 6 seconds (`subnet/hypertensor/config.py` -> `BLOCK_SECS = 6`)
- Epoch length: 20 blocks / 120 seconds (`EPOCH_LENGTH = 20`)
- Retry strategy: `tenacity` with `wait_fixed` for WebSocket disconnections
- Mock: `subnet/hypertensor/mock/local_chain_functions.py` -> `LocalMockHypertensor` (SQLite-backed mock chain via `MockDatabase`)

**Hypertensor Testnet:**
- WebSocket RPC: `wss://rpc.hypertensor.app:443`
- Used via: `docker-compose.chain.yml` with `CHAIN_ENDPOINT` env var

**Hypertensor Local Dev Chain:**
- Docker image: `hypertensor-node:dev` (build from `github.com/hypertensor-blockchain/hypertensor-blockchain`)
- Ports: 9944 (WebSocket RPC), 9933 (HTTP RPC), 30333 (P2P), 9615 (Prometheus metrics)
- Pre-funded accounts: Alice, Bob (10M HTSR each)
- Used via: `docker-compose.chain-local.yml`

## Data Storage

**RocksDB (Primary Database):**
- Wrapper: `subnet/utils/db/database.py` -> `RocksDB` class
- Library: `rocksdict` >=0.3.27 (Python bindings for Facebook RocksDB)
- Storage patterns:
  - Simple key:value (`db.set(key, value)`)
  - Nested key storage (`db.set_nested(k1, k2, value)` -> stored as `k1:k2`)
  - Named maps (`db.nmap_set(nmap, key, value)` -> stored as `nmap:nmap_name:key`)
- Used for:
  - TEE quote storage (DHT data, topic `tee_quote`)
  - RA-TLS certificate storage (topic `ratls_cert`)
  - Heartbeat data
  - Sealed storage (nmap `sealed`)
  - API query data (read-only mode for API server)
- Configuration: `API_DB_PATH` env var (default: `/tmp/bootstrap`)
- Docker volumes mount RocksDB directories per-node

**RocksDB Auth Database (API Keys):**
- Separate RocksDB instance for API key management
- Client: `subnet/api/auth/manager.py` -> `AuthManager`
- Configuration: `API_AUTH_DB_PATH` env var (default: `/tmp/auth_db`)
- Stores SHA-256 hashed API keys with metadata (owner, QPM limit, active status)

**Sealed Storage (Encrypted at rest):**
- Implementation: `subnet/tee/sealed/store.py` -> `SealedStore`
- Encryption: AES-256-GCM with HKDF-SHA256 derived key
- Key derivation: `HKDF(salt="hypertensor-sealed-storage-v1", ikm=sha256(measurement))`
- Backend: RocksDB nmap `sealed`
- Purpose: Persists overwatch salt, evidence, and secrets bound to enclave measurement
- Security: Different enclave binary = different measurement = different key = data inaccessible

**Mock Chain Database:**
- Implementation: `subnet/hypertensor/mock/mock_db.py` -> `MockDatabase`
- Purpose: SQLite-backed mock Substrate chain for local/dev testing
- Configuration: `MOCK_CHAIN_DB_PATH` env var (shared volume across nodes in Docker)

**File Storage:**
- Local filesystem only (no cloud storage)
- Key files stored on disk (`.key` files for node identity)

**Caching:**
- In-memory only via Python dicts
- `subnet/frontier/capacity.py` -> `CapacityTable` (thread-safe in-memory routing table)
- No external cache (Redis, Memcached, etc.)

## P2P Networking (libp2p)

**GossipSub (Pubsub):**
- Protocol: `/meshsub/2.0.0` (`subnet/config.py`)
- Topics:
  - `heartbeat` - Node liveness and status (`subnet/utils/pubsub/heartbeat.py`)
  - `tee_quote` - TEE attestation quote exchange (`subnet/tee/quote.py`)
  - `ratls_cert` - RA-TLS certificate distribution
  - Work topic (mock protocol) for task distribution
  - `node_join` / `node_leave` events (`subnet/frontier/messages.py`)
- Parameters (`subnet/utils/gossipsub/gossiper.py`):
  - D=6 (mesh target), D_low=4, D_high=12
  - Fanout TTL: 60s, Gossip window: 3, History: 5
  - Heartbeat interval: 1s

**Kademlia DHT:**
- Used for peer discovery and quote storage
- Client: `libp2p.kad_dht.kad_dht.KadDHT` (`subnet/server/server.py`)
- DHT key format: `{epoch}:{peer_id}` (`subnet/tee/quote.py` -> `dht_key()`)

**Peer Discovery:**
- Bootstrap nodes via multiaddr addresses (e.g., `/dns4/bootnode/tcp/38960/p2p/12D3KooW...`)
- Random walk discovery (`subnet/server/server.py` -> `demonstrate_random_walk_discovery`)
- Proof of Stake validation (`subnet/utils/pos/proof_of_stake.py`)
- Default P2P port: 38960 (bootnode), 38961-38965 (nodes)

## TEE (Trusted Execution Environment)

**Backend Abstraction:**
- Base: `subnet/tee/backends/base.py` -> `TeeBackendBase` (ABC)
- Mock: `subnet/tee/backends/mock.py` -> `MockBackend` (HMAC-SHA256, score=0.5)
- Intel TDX: `subnet/tee/backends/tdx.py` -> `TdxBackend` (requires `/dev/tdx_guest`)
- AMD SEV-SNP: `subnet/tee/backends/sev_snp.py` -> `SevSnpBackend`
- Azure SEV-SNP: `subnet/tee/backends/sev_snp_azure.py` -> `SevSnpAzureBackend` (vTPM at NV index `0x01400001`)

**RA-TLS (Remote Attestation TLS):**
- Certificate generation: `subnet/tee/ratls/cert.py` -> `generate_ratls_cert()`
- Server: `subnet/tee/ratls/server.py` -> `RaTlsServer`
- Client: `subnet/tee/ratls/client.py`
- Session management: `subnet/tee/ratls/session.py` -> `RaTlsSession`
- Custom X.509 extension OID: `1.3.6.1.4.1.99999.1` (TEE_QUOTE_OID)
- Cert key: Ephemeral ECDSA P-256, renewed each epoch

**Gramine SGX:**
- Manifest: `gramine.manifest.template`
- Enclave size: 512 MB
- Max threads: 16
- Attestation: DCAP (`sgx.remote_attestation = "dcap"`)
- Build script: `scripts/build-gramine.sh`

**Azure vTPM (SEV-SNP):**
- Tool: `tpm2_nvread` (system command via subprocess)
- NV Index: `0x01400001`
- VM type: DCasv5/DCadsv5 Azure Confidential VMs
- Device: `/dev/tpmrm0`

## Authentication & Identity

**Node Identity:**
- libp2p Ed25519 key pairs stored as `.key` files
- Peer ID derived from public key (libp2p standard)
- Key generation: `keygen` CLI command (`subnet/cli/crypto/keygen.py`)

**Blockchain Identity:**
- Substrate keypairs (SR25519) via mnemonic phrase (`PHRASE` env var)
- Alternative: raw private key (`TENSOR_PRIVATE_KEY` env var)
- Used for signing extrinsics (propose_attestation, attest, commit/reveal)

**API Authentication:**
- API keys with `st_` prefix (generated via `run_api_keys` CLI)
- Keys stored SHA-256 hashed in RocksDB
- Per-key rate limiting (QPM - queries per minute)
- Rate limiter: `slowapi` (`subnet/api/auth/ratelimit.py`)
- Global auth dependency on all API routes (`subnet/api/main.py`)

**Frontier Auth:**
- Bearer token authentication (`subnet/frontier/app.py` -> `require_auth`)
- Optional: `None` = auth disabled

## Monitoring & Observability

**Error Tracking:**
- None (no Sentry, Datadog, etc.)

**Logs:**
- Python `logging` module throughout
- Format: `%(asctime)s - %(name)s - %(levelname)s - %(message)s`
- JSON logging available via `LOG_JSON=true` env var (Docker Compose configs)
- Named loggers per module (e.g., `consensus/1.0.0`, `local-chain-functions`, `proof-of-stake`)

**Health Checks:**
- API health: `GET /api/v1.0/health` (`subnet/api/routers/v1/health.py`)
- Node health: `GET /health` on port 8080 (`subnet/server/health.py`)
- Docker healthcheck via `curl` or Python urllib
- Frontier health: `GET /health` (`subnet/frontier/app.py`)

**Metrics:**
- Prometheus endpoint commented out in `docker-compose.yml` (not active)
- Hypertensor dev chain exposes Prometheus at `:9615`
- API metrics redirect: `/metrics` -> `/api/v1.0/health/metrics`
- Codecov for test coverage (target: 80%, `codecov.yaml`)

## CI/CD & Deployment

**Hosting:**
- Docker containers (multi-stage build, `python:3.11-slim`)
- Azure Confidential VMs for production TEE
- Azure NCCadsH100v5 for GPU inference

**CI Pipeline:**
- GitHub Actions (`.github/workflows/ci.yml`)
- Triggers: push to `main`, PRs to `main`
- Runner: `ubuntu-latest`
- Steps:
  1. pytest (`tests/` excluding `tests/hypertensor/`)
  2. Docker Compose config validation
  3. Chain smoke test (informational, `continue-on-error: true`)

**Container Registry:**
- `nvcr.io` (NVIDIA NGC) for NIM inference images
- No published application container images (build locally)

## Webhooks & Callbacks

**Incoming:**
- None (no webhook endpoints)

**Outgoing:**
- Substrate extrinsic callbacks (block finalization events via WebSocket subscription)
- GossipSub message handlers (pubsub topic subscriptions)

## Environment Configuration

**Required env vars (production):**
- `DEV_RPC` or `CHAIN_ENDPOINT` - Hypertensor chain WebSocket URL
- `PHRASE` or `TENSOR_PRIVATE_KEY` - Blockchain signing key
- `SUBNET_ID` - Subnet identifier
- `TEE_BACKEND` - `sev-snp` or `tdx` for real hardware
- `EXPECTED_MEASUREMENT` - Enclave measurement hash to enforce

**Required env vars (GPU inference):**
- `NGC_API_KEY` - NVIDIA NGC container registry auth
- `NIM_BASE_URL` - NIM inference server URL
- `NIM_MODEL` - Model identifier

**Required env vars (overwatch node):**
- `OVERWATCH_NODE_ID` - On-chain overwatch node ID
- `OVERWATCH_PHRASE` - Overwatch node signing mnemonic

**Optional env vars:**
- `MOCK_TEE` - `true`/`false` (default: `true`)
- `MIN_TEE_SCORE` - Minimum TEE score threshold (default: `0.0`)
- `TCB_POLICY` - `strict`/`permissive` (default: `strict`)
- `PCCS_URL` - Intel PCCS URL for DCAP verification
- `MOCK_TEE_KEY` - Hex HMAC key for mock TEE (default: dev key)
- `MOCK_CHAIN_DB_PATH` - Path for mock chain SQLite database
- `TAMPER_RATE` - Consensus tamper rate for testing
- `LOG_JSON` - Enable JSON-structured logging
- `API_DB_PATH`, `API_PORT`, `API_HOST` - API server config
- `API_DB_READ_ONLY` - Read-only mode for API
- `API_AUTH_DB_PATH`, `API_ENABLE_AUTH`, `API_DEFAULT_QPM` - API auth config

**Secrets location:**
- `.env` files (gitignored)
- `.key` files for node identity (committed for dev nodes: `bootnode.key`, `alith.key`, etc.)
- Docker Compose environment variables with `:?` validation syntax

---

*Integration audit: 2026-03-24*
