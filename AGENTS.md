# Project guide for AI coding agents

Shared by GitHub Copilot, Claude Code and other agents. Keep this file short and
current: every line is loaded each session and costs context.

## Project
WSNE hiring stack for WSNE Consulting. Everything is free, open-source software
that runs locally via Docker Compose.
- `hub/`: the Hiring Hub (Python, FastAPI, Jinja2 templates, SQLAlchemy, Postgres
  in Docker / SQLite in tests). Resume parsing, per-role scoring, typing/written/
  voice assessment, role line-up.
- `hub/roles/*.yaml`: one scorecard per role (weights, minimums, knockout rules).
- `docker-compose.yml`: hub plus OpenCATS (ATS), Cal.com, Metabase, Chatwoot.
- `./wsne`: shell wrapper for the stack. `inbox/`: drop-folder for resumes.
- `data/` and `vendor/`: runtime data and third-party code. Do not edit.

## Commands
- First run: `./wsne setup` (or `./wsne setup core` for the hub only)
- Start / stop: `./wsne up [parts]` / `./wsne down`
- Status / logs: `./wsne status`, `./wsne logs hub`
- Tests: `./wsne test` (runs pytest in Docker against `hub/tests`)
- Parts: `core`, `ats`, `calendar`, `inbox`, `reports`
- Needs Docker Desktop running.

## Conventions
- Prefer small, focused changes. One concern per commit.
- Match the style of surrounding code. Do not reformat unrelated files.
- Add or update tests in `hub/tests/` with every behaviour change.
- Scoring numbers live in `hub/roles/*.yaml`, not in code. Change the YAML.
- Missing candidate information must never reject anyone; it is "not checked".

## Safety rules
- Never read, print, edit or commit `.env`. It holds real secrets. `.env.example`
  documents the variables.
- `data/` holds candidate personal data. Never commit it or paste it into chats.
- Do not add automated access to Naukri; its terms prohibit it.

## Working agreements for agents
- Read the relevant files before editing; do not guess APIs.
- Ask before adding dependencies, deleting files or changing project structure.
- Keep answers brief. Show diffs or file paths rather than pasting whole files.
- When you learn a durable fact (a command, a decision, a gotcha), add one line
  to the right section above instead of leaving it only in chat.

## Decisions log
- Format: `YYYY-MM-DD: decision, reason`.
- 2026-11-26: Free-only tooling (Copilot Free, open-source memory tools), no paid plans.
