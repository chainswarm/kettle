# S03: Restart recovery + observability — UAT

**Milestone:** M004
**Written:** 2026-03-17

## UAT Type

- UAT mode: mixed (artifact-driven for unit tests and import checks; live-runtime for health endpoint, JSON log pipeline, and restart recovery)
- Why this mode is sufficient: The static checks confirm all code paths are wired correctly without a running stack; the live-runtime checks were executed by the executor agent and are documented as passed. A human reviewer can re-run any step against a live stack for confirmation.

## Preconditions

For static/artifact-driven tests (1–3): No compose stack required. Python environment with project deps installed.

For live-runtime tests (4–8): `docker compose -f docker-compose.tee-dev.yml up --build -d` completed and all four containers are in `(healthy)` state (verify with `docker compose ps`). Allow ~60s after start for GossipSub mesh formation before running scoring-related checks.

## Smoke Test

```bash
# Quick check: formatter is importable and health server is wired
python3 -c "from subnet.utils.logging import JsonFormatter; from subnet.server.server import _health_server; print('smoke: ok')"
```
**Expected:** `smoke: ok` — no ImportError.

---

## Test Cases

### 1. JsonFormatter unit tests pass

```bash
cd /path/to/project
python3 -m pytest tests/test_json_logging.py -v
```

**Expected:** `2 passed` with test names `test_json_formatter_basic` and `test_json_formatter_extra_fields`. Zero failures, zero errors.

---

### 2. JSON formatter produces valid JSON with extra fields

```bash
LOG_JSON=true python3 -c "
import logging, json
from subnet.utils.logging import JsonFormatter
f = JsonFormatter()
r = logging.LogRecord('validator_scoring_loop', logging.INFO, '', 0, '[Validator] score', (), None)
r.epoch = 1; r.peer = '12D3KooWtest'; r.score = 0.5
line = f.format(r)
d = json.loads(line)
assert 'timestamp' in d and 'level' in d and 'logger' in d and 'message' in d, f'Missing base fields: {list(d.keys())}'
assert 'epoch' in d and 'peer' in d and 'score' in d, f'Missing extra fields: {list(d.keys())}'
assert d['logger'] == 'validator_scoring_loop', f'Wrong logger name: {d[\"logger\"]}'
assert d['epoch'] == 1
assert d['score'] == 0.5
print('PASS: JSON output is valid with all extra fields present')
"
```

**Expected:** `PASS: JSON output is valid with all extra fields present`

---

### 3. Health server is wired in Server.run() and importable

```bash
python3 -c "from subnet.server.server import _health_server; print('import: ok')"

python3 -c "
import inspect, subnet.server.server as s
src = inspect.getsource(s.Server.run)
assert '_health_server' in src, 'NOT WIRED — _health_server missing from Server.run()'
print('health_server wired: OK')
"
```

**Expected (line 1):** `import: ok`
**Expected (line 2):** `health_server wired: OK`

---

### 4. Full test suite — no regressions

```bash
python3 -m pytest tests/ -q --tb=short
```

**Expected:** `183 passed, 1 skipped` (or more — never fewer than 183 passed). Zero failures.

---

### 5. All containers reach healthy status

*Requires: compose stack running after `docker compose up --build -d`*

```bash
docker compose -f docker-compose.tee-dev.yml ps
```

**Expected:** All four containers (`tee-bootnode`, `tee-miner-1`, `tee-miner-2`, `tee-validator`) show `(healthy)` in the Status column. Allow up to 90s (start_period: 30s + a few health intervals).

---

### 6. Health endpoint responds from inside a non-bootstrap container

*Requires: compose stack running with all containers healthy*

```bash
docker compose -f docker-compose.tee-dev.yml exec miner-1 curl -sf http://localhost:8080/health
docker compose -f docker-compose.tee-dev.yml exec miner-2 curl -sf http://localhost:8080/health
docker compose -f docker-compose.tee-dev.yml exec validator curl -sf http://localhost:8080/health
```

**Expected:** `{"status":"ok"}` for each command. Exit code 0.

---

### 7. JSON log output is parseable via jq

*Requires: compose stack running; wait ≥60s for GossipSub mesh + first scoring epoch*

```bash
docker compose -f docker-compose.tee-dev.yml logs --no-log-prefix validator | grep '"score"' | jq '.score'
```

**Expected:** One or more lines containing `0.5` (miner-2 honest score). Lines may also contain `0` or `0.0` (miner-1 tamper score — expected with `TAMPER_RATE=1.0`). No `jq` parse errors.

Note: `--no-log-prefix` is mandatory. Without it, the `tee-validator  | ` prefix breaks jq.

---

### 8. Restart recovery: miner-1 re-scored within 120 seconds

*Requires: compose stack running with all containers healthy; wait 60s for initial mesh formation*

```bash
# Step 1: Restart miner-1
docker compose -f docker-compose.tee-dev.yml restart miner-1

# Step 2: Wait for recovery window
sleep 120

# Step 3: Check validator logs for miner-1's peer_id
docker compose -f docker-compose.tee-dev.yml logs --since 90s validator | grep '\[Validator\]'
```

**Expected:** At least one line matching `[Validator]` that contains miner-1's peer_id (a `12D3KooW...` string). The score column will show `0.00 correct=False` (because miner-1 has `TAMPER_RATE=1.0` — this is expected and proves the validator is scoring it). The presence of any `[Validator]` line for miner-1's peer within 120s proves:
- Miner-1 re-registered in the DHT after restart
- Miner-1 rejoined the GossipSub mesh
- Validator detected miner-1 and included it in scoring

---

## Edge Cases

### Bootnode healthcheck must NOT use curl

```bash
grep -A 20 'bootnode:' docker-compose.tee-dev.yml | grep -A 3 'healthcheck:' | grep 'test:'
```

**Expected:** `test: ["CMD", "true"]` — not a curl command. The bootnode does not run `_health_server` (it is bootstrap-mode only).

---

### propagate=False prevents double-logging

```bash
# Confirm that JSON lines from validator logger are single (not doubled)
LOG_JSON=true python3 -c "
import logging, json
from subnet.utils.logging import JsonFormatter

# Simulate what run_node.py does
logger = logging.getLogger('validator_scoring_loop')
handler = logging.StreamHandler()
handler.setFormatter(JsonFormatter())
logger.addHandler(handler)
logger.propagate = False
logger.setLevel(logging.INFO)

# Root handler would emit a second plain-text line if propagate were True
import io, sys
buf = io.StringIO()
root_handler = logging.StreamHandler(buf)
logging.getLogger().addHandler(root_handler)
logging.getLogger().setLevel(logging.DEBUG)

logger.info('[Validator] test', extra={'epoch': 5, 'peer': '12D3KooWtest', 'score': 0.5})
root_output = buf.getvalue()
assert root_output == '', f'Root handler fired (propagate=True bug): {root_output!r}'
print('PASS: propagate=False correctly suppresses root handler')
"
```

**Expected:** `PASS: propagate=False correctly suppresses root handler`

---

### Non-JSON lines break jq — filter with grep first

```bash
# Without filter: some lines may lack 'score' field → jq outputs null (not a parse error)
docker compose -f docker-compose.tee-dev.yml logs --no-log-prefix validator | jq '.score' | head -5
```

**Expected:** Mix of `0.5`, `0`, `null` (null for non-scoring log lines). No parse errors. If parse errors appear, the formatter is not active or `--no-log-prefix` was omitted.

---

## Failure Signals

- `exec: "curl": executable file not found` in container logs → `curl` was not added to the Dockerfile production stage. Check `Dockerfile` production stage `apt-get install` includes `curl`.
- `(unhealthy)` in `docker compose ps` for a non-bootstrap container → either health server not wired in nursery, or port 8080 collision. Run `docker compose logs <service> | tail -30` and look for trio nursery crash or `Address already in use`.
- `jq: error (at <stdin>:1): Invalid numeric literal` → `--no-log-prefix` was omitted. The container name prefix `tee-validator  | ` breaks jq parsing.
- `FAIL: Non-JSON output` in formatter smoke test → `propagate=False` not set or `LOG_JSON` block didn't run before `trio.run()`. Check `run_node.py` LOG_JSON block ordering.
- No `[Validator]` lines for miner-1 after restart + 120s → check miner-1 is actually running (`docker compose ps`) and that it completed at least one epoch after restart. DHT convergence takes ~30s; scoring happens on the next epoch boundary.
- `2 failed` or `ImportError` in pytest → a dependency was broken. Run `python3 -m pytest tests/test_json_logging.py -v` in isolation to narrow the failure.

## Requirements Proved By This UAT

- R008 (restart recovery — basic) — Test Case 8 proves `docker compose restart miner-1` → re-scored within 120s.
- R022 (test coverage) — Test Case 4 proves full suite at 183 passed, 1 skipped with no regressions from S03 additions.

## Not Proven By This UAT

- Full R008 (advanced restart recovery — state persistence across restart, zero missed epochs): this UAT proves the node re-joins and gets scored, not that it resumed from an exact epoch offset. Advanced recovery is deferred.
- Hardware TEE paths (R002, R003): all tests run in `MOCK_TEE=true` mode.
- Chain integration (R019 on-chain): M005 scope.

## Notes for Tester

- `miner-1` has `TAMPER_RATE=1.0` — it will always score `0.00 correct=False`. This is expected and is what S02 set up. Do not interpret a 0.00 score for miner-1 as a failure.
- `miner-2` has no tamper rate set and should score `0.50 correct=True` consistently from epoch 3 onward.
- First 1–2 epochs after stack start (or after `docker compose restart`): validator may score 0.00 for all peers. This is the GossipSub cold-start window documented in KNOWLEDGE.md. Wait for epoch 3+ before asserting scores.
- The `jq '.score'` pipeline will output `null` for validator log lines that don't carry a `score` field (e.g. epoch boundary messages). Use `grep '"score"'` to filter before piping to jq if you only want scoring lines.
- Live-runtime tests (5–8) require the compose stack to be up and healthy. Run `docker compose -f docker-compose.tee-dev.yml up --build -d` and wait ~90s before executing these tests.
