---
created: 2026-03-25T17:36:00.000Z
title: Truncate all addresses in 6...4...6 format instead of 6...4
area: ui
files:
  - dashboard/src/components/NodeCard.vue
  - dashboard/src/components/EventFeed.vue
  - dashboard/src/components/OverwatchFeed.vue
  - dashboard/src/components/NetworkTopology.vue
  - dashboard/src/views/EpochTimelineView.vue
  - dashboard/src/views/NodeDetailView.vue
---

## Problem

Peer IDs and addresses are truncated inconsistently across components:
- NodeCard: `${id.slice(0, 8)}...${id.slice(-4)}` → 8...4
- EventFeed: `${peerId.slice(0, 6)}...${peerId.slice(-4)}` → 6...4
- OverwatchFeed: same 6...4
- NetworkTopology: `peerId.slice(8, 16)` → 8 chars middle

User wants consistent `6...4...6` format everywhere (first 6, middle 4, last 6).

## Solution

1. Create a shared `truncateAddress(addr: string): string` utility in a `utils.ts` file
2. Format: `${addr.slice(0, 6)}...${addr.slice(mid-2, mid+2)}...${addr.slice(-6)}`
3. Replace all per-component `truncatePeerId` functions with the shared utility
