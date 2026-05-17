# M001: TEE Core — Attestation + Identity + Consensus

**Vision:** Miners prove they are running the exact approved binary on real hardware, with identity and epoch bound into every proof. Validators verify the full certificate chain. A fake or replayed attestation scores 0. Ships with mock mode so any developer can run it.

## Success Criteria

- A miner with `MOCK_TEE=true` starts, generates a quote bound to its peer_id + epoch, publishes to DHT
- Validator fetches, verifies (mock path), checks identity binding, checks measurement, produces tee_score
- Debug mode quote → 0.0 score (tested)
- Replayed quote (wrong epoch) → 0.0 (tested)
- Stolen quote (wrong peer_id) → 0.0 (tested)
- Measurement mismatch → 0.0 (tested)
- `docker compose up` runs 2 epochs cleanly, all miners score non-zero

## Key Risks

- `report_data` field handling differs between TDX/SEV-SNP drivers — normalise early
- Gramine manifest measurement changes on every rebuild — need reproducible build or measurement update flow

## Verification Classes

- Contract: pytest unit tests (mock path — all attack scenarios)
- Integration: docker compose 2-epoch run with MOCK_TEE=true
- Operational: miner restart mid-epoch, fresh quote on next epoch

## Milestone Definition of Done

- [x] `subnet/tee/quote.py` — TeeQuote dataclass + serialisation
- [x] `subnet/tee/backends/mock.py` — MockBackend with identity binding
- [x] `subnet/tee/backends/tdx.py` — TdxBackend stub + real `tdx-attest` call
- [x] `subnet/tee/backends/sev_snp.py` — SevSnpBackend stub
- [x] `subnet/tee/publisher.py` — TeePublisher: epoch quote → DHT
- [x] `subnet/tee/verifier.py` — DcapVerifier: fetch from DHT, verify chain (mock), identity check, debug check, measurement check
- [ ] `subnet/tee/collateral.py` — CollateralCache: PCK CRL + TCB Info + QE Identity, DHT-backed (deferred to M002)
- [x] `subnet/consensus/consensus.py` — `get_scores()` wired with tee_score multiplier
- [x] All R001–R010, R018–R020, R022 tests pass

## Requirement Coverage

- Covers: R001–R010, R018, R019, R020, R022
- Deferred to M002: R011–R017 (RA-TLS, sealed storage, Gramine, input encryption)
- Deferred to M002: R021 (PCCS DHT cache — M001 uses online PCS or mock)

## Slices

- [x] **S01: Quote schema + identity binding + mock backend + DHT publisher** `risk:high` `depends:[]`
  > 52 tests. Miner generates peer_id+epoch-bound mock quote, publishes to DHT. Replay + stolen-quote rejection proven.

- [x] **S02: Full DCAP verifier — chain verification, debug check, measurement, TCB stub** `risk:high` `depends:[S01]`
  > 27 tests (79 total). Validator DcapVerifier 7-step pipeline. All attacks rejected. Consensus.get_scores() wired.

- [x] **S03: Consensus integration + docker compose stack** `risk:medium` `depends:[S02]`
  > Server wired: _tee_publish_loop started alongside heartbeat. docker-compose.tee-dev.yml: MOCK_TEE=true, 1 bootnode + 1 validator + 2 miners.

## Boundary Map

### S01 → S02

Produces:
- `TeeQuote`: `{backend, measurement, nonce, report_data, timestamp, sig, raw_bytes}`
- `MockBackend.generate_quote(peer_id, epoch) → TeeQuote`
- `TdxBackend.generate_quote(peer_id, epoch) → TeeQuote` (stub calls real driver)
- `TeePublisher.publish(epoch)` → `nmap_put("tee_quote", "{epoch}:{peer_id}", quote.to_bytes())`
- DHT key schema: topic=`tee_quote`, key=`{epoch}:{peer_id}`
- Identity binding contract: `report_data = sha256(f"{peer_id}:{epoch}").encode()[:64]`

Consumes:
- nothing (first slice)

### S02 → S03

Produces:
- `DcapVerifier.verify(quote, peer_id, epoch) → float` — 0.0 / 0.5 / 1.0
- `DcapVerifier._check_identity(quote, peer_id, epoch) → bool`
- `DcapVerifier._check_debug_mode(quote) -> bool`
- `DcapVerifier._check_measurement(quote) -> bool`
- `DcapVerifier._verify_chain(quote) -> bool` (mock: HMAC; real: full x509 chain)
- `CollateralCache.get_tcb_info(fmspc) -> dict` (mock: fixture; real: PCS fetch)

Consumes:
- `TeeQuote` schema (S01)
- DHT publish contract (S01)

### S03 → (done)

Produces:
- `get_scores()` returning `tee_score`-weighted `SubnetNodeConsensusData` list
- `MIN_TEE_SCORE` env var respected
- docker-compose.yml with `MOCK_TEE=true` for bootnode + validator + 2 miners

Consumes:
- `DcapVerifier.verify()` (S02)
- DHT quote lookup (S01)
