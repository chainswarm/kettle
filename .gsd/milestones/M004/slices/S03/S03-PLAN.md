# S03: Restart recovery + observability

**Goal:** `docker compose restart miner-1` recovers within one epoch; all three operational log streams emit structured JSON when `LOG_JSON=true`; `:8080/health` returns `{"status":"ok"}` for non-bootstrap containers.
**Demo:** `docker compose -f docker-compose.tee-dev.yml logs validator | jq '.score'` prints `0.5` lines; `docker compose exec miner-1 curl -sf http://localhost:8080/health` returns `{"status":"ok"}`; after `docker compose restart miner-1`, validator logs show `[Validator]` lines for miner-1's peer within 120 s.

## Must-Haves

- `subnet/utils/logging.py` exists with a stdlib-only `JsonFormatter(logging.Formatter)` class
- `LOG_JSON=true` activates JSON output for `miner_epoch_loop`, `validator_scoring_loop`, and `overwatch_epoch_loop` loggers (not root logger — avoids py-libp2p noise)
- Key log calls in all three epoch loops carry `extra={"epoch": N, ...}` structured fields
- `_health_server(port)` async function in `server.py` answers `GET /health` with `{"status":"ok"}`
- Non-bootstrap containers (`validator`, `miner-1`, `miner-2`) have `healthcheck.test` pointing at `curl http://localhost:8080/health`; `bootnode` stays `["CMD", "true"]`
- `docker compose restart miner-1` → validator scores miner-1 within one epoch (120 s max)
- `python3 -m pytest tests/ -q` still passes (≥181 tests, no regressions)

## Proof Level

- This slice proves: operational
- Real runtime required: yes (T02 restart test requires a running compose stack)
- Human/UAT required: no (logs and curl output are machine-verifiable)

## Verification

```bash
# 1. Unit test for JsonFormatter
python3 -m pytest tests/test_json_logging.py -v
# expect: 2 passed

# 2. Import smoke checks
python3 -c "from subnet.utils.logging import JsonFormatter; print('ok')"
python3 -c "from subnet.server.server import _health_server; print('ok')"

# 3. Full test suite — no regressions
python3 -m pytest tests/ -q --tb=short
# expect: ≥181 passed, 1 skipped

# 4. Health endpoint live (running compose stack)
docker compose -f docker-compose.tee-dev.yml exec miner-1 curl -sf http://localhost:8080/health
# expect: {"status":"ok"}

# 5. JSON log output parseable
docker compose -f docker-compose.tee-dev.yml logs validator | jq '.score'
# expect: lines of 0.5

# 6. Restart recovery (operational proof)
docker compose -f docker-compose.tee-dev.yml up -d
sleep 60
docker compose -f docker-compose.tee-dev.yml restart miner-1
sleep 120
docker compose -f docker-compose.tee-dev.yml logs --since 90s validator | grep '\[Validator\]'
# expect: at least one [Validator] line containing miner-1's peer_id

# 7. Failure-path diagnostic: detect duplicate/non-JSON lines (propagate=False missing)
LOG_JSON=true python3 -c "
import logging, json
from subnet.utils.logging import JsonFormatter
f = JsonFormatter()
r = logging.LogRecord('validator_scoring_loop', logging.INFO, '', 0, '[Validator] score', (), None)
r.epoch = 1; r.peer = '12D3KooWtest'
line = f.format(r)
try:
    d = json.loads(line)
    assert 'epoch' in d and 'peer' in d, 'Missing extra fields — extra={} not wired'
    print('PASS: JSON parseable with extra fields')
except json.JSONDecodeError as e:
    print(f'FAIL: Non-JSON output (propagate=False likely missing): {line[:80]}')
    raise
"
# expect: PASS: JSON parseable with extra fields
```

## Observability / Diagnostics

- Runtime signals: `{"timestamp":..., "level":"INFO", "logger":"validator_scoring_loop", "message":"[Validator] ...", "epoch":N, "peer":"12D3KooW...", "score":0.5}` — one JSON line per scored peer per epoch
- Inspection surfaces: `docker compose logs validator | jq 'select(.logger=="validator_scoring_loop")'`; `curl http://localhost:8080/health` from inside any non-bootstrap container
- Failure visibility: if `jq` fails to parse a line, the formatter is not attached or propagate=False was not set (duplicate non-JSON lines will break `jq`); if health endpoint times out, check nursery wiring in `server.py`
- Redaction constraints: peer_id (16-char prefix) and epoch are safe to log; no secrets in log output

### Failure-path checks

```bash
# 8. Health endpoint failure diagnosis
# If `docker compose ps` shows (unhealthy) for a non-bootstrap service:
docker compose -f docker-compose.tee-dev.yml logs miner-1 | tail -30
# Look for: nursery crash traceback OR "Address already in use" on port 8080

# If health endpoint times out from outside the container, confirm it is wired:
python3 -c "import inspect, subnet.server.server as s; src = inspect.getsource(s.Server.run); assert '_health_server' in src, 'NOT WIRED'; print('health_server wired: OK')"
# expect: health_server wired: OK

# 9. Verify JSON log formatter is active (in-process smoke test, no compose required)
LOG_JSON=true python3 -c "
import logging, json
from subnet.utils.logging import JsonFormatter
f = JsonFormatter()
r = logging.LogRecord('validator_scoring_loop', logging.INFO, '', 0, '[Validator] score', (), None)
r.epoch = 1; r.peer = '12D3KooWtest'; r.score = 0.5
line = f.format(r)
try:
    d = json.loads(line)
    assert 'epoch' in d and 'peer' in d and 'score' in d, f'Missing extra fields: {list(d.keys())}'
    print('PASS: JSON parseable with extra fields')
except json.JSONDecodeError as e:
    print(f'FAIL: Non-JSON output (propagate=False likely missing): {line[:80]}')
    raise
"
# expect: PASS: JSON parseable with extra fields

# 10. Confirm bootnode healthcheck is NOT using curl (should stay ["CMD", "true"])
grep -A3 'bootnode:' docker-compose.tee-dev.yml | grep -A3 'healthcheck:' | grep 'test:'
# expect: test: ["CMD", "true"]  — NOT curl
```

## Integration Closure

- Upstream surfaces consumed: `subnet/server/server.py` epoch loops (S01); `subnet/cli/run_node.py` basicConfig wire-up (S01); `docker-compose.tee-dev.yml` service definitions (S01)
- New wiring introduced: `JsonFormatter` attached to 3 named loggers in `run_node.py`; `_health_server` started via `nursery.start_soon` in non-bootstrap block of `Server.run()`; `LOG_JSON: "true"` in `x-tee-env` anchor; healthcheck curl commands for validator/miner-1/miner-2
- What remains before the milestone is truly usable end-to-end: nothing — S03 is the final slice for M004

## Tasks

- [x] **T01: Add JsonFormatter and structured extra={} fields to epoch loop loggers** `est:45m`
  - Why: Enables `docker compose logs | jq` pipelines; structured fields (epoch, peer, score) make log analysis scriptable without grep+awk
  - Files: `subnet/utils/logging.py` (new), `subnet/cli/run_node.py`, `subnet/server/server.py`, `tests/test_json_logging.py` (new)
  - Do: Create `JsonFormatter` in `subnet/utils/logging.py`; wire via `LOG_JSON` env var in `run_node.py` attaching to named loggers with `propagate=False`; add `extra={}` kwargs to key log calls in all three epoch loops in `server.py`; write unit tests
  - Verify: `python3 -m pytest tests/test_json_logging.py -v` passes; `LOG_JSON=true python3 -c "import logging; from subnet.utils.logging import JsonFormatter; ..."` emits valid JSON
  - Done when: `tests/test_json_logging.py` passes with ≥2 assertions; `extra` fields (`epoch`, `score`) appear in JSON output from validator/miner loggers

- [x] **T02: Add health endpoint, update docker-compose healthchecks, verify restart recovery** `est:1h`
  - Why: Health endpoint enables Docker healthchecks and the restart recovery verification; `LOG_JSON` in compose activates T01's formatter end-to-end
  - Files: `subnet/server/server.py`, `docker-compose.tee-dev.yml`
  - Do: Add `_health_server(port)` async function to `server.py`; wire into nursery for non-bootstrap nodes; add `LOG_JSON: "true"` to `x-tee-env`; update validator/miner-1/miner-2 healthchecks to `curl -sf http://localhost:8080/health`; run live restart test
  - Verify: `curl http://localhost:8080/health` → `{"status":"ok"}`; `docker compose restart miner-1` → `[Validator]` lines for miner-1 reappear within 120 s
  - Done when: all four verification commands in the slice-level Verification section pass; full test suite still green

## Files Likely Touched

- `subnet/utils/logging.py` (new)
- `subnet/cli/run_node.py`
- `subnet/server/server.py`
- `docker-compose.tee-dev.yml`
- `tests/test_json_logging.py` (new)
