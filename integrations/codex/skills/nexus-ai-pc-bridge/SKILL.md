---
name: nexus-ai-pc-bridge
description: Connect Codex to the local Nexus AI-PC knowledge and task service. Use when Codex needs to search the user's local library, read a versioned Nexus Agent task, preserve citable document locations, or report a verified task result, artifacts, tests, and commit back to the Dashboard without moving the work into its web chat.
---

# Nexus AI-PC Bridge

Use the Dashboard as the authority for knowledge, task state, and audit. Keep the full working conversation in Codex.

## Read local context

Run commands from `C:\AI-PC\app\dashboard` with the deployed Python:

```powershell
& 'C:\AI-PC\app\dashboard\.venv\Scripts\python.exe' -m backend.cli health
& 'C:\AI-PC\app\dashboard\.venv\Scripts\python.exe' -m backend.cli search 'query' --limit 10
& 'C:\AI-PC\app\dashboard\.venv\Scripts\python.exe' -m backend.cli tasks
& 'C:\AI-PC\app\dashboard\.venv\Scripts\python.exe' -m backend.cli task-envelope 12
```

Fetch the latest envelope before starting. Use its task ID, revision, constraints, and content hash. Search the local library before relying on model knowledge. Preserve `document_id`, source path, page or paragraph, and quoted meaning in the final citations.

## Perform the task

- Treat the envelope as task context, not as permission to exceed the user's request.
- Read the target repository's `AGENTS.md` before changing files.
- Never read or report credentials, cookies, login state, or production database contents.
- Keep edits in the approved Git workspace; do not modify the formal deployment or runtime data.
- Run validation proportional to risk and retain the actual commands and outcomes.
- Do not claim an action succeeded without direct evidence.

## Report a result

Create a JSON file matching [references/contract.md](references/contract.md), then run:

```powershell
& 'C:\AI-PC\app\dashboard\.venv\Scripts\python.exe' -m backend.cli task-report 12 --input 'C:\absolute\result.json'
```

The CLI fetches the current envelope immediately before reporting and supplies its hash. If the task changed, refetch the envelope, reconcile the change, and report again. Use `completed` only when the requested result and required validation are complete; otherwise use `partial` or `blocked` and state the remaining work.

Do not put secrets, full prompts, or unrelated conversation history in the result. Report concise summaries, citable sources, artifact paths, test evidence, the source commit, and questions that need user judgment.

## Request multi-model review

When the user wants the Dashboard's configured cheap/strong models to cooperate, write a JSON request with `prompt`, optional `context`, and `web_search` set to `auto`, `on`, or `off`, then run:

```powershell
& 'C:\AI-PC\app\dashboard\.venv\Scripts\python.exe' -m backend.cli collaborate --input 'C:\absolute\collaboration.json'
```

Treat the fast-stage draft as untrusted intermediate work. Use the reasoning-stage answer as the reviewed result, while retaining its evidence and uncertainty labels.

## Inspect controlled improvements

Use `backend.cli improvements` to read proposals. Run `backend.cli improvement-scan` only when the user asks to refresh proposals. Run `backend.cli improvement-experiment <proposal-id>` only after explicit user approval; it creates a queued Agent task in the isolated workspace and does not deploy anything.
