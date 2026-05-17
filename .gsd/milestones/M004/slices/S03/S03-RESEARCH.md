# S03: Restart recovery + observability — Research

**Date:** 2026-03-17

## Summary

S03 is light work. The architecture from S01 already makes restart recovery correct by design: epoch numbers are derived from wall-clock time (`time.time()` → block number → epoch), so a restarted miner picks up the live epoch immediately without any persistent state. Work records land in a named-volume RocksDB (`/app/db`) that survives container restart. Node registration in the shared SQLite is idempotent (`INSERT OR REPLACE`). After restart, `_miner_epoch_loop` starts after a 10 s delay and `_validator_scoring_loop` scores epoch N-1 — both well inside a 120 s epoch (20 blocks × 6 s).

Structured JSON logs are the larger code addition. The existing loops emit human-readable strings via `logging.basicConfig`. Adding a stdlib-only `JsonFormatter` (≈15 lines) wired to the operational loggers, combined with `extra={}` kwargs in the key log calls, satisfies `docker compose logs | jq` with zero new dependencies.

The health endpoint needs one new async function — a minimal `trio` TCP server (stdlib only, ≈20 lines) listening on `:8080`, returning `{"status":"ok"}`. The docker-compose.yml healthcheck then changes from `["CMD", "true"]` to `["CMD-SHELL", "curl -sf http://localhost:8080/health || exit 1"]`.

## Recommendation

Two tasks in order:

1. **JSON logging** — Write `subnet/utils/logging.py` with a `JsonFormatter` class; wire it to the 3 operational loggers (miner, validator, overwatch epoch loops); add `extra={"epoch": N, "peer": ..., "score": ...}` to the key structured log calls. Activate via `LOG_JSON=true` env var (default off; set to `true` in docker-compose.yml for all services).

2. **Health endpoint + restart test** — Add `_health_server(port)` async function to `server.py` that opens a TCP listener and returns `{"status":"ok","epoch":N}`. Wire into `nursery.start_soon` for all non-bootstrap nodes. Update docker-compose.yml healthchecks. Run a live `docker compose restart miner-1` to confirm the node re-scores within one epoch.

Order matters: do JSON logging first so the restart test produces clean jq-able output for verification.

## Implementation Landscape

### Key Files

- `subnet/server/server.py` — All three epoch loops live here. Add `_health_server()` as a new module-level async function, wire via `nursery.start_soon(_health_server, 8080)` in the non-bootstrap block. Add `extra={}` kwargs to `[Validator]`, `[MinerLoop]`, `[Overwatch]` log calls.
- `subnet/utils/logging.py` — **Does not exist yet.** Create it with `JsonFormatter(logging.Formatter)` that overrides `format()` to emit a JSON object with `timestamp`, `level`, `logger`, `message`, and any `extra` fields merged in. Keep it to stdlib only.
- `subnet/cli/run_node.py` — `logging.basicConfig()` is configured here (lines 34–38). After the basicConfig call, check `LOG_JSON` env var and conditionally attach a `JsonFormatter`-backed `StreamHandler` to the root logger (or just the operational loggers: `miner_epoch_loop`, `validator_scoring_loop`, `overwatch_epoch_loop`).
- `docker-compose.tee-dev.yml` — Add `LOG_JSON: "true"` to `x-tee-env` anchor. Change all four service `healthcheck.test` from `["CMD", "true"]` to `["CMD-SHELL", "curl -sf http://localhost:8080/health || exit 1"]`. Add `8080` port expose for non-bootnode services (optional — healthcheck works container-internally without published port).

### Build Order

1. `subnet/utils/logging.py` — standalone, no dependencies, easy to test in isolation with `python3 -c "import logging; from subnet.utils.logging import JsonFormatter; ..."`.
2. `run_node.py` wire-up — one env-var check after `basicConfig`, attaches JSON handler.
3. `extra={}` in epoch loop log calls — surgical edit to 3 functions in `server.py`.
4. `_health_server()` in `server.py` + `nursery.start_soon`.
5. docker-compose.yml healthcheck update.
6. Live restart test.

### Verification Approach

```bash
# JSON output check (from a running compose stack)
docker compose -f docker-compose.tee-dev.yml logs validator | jq '.score' | grep 0.5

# Structured fields present
docker compose -f docker-compose.tee-dev.yml logs miner-1 | \
  jq 'select(.message | startswith("[MinerLoop]")) | {epoch, peer}'

# Health endpoint live
docker compose exec miner-1 curl -sf http://localhost:8080/health
# → {"status":"ok","epoch":14781200}

# Restart recovery
docker compose -f docker-compose.tee-dev.yml up -d
sleep 60   # wait for scoring to stabilise
docker compose restart miner-1
sleep 120  # one full epoch
docker compose logs --since 90s validator | grep "\[Validator\]"
# expect: at least one [Validator] line for miner-1's peer_id

# Unit tests still green
python3 -m pytest tests/ -q --tb=short
# expect: ≥181 passed
```

## Constraints

- **No new runtime dependencies.** `pyproject.toml` must not gain a new package for logging. stdlib `json`, `logging`, `time` are sufficient for `JsonFormatter`. The health server uses `trio` (already the async runtime) and stdlib `http`.
- **Epoch length = 120 s.** Startup delays are 10 s (miner) and 30 s (validator). Both are well within one epoch window — the restart test passes unless the container takes >90 s to boot (never observed).
- **RocksDB at `/app/db` is volume-backed.** Gossip records written by the miner before restart survive. This means the validator may already have the miner's work record for the current epoch and won't miss a score.
- **LOG_JSON guard.** The JSON formatter must be conditional (env var) so that local `python3 -m subnet.cli.run_node` still produces human-readable output without change.
- **Health server port must not conflict.** `38960–38963` are libp2p ports; `8080` is safe and matches the roadmap.

## Common Pitfalls

- **Double-logging.** Attaching a second handler to the root logger while `basicConfig` already added one produces duplicate lines. Fix: either replace the root handler or add the JSON handler only to the specific operational loggers (`logging.getLogger("miner_epoch_loop")` etc.) — the latter is cleaner and avoids flooding with py-libp2p internals.
- **`extra` field collision.** Python's `logging` reserves field names like `message`, `levelname`, `name`. If `JsonFormatter` naively merges `record.__dict__` it will collide. Safe pattern: only merge keys not in `logging.LogRecord.__dict__` defaults — or prefix with the domain (e.g. `epoch` is not a reserved name so it's safe).
- **Bootnode gets no health server.** The `_health_server` call is inside `if not self.is_bootstrap:` — correct, the bootnode has no epoch loop. The docker-compose healthcheck for bootnode should stay `["CMD", "true"]` or use a TCP probe, not HTTP.
- **`curl` may not be in the image.** The Dockerfile base may not include curl. Check — if absent, use `wget -q -O- http://localhost:8080/health` or switch to Python: `python3 -c "import urllib.request; urllib.request.urlopen('http://localhost:8080/health')"`. Verify before committing the healthcheck change.
