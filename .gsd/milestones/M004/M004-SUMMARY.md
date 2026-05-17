---
id: M004
provides:
  - docker compose -f docker-compose.tee-dev.yml up --build brings up bootnode + validator + miner-1 + miner-2; all four containers reach (healthy) status
  - _miner_epoch_loop: calls MockNodeProtocol.miner_loop(epoch) and publishes TEE quote, RA-TLS cert, work record over GossipSub each epoch
  - _validator_scoring_loop: waits 30s on startup, scores all non-self peers per epoch via validator_call() + MockNodeScoring.score_peer(); emits [Validator] log lines
  - _overwatch_epoch_loop: waits 35s on startup, audits all non-self peers per epoch via MockOverwatchVerifier.verify(); emits [Overwatch] TAMPER/PASS log lines
  - GossipSub cross-container transport on 4 topics (heartbeat, tee_quote, ratls_cert, mock_work) with RocksDB storage keyed by {epoch}:{peer_id}
  - Shared mock-chain SQLite (WAL mode) on named Docker volume with correct ownership
  - TAMPER_RATE=1.0 on miner-1 for demo; every epoch caught by both validator (score=0.00 correct=False) and overwatch (TAMPER reason=parity_mismatch)
  - stdlib-only JsonFormatter in subnet/utils/logging.py; LOG_JSON env var wires formatter to 3 named loggers with propagate=False
  - _health_server/_health_handler serving {"status":"ok"} on :8080/health via raw trio TCP sockets; wired into Server.run() nursery for non-bootstrap nodes
  - curl-based Docker healthchecks for validator/miner-1/miner-2 (start_period 30s)
  - docker compose restart miner-1 recovery: miner-1 re-scored within 120s (one epoch) confirmed live
  - TESTING_LAYERS.md Layer 2 section: demo setup, expected log output, JSON log pipeline, restart recovery notes
key_decisions:
  - D001: Shared SQLite volume (WAL mode) + MOCK_CHAIN_DB_PATH env var for mock chain state across containers
  - D002: GossipSub (not KadDHT put/get) for cross-container work record transport — follows proven heartbeat pattern, lower integration risk
  - D004: Application-layer DNS resolution in bootstrap.py — workaround for py-libp2p /dns4/ multiaddr limitation
  - D005: Dockerfile mkdir /app/mock_chain before USER directive to pre-seed Docker volume ownership
  - D010: _health_server uses raw trio TCP sockets — no new HTTP library dependencies
  - D011: curl added to Dockerfile production stage — multi-stage builds discard builder-stage packages
patterns_established:
  - Named volume + WAL mode for shared SQLite across containers; Dockerfile must pre-create directory with correct ownership before USER directive
  - GossipSub message handler pattern: deserialise → dedup (in-memory set) → nmap_set to RocksDB; lazy imports to avoid circular import risk
  - Trio-safe epoch loop pattern: poll epoch, do work, Cancelled re-raise, non-Cancelled exception guard with 10s sleep, move_on_after sleep 5s
  - Three-loop nursery: _miner_epoch_loop + _validator_scoring_loop + _overwatch_epoch_loop running concurrently inside Server.run() nursery
  - LOG_JSON=true attaches JsonFormatter to named loggers with propagate=False; extra={} kwargs at call site carry epoch/peer/score/reason fields
  - _health_server/_health_handler split: outer function opens trio listener, inner handler serves each connection; skips empty receive_some (TCP probes)
  - docker compose logs --no-log-prefix <service> | grep '"score"' | jq '.score' — correct jq pipeline (--no-log-prefix strips container prefix)
observability_surfaces:
  - "[Validator] peer=<16chars> epoch=N score=0.50 correct=True — primary honest-miner signal; one line per miner per epoch from epoch 3+"
  - "[Overwatch] TAMPER peer=<16chars> epoch=N reason=parity_mismatch — WARNING; fires every epoch for miner-1 with TAMPER_RATE=1.0"
  - "[Overwatch] PASS peer=<16chars> epoch=N — INFO; fires every epoch for miner-2"
  - "docker compose -f docker-compose.tee-dev.yml logs validator | grep '[Overwatch]\\|[Validator]' — single command for both audit streams"
  - "docker compose ps — all four containers (healthy) after up --build"
  - "docker compose exec miner-1 curl -sf http://localhost:8080/health → {\"status\":\"ok\"}"
  - "docker compose logs --no-log-prefix validator | grep '\"score\"' | jq '.score' — JSON pipeline confirmation"
requirement_outcomes:
  - id: R022
    from_status: validated
    to_status: validated
    proof: "183 tests pass (1 skipped) — up from 181 at M003. test_json_logging.py adds 2 new tests for JsonFormatter. Live multi-container run satisfies the 'two-epoch docker compose cycle (Layer 2 — deferred to M004)' item from original R022 validation criteria: [Validator] score=0.50 confirmed for both miners over multiple epochs in S01; tamper detection over 3 epochs in S02; restart recovery within 120s in S03."
duration: ~3.5h total across 3 slices (S01: ~2h, S02: ~45min, S03: ~40min)
verification_result: passed
completed_at: 2026-03-17
---

# M004: Layer 2 — Docker Network Integration

**Three-slice milestone that built a live 4-container subnet: S01 established multi-node epoch scoring over GossipSub, S02 wired overwatch to demonstrate tamper detection every epoch with `TAMPER_RATE=1.0`, and S03 added structured JSON logging, a `:8080/health` endpoint, and confirmed `docker compose restart` recovery within one epoch.**

## What Happened

M004 took the in-memory `MockNodeProtocol` and `MockOverwatchVerifier` from M003 and promoted them to a live multi-container environment over three slices, each adding a layer of capability and operational maturity.

**S01 — Multi-node epoch loop.** The foundation required four components working together: a shared mock chain (SQLite in WAL mode on a named Docker volume, accessed via `MOCK_CHAIN_DB_PATH`), GossipSub cross-container transport (extended `GossipReceiver` from 1 to 4 topics — heartbeat, tee_quote, ratls_cert, mock_work — storing records to RocksDB with `{epoch}:{peer_id}` keys), two module-level epoch loops in `server.py` (`_miner_epoch_loop` calling `MockNodeProtocol.miner_loop(epoch)` and publishing gossip; `_validator_scoring_loop` waiting 30s for mesh formation then scoring all non-self peers via `validator_call()` + `MockNodeScoring.score_peer()`), and four runtime bugs that only surfaced in containers: Docker volume ownership (`root:root` vs `apiuser` — fixed in Dockerfile), py-libp2p's inability to resolve `/dns4/` multiaddrs (fixed with `_resolve_dns_multiaddr()` in `bootstrap.py`), `MockNodeScoring()` requiring explicit `db/subnet_id/config` args (not no-arg), and `SubnetNodeInfo.peer_info` being a `PeerInfo` object not a dict (fixed with `hasattr` branch). After fixes: `[Validator] peer=... epoch=N score=0.50 correct=True` for both miners from epoch 3 onward.

**S02 — Live tamper detection.** `MockOverwatchVerifier` existed and was unit-tested in M003 but was never called in a running server. Three surgical changes to `server.py` wired it in: importing `MockOverwatchVerifier`, adding `_overwatch_epoch_loop` (following the established trio-safe pattern — 35s startup wait, epoch poll, iterate peers, call `verify()`, log TAMPER at WARNING / PASS at INFO / no_work_record at DEBUG), and adding `nursery.start_soon(_overwatch_epoch_loop, ...)` immediately after the validator call. The 5s extra startup delay vs the validator's 30s gives GossipSub mesh formation a full window before the first audit. Setting miner-1's `TAMPER_RATE` to `1.0` in the compose file produced the demo: over 3 complete epochs (14781189–14781191), every epoch produced exactly one `[Validator] score=0.00 correct=False` (miner-1) and one `[Overwatch] TAMPER reason=parity_mismatch` (overwatch catches miner-1), alongside `[Validator] score=0.50 correct=True` and `[Overwatch] PASS` for miner-2. TAMPER=3, PASS=6, loop errors=0, no_work_record at INFO=0.

**S03 — Observability and restart recovery.** A stdlib-only `JsonFormatter` was added to `subnet/utils/logging.py` — it builds ISO-8601 UTC timestamp + level + logger + message, then merges non-reserved `record.__dict__` keys as top-level extra fields using a frozenset of 22 stdlib-reserved names. `run_node.py` attaches the formatter to 3 named loggers when `LOG_JSON` is `1/true/yes`, with `propagate=False` to prevent the root handler from emitting duplicate non-JSON lines. Seven `extra={}` kwargs were added to the epoch loop log calls in `server.py`. A `_health_server`/`_health_handler` pair using raw trio TCP sockets (no new dependencies) was added and wired into the nursery for non-bootstrap nodes, serving `{"status":"ok"}` on `:8080/health`. Docker healthchecks for the three non-bootstrap containers were upgraded from `["CMD", "true"]` to curl-based checks. A deviation from plan was discovered: `curl` was only in the Dockerfile builder stage, not the production `python:3.11-slim` stage — all three containers reported `(unhealthy)` until `curl` was added to the production `apt-get install`. After rebuild, all four containers reached `(healthy)`. Restart recovery was confirmed live: `docker compose restart miner-1` → `[Validator]` lines for miner-1's peer_id reappeared within 120s.

## Cross-Slice Verification

**Success criterion 1: `docker compose -f docker-compose.tee-dev.yml up --build` brings up bootnode + 2 miners + validator + overwatch**
✅ S01: four containers start and run (bootnode, validator, miner-1, miner-2). Overwatch is `_overwatch_epoch_loop` running inside the validator container's nursery — consistent with the architecture intent (not a separate container). S03: `docker compose ps` shows all four containers `(healthy)`.

**Success criterion 2: Miners publish work records; validator reads and scores each epoch**
✅ S01 live demo: `[Validator] peer=12D3KooWM5J4zS17 epoch=14781175 score=0.50 correct=True` and `[Validator] peer=12D3KooWKxAhu5U8 epoch=14781175 score=0.50 correct=True`. Transport is GossipSub per decision D002 (documented deviation from "DHT" phrasing — same functional outcome).

**Success criterion 3: One miner has `TAMPER_RATE=0.001`**
✅ `grep TAMPER_RATE docker-compose.tee-dev.yml` → validator=0.0, miner-1=1.0 (demo; comment notes production: 0.001), miner-2=0.001.

**Success criterion 4: Validator and overwatch logs both show `TAMPER` / `parity_mismatch`**
✅ S02 live demo (3 epochs): `[Validator] peer=12D3KooWM5J4zS17 epoch=N score=0.00 correct=False` + `[Overwatch] TAMPER peer=12D3KooWM5J4zS17 epoch=N reason=parity_mismatch` — every epoch for miner-1. TAMPER=3, errors=0.

**Success criterion 5: Honest miner consistently scores `0.5`**
✅ S02: `[Validator] peer=12D3KooWKxAhu5U8 epoch=N score=0.50 correct=True` + `[Overwatch] PASS peer=12D3KooWKxAhu5U8 epoch=N` — every epoch for miner-2. PASS=6 (2 per epoch × 3 epochs).

**Success criterion 6: `docker compose logs validator` is human-readable without source access**
✅ S01/S02: human-readable `[Validator]`/`[Overwatch]` prefixed lines. S03: `LOG_JSON=true` emits JSON lines with message as a top-level key — `{"message": "[Validator] peer=... score=0.50 correct=True", "epoch": N, ...}`. Readable with or without `jq`.

**Success criterion 7: `docker compose down` is clean**
✅ S01: `docker compose down --volumes` → exit 0. S02: `docker compose down --volumes` exited 0 cleanly. S03 does not change teardown.

**Definition of Done:**
- ✅ `docker compose up` works end-to-end — S01/S02/S03
- ✅ Live tamper detection with `TAMPER_RATE=1.0` — S02 (3-epoch live run)
- ✅ `docker compose restart` recovery — S03 (miner-1 re-scored within 120s = 1 epoch)
- ✅ `TESTING_LAYERS.md` Layer 2 section accurate and complete — S02 (demo setup + actual log output); S03 (JSON logs + health endpoint)
- ✅ Layer 1 tests still green — 183 passed, 1 skipped (`pytest tests/`). The `< 2s` DoD target reflects the 24-test `test_mock_node.py` subset (~1.4–2.1s); the full 183-test suite runs in ~5s. No regressions; timing delta is documentation drift from suite growth across M001–M004.

All slices complete: S01 ✅, S02 ✅, S03 ✅. All slice summaries exist. All cross-slice boundaries resolved (S01 produces the epoch loops and gossip transport consumed by S02; S01 produces the nursery structure consumed by S03; S03 closes the milestone).

## Requirement Changes

- R022: validated → validated — Additional evidence: test count grew from 181 to 183 (2 new tests for `JsonFormatter`); live multi-container run satisfies the "two-epoch docker compose cycle (Layer 2 — deferred to M004)" deferred item from the original R022 validation criteria; `[Validator] score=0.50` confirmed across multiple epochs in S01; tamper detection across 3 full epochs in S02; restart recovery within 120s in S03.

*(All other requirements validated in prior milestones — R001–R021 — are unchanged. R005, R006, R007 in the roadmap's internal notation refer to multi-node, P2P DHT, and epoch timing — these are functional capabilities demonstrated in M004 but not tracked as distinct requirements in REQUIREMENTS.md, which has its own R005–R008 for debug-mode detection, DCAP chain verification, TCB status, and PCCS collateral.)*

## Forward Intelligence

### What the next milestone should know

- The three-loop nursery in `Server.run()` (`_miner_epoch_loop`, `_validator_scoring_loop`, `_overwatch_epoch_loop`, `_health_server`) is the stable server architecture going into M005. Any chain integration should extend this nursery pattern, not replace it.
- Mock chain state lives in a shared SQLite file on a named Docker volume. Only the bootnode resets it on startup (`reset_db=True` logic in `run_node.py`). M005 will replace this with real chain calls — the `MOCK_CHAIN_DB_PATH` env var and WAL mode can be retired, but the `_resolve_dns_multiaddr()` workaround in `bootstrap.py` remains needed until py-libp2p fixes upstream `/dns4/` support.
- `LOG_JSON=true` is active in all containers via the `x-tee-env` anchor. Any new named logger added to `run_node.py`'s LOG_JSON block will need its own `propagate=False` or it will emit a duplicate non-JSON line that breaks `jq` pipelines.
- The `--no-log-prefix` flag is mandatory for `docker compose logs | jq` pipelines — without it, the `tee-validator  | ` prefix causes parse errors. This is in KNOWLEDGE.md.
- Epoch cadence in the mock chain is ~120s. The S02 plan's 65s demo estimate was wrong — observers need ~7min after `docker compose up` for 3 tamper events. A `MOCK_CHAIN_EPOCH_SECONDS` env var would make demos faster without changing internals.

### What's fragile

- **GossipSub cold-start window** — The 30s (validator) / 35s (overwatch) startup delays are calibrated for the current 4-container topology. If M005 adds containers or changes bootnode timing, these delays may need adjustment. Symptom of too-short delay: first-epoch false positives or zero scores that shouldn't appear.
- **Port 8080 hardcoded** — `_health_server` binds `:8080` with no port-conflict handling. If another service occupies :8080, the nursery crashes without a useful error. Add `try/except OSError` if co-hosted deployments are needed.
- **propagate=False on exactly 3 loggers** — `run_node.py` configures only `miner_epoch_loop`, `validator_scoring_loop`, and `overwatch_epoch_loop`. Any new epoch loop added in M005 must replicate the LOG_JSON pattern or its output will have duplicate non-JSON lines breaking `jq`.
- **MockNodeScoring wiring** — `MockNodeScoring(db=self.db, subnet_id=..., config=None)` passes the server's RocksDB instance. If M005 changes how scoring state is stored, this wiring needs updating.

### Authoritative diagnostics

- `docker compose -f docker-compose.tee-dev.yml logs validator | grep "\[Overwatch\]\|\[Validator\]"` — single command showing both audit streams; if TAMPER lines absent when TAMPER_RATE=1.0, check overwatch loop wiring
- `docker compose ps` — fastest readiness check; all four containers must show `(healthy)` before running jq queries
- `docker compose logs --no-log-prefix validator | grep '"score"' | jq '.score'` — end-to-end JSON pipeline smoke test; confirms formatter active + no duplicate lines
- `python3 -m pytest tests/ -q --tb=short` → 183 passed, 1 skipped — Layer 1 regression baseline
- `sqlite3 <db_path> "PRAGMA journal_mode;"` → must return `wal`; if `delete`, WAL fix didn't apply

### What assumptions changed

- **"GossipSub only needs heartbeats"** — S01 expanded it to 4 topics; GossipReceiver is now the canonical gossip subscription point for the server
- **"MockNodeScoring() takes no args"** — inherits `BaseNodeScoring.__init__` which requires `db/subnet_id/config`; always pass explicitly
- **"node.peer_info is a dict"** — `SubnetNodeInfo.__post_init__` converts dicts to `PeerInfo` objects; use `hasattr(peer_info, "peer_id")`
- **"libp2p handles dns4 multiaddrs"** — it does not; `_resolve_dns_multiaddr()` in bootstrap.py is a permanent workaround
- **"curl is in the production image"** — it was only in the builder stage; multi-stage builds require explicit reinstall in the production stage
- **"epoch cadence is ~30s"** — actual mock chain epochs are ~120s; plan's 65s demo estimate was based on wrong assumption

## Files Created/Modified

- `subnet/hypertensor/mock/mock_db.py` — WAL pragma in `_connect()`; env-var path resolution in `__init__` via `MOCK_CHAIN_DB_PATH`
- `subnet/node/mock.py` — `TAMPER_RATE` reads from env var with safe fallback
- `subnet/utils/gossipsub/gossip_receiver.py` — 3 additional topic handlers (`_handle_tee_quote`, `_handle_ratls_cert`, `_handle_work_record`); 3 dedup sets; dispatch wiring
- `subnet/utils/connections/bootstrap.py` — `_resolve_dns_multiaddr()` pre-resolves `/dns4/` to `/ip4/` before libp2p dial
- `subnet/utils/logging.py` — New: stdlib-only `JsonFormatter` with frozenset reserved-key exclusion (~70 lines)
- `subnet/server/server.py` — `_miner_epoch_loop`, `_validator_scoring_loop`, `_overwatch_epoch_loop`, `_health_server`, `_health_handler` module-level async functions; `MockNodeProtocol`/`MockNodeScoring`/`MockOverwatchVerifier` instantiation in `Server.run()`; `extra={}` kwargs on 7 log calls; `nursery.start_soon` calls for all four loops
- `subnet/cli/run_node.py` — 11-line `LOG_JSON` block attaching `JsonFormatter` to 3 named loggers with `propagate=False`
- `docker-compose.tee-dev.yml` — `mock-chain` named volume on all 4 services; `MOCK_CHAIN_DB_PATH`/`TAMPER_RATE`/`LOG_JSON` env vars; curl-based healthchecks for validator/miner-1/miner-2; bootnode stays `["CMD", "true"]`; miner-1 `TAMPER_RATE=1.0` for demo
- `Dockerfile` — `mkdir -p /app/mock_chain` in useradd RUN layer (volume ownership); `curl` in production stage `apt-get install` (healthcheck support)
- `tests/test_json_logging.py` — New: 2 unit tests for `JsonFormatter` (basic format + extra fields)
- `TESTING_LAYERS.md` — Layer 2 section: demo setup with TAMPER_RATE=1.0, expected log output with actual observed lines, JSON log pipeline, restart recovery notes
- `.gsd/KNOWLEDGE.md` — Added: py-libp2p dns4 limitation, Docker volume ownership, SubnetNodeInfo.peer_info type, MockNodeScoring args, multi-stage Dockerfile curl gotcha, `--no-log-prefix` for jq
- `.gsd/DECISIONS.md` — D001 (shared SQLite WAL), D002 (GossipSub transport), D004 (DNS multiaddr), D005 (Dockerfile volume ownership), D010 (raw trio TCP health server), D011 (curl in production stage)
