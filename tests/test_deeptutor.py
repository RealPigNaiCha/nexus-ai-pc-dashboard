import json
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.app import create_app
from backend.credentials import ApiCredentialStore, SERVICE_NAME
from backend.database import Database
from backend.deeptutor import DeepTutorError, DeepTutorService


class MemoryKeyring:
    def __init__(self) -> None:
        self.secrets: dict[tuple[str, str], str] = {}

    def get_password(self, service: str, username: str) -> str | None:
        return self.secrets.get((service, username))

    def set_password(self, service: str, username: str, password: str) -> None:
        self.secrets[(service, username)] = password

    def delete_password(self, service: str, username: str) -> None:
        self.secrets.pop((service, username), None)


SUCCESS_NDJSON = "\n".join(
    [
        json.dumps(
            {
                "type": "session",
                "content": "",
                "metadata": {"session_id": "sess-1", "turn_id": "turn-1"},
                "session_id": "sess-1",
                "turn_id": "turn-1",
            }
        ),
        json.dumps(
            {
                "type": "content",
                "content": "你好",
                "metadata": {"call_id": "c1", "trace_kind": "llm_chunk"},
            }
        ),
        json.dumps(
            {
                "type": "progress",
                "content": "",
                "metadata": {
                    "trace_kind": "call_status",
                    "call_state": "complete",
                    "call_role": "finish",
                    "call_id": "c1",
                },
            }
        ),
        json.dumps(
            {
                "type": "result",
                "content": "",
                "metadata": {
                    "cost_summary": {
                        "prompt_tokens": 10,
                        "completion_tokens": 5,
                        "total_tokens": 15,
                    }
                },
            }
        ),
        json.dumps({"type": "done", "content": "", "metadata": {"status": "success"}}),
    ]
)


def make_environment(
    tmp_path: Path,
    *,
    runner,
    bootstrap_runner=None,
    auto_bootstrap: bool = False,
    configure_role: bool = True,
) -> tuple[Database, DeepTutorService, MemoryKeyring]:
    database = Database(tmp_path / "deeptutor.sqlite3")
    database.initialize()
    if configure_role:
        database.save_model_role(
            role="reasoning",
            provider="openai",
            model="gpt-test",
            endpoint="https://api.openai.com/v1",
        )
        database.save_model_role(
            role="fast",
            provider="deepseek",
            model="deepseek-chat",
            endpoint="https://api.deepseek.com",
        )
    backend = MemoryKeyring()
    backend.secrets[(SERVICE_NAME, "api-key:openai")] = "sk-test-secret"
    store = ApiCredentialStore(backend)
    service = DeepTutorService(
        database=database,
        credential_store=store,
        root=tmp_path / "deeptutor",
        home=tmp_path / "deeptutor-home",
        runner=runner,
        bootstrap_runner=bootstrap_runner,
        auto_bootstrap=auto_bootstrap,
    )
    return database, service, backend


def completed(*, returncode: int = 0, stdout: str = "", stderr: str = "") -> subprocess.CompletedProcess[str]:
    return subprocess.CompletedProcess(
        args=[],
        returncode=returncode,
        stdout=stdout,
        stderr=stderr,
    )


def catalog_text(home: Path) -> str:
    path = home / "data" / "user" / "settings" / "model_catalog.json"
    return path.read_text(encoding="utf-8")


def test_run_success_parses_answer_and_keeps_catalog_keyless(tmp_path: Path) -> None:
    calls: list[tuple[list[str], dict[str, str], float]] = []

    def runner(args, env, timeout):
        calls.append((args, env, timeout))
        return completed(stdout=SUCCESS_NDJSON)

    database, service, _ = make_environment(tmp_path, runner=runner)

    result = service.run(capability="chat", prompt="你好", role="reasoning", language="zh")

    assert result["answer"] == "你好"
    assert result["session_id"] == "sess-1"
    assert result["turn_id"] == "turn-1"
    assert result["status"] == "success"
    assert result["model"] == "gpt-test"
    assert result["prompt_tokens"] == 10
    assert result["total_tokens"] == 15
    assert len(calls) == 1
    args, env, _ = calls[0]
    assert args[:3] == [str(service._python), "-m", "deeptutor_cli"]
    assert "run" in args and "chat" in args and "你好" in args
    assert env["DEEPTUTOR_HOME"] == str(service._home)

    catalog = json.loads(catalog_text(service._home))
    assert catalog["services"]["llm"]["profiles"] == []
    assert "sk-test-secret" not in catalog_text(service._home)

    calls_row = database.query_one("SELECT * FROM model_calls ORDER BY id DESC LIMIT 1")
    assert calls_row["operation"] == "deeptutor_run"
    assert calls_row["status"] == "success"
    assert calls_row["provider"] == "openai"
    assert calls_row["model"] == "gpt-test"
    assert calls_row["prompt_tokens"] == 10
    assert calls_row["total_tokens"] == 15
    audit = database.query_all(
        "SELECT category, action, result FROM audit_events WHERE category = 'deeptutor' ORDER BY id DESC LIMIT 1"
    )
    assert audit and audit[0]["action"] == "run" and audit[0]["result"] == "success"


def test_failure_records_error_and_restores_keyless_catalog(tmp_path: Path) -> None:
    def runner(args, env, timeout):
        return completed(
            returncode=1,
            stdout=json.dumps(
                {
                    "type": "error",
                    "content": "Invalid API key",
                    "metadata": {"turn_terminal": True, "status": "failed"},
                }
            ),
            stderr="HTTP 401",
        )

    database, service, _ = make_environment(tmp_path, runner=runner)

    with pytest.raises(DeepTutorError) as excinfo:
        service.run(capability="chat", prompt="hi", role="reasoning")

    assert excinfo.value.code == "authentication_failed"
    assert excinfo.value.status_code == 401
    assert "sk-test-secret" not in catalog_text(service._home)
    row = database.query_one("SELECT * FROM model_calls ORDER BY id DESC LIMIT 1")
    assert row["status"] == "error"
    assert row["error_code"] == "authentication_failed"


def test_timeout_restores_catalog_and_records_timeout(tmp_path: Path) -> None:
    def runner(args, env, timeout):
        raise subprocess.TimeoutExpired(cmd=args, timeout=timeout)

    database, service, _ = make_environment(tmp_path, runner=runner)

    with pytest.raises(DeepTutorError) as excinfo:
        service.run(capability="chat", prompt="hi", role="reasoning", timeout_seconds=30)

    assert excinfo.value.code == "timeout"
    assert excinfo.value.status_code == 504
    assert "sk-test-secret" not in catalog_text(service._home)
    row = database.query_one("SELECT * FROM model_calls ORDER BY id DESC LIMIT 1")
    assert row["status"] == "error"
    assert row["error_code"] == "timeout"


def test_validation_and_role_errors_never_invoke_runner(tmp_path: Path) -> None:
    invoked = []

    def runner(args, env, timeout):
        invoked.append(args)
        return completed(stdout=SUCCESS_NDJSON)

    database, service, _ = make_environment(
        tmp_path, runner=runner, configure_role=False
    )
    with pytest.raises(DeepTutorError) as excinfo:
        service.run(capability="chat", prompt="hi", role="reasoning")
    assert excinfo.value.code == "role_not_configured"

    database, service, _ = make_environment(tmp_path, runner=runner)
    with pytest.raises(DeepTutorError) as excinfo:
        service.run(capability="unknown", prompt="hi")
    assert excinfo.value.code == "unsupported_capability"
    with pytest.raises(DeepTutorError) as excinfo:
        service.run(capability="chat", prompt="   ")
    assert excinfo.value.code == "empty_prompt"
    with pytest.raises(DeepTutorError) as excinfo:
        service.run(capability="chat", prompt="hi", role="vision")
    assert excinfo.value.code == "unsupported_role"
    with pytest.raises(DeepTutorError) as excinfo:
        service.run(capability="chat", prompt="hi", language="ja")
    assert excinfo.value.code == "unsupported_language"
    assert invoked == []


def test_bootstrap_writes_keyless_baseline_before_run(tmp_path: Path) -> None:
    bootstrap_calls = []

    def bootstrap_runner(args, env, timeout):
        bootstrap_calls.append((args, env))
        return completed(stdout="BOOTSTRAP_OK")

    def runner(args, env, timeout):
        return completed(stdout=SUCCESS_NDJSON)

    _, service, _ = make_environment(
        tmp_path,
        runner=runner,
        bootstrap_runner=bootstrap_runner,
        auto_bootstrap=True,
    )

    service.run(capability="chat", prompt="hi", role="reasoning")

    assert len(bootstrap_calls) == 1
    args, env = bootstrap_calls[0]
    assert "-c" in args
    assert env["DEEPTUTOR_HOME"] == str(service._home)
    assert (service._home / ".ai-pc-ready").is_file()
    assert "sk-test-secret" not in catalog_text(service._home)


def test_status_never_exposes_secrets(tmp_path: Path) -> None:
    def runner(args, env, timeout):
        return completed(stdout=SUCCESS_NDJSON)

    _, service, _ = make_environment(tmp_path, runner=runner)

    status = service.status()
    rendered = json.dumps(status, ensure_ascii=False)
    assert "sk-test-secret" not in rendered
    assert status["capabilities"] == ["chat", "deep_solve", "deep_question", "deep_research"]
    roles = {item["role"]: item for item in status["roles"]}
    assert roles["reasoning"]["ready"] is True
    assert roles["reasoning"]["provider"] == "openai"
    assert roles["fast"]["ready"] is False
    assert roles["fast"]["error"] == "credential_missing"


def test_api_status_and_run_endpoints(tmp_path: Path) -> None:
    def runner(args, env, timeout):
        return completed(stdout=SUCCESS_NDJSON)

    database, service, backend = make_environment(tmp_path, runner=runner)
    app = create_app(
        tmp_path / "api.sqlite3",
        serve_static=False,
        credential_backend=backend,
        deeptutor_service=service,
    )
    client = TestClient(app)

    with client:
        status = client.get("/api/deeptutor/status").json()
        assert status["installed"] is False
        assert status["ready"] is False
        assert "sk-test-secret" not in client.get("/api/deeptutor/status").text

        ok = client.post(
            "/api/deeptutor/run",
            json={
                "capability": "chat",
                "prompt": "你好",
                "role": "reasoning",
                "language": "zh",
                "timeout_seconds": 60,
            },
        )
        assert ok.status_code == 200
        assert ok.json()["answer"] == "你好"
        assert ok.json()["model"] == "gpt-test"

        missing = client.post(
            "/api/deeptutor/run",
            json={"capability": "chat", "prompt": "hi", "role": "fast", "language": "zh"},
        )
        assert missing.status_code == 409
        assert missing.json()["detail"] == "该模型角色缺少 API 密钥"

        invalid = client.post(
            "/api/deeptutor/run",
            json={"capability": "chat", "prompt": "hi", "role": "reasoning", "language": "ja"},
        )
        assert invalid.status_code == 422

    rows = database.query_all("SELECT * FROM model_calls ORDER BY id")
    assert any(row["operation"] == "deeptutor_run" and row["status"] == "success" for row in rows)
    assert any(
        row["operation"] == "deeptutor_run"
        and row["status"] == "error"
        and row["error_code"] == "credential_missing"
        for row in rows
    )
