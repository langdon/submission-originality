# submission-originality

Originality checker for hackathon submissions. Analyzes git repos and Devpost
submissions to help organizers identify pre-built code, GenAI usage patterns,
and off-track or rando submissions.

## Context

- Built for Civic Hacks 2026 (https://civic-hacks.com/); designed to be reusable
- GenAI usage by teams is **allowed and encouraged** — the goal is to surface
  signals, not penalize AI use
- Report audience is non-technical (judges, organizers), not engineers
- Event-specific data lives in `civic-hacks-2026/` (gitignored — never commit)

## Tech stack

Python 3.11+. Dependencies managed with `pip` / `requirements.txt` (or `pyproject.toml`
if the project grows). No framework required for MVP.

## Project layout

```
submission-originality/
├── src/                    # checker modules
├── tests/                  # pytest tests
├── civic-hacks-2026/       # gitignored — event data, inputs, outputs
├── CLAUDE.md
├── .gitignore
└── README.md
```

## Commands

```bash
# Install dependencies
pip install -r requirements.txt

# Run tests
pytest -q

# Run checker (once CLI exists)
python -m src.cli --config civic-hacks-2026/config.yml
```

## Key design constraints

- **Multi-host**: support GitHub and GitLab repo URLs; normalize to a common
  interface; don't crash on unknown hosts
- **Hackathon window**: always configurable (`start_datetime` + `end_datetime`
  with timezone); never hardcoded
- **Graceful degradation**: unreachable repos, missing API tokens, and failed
  Devpost fetches produce warnings and are skipped — not crashes
- **Descriptive output**: flags explain *why* something was flagged; no opaque scores
- **Privacy**: report must be easy to redact/anonymize before sharing publicly

## Worktree convention

Each issue gets its own git worktree. Never implement on `main` directly.

```bash
# Set up a worktree for issue #N
REPO=~/loc-projects/submission-originality
git -C "$REPO" worktree add "$REPO/wt/issue-N" -b feat/N-short-description

# Work in the worktree
cd "$REPO/wt/issue-N"

# Clean up after merge
git -C "$REPO" worktree remove wt/issue-N
```

Host path (for prompts): `~/loc-projects/submission-originality/wt/issue-N`

**Codex web**: creates a branch directly (no filesystem access) — worktree
not applicable. The build prompt handles this adaptively.

**Local agents / direct sessions**: use a worktree as above for isolation.

## Build Prompt Consumption (Task Mode)

When invoked like `implement #<N>` or `read CLAUDE.md and implement #<N>`:

1. Verify the issue is in THIS repo (`langdon/submission-originality`) and OPEN.
   If closed or missing, STOP and report.
2. Read issue body + latest build prompt:
   ```bash
   gh api repos/langdon/submission-originality/issues/<N> --jq '.body'
   gh api repos/langdon/submission-originality/issues/<N>/comments \
     --jq '[.[] | select(.body | startswith("## BUILD PROMPT"))] | last | .body'
   ```
3. If no `## BUILD PROMPT` comment exists, STOP and report.
4. Execute using the latest `## BUILD PROMPT` as the task contract.
5. Deliver: open a PR linked to the issue, post a summary comment with files
   changed + verification results.

## GitHub issue operations

Backlog is managed via GitHub issues on this repo. Allowed without confirmation:
create, edit, comment, label, close (with review). No force-push to main.

## Completion / blocked notification

```bash
# On completion:
tg-notify "Agent completed submission-originality#<N>: <summary>. PR: <url>" ambient 2>/dev/null || \
  curl -s -X POST "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
    -d "chat_id=${TELEGRAM_AMBIENT_CHAT_ID}&text=Agent+completed+submission-originality%23<N>:+<summary>" > /dev/null || true

# On blocker:
tg-notify "Agent blocked on submission-originality#<N>: <summary>" alerts 2>/dev/null || \
  curl -s -X POST "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
    -d "chat_id=${TELEGRAM_ALERTS_CHAT_ID}&text=Agent+blocked+on+submission-originality%23<N>:+<summary>" > /dev/null || true
```
