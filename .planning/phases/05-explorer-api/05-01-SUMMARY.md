---
phase: "05"
plan: "01"
subsystem: dashboard-explorer
tags: [api, explorer, security-events, audit, search]
dependency-graph:
  requires: [dashboard-rest-api, rocksdb-nmap]
  provides: [explorer-api-events, explorer-api-epochs, explorer-api-audit, explorer-api-search]
  affects: [dashboard-ws-bridge]
tech-stack:
  added: [pydantic-models-explorer]
  patterns: [event-indexer, severity-classification, paginated-responses]
key-files:
  created:
    - subnet/dashboard/explorer/__init__.py
    - subnet/dashboard/explorer/models.py
    - subnet/dashboard/explorer/indexer.py
    - subnet/dashboard/explorer/router.py
    - tests/dashboard/__init__.py
    - tests/dashboard/test_explorer_api.py
  modified:
    - subnet/dashboard/ws_bridge.py
decisions:
  - "Used EventIndexer pattern that scans RocksDB nmaps on each request rather than maintaining in-memory state -- simpler, stateless, and the RocksDB nmap scan is fast for typical subnet sizes"
  - "Mapped existing nmap topics (heartbeat, tee_quote, mock_work) to security event types with severity classification based on data content (tampered=critical, parity_fail=warning)"
  - "Extended existing dashboard FastAPI app via separate router prefix /api/explorer rather than modifying existing /api endpoints"
metrics:
  duration: "~5 min"
  completed: "2026-03-25"
  tasks: 3
  files-created: 6
  files-modified: 1
  tests-added: 34
---

# Phase 5 Plan 1: Explorer API Summary

**Explorer API with filtered security event queries, epoch summaries, node history, overwatch audit logs, and cross-entity search over existing RocksDB nmap data**

## What Was Built

Six new REST API endpoints mounted under `/api/explorer/` in the existing dashboard FastAPI app:

| Endpoint | Requirement | Purpose |
|----------|------------|---------|
| `GET /api/explorer/events` | EXP-01 | Query security events with filters (epoch range, peer_id, event_type, severity) |
| `GET /api/explorer/epochs` | EXP-02 | Epoch history with per-epoch summaries (node count, events, scores, tamper status) |
| `GET /api/explorer/epochs/{epoch}` | EXP-02 | Single epoch detail view |
| `GET /api/explorer/nodes/{peer_id}/history` | EXP-03 | Full event history for a specific node |
| `GET /api/explorer/audit` | EXP-04 | Overwatch audit log with slash history and tamper evidence |
| `GET /api/explorer/search` | EXP-05 | Search by peer_id, epoch, event_type, hardware_id |

### Architecture

- **Models** (`models.py`): SecurityEvent, EpochSummary, AuditLogEntry, SearchResult, PaginatedResponse Pydantic models with EventType and Severity enums
- **Indexer** (`indexer.py`): EventIndexer reads from RocksDB nmaps (heartbeat, tee_quote, mock_work) and provides filtered, paginated queries with severity classification
- **Router** (`router.py`): FastAPI APIRouter with all 6 endpoints, mounted in ws_bridge.py under `/api/explorer`

### Severity Classification

Events are automatically classified:
- **CRITICAL**: Work records with `tampered=True`
- **WARNING**: TEE quotes with `tee_score < 1.0`, work records with `parity_ok=False`
- **INFO**: All other events (heartbeats, normal quotes/work)

## Commits

| Task | Commit | Description |
|------|--------|-------------|
| 1 | 4c27389 | Security event models and indexer |
| 2 | 18e6f8b | Explorer API endpoints (all 6 routes) |
| 3 | b574883 | 34 comprehensive tests |

## Test Results

- 34 new tests added covering all endpoints and filter combinations
- 434 total tests collected (400 existing + 34 new)
- 433 passed, 1 skipped (pre-existing skip), 0 failures

## Deviations from Plan

None - plan executed exactly as written.

## Known Stubs

None. All endpoints return real data from RocksDB nmaps.

## Self-Check: PASSED

All 6 created files verified on disk. All 3 commit hashes verified in git log.
