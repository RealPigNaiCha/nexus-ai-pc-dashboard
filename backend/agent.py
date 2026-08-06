from __future__ import annotations

import hashlib
import json
import os
import stat
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping
from urllib.parse import quote


CLINE_EXTENSION_ID = "saoudrizwan.claude-dev"


class AgentHandoffError(RuntimeError):
    pass


@dataclass(frozen=True)
class PreparedTask:
    path: Path
    sha256: str


class AgentHandoff:
    def __init__(
        self,
        workspace_path: Path,
        task_root: Path,
        *,
        allowed_workspace_root: Path | None = None,
        code_executable: Path | None = None,
        process_launcher: Callable[[list[str], Path], None] | None = None,
        uri_opener: Callable[[str], None] | None = None,
        cline_version: str | None = None,
        extension_root: Path | None = None,
    ) -> None:
        self.workspace_path = workspace_path
        self.task_root = task_root
        self.allowed_workspace_root = allowed_workspace_root or workspace_path.parent
        self.code_executable = code_executable or self._find_code_executable()
        self._process_launcher = process_launcher or self._launch_process
        self._uri_opener = uri_opener or self._open_uri
        self._cline_version_override = cline_version
        self.extension_root = extension_root or (Path.home() / ".vscode" / "extensions")

    def status(self) -> dict[str, object]:
        workspace_exists = self.workspace_path.is_dir()
        workspace_approved = self._workspace_is_approved()
        vscode_available = bool(self.code_executable and self.code_executable.is_file())
        cline_version = self._cline_version_override or self._find_cline_version()
        return {
            "available": workspace_exists and workspace_approved and vscode_available and bool(cline_version),
            "workspace_available": workspace_exists and workspace_approved,
            "workspace_exists": workspace_exists,
            "workspace_approved": workspace_approved,
            "workspace_path": str(self.workspace_path),
            "task_root": str(self.task_root),
            "vscode_available": vscode_available,
            "cline_available": bool(cline_version),
            "cline_version": cline_version,
            "execution_mode": "explicit_handoff",
        }

    def prepare_task(self, task: Mapping[str, object]) -> PreparedTask:
        workspace = self._resolved_workspace()
        task_id = int(task["id"])
        content = self._task_document(task, workspace).encode("utf-8")
        expected_sha256 = hashlib.sha256(content).hexdigest()
        temporary_path: Path | None = None

        try:
            self.task_root.mkdir(parents=True, exist_ok=True)
            task_root = self.task_root.resolve(strict=True)
            task_path = task_root / f"task-{task_id:06d}.md"
            if task_path.exists():
                resolved_path = task_path.resolve(strict=True)
                if not resolved_path.is_relative_to(task_root) or not resolved_path.is_file():
                    raise AgentHandoffError("Existing task file is outside the approved task directory")
                actual_sha256 = hashlib.sha256(resolved_path.read_bytes()).hexdigest()
                if actual_sha256 != expected_sha256:
                    raise AgentHandoffError("Existing task file failed its integrity check")
                return PreparedTask(path=resolved_path, sha256=actual_sha256)

            with tempfile.NamedTemporaryFile(
                mode="wb",
                dir=task_root,
                prefix=f"task-{task_id:06d}-",
                suffix=".tmp",
                delete=False,
            ) as temporary:
                temporary.write(content)
                temporary.flush()
                os.fsync(temporary.fileno())
                temporary_path = Path(temporary.name)

            os.replace(temporary_path, task_path)
            temporary_path = None
            task_path.chmod(stat.S_IREAD | stat.S_IRGRP | stat.S_IROTH)
            resolved_path = task_path.resolve(strict=True)
            actual_sha256 = hashlib.sha256(resolved_path.read_bytes()).hexdigest()
            if actual_sha256 != expected_sha256:
                raise AgentHandoffError("Task file failed its integrity check")
            return PreparedTask(path=resolved_path, sha256=actual_sha256)
        except AgentHandoffError:
            raise
        except OSError as error:
            raise AgentHandoffError("Task file could not be prepared") from error
        finally:
            if temporary_path is not None:
                try:
                    temporary_path.unlink(missing_ok=True)
                except OSError:
                    pass

    def open_workspace(self) -> None:
        workspace = self._resolved_workspace()
        code = self._resolved_code()
        self._process_launcher([str(code), "--reuse-window", str(workspace)], workspace)

    def open_in_cline(self, task: Mapping[str, object], task_file: Path) -> str:
        workspace = self._resolved_workspace()
        code = self._resolved_code()
        if not (self._cline_version_override or self._find_cline_version()):
            raise AgentHandoffError("Cline extension is not installed")

        try:
            task_path = task_file.resolve(strict=True)
            task_root = self.task_root.resolve(strict=True)
        except OSError as error:
            raise AgentHandoffError("Task file is unavailable") from error
        if not task_path.is_relative_to(task_root) or not task_path.is_file():
            raise AgentHandoffError("Task file is outside the approved task directory")

        prompt = (
            f"AI-PC 编程任务 #{int(task['id'])}。读取只读任务说明：{task_path}。"
            "仅按文件中批准的范围执行，并继续遵循 Cline 的逐步授权。"
        )
        uri = f"vscode://{CLINE_EXTENSION_ID}/task?prompt={quote(prompt, safe='')}"
        self._process_launcher([str(code), "--reuse-window", str(workspace)], workspace)
        self._uri_opener(uri)
        return uri

    def _resolved_workspace(self) -> Path:
        try:
            workspace = self.workspace_path.resolve(strict=True)
            allowed_root = self.allowed_workspace_root.resolve(strict=True)
        except OSError as error:
            raise AgentHandoffError("Approved Agent workspace is unavailable") from error
        if not workspace.is_dir():
            raise AgentHandoffError("Approved Agent workspace is not a directory")
        if workspace == allowed_root or not workspace.is_relative_to(allowed_root):
            raise AgentHandoffError("Agent workspace is outside the approved workspace root")
        return workspace

    def _workspace_is_approved(self) -> bool:
        try:
            workspace = self.workspace_path.resolve(strict=True)
            allowed_root = self.allowed_workspace_root.resolve(strict=True)
        except OSError:
            return False
        return workspace.is_dir() and workspace != allowed_root and workspace.is_relative_to(allowed_root)

    def _resolved_code(self) -> Path:
        if self.code_executable is None:
            raise AgentHandoffError("Visual Studio Code is unavailable")
        try:
            code = self.code_executable.resolve(strict=True)
        except OSError as error:
            raise AgentHandoffError("Visual Studio Code is unavailable") from error
        if not code.is_file():
            raise AgentHandoffError("Visual Studio Code executable is invalid")
        return code

    @staticmethod
    def _task_document(task: Mapping[str, object], workspace: Path) -> str:
        run_tests = bool(task.get("run_tests"))
        generate_summary = bool(task.get("generate_summary"))
        allow_dependencies = bool(task.get("allow_dependencies"))
        dependency_rule = (
            "可以提出安装依赖，但仍需用户在 Cline 中逐步确认。"
            if allow_dependencies
            else "不要安装或升级依赖；如确有必要，先说明原因并等待用户修改任务设置。"
        )
        return f"""# AI-PC 编程任务 #{int(task['id'])}

- 项目：{task['project']}
- 工作目录：{workspace}
- 创建时间：{task['created_at']}
- 交接方式：VS Code + Cline（显式用户启动）

## 任务

{task['title']}

## 执行约束

1. 先读取工作区中的 AGENTS.md 和与任务直接相关的文件。
2. 只能在上述工作目录内修改源码；不要写入 C:\\AI-PC\\data、备份、日志或正式数据库。
3. 不要读取、输出或持久化 API 密钥、令牌、Cookie 或 Windows Credential Manager 内容。
4. 修改前检查现状，保持变更范围与任务一致，不撤销用户已有修改。
5. {"完成后运行相关测试并记录结果。" if run_tests else "只有用户明确要求时才运行测试。"}
6. {"完成后生成简短变更说明。" if generate_summary else "无需额外生成变更说明。"}
7. {dependency_rule}
8. 不要自行推送、发布、合并或执行破坏性命令。
9. 所有电脑和命令操作仍受 Cline 的授权界面约束，本文件不授予额外权限。

## 完成标准

- 任务要求已实现并经过与风险相称的验证。
- 向用户展示实际变更、测试结果和仍存在的限制。
- 保留 Git diff 供用户审查。
"""

    @staticmethod
    def _find_code_executable() -> Path | None:
        candidates = [
            Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Microsoft VS Code" / "Code.exe",
            Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Microsoft VS Code" / "Code.exe",
        ]
        return next((path for path in candidates if path.is_file()), None)

    def _find_cline_version(self) -> str | None:
        extension_root = self.extension_root
        if not extension_root.is_dir():
            return None
        candidates = sorted(extension_root.glob(f"{CLINE_EXTENSION_ID}-*"), reverse=True)
        for directory in candidates:
            package_path = directory / "package.json"
            try:
                package = json.loads(package_path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if package.get("publisher") == "saoudrizwan" and package.get("name") == "claude-dev":
                version = package.get("version")
                return str(version) if version else None
        return None

    @staticmethod
    def _launch_process(arguments: list[str], workspace: Path) -> None:
        try:
            subprocess.Popen(
                arguments,
                cwd=workspace,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                close_fds=True,
            )
        except OSError as error:
            raise AgentHandoffError("Visual Studio Code could not be started") from error

    @staticmethod
    def _open_uri(uri: str) -> None:
        try:
            os.startfile(uri)  # type: ignore[attr-defined]
        except (AttributeError, OSError) as error:
            raise AgentHandoffError("Cline task URI could not be opened") from error
