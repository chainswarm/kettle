# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-03-25)

**Core value:** The only subnet where every computation is cryptographically proven to run on real, unmodified hardware — zero trust required.
**Current focus:** v1.2 — TEE-Attested x402 Inference for Agents

## Current Phase

Defining requirements for milestone v1.2

## Phase Progress

| Phase | Name | Status | Started | Completed |
|-------|------|--------|---------|-----------|
| 1 | Cross-CVM Networking Fix (v1.0) | Done | 2026-03-24 | 2026-03-24 |
| 2 | Real-Time Monitoring Dashboard (v1.0) | Done | 2026-03-25 | 2026-03-25 |
| 3 | Inference Integration (v1.0) | Deferred | — | — |
<<<<<<< HEAD
| 4 | Security Event Indexer | Done | 2026-03-25 | 2026-03-25 |
| 5 | Explorer API | Done | 2026-03-25 | 2026-03-25 |
| 6 | Explorer UI | Done | 2026-03-25 | 2026-03-25 |
| 7 | x402 Payment Middleware | Not started | — | — |
| 8 | TEE-Attested Gateway | Not started | — | — |
| 9 | Agent Integration & Deployment | Not started | — | — |
=======
| 4 | Security Event Indexer | Not started | — | — |
| 5 | Explorer API | Not started | — | — |
| 6 | Explorer UI | Not started | — | — |
| 9 | Agent Integration & Deployment | Done | 2026-03-25 | 2026-03-25 |
>>>>>>> worktree-agent-ae66fb20

## Blockers/Concerns

- Cross-CVM libp2p multistream handshake fails after initial TCP connection (see todo: .planning/todos/pending/2026-03-24-fix-cross-cvm-libp2p-persistent-connections.md)
- Azure DCesv5 (Intel TDX) not available — requires preview enrollment

## Accumulated Context

### Infrastructure
- Two Azure CVMs deployed: tee-one (48.209.8.60, westeurope), teetwo (40.112.65.210, northeurope)
- Different physical AMD EPYC CPUs → different CHIP_IDs (Sybil resistance verified)
- Ports 38960-38963 open on both
- CVMs currently powered off (user shutting down for the night)

### Recently Completed (pre-GSD)
- Hardware Sybil resistance (CHIP_ID, GPU UUID dedup)
- Real DCAP signature verification (VCEK for SEV-SNP, PCK for TDX)
- CVE-aware TCB enforcement (CacheWarp, BadRAM)
- 399 tests passing

<<<<<<< HEAD
Last activity: 2026-03-25 - Milestone v1.2 started
=======
### Decisions (Phase 9)
- x402 HTTP 402 protocol for agent payment (compatible with @x402/fetch)
- Per-model pricing tiers with USDC input/output token pricing
- Up-to settlement: agent authorizes max, actual charge based on usage
- MockOnChainVerifier for dev, pluggable OnChainVerifier protocol for production
- Port 8402 for x402 frontier (separate from 8080 base frontier)

Last activity: 2026-03-25 - Phase 9 Agent Integration complete (6 tasks, 30 tests)
>>>>>>> worktree-agent-ae66fb20
