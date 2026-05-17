---
id: T02
parent: S03
milestone: M002
provides:
  - subnet/node/mock.py with SealedStore wired into MockNodeProtocol (register_handlers + miner_loop)
  - tests/tee/test_sealed_integration.py — all 3 integration tests now passing
key_files:
  - subnet/node/mock.py
key_decisions:
  - Lazy imports inside register_handlers (matching existing pattern) used for SealedStore and MOCK_MEASUREMENT/MOCK_DEV_KEY imports
  - Used MOCK_DEV_KEY from subnet.tee.backends.mock (canonical import), not the local _MOCK_KEY module constant, so _sealed_store.measurement returns the canonical mock value
  - _seal_key local variable (leading underscore) avoids shadowing the module-level _MOCK_KEY constant
patterns_established:
  - SealedStore instantiated in register_handlers alongside other TEE components (_publisher, _verifier)
  - seal_json called immediately after tamper block, before OutputEnvelope.create — stats are sealed before the work record is published
observability_surfaces:
  - "[SealedStore] Initialised with measurement=<hex[:16]>..." (DEBUG) — logged once per register_handlers call"
  - "[SealedStore] Sealed key=epoch_stats:... (<n> bytes)" (DEBUG) — logged on every miner_loop seal call"
  - "[MockMiner] sealed epoch_stats epoch=<n> peer=<prefix>" (INFO) — grep-able signal that sealing is active"
  - "db.nmap_get('sealed', 'epoch_stats:{peer_id}:{epoch}') — returns raw encrypted blob; non-None = sealed"
  - "miner._sealed_store.exists('epoch_stats:{peer_id}:{epoch}') — True after miner_loop runs"
duration: ~10m
verification_result: passed
completed_at: 2026-03-16
blocker_discovered: false
---

# T02: Wire SealedStore into MockNodeProtocol

**Wired `SealedStore` into `MockNodeProtocol.register_handlers` and `miner_loop`, making all 3 S03 integration tests pass with zero regressions (176/176 tests green).**

## What Happened

Added two changes to `subnet/node/mock.py`:

1. **`register_handlers`** — After `self._verifier = DcapVerifier(...)`, added lazy imports for `SealedStore` and `MOCK_MEASUREMENT`/`MOCK_DEV_KEY`, then instantiated `self._sealed_store = SealedStore(db=self.db, measurement=MOCK_MEASUREMENT, mock_key=MOCK_DEV_KEY)`.

2. **`miner_loop`** — After the tamper injection block and before `OutputEnvelope.create`, added:
   - `_seal_key = f"epoch_stats:{self.peer_id}:{epoch}"`
   - `self._sealed_store.seal_json(_seal_key, {"n": n, "parity": parity})`
   - `logger.info("[MockMiner] sealed epoch_stats epoch=%d peer=%s", epoch, self.peer_id[:16])`

No new files were created. Only `subnet/node/mock.py` was modified.

## Verification

```
# Integration tests (T01's 3 failing tests, now passing)
python3 -m pytest tests/tee/test_sealed_integration.py -v
→ 3/3 PASSED

# Mock node tests (no regressions)
python3 -m pytest tests/test_mock_node.py -v
→ 24/24 PASSED

# Sealed unit tests (no regressions)
python3 -m pytest tests/tee/test_sealed.py -v
→ 21/21 PASSED

# Full suite
python3 -m pytest tests/ --ignore=tests/hypertensor -q
→ 176/176 PASSED
```

## Diagnostics

- `db.nmap_get("sealed", f"epoch_stats:{peer_id}:{epoch}")` — returns opaque encrypted blob; non-None confirms sealing is active
- `miner._sealed_store.exists(f"epoch_stats:{peer_id}:{epoch}")` — returns `True` after `miner_loop` runs
- `miner._sealed_store.unseal(f"epoch_stats:{peer_id}:{epoch}")` — returns raw JSON bytes; `json.loads(...)` yields `{"n": <int>, "parity": "even"|"odd"}`
- `SealedDecryptionError` raised when a different-measurement store tries to unseal — carries `key=...` and `measurement mismatch or corruption` in message
- Grep pattern for miner activity: `[MockMiner] sealed epoch_stats epoch=`

## Deviations

None. Plan followed exactly.

## Known Issues

None.

## Files Created/Modified

- `subnet/node/mock.py` — added `self._sealed_store` in `register_handlers`; added `seal_json` call + INFO log in `miner_loop`
