#!/usr/bin/env python3
"""Start the local Linear/Codex stack and update Linear's webhook URL."""

from __future__ import annotations

import argparse
from http.client import HTTPConnection
import json
import os
from pathlib import Path
import re
import secrets
import signal
import subprocess
import sys
import time
from typing import Any
from urllib import request as urllib_request


ROOT = Path(__file__).resolve().parents[1]
STATE_DIR = ROOT / ".linear-agent"
WORKER_PID = STATE_DIR / "worker.pid"
TUNNEL_PID = STATE_DIR / "cloudflared.pid"
TUNNEL_LOG = STATE_DIR / "cloudflared.log"
WORKER_LOG = STATE_DIR / "worker.log"
ENV_PATH = ROOT / ".env"


def load_env() -> dict[str, str]:
    env = os.environ.copy()
    if ENV_PATH.exists():
        for raw_line in ENV_PATH.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            env.setdefault(key.strip(), value.strip().strip('"').strip("'"))
    return env


def upsert_env(values: dict[str, str]) -> None:
    lines = ENV_PATH.read_text(encoding="utf-8").splitlines() if ENV_PATH.exists() else []
    seen: set[str] = set()
    next_lines: list[str] = []
    for line in lines:
        if "=" not in line or line.strip().startswith("#"):
            next_lines.append(line)
            continue
        key = line.split("=", 1)[0].strip()
        if key in values:
            next_lines.append(f'{key}="{values[key]}"')
            seen.add(key)
        else:
            next_lines.append(line)
    for key, value in values.items():
        if key not in seen:
            next_lines.append(f'{key}="{value}"')
    ENV_PATH.write_text("\n".join(next_lines) + "\n", encoding="utf-8")


def is_running(pid_file: Path) -> bool:
    if not pid_file.exists():
        return False
    try:
        os.kill(int(pid_file.read_text(encoding="utf-8").strip()), 0)
        return True
    except Exception:
        return False


def pid_value(pid_file: Path) -> int | None:
    if not pid_file.exists():
        return None
    try:
        return int(pid_file.read_text(encoding="utf-8").strip())
    except Exception:
        return None


def proc_cmdline(pid: int) -> str:
    cmdline = Path(f"/proc/{pid}/cmdline")
    if not cmdline.exists():
        return ""
    return cmdline.read_text(encoding="utf-8", errors="replace").replace("\x00", " ").strip()


def pid_matches(pid_file: Path, expected: str) -> bool:
    pid = pid_value(pid_file)
    if pid is None or not is_running(pid_file):
        return False
    return expected in proc_cmdline(pid)


def status(env: dict[str, str]) -> None:
    port = int(env.get("LINEAR_AGENT_PORT", "8787"))
    worker_pid = pid_value(WORKER_PID)
    tunnel_pid = pid_value(TUNNEL_PID)
    worker_ok = health_ok(port)
    tunnel_url = parse_tunnel_url()
    print("Linear local agent status")
    print(f"- worker pid: {worker_pid or 'none'}")
    print(f"- worker health: {'ok' if worker_ok else 'down'}")
    print(f"- tunnel pid: {tunnel_pid or 'none'}")
    print(f"- tunnel url: {tunnel_url or 'unknown'}")
    print(f"- webhook url: {env.get('LINEAR_PUBLIC_WEBHOOK_URL') or 'unknown'}")
    print(f"- trigger: {env.get('LINEAR_TRIGGER_PHRASE', '@kettle')}")


def stop_pid(pid_file: Path) -> None:
    if not pid_file.exists():
        return
    try:
        pid = int(pid_file.read_text(encoding="utf-8").strip())
        os.kill(pid, signal.SIGTERM)
        print(f"Stopped PID {pid} from {pid_file}")
    except ProcessLookupError:
        pass
    except Exception as exc:
        print(f"WARNING: could not stop {pid_file}: {exc}", file=sys.stderr)
    pid_file.unlink(missing_ok=True)


def health_ok(port: int) -> bool:
    try:
        conn = HTTPConnection("127.0.0.1", port, timeout=1)
        conn.request("GET", "/healthz")
        resp = conn.getresponse()
        return resp.status == 200
    except Exception:
        return False


def start_worker(env: dict[str, str]) -> None:
    port = int(env.get("LINEAR_AGENT_PORT", "8787"))
    if health_ok(port):
        print(f"Worker already responds on http://127.0.0.1:{port}")
        if not pid_matches(WORKER_PID, "linear_agent_webhook.py"):
            print("WARNING: worker is healthy but PID file is stale or missing")
        return

    if WORKER_PID.exists() and not pid_matches(WORKER_PID, "linear_agent_webhook.py"):
        WORKER_PID.unlink(missing_ok=True)

    STATE_DIR.mkdir(parents=True, exist_ok=True)
    log = WORKER_LOG.open("ab")
    proc = subprocess.Popen(
        [sys.executable, str(ROOT / "scripts" / "linear_agent_webhook.py")],
        cwd=ROOT,
        env=env,
        stdout=log,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    WORKER_PID.write_text(str(proc.pid), encoding="utf-8")
    for _ in range(30):
        if health_ok(port):
            print(f"Started worker PID {proc.pid} on http://127.0.0.1:{port}")
            return
        time.sleep(0.2)
    raise RuntimeError(f"worker did not become healthy; see {WORKER_LOG}")


def start_tunnel(env: dict[str, str]) -> str:
    if not shutil_which("cloudflared"):
        raise RuntimeError("cloudflared is not installed")

    port = int(env.get("LINEAR_AGENT_PORT", "8787"))
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    if pid_matches(TUNNEL_PID, "cloudflared tunnel --url"):
        print("Existing cloudflared process is running; reading previous URL from log")
        url = parse_tunnel_url()
        if url:
            return url
        stop_pid(TUNNEL_PID)
    elif TUNNEL_PID.exists():
        TUNNEL_PID.unlink(missing_ok=True)

    log = TUNNEL_LOG.open("wb")
    proc = subprocess.Popen(
        ["cloudflared", "tunnel", "--url", f"http://127.0.0.1:{port}"],
        cwd=ROOT,
        stdout=log,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    TUNNEL_PID.write_text(str(proc.pid), encoding="utf-8")
    for _ in range(120):
        url = parse_tunnel_url()
        if url:
            print(f"Started cloudflared PID {proc.pid}: {url}")
            return url
        if proc.poll() is not None:
            raise RuntimeError(f"cloudflared exited early; see {TUNNEL_LOG}")
        time.sleep(0.5)
    raise RuntimeError(f"timed out waiting for tunnel URL; see {TUNNEL_LOG}")


def shutil_which(command: str) -> str | None:
    for directory in os.getenv("PATH", "").split(os.pathsep):
        candidate = Path(directory) / command
        if candidate.exists() and os.access(candidate, os.X_OK):
            return str(candidate)
    return None


def parse_tunnel_url() -> str | None:
    if not TUNNEL_LOG.exists():
        return None
    text = TUNNEL_LOG.read_text(encoding="utf-8", errors="replace")
    match = re.search(r"https://[-a-zA-Z0-9]+\.trycloudflare\.com", text)
    return match.group(0) if match else None


def linear_graphql(env: dict[str, str], query: str, variables: dict[str, Any] | None = None) -> dict[str, Any]:
    token = env.get("LINEAR_ACCESS_TOKEN")
    if not token:
        raise RuntimeError("LINEAR_ACCESS_TOKEN is not configured")
    auth_value = token if token.startswith("lin_api_") or token.lower().startswith("bearer ") else f"Bearer {token}"
    body = json.dumps({"query": query, "variables": variables or {}}).encode("utf-8")
    req = urllib_request.Request(
        "https://api.linear.app/graphql",
        data=body,
        headers={"Authorization": auth_value, "Content-Type": "application/json"},
        method="POST",
    )
    with urllib_request.urlopen(req, timeout=20) as response:  # noqa: S310 - fixed Linear API URL
        payload = json.loads(response.read().decode("utf-8"))
    if payload.get("errors"):
        raise RuntimeError("; ".join(error.get("message", str(error)) for error in payload["errors"]))
    return payload["data"]


def ensure_webhook(env: dict[str, str], public_url: str) -> str:
    label = env.get("LINEAR_WEBHOOK_LABEL", "Kettle Local Agent")
    secret = env.get("LINEAR_WEBHOOK_SECRET") or f"lin_wh_{secrets.token_urlsafe(32)}"
    webhook_url = f"{public_url.rstrip('/')}/webhooks/linear"

    data = linear_graphql(env, "query { webhooks(first: 100) { nodes { id label url enabled } } }")
    existing = next((node for node in data["webhooks"]["nodes"] if node.get("label") == label), None)

    if existing:
        mutation = """
        mutation UpdateWebhook($id: String!, $input: WebhookUpdateInput!) {
          webhookUpdate(id: $id, input: $input) { success webhook { id label url enabled } }
        }
        """
        linear_graphql(
            env,
            mutation,
            {
                "id": existing["id"],
                "input": {
                    "label": label,
                    "enabled": True,
                    "url": webhook_url,
                    "secret": secret,
                    "resourceTypes": ["Comment"],
                },
            },
        )
        print(f"Updated Linear webhook {label!r} -> {webhook_url}")
    else:
        mutation = """
        mutation CreateWebhook($input: WebhookCreateInput!) {
          webhookCreate(input: $input) { success webhook { id label url enabled } }
        }
        """
        linear_graphql(
            env,
            mutation,
            {
                "input": {
                    "label": label,
                    "enabled": True,
                    "url": webhook_url,
                    "secret": secret,
                    "resourceTypes": ["Comment"],
                    "allPublicTeams": True,
                },
            },
        )
        print(f"Created Linear webhook {label!r} -> {webhook_url}")

    upsert_env({"LINEAR_WEBHOOK_SECRET": secret, "LINEAR_PUBLIC_WEBHOOK_URL": webhook_url})
    return webhook_url


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stop", action="store_true", help="Stop background worker and tunnel")
    parser.add_argument("--status", action="store_true", help="Report current worker/tunnel status")
    parser.add_argument("--reuse", action="store_true", help="Reuse existing worker/tunnel instead of restarting")
    args = parser.parse_args()

    env = load_env()

    if args.stop:
        stop_pid(WORKER_PID)
        stop_pid(TUNNEL_PID)
        return

    if args.status:
        status(env)
        return

    if not args.reuse:
        stop_pid(WORKER_PID)
        stop_pid(TUNNEL_PID)
        time.sleep(0.5)

    if not env.get("LINEAR_WEBHOOK_SECRET"):
        env["LINEAR_WEBHOOK_SECRET"] = f"lin_wh_{secrets.token_urlsafe(32)}"
        upsert_env({"LINEAR_WEBHOOK_SECRET": env["LINEAR_WEBHOOK_SECRET"]})

    start_worker(env)
    public_url = start_tunnel(env)
    webhook_url = ensure_webhook(env, public_url)
    print("")
    print("Linear local agent stack is running.")
    print(f"Webhook URL: {webhook_url}")
    print(f"Trigger comments with: {env.get('LINEAR_TRIGGER_PHRASE', '@kettle')} <task>")
    print(f"Worker log: {WORKER_LOG}")
    print(f"Tunnel log: {TUNNEL_LOG}")


if __name__ == "__main__":
    main()
