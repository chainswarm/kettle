---
phase: 4
plan: 1
subsystem: security
tags: [security, indexing, audit, rocksdb, api]
dependency-graph:
  requires: [tee-verifier, rocksdb-nmap, consensus]
  provides: [security-event-index, security-events-api]
  affects: [tee/verifier.py, consensus/consensus.py, api/routers/v1]
tech-stack:
  added: []
  patterns: [triple-nmap-indexing, optional-observer-pattern]
key-files:
  created:
    - subnet/security/__init__.py
    - subnet/security/events.py
    - subnet/api/routers/v1/security_events.py
    - tests/test_security_event_indexer.py
  modified:
    - subnet/tee/verifier.py
    - subnet/consensus/consensus.py
    - subnet/api/routers/v1/__init__.py
    - subnet/api/models.py
decisions:
  - Triple-nmap indexing (by time, peer, type) for efficient querying
  - Optional observer pattern — indexer is None by default, no-op when absent
  - "Good is good, let it go" — only rejections and failures indexed
metrics:
  duration: 468s
  completed: 2026-03-25
  tasks: 5
  files-created: 4
  files-modified: 4
  tests-added: 38
  total-tests: 437
---

# Phase 4 Plan 1: Security Event Indexer Summary

**One-liner:** Triple-indexed security event store recording TEE rejections, overwatch slashes, and scoring failures into RocksDB nmaps with REST API query endpoints.

## What Was Built

### SecurityEvent Model and Indexer (`subnet/security/events.py`)
- `SecurityEvent` dataclass with event_type, peer_id, epoch, reason, severity, timestamp, details
- `SecurityEventType` enum: 13 event types covering TEE rejections, overwatch slashes, scoring failures
- `SecuritySeverity` enum: LOW (operational), MEDIUM (suspicious), HIGH (active threats), CRITICAL (slashes/vulnerable firmware)
- `SecurityEventIndexer` class with triple-nmap indexing pattern:
  - `security_events` nmap: primary index by timestamp (for recent events)
  - `security_by_peer` nmap: secondary index by peer_id (for per-node audit)
  - `security_by_type` nmap: tertiary index by event type (for type-specific queries)

### DcapVerifier Integration (`subnet/tee/verifier.py`)
- Optional `security_indexer` parameter added to `DcapVerifier.__init__()`
- All 10 rejection paths in `verify()` and `verify_quote()` now call `_index_rejection()`
- Indexer errors are silently caught -- never breaks the verification pipeline
- Backward compatible: existing code that creates DcapVerifier without indexer works unchanged

### Consensus Integration (`subnet/consensus/consensus.py`)
- `SecurityEventIndexer` created in `Consensus.__init__()` and passed to `DcapVerifier`
- Scoring failures in Path 1 (full scoring pipeline) are indexed

### REST API Endpoints (`subnet/api/routers/v1/security_events.py`)
- `GET /v1.0/security-events` — recent events, time-ordered descending
- `GET /v1.0/security-events/by-peer/{peer_id}` — events for a specific peer
- `GET /v1.0/security-events/by-type/{event_type}` — events of a specific type
- `GET /v1.0/security-events/counts` — event counts grouped by type
- `GET /v1.0/security-events/counts/severity` — event counts grouped by severity

### Tests (`tests/test_security_event_indexer.py`)
- 38 new tests covering model, indexer, verifier integration, type mapping, severity assignment
- All 437 tests pass (399 existing + 38 new)

## Design Principle

"Good is good, let it go" -- passing verifications and normal operations produce NO security events. Only rejections, failures, and slashes are indexed. This keeps the index focused and the storage bounded to actual security-relevant activity.

## Commits

| Hash | Message |
|------|---------|
| 010dbbe | feat(04-01): add SecurityEvent model and SecurityEventIndexer |
| 0187cae | feat(04-01): integrate SecurityEventIndexer into DcapVerifier |
| 4e9125b | feat(04-01): wire SecurityEventIndexer into Consensus |
| 650437c | feat(04-01): add security events API endpoints |
| e95cd41 | test(04-01): add comprehensive security event indexer tests |

## Deviations from Plan

None -- plan executed as designed.

## Known Stubs

None -- all components are fully wired and functional.

## Self-Check: PASSED
