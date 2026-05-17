#!/usr/bin/env python3
"""Local Linear Agent webhook receiver for Kettle.

This script intentionally uses only the Python standard library so it can run
before the full subnet development environment is installed.
"""

from __future__ import annotations

from http.server import BaseHTTPRequestHandler
from http.server import ThreadingHTTPServer
import hashlib
import hmac
import json
import os
from pathlib import Path
import subprocess
import threading
import time
from typing import Any
from urllib import request as urllib_request


def _load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


_load_dotenv(Path.cwd() / ".env")

REPO_DIR = Path(os.getenv("KETTLE_REPO_DIR", Path.cwd())).resolve()
WEBHOOK_SECRET = os.getenv("LINEAR_WEBHOOK_SECRET", "")
LINEAR_ACCESS_TOKEN = os.getenv("LINEAR_ACCESS_TOKEN", "")
JOBS_DIR = REPO_DIR / ".linear-agent" / "jobs"
RUNNER = REPO_DIR / "scripts" / "run_linear_gsd_task.sh"
MAX_SKEW_MS = 60_000


def _json_response(handler: BaseHTTPRequestHandler, status: int, payload: dict[str, Any]) -> None:
    body = json.dumps(payload).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def _verify_signature(signature: str | None, raw_body: bytes) -> tuple[bool, str]:
    if not WEBHOOK_SECRET:
        return False, "LINEAR_WEBHOOK_SECRET is not configured"
    if not signature:
        return False, "missing Linear-Signature"

    expected = hmac.new(WEBHOOK_SECRET.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, signature):
        return False, "invalid Linear-Signature"
    return True, ""


def _verify_timestamp(payload: dict[str, Any]) -> tuple[bool, str]:
    timestamp = payload.get("webhookTimestamp")
    if not isinstance(timestamp, int):
        return False, "missing webhookTimestamp"
    if abs(int(time.time() * 1000) - timestamp) > MAX_SKEW_MS:
        return False, "stale webhook"
    return True, ""


def _graphql(query: str, variables: dict[str, Any]) -> dict[str, Any] | None:
    if not LINEAR_ACCESS_TOKEN:
        return None

    body = json.dumps({"query": query, "variables": variables}).encode("utf-8")
    req = urllib_request.Request(
        "https://api.linear.app/graphql",
        data=body,
        headers={
            "Authorization": f"Bearer {LINEAR_ACCESS_TOKEN}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib_request.urlopen(req, timeout=15) as response:  # noqa: S310 - fixed Linear API URL
        return json.loads(response.read().decode("utf-8"))


def _emit_activity(agent_session_id: str | None, content: dict[str, Any]) -> None:
    if not agent_session_id:
        return
    mutation = """
    mutation AgentActivityCreate($input: AgentActivityCreateInput!) {
      agentActivityCreate(input: $input) {
        success
      }
    }
    """
    try:
        _graphql(mutation, {"input": {"agentSessionId": agent_session_id, "content": content}})
    except Exception as exc:  # pragma: no cover - best-effort Linear status update
        print(f"WARNING: failed to emit Linear activity: {exc}", flush=True)


def _agent_session(payload: dict[str, Any]) -> dict[str, Any]:
    return payload.get("agentSession") or payload.get("data", {}).get("agentSession") or {}


def _issue_from_session(session: dict[str, Any]) -> dict[str, Any]:
    return session.get("issue") or {}


def _job_paths(delivery_id: str) -> tuple[Path, Path]:
    JOBS_DIR.mkdir(parents=True, exist_ok=True)
    payload_path = JOBS_DIR / f"{delivery_id}.json"
    prompt_path = JOBS_DIR / f"{delivery_id}.prompt.txt"
    return payload_path, prompt_path


def _status_file(delivery_id: str) -> Path:
    return JOBS_DIR / f"{delivery_id}.status.json"


def _write_status(delivery_id: str, status: str, **extra: Any) -> None:
    _status_file(delivery_id).write_text(
        json.dumps({"status": status, "updatedAt": int(time.time()), **extra}, indent=2),
        encoding="utf-8",
    )


def _run_job(delivery_id: str, payload: dict[str, Any], prompt_path: Path) -> None:
    session = _agent_session(payload)
    issue = _issue_from_session(session)
    agent_session_id = session.get("id")
    issue_id = issue.get("identifier") or issue.get("id") or delivery_id
    issue_title = issue.get("title") or "Linear issue"
    issue_url = issue.get("url") or payload.get("url") or ""

    _emit_activity(
        agent_session_id,
        {"type": "action", "action": "Starting local Codex", "parameter": str(issue_id)},
    )
    _write_status(delivery_id, "running", issue=issue_id)

    env = os.environ.copy()
    env.update(
        {
            "LINEAR_ISSUE_ID": str(issue_id),
            "LINEAR_ISSUE_TITLE": str(issue_title),
            "LINEAR_ISSUE_URL": str(issue_url),
            "LINEAR_PROMPT_CONTEXT_PATH": str(prompt_path),
        }
    )

    try:
        completed = subprocess.run(
            [str(RUNNER)],
            cwd=REPO_DIR,
            env=env,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=int(os.getenv("LINEAR_JOB_TIMEOUT_SECONDS", "7200")),
            check=False,
        )
    except Exception as exc:
        _write_status(delivery_id, "error", error=str(exc))
        _emit_activity(agent_session_id, {"type": "error", "body": f"Local runner failed: `{exc}`"})
        return

    output_path = JOBS_DIR / f"{delivery_id}.log"
    output_path.write_text(completed.stdout, encoding="utf-8")

    if completed.returncode == 0:
        _write_status(delivery_id, "complete", log=str(output_path))
        _emit_activity(
            agent_session_id,
            {
                "type": "response",
                "body": f"Local Codex/GSD run completed for `{issue_id}`. Log: `{output_path}`",
            },
        )
    else:
        _write_status(delivery_id, "error", returncode=completed.returncode, log=str(output_path))
        _emit_activity(
            agent_session_id,
            {
                "type": "error",
                "body": f"Local Codex/GSD run failed for `{issue_id}` with exit {completed.returncode}. Log: `{output_path}`",
            },
        )


class LinearAgentHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        if self.path == "/healthz":
            _json_response(self, 200, {"status": "ok"})
            return
        _json_response(self, 404, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        if self.path != "/webhooks/linear":
            _json_response(self, 404, {"error": "not found"})
            return

        length = int(self.headers.get("content-length", "0"))
        raw_body = self.rfile.read(length)

        ok, reason = _verify_signature(self.headers.get("linear-signature"), raw_body)
        if not ok:
            _json_response(self, 401 if "SECRET" not in reason else 500, {"error": reason})
            return

        try:
            payload = json.loads(raw_body)
        except json.JSONDecodeError:
            _json_response(self, 400, {"error": "invalid JSON"})
            return

        ok, reason = _verify_timestamp(payload)
        if not ok:
            _json_response(self, 401, {"error": reason})
            return

        delivery_id = self.headers.get("linear-delivery") or f"manual-{int(time.time() * 1000)}"
        payload_path, prompt_path = _job_paths(delivery_id)
        if payload_path.exists():
            _json_response(self, 200, {"status": "duplicate", "deliveryId": delivery_id})
            return

        payload_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        session = _agent_session(payload)
        prompt_context = session.get("promptContext") or payload.get("promptContext") or ""
        prompt_path.write_text(str(prompt_context), encoding="utf-8")

        agent_session_id = session.get("id")
        _emit_activity(agent_session_id, {"type": "thought", "body": "Accepted. Starting local Codex/GSD run."})
        _write_status(delivery_id, "queued")

        thread = threading.Thread(target=_run_job, args=(delivery_id, payload, prompt_path), daemon=True)
        thread.start()
        _json_response(self, 200, {"status": "queued", "deliveryId": delivery_id})

    def log_message(self, format: str, *args: Any) -> None:
        print(f"{self.address_string()} - {format % args}", flush=True)


def main() -> None:
    port = int(os.getenv("LINEAR_AGENT_PORT", "8787"))
    server = ThreadingHTTPServer(("127.0.0.1", port), LinearAgentHandler)
    print(f"Kettle Linear Agent webhook listening on http://127.0.0.1:{port}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
