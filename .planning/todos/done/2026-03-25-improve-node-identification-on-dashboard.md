---
created: 2026-03-25T17:22:00.000Z
title: Improve node identification on dashboard
area: ui
files:
  - dashboard/src/components/NodeCard.vue
  - dashboard/src/components/NetworkTopology.vue
  - subnet/utils/pubsub/heartbeat.py
---

## Problem

Dashboard shows "Node #4", "Node #2" etc. using `subnet_node_id` from the mock chain. This number is assigned at registration time and differs between mock chain instances (tee-one has {1,2,3,4}, teetwo has {1,3,4,5} for the same peers). It's not a stable, deterministic identifier.

Users need a reliable way to identify nodes across different dashboard views and CVMs.

## Solution

Options to investigate:
1. Show truncated peer_id (e.g. `KxAhu5U8`) as primary identifier — deterministic, derived from private key
2. Show both: "Node #4 (KxAhu5U8)" — chain ID + peer fingerprint
3. Allow node operators to set a custom name/alias in heartbeat data
4. Use the key file name as a human-friendly label (alith, baltathar, charleth, dorothy)

The peer_id is the only truly deterministic identifier across all environments. NodeCard already shows truncated peer_id below the node ID — consider making it more prominent or using it as the primary label.
