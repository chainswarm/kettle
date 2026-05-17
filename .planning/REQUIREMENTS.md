# Requirements: TEE Subnet Template

**Defined:** 2026-03-25
**Core Value:** The only subnet where every computation is cryptographically proven to run on real, unmodified hardware — zero trust required.

## v1.0 Requirements (Complete)

### Networking
- [x] **NET-01**: Nodes form persistent libp2p mesh
- [x] **NET-02**: Nodes advertise public IPs via ANNOUNCE_IP
- [x] **NET-03**: GossipSub mesh recovers automatically

### Dashboard
- [x] **DASH-01** through **DASH-07**: Real-time dashboard with Vue.js + Tailwind

## v1.1 Requirements (Complete)

### Indexer
- [x] **IDX-01** through **IDX-06**: Security event indexer (only bad events recorded)

### Explorer API
- [x] **EXP-01** through **EXP-05**: REST endpoints for events, epochs, nodes, audit, search

### Explorer UI
- [x] **UI-01** through **UI-05**: Epoch timeline, node history, audit log, search, integrated

## v1.2 Requirements

### x402 Payment Middleware

- [ ] **PAY-01**: x402 frontier returns 402 + PAYMENT-REQUIRED header when agent requests inference without payment
- [ ] **PAY-02**: upto scheme support — agents authorize max amount, settle for actual token usage
- [ ] **PAY-03**: Coinbase mainnet facilitator integration (verify + settle endpoints)
- [ ] **PAY-04**: PAYMENT-SIGNATURE header parsing and validation on retry requests
- [ ] **PAY-05**: PAYMENT-RESPONSE header with settlement tx hash on success
- [ ] **PAY-06**: Testnet/mainnet toggle via config (Base Sepolia / Base mainnet)

### TEE-Attested Gateway

- [ ] **TEE-01**: x402 frontier runs inside CVM with TEE attestation
- [ ] **TEE-02**: /attestation endpoint — agents verify gateway measurement before paying
- [ ] **TEE-03**: RA-TLS forwarding from x402 frontier to inference nodes
- [ ] **TEE-04**: Gateway measurement published on-chain (agents can verify independently)

### Agent Integration

- [ ] **AGT-01**: ACP-compatible endpoint for autonomous agents
- [ ] **AGT-02**: OpenAI-compatible /v1/chat/completions with x402 payment layer
- [ ] **AGT-03**: Works with @x402/fetch client library (agents auto-handle 402 flow)
- [ ] **AGT-04**: Per-request pricing based on model + output tokens (upto settlement)

### Config & Operations

- [ ] **OPS-01**: Subnet owner wallet as payTo address (receives USDC)
- [ ] **OPS-02**: CDP API key configuration for facilitator auth
- [ ] **OPS-03**: Price table per model (configurable $/token rates)
- [ ] **OPS-04**: Docker Compose service for x402 frontier

### Agent Integration

- [x] **AGT-01**: ACP-compatible endpoint for autonomous agents
- [x] **AGT-02**: OpenAI-compatible /v1/chat/completions with x402 payment layer
- [x] **AGT-03**: Works with @x402/fetch client library
- [x] **AGT-04**: Per-request pricing based on model + output tokens (up-to settlement)

### Operations

- [x] **OPS-04**: Docker Compose service for x402 frontier

## Out of Scope

| Feature | Reason |
|---------|--------|
| exact scheme | upto is better for inference (variable token count) |
| Custom facilitator | Use Coinbase mainnet facilitator |
| Multi-chain payments | Base only for v1.2, expand later |
| Subscription/credits model | x402 is per-request micropayments |

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
<<<<<<< HEAD
| PAY-01 | Phase 7 | Pending |
| PAY-02 | Phase 7 | Pending |
| PAY-03 | Phase 7 | Pending |
| PAY-04 | Phase 7 | Pending |
| PAY-05 | Phase 7 | Pending |
| PAY-06 | Phase 7 | Pending |
| TEE-01 | Phase 8 | Pending |
| TEE-02 | Phase 8 | Pending |
| TEE-03 | Phase 8 | Pending |
| TEE-04 | Phase 8 | Pending |
| AGT-01 | Phase 9 | Pending |
| AGT-02 | Phase 9 | Pending |
| AGT-03 | Phase 9 | Pending |
| AGT-04 | Phase 9 | Pending |
| OPS-01 | Phase 7 | Pending |
| OPS-02 | Phase 7 | Pending |
| OPS-03 | Phase 7 | Pending |
| OPS-04 | Phase 9 | Pending |

**Coverage:**
- v1.2 requirements: 18 total
- Mapped to phases: 18
=======
| IDX-01 | Phase 4 | Pending |
| IDX-02 | Phase 4 | Pending |
| IDX-03 | Phase 4 | Pending |
| IDX-04 | Phase 4 | Pending |
| IDX-05 | Phase 4 | Pending |
| IDX-06 | Phase 4 | Pending |
| EXP-01 | Phase 5 | Pending |
| EXP-02 | Phase 5 | Pending |
| EXP-03 | Phase 5 | Pending |
| EXP-04 | Phase 5 | Pending |
| EXP-05 | Phase 5 | Pending |
| UI-01 | Phase 6 | Pending |
| UI-02 | Phase 6 | Pending |
| UI-03 | Phase 6 | Pending |
| UI-04 | Phase 6 | Pending |
| UI-05 | Phase 6 | Pending |
| AGT-01 | Phase 9 | Complete |
| AGT-02 | Phase 9 | Complete |
| AGT-03 | Phase 9 | Complete |
| AGT-04 | Phase 9 | Complete |
| OPS-04 | Phase 9 | Complete |

**Coverage:**
- v1.1 requirements: 16 total
- v1.2 agent requirements: 5 total
- Mapped to phases: 21
>>>>>>> worktree-agent-ae66fb20
- Unmapped: 0

---
*Requirements defined: 2026-03-25*
*Last updated: 2026-03-25 after milestone v1.2*
