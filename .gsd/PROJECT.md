# Project

## What This Is

TEE-native Hypertensor subnet template. Extends the base `hayotensor/subnet-template` (py-libp2p-subnet) with first-class TEE support: miners generate DCAP attestation quotes each epoch, publish them to the DHT, and validators verify the quotes as part of consensus scoring. Includes RA-TLS for enclave-to-enclave encrypted channels, measurement-bound sealed storage, and a Gramine manifest template for running Python miners in TDX. Ships with `MOCK_TEE=true` as default so any developer can run and test the full flow without TEE hardware.

## Core Value

A subnet developer can drop in this template and get TEE attestation (hardware identity + code integrity proof) wired into consensus, plus RA-TLS encrypted channels and sealed storage — with zero additional plumbing. Mock mode for development; real TDX/SEV-SNP in production.

## Current State

- **M001 complete** — TEE attestation core: quote schema, identity binding, mock/TDX/SEV-SNP backends, DHT publisher, DcapVerifier (7-step pipeline), consensus integration (tee_score multiplier), docker-compose.tee-dev.yml. R001–R010, R018–R020, R022 validated.
- **M002 complete** — Confidential compute: RA-TLS (RaTlsServer, RaTlsClient, RaTlsSession), input encryption (WorkEnvelope AES-GCM), signed outputs (OutputEnvelope HMAC-SHA256), sealed storage (SealedStore measurement-bound), Gramine manifest + reproducible build script. R011–R016 validated.
- **M003 complete** — Layer 1 in-memory test suite: `MockNodeProtocol` (miner+validator), `MockOverwatchVerifier` (independent audit path), `TAMPER_RATE` fault injection, `OverwatchResult`, `TESTING_LAYERS.md`, root `conftest.py` (excludes live-chain tests from default run). 181 tests pass, 1 skipped (`pytest tests/`); `tests/test_mock_node.py` alone runs in ~1.4–2.1 s (24 tests). All M003 success criteria verified.
- Total: 181 tests passing, 1 skipped. Full confidential-compute stack deployed and exercised in-memory via MockNodeProtocol.

- **M004 complete** — Layer 2 Docker Network Integration (all 3 slices done):
  - **S01** — Multi-node epoch loop: `docker compose up` → bootnode + validator + 2 miners; `[Validator] score=0.50 correct=True` for both miners from epoch 3+; GossipSub cross-container transport on 4 topics; 4 runtime bugs fixed (py-libp2p DNS multiaddr, Docker volume ownership, MockNodeScoring args, PeerInfo extraction)
  - **S02** — Live tamper detection: `_overwatch_epoch_loop` wired into server nursery; miner-1 `TAMPER_RATE=1.0`; 3-epoch live demo: TAMPER=3, PASS=6, errors=0; both validator and overwatch flag every tamper
  - **S03** — Restart recovery + observability: stdlib `JsonFormatter` with `LOG_JSON` env var; `_health_server` on `:8080/health`; curl-based Docker healthchecks; all four containers `(healthy)`; `docker compose restart miner-1` recovery within 120s confirmed live
  - Full DoD satisfied. 183 tests passing, 1 skipped.
- Total: 183 tests passing, 1 skipped.

- **M005 complete** — Layer 3 Hypertensor Chain Integration (all 4 slices done):
  - **S01** — Chain peer discovery: `scripts/check_peers.py` enumerates registered subnet peers via `Hypertensor(url, phrase).get_subnet_nodes_info_formatted()`; `docker-compose.chain.yml` wires full node stack to testnet (no `--no_blockchain_rpc`, `CHAIN_ENDPOINT`/`SUBNET_ID` `:?` guarded, `MOCK_TEE=true` in all services); `TESTING_LAYERS.md` Layer 3 section filled; `CHAIN.md` stub created. All 7 S01 verification checks passed.
  - **S02** — Score submission extrinsic: `ChainScoreSubmitter(hypertensor, subnet_id).submit(scores)` wraps `propose_attestation`; 5 unit tests; `scripts/check_scores.py`; per-node `:?`-guarded `PHRASE` vars in `docker-compose.chain.yml`. 188 tests passing.
  - **S03** — Overwatch slash extrinsic: `ChainOverwatchReporter(hypertensor, overwatch_node_id, subnet_id).slash()` commit+reveal wired into `_overwatch_epoch_loop` behind `OVERWATCH_NODE_ID` guard (MOCK_TEE unaffected); 5 unit tests; `scripts/check_slash.py`; `OVERWATCH_PHRASE` `:?` guard on validator. 193 tests passing.
  - **S04** — Chain integration docs + smoke tests: `ChainScoreSubmitter` wired into `_validator_scoring_loop` in `server.py` (line 567 instantiation, line 618 submit call); `scripts/register_subnet.py`, `scripts/register_node.py`, `scripts/smoke_test_chain.py` added; `CHAIN.md` expanded to 8-section developer walkthrough; `TESTING_LAYERS.md` Layer 3 expanded; `.github/workflows/ci.yml` added (Layer 1 + 2 blocking, Layer 3 continue-on-error). 194 tests passing, 1 skipped.
  - Full DoD satisfied (all slice summaries exist, all cross-slice integration wired, CI live). R023–R026 validated. Live testnet UAT (register subnet, stake nodes, confirm scores/slash on-chain) documented in `CHAIN.md` — requires funded testnet wallet.
- Total: 194 tests passing, 1 skipped. Full chain integration layer deployed: score extrinsic, slash commit+reveal, peer discovery, and developer toolchain all wired and tested.

## Architecture / Key Patterns

- **Node runtime:** `subnet/cli/run_node.py` — starts libp2p host, consensus, DHT, gossipsub
- **Consensus loop:** `subnet/consensus/consensus.py` — `get_scores()` calls `DcapVerifier.verify(peer_id, epoch-1)` per node; applies `tee_score` multiplier (0.0/0.5/1.0); `MIN_TEE_SCORE` gate excludes nodes below threshold
- **DHT:** `subnet/utils/dht.py` — `nmap_put/nmap_get` for key-value storage per topic
- **TEE layer:** `subnet/tee/` — quote generation (mock + real), DHT publisher, DCAP verifier, RA-TLS, sealed storage
- **Config:** env vars `MOCK_TEE`, `TEE_BACKEND` (mock / tdx / sev-snp), `EXPECTED_MEASUREMENT`, `MIN_TEE_SCORE`, `TCB_POLICY`, `PCCS_URL`
- **Score model:** `tee_score ∈ {0.0, 0.5, 1.0}` multiplied into base score; no TEE = 0.0
- **Identity binding:** `report_data = sha256(f"{peer_id}:{epoch}".encode())` zero-padded to 64 bytes — enforced in every backend, verified in DcapVerifier
- **RA-TLS:** `RaTlsServer` (lazy cert gen), `RaTlsClient` (inline attestation verify), `RaTlsSession` (HKDF + AES-GCM) — full encrypted channel without a CA
- **Sealed storage:** `SealedStore` keyed by measurement hash — AES-GCM with nonce, only same enclave binary can unseal

## Milestone Sequence

- [x] M001: TEE Core — attestation, identity binding, DCAP verification, consensus integration
- [x] M002: Confidential Compute — RA-TLS, input encryption, signed outputs, sealed storage, Gramine manifest (all 4 slices complete; R011–R016 validated)
- [x] M003: Layer 1 in-memory test suite — MockNode, overwatch, fault injection (complete on main branch)
- [x] M004: Layer 2 docker-compose — S01 ✅ (multi-node epoch loop), S02 ✅ (live tamper detection), S03 ✅ (restart recovery + observability) — **complete**
- [x] M005: Layer 3 Hypertensor testnet — chain integration, on-chain scoring (all 4 slices complete; R023–R026 validated; 194 tests; CHAIN.md + CI live)
- [x] M006: Knowledge Base — TEE subnet education + architect reference (docs/ folder: Hypertensor primer, TEE primer, HLA, anti-cheat, Bittensor comparison, business case)

## Capability Contract

See `.gsd/REQUIREMENTS.md` for the explicit capability contract.
