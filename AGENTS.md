# Project guide for AI coding agents

Shared by GitHub Copilot, Claude Code and other agents. Keep this file short and
current: every line is loaded each session and costs context.

## Project
- Name: wsne. Early stage; the README only says "ats" (possibly an applicant
  tracking system). Update this section once the purpose and stack are decided.
- Stack: TBD. Record language, framework, package manager and test runner here.

## Commands
- Install: TBD
- Test: TBD
- Lint/format: TBD
- Run: TBD

## Conventions
- Prefer small, focused changes. One concern per commit.
- Match the style of surrounding code. Do not reformat unrelated files.
- Add or update tests with every behaviour change.
- Never commit secrets, `.env` files or credentials.

## Working agreements for agents
- Read the relevant files before editing; do not guess APIs.
- Ask before adding dependencies, deleting files or changing project structure.
- Keep answers brief. Show diffs or file paths rather than pasting whole files.
- When you learn a durable fact (a command, a decision, a gotcha), add one line
  to the right section above instead of leaving it only in chat.

## Decisions log
- (none yet) Format: `YYYY-MM-DD: decision, reason`.
