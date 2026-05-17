# TEE Subnet Template

The first production-grade subnet template with native hardware attestation. Fork this repo, replace 3 files, and deploy a subnet where every miner proves it runs your exact code on real TEE hardware — no trust required.

Built for [Hypertensor](https://hypertensor.org). Production deployment uses **Gramine/SGX** — the only runtime where the hardware seals enclave memory against the operator. CVM backends (SEV-SNP, TDX) are available for development and testing.

## "But who owns the box?"

> *"Nobody can fully explain to me that if I send a message to an LLM, the operator of that LLM cannot see or alter your message. 'We are using TEE', great — who's the owner of that box and how can that owner guarantee that he did not tamper with that box?"*

This is the right question. Here is how it actually works:

**You don't trust the operator. You trust the silicon.**

Every Intel/AMD CPU has a private key **burned into the silicon** during manufacturing. This key cannot be extracted — not by the operator, not by the cloud provider, not by anyone with physical access. When code runs inside a TEE enclave, the CPU:

1. **Measures** the code — computes a SHA-384 hash of exactly what was loaded
2. **Seals** the memory — encrypts it so the operator cannot read or modify it
3. **Signs an attestation report** — using the silicon-fused key, proving: *"this exact code is running, unmodified, on genuine hardware"*

The attestation report chains back to Intel/AMD's root certificate (published publicly). Anyone can verify it. The operator cannot forge it — they don't have the silicon key.

```
What the operator controls          What the hardware guarantees
─────────────────────────           ──────────────────────────────
The physical machine        BUT     Cannot read enclave memory (encrypted by CPU)
The network, the OS         BUT     Cannot modify running code (measurement would change)
The power cable             BUT     Cannot forge attestation (signed by silicon key)
```

**In this subnet**, every miner runs inside a TEE. Every epoch, validators verify the attestation report — not by trusting the miner, but by checking the hardware signature against Intel/AMD's root CA. If the operator tampers with the code, the measurement changes and the miner scores 0.0. If the operator tries to forge a report, the signature fails. The operator's only options are: run the genuine code honestly, or score zero.

### "But the message still travels over the operator's network"

The operator controls the network. They could intercept messages before they reach the enclave. This is solved by **RA-TLS** — the TLS certificate is generated **inside** the enclave, and the cert's public key hash is burned into the hardware-signed attestation report:

```
Validator                                Miner's TEE Enclave
    │                                           │
    │  1. Fetch attestation report              │
    │◄──────────────────────────────────────────│  signed by silicon key
    │                                           │
    │  2. Check: sha256(TLS cert pubkey)        │
    │     matches what's in the report          │  hardware proves this cert
    │     → YES, this cert came from            │  was generated inside the
    │       inside the enclave                  │  enclave, not by the operator
    │                                           │
    │  3. TLS handshake using THAT cert         │
    │──────────────────────────────────────────►│  encrypted end-to-end
    │                                           │
    │  4. Send work / receive results           │
    │◄─────────────────────────────────────────►│  operator sees only ciphertext
```

The operator **cannot** man-in-the-middle this connection because:
- The TLS private key was generated **inside** the enclave — the operator never sees it
- The public key hash is in the **hardware-signed** attestation — the operator cannot swap in a different cert
- If the operator presents their own cert, `sha256(their_pubkey) != report_data` and the connection is rejected

The TLS handshake **is** the attestation. No separate quote exchange, no trust-me-bro — one handshake proves the code is genuine AND encrypts the channel to it.

For the full threat model and 13 tested attack vectors, see [`docs/04-anti-cheat.md`](docs/04-anti-cheat.md).

## Verified on real hardware

Every security claim is tested on an Azure DCasv5 SEV-SNP VM. These are not theoretical — they are real test results:

| Attack | Blocked | How |
|--------|---------|-----|
| Identity theft (Sybil) | YES | `report_data = sha256(peer_id:epoch)` burned into hardware |
| Quote replay | YES | Nonce must match current epoch |
| Fabricated quote | YES | Chain verification requires real attestation report |
| Wrong binary (modified Docker) | YES | `EXPECTED_MEASUREMENT` rejects wrong SHA-384 |
| Output forgery | YES | HMAC-SHA256 with enclave-derived session key |
| External keypair cert | YES | Cert pubkey hash bound in report_data |
| Debug mode enclave | YES | `debug_mode=True` always score=0.0 |
| DHT record overwrite | YES | GossipSub validates sender matches content peer_id |

Full details: [`docs/testing/attack-vectors.md`](docs/testing/attack-vectors.md) | Production CVM results: [`docs/testing/production-cvm-testing.md`](docs/testing/production-cvm-testing.md)

## Why TEE, not just cryptographic proofs

Bittensor's top subnets use three approaches to verify miners. Each has structural gaps that TEE eliminates:

| | SN9 IOTA | SN81 GRAIL | SN75 hippius | **Hypertensor TEE** |
|---|----------|------------|--------------|---------------------|
| **Verification** | Centralised orchestrator computes scores | PRF-based cryptographic proofs per token | On-chain pallet scoring | Hardware attestation (DCAP) |
| **TEE support** | In codebase, not enforced | None | None | Native, enforced |
| **What it proves** | "Orchestrator says you worked" | "These tokens came from this model" | "CIDs are pinned" | **"This exact binary ran in isolated hardware"** |
| **Operator can read secrets** | Yes | Yes | Yes | **No** (hardware isolation) |
| **Operator can run different code** | Yes | Partially blocked (model hash) | Yes | **No** (measurement binding) |
| **Single point of trust** | Orchestrator API | None (good) | Chain pallet | **None** |
| **Validator collusion cost** | Free (no slash) | Free (no slash) | N/A | 3.125% stake slashed + 66% attestation |
| **Score** | `0.5` (mock) or `1.0` (real HW) | Binary pass/fail | Availability % | `tee_score * correctness` |

Full analysis with code evidence: [`docs/05-bittensor-comparison.md`](docs/05-bittensor-comparison.md)

## Quick start

```bash
git clone https://github.com/chainswarm/tee-subnet-template.git my-subnet
cd my-subnet

# Development (mock TEE, no hardware required)
docker compose -f docker-compose.tee-dev.yml up --build

# Testing on real TEE hardware (Azure CVM — not for production, see GRAMINE.md)
docker compose -f docker-compose.tee-real.yml up --build

# Production (Gramine/SGX)
# See GRAMINE.md for full instructions
```

## Build your subnet

All your code goes in `subnet/node/`. Fork and replace 3 files:

```
subnet/node/
  protocol.py  ← what miners do each epoch + how validators call them
  scoring.py   ← how validators score peers (0.0–1.0)
  config.py    ← your subnet parameters
```

Everything else — DHT, libp2p mesh, TEE attestation, RA-TLS, consensus, overwatch, chain integration — is template boilerplate.

```python
# subnet/node/protocol.py
class MyProtocol(BaseNodeProtocol):
    async def miner_loop(self, epoch: int) -> NodeMinerResult:
        tps = await self.run_gpu_benchmark()
        return NodeMinerResult(success=True, metrics={"tps": tps})

    async def validator_call(self, peer_id: str, epoch: int) -> NodeValidatorResult:
        tps = await self.call_remote_peer(peer_id, epoch)
        return NodeValidatorResult(peer_id=peer_id, metrics={"tps": tps})

# subnet/node/scoring.py
class MyScoring(BaseNodeScoring):
    async def score_peer(self, result: NodeValidatorResult, epoch: int) -> PeerScore:
        tps = result.metrics.get("tps", 0.0)
        return PeerScore(peer_id=result.peer_id, score=min(tps / 100.0, 1.0))
```

The TEE backend auto-detects from environment: `MOCK_TEE=true` (default) uses HMAC-based mock for development. Production requires Gramine/SGX — see [`GRAMINE.md`](GRAMINE.md).

Full guide: [`NODE.md`](NODE.md)

## Security model — 5 layers

```
L1 — Hardware attestation     "This code ran unmodified in a genuine TEE"
  ↓
L2 — Confidential compute     "Data never left the enclave unencrypted"
  ↓
L3 — Output integrity          "This output was signed by the attested enclave"
  ↓
L4 — Independent audit         "Overwatch re-verified the work independently"
  ↓
L5 — Economic enforcement      "Cheating costs 3.125% of stake per epoch"
```

Each layer is independently tested. A failure at L1 doesn't mean L4 is broken.

### RA-TLS — the TLS handshake IS the attestation

No separate quote exchange. The miner's TLS certificate contains the DCAP attestation quote in an X.509 extension. The cert's public key hash is bound into the hardware-signed `report_data` — proving the cert was generated inside the enclave.

```python
# Miner
server = RaTlsServer(peer_id=peer_id, epoch=epoch, backend=backend)
session = server.make_session()
ciphertext = session.encrypt(my_result)

# Validator
client = RaTlsClient(config=config)
result = client.verify_cert(cert_pem, peer_id, epoch)  # score=1.0 for real hardware
plaintext = result.session.decrypt(ciphertext)
```

### Identity binding

```
report_data (64 bytes) = sha256(peer_id:epoch) || sha256(cert_pubkey_der)
                         ↑ prevents replay/Sybil   ↑ prevents session hijack (F-02)
```

Hardware signs this into the attestation quote. Cannot be changed post-hoc.

## 4-layer testing strategy

```
                          ┌─────────────────────┐
                          │  Layer 4: Real CVM   │  Azure DCasv5 SEV-SNP
                          │  Production config   │  score=1.0, tamper→slash
                          │  8 attack vectors    │
                          └─────────────────────┘
                     ┌────────────────────────────────┐
                     │  Layer 3: Live chain            │  Hypertensor testnet
                     │  smoke_test_chain.py            │  Peer registration, scores
                     │  continue-on-error in CI        │
                     └────────────────────────────────┘
                ┌─────────────────────────────────────────┐
                │  Layer 2: Docker network                 │  docker-compose.tee-dev.yml
                │  5 containers, live GossipSub            │  Multi-epoch scoring
                │  TAMPER_RATE=1.0 → overwatch detection   │  Restart recovery
                └─────────────────────────────────────────┘
           ┌──────────────────────────────────────────────────┐
           │  Layer 1: In-memory (pytest)                      │  260+ tests, <6 seconds
           │  No Docker, no chain, no hardware                 │  All attestation paths
           │  MockBackend for TEE, trio for async              │  Covers every rejection
           └──────────────────────────────────────────────────┘
```

| Layer | Tests | What it covers | Run time |
|-------|-------|----------------|----------|
| 1. In-memory | 260+ tests | Attestation pipeline, RA-TLS, sealed storage, overwatch, consensus, scoring | <6s |
| 2. Docker network | 5-node topology | GossipSub mesh, multi-epoch scoring, tamper detection, restart recovery | ~3 min |
| 3. Live chain | Smoke tests | Peer registration, score submission, slash events on testnet | ~5 min |
| 4. Real CVM | 8 attack vectors | Hardware attestation testing on Azure SEV-SNP, measurement enforcement | ~4 min |

```bash
# Layer 1
python3 -m pytest tests/ -x -q

# Layer 2
docker compose -f docker-compose.tee-dev.yml up --build

# Layer 4 (on Azure CVM)
docker compose -f docker-compose.tee-real.yml up --build
```

Full testing documentation: [`docs/testing/`](docs/testing/)

## Production deployment

### Deploy to Hypertensor testnet

1. **Get testnet tokens** — join the [Hypertensor Discord](https://discord.gg/hypertensor) and request HTSR from `#testnet-faucet`

2. **Register your subnet**
   ```bash
   PHRASE="your mnemonic ..." \
   python scripts/register_subnet.py \
     --chain wss://rpc.hypertensor.app:443 \
     --name "my-subnet"
   ```

3. **Register and stake nodes** (repeat for each node)
   ```bash
   PHRASE="node mnemonic ..." \
   python scripts/register_node.py \
     --chain wss://rpc.hypertensor.app:443 \
     --subnet_id 1 \
     --hotkey 5GrwvaEF... \
     --peer_id 12D3KooW...
   ```

4. **Run the full stack**
   ```bash
   CHAIN_ENDPOINT=wss://rpc.hypertensor.app:443 \
   SUBNET_ID=1 \
   VALIDATOR_PHRASE="..." \
   MINER1_PHRASE="..." \
   MINER2_PHRASE="..." \
   docker compose -f docker-compose.chain.yml up --build
   ```

5. **Verify on-chain** (after 3+ epochs)
   ```bash
   python scripts/check_peers.py  --chain wss://rpc.hypertensor.app:443 --subnet_id 1
   python scripts/check_scores.py --chain wss://rpc.hypertensor.app:443 --subnet_id 1 --epoch 3
   ```

Full walkthrough: [`CHAIN.md`](CHAIN.md)

### Production hardening

**Gramine/SGX is the only supported production runtime.** CVM-only deployments (SEV-SNP, TDX without Gramine) are vulnerable to runtime code tampering — the operator can modify code after boot while attestation reports still show the original measurement. With Gramine/SGX, the CPU hardware-seals enclave memory; any tampering attempt crashes the enclave.

See [docs/04-anti-cheat.md §10a](docs/04-anti-cheat.md#10a-runtime-code-tampering-inside-a-cvm) for the full threat analysis.

```bash
# Required for production (Gramine/SGX)
EXPECTED_MEASUREMENT="<MRENCLAVE from gramine-sgx-sign>"  # blocks modified binaries
MIN_TEE_SCORE=1.0                                          # require real hardware (no mock)
TCB_POLICY=strict                                          # reject degraded firmware
```

Without `EXPECTED_MEASUREMENT`, a miner can run any binary on real TEE hardware and score 1.0. With it, only your exact binary passes. Use `scripts/build-gramine.sh` to extract the MRENCLAVE hash.

### Deployment paths

| Path | Hardware | Runtime | Score | Production? |
|------|----------|---------|-------|-------------|
| Development | Any machine | `docker-compose.tee-dev.yml` | 0.5 (mock) | No |
| Testing (CVM) | Azure DCasv5 | `docker-compose.tee-real.yml` | 1.0 | No — vulnerable to runtime tampering |
| **Production** | **SGX-capable host** | **Gramine/SGX** — see [`GRAMINE.md`](GRAMINE.md) | **1.0** | **Yes** |
| Testnet | Any machine | `docker-compose.chain.yml` | 0.5 (mock) | No |

### On-chain state and diagnostics

Each subnet has its own state on the Hypertensor chain, queryable via RPC at `wss://rpc.hypertensor.app:443`:

```bash
# Registered peers
python scripts/check_peers.py --chain wss://rpc.hypertensor.app:443 --subnet_id 1

# Score submissions per epoch
python scripts/check_scores.py --chain wss://rpc.hypertensor.app:443 --subnet_id 1 --epoch 5

# Overwatch slash events
python scripts/check_slash.py --chain wss://rpc.hypertensor.app:443 --subnet_id 1 --epoch 5
```

## Real-world example

**vgc-subnet** — GPU benchmark scoring subnet built on this template:
- Protocol: LLM inference via kubetee TDX enclaves, measures tokens/sec
- Scoring: GPU tier multipliers (H100=1.5x, H200=2x, B200=3.5x) + TEE verification
- https://github.com/chainswarm/vgc-subnet

## Documentation

### For subnet builders

| Document | What you'll learn |
|----------|-------------------|
| [`NODE.md`](NODE.md) | How to implement your protocol, scoring, and config — the 3 files you replace |
| [`CHAIN.md`](CHAIN.md) | Full testnet deployment walkthrough — registration, staking, epoch verification |
| [`GRAMINE.md`](GRAMINE.md) | Production TDX deployment with Gramine SGX — measurement extraction, sealed storage |

### For architects

| Document | What you'll learn |
|----------|-------------------|
| [`ARCHITECTURE.md`](ARCHITECTURE.md) | Full module map — every function signature, call path, and data flow |
| [`docs/03-tee-subnet-architecture.md`](docs/03-tee-subnet-architecture.md) | High-level architecture — node topology, epoch flow, 5 security layers |
| [`docs/01-what-is-hypertensor.md`](docs/01-what-is-hypertensor.md) | Hypertensor primer — consensus, slashing, emission, how it differs from Bittensor |
| [`docs/02-what-is-tee.md`](docs/02-what-is-tee.md) | TEE primer — TDX, SEV-SNP, DCAP, identity binding, TCB status, cloud options |

### For security reviewers

| Document | What you'll learn |
|----------|-------------------|
| [`docs/testing/attack-vectors.md`](docs/testing/attack-vectors.md) | 13 attack vectors — 10 tested on real hardware, 3 documented with mitigations |
| [`docs/testing/production-cvm-testing.md`](docs/testing/production-cvm-testing.md) | Azure CVM production test — multi-node Docker, measurement enforcement, scoring |
| [`docs/04-anti-cheat.md`](docs/04-anti-cheat.md) | Attack taxonomy — 10 vectors + runtime tampering, shared resources, GPU sharing |
| [`TESTING_LAYERS.md`](TESTING_LAYERS.md) | 4-layer testing strategy — in-memory, Docker, chain, real CVM |

### For evaluators

| Document | What you'll learn |
|----------|-------------------|
| [`docs/05-bittensor-comparison.md`](docs/05-bittensor-comparison.md) | Why TEE beats SN9 IOTA, SN81 GRAIL, SN75 hippius — structural gap analysis |
| [`docs/06-business-case.md`](docs/06-business-case.md) | Why TEE-backed outputs are productisable — 4 business-critical properties |

## License

MIT
