# TEE Inference Cluster — Design Spec

> **Date:** 2026-03-22
> **Scope:** Decentralized inference provider for OpenRouter — TEE-attested GPU nodes, smart frontier router, Kata container isolation, NVIDIA-only stack
> **One-liner:** A decentralized OpenRouter backend where every inference response is cryptographically proven to come from the genuine model running on verified hardware — no trust in any operator required.

---

## 1. Problem statement

> *"Nobody can fully explain to me that if I send a message to an LLM, the operator of that LLM cannot see or alter your message."*

Current inference providers (Together, Fireworks, Replicate) ask consumers to trust the operator. The operator controls the hardware, the network, and the code. There is no cryptographic proof that:
- The model advertised is the model actually running
- The response wasn't altered in transit
- The operator didn't read the request payload

This design solves all three via hardware attestation (CPU TEE + GPU TEE), RA-TLS transport encryption, and signed output envelopes.

---

## 2. Architecture overview

```
                    OpenRouter (external consumer)
                         │
                         │ POST /v1/chat/completions
                         │ model: "nvidia/nemotron-3-49b"
                         ▼
              ┌─────────────────────┐
              │  Frontier (Smart)    │  ← multiple instances behind DNS LB
              │  - OpenAI-compat API │     any node can run one
              │  - capacity table    │     state rebuilds from heartbeats
              │  - model→nodes map   │     in seconds if restarted
              └──────────┬──────────┘
                         │
          ┌──────────────┼──────────────┐
          ▼              ▼              ▼
    ┌───────────┐  ┌───────────┐  ┌───────────┐
    │  Node A   │  │  Node B   │  │  Node C   │
    │ CVM+H100  │  │ CVM+H100  │  │ CVM+H200  │
    │ Kata      │  │ Kata      │  │ Kata      │
    │ NIM:      │  │ NIM:      │  │ NIM:      │
    │ nemotron  │  │ nemotron  │  │ llama-70b │
    │ -3-8b     │  │ -3-49b    │  │           │
    │ TEE ✓     │  │ TEE ✓     │  │ TEE ✓     │
    └───────────┘  └───────────┘  └───────────┘
          │              │              │
          └──────────────┼──────────────┘
                         │
              libp2p mesh (GossipSub + DHT)
                         │
              Hypertensor chain (scoring, emissions, slashing)
```

### Trust boundaries

- **OpenRouter → Frontier**: Standard HTTPS. OpenRouter trusts the provider endpoint.
- **Frontier → Node**: RA-TLS. Frontier verifies the node's TEE attestation before forwarding. The response is signed by the enclave's session key.
- **Node → Node**: libp2p mesh with Noise transport + Proof-of-Stake authentication.
- **Nobody trusts the operator**: Kata blocks runtime tampering, TEE measurement proves the model, RA-TLS encrypts payloads end-to-end.

### Key design decisions

| Decision | Choice | Why |
|----------|--------|-----|
| Orchestration | P2P (no K3s) | No central control plane, Hypertensor IS the orchestrator |
| Container isolation | Kata on CVM | dm-verity + OPA blocks runtime tampering without needing Gramine |
| GPU stack | NVIDIA only (NIM + TensorRT-LLM) | Optimized inference, GPU attestation via nv-attestation-sdk |
| Model assignment | Owner-defined ratios, round-robin | Subnet owner controls supply, nodes don't choose |
| Routing | Smart frontier with capacity table | Least-loaded routing, failover, SSE streaming pass-through |
| Multiple frontiers | Yes, behind DNS LB | Any node can run a frontier, no single point of failure |

---

## 3. Per-node stack

```
┌─────────────────────────────────────────────┐
│  CVM (SEV-SNP or TDX)                       │
│                                              │
│  ┌────────────────────────────────────────┐  │
│  │  Kata Container (dm-verity + OPA)      │  │
│  │                                        │  │
│  │  ┌──────────────────────────────────┐  │  │
│  │  │  NVIDIA NIM                      │  │  │
│  │  │  ┌────────────────────────────┐  │  │  │
│  │  │  │  TensorRT-LLM (engine)    │  │  │  │
│  │  │  └────────────────────────────┘  │  │  │
│  │  │  OpenAI-compat API :8000        │  │  │
│  │  └──────────────────────────────────┘  │  │
│  │                                        │  │
│  │  ┌──────────────────────────────────┐  │  │
│  │  │  Subnet agent                    │  │  │
│  │  │  - libp2p mesh participant       │  │  │
│  │  │  - TEE attestation (DCAP)        │  │  │
│  │  │  - RA-TLS cert + session keys    │  │  │
│  │  │  - Heartbeat (model, GPU, load)  │  │  │
│  │  └──────────────────────────────────┘  │  │
│  └────────────────────────────────────────┘  │
│                                              │
│  GPU: NVIDIA H100 / H200 / B200             │
│  GPU attestation: nv-attestation-sdk         │
│  Device identity: silicon-fused ECC-384 key  │
└─────────────────────────────────────────────┘
```

### NVIDIA stack

| Layer | Component | Purpose |
|-------|-----------|---------|
| Model serving | NVIDIA NIM | Containerized inference, OpenAI-compatible API, optimized TensorRT-LLM engines |
| GPU runtime | NVIDIA Container Toolkit | GPU passthrough into Kata microVM |
| GPU attestation | nv-attestation-sdk | Verify H100 device identity certificate (silicon-fused key) |
| GPU verification | NVIDIA NRAS | Remote attestation service — validates GPU report against golden measurements |
| Models | NVIDIA NGC | Model registry — Nemotron, Llama, Mistral via NIM |

### Heartbeat payload

```json
{
  "version": 1,
  "peer_id": "12D3KooW...",
  "models": ["nvidia/nemotron-3-49b"],
  "gpu": "H100",
  "gpu_uuid": "GPU-abc123...",
  "gpu_attested": true,
  "vram_total_gb": 80,
  "vram_used_gb": 45,
  "requests_in_flight": 3,
  "latency_p95_ms": 890,
  "tee_score": 1.0,
  "nim_version": "1.12.0"
}
```

### Integrity chain (CVM → Kata → NIM container)

```
CVM boot measurement (SEV-SNP MEASUREMENT / TDX MRTD)
  → attests the host kernel + Kata runtime
    → Kata dm-verity attests the guest rootfs (microVM image)
      → Kata OPA policy restricts which container images can run
        → NIM container image hash must match the on-chain expected measurement
          → OPA blocks kubectl exec / attach (no runtime tampering)
```

The policy hash is stored in the attestation report's `HOSTDATA` field, creating a hardware-rooted chain from silicon to container.

### Dual attestation chains (verified every epoch)

1. **CPU TEE** — DCAP quote signed by AMD/Intel silicon → proves code is genuine, Kata policy is enforced
2. **GPU TEE** — Device identity cert signed by NVIDIA silicon → proves GPU is real, not spoofed. Verified via `nv-attestation-sdk` against NVIDIA NRAS. GPU attestation is checked during RA-TLS handshake (on first connect) and re-verified by validators each epoch.

---

## 4. Model incentives and assignment

### Owner-defined model ratios

The subnet owner publishes a model configuration on-chain:

```
Model config (on-chain):
┌──────────────────────────────┬───────┬─────────────────────┐
│ Model                        │ Ratio │ Measurement         │
├──────────────────────────────┼───────┼─────────────────────┤
│ nvidia/nemotron-3-8b         │  50%  │ a1b2c3d4...         │
│ nvidia/nemotron-3-49b        │  30%  │ e5f6a7b8...         │
│ meta/llama-3.1-70b           │  20%  │ c9d0e1f2...         │
└──────────────────────────────┴───────┴─────────────────────┘
```

### How it works

1. **Subnet owner** sets the model list + target ratios on-chain
2. **Model assignment is self-computed by the node** — not assigned by the frontier. When a node joins, it reads the on-chain ratio config and the current model-to-node mapping from DHT. It computes which model has the largest deficit (target% − actual%) and self-assigns to that model. This is deterministic: given the same on-chain config and DHT state, every node and frontier computes the same assignment.
3. **The node publishes its assignment** to DHT (`model_assignment:{peer_id} → model_name`) and starts its NIM container. The frontier reads this from DHT / heartbeats — it does not make the assignment decision.
4. **Tie-breaking**: If multiple models have equal deficit, the node picks the one with the lowest lexicographic name. If multiple nodes join simultaneously, each reads the DHT state at join time — temporary over-assignment self-corrects at the next epoch when validators score and the surplus nodes switch.
5. **Request routing** within each model — frontier picks the least-loaded node (by `requests_in_flight` from heartbeat). On failover (5s timeout), tries the next least-loaded.

### Example

```
10 nodes, owner ratio = 50/30/20:

  nemotron-8b:  Node A, B, C, D, E     (5 nodes = 50%)
  nemotron-49b: Node F, G, H           (3 nodes = 30%)
  llama-70b:    Node I, J              (2 nodes = 20%)

Request for nemotron-49b → least-loaded: F(30%) > H(50%) > G(70%)
Request for llama-70b    → least-loaded: I(10%) > J(40%)
```

### Model verification

The TEE measurement is unique per NIM container image — MRTD on Intel TDX, MEASUREMENT on AMD SEV-SNP (not MRENCLAVE, which is SGX-specific). Each model in the config has a corresponding expected measurement. When a node claims to run nemotron-49b, its TEE attestation must contain the matching measurement. Wrong model → measurement mismatch → score 0.0.

### Rebalancing

When the subnet owner updates ratios on-chain, nodes detect the change by polling the chain (same mechanism as epoch data). Each node re-runs the self-assignment algorithm with the new ratios and current DHT state. No GossipSub command needed — nodes react to on-chain state changes autonomously.

```
Before: nemotron-8b=50%, nemotron-49b=30%, llama-70b=20%  (on-chain)
After:  nemotron-8b=30%, nemotron-49b=30%, llama-70b=40%  (on-chain update)

Node D: reads new ratios → sees nemotron-8b surplus, llama-70b deficit
  → self-reassigns to llama-70b → pulls new NIM → re-attests
Node E: same computation → same result → switches
```

No central coordinator. No unauthenticated GossipSub commands. Nodes follow the chain as the source of truth.

### Scoring

```
score = tee_score × gpu_attestation × uptime × latency_factor
         (0 or 1)     (0 or 1)        (0-1)     (0-1)
```

- `tee_score`: 1.0 if CPU DCAP attestation passes (measurement matches on-chain expected for assigned model), 0.0 otherwise.
- `gpu_attestation`: 1.0 if GPU device identity verified via nv-attestation-sdk, 0.0 otherwise.
- `uptime`: `heartbeats_received / heartbeats_expected` over the epoch. 2s interval, ~30s epoch = 15 expected. 12 received = 0.8.
- `latency_factor`: `min(1.0, target_p95 / actual_p95)` where `target_p95` is per-model (set on-chain alongside ratio). Faster than target = 1.0, slower = proportionally degraded.

No multiplier per model. Faster GPUs naturally serve more requests per epoch and earn more through higher uptime and better latency scores.

---

## 5. Frontier (Smart Router)

The frontier is a lightweight service that any node can run. Multiple instances behind DNS load balancer. No secrets, no persistent state.

### Request routing

```
OpenRouter
    │
    │  POST /v1/chat/completions
    │  {"model": "nvidia/nemotron-3-49b", "messages": [...]}
    │
    ▼
Frontier
    │
    │  1. Parse model name from request
    │  2. Look up capacity table:
    │     nemotron-49b → [Node F (load=30%), Node G (70%), Node H (50%)]
    │  3. Pick Node F (least loaded)
    │  4. Forward via RA-TLS to Node F
    │  5. Node F responds with signed completion
    │  6. Return response to OpenRouter
    │     + X-TEE-Proof header (optional)
```

### Capacity table

In-memory, rebuilt from heartbeats. Updated every ~2s.

```
┌──────────────────────────┬──────┬──────┬──────┐
│ model                    │ node │ load │ p95  │
├──────────────────────────┼──────┼──────┼──────┤
│ nvidia/nemotron-3-8b     │  A   │ 30%  │ 210  │
│ nvidia/nemotron-3-8b     │  B   │ 45%  │ 230  │
│ nvidia/nemotron-3-49b    │  F   │ 30%  │ 890  │
│ nvidia/nemotron-3-49b    │  G   │ 70%  │ 920  │
│ meta/llama-3.1-70b       │  I   │ 10%  │ 950  │
└──────────────────────────┴──────┴──────┴──────┘
```

### Design properties

- **Routing**: Least-loaded first, with failover. If a node doesn't respond in 5s, retry next.
- **Streaming**: SSE pass-through (`stream: true`). Frontier doesn't buffer — low memory, low latency.
- **Authentication**: OpenRouter sends a bearer token, validated against an allowlist.
- **Connection pooling**: Frontier maintains persistent RA-TLS connections to nodes. The RA-TLS handshake (attestation verification) happens once per connection, not per request. Connections are re-established on heartbeat failure or attestation expiry (epoch boundary).
- **Statelessness**: Capacity table is a read cache of heartbeat data. Restarts rebuild in one heartbeat interval (~2s). Connection pool rebuilds on first request to each node.
- **Staleness**: A node is removed from the capacity table after 3 missed heartbeats (~6s). In-flight requests to that node are allowed to complete (5s timeout), but no new requests are routed.
- **Backpressure**: When all nodes for a model are above 90% load, frontier returns `HTTP 429 {"error": "capacity_exceeded", "retry_after": 5}`. OpenRouter handles retry.
- **Proof header**: `X-TEE-Proof: <base64>` — JSON containing `{attestation_quote, output_signature, gpu_device_cert}`, base64-encoded. Consumer can independently verify the response came from attested hardware by checking the DCAP signature chain and output envelope signature.
- **Payload visibility**: The frontier terminates HTTPS from OpenRouter and forwards via RA-TLS to the node. The frontier CAN see request/response payloads (it must parse the model name for routing). For end-to-end encryption where even the frontier cannot read payloads, OpenRouter would need to establish RA-TLS directly to the node — this is a future enhancement. In the initial design, the frontier is a trusted proxy for payload confidentiality but not for integrity (responses are still signed by the enclave).

### Failure modes

| Failure | What happens |
|---------|-------------|
| Node doesn't respond in 5s | Frontier retries on next node in round-robin |
| Node TEE attestation fails | Frontier skips node, reports to mesh for scoring |
| Node GPU attestation fails | Same — skip and report |
| All nodes for a model down | `HTTP 503 {"error": "model_unavailable"}` |
| Frontier goes down | DNS LB routes to another frontier instance |

---

## 6. Request flow (end to end)

```
OpenRouter                  Frontier                    Node G
    │                          │                           │
    │ POST /v1/chat/completions│                           │
    │ model: nemotron-3-49b    │                           │
    │─────────────────────────►│                           │
    │                          │                           │
    │                          │ 1. Lookup: nemotron-49b   │
    │                          │    → nodes F, G, H        │
    │                          │    → round-robin: G next  │
    │                          │                           │
    │                          │ 2. RA-TLS connect to G    │
    │                          │──────────────────────────►│
    │                          │   (verify TEE attestation │
    │                          │    + GPU device identity)  │
    │                          │                           │
    │                          │ 3. Forward request        │
    │                          │──────────────────────────►│
    │                          │                           │ 4. NIM inference
    │                          │                           │    (TensorRT-LLM)
    │                          │                           │
    │                          │ 5. Signed response (SSE)  │
    │                          │◄──────────────────────────│
    │                          │   (OutputEnvelope signed  │
    │                          │    by enclave session key) │
    │                          │                           │
    │ 6. Response + proof      │                           │
    │◄─────────────────────────│                           │
    │   X-TEE-Proof: <base64>  │                           │
```

### What each step proves

| Step | What happens | What it proves |
|------|-------------|----------------|
| 2 | RA-TLS handshake | Node runs genuine NIM container (measurement match) on real hardware (DCAP signature) |
| 2 | GPU attestation check | GPU is a real H100/H200/B200 (NVIDIA silicon-fused key) |
| 5 | OutputEnvelope signature | This specific response came from inside that specific enclave |
| 6 | X-TEE-Proof header | OpenRouter (or end consumer) can independently verify |

---

## 7. Node lifecycle

### Join

1. Operator provisions CVM + GPU (e.g., Azure NCCadsH100v5)
2. Node boots Kata + subnet agent
3. Node joins libp2p mesh (POS-authenticated)
4. Frontier assigns model based on ratio deficit
5. Node pulls NIM container from NGC, starts inference server
6. Node generates TEE quote + GPU attestation report
7. First heartbeat — frontier verifies measurement against on-chain expected value
8. Added to capacity table, starts receiving requests

### Running

- Heartbeats every ~2s with model, GPU, load, latency
- Round-robin validator verifies TEE + GPU attestation each epoch
- Overwatch randomly audits: sends challenge prompt via RA-TLS, verifies signed response, re-checks attestation
- Scoring each epoch: `tee_score × gpu_attestation × uptime × latency_factor`

### Model rebalancing

When subnet owner updates ratios on-chain, frontier sends model-switch signals via GossipSub. Reassigned nodes pull new NIM container, restart, re-attest.

### Leave

**Graceful** (node announces departure):
1. Node sends "leaving" to GossipSub
2. Frontier removes from capacity table immediately (no new requests)
3. Node finishes in-flight requests, then shuts down
4. No uptime penalty for the current epoch (announced departure)

**Ungraceful** (node disappears):
1. Frontier detects 3 missed heartbeats (~6s), removes from capacity table
2. In-flight requests to that node time out (5s), frontier retries on another node
3. Missed heartbeats reduce uptime score for that epoch

---

## 8. Security model

### 5 layers (inherited from template)

```
L5 — Economic enforcement     Hypertensor chain: slash 3.125% stake per failed epoch
  ↑
L4 — Independent audit        Overwatch: random inference challenges + re-attestation
  ↑
L3 — Output integrity         OutputEnvelope signed by enclave session key (RA-TLS)
  ↑
L2 — Confidential compute     Kata microVM (dm-verity + OPA) on CVM (SEV-SNP/TDX)
  ↑
L1 — Hardware attestation     CPU: DCAP (AMD/Intel silicon key)
                               GPU: NVIDIA device identity (silicon-fused ECC-384)
```

### Actor permissions

| Actor | Can | Cannot |
|-------|-----|--------|
| Node operator | Provision hardware, join/leave network | See request payloads (RA-TLS), modify code (Kata dm-verity), fake attestation (silicon key), choose which model to run (assigned) |
| Frontier operator | Route requests, see request/response payloads (HTTPS termination) | Alter responses (signed by enclave — tampering is detectable), fake attestation |
| Subnet owner | Set model ratios, set expected measurements | Forge TEE quotes, read enclave memory, override hardware attestation |
| OpenRouter | Send requests, verify X-TEE-Proof headers | Nothing beyond what any consumer can do |

### Attack surface (inherits all 13 from template, adds 3 new)

| Attack | Defense |
|--------|---------|
| Node runs cheaper model | Measurement mismatch → score 0.0 |
| Node fakes GPU identity | GPU attestation via nv-attestation-sdk → score 0.0 |
| Operator modifies code at runtime | Kata dm-verity + OPA blocks exec |
| Frontier routes to compromised node | RA-TLS — frontier can't MitM, consumer can verify X-TEE-Proof |
| Frontier drops requests (DoS) | Multiple frontiers behind DNS LB |
| Node claims wrong model assignment | Measurement must match assigned model on-chain |
| Sybil — one GPU as multiple nodes | GPU device identity certificate is unique per silicon |

### What's new vs the current template

| Component | Current template | This design |
|-----------|-----------------|-------------|
| Container isolation | Gramine/SGX (or bare CVM) | Kata on CVM (dm-verity + OPA) |
| GPU verification | Documented, not implemented | nv-attestation-sdk integrated into scoring |
| Work distribution | Epoch loop (all nodes do same work) | Frontier routes external requests to specific nodes |
| Model verification | Single EXPECTED_MEASUREMENT | Per-model measurement map on-chain |
| External API | None | OpenAI-compatible frontier |

---

## 9. Technology stack

| Layer | Technology | Notes |
|-------|-----------|-------|
| Inference | NVIDIA NIM + TensorRT-LLM | OpenAI-compatible API, optimized engines |
| Models | NVIDIA NGC | Nemotron 3, Llama, etc. |
| GPU attestation | nv-attestation-sdk | Silicon-fused device identity |
| Container runtime | Kata Containers | dm-verity + OPA on CVM |
| CPU TEE | AMD SEV-SNP / Intel TDX | CVM with Kata (not bare CVM) |
| Networking | libp2p (GossipSub + DHT) | Existing template mesh |
| Transport security | RA-TLS | Cert pubkey bound in attestation |
| Consensus | Hypertensor chain | Round-robin validators, overwatch, slashing |
| Frontend | OpenAI-compatible HTTP API | Frontier instances behind DNS LB |

---

## 10. Out of scope (future)

- **Billing/payments**: Handled by OpenRouter. Hypertensor chain handles emissions.
- **Multi-provider routing**: Frontier serves one subnet. Cross-subnet routing is a chain-level feature.
- **Fine-tuning / RL**: Architecture supports it (Kata + GPU), but initial implementation is inference-only.
- **Consumer-facing frontend**: No dashboard, no UI. OpenRouter is the consumer interface.
- **K3s/Kubernetes**: Not needed. libp2p mesh + Hypertensor chain provides scheduling, discovery, and coordination.
- **Multi-GPU nodes**: Initial design assumes 1 model per node, 1 GPU per node. Tensor parallelism across multiple GPUs on one node is a future enhancement.
- **End-to-end encryption (frontier bypass)**: OpenRouter establishing RA-TLS directly to nodes, bypassing frontier payload visibility. Future enhancement.
- **Observability stack**: Prometheus, Grafana, distributed tracing. Important for production but out of scope for the initial design.
