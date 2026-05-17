---
estimated_steps: 7
estimated_files: 4
---

# T01: Add JsonFormatter and structured extra={} fields to epoch loop loggers

**Slice:** S03 — Restart recovery + observability
**Milestone:** M004

## Description

Creates `subnet/utils/logging.py` with a stdlib-only `JsonFormatter` class. Wires it to the three operational loggers (`miner_epoch_loop`, `validator_scoring_loop`, `overwatch_epoch_loop`) in `run_node.py` when `LOG_JSON=true` is set. Adds `extra={"epoch": N, ...}` kwargs to the key log calls in all three epoch loops in `server.py` so structured fields appear in the JSON output.

This task is entirely Python-only — no Docker required. It fully closes the "structured JSON logs" must-have and produces a unit test that proves the formatter works.

## Steps

1. **Create `subnet/utils/logging.py`** — Define `JsonFormatter(logging.Formatter)` that overrides `format(record)`:
   - Build a base dict: `{"timestamp": ..., "level": record.levelname, "logger": record.name, "message": record.getMessage()}`
   - Merge any `extra` fields from `record.__dict__` that are NOT in the standard `LogRecord` reserved keys. Safe extras to include: any key not in `{"name","msg","args","levelname","levelno","pathname","filename","module","exc_info","exc_text","stack_info","lineno","funcName","created","msecs","relativeCreated","thread","threadName","processName","process","message","taskName"}`. Simple approach: merge `record.__dict__` items and pop the reserved set after.
   - Return `json.dumps(result)` — single line, no indent.
   - Keep imports to stdlib only: `import json`, `import logging`, `import time`.

2. **Wire in `run_node.py`** — After the existing `logging.basicConfig(...)` call (line ~34), add:
   ```python
   if os.getenv("LOG_JSON", "").lower() in ("1", "true", "yes"):
       from subnet.utils.logging import JsonFormatter
       _json_formatter = JsonFormatter()
       for _logger_name in ("miner_epoch_loop", "validator_scoring_loop", "overwatch_epoch_loop"):
           _lg = logging.getLogger(_logger_name)
           _lg.handlers.clear()
           _handler = logging.StreamHandler()
           _handler.setFormatter(_json_formatter)
           _lg.addHandler(_handler)
           _lg.propagate = False  # prevent double-logging via root handler
   ```
   Setting `propagate = False` is critical — without it, the root handler (added by `basicConfig`) also fires and produces duplicate non-JSON lines that break `jq`.

3. **Add `extra={}` to `_miner_epoch_loop` log calls in `server.py`** — Edit the `loop_logger.info("[MinerLoop] New epoch %d — running miner_loop", current_epoch)` call and the gossip publish log calls to pass `extra={"epoch": current_epoch}`. Specifically update the "New epoch" line and the three `[GossipPub]` info lines.

4. **Add `extra={}` to `_validator_scoring_loop` log calls** — Edit the `[Validator]` score log call to pass `extra={"epoch": score_epoch, "peer": peer_id[:16], "score": round(peer_score.score, 2)}`.

5. **Add `extra={}` to `_overwatch_epoch_loop` log calls** — Edit the `[Overwatch] PASS` and `[Overwatch] TAMPER` log calls to pass `extra={"epoch": score_epoch, "peer": peer_id[:16]}`. Add `"reason": result.reason` to the TAMPER extra.

6. **Create `tests/test_json_logging.py`** with two test functions:
   - `test_json_formatter_basic()`: Create a `JsonFormatter`, create a `LogRecord`, call `formatter.format(record)`, parse result as JSON, assert keys `timestamp`, `level`, `logger`, `message` are present and have correct values.
   - `test_json_formatter_extra_fields()`: Create a `LogRecord` and add custom `extra` keys (e.g. `epoch=42`, `score=0.5`) to the record's `__dict__` before formatting; assert they appear in the parsed JSON output.

7. **Run the tests** to confirm they pass before marking done.

## Must-Haves

- [ ] `subnet/utils/logging.py` exists and imports without error
- [ ] `JsonFormatter.format()` returns a string that `json.loads()` parses without error
- [ ] `epoch`, `score`, `peer` fields appear in JSON output for `[Validator]` log calls
- [ ] `propagate = False` is set on the three operational loggers so no duplicate lines appear
- [ ] `tests/test_json_logging.py` passes with ≥2 assertions (`python3 -m pytest tests/test_json_logging.py -v`)
- [ ] Full test suite still green (`python3 -m pytest tests/ -q` ≥181 passed)

## Verification

```bash
# Unit tests for the formatter
python3 -m pytest tests/test_json_logging.py -v
# expect: 2 passed

# Import smoke check
python3 -c "from subnet.utils.logging import JsonFormatter; import json, logging; \
  f = JsonFormatter(); r = logging.LogRecord('test','','',-1,'hello',(),None); \
  out = f.format(r); d = json.loads(out); print(d['message'])"
# expect: hello

# Extra field test (simulating epoch loop)
LOG_JSON=true python3 -c "
import logging, os
from subnet.utils.logging import JsonFormatter
import json
f = JsonFormatter()
r = logging.LogRecord('validator_scoring_loop', logging.INFO, '', 0, '[Validator] score', (), None)
r.epoch = 100; r.score = 0.5; r.peer = '12D3KooWabcd'
print(json.loads(f.format(r)))
"
# expect: dict with epoch=100, score=0.5, peer='12D3KooWabcd'

# Full suite
python3 -m pytest tests/ -q --tb=short
# expect: ≥181 passed, 1 skipped
```

## Observability Impact

- Signals added/changed: Three operational loggers (`miner_epoch_loop`, `validator_scoring_loop`, `overwatch_epoch_loop`) now emit structured JSON lines when `LOG_JSON=true`. Key fields: `timestamp`, `level`, `logger`, `message`, `epoch`, `peer`, `score` (validator), `reason` (overwatch TAMPER).
- How a future agent inspects this: `docker compose logs validator | jq 'select(.logger=="validator_scoring_loop") | {epoch, peer, score}'`
- Failure state exposed: if `jq` errors on a line, `propagate=False` was not set (duplicate non-JSON line); if `epoch` key is absent, the `extra={}` was not added to the log call

## Inputs

- `subnet/server/server.py` — Three epoch loops with existing log calls: `miner_epoch_loop` (logger name), `validator_scoring_loop`, `overwatch_epoch_loop`. These are the only loggers that receive `extra={}` and JSON handler wiring.
- `subnet/cli/run_node.py` — `logging.basicConfig()` at line ~34; `LOG_JSON` env var check goes immediately after this block.
- S01 established pattern: loggers are named (`logging.getLogger("miner_epoch_loop")`) and created inside the async functions — the `run_node.py` wire-up works because it runs before `trio.run()` is called.

## Expected Output

- `subnet/utils/logging.py` — New file with `JsonFormatter` class (~20 lines, stdlib only)
- `subnet/cli/run_node.py` — 8-line LOG_JSON block added after `basicConfig`
- `subnet/server/server.py` — `extra={}` kwargs on ~7 specific log calls across 3 loop functions
- `tests/test_json_logging.py` — New test file with 2 test functions
