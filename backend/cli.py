from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Sequence

import httpx


DEFAULT_URL = "http://127.0.0.1:8765"


class NexusClient:
    def __init__(
        self,
        base_url: str = DEFAULT_URL,
        *,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._client = httpx.Client(
            base_url=base_url.rstrip("/"),
            timeout=20.0,
            follow_redirects=False,
            transport=transport,
        )

    def close(self) -> None:
        self._client.close()

    def _json(self, response: httpx.Response) -> Any:
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as error:
            detail = ""
            try:
                detail = str(error.response.json().get("detail") or "")
            except (ValueError, AttributeError):
                pass
            raise RuntimeError(detail or f"Dashboard returned HTTP {error.response.status_code}") from None
        return response.json()

    def health(self) -> dict[str, object]:
        return self._json(self._client.get("/api/health"))

    def search(self, query: str, limit: int = 10) -> list[dict[str, object]]:
        return self._json(self._client.get("/api/library/search", params={"q": query, "limit": limit}))

    def tasks(self) -> list[dict[str, object]]:
        return self._json(self._client.get("/api/agent/tasks"))

    def task_envelope(self, task_id: int) -> dict[str, object]:
        return self._json(self._client.get(f"/api/bridge/tasks/{task_id}/envelope"))

    def report_task(self, task_id: int, payload: dict[str, object]) -> dict[str, object]:
        envelope = self.task_envelope(task_id)
        body = dict(payload)
        body["envelope_sha256"] = envelope["content_sha256"]
        return self._json(
            self._client.post(
                f"/api/bridge/tasks/{task_id}/results",
                json=body,
                headers={"X-AI-PC-Action": "bridge-result"},
            )
        )

    def collaborate(self, payload: dict[str, object]) -> dict[str, object]:
        return self._json(self._client.post("/api/collaboration/run", json=payload))

    def improvements(self) -> dict[str, object]:
        return self._json(self._client.get("/api/improvements/proposals"))

    def improvement_scan(self) -> dict[str, object]:
        return self._json(
            self._client.post("/api/improvements/scan", headers={"X-AI-PC-Action": "improvement-scan"})
        )

    def improvement_experiment(self, proposal_id: int) -> dict[str, object]:
        return self._json(
            self._client.post(
                f"/api/improvements/proposals/{proposal_id}/experiment",
                headers={"X-AI-PC-Action": "improvement-experiment"},
            )
        )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="nexus", description="Nexus AI-PC local bridge CLI")
    parser.add_argument("--base-url", default=os.getenv("AI_PC_DASHBOARD_URL", DEFAULT_URL))
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("health")
    search = commands.add_parser("search")
    search.add_argument("query")
    search.add_argument("--limit", type=int, default=10, choices=range(1, 21), metavar="1..20")
    commands.add_parser("tasks")
    envelope = commands.add_parser("task-envelope")
    envelope.add_argument("task_id", type=int)
    report = commands.add_parser("task-report")
    report.add_argument("task_id", type=int)
    report.add_argument("--input", required=True, type=Path)
    collaborate = commands.add_parser("collaborate")
    collaborate.add_argument("--input", required=True, type=Path)
    commands.add_parser("improvements")
    commands.add_parser("improvement-scan")
    experiment = commands.add_parser("improvement-experiment")
    experiment.add_argument("proposal_id", type=int)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    client = NexusClient(args.base_url)
    try:
        if args.command == "health":
            payload = client.health()
        elif args.command == "search":
            payload = client.search(args.query, args.limit)
        elif args.command == "tasks":
            payload = client.tasks()
        elif args.command == "task-envelope":
            payload = client.task_envelope(args.task_id)
        elif args.command == "task-report":
            try:
                report = json.loads(args.input.read_text(encoding="utf-8"))
            except (OSError, ValueError) as error:
                raise RuntimeError("Result input must be a readable JSON object") from error
            if not isinstance(report, dict):
                raise RuntimeError("Result input must be a JSON object")
            payload = client.report_task(args.task_id, report)
        elif args.command == "collaborate":
            try:
                collaboration = json.loads(args.input.read_text(encoding="utf-8"))
            except (OSError, ValueError) as error:
                raise RuntimeError("Collaboration input must be a readable JSON object") from error
            if not isinstance(collaboration, dict):
                raise RuntimeError("Collaboration input must be a JSON object")
            payload = client.collaborate(collaboration)
        elif args.command == "improvements":
            payload = client.improvements()
        elif args.command == "improvement-scan":
            payload = client.improvement_scan()
        else:
            payload = client.improvement_experiment(args.proposal_id)
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0
    except (httpx.RequestError, RuntimeError) as error:
        print(f"nexus: {error}", file=sys.stderr)
        return 1
    finally:
        client.close()


if __name__ == "__main__":
    raise SystemExit(main())
