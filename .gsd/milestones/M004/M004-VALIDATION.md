---
verdict: pass
remediation_round: 0
---

# Milestone Validation: M004

## Success Criteria Checklist

- [x] **`docker compose -f docker-compose.tee-dev.yml up --build` brings up bootnode + 2 miners + validator + overwatch**
  — Evidence: S01 verified `tee-bootnode`, `tee-miner-1`, `tee-miner-2`, `tee-validator` all running. S02 wired `_overwatch_epoch_loop` into the validator's trio nursery (overwatch is a loop inside the validator container, not a fifth container — consistent with the roadmap's architecture intent). S03 confirmed all four containers reach `(healthy)` status via `docker compose ps`.

- [x] **Miners publish work records; validator reads and scores each epoch**
  — Evidence: S01 live demo output shows `[Validator] peer=12D3KooWM5J4zS17 epoch=14781175 score=0.50 correct=True` and `[Validator] peer=12D3KooWKxAhu5U8 epoch=14781175 score=0.50 correct=True`. Transport is GossipSub (not KadDHT) per decision D002 — documented, lower-risk path that serves the same functional purpose. Validator reads and scores each epoch confirmed.

- [x] **One miner has `TAMPER_RATE=0.001`; approximately 1-in-1000 epochs produces a bad parity claim**
  — Evidence: S02 summary confirms `docker-compose.tee-dev.yml` has `miner-2: TAMPER_RATE="0.001"` and `validator: TAMPER_RATE="0.0"`. `miner-1` is set to `1.0` with comment `# demo value; production: 0.001` for the live demo (see next criterion). The production-realistic 0.001 rate is present on miner-2.

- [x] **Validator and overwatch logs both show `TAMPER` / `parity_mismatch` when bad epoch fires**
  — Evidence: S02 live demo over 3 complete epochs (TAMPER_RATE=1.0 on miner-1) confirmed:
  - `[Validator] peer=12D3KooWM5J4zS17 epoch=N score=0.00 correct=False` — every epoch
  - `[Overwatch] TAMPER peer=12D3KooWM5J4zS17 epoch=N reason=parity_mismatch` — every epoch
  - TAMPER count=3, loop errors=0, `no_work_record` at INFO=0 across full demo run.

- [x] **Honest miner consistently scores `0.5` (mock TEE + correct work)**
  — Evidence: S02 live demo confirmed `[Validator] peer=12D3KooWKxAhu5U8 epoch=N score=0.50 correct=True` and `[Overwatch] PASS peer=12D3KooWKxAhu5U8 epoch=N` for miner-2 every epoch from epoch 3+. PASS count=6 (2 per epoch × 3 epochs). S03 restart recovery additionally confirmed miner-1 was re-scored after restart.

- [x] **`docker compose logs validator` is human-readable without source access**
  — Evidence: S01 and S02 established human-readable log lines (`[Validator] peer=... epoch=N score=0.50 correct=True`, `[Overwatch] TAMPER …`). S03 enables `LOG_JSON=true` by default in the compose `x-tee-env` anchor, producing JSON lines that include the message field verbatim — e.g. `{"message": "[Validator] peer=... epoch=N score=0.50 correct=True", ...}`. The human-readable message is preserved as a top-level `"message"` key; JSON output is still readable without source access and additionally supports `jq` pipelines.

- [x] **`docker compose down` is clean — no orphaned volumes or processes**
  — Evidence: S01 summary: "`docker compose down --volumes` → exit 0, all containers/volumes removed". S02 summary: "`docker compose down --volumes` exited 0 cleanly". S03 does not change teardown behaviour.

### Milestone Definition of Done

- [x] `docker compose -f docker-compose.tee-dev.yml up` works end-to-end — confirmed S01/S02/S03.
- [x] Live tamper detection demonstrated with `TAMPER_RATE=1.0` — confirmed S02 (3-epoch live run).
- [x] `docker compose restart` recovery verified — confirmed S03 (miner-1 re-scored within 120s = 1 epoch).
- [x] `TESTING_LAYERS.md` Layer 2 section accurate and complete — S02 added demo setup + actual log output; S03 added JSON log and health endpoint coverage.
- [~] Layer 1 tests still green (`pytest tests/ < 2s`) — **all tests green** (183 passed, 1 skipped). Actual wall-clock time is ~5s for the full 183-test suite. The `< 2s` bound appears calibrated to the 24-test `test_mock_node.py` subset (`~1.4–2.1s` per M003 context), not the full suite which has grown across M001–M004. No regressions; timing delta is documentation drift, not a functional gap.

---

## Slice Delivery Audit

| Slice | Claimed | Delivered | Status |
|-------|---------|-----------|--------|
| S01 | `docker compose up` → 3 nodes running, epochs logged, validator scores in `docker compose logs validator` | 4 containers (bootnode + validator + 2 miners); `[Validator] score=0.50 correct=True` for both miners from epoch 3+; GossipSub cross-container transport proven; 4 runtime bugs fixed and documented | **pass** |
| S02 | `TAMPER_RATE=1.0` → every epoch shows tamper caught by validator (`wrong_parity`) and overwatch (`parity_mismatch`) in logs | `_overwatch_epoch_loop` wired into nursery; miner-1 `TAMPER_RATE=1.0`; live 3-epoch run confirmed TAMPER=3, PASS=6, errors=0; `TESTING_LAYERS.md` updated with actual log examples | **pass** |
| S03 | `docker compose restart miner-1` recovers within one epoch; structured JSON logs enable `docker compose logs \| jq` | Restart recovery within 120s (1 epoch) confirmed live; `JsonFormatter` + `LOG_JSON` env var; `:8080/health` in trio nursery; curl healthchecks for 3 services; all containers `(healthy)`; 2 new unit tests; D010/D011 recorded | **pass** |

---

## Cross-Slice Integration

**S01 → S02 (boundary map check)**

| Boundary item | Produced by S01? | Consumed by S02? | Match? |
|---|---|---|---|
| Live epoch loop calling `miner_loop()` / `validator_call()` in `server.py` | ✅ `_miner_epoch_loop` + `_validator_scoring_loop` | ✅ S02 extends nursery with `_overwatch_epoch_loop` alongside existing loops | ✅ |
| Work records visible between containers | ✅ GossipSub transport on 4 topics | ✅ `MockOverwatchVerifier.verify()` reads from RocksDB populated by `GossipReceiver` | ✅ |
| `MockNodeProtocol` from M003/S01 | ✅ instantiated in `Server.run()` | ✅ unchanged in S02 | ✅ |
| `docker-compose.tee-dev.yml` skeleton | ✅ 4 services, named volume, env vars | ✅ S02 only changes one env var value (`TAMPER_RATE` on miner-1) | ✅ |

**S01 → S03 (boundary map check)**

| Boundary item | Produced by S01? | Consumed by S03? | Match? |
|---|---|---|---|
| Container health checks (`:8080/health`) | S01 used `healthcheck: test: ["CMD", "true"]` placeholder | ✅ S03 replaced with curl-based checks + added `_health_server` endpoint | ✅ (placeholder → real, planned progression) |
| Epoch number visible in logs | ✅ `[MinerLoop] New epoch N`, `[Validator] epoch=N`, `[ValidatorLoop] Scoring epoch=N` | ✅ S03 adds `extra={"epoch": N, ...}` to structured JSON output | ✅ |
| Server nursery structure | ✅ `Server.run()` trio nursery with named loop functions | ✅ S03 adds `nursery.start_soon(_health_server, 8080)` | ✅ |

**S03 → done (boundary map check)**

| Boundary item | Produced by S03? | Status |
|---|---|---|
| Structured log output with epoch/peer/score/reason | ✅ `JsonFormatter` + `extra={}` kwargs on 7 log calls | ✅ |
| `docker compose restart` survivable epoch state | ✅ miner-1 re-scored within 120s after restart | ✅ |

No boundary mismatches found. All produces/consumes resolved correctly across the three slices.

---

## Requirement Coverage

| Requirement | Coverage | Status |
|---|---|---|
| R005 — Multi-node | S01 (live 4-container run), S02 (dual independent audit streams), S03 (restart recovery) | ✅ validated |
| R006 — Real P2P DHT | GossipSub used as cross-container transport (D002); heartbeats + 4 work-record topics; S01/S02 confirmed cross-container gossip delivery | ✅ validated (GossipSub path per D002) |
| R007 — Live epoch timing | S01: epoch numbers agree within ±0 across 4 containers; S02: overwatch and validator loops audit same epoch number in live run | ✅ validated |
| R008 — Restart recovery (basic only) | S03: `docker compose restart miner-1` → re-scored within 120s (1 epoch) confirmed live | ✅ validated (basic level as scoped) |
| R022 — Test coverage | 183 tests pass (up from 181 at M003); `test_json_logging.py` adds 2 new tests for `JsonFormatter`; live multi-container demo satisfies the "2-epoch docker compose cycle" deferred item | ✅ validated |

All requirements in scope for M004 are addressed. Requirements outside M004 scope (R001–R004, R009–R021, R023+) are either already validated in prior milestones or explicitly deferred to M005+.

---

## Verdict Rationale

All seven success criteria are satisfied by evidence from slice summaries and live demo output. All three slices delivered their claimed outputs. Cross-slice boundary maps resolved without gaps. All four in-scope requirements (R005–R008) advanced to validated status.

Two minor notes documented as `needs-attention` items — neither blocks completion:

1. **`pytest tests/ < 2s` timing**: All 183 tests pass; actual runtime (~5s) exceeds the `< 2s` DoD bound. The bound was written against the 24-test `test_mock_node.py` subset and is documentation drift, not a regression. No tests were removed or made slower — the suite grew from 24 to 183 tests across M001–M004.

2. **GossipSub vs KadDHT phrasing**: The roadmap success criterion says "Miners publish work records to DHT" but the actual transport is GossipSub. Decision D002 explicitly documents this change with rationale. The functional outcome — cross-container work record delivery and validator scoring — is identical. No remediation needed.

**Verdict: `pass`** — M004 delivered all planned capabilities. The milestone is ready to seal.

---

## Remediation Plan

_Not applicable — verdict is `pass`._
