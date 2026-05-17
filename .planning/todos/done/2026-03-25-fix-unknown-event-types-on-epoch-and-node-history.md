---
created: 2026-03-25T17:25:00.000Z
title: Fix unknown event types on epoch timeline and node history pages
area: ui
files:
  - dashboard/src/views/EpochTimelineView.vue
  - dashboard/src/views/NodeDetailView.vue
  - dashboard/src/views/NodeHistoryView.vue
  - dashboard/src/composables/useExplorerApi.ts
  - subnet/dashboard/rest_api.py
  - subnet/dashboard/explorer/router.py
---

## Problem

Multiple "unknown" labels appear across the dashboard:

1. **Epoch timeline** — expanding an epoch shows events with "unknown" type badge. The epoch summary bar shows correct types (heartbeat: N, tee_quote: N) but the expanded event list shows "unknown" because `event.data.type` is not set.

2. **Node history** — events listed as "unknown" for the same reason.

3. **Node detail** — similar issue with event types.

Root cause: The explorer API returns events from RocksDB where the event type (heartbeat, tee_quote, mock_work) is derived from the topic/nmap name, not stored inside the event data. The frontend expects `event.data.type` but the API doesn't inject it.

## Solution

Two approaches:
1. **Backend fix** — in the explorer API router, inject the event type into `event.data.type` based on which nmap/topic the event was read from. This is the cleanest fix.
2. **Frontend fix** — in `useExplorerApi.ts`, infer the type from the event key pattern or data shape.

Backend fix is preferred — the API should always return complete data.
