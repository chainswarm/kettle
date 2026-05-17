# Phase 5: Explorer API - Context

**Gathered:** 2026-03-25
**Status:** Ready for planning
**Mode:** Auto-generated (infrastructure phase)

<domain>
## Phase Boundary

REST endpoints for querying indexed security events, epoch history, node history, and overwatch audit log. Extends the existing dashboard-api (FastAPI at port 8100).

</domain>

<decisions>
## Implementation Decisions

### Claude's Discretion
All implementation choices are at Claude's discretion — infrastructure phase. Build on Phase 4's SecurityEventIndexer with its triple-nmap indexing (by_time, by_peer, by_type).

Key constraints:
- Extend existing dashboard-api (subnet/dashboard/rest_api.py or new router)
- Use secondary RocksDB instance (already working in dashboard-api)
- Query the security_events nmaps from Phase 4
- Return JSON, paginated where appropriate
- Filter by epoch range, peer_id, event_type, severity, hardware_id

</decisions>

<code_context>
## Existing Code Insights

### Reusable Assets
- `subnet/security/events.py` — SecurityEvent, SecurityEventIndexer with query methods
- `subnet/api/routers/v1/security_events.py` — Already has basic security events API from Phase 4
- `subnet/dashboard/rest_api.py` — Existing REST router with /api/nodes, /api/events, /api/topology
- `subnet/dashboard/ws_bridge.py` — WebSocket bridge for real-time events

### Integration Points
- Dashboard-api already reads from node-1's RocksDB via secondary mode
- New endpoints extend the existing FastAPI app
- Phase 4 already created security events API endpoints — Phase 5 adds epoch history, node history, overwatch audit, search

</code_context>

<specifics>
## Specific Ideas

No specific requirements — extend what Phase 4 built with richer query endpoints.

</specifics>

<deferred>
## Deferred Ideas

None

</deferred>
