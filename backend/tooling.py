from __future__ import annotations

import json
import os
import re
from pathlib import Path

from .agent import AgentHandoff


VERSION_ASSIGNMENT = re.compile(r'^__version__\s*=\s*["\']([^"\']+)["\']', re.MULTILINE)


class ToolRegistry:
    """Report installed AI-PC capabilities without reading credentials or login state."""

    def __init__(
        self,
        ai_pc_root: Path,
        agent_handoff: AgentHandoff,
        *,
        local_app_data: Path | None = None,
        program_files: Path | None = None,
    ) -> None:
        self.ai_pc_root = ai_pc_root
        self.agent_handoff = agent_handoff
        self.local_app_data = local_app_data or Path(os.environ.get("LOCALAPPDATA", ""))
        self.program_files = program_files or Path(os.environ.get("ProgramFiles", r"C:\Program Files"))

    def list_tools(self, app_version: str) -> list[dict[str, object]]:
        agent_status = self.agent_handoff.status()
        deeptutor_root = self.ai_pc_root / "tools" / "deeptutor"
        deeptutor_python = deeptutor_root / ".venv-cli" / "Scripts" / "python.exe"
        codex_executable = self.ai_pc_root / "tools" / "codex" / "codex.exe"
        obsidian_executable = self.local_app_data / "Programs" / "Obsidian" / "Obsidian.exe"
        zotero_executable = self.program_files / "Zotero" / "zotero.exe"
        vault_path = self.ai_pc_root / "vault"

        deeptutor_installed = (deeptutor_root / "pyproject.toml").is_file()
        deeptutor_ready = deeptutor_installed and deeptutor_python.is_file()
        codex_installed = codex_executable.is_file()
        obsidian_installed = obsidian_executable.is_file()
        zotero_installed = zotero_executable.is_file()
        obsidian_ready = obsidian_installed and vault_path.is_dir()

        return [
            self._tool(
                "nexus-core",
                "Nexus data core",
                "core",
                "ready",
                "active",
                True,
                version=app_version,
                path=self.ai_pc_root / "app" / "dashboard",
            ),
            self._tool(
                "vscode",
                "Visual Studio Code",
                "coding",
                "ready" if agent_status["vscode_available"] else "unavailable",
                "active" if agent_status["vscode_available"] else "missing",
                bool(agent_status["vscode_available"]),
                path=self.agent_handoff.code_executable,
            ),
            self._tool(
                "cline",
                "Cline",
                "coding",
                "ready" if agent_status["cline_available"] else "unavailable",
                "active" if agent_status["cline_available"] else "missing",
                bool(agent_status["cline_available"]),
                version=str(agent_status["cline_version"]) if agent_status["cline_version"] else None,
                path=self.agent_handoff.extension_root,
            ),
            self._tool(
                "deeptutor",
                "DeepTutor",
                "learning",
                "ready" if deeptutor_ready else "installed" if deeptutor_installed else "unavailable",
                "active" if deeptutor_ready else "adapter_pending" if deeptutor_installed else "missing",
                deeptutor_ready,
                version=self._deeptutor_version(deeptutor_root),
                path=deeptutor_root,
            ),
            self._tool(
                "codex-cli",
                "Codex CLI",
                "coding",
                "installed" if codex_installed else "unavailable",
                "isolated_manual" if codex_installed else "missing",
                codex_installed,
                version=self._codex_version(codex_executable.parent),
                path=codex_executable,
            ),
            self._tool(
                "obsidian",
                "Obsidian",
                "knowledge",
                "ready" if obsidian_ready else "installed" if obsidian_installed else "unavailable",
                "active" if obsidian_ready else "vault_pending" if obsidian_installed else "missing",
                obsidian_installed,
                path=obsidian_executable,
            ),
            self._tool(
                "zotero",
                "Zotero",
                "research",
                "installed" if zotero_installed else "unavailable",
                "adapter_pending" if zotero_installed else "missing",
                zotero_installed,
                version=self._zotero_version(zotero_executable),
                path=zotero_executable,
            ),
            self._tool("paperqa2", "PaperQA2", "research", "ready", "active", True),
            self._tool("openadapt", "OpenAdapt", "automation", "planned", "planned", False),
        ]

    @staticmethod
    def _tool(
        tool_id: str,
        name: str,
        category: str,
        status: str,
        integration: str,
        installed: bool,
        *,
        version: str | None = None,
        path: Path | None = None,
    ) -> dict[str, object]:
        return {
            "id": tool_id,
            "name": name,
            "category": category,
            "status": status,
            "integration": integration,
            "installed": installed,
            "available": installed,
            "kind": category,
            "version": version,
            "path": str(path) if path else None,
        }

    @staticmethod
    def _deeptutor_version(root: Path) -> str | None:
        version_file = root / "deeptutor" / "__version__.py"
        try:
            match = VERSION_ASSIGNMENT.search(version_file.read_text(encoding="utf-8"))
        except OSError:
            return None
        return match.group(1) if match else None

    @staticmethod
    def _version_marker(directory: Path) -> str | None:
        for name in ("VERSION", "version.txt"):
            try:
                value = (directory / name).read_text(encoding="utf-8").strip()
            except OSError:
                continue
            if value:
                return value[:100]
        return None

    @staticmethod
    def _codex_version(directory: Path) -> str | None:
        marker = ToolRegistry._version_marker(directory)
        if marker:
            return marker
        metadata = directory / "release-latest.json"
        try:
            payload = json.loads(metadata.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        value = payload.get("name") or payload.get("tag_name")
        if not value:
            return None
        return str(value).removeprefix("rust-v")

    @staticmethod
    def _zotero_version(executable: Path) -> str | None:
        application_ini = executable.parent / "application.ini"
        try:
            for line in application_ini.read_text(encoding="utf-8").splitlines():
                if line.startswith("Version="):
                    return line.partition("=")[2].strip() or None
        except OSError:
            return None
        return None
