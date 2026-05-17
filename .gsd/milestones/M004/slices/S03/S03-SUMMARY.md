---
id: S03
parent: M004
milestone: M004
provides:
  - stdlib-only JsonFormatter in subnet/utils/logging.py producing single-line JSON with extra fields
  - LOG_JSON env var wiring in run_node.py: JsonFormatter attached to 3 named loggers with propagate=False
  - extra={epoch,peer,score,reason} kwargs on 7 key log calls across all three epoch loops in server.py
  - _health_server/_health_handler async functions in server.py serving {"status":"ok"} on :8080/health
  - nursery.start_soon(_health_server, 8080) in non-bootstrap block of Server.run()
  - LOG_JSON="true" in x-tee-env anchor in docker-compose.tee-dev.yml (activates JSON logging for all services)
  - curl-based healthchecks for validator/miner-1/miner-2 with start_period=30s; bootnode stays ["CMD","true"]
  - curl added to Dockerfile production stage (fixes multi-stage build gap)
  - Restart recovery: miner-1 re-scored by validator within 120s after docker compose restart
  - Unit tests for JsonFormatter (2 passing)
  - Two KNOWLEDGE.md entries: multi-stage Dockerfile curl gotcha; docker compose logs --no-log-prefix for jq
  - D010 and D011 recorded in DECISIONS.md
requires:
  - slice: S01
    provides: Server.run() nursery structure; named epoch loop functions; docker-compose.tee-dev.yml services
affects: []
key_files:
  - subnet/utils/logging.py
  - subnet/cli/run_node.py
  - subnet/server/server.py
  - docker-compose.tee-dev.yml
  - Dockerfile
  - tests/test_json_logging.py
key_decisions:
  - D010: _health_server uses raw trio TCP sockets (no HTTP library) — no new dependencies
  - D011: curl added to production stage of Dockerfile — multi-stage builds discard builder-stage packages
  - JsonFormatter merges all non-reserved LogRecord __dict__ keys as extra fields via frozenset exclusion
  - propagate=False on 3 operational loggers prevents double-logging (non-JSON root handler line would break jq)
  - _health_handler skips response on empty receive_some (TCP probe connections that close without data)
patterns_established:
  - Named loggers configured in run_node.py before trio.run() — log calls in server.py pick up formatter transparently
  - extra={} fields on individual log calls (not LoggerAdapter) keeps call sites minimal
  - _health_server/_health_handler split: outer nursery opens listeners, inner handler loops on accept
  - docker compose logs --no-log-prefix <service> | grep '"score"' | jq '.score' — correct jq pipeline
observability_surfaces:
  - "docker compose logs --no-log-prefix validator | grep '\"score\"' | jq '.score' → 0.5 lines"
  - "docker compose exec miner-1 curl -sf http://localhost:8080/health → {\"status\":\"ok\"}"
  - "docker compose ps → shows (healthy)/(unhealthy) per container"
  - "LOG_JSON=true python3 -m subnet.cli.run_node ... | jq 'select(.logger==\"validator_scoring_loop\") | {epoch,peer,score}'"
drill_down_paths:
  - .gsd/milestones/M004/slices/S03/tasks/T01-SUMMARY.md
  - .gsd/milestones/M004/slices/S03/tasks/T02-SUMMARY.md
duration: ~40min (T01: 15m, T02: 25m)
verification_result: passed
completed_at: 2026-03-17
---

# S03: Restart recovery + observability

**Structured JSON logging via `LOG_JSON=true`, a `:8080/health` endpoint wired into the trio nursery, Docker healthchecks for all non-bootstrap containers, and confirmed `docker compose restart miner-1` recovery within one epoch.**

## What Happened

S03 delivered two orthogonal but related capabilities: structured observability and operational resilience.

**T01 — JsonFormatter + structured log fields** (15 min)

A stdlib-only `JsonFormatter(logging.Formatter)` was created in `subnet/utils/logging.py`. It builds a base dict with ISO-8601 UTC timestamp (millisecond precision), level, logger name, and message, then merges any non-reserved `record.__dict__` keys as extra fields at the top level. A frozenset of 22 stdlib-reserved LogRecord keys excludes internal noise. The formatter is wired in `run_node.py` via an 11-line `LOG_JSON` block: when `LOG_JSON` is `1`, `true`, or `yes`, the formatter is attached to the three named operational loggers (`miner_epoch_loop`, `validator_scoring_loop`, `overwatch_epoch_loop`) and `propagate=False` is set on each. The `propagate=False` is non-negotiable: without it the root handler also fires and emits a non-JSON formatted line to stdout, breaking all `jq` pipelines.

Structured `extra={}` kwargs were added to 7 log calls in `server.py`:
- `_miner_epoch_loop`: 4 calls carry `extra={"epoch": current_epoch}`
- `_validator_scoring_loop`: 1 call carries `extra={"epoch": N, "peer": peer_id[:16], "score": round(s, 2)}`
- `_overwatch_epoch_loop`: 2 calls carry `extra={"epoch": N, "peer": peer_id[:16]}` plus `"reason"` on tamper warnings

Two unit tests (`tests/test_json_logging.py`) were written covering basic format validation and extra-field passthrough. All 183 tests pass (184 collected, 1 skipped).

**T02 — Health endpoint + Docker healthchecks + restart recovery proof** (25 min)

`_health_server(port)` and `_health_handler(listener)` were added at module level in `server.py`. The handler responds with a raw `HTTP/1.1 200 OK` response over trio TCP sockets — no new dependencies. A key correctness detail: `receive_some` returning `b""` indicates a TCP probe connection (curl's pre-connection check); the handler skips sending a response on empty reads rather than treating it as an error. `nursery.start_soon(_health_server, 8080)` was added inside the `if not self.is_bootstrap:` block in `Server.run()` — the bootnode deliberately does not start the health server.

`docker-compose.tee-dev.yml` received two changes: `LOG_JSON: "true"` in the `x-tee-env` anchor (propagates to all four services), and curl-based healthchecks for `validator`, `miner-1`, and `miner-2` (`CMD-SHELL curl -sf http://localhost:8080/health || exit 1`, interval 30s, timeout 5s, retries 3, start_period 30s). Bootnode healthcheck stays `["CMD", "true"]`.

A deviation was discovered during execution: `curl` existed only in the Dockerfile builder stage, not the production `python:3.11-slim` stage. All three non-bootstrap containers immediately reported `(unhealthy)` after the first build. Fix: `curl` added to the production stage's `apt-get install`. After rebuild, all four containers reached `(healthy)`.

Restart recovery was verified live: after `docker compose restart miner-1`, within 120 seconds the validator logs showed `[Validator]` lines for `peer=12D3KooWM5J4zS17` (miner-1's peer_id) at epoch 14781206 — confirming DHT re-registration, GossipSub mesh re-join, and validator scoring all happen within one epoch window.

## Verification

```
# Unit tests for JsonFormatter
python3 -m pytest tests/test_json_logging.py -v
→ 2 passed in 0.02s

# Import smoke checks
python3 -c "from subnet.utils.logging import JsonFormatter; print('ok')"  → ok
python3 -c "from subnet.server.server import _health_server; print('ok')"  → ok

# Health server wired check
python3 -c "import inspect, subnet.server.server as s; assert '_health_server' in inspect.getsource(s.Server.run); print('health_server wired: OK')"
→ health_server wired: OK

# JSON formatter in-process
LOG_JSON=true python3 -c "[...epoch=1, peer='12D3KooWtest', score=0.5...]"
→ PASS: JSON parseable with extra fields

# Full test suite — no regressions
python3 -m pytest tests/ -q --tb=short
→ 183 passed, 1 skipped in 5.02s

# Bootnode healthcheck stays ["CMD","true"]
grep -A3 'bootnode:' docker-compose.tee-dev.yml | grep -A3 'healthcheck:' | grep 'test:'
→ test: ["CMD", "true"]

# Live (with running compose stack — verified by executor):
docker compose ps → tee-bootnode (healthy), tee-miner-1 (healthy), tee-miner-2 (healthy), tee-validator (healthy)
docker compose exec miner-1 curl -sf http://localhost:8080/health → {"status":"ok"}
docker compose logs --no-log-prefix validator | grep '"score"' | jq '.score' → 0.5 lines
docker compose restart miner-1 && sleep 120 → [Validator] peer=12D3KooWM5J4zS17 epoch=14781206 reappears
```

## Requirements Advanced

- R008 (restart recovery — basic only) — basic `docker compose restart` recovery within one epoch is now proven at the live runtime level (miner-1 re-scored within 120s after restart). The "basic only" qualifier in the roadmap is satisfied.

## Requirements Validated

- R022 (test coverage) — now at 183 passed, 1 skipped (up from 181). `tests/test_json_logging.py` adds explicit coverage for the JSON formatter.

## New Requirements Surfaced

None.

## Requirements Invalidated or Re-scoped

None.

## Deviations

1. **Dockerfile production stage missing `curl`**: The S03 plan noted "curl is already present in the image (Dockerfile line 13)" — that line was in the builder stage. The production `python:3.11-slim` stage only had `libgomp1`. Required a second `docker compose up --build` cycle after adding `curl` to the production `apt-get install`. Documented in KNOWLEDGE.md (multi-stage build: curl in builder ≠ curl in production).

2. **Pre-flight diagnostic additions to S03-PLAN.md**: Executor added failure-path diagnostic checks (steps 7–10) and the `--no-log-prefix` jq pipeline note to the plan's Verification and Observability sections. These were discovered during execution and recorded for future reference.

## Known Limitations

- `miner-1` (TAMPER_RATE=1.0 from S02) scores 0.00 after restart with `correct=False` — expected behaviour, not a bug. The restart recovery proof is that miner-1 is being scored at all, which confirms network re-join.
- `jq '.score'` without a `grep '"score"'` filter outputs `null` for epoch-loop status lines that lack a `score` field. The correct pipeline is `... | grep '"score"' | jq '.score'`.
- First 1–2 epochs after restart: validator may score miner-1 at 0.00 due to GossipSub cold-start (mesh not yet fully formed). Epoch 3+ shows stable scoring. This is the same cold-start behaviour documented in KNOWLEDGE.md for initial stack startup.
- Health server on port 8080 is hardcoded. If another process occupies :8080, the nursery will crash. No port-conflict handling exists.

## Follow-ups

- M004 milestone DoD is now fully satisfied — `TESTING_LAYERS.md` Layer 2 section should be reviewed/updated to reflect S03 additions (health endpoint, JSON logs) before M005 planning.
- If health endpoint grows (epoch count, peer count, mesh status), replace raw TCP handler with a lightweight async HTTP library (hypercorn/starlette). D010 explicitly marks this revisable.
- Port-conflict guard for :8080 could be added if multi-tenant or co-hosted deployments are needed.

## Files Created/Modified

- `subnet/utils/logging.py` — New: stdlib-only `JsonFormatter` class with frozenset reserved-key exclusion (~70 lines with docstrings)
- `subnet/cli/run_node.py` — Added 11-line `LOG_JSON` block attaching `JsonFormatter` to 3 named loggers with `propagate=False`
- `subnet/server/server.py` — Added `_health_handler` + `_health_server` module-level functions; `nursery.start_soon(_health_server, 8080)` in non-bootstrap block; `extra={}` kwargs on 7 log calls
- `docker-compose.tee-dev.yml` — Added `LOG_JSON: "true"` to `x-tee-env`; updated validator/miner-1/miner-2 healthchecks to `curl -sf http://localhost:8080/health` with `start_period: 30s`
- `Dockerfile` — Added `curl` to production stage `apt-get install`
- `tests/test_json_logging.py` — New: 2 unit tests for `JsonFormatter` (basic format + extra fields)
- `.gsd/KNOWLEDGE.md` — Added: multi-stage Dockerfile curl gotcha; `docker compose logs --no-log-prefix` for jq
- `.gsd/DECISIONS.md` — Added D010 (raw trio TCP for health server) and D011 (curl in production stage)
- `.gsd/milestones/M004/slices/S03/S03-PLAN.md` — Pre-flight fixes: failure-path diagnostic steps 7–10, `--no-log-prefix` pipeline note

## Forward Intelligence

### What the next slice should know
- JSON logging is already active in all containers via `LOG_JSON: "true"` in the `x-tee-env` anchor. Any new named logger added to `run_node.py` will need its own `propagate=False` block if it should emit clean JSON — the current block only covers the three operational loggers.
- The `--no-log-prefix` flag is mandatory for `jq` pipelines against `docker compose logs`. Without it, the container name prefix (`tee-validator  | `) causes a parse error. This is in KNOWLEDGE.md.
- All four containers reach `(healthy)` status — `docker compose ps` can be used as a reliable readiness check in CI/automation scripts.
- M004 is now fully done. The next milestone (M005) starts with a live multi-container stack that has structured logs, health endpoints, and proven restart recovery.

### What's fragile
- Port 8080 hardcoded in `_health_server` — if a future slice adds another service on :8080, the nursery will crash without a useful error message. Add a `try/except OSError` in `_health_server` if this becomes a concern.
- `propagate=False` on only 3 loggers — any new epoch loop added in future slices must replicate the LOG_JSON pattern in `run_node.py` or its output will not be valid JSON (root handler will emit a plain-text duplicate).

### Authoritative diagnostics
- `docker compose ps` — fastest way to confirm all containers are healthy after `up --build`
- `docker compose logs --no-log-prefix <service> | grep '"score"' | jq '.score'` — confirms JSON pipeline works end-to-end (formatter active + no duplicate lines)
- `python3 -c "import inspect, subnet.server.server as s; assert '_health_server' in inspect.getsource(s.Server.run)"` — confirms health server is wired in nursery without needing a running container

### What assumptions changed
- "curl is already present in the image" — assumed to mean the production stage; it was only in the builder stage. Multi-stage builds are a consistent footgun: always verify each stage's installed packages independently.
- The `--no-log-prefix` requirement for `jq` pipelines was not in the original plan — discovered during live verification. Added to KNOWLEDGE.md and the plan's verification section.
