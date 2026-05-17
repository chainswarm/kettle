---
name: linear-local-agent
description: "Use when operating the Kettle Linear local agent integration: starting or stopping the webhook worker, Cloudflare tunnel, Linear webhook registration, or troubleshooting Linear-to-local-Codex delivery."
---

# Linear Local Agent

Use this skill when Linear should drive local Codex/GSD work on this machine.

## Start

Run:

```bash
python3 scripts/start_linear_agent_stack.py
```

This starts the local webhook worker, starts a Cloudflare quick tunnel, and
creates or updates the Linear webhook named by `LINEAR_WEBHOOK_LABEL`.

## Stop

Run:

```bash
python3 scripts/start_linear_agent_stack.py --stop
```

## Trigger

The automated webhook listens for Linear **Comment** events. A comment must
contain `LINEAR_TRIGGER_PHRASE`, default `@kettle`, before local Codex starts.

Example:

```text
@kettle implement this issue with GSD quick validate
```

## Secrets

Secrets live only in `.env`:

- `LINEAR_ACCESS_TOKEN`
- `LINEAR_WEBHOOK_SECRET`
- `LINEAR_CLIENT_SECRET`

Never print or commit `.env`, `.linear-agent/`, or webhook payload logs.

## Troubleshooting

- Worker health: `curl http://127.0.0.1:8787/healthz`
- Job files: `find .linear-agent/jobs -maxdepth 1 -type f`
- Worker log: `.linear-agent/worker.log`
- Tunnel log: `.linear-agent/cloudflared.log`
- If no files appear after a trigger comment, Linear is not delivering to the webhook.
