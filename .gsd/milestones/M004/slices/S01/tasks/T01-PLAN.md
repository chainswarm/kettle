---
estimated_steps: 4
estimated_files: 2
---

# T01: Fix MockDatabase WAL mode, env-var DB path, and env-var TAMPER_RATE

**Slice:** S01 — Multi-node epoch loop
**Milestone:** M004

## Description

Two isolated one-liner fixes that unblock multi-container operation:

1. **`mock_db.py` — WAL mode + env-var path**: SQLite in default journal mode deadlocks under concurrent writes from 4 Docker containers. `PRAGMA journal_mode=WAL` serialises writes safely. `MOCK_CHAIN_DB_PATH` env var lets all containers share a single SQLite file on a named Docker volume.

2. **`mock.py` — env-var TAMPER_RATE**: `TAMPER_RATE` is currently a module-level float hardcoded to `1/1000`. Making it env-var-driven allows per-container fault injection (miner-2 can be set higher for the S02 demo without code changes).

Neither change touches any logic or test paths — both are configuration-level changes to initialization code.

## Steps

1. Open `subnet/hypertensor/mock/mock_db.py`. In `_connect()`, immediately after `self.conn = sqlite3.connect(self.db_path, check_same_thread=False)`, add `self.conn.execute("PRAGMA journal_mode=WAL")`.
2. In `MockDatabase.__init__`, change the signature from `def __init__(self, db_path: str = DB_FILE)` to `def __init__(self, db_path: str | None = None)`. At the start of `__init__`, before `self.db_path = db_path`, derive the effective path:
   ```python
   import os
   if db_path is None:
       db_path = os.getenv("MOCK_CHAIN_DB_PATH", DB_FILE)
   self.db_path = db_path
   ```
   (Add `import os` at the top of the file if not already present — it's already used in `reset_database()` so it is imported.)
3. Open `subnet/node/mock.py`. Replace:
   ```python
   TAMPER_RATE = 1 / 1000   # ~0.1% of epochs
   ```
   with:
   ```python
   import os as _os
   try:
       TAMPER_RATE = float(_os.getenv("TAMPER_RATE", "0.001"))
   except (ValueError, TypeError):
       TAMPER_RATE = 0.001
   ```
   The `import os as _os` avoids polluting the module namespace; alternatively add `import os` to the existing imports at the top and reference `os.getenv(...)` there.
4. Run `python3 -m pytest tests/ -q --tb=short` from the repo root. All 182 tests must pass.

## Must-Haves

- [ ] `MockDatabase._connect()` calls `PRAGMA journal_mode=WAL` on every connection
- [ ] `MockDatabase()` with no args uses `os.getenv("MOCK_CHAIN_DB_PATH", "mock_hypertensor.db")` as path
- [ ] `MockDatabase("/custom/path.db")` with explicit arg still uses the given path (env var ignored when explicit path provided)
- [ ] `TAMPER_RATE` reads from `TAMPER_RATE` env var; defaults to `0.001` if unset or invalid
- [ ] All 182 existing tests pass unchanged

## Verification

- `python3 -m pytest tests/ -q --tb=short` — must show `182 passed` (or higher) in < 10s
- `MOCK_CHAIN_DB_PATH=/tmp/test_wal.db python3 -c "from subnet.hypertensor.mock.mock_db import MockDatabase; db = MockDatabase(); print(db.db_path)"` — must print `/tmp/test_wal.db`
- `python3 -c "from subnet.hypertensor.mock.mock_db import MockDatabase; db = MockDatabase(); print(db.db_path)"` — must print `mock_hypertensor.db` (default)
- `TAMPER_RATE=0.5 python3 -c "import subnet.node.mock as m; print(m.TAMPER_RATE)"` — must print `0.5`

## Observability Impact

**Signals introduced:**
- `PRAGMA journal_mode=WAL` is applied silently on every `_connect()` call. Failure would surface as a Python exception on startup (unhandled `sqlite3.OperationalError`). Success is silent — no log line added.
- `MOCK_CHAIN_DB_PATH` env var path is visible via `db.db_path` attribute at runtime. Containers using a shared volume will all print the same path in their startup logs if logging is added.
- `TAMPER_RATE` value is readable via `subnet.node.mock.TAMPER_RATE` at import time.

**How to inspect this task's behavior:**
- WAL mode: `sqlite3 /path/to/mock_hypertensor.db "PRAGMA journal_mode;"` → must return `wal`
- DB path: check container startup logs or run `python3 -c "from subnet.hypertensor.mock.mock_db import MockDatabase; db = MockDatabase(); print(db.db_path)"`
- TAMPER_RATE: `python3 -c "import subnet.node.mock as m; print(m.TAMPER_RATE)"`

**Failure modes made visible:**
- Before this fix: concurrent writes from multiple containers would cause `sqlite3.OperationalError: database is locked` (BUSY errors). After this fix, these errors should not appear in `docker compose logs`.
- If `MOCK_CHAIN_DB_PATH` is unset, fallback to `mock_hypertensor.db` (local file) is silent.
- If `TAMPER_RATE` env var contains a non-numeric value, the `except` clause silently resets to `0.001`.

## Inputs

- `subnet/hypertensor/mock/mock_db.py` — existing file; `_connect()` and `__init__` are the only methods touched
- `subnet/node/mock.py` — existing file; only the module-level `TAMPER_RATE` constant is changed

## Expected Output

- `subnet/hypertensor/mock/mock_db.py` — `_connect()` has WAL pragma; `__init__` accepts `None` and reads env var
- `subnet/node/mock.py` — `TAMPER_RATE` is env-var-driven with safe fallback
