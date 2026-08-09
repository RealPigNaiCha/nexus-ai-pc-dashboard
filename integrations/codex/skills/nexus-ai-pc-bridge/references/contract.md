# Bridge contract v1

The Dashboard returns `schema=nexus.task-envelope`, `version=1`, a stable `task_id`, a `revision`, and `content_sha256`. The hash covers the task, constraints, context descriptor, endpoints, and earlier results.

Use this result JSON shape with `task-report`:

```json
{
  "status": "completed",
  "summary": "Implemented the requested change and verified it.",
  "citations": [
    {
      "kind": "library",
      "resource_id": "document:7",
      "title": "Source title",
      "source_path": "C:\\AI-PC\\data\\library\\source.pdf",
      "page": 12,
      "note": "Supports the selected approach"
    }
  ],
  "artifacts": [
    {
      "path": "C:\\AI-PC\\workspaces\\project\\output.md",
      "kind": "document",
      "sha256": "optional lowercase SHA-256"
    }
  ],
  "tests": [
    {
      "command": "uv run pytest",
      "status": "passed",
      "summary": "All tests passed"
    }
  ],
  "questions": [],
  "executor": "codex-cli",
  "source_commit": "optional Git commit hash"
}
```

Allowed result states are `completed`, `partial`, and `blocked`. Citation kinds are `library`, `research`, `web`, and `file`. Test states are `passed`, `failed`, and `not_run`.

The CLI adds `envelope_sha256`; do not hard-code it in the file. The server rejects stale hashes with HTTP 409 and records successful reports in the audit log.
