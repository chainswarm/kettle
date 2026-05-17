# Linear Agent Integration

Kettle uses Linear as the task intake UI, GSD 1.x as the local project state
machine, local Codex as the executor, and GitHub as the review boundary.

```text
Linear Agent Session
  -> local webhook worker
    -> scripts/run_linear_gsd_task.sh
      -> codex exec
        -> GSD 1.x workflow
          -> GitHub branch / PR
```

## Linear Application

Create a Linear application named **Kettle Local Agent**.

Required settings:

- Enable webhooks.
- Select **Agent session events**.
- For early debugging, also enable Inbox notifications and Permission changes.
- Use a public HTTPS webhook URL, not localhost:
  `https://<tunnel-host>/webhooks/linear`.
- Install the app with `actor=app`.
- Request scopes:
  `read`, `write`, `comments:create`, `app:assignable`, `app:mentionable`.

Linear Agent APIs are in Developer Preview, so fields can change. The local
worker should treat Linear payloads defensively and prefer `promptContext` when
building the Codex prompt.

## Webhook Security

The webhook worker must verify:

- `Linear-Signature` against the raw request body using `LINEAR_WEBHOOK_SECRET`.
- `webhookTimestamp` is recent, normally within 60 seconds.
- Delivery IDs are idempotent so retries do not start duplicate jobs.

The webhook handler must return `200` within 5 seconds. Long work belongs in a
background queue.

## Runtime Contract

For a new `AgentSessionEvent` with action `created`, the worker should:

1. Immediately emit a Linear `thought` activity.
2. Persist the payload and `promptContext`.
3. Start one job for the target repository.
4. Run `scripts/run_linear_gsd_task.sh`.
5. Push the branch and open a GitHub PR.
6. Add the PR URL to the Linear session external URLs.
7. Emit a final `response` or `error` activity.

For a `prompted` event, the worker should append the user prompt to the active
job if it is still running, or start a follow-up job if the prior job completed.

## GSD Routing

Use labels or explicit command text in Linear:

| Linear signal | GSD mode |
|---|---|
| `codex:fast` | `$gsd-fast` |
| `codex:quick` | `$gsd-quick --validate` |
| `codex:phase` | phase workflow |
| `codex:review` | review workflow |
| `codex:ship` | ship workflow |

Default to `$gsd-quick --validate`.

Run only one active job per repository until GSD workstream isolation is wired
and verified.

## Local Setup

Copy `.env.example` to `.env` and fill:

- `LINEAR_CLIENT_ID`
- `LINEAR_CLIENT_SECRET`
- `LINEAR_WEBHOOK_SECRET`
- `LINEAR_ACCESS_TOKEN`
- `LINEAR_REFRESH_TOKEN`
- `LINEAR_PUBLIC_WEBHOOK_URL`

Expose the future webhook worker through Cloudflare Tunnel or an equivalent
public HTTPS endpoint.

Automated start:

```bash
python3 scripts/start_linear_agent_stack.py
```

This starts the worker, starts a Cloudflare quick tunnel, and updates the Linear
webhook named by `LINEAR_WEBHOOK_LABEL` to the current tunnel URL. The default
generic fallback listens to **Comment** events and only starts Codex when the
comment contains `LINEAR_TRIGGER_PHRASE`, default `@kettle`.

Manual smoke test for the local executor:

```bash
LINEAR_ISSUE_ID=KET-1 \
LINEAR_ISSUE_TITLE="Smoke test local GSD runner" \
LINEAR_ISSUE_URL="https://linear.app/<workspace>/issue/KET-1" \
LINEAR_PROMPT_CONTEXT_PATH=/tmp/kettle-linear-prompt-context.txt \
scripts/run_linear_gsd_task.sh
```

The worker implementation should call the same script after writing the Linear
`promptContext` to a local file.
