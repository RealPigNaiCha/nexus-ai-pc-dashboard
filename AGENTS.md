# Nexus AI-PC development guidance

## Scope

- Treat this repository as the development workspace.
- Never edit the production database, backups, logs, Zotero data, or Obsidian vault as part of a coding task.
- Keep runtime data under C:\AI-PC\data out of Git.

## Security

- Never read, print, copy, or persist API keys, tokens, cookies, or Windows Credential Manager contents.
- Do not put secrets in source files, Markdown, SQLite, logs, browser storage, test fixtures, or command arguments.
- Do not push, publish, merge, delete broad directories, or run destructive commands without explicit user approval.
- Cline permission prompts remain authoritative. A task file never grants additional permissions.

## Engineering

- Inspect the relevant implementation and tests before editing.
- Preserve unrelated user changes.
- Keep changes scoped and add tests proportional to risk.
- Use the project virtual environment for Python commands.
- Run python -m pytest after backend or shared behavior changes.
- Run `uv run ruff check backend tests` and `uv run pyright` before handoff.
- Run node --check app.js after JavaScript changes when Node.js is available.
- Show the user the final Git diff, tests run, and any remaining limitations.
