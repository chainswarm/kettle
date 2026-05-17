---
id: T01
parent: S01
milestone: M004
provides:
  - SQLite WAL mode on every MockDatabase connection
  - MOCK_CHAIN_DB_PATH env var for shared-volume DB path across containers
  - TAMPER_RATE env var for per-container fault injection control
key_files:
  - subnet/hypertensor/mock/mock_db.py
  - subnet/node/mock.py
key_decisions:
  - Used `db_path: str | None = None` signature to distinguish "caller passed nothing" from "caller passed a path", so the env var is only consulted when no explicit path is given
  - Added `import os` to mock.py stdlib imports block rather than `import os as _os` alias — cleaner and consistent with project style
patterns_established:
  - Env-var with typed default + safe fallback via try/except for module-level constants (TAMPER_RATE pattern)
  - SQLite WAL pragma applied immediately after connect, before row_factory, so all subsequent connections are WAL
observability_surfaces:
  - "sqlite3 /path/to/mock_hypertensor.db 'PRAGMA journal_mode;' → must return wal"
  - "python3 -c 'from subnet.hypertensor.mock.mock_db import MockDatabase; db = MockDatabase(); print(db.db_path)'"
  - "python3 -c 'import subnet.node.mock as m; print(m.TAMPER_RATE)'"
duration: ~5min
verification_result: passed
completed_at: 2026-03-17
blocker_discovered: false
---

# T01: Fix MockDatabase WAL mode, env-var DB path, and env-var TAMPER_RATE

**Enabled safe multi-container SQLite sharing via WAL mode and MOCK_CHAIN_DB_PATH, and made TAMPER_RATE env-var-driven for per-container fault injection.**

## What Happened

Three targeted one-liner changes were applied to two files:

1. `mock_db.py` `_connect()`: Added `self.conn.execute("PRAGMA journal_mode=WAL")` immediately after `sqlite3.connect()`. This prevents `database is locked` BUSY errors when 4 Docker containers write concurrently to a shared SQLite file on a named volume.

2. `mock_db.py` `__init__`: Changed signature to `db_path: str | None = None` and added env-var resolution at the top of `__init__`: if `db_path is None`, reads `MOCK_CHAIN_DB_PATH` env var with `DB_FILE` as fallback. `os` was already imported.

3. `mock.py`: Added `import os` to the stdlib imports block, then replaced the hardcoded `TAMPER_RATE = 1 / 1000` with env-var-driven `float(os.getenv("TAMPER_RATE", "0.001"))` wrapped in a `try/except (ValueError, TypeError)` with `0.001` fallback.

## Verification

All plan verification commands passed:

```
# Tests
python3 -m pytest tests/ -q --tb=short
→ 181 passed, 1 skipped in 5.86s

# Env var path resolution
MOCK_CHAIN_DB_PATH=/tmp/test_wal.db python3 -c "from subnet.hypertensor.mock.mock_db import MockDatabase; db = MockDatabase(); print(db.db_path)"
→ /tmp/test_wal.db

# Default path fallback
python3 -c "from subnet.hypertensor.mock.mock_db import MockDatabase; db = MockDatabase(); print(db.db_path)"
→ mock_hypertensor.db

# TAMPER_RATE env var
TAMPER_RATE=0.5 python3 -c "import subnet.node.mock as m; print(m.TAMPER_RATE)"
→ 0.5
```

## Diagnostics

- **WAL mode active**: `sqlite3 /path/to/mock_hypertensor.db "PRAGMA journal_mode;"` → `wal`
- **DB path in use**: inspect `db.db_path` or check container env via `docker compose exec <svc> env | grep MOCK_CHAIN`
- **TAMPER_RATE active**: `docker compose exec miner-2 python3 -c "import subnet.node.mock as m; print(m.TAMPER_RATE)"`
- **Failure signal (before fix)**: `sqlite3.OperationalError: database is locked` in `docker compose logs` — should not appear after this fix

## Deviations

- Test count is 181 passed + 1 skipped (not 182 passed as stated in the plan). The skipped test was pre-existing; the plan's "182 passed" likely counted skipped as passing in a different pytest configuration. No test regressions.

## Known Issues

None.

## Files Created/Modified

- `subnet/hypertensor/mock/mock_db.py` — WAL pragma in `_connect()`; env-var path resolution in `__init__`
- `subnet/node/mock.py` — `import os` added; `TAMPER_RATE` now reads from env var with safe fallback
