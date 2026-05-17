# Roadmap: TEE Subnet Template

**Created:** 2026-03-25
**Milestone:** v1.1 — Subnet Block Explorer & Security Indexer

## Phases

### Phase 1: Cross-CVM Networking Fix (v1.0)
- [x] Complete

### Phase 2: Real-Time Monitoring Dashboard (v1.0)
- [x] Complete

### Phase 3: Inference Integration (v1.0)
- [ ] Complete (deferred)

---

### Phase 4: Security Event Indexer
**Goal:** Instrument DcapVerifier, overwatch, and consensus to emit security events into a dedicated RocksDB nmap — only bad events recorded
**Requirements:** IDX-01, IDX-02, IDX-03, IDX-04, IDX-05, IDX-06
**Risk:** low
**Depends:** []
**Plans:** 1 plan

Plans:
- [ ] 04-01-PLAN.md — SecurityEvent model, SecurityEventIndexer, instrument DcapVerifier/overwatch rejection points

After this: every TEE rejection, Sybil detection, CVE violation, tamper detection, and slash event is persistently stored with epoch, peer_id, event_type, severity, and full details. Valid attestations produce no indexer writes.

- [ ] Complete

### Phase 5: Explorer API
**Goal:** REST endpoints for querying indexed security events, epoch history, node history, and overwatch audit log
**Requirements:** EXP-01, EXP-02, EXP-03, EXP-04, EXP-05
**Risk:** low
**Depends:** [4]

After this: dashboard-api serves filtered security events, epoch summaries, per-node history, overwatch audit trail, and search by peer_id/epoch/hardware_id/event_type.

- [ ] Complete

### Phase 6: Explorer UI
**Goal:** Vue.js explorer views integrated into existing dashboard — epoch timeline, node history, overwatch log, search
**Requirements:** UI-01, UI-02, UI-03, UI-04, UI-05
**Risk:** medium
**Depends:** [5]

After this: operators browse epoch timeline, drill into node security history, review overwatch audit log, and search across all indexed events — all within the existing white/green dashboard.

- [ ] Complete

### Phase 8: TEE-Attested Gateway
**Goal:** Add TEE attestation endpoint and RA-TLS inference forwarding to the Frontier gateway
**Requirements:** TEE-01, TEE-02, TEE-03, TEE-04
**Risk:** low
**Depends:** []
**Plans:** 1 plan

Plans:
- [x] 08-01-PLAN.md -- /attestation endpoint, RA-TLS forwarder, chat completions integration

After this: the Frontier gateway can prove it runs in a TEE via /attestation, and forwards inference requests to miner nodes via RA-TLS verified channels with proper error handling (502/504).

- [x] Complete

### Phase 9: Agent Integration & Deployment
**Goal:** x402 payment middleware for autonomous agent access to OpenAI-compatible inference endpoints
**Requirements:** AGT-01, AGT-02, AGT-03, AGT-04, OPS-04
**Risk:** low
**Depends:** []
**Plans:** 1 plan

Plans:
- [x] 09-01-PLAN.md — x402 payment models, middleware, app, Docker service, example client, integration tests

After this: autonomous agents can pay-per-request for inference via HTTP 402 protocol, with per-model pricing and settlement receipts.

- [x] Complete

## Success Criteria

- [ ] Security events indexed on every DcapVerifier rejection
- [ ] Valid attestations produce zero indexer writes
- [ ] Explorer API returns filtered results in <100ms
- [ ] Dashboard shows epoch timeline with drill-down to events
- [ ] Search by peer_id returns full security history
- [ ] All 399+ existing tests still pass
- [ ] New indexer + API + UI have test coverage

---
*Roadmap created: 2026-03-25*
*Last updated: 2026-03-25 after phase 8 completion*
