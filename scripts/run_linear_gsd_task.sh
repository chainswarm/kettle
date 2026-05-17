#!/usr/bin/env bash
set -euo pipefail

if ! command -v codex >/dev/null 2>&1; then
  echo "ERROR: codex CLI is not installed or not in PATH." >&2
  exit 1
fi

if ! command -v gsd-sdk >/dev/null 2>&1; then
  echo "ERROR: gsd-sdk is not installed or not in PATH." >&2
  exit 1
fi

REPO_DIR="${KETTLE_REPO_DIR:-$(git rev-parse --show-toplevel)}"
ISSUE_ID="${LINEAR_ISSUE_ID:?Set LINEAR_ISSUE_ID, for example KET-123.}"
ISSUE_TITLE="${LINEAR_ISSUE_TITLE:-Linear issue}"
ISSUE_URL="${LINEAR_ISSUE_URL:-}"
PROMPT_CONTEXT_PATH="${LINEAR_PROMPT_CONTEXT_PATH:-}"
GSD_MODE="${LINEAR_GSD_MODE:-quick}"
BASE_BRANCH="${LINEAR_BASE_BRANCH:-main}"
CODEX_MODEL="${LINEAR_CODEX_MODEL:-}"

cd "$REPO_DIR"

if [ -n "$(git status --porcelain)" ] && [ "${LINEAR_ALLOW_DIRTY:-false}" != "true" ]; then
  echo "ERROR: working tree is dirty. Commit/stash first or set LINEAR_ALLOW_DIRTY=true." >&2
  git status --short >&2
  exit 1
fi

slug="$(printf '%s' "$ISSUE_TITLE" \
  | tr '[:upper:]' '[:lower:]' \
  | sed 's/[^a-z0-9]/-/g; s/-\+/-/g; s/^-//; s/-$//' \
  | cut -c1-48)"
slug="${slug:-task}"
BRANCH_NAME="${LINEAR_BRANCH_NAME:-linear/${ISSUE_ID}-${slug}}"

git fetch --quiet origin "$BASE_BRANCH" || true
if git show-ref --verify --quiet "refs/heads/$BRANCH_NAME"; then
  git switch "$BRANCH_NAME"
else
  git switch -c "$BRANCH_NAME" "origin/$BASE_BRANCH"
fi

prompt_context=""
if [ -n "$PROMPT_CONTEXT_PATH" ] && [ -f "$PROMPT_CONTEXT_PATH" ]; then
  prompt_context="$(cat "$PROMPT_CONTEXT_PATH")"
fi

case "$GSD_MODE" in
  fast)
    gsd_command="\$gsd-fast"
    ;;
  phase)
    gsd_command="\$gsd-phase"
    ;;
  review)
    gsd_command="\$gsd-code-review"
    ;;
  ship)
    gsd_command="\$gsd-ship"
    ;;
  quick|*)
    gsd_command="\$gsd-quick --validate"
    ;;
esac

prompt=$(cat <<EOF
${gsd_command}

Linear issue: ${ISSUE_ID}
Title: ${ISSUE_TITLE}
URL: ${ISSUE_URL}

Use the Linear context below as the task requirements. Keep work scoped to this
issue. Use the repo-local Hypertensor subnet skill when touching subnet behavior
or docs. Commit atomically and report tests run.

<linear_prompt_context>
${prompt_context}
</linear_prompt_context>
EOF
)

codex_args=(exec -C "$REPO_DIR" --sandbox workspace-write --ask-for-approval never)
if [ -n "$CODEX_MODEL" ]; then
  codex_args+=(--model "$CODEX_MODEL")
fi

codex "${codex_args[@]}" "$prompt"
