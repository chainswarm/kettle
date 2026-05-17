# Phase 6: Explorer UI - Context

**Gathered:** 2026-03-25
**Status:** Ready for planning
**Mode:** Auto-generated

<domain>
## Phase Boundary

Vue.js explorer views integrated into the existing dashboard — epoch timeline, node history, overwatch log, search. Uses the Explorer API endpoints from Phase 5. Extends the existing Vue.js + Tailwind dashboard with new views and nav items. Same white and light green theme.

</domain>

<decisions>
## Implementation Decisions

### Claude's Discretion
- Extend existing dashboard at `dashboard/` — add new Vue views and router entries
- Use the `/api/explorer/` endpoints from Phase 5
- Match existing white + light green Tailwind theme
- Add nav items to existing AppHeader component
- Use same composables pattern (useWebSocket.ts, network store)

</decisions>

<code_context>
## Existing Code Insights

### Reusable Assets
- `dashboard/src/views/ExplorerView.vue` — existing explorer view (basic node list)
- `dashboard/src/views/AdminView.vue` — admin view pattern
- `dashboard/src/views/NodeDetailView.vue` — node detail pattern
- `dashboard/src/components/EventFeed.vue` — event feed component
- `dashboard/src/components/StatusBadge.vue` — status badge
- `dashboard/src/stores/network.ts` — Pinia network store
- `dashboard/src/composables/useWebSocket.ts` — WebSocket composable
- `dashboard/src/router/index.ts` — Vue Router config
- `dashboard/src/components/AppHeader.vue` — navigation header

### Integration Points
- Add routes to router/index.ts
- Add nav links to AppHeader.vue
- New views call /api/explorer/* endpoints
- Reuse StatusBadge, EventFeed patterns

</code_context>

<specifics>
## Specific Ideas

User wants:
- Epoch timeline (browse epochs, see events per epoch)
- Node history (all security events for a node, drill from node card)
- Overwatch audit log (dedicated page for slash events)
- Search bar (search across peer_id, epoch, hardware_id, event type)
- White and light green theme (already established)

</specifics>

<deferred>
## Deferred Ideas

None

</deferred>
