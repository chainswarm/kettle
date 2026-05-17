---
name: linear-plan-sync
description: "Use when the user invokes $linear-plan-sync or asks to sync GSD planning, milestones, phases, todos, backlog, or roadmap structure into Linear Projects."
---

# Linear Plan Sync

Use this skill for `$linear-plan-sync`.

## Run

```bash
python3 scripts/sync_gsd_to_linear.py
```

This performs a conservative one-way sync:

- GSD project -> Linear Project
- GSD current milestone -> Linear Project Milestone
- GSD current milestone -> one Linear milestone issue with ordered phase checklist
- GSD pending todos -> Linear backlog issues
- GSD planning docs -> Linear Documents attached to the project

It writes the tracked mapping file:

```text
.planning/integrations/linear-map.json
```

## Dry Run

If the user asks to preview:

```bash
python3 scripts/sync_gsd_to_linear.py --dry-run
```

## Boundary

GSD remains the source of truth for technical planning and verification. Linear
is the coordination/project UI. Do not let Linear directly rewrite `.planning/`
artifacts.
