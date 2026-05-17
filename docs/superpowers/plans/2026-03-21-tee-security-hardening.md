# TEE Security Hardening — Consolidated Plan

> **Spec:** [`docs/superpowers/specs/2026-03-21-tee-architecture-review-design.md`](../specs/2026-03-21-tee-architecture-review-design.md)
> **Status:** 23/24 findings implemented
> **Last updated:** 2026-03-21

---

## Completed (22 findings)

### P0 — Security foundations (3/3 DONE)

| Finding | Commit | What was done |
|---------|--------|---------------|
| F-01: DCAP verification | `1b26037` | SEV-SNP structural verification: version=2, non-zero measurement, consistency checks, sig algo validation. Azure vTPM path via `SevSnpAzureBackend`. |
| F-02: Cert pubkey binding | `ac3f746` | Upper 32 bytes of `report_data` contain `sha256(cert_pubkey_der)`. Keypair generated before quote. All backends updated. Verified on real SEV-SNP: Attack 6 (external keypair cert) blocked. |
| F-03: DHT write auth | `5327816` | GossipSub receiver validates sender `peer_id` matches content `peer_id` for TEE quotes, RA-TLS certs, and work records. 6 tests. |

### P1 — Security hardening (11/11 DONE)

| Finding | Commit | What was done |
|---------|--------|---------------|
| F-05: Hardware sealing | `3f04932` | `SealedStore(is_mock=False)` uses `SHA256(measurement_bytes)` as IKM instead of `HMAC(mock_key, measurement)`. 4 tests. Verified on real SEV-SNP. |
| F-06: Salt persistence | `fefc82d` | `ChainOverwatchReporter` accepts optional `sealed_store`. Salt persisted before commit, cleaned up only after confirmed successful reveal. 2 tests. |
| F-07: Overwatch sig verification | `22fe37d` | Overwatch fetches RA-TLS cert from DHT, derives session key, verifies OutputEnvelope signature. If signature fails, output was not produced by attested enclave. |
| F-08: verify_quote() | `ed0777b` | `DcapVerifier.verify_quote()` runs steps 2-7 on a `TeeQuote` directly. `db` parameter is optional (`None`). `RaTlsClient` no longer creates temp RocksDB. 4 tests. |
| F-09: Comparison tests | `e88db76` | Semantic tests for `compare_consensus_data`: score sensitivity, order independence. 2 tests. |
| F-10: Wire versioning | `f3cfb1f` | `TeeQuote.version` field (default 1). `from_bytes()` rejects unknown versions. Backward compatible. 4 tests. |
| F-12: Unify scoring | `21dc93a` | `Consensus.get_scores()` delegates to `BaseNodeScoring.score_peer()`. One unified scoring path. |
| F-13: BaseOverwatchVerifier | `ffbada4` | Added `BaseOverwatchVerifier` abstract class with `verify(peer_id, epoch) -> OverwatchResult`. `MockOverwatchVerifier` extends base. |
| F-16: In-memory key loading docs | `00bb808` | `RaTlsServer.make_ssl_context()` uses memory-only TLS context via cryptography library. Temp key files no longer written to disk. |
| F-17: Multi-measurement | `d53f924` | `EXPECTED_MEASUREMENT` parsed as comma-separated list. Validators accept any measurement in list. Enables rolling binary updates. |
| F-19: Evidence storage | `2a4de2b` | `ChainOverwatchReporter.slash()` stores overwatch evidence in DHT indexed by `(epoch, peer_id)`. |
| F-20: DHT GC | `0568759` | TTL-based cleanup after each epoch. Delete entries older than `max(3, OVERWATCH_EPOCH_MULTIPLIER + 1)` epochs. |
| F-21: WAL mode | `303fafd` | Added `PRAGMA journal_mode=WAL` to `MockChainDB.__init__`. Prevents `SQLITE_BUSY` errors with concurrent Docker containers. |

### P2 — Bug fixes (2/9 DONE)

| Finding | Commit | What was done |
|---------|--------|---------------|
| F-22: TCB scoring bug | `ecc08b3` | `TcbStatus.UNKNOWN` added to hard-fail guard in `_score_from_tcb`. Was scoring 0.5, now scores 0.0. 3 tests. |
| F-23: Duplicate config | `1580c7d` | Removed duplicate `self._config` assignment in `RaTlsClient.__init__`. |

### P3 — Operational fix (1/5 DONE)

| Finding | Commit | What was done |
|---------|--------|---------------|
| F-24: Div-by-zero | `242a481` | Guard in `get_attestation_ratio`: returns 0.0 if `subnet_nodes` is empty. 5 tests. |

### Additional work (beyond original spec)

| Item | Commit | What was done |
|------|--------|---------------|
| SevSnpAzureBackend | `45db824` | Azure CVM vTPM attestation via `tpm2_nvread` NV index 0x01400001. Auto-detected by backend factory. |
| docker-compose.tee-real.yml | `c626d3d` | 5-node production stack with real SEV-SNP, TPM device passthrough. |
| raw_bytes in DHT | `f43d97a` | `TeeQuote.to_bytes()` includes base64 `raw_bytes` for DCAP verification via DHT. |
| Attack testing | — | 10 attack vectors tested on Azure DCasv5 SEV-SNP. 8 unconditionally blocked. |
| Production CVM testing | — | Multi-node Docker, measurement enforcement, scoring=1.0 on real hardware. |
| MockNodeProtocol env-aware | `c626d3d` | `register_handlers()` uses `TeeConfig()` + `get_backend()` instead of hardcoded MockBackend. |
| Documentation overhaul | `cf6d6a8` | README rewrite, NODE/CHAIN/GRAMINE updates, attack-vectors.md, production-cvm-testing.md. |

**Tests:** 194 → 260 (+66 new)

---

## Recently completed

| Finding | Commit | What was done |
|---------|--------|---------------|
| F-14: Extract server.py | — | Split monolithic `server.py` into `server/host.py` (libp2p host + transport setup), `server/loops.py` (epoch loops: TEE publish, miner, validator scoring, overwatch), `server/health.py` (HTTP health endpoint), and `server/server.py` (thin composition layer with `_start_node_loops` helper). |

---

## Remaining (1 finding)

#### F-15: Register proper OID (external process)

**Priority:** Low
**Effort:** Small (external process)

**Current state:** The RA-TLS certificate embeds TEE attestation quotes in a custom X.509 extension using OID `1.3.6.1.4.1.99999.1` (defined in `subnet/tee/ratls/cert.py:64`). The `99999` arc is a placeholder — it is not registered and could collide with a legitimately assigned PEN.

**What this OID does:** When a node generates an RA-TLS certificate (via `create_ratls_certificate()`), the TEE quote bytes are embedded as a non-critical X.509 extension under this OID. Validators extract the quote from the extension during RA-TLS verification to confirm the peer is running inside a genuine TEE enclave. The OID appears in:
- `subnet/tee/ratls/cert.py` — `TEE_QUOTE_OID` constant, used in cert generation
- `subnet/tee/ratls/server.py` — extracted during TLS handshake verification

**Why it matters:** In production, any X.509 tooling or CA that encounters this extension will see an unregistered OID. While non-critical extensions with unknown OIDs are silently ignored per RFC 5280, using a real PEN:
- Prevents collision if `99999` is ever assigned to another organisation
- Allows third-party validators and audit tools to recognise the extension semantically
- Is required for any formal security certification (SOC2, FedRAMP, etc.)

**How to register:**
1. Submit a PEN (Private Enterprise Number) request to IANA at https://pen.iana.org/pen/PenApplication.page
2. The form requires: organisation name, contact email, and a short description of intended use
3. IANA assigns a unique number under the `1.3.6.1.4.1.{your-pen}` arc — typically within 1-2 weeks
4. Once assigned, replace `99999` with the registered PEN in `TEE_QUOTE_OID` and update the docstrings in `cert.py`
5. No code changes needed beyond the constant — all consumers reference `TEE_QUOTE_OID` symbolically

**Impact of not doing this:** Functionally zero for internal/testnet use. Only relevant for production deployments that interact with external PKI infrastructure or require compliance audits.

---

## GPU inference testing plan

GPU inference example (`examples/gpu-inference/`) — TEE-attested LLM via NVIDIA NIM.

### Phase 1: NIM integration (A10, ~$0.60)

**VM:** Azure Standard_NV36ads_A10_v5 (A10 24GB, ~$1.80/hr)
**Model:** Llama 3.2 1B Instruct via NIM
**TEE:** `MOCK_TEE=true` (A10 has no confidential computing)
**Goal:** Validate NIM integration works — protocol calls NIM, signs output, publishes to DHT, validator scores correctly.

Steps:
1. Provision A10 VM, install NVIDIA Container Toolkit
2. `docker login nvcr.io` with NGC API key
3. `docker compose -f examples/gpu-inference/docker-compose.gpu-inference.yml up --build`
4. Verify: miner calls NIM, returns completion, validator scores > 0
5. Tear down VM (~20 min total)

**Success criteria:** Miner logs show `[GpuMiner] epoch=N tokens=X latency=Yms`, validator scores miner at 0.5 (mock TEE).

### Phase 2: Confidential GPU (H100, ~$3)

**VM:** Azure Standard_NCC40ads_H100_v5 (H100 80GB, SEV-SNP + GPU TEE, ~$10/hr)
**Model:** Same (Llama 3.2 1B) or upgrade to Nemotron Nano 4B
**TEE:** `TEE_BACKEND=sev-snp` (real CPU attestation) + NVIDIA GPU attestation
**Goal:** Validate full confidential GPU pipeline — CPU TEE attestation + GPU device identity.

Steps:
1. Provision H100 confidential VM
2. Run same docker-compose with `MOCK_TEE=false`, `TEE_BACKEND=sev-snp`
3. Verify: TEE score=1.0, attestation report from real hardware
4. (Optional) Add NVIDIA GPU attestation via `nv-attestation-sdk` — verify H100 device identity certificate
5. Tear down VM (~20 min total)

**Success criteria:** Miner scores 1.0 (real TEE), GPU attestation report contains valid NVIDIA device identity.

### Status

- [x] Example protocol, scoring, overwatch created (`examples/gpu-inference/protocol.py`)
- [x] Docker compose with NIM + subnet stack (`docker-compose.gpu-inference.yml`)
- [x] Documentation (`examples/gpu-inference/README.md`)
- [ ] Phase 1: A10 integration test
- [ ] Phase 2: H100 confidential GPU test
- [ ] (Optional) Integrate `nv-attestation-sdk` into verifier pipeline
