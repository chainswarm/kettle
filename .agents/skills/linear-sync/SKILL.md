---
name: linear-sync
description: "Use when the user invokes $linear-sync or asks to sync/start Kettle with Linear. Starts or refreshes the local Linear webhook worker, Cloudflare tunnel, and Linear webhook URL for local Codex/GSD execution."
---

# Linear Sync

Use this skill for `$linear-sync`.

## Start or Refresh

Run:

```bash
python3 scripts/start_linear_agent_stack.py
```

Then report:

- worker health
- current webhook URL
- trigger phrase
- log paths

The default behavior is restart-and-refresh: stop the managed worker/tunnel,
start fresh processes, and update Linear to the new tunnel URL.

If the user explicitly asks to reuse existing processes, run:

```bash
python3 scripts/start_linear_agent_stack.py --reuse
```

## Status

If the user asks whether it is running, run:

```bash
python3 scripts/start_linear_agent_stack.py --status
```

## Stop

If the user asks to stop Linear sync, run:

```bash
python3 scripts/start_linear_agent_stack.py --stop
```

## Trigger From Linear

After sync is running, Linear comments that contain the trigger phrase start
local Codex/GSD work. Default:

```text
@kettle <task>
```

## Safety

Do not print `.env`, `LINEAR_ACCESS_TOKEN`, `LINEAR_WEBHOOK_SECRET`,
`LINEAR_CLIENT_SECRET`, or payload contents from `.linear-agent/jobs/`.
