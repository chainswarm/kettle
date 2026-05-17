---
created: 2026-03-25T17:34:00.000Z
title: Show node earnings or balance on dashboard
area: ui
files:
  - dashboard/src/views/NodeDetailView.vue
  - dashboard/src/components/NodeCard.vue
  - subnet/dashboard/rest_api.py
  - subnet/hypertensor/chain_functions.py
---

## Problem

Each node has an on-chain address (hotkey) with stake balance and earned rewards, but the dashboard doesn't show any financial info. Node operators want to see their earnings at a glance.

## Solution

Simple approach — no backfilling, just current state:

1. **NodeCard** — show current stake balance next to TEE score
2. **NodeDetailView** — add earnings section with:
   - Current stake balance (from `get_subnet_node_stake_info`)
   - Delegate stake balance
   - Forward-only earning log: track reward events per epoch as they happen (store in local DB alongside heartbeats)

Data source: the mock chain / Hypertensor chain already has `stake_balance`, `node_delegate_stake_balance` per node. Dashboard API just needs to expose it.

For earning history: record each epoch's consensus score + reward amount going forward. No need to backfill — starts tracking from when the feature is deployed.
