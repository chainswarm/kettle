---
name: gsd-linear-auto
description: "Use when the user invokes $gsd-linear-auto or asks to run GSD autonomous mode and sync the result to Linear. Runs GSD autonomous work first, then syncs GSD planning to Linear."
---

# GSD Linear Auto

Use this skill for `$gsd-linear-auto`.

## Workflow

1. Execute the GSD autonomous workflow:

```text
$gsd-autonomous
```

Pass through any user arguments after `$gsd-linear-auto` to `$gsd-autonomous`
where they make sense, for example `--only 3`, `--from 2`, `--to 5`, or
`--interactive`.

2. After GSD autonomous completes or stops cleanly, run:

```bash
python3 scripts/sync_gsd_to_linear.py
```

3. Report:

- autonomous outcome
- Linear sync outcome
- changed files/commits
- any blocker that prevented sync

## Boundaries

Do not run Linear sync if GSD autonomous aborts with unresolved conflicts or
leaves `.planning` in an obviously invalid state. In that case, report the GSD
blocker first.

GSD is the source of truth. Linear is updated after GSD changes are written.
