# Technology Stack

**Analysis Date:** 2026-03-24

## Languages

**Primary:**
- Python >=3.10, <4.0 - All application code (`subnet/`, `tests/`, `scripts/`)
- Protobuf (proto2) - Wire protocol definitions (`subnet/protocols/pb/mock_protocol.proto`)

**Secondary:**
- Bash - Build scripts, `run_peer.sh`, `scripts/build-gramine.sh`
- TOML - Configuration (`pyproject.toml`, Gramine manifest template)

## Runtime

**Environment:**
- Python 3.11 (Docker image: `python:3.11-slim`)
- Supports 3.10, 3.11, 3.12, 3.13 (tested via tox)
- Trio async runtime (NOT asyncio) - all async code uses `trio`, not `asyncio`

**Package Manager:**
- pip (with setuptools>=42 build backend)
- Lockfile: **missing** - no `requirements.txt` or `pip-compile` lockfile; dependencies pinned via `pyproject.toml` constraints

## Frameworks

**Core:**
- FastAPI >=0.115.0 - Two distinct HTTP applications:
  1. RocksDB API server (`subnet/api/main.py`) - node data query API
  2. Frontier inference gateway (`subnet/frontier/app.py`) - OpenAI-compatible chat completions router
- Pydantic >=2.0.0 - Data validation and settings
- pydantic-settings >=2.0.0 - Environment-based configuration (`subnet/api/config.py`, `subnet/tee/config.py`)
- uvicorn[standard] >=0.32.0 - ASGI server

**Networking:**
- libp2p (py-libp2p) @ git commit `c4abd7c` - P2P networking, GossipSub, Kademlia DHT, pubsub
- multiaddr ==0.0.11 - Multiaddress parsing for libp2p
- pymultihash ==0.8.2 - Content addressing

**Async:**
- trio - Primary async framework (used by libp2p and consensus loops)
- NOT asyncio - libp2p Python uses trio exclusively

**Testing:**
- pytest >=7.0.0 - Test runner
- pytest-asyncio >=0.21.0 - Async test support
- pytest-trio >=0.5.2 - Trio-specific test support
- pytest-xdist >=2.4.0 - Parallel test execution (`-n auto`)
- pytest-mock >=3.15.1 - Mocking utilities
- pytest-timeout >=2.4.0 - Test timeout enforcement
- pytest-rerunfailures >=12.0 - Flaky test retries
- factory-boy >=2.12.0,<3.0.0 - Test factories
- tox >=4.0.0 - Multi-environment test orchestration (`tox.ini`)

**Build/Dev:**
- setuptools >=42 + wheel - Build backend
- ruff >=0.11.10 - Linting and formatting (replaces black/isort/flake8)
- mypy >=1.15.0 - Static type checking
- pyrefly >=0.17.1,<0.18.0 - Additional type checking
- pre-commit >=3.4.0 - Git hooks
- protoc (protobuf compiler) - Protobuf code generation via `Makefile`
- bump_my_version >=0.19.0 - Version management
- sphinx >=6.0.0 + sphinx_rtd_theme - Documentation generation

## Key Dependencies

**Critical:**
- `libp2p` (git pin: `c4abd7c19630c5ff25a89d263b22beb2183a64ae`) - Entire P2P networking layer: host creation, GossipSub pubsub, Kademlia DHT, peer discovery, stream multiplexing. Pinned to specific commit from `github.com/libp2p/py-libp2p`
- `substrate-interface` (git pin: `hypertensor` branch of `github.com/hayotensor/py-polkadot-sdk`) - Substrate/Polkadot blockchain client for Hypertensor chain. Used in `subnet/hypertensor/chain_functions.py` for extrinsic signing, RPC queries, keypair management
- `rocksdict` >=0.3.27 - Python bindings for RocksDB; used as the primary local database via `subnet/utils/db/database.py`
- `cryptography` (transitive, used directly) - TLS cert generation (`subnet/tee/ratls/cert.py`), AES-GCM sealed storage (`subnet/tee/sealed/store.py`), ECDSA keys, HKDF key derivation
- `tenacity` >=8.2.3 - Retry logic for blockchain RPC calls (`subnet/hypertensor/chain_functions.py`)

**Infrastructure:**
- `slowapi` >=0.1.9 - Rate limiting for FastAPI endpoints (`subnet/api/auth/ratelimit.py`)
- `python-dotenv` >=1.0.1 - `.env` file loading
- `tabulate` >=0.9.0 - CLI table formatting
- `httpx` >=0.27.0 (optional, `[gpu]` extra) - HTTP client for NIM inference API calls
- `scalecodec` (transitive via substrate-interface) - Substrate SCALE codec encoding/decoding

**Optional/Hardware:**
- `nv-attestation-sdk` (runtime import, not in deps) - NVIDIA GPU attestation for H100/H200/B200 (`subnet/tee/gpu_attestation.py`)
- `tpm2-tools` (system package) - Azure vTPM access for SEV-SNP attestation (`subnet/tee/backends/sev_snp_azure.py`)

## Configuration

**Environment:**
- `.env` files loaded via `python-dotenv` and `pydantic-settings`
- `.env.example` provides template with: `LOCAL_RPC`, `DEV_RPC`, `LIVE_RPC`, `PHRASE`
- API config via `API_` prefix env vars (e.g., `API_DB_PATH`, `API_PORT`, `API_HOST`)
- TEE config via direct env vars: `MOCK_TEE`, `TEE_BACKEND`, `EXPECTED_MEASUREMENT`, `MIN_TEE_SCORE`, `TCB_POLICY`, `PCCS_URL`, `MOCK_TEE_KEY`
- Chain config: `DEV_RPC` (WebSocket URL), `PHRASE` (mnemonic), `TENSOR_PRIVATE_KEY`
- Node identity: `OVERWATCH_NODE_ID`, `TAMPER_RATE`
- Mock chain: `MOCK_CHAIN_DB_PATH`

**Build:**
- `pyproject.toml` - Package metadata, dependencies, tool configuration (ruff, mypy, pytest, pyrefly)
- `tox.ini` - Multi-python test matrix (py310-py313), lint environment
- `codecov.yaml` - Coverage targets (80% project, 80% patch)
- `Makefile` - Development commands (`make test`, `make lint`, `make fix`, `make protobufs`)
- `gramine.manifest.template` - Gramine SGX enclave manifest for production TEE deployment

**Docker Compose Configurations (6 variants):**
- `docker-compose.yml` - Standalone RocksDB API server
- `docker-compose.peers.yml` - 5-node P2P network (bootnode + 4 peers, no blockchain)
- `docker-compose.tee-dev.yml` - TEE dev stack with mock TEE (bootnode + validator + 2 miners + overwatch)
- `docker-compose.tee-real.yml` - Real SEV-SNP attestation (requires Azure CVM with `/dev/tpmrm0`)
- `docker-compose.chain-local.yml` - Full stack with local Hypertensor dev chain node
- `docker-compose.chain.yml` - Staging stack connected to Hypertensor testnet

## Platform Requirements

**Development:**
- Python 3.10+ (3.11 recommended, matches Docker image)
- pip with git support (two git-pinned dependencies)
- protoc (Protocol Buffers compiler) for regenerating protobuf files
- Docker + Docker Compose for multi-node testing

**Production (TEE):**
- Azure Confidential VM (DCasv5/DCadsv5) for SEV-SNP attestation
- `/dev/tpmrm0` device access for vTPM-based attestation
- `tpm2-tools` system package installed
- OR Intel TDX-capable host with `/dev/tdx_guest` + `libtdx-attest`
- OR Gramine-SGX with DCAP quote generation

**Production (GPU Inference):**
- Azure NCCadsH100v5 (SEV-SNP + H100 confidential GPU)
- NVIDIA Container Toolkit
- NGC API key for pulling NIM container images
- NVIDIA NIM inference server (`nvcr.io/nim/meta/llama-3.2-1b-instruct:latest`)

**CI:**
- GitHub Actions (`ubuntu-latest`, Python 3.11)
- Three-layer CI: pytest -> Docker Compose config validation -> chain smoke test (informational)

## CLI Entry Points

Defined in `pyproject.toml` `[project.scripts]`:
- `run_node` -> `subnet.cli.run_node:main` - Main node entry point
- `run_bootnode` -> `subnet.cli.run_bootnode:main`
- `run_api` -> `subnet.api.main:cli` - RocksDB API server
- `run_api_keys` -> `subnet.api.auth.cli:main` - API key management
- `run_frontier` -> `subnet.frontier.cli:main` - Frontier inference gateway
- `keygen` -> `subnet.cli.crypto.keygen:main` - Key generation
- `keyview` -> `subnet.cli.crypto.keyview:main` - Key inspection
- `register_subnet` -> `subnet.cli.hypertensor.subnet.register:main`
- `activate_subnet` -> `subnet.cli.hypertensor.subnet.activate:main`
- `register_node` -> `subnet.cli.hypertensor.node.register:main`

---

*Stack analysis: 2026-03-24*
