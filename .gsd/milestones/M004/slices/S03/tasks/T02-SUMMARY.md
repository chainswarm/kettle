---
id: T02
parent: S03
milestone: M004
provides:
  - _health_server async function in subnet/server/server.py serving {"status":"ok"} on :8080/health
  - _health_handler TCP connection handler with empty-read safety for TCP probe connections
  - nursery.start_soon(_health_server, 8080) in non-bootstrap block of Server.run()
  - LOG_JSON="true" in x-tee-env anchor in docker-compose.tee-dev.yml (activates T01 JsonFormatter for all services)
  - curl-based healthchecks for validator/miner-1/miner-2 with start_period=30s and interval=30s
  - curl added to Dockerfile production stage (was only in builder stage)
  - Restart recovery proof: miner-1 scored by validator within 120s after docker compose restart
key_files:
  - subnet/server/server.py
  - docker-compose.tee-dev.yml
  - Dockerfile
key_decisions:
  - D010: _health_server uses raw trio TCP sockets (no HTTP library) — trivial endpoint, no new deps
  - D011: curl added to production stage — multi-stage build discards builder-stage packages
patterns_established:
  - _health_server/_health_handler pattern: outer server opens TCP listeners, inner handler loops on accept; empty receive_some returns b"" for TCP probe connections (curl healthcheck) — must skip response on empty read, not treat as error
  - docker compose logs --no-log-prefix <service> | grep '"score"' | jq '.score' — correct jq pipeline (without --no-log-prefix, container name prefix breaks jq parse)
observability_surfaces:
  - "docker compose -f docker-compose.tee-dev.yml ps — shows (healthy)/(unhealthy) per container; all 4 containers healthy confirmed"
  - "docker compose exec miner-1 curl -sf http://localhost:8080/health → {\"status\":\"ok\"}"
  - "docker compose logs --no-log-prefix validator | grep '\"score\"' | jq '.score' → 0.5 lines"
  - "docker compose restart miner-1 → [Validator] lines for 12D3KooWM5J4zS17 reappear within 120s (confirmed epoch 14781206)"
duration: ~25min
verification_result: passed
completed_at: 2026-03-17
blocker_discovered: false
---

# T02: Add health endpoint, update docker-compose healthchecks, verify restart recovery

**Added `_health_server` on :8080 inside the trio nursery, activated JSON logs via `LOG_JSON` in compose, and confirmed `docker compose restart miner-1` recovers within one epoch with structured JSON scoring output.**

## What Happened

1. Added `_health_server(port=8080)` and `_health_handler(listener)` at module level in `server.py`. The handler uses raw HTTP/1.1 bytes over trio TCP sockets — no new dependencies. The handler skips sending a response when `receive_some` returns `b""` (TCP probes that connect then immediately close, which curl healthchecks can do).

2. Wired `nursery.start_soon(_health_server, 8080)` into the `if not self.is_bootstrap:` block in `Server.run()`, after `_overwatch_epoch_loop`. Bootnode does NOT start the health server.

3. Added `LOG_JSON: "true"` to the `x-tee-env` anchor in `docker-compose.tee-dev.yml`, propagating to all four services. Activates T01's JsonFormatter automatically in all containers.

4. Updated healthchecks for `validator`, `miner-1`, `miner-2` from `["CMD", "true"]` to `["CMD-SHELL", "curl -sf http://localhost:8080/health || exit 1"]` with `interval: 30s`, `timeout: 5s`, `retries: 3`, `start_period: 30s`. Bootnode healthcheck unchanged.

5. **Deviation discovered**: `curl` was only in the Dockerfile builder stage, not the production stage. The plan stated "curl is already present in the image (Dockerfile line 13)" — this was correct for the builder stage but the production `python:3.11-slim` stage only had `libgomp1`. All three non-bootstrap containers reported `(unhealthy)` after the first build with `exec: "curl": executable file not found`. Fix: added `curl` to the production stage's `apt-get install`. Rebuilt and all containers reached `(healthy)`.

6. Ran the restart recovery test: after `docker compose restart miner-1`, waited 120s, confirmed `[Validator]` lines for `peer=12D3KooWM5J4zS17` (miner-1's peer_id) appeared in validator logs at epoch 14781206.

## Verification

```
# Import smoke check
python3 -c "from subnet.server.server import _health_server; print('ok')"
→ ok

# Health server wired check
python3 -c "import inspect, subnet.server.server as s; src = inspect.getsource(s.Server.run); assert '_health_server' in src; print('health_server wired: OK')"
→ health_server wired: OK

# JSON formatter in-process
LOG_JSON=true python3 -c "[...assert epoch in d and peer in d...]"
→ PASS: JSON parseable with extra fields

# Full test suite
python3 -m pytest tests/ -q --tb=short
→ 183 passed, 1 skipped

# JsonFormatter unit tests
python3 -m pytest tests/test_json_logging.py -v
→ 2 passed

# Docker compose ps after 60s
→ tee-bootnode (healthy), tee-miner-1 (healthy), tee-miner-2 (healthy), tee-validator (healthy)

# Health endpoint live
docker compose -f docker-compose.tee-dev.yml exec miner-1 curl -sf http://localhost:8080/health
→ {"status":"ok"}

# JSON log output parseable
docker compose logs --no-log-prefix validator | grep '"score"' | jq '.score'
→ 0.5 lines

# Restart recovery
docker compose restart miner-1 && sleep 120
docker compose logs --since 90s validator | grep '[Validator]'
→ peer=12D3KooWM5J4zS17 epoch=14781206 score=0.00 correct=False (tamper_rate=1.0 for miner-1)
→ peer=12D3KooWKxAhu5U8 epoch=14781206 score=0.50 correct=True
```

## Diagnostics

- `docker compose -f docker-compose.tee-dev.yml ps` → check `(healthy)` / `(unhealthy)` status per container
- If `(unhealthy)`: `docker compose logs <service> | tail -30` — look for trio nursery crash or `Address already in use` on port 8080
- If health endpoint doesn't respond: confirm `_health_server` is wired with `python3 -c "import inspect, subnet.server.server as s; assert '_health_server' in inspect.getsource(s.Server.run)"`
- JSON log pipeline: `docker compose logs --no-log-prefix validator | grep '"score"' | jq '.score'` (must use `--no-log-prefix` — the container name prefix breaks jq)
- Bootnode healthcheck stays `["CMD", "true"]` — verify: `grep -A3 'bootnode:' docker-compose.tee-dev.yml | grep 'test:'` → `["CMD", "true"]`

## Deviations

1. **Dockerfile production stage missing `curl`**: The plan noted curl was available at Dockerfile line 13, but that's the builder stage. The production `python:3.11-slim` stage only had `libgomp1`. Added `curl` to the production apt-get install. This required a second `docker compose up --build` cycle.

## Known Issues

- `miner-1` (TAMPER_RATE=1.0) consistently scores 0.00 on the scoring loop (correct=False) — this is expected behavior, not a bug. The restart recovery test confirms the peer is being scored at all after restart, which is the real proof.
- The `jq '.score'` verification produces `null` for log lines without a `score` field (epoch-loop status messages) — filter with `grep '"score"'` to isolate only scoring lines.

## Files Created/Modified

- `subnet/server/server.py` — added `_health_handler` and `_health_server` at module level; added `nursery.start_soon(_health_server, 8080)` in non-bootstrap block
- `docker-compose.tee-dev.yml` — added `LOG_JSON: "true"` to `x-tee-env`; updated validator/miner-1/miner-2 healthchecks to curl with start_period=30s
- `Dockerfile` — added `curl` to production stage apt-get install
- `.gsd/milestones/M004/slices/S03/S03-PLAN.md` — added failure-path diagnostic checks to Observability section (pre-flight fix)
- `.gsd/KNOWLEDGE.md` — added two new entries: multi-stage Dockerfile curl gotcha; docker compose logs --no-log-prefix for jq
- `.gsd/DECISIONS.md` — added D010 (raw trio TCP for health server) and D011 (curl in production stage)
