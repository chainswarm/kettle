---
id: T01
parent: S03
milestone: M004
provides:
  - JsonFormatter stdlib-only class in subnet/utils/logging.py
  - LOG_JSON env var wiring in run_node.py attaching JsonFormatter to 3 named loggers with propagate=False
  - extra={epoch,peer,score,reason} kwargs on key log calls in all three epoch loops in server.py
  - Unit tests for JsonFormatter (2 passing tests)
key_files:
  - subnet/utils/logging.py
  - subnet/cli/run_node.py
  - subnet/server/server.py
  - tests/test_json_logging.py
key_decisions:
  - JsonFormatter merges all non-reserved LogRecord __dict__ keys as extra fields, using a frozenset of stdlib reserved keys as the exclusion list
  - propagate=False on the three operational loggers prevents double-logging when LOG_JSON is active
  - Timestamp uses time.gmtime + msecs for sub-second precision in ISO-8601 UTC format
patterns_established:
  - Named loggers (miner_epoch_loop, validator_scoring_loop, overwatch_epoch_loop) are configured in run_node.py before trio.run() so run-time log calls pick up the formatter transparently
  - extra={} fields are set on log calls, not via LoggerAdapter, keeping call sites minimal
observability_surfaces:
  - "LOG_JSON=true python3 -m subnet.cli.run_node ... | jq 'select(.logger==\"validator_scoring_loop\") | {epoch,peer,score}'"
  - "docker compose logs validator | jq 'select(.logger==\"validator_scoring_loop\")'"
  - "Failure diagnostic: if jq errors on a line, propagate=False was not set (duplicate non-JSON line from root handler)"
duration: 15m
verification_result: passed
completed_at: 2026-03-17
blocker_discovered: false
---

# T01: Add JsonFormatter and structured extra={} fields to epoch loop loggers

**Created stdlib-only JsonFormatter in subnet/utils/logging.py; wired to three named operational loggers via LOG_JSON env var in run_node.py with propagate=False; added extra={epoch,peer,score,reason} kwargs to key log calls across all three epoch loops in server.py.**

## What Happened

1. Created `subnet/utils/logging.py` with `JsonFormatter(logging.Formatter)` — builds a base dict with `timestamp` (ISO-8601 UTC with milliseconds), `level`, `logger`, `message`, then merges any non-reserved `record.__dict__` keys as extra fields. Entirely stdlib (json, logging, time).

2. Added 11-line LOG_JSON block in `subnet/cli/run_node.py` immediately after `basicConfig`. When `LOG_JSON` is `1`, `true`, or `yes`, attaches `JsonFormatter` to `miner_epoch_loop`, `validator_scoring_loop`, and `overwatch_epoch_loop` loggers and sets `propagate=False` on each to prevent root handler from emitting duplicate non-JSON lines.

3. In `subnet/server/server.py`, added `extra={"epoch": current_epoch}` to:
   - `_miner_epoch_loop`: "New epoch" info line + three `[GossipPub]` info lines (4 calls)

   Added `extra={"epoch": score_epoch, "peer": peer_id[:16], "score": round(peer_score.score, 2)}` to:
   - `_validator_scoring_loop`: `[Validator]` info line (1 call)

   Added `extra={"epoch": score_epoch, "peer": peer_id[:16]}` and `extra={..., "reason": result.reason}` to:
   - `_overwatch_epoch_loop`: `[Overwatch] PASS` info + `[Overwatch] TAMPER` warning (2 calls)

4. Created `tests/test_json_logging.py` with two test functions covering basic format validation and extra-field passthrough.

5. Applied S03-PLAN.md pre-flight fix: added a failure-path diagnostic check (step 7) to the slice verification section.

## Verification

```
python3 -m pytest tests/test_json_logging.py -v
# → 2 passed in 0.02s

python3 -c "from subnet.utils.logging import JsonFormatter; import json, logging; \
  f = JsonFormatter(); r = logging.LogRecord('test','','',-1,'hello',(),None); \
  out = f.format(r); d = json.loads(out); print(d['message'])"
# → hello

LOG_JSON=true python3 -c "...epoch=100, score=0.5, peer='12D3KooWabcd'..."
# → {'timestamp': ..., 'level': 'INFO', 'logger': 'validator_scoring_loop',
#    'message': '[Validator] score', 'epoch': 100, 'score': 0.5, 'peer': '12D3KooWabcd'}

python3 -m pytest tests/ -q --tb=short
# → 183 passed, 1 skipped in 4.90s
```

## Diagnostics

- `LOG_JSON=true python3 -m subnet.cli.run_node ... | jq 'select(.logger=="validator_scoring_loop") | {epoch,peer,score}'` — structured per-peer scoring stream
- `docker compose logs validator | jq 'select(.logger=="validator_scoring_loop")'` — filter by logger in compose
- If `jq` fails to parse a line: `propagate=False` was not set → root handler emitted a non-JSON formatted line; fix: confirm the LOG_JSON block in run_node.py ran before trio.start
- If `epoch` key absent from JSON output: the `extra={}` kwarg was not added to that log call in server.py

## Deviations

None — implemented exactly as specified in the task plan.

## Known Issues

None.

## Files Created/Modified

- `subnet/utils/logging.py` — New file: stdlib-only JsonFormatter class (~55 lines including docstrings)
- `subnet/cli/run_node.py` — Added 11-line LOG_JSON block after basicConfig; wires JsonFormatter to 3 loggers with propagate=False
- `subnet/server/server.py` — Added extra={} kwargs to 7 log calls across _miner_epoch_loop (4), _validator_scoring_loop (1), _overwatch_epoch_loop (2)
- `tests/test_json_logging.py` — New file: 2 unit tests for JsonFormatter
- `.gsd/milestones/M004/slices/S03/S03-PLAN.md` — Pre-flight fix: added failure-path diagnostic step 7 to Verification section
