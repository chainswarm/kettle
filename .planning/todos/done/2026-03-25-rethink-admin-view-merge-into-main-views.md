---
created: 2026-03-25T17:30:00.000Z
title: Rethink admin view — merge overwatch and event inspector into main views
area: ui
files:
  - dashboard/src/views/AdminView.vue
  - dashboard/src/views/ExplorerView.vue
  - dashboard/src/views/NodeDetailView.vue
  - dashboard/src/components/OverwatchFeed.vue
  - dashboard/src/router/index.ts
---

## Problem

The admin view currently has:
- Overwatch activity feed
- Event inspector (raw data viewer)
- DB stats

If overwatch activity is moved to the main explorer/node views and event details are enriched (see related todo), the admin view becomes redundant. The auth-gated admin page adds complexity without clear value if all useful data is in the main views.

## Solution

1. Move OverwatchFeed component to ExplorerView (alongside EventFeed)
2. Add event inspector / expandable raw data to the enriched event items
3. DB stats could move to a simple footer or debug panel
4. Remove AdminView and its auth gate, or keep it as a minimal debug-only page
5. Update router to remove /admin or make it optional
