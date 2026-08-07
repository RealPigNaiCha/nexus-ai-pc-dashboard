from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import pickle
import threading
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from typing import Any, Protocol, Sequence

from .credentials import ApiCredentialStore, CredentialStorageError, normalize_provider
from .database import Database


# LiteLLM fetches a remote model-cost map at import time. Prefer the bundled map
# so PaperQA2 imports are fast and do not depend on GitHub availability.
os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "True")

logger = logging.getLogger("nexus.paperqa")

DEFAULT_EMBEDDING_MODEL = "BAAI/bge-small-zh-v1.5"
DEFAULT_EMBEDDING_DIMENSIONS = 512
SUPPORTED_PAPERQA_ROLES = ("reasoning", "fast")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class PaperQAError(RuntimeError):
    """Stable, detail-safe error raised by the PaperQA2 integration."""

    def __init__(self, code: str, detail: str, status_code: int) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail
        self.status_code = status_code


class PaperQAServiceProtocol(Protocol):
    def status(self) -> dict[str, object]: ...

    async def build_index(self, paths: Sequence[Path]) -> dict[str, object]: ...

    async def ask(
        self,
        question: str,
        role: str = "reasoning",
        max_tokens: int = 1024,
        temperature: float = 0.2,
    ) -> dict[str, object]: ...


PROVIDER_LITELLM_PREFIX = {
    "openai": "openai",
    "openai-compatible": "openai",
    "anthropic": "anthropic",
    "google-gemini": "gemini",
    "deepseek": "deepseek",
    "alibaba-bailian": "openai",
}


def _router_config(
    *,
    provider: str,
    model: str,
    endpoint: str,
    api_key: str,
    temperature: float,
    max_tokens: int,
    timeout_seconds: float,
) -> dict[str, Any]:
    prefix = PROVIDER_LITELLM_PREFIX.get(provider)
    if prefix is None:
        raise PaperQAError("unsupported_provider", "不支持的模型服务商", 422)
    litellm_params: dict[str, Any] = {
        "model": f"{prefix}/{model}",
        "api_key": api_key,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "timeout": timeout_seconds,
    }
    if provider in {"openai-compatible", "alibaba-bailian"}:
        litellm_params["api_base"] = endpoint
    return {
        "name": "ai-pc-paperqa",
        "model_list": [
            {
                "model_name": "ai-pc-paperqa",
                "litellm_params": litellm_params,
            }
        ],
        "router_kwargs": {"retry_after": 5},
    }


class FastEmbeddingModel:
    """Local fastembed-backed embedding model for PaperQA2."""

    name = f"fastembed/{DEFAULT_EMBEDDING_MODEL}"
    ndim: int | None = DEFAULT_EMBEDDING_DIMENSIONS
    config: dict[str, Any] = {}

    def __init__(self, *, model_name: str = DEFAULT_EMBEDDING_MODEL, cache_dir: str = "") -> None:
        self.model_name = model_name
        self.cache_dir = cache_dir
        self._embedder: Any = None
        self._lock = threading.Lock()

    def set_mode(self, mode: str) -> None:
        """No-op: fastembed uses a single document/query mode."""

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        vectors = await asyncio.to_thread(self._embed_sync, texts)
        return [[float(value) for value in vector] for vector in vectors]

    def _embed_sync(self, texts: list[str]) -> list[Any]:
        from fastembed import TextEmbedding

        with self._lock:
            if self._embedder is None:
                self._embedder = TextEmbedding(
                    model_name=self.model_name,
                    cache_dir=self.cache_dir or None,
                    lazy_load=True,
                )
            return list(self._embedder.embed(texts))


class PaperQAService:
    """PaperQA2 wrapper: local index snapshots plus LiteLLM-backed Q&A."""

    def __init__(
        self,
        *,
        database: Database,
        credential_store: ApiCredentialStore,
        index_root: Path | str,
        allowed_roots: Sequence[Path | str],
        embedding_model: Any | None = None,
        timeout_seconds: float = 120.0,
    ) -> None:
        self._database = database
        self._credential_store = credential_store
        self._index_root = Path(index_root) / "paperqa"
        self._allowed_roots = tuple(
            Path(root).expanduser().resolve(strict=False) for root in allowed_roots
        )
        self._timeout_seconds = float(timeout_seconds)
        self._embedding_model = embedding_model
        self._lock = asyncio.Lock()
        self._cache: dict[str, Any] = {}

    def status(self) -> dict[str, object]:
        role = self._role_status("reasoning")
        index = self._index_status()
        return {
            "ready": bool(role["ready"] and index["built"]),
            "llm": role,
            "index": index,
            "embedding": {
                "provider": "local",
                "model": DEFAULT_EMBEDDING_MODEL,
                "ready": True,
            },
            "index_path": str(self._index_root),
        }

    async def build_index(self, paths: Sequence[Path]) -> dict[str, object]:
        files = self._normalize_files(paths)
        if not files:
            raise PaperQAError("no_documents", "没有可索引的文档", 422)
        async with self._lock:
            started = perf_counter()
            try:
                await self._build_snapshot(files)
            except PaperQAError:
                raise
            except Exception as error:
                logger.warning("PaperQA index build failed: %s", type(error).__name__)
                raise PaperQAError("index_failed", "论文索引建立失败", 502) from error
            duration_ms = max(0, round((perf_counter() - started) * 1000))
        return {
            "status": "ok",
            "document_count": len(files),
            "files": [
                {"path": str(path), "docname": path.stem} for path in files
            ],
            "index_path": str(self._index_root),
            "latency_ms": duration_ms,
        }

    async def ask(
        self,
        question: str,
        role: str = "reasoning",
        max_tokens: int = 1024,
        temperature: float = 0.2,
    ) -> dict[str, object]:
        question = (question or "").strip()
        if not question:
            raise PaperQAError("invalid_question", "问题不能为空", 422)
        if role not in SUPPORTED_PAPERQA_ROLES:
            raise PaperQAError("unsupported_role", "该模型角色不支持论文问答", 422)

        config, provider, api_key = self._require_role(role)
        async with self._lock:
            index = self._index_status()
            if not index["built"]:
                raise PaperQAError("index_not_built", "请先建立论文索引", 409)
            manifest = self._load_manifest() or {}
            docs = self._load_docs()
            source_root = manifest.get("source_root") or str(self._index_root)
            llm_config = _router_config(
                provider=provider,
                model=config["model"],
                endpoint=config["endpoint"],
                api_key=api_key,
                temperature=temperature,
                max_tokens=max_tokens,
                timeout_seconds=self._timeout_seconds,
            )
            settings = self._make_settings(
                source_root=source_root,
                llm_config=llm_config,
            )
            llm_model = settings.get_llm()
            summary_llm_model = settings.get_summary_llm()
            embedding_model = self._get_embedding_model()
            # Do not keep the secret in the long-lived settings object.
            llm_config["model_list"][0]["litellm_params"]["api_key"] = ""

            started = perf_counter()
            try:
                session = await asyncio.wait_for(
                    docs.aquery(
                        question,
                        settings=settings,
                        llm_model=llm_model,
                        summary_llm_model=summary_llm_model,
                        embedding_model=embedding_model,
                    ),
                    timeout=self._timeout_seconds,
                )
            except asyncio.TimeoutError:
                raise PaperQAError("timeout", "论文问答超时，请稍后重试", 504) from None
            except Exception as error:
                raise self._map_upstream_error(error) from error
            duration_ms = max(0, round((perf_counter() - started) * 1000))

        sources: list[dict[str, object]] = []
        for context in session.contexts:
            sources.append(
                {
                    "citation": context.text.doc.formatted_citation,
                    "docname": context.text.name,
                    "text": context.text.text,
                    "score": context.score,
                }
            )
        prompt_tokens = sum(
            counts[0] for counts in session.token_counts.values() if counts
        )
        completion_tokens = sum(
            counts[1] for counts in session.token_counts.values() if counts
        )
        total_tokens = (
            prompt_tokens + completion_tokens
            if prompt_tokens or completion_tokens
            else None
        )
        return {
            "question": session.question,
            "answer": session.answer,
            "formatted_answer": session.formatted_answer,
            "context": session.context,
            "references": session.references,
            "sources": sources,
            "model": config["model"],
            "latency_ms": duration_ms,
            "prompt_tokens": prompt_tokens or None,
            "completion_tokens": completion_tokens or None,
            "total_tokens": total_tokens,
        }

    def _normalize_files(self, paths: Sequence[Path]) -> list[Path]:
        files: list[Path] = []
        for raw in paths:
            candidate = Path(raw).expanduser().resolve(strict=False)
            if not any(self._is_relative_to(candidate, root) for root in self._allowed_roots):
                raise PaperQAError("path_forbidden", "路径不在允许的库目录内", 403)
            if not candidate.is_file():
                raise PaperQAError("path_not_found", "文档不存在", 404)
            if candidate.suffix.lower() not in {".pdf", ".md", ".markdown", ".txt"}:
                raise PaperQAError("unsupported_document", "仅支持 PDF、Markdown 和 TXT", 422)
            files.append(candidate)
        unique: list[Path] = []
        for path in files:
            if path not in unique:
                unique.append(path)
        return unique

    async def _build_snapshot(self, files: list[Path]) -> None:
        from paperqa import Docs
        from paperqa.settings import AgentSettings, IndexSettings, ParsingSettings, Settings

        source_root = self._common_source_root(files)
        llm_config = self._fallback_llm_config()
        settings = Settings(
            llm="ai-pc-paperqa",
            llm_config=llm_config,
            summary_llm="ai-pc-paperqa",
            summary_llm_config=llm_config,
            embedding=f"fastembed/{DEFAULT_EMBEDDING_MODEL}",
            temperature=0.0,
            agent=AgentSettings(
                index=IndexSettings(
                    paper_directory=source_root,
                    index_directory=self._index_root,
                    use_absolute_paper_directory=True,
                    recurse_subdirectories=False,
                )
            ),
            parsing=ParsingSettings(use_doc_details=False),
        )
        llm_model = settings.get_llm()
        embedding_model = self._get_embedding_model()
        docs = Docs()
        for path in files:
            await docs.aadd(
                path=path,
                citation=path.stem,
                docname=path.stem,
                title=path.stem,
                settings=settings,
                llm_model=llm_model,
                embedding_model=embedding_model,
            )
        self._save_snapshot(docs, files, source_root)
        self._cache = {"files": tuple(str(path) for path in files), "docs": docs}

    def _fallback_llm_config(self) -> dict[str, Any]:
        """Config for indexing only: no network call is made while indexing."""
        return {
            "name": "ai-pc-paperqa",
            "model_list": [
                {
                    "model_name": "ai-pc-paperqa",
                    "litellm_params": {
                        "model": "gpt-4o-mini",
                        "temperature": 0.0,
                        "max_tokens": 1024,
                    },
                }
            ],
            "router_kwargs": {"retry_after": 5},
        }

    def _make_settings(self, *, source_root: str, llm_config: dict[str, Any]):
        from paperqa.settings import AgentSettings, IndexSettings, ParsingSettings, Settings

        return Settings(
            llm="ai-pc-paperqa",
            llm_config=llm_config,
            summary_llm="ai-pc-paperqa",
            summary_llm_config=llm_config,
            embedding=f"fastembed/{DEFAULT_EMBEDDING_MODEL}",
            temperature=0.0,
            agent=AgentSettings(
                index=IndexSettings(
                    paper_directory=Path(source_root),
                    index_directory=self._index_root,
                    use_absolute_paper_directory=True,
                    recurse_subdirectories=False,
                )
            ),
            parsing=ParsingSettings(use_doc_details=False),
        )

    def _save_snapshot(
        self,
        docs: Any,
        files: list[Path],
        source_root: Path,
    ) -> None:
        self._index_root.mkdir(parents=True, exist_ok=True)
        manifest = {
            "version": 1,
            "built_at": utc_now(),
            "source_root": str(source_root),
            "files": [
                {
                    "path": str(path),
                    "sha256": self._file_sha256(path),
                    "docname": path.stem,
                }
                for path in files
            ],
        }
        docs_tmp = self._index_root / "docs.pkl.tmp"
        manifest_tmp = self._index_root / "manifest.json.tmp"
        with open(docs_tmp, "wb") as handle:
            pickle.dump(docs, handle, protocol=pickle.HIGHEST_PROTOCOL)
        docs_tmp.replace(self._index_root / "docs.pkl")
        manifest_tmp.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        manifest_tmp.replace(self._index_root / "manifest.json")

    def _load_docs(self) -> Any:
        from paperqa import Docs

        manifest = self._load_manifest() or {}
        manifest_files = tuple(item["path"] for item in manifest.get("files", []))
        cached = self._cache.get("docs")
        if cached is not None and self._cache.get("files") == manifest_files:
            return cached
        docs_path = self._index_root / "docs.pkl"
        if not docs_path.is_file():
            raise PaperQAError("index_not_built", "请先建立论文索引", 409)
        try:
            with open(docs_path, "rb") as handle:
                docs = pickle.load(handle)
        except Exception:
            raise PaperQAError("index_corrupt", "论文索引已损坏，请重新建立", 503) from None
        if not isinstance(docs, Docs):
            raise PaperQAError("index_corrupt", "论文索引已损坏，请重新建立", 503)
        self._cache = {"files": manifest_files, "docs": docs}
        return docs

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

    def _require_role(
        self, role: str
    ) -> tuple[dict[str, str], str, str]:
        roles = {item["role"]: item for item in self._database.get_model_roles()}
        config = roles.get(role)
        provider = normalize_provider(config.get("provider", "")) if config else None
        if not config or not config.get("model") or provider is None:
            raise PaperQAError("role_not_configured", "该模型角色尚未配置", 409)
        try:
            api_key = self._credential_store.get(provider)
        except CredentialStorageError:
            raise PaperQAError(
                "credential_store_unavailable", "凭据存储不可用", 503
            ) from None
        if api_key is None:
            raise PaperQAError("credential_missing", "该模型角色缺少 API 密钥", 409)
        return config, provider, api_key

    def _index_status(self) -> dict[str, object]:
        manifest = self._load_manifest()
        files = manifest.get("files", []) if manifest else []
        return {
            "built": bool(manifest),
            "document_count": len(files),
            "built_at": manifest.get("built_at") if manifest else None,
            "files": [
                {
                    "path": item.get("path", ""),
                    "docname": item.get("docname", Path(item.get("path", "")).stem),
                }
                for item in files
            ],
        }

    def _load_manifest(self) -> dict[str, Any] | None:
        manifest_path = self._index_root / "manifest.json"
        if not manifest_path.is_file():
            return None
        try:
            return json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def _get_embedding_model(self) -> Any:
        if self._embedding_model is not None:
            return self._embedding_model
        cache_dir = self._index_root.parent / "models"
        return FastEmbeddingModel(cache_dir=str(cache_dir))

    def _map_upstream_error(self, error: Exception) -> PaperQAError:
        name = type(error).__name__
        if "RateLimit" in name:
            return PaperQAError("rate_limited", "模型服务配额或速率受限", 429)
        if "Authentication" in name or "PermissionDenied" in name:
            return PaperQAError(
                "authentication_failed", "模型服务拒绝了凭据", 401
            )
        if "Timeout" in name:
            return PaperQAError("timeout", "模型服务响应超时", 504)
        if (
            "APIConnection" in name
            or "ConnectionError" in name
            or "ServiceUnavailable" in name
        ):
            return PaperQAError("network_error", "模型服务不可用", 502)
        logger.warning("PaperQA ask failed: %s", name)
        return PaperQAError("upstream_error", "论文问答调用失败", 502)

    @staticmethod
    def _file_sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with open(path, "rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(block)
        return digest.hexdigest()

    @staticmethod
    def _common_source_root(files: Sequence[Path]) -> Path:
        if len(files) == 1:
            return files[0].parent
        common = os.path.commonpath([str(path.parent) for path in files])
        return Path(common)

    @staticmethod
    def _is_relative_to(path: Path, root: Path) -> bool:
        try:
            path.relative_to(root)
            return True
        except ValueError:
            return False
