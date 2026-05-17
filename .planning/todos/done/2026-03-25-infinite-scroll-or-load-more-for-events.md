---
created: 2026-03-25T17:32:00.000Z
title: Add infinite scroll or load-more for event lists
area: ui
files:
  - dashboard/src/components/EventFeed.vue
  - dashboard/src/views/EpochTimelineView.vue
  - dashboard/src/views/NodeDetailView.vue
  - dashboard/src/views/NodeHistoryView.vue
  - dashboard/src/composables/useExplorerApi.ts
---

## Problem

Event feeds and history views show a fixed number of items (EventFeed: 50, store: 200 max). When browsing older events there's no way to load more. Users hit the bottom and see nothing.

## Solution

Add infinite scroll — when the user scrolls near the bottom, automatically fetch the next page of events. Use an IntersectionObserver on a sentinel element at the bottom of the list.

- EventFeed: append older events on scroll (cursor-based: pass last event's epoch/key as offset)
- EpochTimeline: already has pagination buttons — keep those but also add auto-load option
- NodeHistory: load more events for the node on scroll
- API already supports `limit` param — add `offset` or `cursor` param for pagination
