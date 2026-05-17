# Kettle Agent Instructions

This repository is intended to be operated by local Codex with repo-local
skills.

## First Action

When starting a Codex session for Kettle, run:

```text
$linear-sync
```

This starts or refreshes:

- the local Linear webhook worker
- the Cloudflare tunnel
- the Linear webhook URL

The command restarts the managed worker/tunnel by default and refreshes Linear
to the new tunnel URL. Use `python3 scripts/start_linear_agent_stack.py --status`
to inspect current processes without restarting.

After sync is running, Linear comments containing the trigger phrase start local
Codex/GSD work:

```text
@kettle <task>
```

## Local Skills

Use these repo-local skills when relevant:

- `linear-sync` — start/refresh/stop Linear local agent sync.
- `linear-local-agent` — operate and troubleshoot Linear webhook delivery.
- `linear-plan-sync` — sync GSD project/milestone/phases/todos into Linear.
- `gsd-linear-auto` — run GSD autonomous mode, then sync planning to Linear.
- `hypertensor-subnet` — Hypertensor terminology and architecture rules.

## Secrets

Secrets stay in local `.env` only. Never print, commit, or paste:

- `LINEAR_ACCESS_TOKEN`
- `LINEAR_WEBHOOK_SECRET`
- `LINEAR_CLIENT_SECRET`
- Linear webhook payloads under `.linear-agent/jobs/`

`.env` and `.linear-agent/` are ignored by git.

## Hypertensor Terminology

Use Hypertensor-native wording:

- Say **node**, not miner or validator, for participant software.
- Say **Overwatch node** for the separately registered auditor.
- Treat **Validator** as a rotating chain classification/election status, not a
  permanent node type.

Before changing subnet behavior, read `CLAUDE.md` and use the
`hypertensor-subnet` skill.

## Project Control

Use GSD 1.x as the project state machine for Kettle:

- quick Linear issues: `$gsd-quick --validate`
- larger scoped work: phase workflows
- shipping: `$gsd-ship`

Superpowers skills are supporting discipline for brainstorming, debugging,
TDD, and verification.

## Linear Planning Sync

Use `$linear-plan-sync` to publish the GSD planning hierarchy into Linear:

- GSD project -> Linear Project
- GSD milestone -> Linear Project Milestone
- GSD phase -> Linear Issue
- GSD pending todo -> Linear backlog issue

GSD remains the source of truth for technical details.

Use `$gsd-linear-auto` when you want autonomous GSD execution followed by a
Linear planning sync.
