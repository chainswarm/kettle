#!/usr/bin/env python3
"""Sync Kettle GSD planning structure to Linear."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
from typing import Any
from urllib import request as urllib_request


ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = ROOT / ".env"
ROADMAP_PATH = ROOT / ".planning" / "ROADMAP.md"
PROJECT_PATH = ROOT / ".planning" / "PROJECT.md"
REQUIREMENTS_PATH = ROOT / ".planning" / "REQUIREMENTS.md"
STATE_PATH = ROOT / ".planning" / "STATE.md"
TODO_DIR = ROOT / ".planning" / "todos" / "pending"
MAP_PATH = ROOT / ".planning" / "integrations" / "linear-map.json"
PLANNING_DOCUMENTS = (
    ("project", PROJECT_PATH, "Project Brief"),
    ("roadmap", ROADMAP_PATH, "Roadmap"),
    ("requirements", REQUIREMENTS_PATH, "Requirements"),
    ("state", STATE_PATH, "Current State"),
)


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


def graphql(env: dict[str, str], query: str, variables: dict[str, Any] | None = None) -> dict[str, Any]:
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
    with urllib_request.urlopen(req, timeout=30) as response:  # noqa: S310 - fixed Linear API URL
        payload = json.loads(response.read().decode("utf-8"))
    if payload.get("errors"):
        raise RuntimeError("; ".join(error.get("message", str(error)) for error in payload["errors"]))
    return payload["data"]


def read_map() -> dict[str, Any]:
    if MAP_PATH.exists():
        return json.loads(MAP_PATH.read_text(encoding="utf-8"))
    return {"version": 1, "linear": {}, "gsd": {"milestones": {}, "phases": {}, "todos": {}}}


def write_map(mapping: dict[str, Any]) -> None:
    MAP_PATH.parent.mkdir(parents=True, exist_ok=True)
    MAP_PATH.write_text(json.dumps(mapping, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def project_name() -> str:
    if PROJECT_PATH.exists():
        text = PROJECT_PATH.read_text(encoding="utf-8")
        heading = re.search(r"^#\s+(.+)$", text, re.MULTILINE)
        if heading:
            name = heading.group(1).replace("Project:", "").strip()
            if name and "template" not in name.lower():
                return name
    return os.getenv("LINEAR_PROJECT_NAME", "Kettle")


def current_milestone() -> tuple[str, str]:
    text = ROADMAP_PATH.read_text(encoding="utf-8") if ROADMAP_PATH.exists() else ""
    match = re.search(r"\*\*Milestone:\*\*\s*([^\n]+)", text)
    if match:
        raw = match.group(1).strip()
        version_match = re.search(r"(v\d+(?:\.\d+)*)", raw)
        version = version_match.group(1) if version_match else raw.split()[0]
        return version, raw
    return "v0.1", "v0.1 — Initial Kettle setup"


def parse_phases() -> list[dict[str, str]]:
    text = ROADMAP_PATH.read_text(encoding="utf-8") if ROADMAP_PATH.exists() else ""
    phases: list[dict[str, str]] = []
    pattern = re.compile(r"^### Phase\s+([0-9.]+):\s+(.+?)\n(.*?)(?=^### Phase\s+|\Z)", re.MULTILINE | re.DOTALL)
    for match in pattern.finditer(text):
        num = match.group(1).strip()
        name = match.group(2).strip()
        body = match.group(3).strip()
        goal_match = re.search(r"\*\*Goal:\*\*\s*(.+)", body)
        status = "Done" if re.search(r"- \[x\]\s+Complete", body) else "Todo"
        phases.append(
            {
                "number": num,
                "name": name,
                "goal": goal_match.group(1).strip() if goal_match else "",
                "body": body[:4000],
                "status": status,
            }
        )
    return phases


def parse_pending_todos() -> list[dict[str, str]]:
    todos: list[dict[str, str]] = []
    if not TODO_DIR.exists():
        return todos
    for path in sorted(TODO_DIR.glob("*.md")):
        text = path.read_text(encoding="utf-8")
        heading = re.search(r"^#\s+(.+)$", text, re.MULTILINE)
        title = heading.group(1).strip() if heading else path.stem.replace("-", " ")
        todos.append({"key": str(path.relative_to(ROOT)), "title": title, "body": text[:4000]})
    return todos


def planning_documents(project: str) -> list[dict[str, str]]:
    docs: list[dict[str, str]] = []
    for key, path, label in PLANNING_DOCUMENTS:
        if not path.exists():
            continue
        content = path.read_text(encoding="utf-8").strip()
        if not content:
            continue
        docs.append(
            {
                "key": key,
                "title": f"{project} — {label}",
                "source": str(path.relative_to(ROOT)),
                "content": content[:60000],
            }
        )
    return docs


def get_team(env: dict[str, str]) -> dict[str, Any]:
    preferred = env.get("LINEAR_TEAM_KEY") or "AFL"
    data = graphql(env, "query { teams(first: 50) { nodes { id key name states { nodes { id name type } } } } }")
    teams = data["teams"]["nodes"]
    team = next((item for item in teams if item["key"] == preferred), None) or teams[0]
    states = {state["type"]: state for state in team["states"]["nodes"]}
    return {"id": team["id"], "key": team["key"], "name": team["name"], "states": states}


def ensure_project(env: dict[str, str], mapping: dict[str, Any], team_id: str, name: str) -> str:
    project_id = mapping.get("linear", {}).get("projectId")
    description = f"Synced from Kettle GSD planning.\n\nSource: `.planning/PROJECT.md`, `.planning/ROADMAP.md`"
    if project_id:
        mutation = "mutation($id:String!,$input:ProjectUpdateInput!){ projectUpdate(id:$id,input:$input){ success project { id name } } }"
        graphql(env, mutation, {"id": project_id, "input": {"name": name, "description": description, "teamIds": [team_id]}})
        print(f"Updated Linear project: {name}")
        return project_id

    data = graphql(env, "query($name:String!){ projects(filter:{name:{eq:$name}}, first:5){nodes{id name}} }", {"name": name})
    existing = data["projects"]["nodes"][0] if data["projects"]["nodes"] else None
    if existing:
        project_id = existing["id"]
        print(f"Reusing Linear project: {name}")
    else:
        mutation = "mutation($input:ProjectCreateInput!){ projectCreate(input:$input){ success project { id name } } }"
        result = graphql(env, mutation, {"input": {"name": name, "description": description, "teamIds": [team_id]}})
        project_id = result["projectCreate"]["project"]["id"]
        print(f"Created Linear project: {name}")
    mapping.setdefault("linear", {})["projectId"] = project_id
    return project_id


def ensure_milestone(env: dict[str, str], mapping: dict[str, Any], project_id: str, version: str, name: str) -> str:
    milestones = mapping.setdefault("gsd", {}).setdefault("milestones", {})
    if version in milestones:
        milestone_id = milestones[version]["linearMilestoneId"]
        mutation = "mutation($id:String!,$input:ProjectMilestoneUpdateInput!){ projectMilestoneUpdate(id:$id,input:$input){ success projectMilestone { id name } } }"
        graphql(env, mutation, {"id": milestone_id, "input": {"name": name, "description": f"GSD milestone `{version}`"}})
        print(f"Updated Linear milestone: {name}")
        return milestone_id
    mutation = "mutation($input:ProjectMilestoneCreateInput!){ projectMilestoneCreate(input:$input){ success projectMilestone { id name } } }"
    result = graphql(
        env,
        mutation,
        {"input": {"name": name, "description": f"GSD milestone `{version}`", "projectId": project_id}},
    )
    milestone_id = result["projectMilestoneCreate"]["projectMilestone"]["id"]
    milestones[version] = {"linearMilestoneId": milestone_id, "name": name}
    print(f"Created Linear milestone: {name}")
    return milestone_id


def phase_checklist(phases: list[dict[str, str]]) -> str:
    lines = ["## GSD Phase Order", ""]
    for phase in phases:
        box = "x" if phase["status"] == "Done" else " "
        goal = f" — {phase['goal']}" if phase["goal"] else ""
        lines.append(f"- [{box}] Phase {phase['number']}: {phase['name']}{goal}")
    lines.extend(
        [
            "",
            "## Source",
            "",
            "- `.planning/ROADMAP.md`",
            "- `.planning/STATE.md`",
            "",
            "GSD owns execution order, plans, verification, and decisions. Linear is the coordination view.",
        ]
    )
    return "\n".join(lines)


def ensure_issue(
    env: dict[str, str],
    mapping_bucket: dict[str, Any],
    key: str,
    title: str,
    description: str,
    team_id: str,
    state_id: str,
    project_id: str,
    milestone_id: str | None,
) -> str:
    issue_id = mapping_bucket.get(key, {}).get("linearIssueId")
    input_data = {
        "title": title,
        "description": description,
        "teamId": team_id,
        "stateId": state_id,
        "projectId": project_id,
    }
    if milestone_id:
        input_data["projectMilestoneId"] = milestone_id
    if issue_id:
        mutation = "mutation($id:String!,$input:IssueUpdateInput!){ issueUpdate(id:$id,input:$input){ success issue { id identifier title } } }"
        graphql(env, mutation, {"id": issue_id, "input": input_data})
        print(f"Updated Linear issue: {title}")
        return issue_id
    mutation = "mutation($input:IssueCreateInput!){ issueCreate(input:$input){ success issue { id identifier title } } }"
    result = graphql(env, mutation, {"input": input_data})
    issue = result["issueCreate"]["issue"]
    mapping_bucket[key] = {"linearIssueId": issue["id"], "identifier": issue["identifier"], "title": title}
    print(f"Created Linear issue: {issue['identifier']} {title}")
    return issue["id"]


def ensure_milestone_issue(
    env: dict[str, str],
    mapping: dict[str, Any],
    version: str,
    title: str,
    description: str,
    team_id: str,
    state_id: str,
    project_id: str,
    milestone_id: str,
) -> str:
    milestones = mapping.setdefault("gsd", {}).setdefault("milestones", {})
    milestone_entry = milestones.setdefault(version, {"name": title, "linearMilestoneId": milestone_id})
    issue_id = milestone_entry.get("linearIssueId")
    issue_title = f"Milestone {title}"
    input_data = {
        "title": issue_title,
        "description": description,
        "teamId": team_id,
        "stateId": state_id,
        "projectId": project_id,
        "projectMilestoneId": milestone_id,
    }
    if issue_id:
        mutation = "mutation($id:String!,$input:IssueUpdateInput!){ issueUpdate(id:$id,input:$input){ success issue { id identifier title } } }"
        graphql(env, mutation, {"id": issue_id, "input": input_data})
        print(f"Updated Linear milestone issue: Milestone {title}")
        return issue_id
    existing = graphql(
        env,
        """
        query($teamId:ID!,$title:String!){
          issues(filter:{team:{id:{eq:$teamId}}, title:{eq:$title}}, first:5){
            nodes { id identifier title }
          }
        }
        """,
        {"teamId": team_id, "title": issue_title},
    )["issues"]["nodes"]
    if existing:
        issue = existing[0]
        mutation = "mutation($id:String!,$input:IssueUpdateInput!){ issueUpdate(id:$id,input:$input){ success issue { id identifier title } } }"
        graphql(env, mutation, {"id": issue["id"], "input": input_data})
        milestone_entry.update({"linearIssueId": issue["id"], "identifier": issue["identifier"], "name": title})
        print(f"Reused Linear milestone issue: {issue['identifier']} Milestone {title}")
        return issue["id"]
    mutation = "mutation($input:IssueCreateInput!){ issueCreate(input:$input){ success issue { id identifier title } } }"
    result = graphql(env, mutation, {"input": input_data})
    issue = result["issueCreate"]["issue"]
    milestone_entry.update({"linearIssueId": issue["id"], "identifier": issue["identifier"], "name": title})
    print(f"Created Linear milestone issue: {issue['identifier']} Milestone {title}")
    return issue["id"]


def document_content(doc: dict[str, str]) -> str:
    return (
        f"Synced from `{doc['source']}`.\n\n"
        "GSD owns this document. Edit the source file locally, then run `$linear-plan-sync`.\n\n"
        f"{doc['content']}"
    )


def ensure_document(
    env: dict[str, str],
    mapping: dict[str, Any],
    key: str,
    title: str,
    content: str,
    project_id: str,
) -> str:
    documents = mapping.setdefault("gsd", {}).setdefault("documents", {})
    document_id = documents.get(key, {}).get("linearDocumentId")
    input_data = {"title": title, "content": content, "projectId": project_id}
    if document_id:
        mutation = "mutation($id:String!,$input:DocumentUpdateInput!){ documentUpdate(id:$id,input:$input){ success document { id title } } }"
        graphql(env, mutation, {"id": document_id, "input": input_data})
        print(f"Updated Linear document: {title}")
        return document_id
    mutation = "mutation($input:DocumentCreateInput!){ documentCreate(input:$input){ success document { id title } } }"
    result = graphql(env, mutation, {"input": input_data})
    document = result["documentCreate"]["document"]
    documents[key] = {"linearDocumentId": document["id"], "title": title}
    print(f"Created Linear document: {title}")
    return document["id"]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Parse and print intended sync without writing Linear")
    args = parser.parse_args()

    env = load_env()
    mapping = read_map()
    team = get_team(env)
    todo_state = team["states"].get("unstarted") or next(iter(team["states"].values()))
    done_state = team["states"].get("completed") or todo_state
    backlog_state = team["states"].get("backlog") or todo_state

    name = project_name()
    version, milestone_name = current_milestone()
    phases = parse_phases()
    todos = parse_pending_todos()
    docs = planning_documents(name)

    if args.dry_run:
        print(
            json.dumps(
                {
                    "project": name,
                    "milestone": milestone_name,
                    "phases": phases,
                    "todos": todos,
                    "documents": [{"key": doc["key"], "title": doc["title"], "source": doc["source"]} for doc in docs],
                },
                indent=2,
            )
        )
        return

    project_id = ensure_project(env, mapping, team["id"], name)
    milestone_id = ensure_milestone(env, mapping, project_id, version, milestone_name)
    todo_bucket = mapping.setdefault("gsd", {}).setdefault("todos", {})

    all_phases_done = bool(phases) and all(phase["status"] == "Done" for phase in phases)
    ensure_milestone_issue(
        env,
        mapping,
        version,
        milestone_name,
        phase_checklist(phases),
        team["id"],
        done_state["id"] if all_phases_done else todo_state["id"],
        project_id,
        milestone_id,
    )

    for todo in todos:
        ensure_issue(
            env,
            todo_bucket,
            todo["key"],
            todo["title"],
            f"Synced from `{todo['key']}`.\n\n```markdown\n{todo['body']}\n```",
            team["id"],
            backlog_state["id"],
            project_id,
            milestone_id,
        )

    for doc in docs:
        ensure_document(env, mapping, doc["key"], doc["title"], document_content(doc), project_id)

    write_map(mapping)
    print(f"Wrote {MAP_PATH}")


if __name__ == "__main__":
    main()
