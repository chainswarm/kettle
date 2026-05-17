---
estimated_steps: 6
estimated_files: 2
---

# T02: Add health endpoint, update docker-compose healthchecks, verify restart recovery

**Slice:** S03 — Restart recovery + observability
**Milestone:** M004

## Description

Adds a minimal HTTP health endpoint (`_health_server`) to `server.py` that listens on `:8080` and returns `{"status":"ok"}` for `GET /health`. Wires it into the nursery for all non-bootstrap nodes. Updates `docker-compose.tee-dev.yml` to activate JSON logs (`LOG_JSON: "true"` in `x-tee-env`) and point healthchecks at `curl http://localhost:8080/health` for `validator`, `miner-1`, `miner-2` (bootnode stays `["CMD", "true"]`). Finishes with a live `docker compose restart miner-1` test to prove restart recovery within one epoch.

`curl` is already present in the image (`Dockerfile` line 13: `curl` in apt-get install).

## Steps

1. **Add `_health_server(port: int)` to `server.py`** — Implement as a minimal trio TCP server. Pattern:
   ```python
   async def _health_server(port: int = 8080) -> None:
       import trio
       listeners = await trio.open_tcp_listeners(port)
       async with trio.open_nursery() as nursery:
           for listener in listeners:
               nursery.start_soon(_health_handler, listener)

   async def _health_handler(listener) -> None:
       while True:
           client = await listener.accept()
           async with client:
               # Read request (discard — we don't need to inspect it)
               await client.receive_some(1024)
               body = b'{"status":"ok"}'
               response = (
                   b"HTTP/1.1 200 OK\r\n"
                   b"Content-Type: application/json\r\n"
                   b"Content-Length: " + str(len(body)).encode() + b"\r\n"
                   b"Connection: close\r\n\r\n"
               + body
               )
               await client.send_all(response)
   ```
   Keep both functions at module level alongside the other epoch loop functions. No new imports beyond `trio` (already imported).

   **Important**: The `_health_handler` pattern above needs careful TCP read handling — `receive_some` may return `b""` on a connection that closed before sending data (curl sometimes does a TCP connect + immediate close for health checks). Wrap the `receive_some` call in a try/except and skip the response if the connection is already closed.

2. **Wire `_health_server` into nursery** in `Server.run()` — Inside the `if not self.is_bootstrap:` block, after the existing `nursery.start_soon(_overwatch_epoch_loop, ...)` call, add:
   ```python
   nursery.start_soon(_health_server, 8080)
   ```
   This is inside the non-bootstrap branch — bootnode does NOT start the health server.

3. **Update `docker-compose.tee-dev.yml` — add `LOG_JSON`** — Add `LOG_JSON: "true"` to the `x-tee-env` anchor block. It will propagate to all four services via `<<: *tee-env`.

4. **Update `docker-compose.tee-dev.yml` — update healthchecks** — Change the `healthcheck.test` for `validator`, `miner-1`, and `miner-2` from `["CMD", "true"]` to:
   ```yaml
   test: ["CMD-SHELL", "curl -sf http://localhost:8080/health || exit 1"]
   ```
   Leave the `bootnode` healthcheck unchanged (`["CMD", "true"]`).
   
   Also update `healthcheck.interval` for the three services to `30s` (the server needs ~10s to start) and set `start_period: 30s` to avoid false unhealthy during startup.

5. **Run `docker compose up --build -d`** and wait ~60 s for all containers to reach `healthy` state:
   ```bash
   docker compose -f docker-compose.tee-dev.yml up --build -d
   sleep 60
   docker compose -f docker-compose.tee-dev.yml ps
   # all 4 containers should be Up (healthy) or Up (starting)
   ```

6. **Run the restart recovery test**:
   ```bash
   # Confirm baseline scoring is active
   docker compose -f docker-compose.tee-dev.yml logs --since 30s validator | grep '\[Validator\]'
   
   # Restart miner-1
   docker compose -f docker-compose.tee-dev.yml restart miner-1
   
   # Wait one full epoch (120 s)
   sleep 120
   
   # Confirm miner-1 scored again
   docker compose -f docker-compose.tee-dev.yml logs --since 90s validator | grep '\[Validator\]'
   ```
   At least one `[Validator]` line mentioning miner-1's peer_id must appear in the 90s window after restart.

   Also verify JSON output is parseable:
   ```bash
   docker compose -f docker-compose.tee-dev.yml logs validator | grep '{' | tail -5 | jq '.score'
   # expect: lines of 0.5
   ```

## Must-Haves

- [ ] `_health_server(port)` is defined at module level in `server.py` and handles `GET /health` returning `{"status":"ok"}`
- [ ] `nursery.start_soon(_health_server, 8080)` is in the `if not self.is_bootstrap:` block
- [ ] `LOG_JSON: "true"` is in the `x-tee-env` YAML anchor (propagates to all services)
- [ ] `validator`, `miner-1`, `miner-2` healthchecks use `curl -sf http://localhost:8080/health`
- [ ] `bootnode` healthcheck is unchanged (`["CMD", "true"]`)
- [ ] `docker compose exec miner-1 curl -sf http://localhost:8080/health` → `{"status":"ok"}`
- [ ] `docker compose restart miner-1` → `[Validator]` lines for miner-1 reappear within 120 s
- [ ] `docker compose logs validator | jq '.score'` outputs `0.5` lines without parse errors
- [ ] `python3 -m pytest tests/ -q` still ≥181 passed

## Verification

```bash
# Import check — no runtime, just confirming the function exists
python3 -c "from subnet.server.server import _health_server; print('ok')"
# expect: ok

# Health endpoint live (requires running compose stack)
docker compose -f docker-compose.tee-dev.yml exec miner-1 curl -sf http://localhost:8080/health
# expect: {"status":"ok"}

# JSON log output parseable
docker compose -f docker-compose.tee-dev.yml logs validator | grep '{' | tail -5 | jq '.score'
# expect: 0.5 lines

# Restart recovery (one full epoch wait)
docker compose -f docker-compose.tee-dev.yml restart miner-1
sleep 120
docker compose -f docker-compose.tee-dev.yml logs --since 90s validator | grep '\[Validator\]'
# expect: at least one line

# Full test suite — no regressions
python3 -m pytest tests/ -q --tb=short
# expect: ≥181 passed, 1 skipped
```

## Observability Impact

- Signals added/changed: HTTP health endpoint at `:8080/health` returns `{"status":"ok"}` — Docker healthchecks can now detect if a non-bootstrap container's trio event loop is alive (health server runs in the same nursery as epoch loops). `LOG_JSON: "true"` activates T01's `JsonFormatter` in all containers.
- How a future agent inspects this: `docker compose ps` shows `(healthy)` status once health endpoint is up; `docker compose logs validator | jq 'select(.epoch != null)'` shows structured epoch scoring lines
- Failure state exposed: if `docker compose ps` shows `(unhealthy)` for a non-bootstrap service, the trio nursery crashed or `_health_server` is not wired; check `docker compose logs <service> | tail -20` for the crash traceback

## Inputs

- `subnet/server/server.py` — `if not self.is_bootstrap:` block in `Server.run()` (~line 335); three epoch loop functions; existing `trio` import at top. `_health_server` goes at module level after `_overwatch_epoch_loop`.
- `docker-compose.tee-dev.yml` — `x-tee-env` anchor (~line 18); four service `healthcheck` blocks.
- T01 output: `subnet/utils/logging.py` `JsonFormatter` and `run_node.py` LOG_JSON wire-up already in place — setting `LOG_JSON: "true"` in compose activates it automatically.
- From S01 SUMMARY: `curl` is already installed in the Dockerfile (`Dockerfile` line 13). `bootnode` uses `is_bootstrap=True` — confirmed that the health server must stay out of its nursery.

## Expected Output

- `subnet/server/server.py` — `_health_server` and `_health_handler` functions added at module level; `nursery.start_soon(_health_server, 8080)` in non-bootstrap block
- `docker-compose.tee-dev.yml` — `LOG_JSON: "true"` in `x-tee-env`; `validator`/`miner-1`/`miner-2` healthchecks updated to curl; `start_period: 30s` added to those three services
- Live operational proof: `docker compose restart miner-1` recovery confirmed in logs within 120 s
