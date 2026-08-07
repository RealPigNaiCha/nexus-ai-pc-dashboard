"""DeepTutor adapter for the AI-PC dashboard.

DeepTutor is kept as an external, replaceable capability: the dashboard
invokes its CLI in a dedicated runtime workspace and never runs the
interactive ``deeptutor init`` wizard (which would persist model keys into
``model_catalog.json``).

Credentials are injected only for the duration of one CLI call: the
keyless model catalog is restored (or an empty baseline is written) in a
``finally`` block before the caller returns, and the key is never placed in
arguments, logs, audit events, or SQLite.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import tempfile
import threading
from collections.abc import Callable, Sequence
from pathlib import Path
from time import perf_counter
from typing import Any

from .credentials import ApiCredentialStore, CredentialStorageError, normalize_provider
from .database import Database


logger = logging.getLogger("nexus.deeptutor")

DEFAULT_DEEPTUTOR_ROOT = Path(r"C:\AI-PC\tools\deeptutor")
DEFAULT_DEEPTUTOR_HOME = Path(r"C:\AI-PC\data\deeptutor")

SUPPORTED_CAPABILITIES = ("chat", "deep_solve", "deep_question", "deep_research")
SUPPORTED_ROLES = ("reasoning", "fast")
SUPPORTED_LANGUAGES = ("zh", "en")

# Dashboard provider id -> DeepTutor provider registry binding name.
DEEPTUTOR_BINDINGS = {
    "openai": "openai",
    "openai-compatible": "custom",
    "anthropic": "anthropic",
    "google-gemini": "gemini",
    "deepseek": "deepseek",
    "alibaba-bailian": "dashscope",
}

_WORKSPACE_MARKER = ".ai-pc-ready"


class DeepTutorError(RuntimeError):
    """Stable, detail-safe error raised by the DeepTutor integration."""

    def __init__(
        self,
        code: str,
        detail: str,
        status_code: int,
        *,
        provider: str | None = None,
        role: str | None = None,
        model: str | None = None,
        duration_ms: int = 0,
    ) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail
        self.status_code = status_code
        self.provider = provider
        self.role = role
        self.model = model
        self.duration_ms = duration_ms


def _empty_catalog() -> dict[str, Any]:
    return {
        "version": 1,
        "services": {
            name: {"active_profile_id": None, "active_model_id": None, "profiles": []}
            for name in (
                "llm",
                "embedding",
                "tts",
                "stt",
                "imagegen",
                "videogen",
            )
        }
        | {
            "search": {"active_profile_id": None, "profiles": []},
        },
    }


def _build_keyed_catalog(
    *,
    provider: str,
    model: str,
    endpoint: str,
    api_key: str,
) -> dict[str, Any]:
    binding = DEEPTUTOR_BINDINGS.get(provider)
    if binding is None:
        raise DeepTutorError(
            "unsupported_provider",
            "该模型服务商暂不支持 DeepTutor 调用",
            422,
            provider=provider,
        )
    catalog = _empty_catalog()
    catalog["services"]["llm"] = {
        "active_profile_id": "ai-pc-llm",
        "active_model_id": "ai-pc-model",
        "profiles": [
            {
                "id": "ai-pc-llm",
                "name": "AI-PC Dashboard",
                "binding": binding,
                "base_url": endpoint,
                "api_key": api_key,
                "api_version": "",
                "extra_headers": {},
                "models": [
                    {
                        "id": "ai-pc-model",
                        "name": model,
                        "model": model,
                    }
                ],
            }
        ],
    }
    return catalog


class DeepTutorService:
    """CLI-backed DeepTutor integration with per-call credential injection."""

    def __init__(
        self,
        *,
        database: Database,
        credential_store: ApiCredentialStore,
        root: Path | str = DEFAULT_DEEPTUTOR_ROOT,
        home: Path | str = DEFAULT_DEEPTUTOR_HOME,
        runner: Callable[[list[str], dict[str, str], float], subprocess.CompletedProcess[str]]
        | None = None,
        bootstrap_runner: Callable[[list[str], dict[str, str], float], subprocess.CompletedProcess[str]]
        | None = None,
        timeout_seconds: float = 300.0,
        auto_bootstrap: bool = True,
    ) -> None:
        self._database = database
        self._credential_store = credential_store
        self._root = Path(root).resolve()
        self._home = Path(home).expanduser().resolve()
        self._settings_dir = self._home / "data" / "user" / "settings"
        self._catalog_path = self._settings_dir / "model_catalog.json"
        self._python = self._root / ".venv-cli" / "Scripts" / "python.exe"
        self._timeout_seconds = float(timeout_seconds)
        self._auto_bootstrap = auto_bootstrap
        self._runner = runner or self._default_runner
        self._bootstrap_runner = bootstrap_runner or self._default_runner
        self._uses_injected_runner = runner is not None
        self._run_lock = threading.Lock()
        self._bootstrap_lock = threading.Lock()
        self._workspace_ready = False
        self._detect_cache: tuple[float, dict[str, object]] | None = None

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #

    def status(self) -> dict[str, object]:
        detect = self._detect()
        roles = [self._role_status(role) for role in SUPPORTED_ROLES]
        ready = bool(
            detect["installed"]
            and self._settings_dir.is_dir()
            and not detect["bootstrap_error"]
        )
        return {
            "installed": detect["installed"],
            "version": detect["version"],
            "ready": ready,
            "workspace": str(self._home),
            "settings": str(self._settings_dir),
            "capabilities": list(SUPPORTED_CAPABILITIES),
            "roles": roles,
            "bootstrap_error": detect["bootstrap_error"],
        }

    def run(
        self,
        *,
        capability: str,
        prompt: str,
        role: str = "reasoning",
        language: str = "zh",
        session_id: str | None = None,
        timeout_seconds: float | None = None,
    ) -> dict[str, object]:
        capability = (capability or "").strip()
        prompt = (prompt or "").strip()
        role = (role or "").strip()
        language = (language or "zh").strip().lower()
        if capability not in SUPPORTED_CAPABILITIES:
            raise DeepTutorError(
                "unsupported_capability",
                "不支持的 DeepTutor 能力",
                422,
            )
        if not prompt:
            raise DeepTutorError("empty_prompt", "提示词不能为空", 422)
        if role not in SUPPORTED_ROLES:
            raise DeepTutorError("unsupported_role", "该模型角色不支持 DeepTutor 调用", 422)
        if language not in SUPPORTED_LANGUAGES:
            raise DeepTutorError("unsupported_language", "目前支持 zh / en 两种语言", 422)

        try:
            self._ensure_workspace()
            if not self._uses_injected_runner and not self._python.is_file():
                raise DeepTutorError(
                    "deeptutor_not_installed",
                    "DeepTutor 运行环境不可用",
                    503,
                )

            config, provider, api_key = self._require_role(role)
            model = config["model"]
            endpoint = config["endpoint"]
            args = [
                str(self._python),
                "-m",
                "deeptutor_cli",
                "run",
                capability,
                prompt,
                "--format",
                "json",
                "--language",
                language,
            ]
            if session_id:
                args += ["--session", session_id]
            env = self._build_env()
            timeout = float(timeout_seconds or self._timeout_seconds)
            started = perf_counter()

            with self._run_lock:
                original = self._read_catalog_text()
                self._write_catalog_text(
                    _build_keyed_catalog(
                        provider=provider,
                        model=model,
                        endpoint=endpoint,
                        api_key=api_key,
                    )
                )
                try:
                    completed = self._runner(args, env, timeout)
                except subprocess.TimeoutExpired:
                    duration_ms = max(0, round((perf_counter() - started) * 1000))
                    raise DeepTutorError(
                        "timeout",
                        "DeepTutor 调用超时",
                        504,
                        provider=provider,
                        role=role,
                        model=model,
                        duration_ms=duration_ms,
                    ) from None
                except OSError as error:
                    duration_ms = max(0, round((perf_counter() - started) * 1000))
                    raise DeepTutorError(
                        "process_error",
                        "DeepTutor 进程启动失败",
                        503,
                        provider=provider,
                        role=role,
                        model=model,
                        duration_ms=duration_ms,
                    ) from error
                finally:
                    self._restore_catalog(original)
                    api_key = ""

            duration_ms = max(0, round((perf_counter() - started) * 1000))
            parsed = self._parse_output(completed)
            status = str(parsed.get("status") or "")
            error = parsed.get("error")
            if status == "failed" or error or completed.returncode != 0:
                error_detail = str(error or "").strip() or self._safe_stderr(completed)
                mapped = self._map_error(
                    error_detail,
                    provider=provider,
                    role=role,
                    model=model,
                    duration_ms=duration_ms,
                )
                self._record_call(
                    provider=provider,
                    role=role,
                    model=model,
                    duration_ms=duration_ms,
                    status="error",
                    error_code=mapped.code,
                    capability=capability,
                )
                mapped._recorded = True
                raise mapped

            self._record_call(
                provider=provider,
                role=role,
                model=model,
                duration_ms=duration_ms,
                status="success",
                capability=capability,
                prompt_tokens=parsed.get("prompt_tokens"),
                completion_tokens=parsed.get("completion_tokens"),
                total_tokens=parsed.get("total_tokens"),
            )
            return {
                "capability": capability,
                "answer": parsed.get("answer") or "",
                "status": "success",
                "session_id": parsed.get("session_id"),
                "turn_id": parsed.get("turn_id"),
                "model": model,
                "provider": provider,
                "language": language,
                "latency_ms": duration_ms,
                "prompt_tokens": parsed.get("prompt_tokens"),
                "completion_tokens": parsed.get("completion_tokens"),
                "total_tokens": parsed.get("total_tokens"),
            }
        except DeepTutorError as error:
            if not getattr(error, "_recorded", False):
                self._record_call(
                    provider=error.provider or "",
                    role=error.role or role,
                    model=error.model or "",
                    duration_ms=error.duration_ms,
                    status="error",
                    error_code=error.code,
                    capability=capability,
                )
            raise

    # ------------------------------------------------------------------ #
    # Role and credential handling
    # ------------------------------------------------------------------ #

    def _role_status(self, role: str) -> dict[str, object]:
        roles = {item["role"]: item for item in self._database.get_model_roles()}
        config = roles.get(role)
        if not config or not config.get("model"):
            return {
                "role": role,
                "provider": "",
                "model": "",
                "endpoint": "",
                "ready": False,
                "error": "role_not_configured",
            }
        provider = normalize_provider(config.get("provider", ""))
        if provider is None:
            return {
                "role": role,
                "provider": config.get("provider", ""),
                "model": config.get("model", ""),
                "endpoint": config.get("endpoint", ""),
                "ready": False,
                "error": "unsupported_provider",
            }
        try:
            configured = self._credential_store.is_configured(provider)
        except CredentialStorageError:
            return {
                "role": role,
                "provider": provider,
                "model": config.get("model", ""),
                "endpoint": config.get("endpoint", ""),
                "ready": False,
                "error": "credential_store_unavailable",
            }
        return {
            "role": role,
            "provider": provider,
            "model": config.get("model", ""),
            "endpoint": config.get("endpoint", ""),
            "ready": configured,
            "error": None if configured else "credential_missing",
        }

    def _require_role(self, role: str) -> tuple[dict[str, str], str, str]:
        roles = {item["role"]: item for item in self._database.get_model_roles()}
        config = roles.get(role)
        provider = normalize_provider(config.get("provider", "")) if config else None
        if not config or not config.get("model") or provider is None:
            raise DeepTutorError(
                "role_not_configured",
                "该模型角色尚未配置",
                409,
                role=role,
            )
        if provider not in DEEPTUTOR_BINDINGS:
            raise DeepTutorError(
                "unsupported_provider",
                "该模型服务商暂不支持 DeepTutor 调用",
                422,
                provider=provider,
                role=role,
            )
        try:
            api_key = self._credential_store.get(provider)
        except CredentialStorageError:
            raise DeepTutorError(
                "credential_store_unavailable",
                "凭据存储不可用",
                503,
                provider=provider,
                role=role,
            ) from None
        if api_key is None:
            raise DeepTutorError(
                "credential_missing",
                "该模型角色缺少 API 密钥",
                409,
                provider=provider,
                role=role,
            )
        return config, provider, api_key

    # ------------------------------------------------------------------ #
    # Workspace bootstrap and catalog management
    # ------------------------------------------------------------------ #

    def _ensure_workspace(self) -> None:
        if self._workspace_ready:
            return
        with self._bootstrap_lock:
            if self._workspace_ready:
                return
            self._settings_dir.mkdir(parents=True, exist_ok=True)
            marker = self._home / _WORKSPACE_MARKER
            if self._auto_bootstrap and not marker.is_file():
                self._run_bootstrap()
                self._write_catalog_text(_empty_catalog())
                marker.write_text("ok", encoding="utf-8")
            self._workspace_ready = True

    def _run_bootstrap(self) -> None:
        script = (
            "import os\n"
            "from pathlib import Path\n"
            "home = Path(os.environ['DEEPTUTOR_HOME'])\n"
            "os.environ['DEEPTUTOR_HOME'] = str(home)\n"
            "from deeptutor.services.config.runtime_settings import ensure_runtime_settings_files\n"
            "ensure_runtime_settings_files()\n"
            "from deeptutor.services.path_service import get_path_service\n"
            "get_path_service().ensure_all_directories()\n"
            "print('BOOTSTRAP_OK')\n"
        )
        env = os.environ.copy()
        env["DEEPTUTOR_HOME"] = str(self._home)
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONUTF8"] = "1"
        try:
            completed = self._bootstrap_runner(
                [str(self._python), "-c", script],
                env,
                min(90.0, max(30.0, self._timeout_seconds / 2)),
            )
        except (OSError, subprocess.TimeoutExpired):
            self._detect_cache = None
            raise DeepTutorError(
                "bootstrap_failed",
                "DeepTutor 工作区初始化失败",
                503,
            ) from None
        if completed.returncode != 0:
            self._detect_cache = None
            raise DeepTutorError(
                "bootstrap_failed",
                "DeepTutor 工作区初始化失败",
                503,
            )

    def _read_catalog_text(self) -> str | None:
        try:
            return self._catalog_path.read_text(encoding="utf-8")
        except OSError:
            return None

    def _write_catalog_text(self, catalog: dict[str, Any]) -> None:
        self._settings_dir.mkdir(parents=True, exist_ok=True)
        fd, temp_name = tempfile.mkstemp(
            prefix=".model_catalog.",
            suffix=".tmp",
            dir=self._settings_dir,
        )
        temp_path = Path(temp_name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                json.dump(catalog, handle, indent=2, ensure_ascii=False)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_path, self._catalog_path)
        finally:
            temp_path.unlink(missing_ok=True)

    def _restore_catalog(self, original: str | None) -> None:
        if original is not None:
            try:
                self._catalog_path.write_text(original, encoding="utf-8", newline="\n")
            except OSError:
                logger.exception("Failed to restore keyless DeepTutor catalog")
                self._write_catalog_text(_empty_catalog())
            return
        self._write_catalog_text(_empty_catalog())

    # ------------------------------------------------------------------ #
    # Process and output handling
    # ------------------------------------------------------------------ #

    def _build_env(self) -> dict[str, str]:
        env = os.environ.copy()
        env["DEEPTUTOR_HOME"] = str(self._home)
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONUTF8"] = "1"
        return env

    @staticmethod
    def _default_runner(
        args: list[str],
        env: dict[str, str],
        timeout_seconds: float,
    ) -> subprocess.CompletedProcess[str]:
        creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        return subprocess.run(
            args,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout_seconds,
            env=env,
            creationflags=creationflags,
            check=False,
        )

    def _parse_output(
        self,
        completed: subprocess.CompletedProcess[str],
    ) -> dict[str, Any]:
        chunks: dict[str, list[str]] = {}
        final_call_ids: set[str] = set()
        fallback: list[str] = []
        error: str | None = None
        status: str = "success"
        session_id: str | None = None
        turn_id: str | None = None
        metadata: dict[str, Any] = {}
        for line in (completed.stdout or "").splitlines():
            line = line.strip()
            if not line or not line.startswith("{"):
                continue
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if not isinstance(event, dict):
                continue
            event_type = str(event.get("type") or "")
            event_meta = event.get("metadata") or {}
            if not isinstance(event_meta, dict):
                event_meta = {}
            if event_type == "session":
                session_id = str(event.get("session_id") or event_meta.get("session_id") or "")
                turn_id = str(event.get("turn_id") or event_meta.get("turn_id") or "")
            elif event_type == "content":
                content = str(event.get("content") or "")
                if not content:
                    continue
                call_id = str(event_meta.get("call_id") or "")
                trace_kind = str(event_meta.get("trace_kind") or "")
                if call_id and trace_kind == "llm_chunk":
                    chunks.setdefault(call_id, []).append(content)
                elif trace_kind == "llm_output" or not call_id:
                    fallback.append(content)
            elif event_type == "progress":
                if (
                    str(event_meta.get("trace_kind") or "") == "call_status"
                    and str(event_meta.get("call_state") or "") == "complete"
                    and str(event_meta.get("call_role") or "") == "finish"
                ):
                    final_call_ids.add(str(event_meta.get("call_id") or ""))
            elif event_type == "error":
                error = str(event.get("content") or "") or error
                status = "failed"
            elif event_type == "done":
                done_meta = event.get("metadata") or {}
                if isinstance(done_meta, dict) and str(done_meta.get("status") or "") == "failed":
                    status = "failed"
            elif event_type == "result":
                if isinstance(event_meta, dict):
                    metadata = event_meta
        if status != "failed":
            parts = [chunks[call_id] for call_id in chunks if call_id in final_call_ids]
            if not parts:
                parts = list(chunks.values())
            answer = "".join("".join(part) for part in parts).strip()
            if not answer and fallback:
                answer = "".join(fallback).strip()
        else:
            answer = ""
        cost = metadata.get("cost_summary") or {}
        if not isinstance(cost, dict):
            cost = {}
        return {
            "answer": answer,
            "status": status,
            "error": error,
            "session_id": session_id,
            "turn_id": turn_id,
            "prompt_tokens": cost.get("prompt_tokens"),
            "completion_tokens": cost.get("completion_tokens"),
            "total_tokens": cost.get("total_tokens"),
        }

    @staticmethod
    def _safe_stderr(completed: subprocess.CompletedProcess[str]) -> str:
        text = (completed.stderr or "").strip()
        return text[:500]

    def _map_error(
        self,
        detail: str,
        *,
        provider: str,
        role: str,
        model: str,
        duration_ms: int,
    ) -> DeepTutorError:
        lowered = detail.lower()
        if "timeout" in lowered or "timed out" in lowered:
            code, message, http = "timeout", "DeepTutor 调用超时", 504
        elif "rate" in lowered and ("limit" in lowered or "429" in lowered):
            code, message, http = "rate_limited", "模型服务配额或速率受限", 429
        elif "401" in lowered or "authentication" in lowered or "invalid api key" in lowered:
            code, message, http = "authentication_failed", "模型服务拒绝了凭据", 401
        else:
            code, message, http = "upstream_error", "DeepTutor 调用失败", 502
        return DeepTutorError(
            code,
            message,
            http,
            provider=provider,
            role=role,
            model=model,
            duration_ms=duration_ms,
        )

    def _record_call(
        self,
        *,
        provider: str,
        role: str,
        model: str,
        duration_ms: int,
        status: str,
        capability: str,
        error_code: str | None = None,
        prompt_tokens: int | None = None,
        completion_tokens: int | None = None,
        total_tokens: int | None = None,
    ) -> None:
        try:
            self._database.record_model_call(
                provider=provider,
                operation="deeptutor_run",
                source="dashboard_deeptutor",
                duration_ms=duration_ms,
                status=status,
                role=role,
                model=model,
                error_code=error_code,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=total_tokens,
            )
            self._database.audit(
                "deeptutor",
                "run",
                capability,
                result="error" if status == "error" else "success",
            )
        except Exception:
            logger.exception("Failed to record DeepTutor call metrics")

    # ------------------------------------------------------------------ #
    # Detection helpers
    # ------------------------------------------------------------------ #

    def _detect(self) -> dict[str, object]:
        now = perf_counter()
        if self._detect_cache is not None and now - self._detect_cache[0] < 30:
            return self._detect_cache[1]
        installed = self._python.is_file()
        version = self._deeptutor_version()
        bootstrap_error = ""
        if installed and not self._settings_dir.is_dir():
            try:
                self._ensure_workspace()
            except DeepTutorError as error:
                bootstrap_error = error.detail
        result: dict[str, object] = {
            "installed": installed,
            "version": version,
            "bootstrap_error": bootstrap_error,
        }
        self._detect_cache = (now, result)
        return result

    def _deeptutor_version(self) -> str | None:
        site_packages = self._root / ".venv-cli" / "Lib" / "site-packages"
        if site_packages.is_dir():
            for entry in site_packages.iterdir():
                if entry.name.startswith("deeptutor_cli-") and entry.name.endswith(".dist-info"):
                    version = entry.name[len("deeptutor_cli-") : -len(".dist-info")]
                    if version:
                        return version
        version_file = self._root / "deeptutor" / "__version__.py"
        try:
            for line in version_file.read_text(encoding="utf-8").splitlines():
                if line.startswith("__version__"):
                    return line.partition("=")[2].strip().strip("\"'")
        except OSError:
            pass
        return None
