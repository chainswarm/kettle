---
created: 2026-03-25T16:45:00.000Z
title: Fix dashboard unknown data and make graph nodes draggable with labels
area: ui
files:
  - dashboard/src/components/NetworkTopology.vue
  - dashboard/src/views/ExplorerView.vue
  - dashboard/src/stores/network.ts
  - subnet/dashboard/rest_api.py
---

## Problem

Dashboard has several display issues observed during cross-CVM testing:

1. **Unknown data positions** — several fields show "unknown", "0", or empty where real data should appear (e.g. subnet_node_id was showing 0 for all nodes — JSON parsing fix deployed but other fields may still be affected)
2. **Network topology graph nodes are static** — can't drag/reposition nodes to inspect the mesh layout
3. **Graph nodes have no labels** — just dots, no peer_id or node_id shown, hard to identify which node is which

## Solution

1. Audit all dashboard views for fields showing unknown/empty/zero — trace back to REST API and fix JSON extraction
2. Make NetworkTopology.vue graph nodes draggable (likely needs d3-force or similar interaction)
3. Add labels to graph nodes — show truncated peer_id or subnet_node_id on/near each node
