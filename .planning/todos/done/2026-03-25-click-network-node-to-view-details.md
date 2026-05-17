---
created: 2026-03-25T17:20:00.000Z
title: Click network topology node to view its details
area: ui
files:
  - dashboard/src/components/NetworkTopology.vue
  - dashboard/src/views/NodeDetailView.vue
  - dashboard/src/router/index.ts
---

## Problem

Network topology graph nodes are clickable but don't navigate anywhere. Clicking a node should show its details (TEE score, epoch, GPU info, events, etc.).

## Solution

Add click handler to NetworkTopology.vue graph nodes that navigates to NodeDetailView (route already exists at `/nodes/:peerId`). Distinguish click from drag — only navigate if the node wasn't dragged.
