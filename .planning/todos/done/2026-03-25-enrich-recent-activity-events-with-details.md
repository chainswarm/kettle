---
created: 2026-03-25T17:28:00.000Z
title: Enrich recent activity events with detailed data like admin event inspector
area: ui
files:
  - dashboard/src/views/NodeDetailView.vue
  - dashboard/src/components/EventFeed.vue
  - dashboard/src/views/AdminView.vue
---

## Problem

The "Recent Activity" section on the node detail page shows bare-bones events:
```
heartbeat    Epoch 14787244
work_record  Epoch 14787244
tee_quote    Epoch 14787244
```

Just type + epoch, no useful details. The admin view has an event inspector that shows richer data (TEE score, measurement, work output, etc.) but the node detail and event feed don't surface this.

## Solution

Expand event items in Recent Activity to show key fields per event type:
- **heartbeat** — TEE score, GPU, models, subnet_node_id
- **tee_quote** — backend, measurement (truncated), TCB status
- **work_record** — result hash, tampered flag, parity
- **overwatch** — pass/fail, audit details

Use a collapsible/expandable row or inline summary. Reference AdminView's event inspector for the data extraction patterns.
