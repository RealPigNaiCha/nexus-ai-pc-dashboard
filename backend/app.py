from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shutil
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta, timezone
from ipaddress import ip_address
from pathlib import Path
from typing import Literal, Sequence
from urllib.parse import urlsplit
from uuid import uuid4

import httpx
from fastapi import FastAPI, HTTPException, Query, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, HttpUrl, SecretStr

from .agent import AgentHandoff, AgentHandoffError
from .browser import (
    BrowserController,
    BrowserError,
    BrowserExecutor,
    PlaywrightExecutor,
)
from .credentials import (
    SUPPORTED_PROVIDERS,
    ApiCredentialStore,
    CredentialStorageError,
    KeyringBackend,
    normalize_provider,
)
from .database import Database, utc_now
from .deeptutor import DeepTutorError, DeepTutorService
from .learning import review_concept
from .library import discover_source_files, parse_document, resolve_source_path
from .model_gateway import (
    MODEL_ROLES,
    ModelGateway,
    ModelGatewayError,
    ModelProbeCancelled,
    ModelRequestCancelled,
    build_chat_url,
    build_probe_url,
)
from .ops import (
    DEFAULT_BACKUP_ENABLED,
    DEFAULT_BACKUP_INTERVAL_HOURS,
    DEFAULT_BACKUP_KEEP_COUNT,
    MAX_KEEP_COUNT,
    MAX_INTERVAL_HOURS,
    MIN_KEEP_COUNT,
    MIN_INTERVAL_HOURS,
    read_backup_settings,
    run_auto_backup,
    save_backup_settings,
)
from .paperqa import (
    SUPPORTED_PAPERQA_ROLES,
    PaperQAError,
    PaperQAService,
)
from .research import LiteratureClient, ResearchUpstreamError
from .semantic import (
    DEFAULT_COLLECTION_NAME,
    DEFAULT_MODEL_NAME,
    DEGRADED_REASON,
    SemanticChunk,
    SemanticDocument,
    SemanticIndex,
)
from .tooling import ToolRegistry
from .zotero import ZoteroReader, ZoteroReadError


PROJECT_DIR = Path(__file__).resolve().parents[1]
logger = logging.getLogger("nexus.app")


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class DocumentCreate(StrictModel):
    title: str = Field(min_length=1, max_length=300)
    document_type: str = Field(min_length=1, max_length=24)
    location: str | None = Field(default=None, max_length=1000)
    source: str | None = Field(default=None, max_length=300)


class LibraryImportRequest(StrictModel):
    path: str = Field(min_length=1, max_length=32_000)


class LearningAttemptCreate(StrictModel):
    concept_id: int = Field(gt=0)
    score: float = Field(ge=0, le=1)
    prompt: str | None = Field(default=None, max_length=2000)
    answer: str | None = Field(default=None, max_length=20_000)
    feedback: str | None = Field(default=None, max_length=10_000)
    confidence: float | None = Field(default=None, ge=0, le=1)
    duration_seconds: int | None = Field(default=None, ge=0, le=86_400)
    hints_used: int = Field(default=0, ge=0, le=100)


class LearningCourseCreate(StrictModel):
    title: str = Field(min_length=1, max_length=200)
    goal: str = Field(min_length=1, max_length=2000)
    target_date: date | None = None


class LearningConceptCreate(StrictModel):
    course_id: int = Field(gt=0)
    name: str = Field(min_length=1, max_length=200)
    description: str | None = Field(default=None, max_length=4000)
    prerequisite_ids: list[int] = Field(default_factory=list, max_length=50)


class ResearchProjectCreate(StrictModel):
    name: str = Field(min_length=1, max_length=200)
    question: str = Field(min_length=1, max_length=2000)
    research_type: str = Field(min_length=1, max_length=100)


class ResearchNoteCreate(StrictModel):
    body: str = Field(min_length=1, max_length=100_000)


class ResearchSearchCreate(StrictModel):
    query: str = Field(min_length=1, max_length=500)
    limit: int = Field(default=10, ge=1, le=50)


class ResearchScreeningUpdate(StrictModel):
    decision: Literal["include", "exclude", "maybe"]
    reason: str | None = Field(default=None, max_length=4000)


class AgentTaskCreate(StrictModel):
    project: str = Field(min_length=1, max_length=200)
    title: str = Field(min_length=1, max_length=2000)
    run_tests: bool = True
    generate_summary: bool = True
    allow_dependencies: bool = False


class SettingsUpdate(StrictModel):
    provider: str = Field(min_length=1, max_length=100)
    endpoint: HttpUrl
    data_path: str = Field(max_length=1000)


class BackupSettingsUpdate(StrictModel):
    enabled: bool = True
    interval_hours: int = Field(
        default=DEFAULT_BACKUP_INTERVAL_HOURS,
        ge=MIN_INTERVAL_HOURS,
        le=MAX_INTERVAL_HOURS,
    )
    keep_count: int = Field(
        default=DEFAULT_BACKUP_KEEP_COUNT,
        ge=MIN_KEEP_COUNT,
        le=MAX_KEEP_COUNT,
    )


class CredentialUpdate(StrictModel):
    api_key: SecretStr = Field(min_length=1, max_length=8_192)


class ModelConnectionTestRequest(StrictModel):
    provider: str = Field(min_length=1, max_length=100)
    endpoint: HttpUrl


class ModelRoleUpdate(StrictModel):
    provider: str = Field(min_length=1, max_length=100)
    model: str = Field(min_length=1, max_length=200)
    endpoint: HttpUrl


class ModelGenerateRequest(StrictModel):
    role: str = Field(min_length=1, max_length=32)
    prompt: str = Field(min_length=1, max_length=20_000)
    system: str | None = Field(default=None, max_length=10_000)
    max_tokens: int = Field(default=1024, ge=1, le=8192)
    temperature: float = Field(default=0.2, ge=0, le=2)


class ChatAskRequest(StrictModel):
    question: str = Field(min_length=1, max_length=2000)
    role: str = Field(default="reasoning", min_length=1, max_length=32)
    scope: Literal["all", "library", "learning"] = "all"
    course_id: int | None = Field(default=None, gt=0)
    max_tokens: int = Field(default=1024, ge=1, le=8192)
    temperature: float = Field(default=0.2, ge=0, le=2)


class OpenAIChatMessage(StrictModel):
    role: str = Field(min_length=1, max_length=32)
    content: str | list[dict[str, object]] = Field(default="")


class OpenAIChatRequest(StrictModel):
    model: str = Field(default="reasoning", min_length=1, max_length=200)
    messages: list[OpenAIChatMessage] = Field(min_length=1, max_length=200)
    stream: bool = False
    max_tokens: int | None = Field(default=None, ge=1, le=8192)
    temperature: float | None = Field(default=None, ge=0, le=2)


class BrowserActionCreate(StrictModel):
    action: Literal["open", "click", "type", "snapshot", "close"]
    url: str | None = Field(default=None, max_length=2000)
    selector: str | None = Field(default=None, max_length=500)
    text: str | None = Field(default=None, max_length=2000)
    timeout_ms: int = Field(default=15_000, ge=1_000, le=120_000)


class BrowserAllowlistUpdate(StrictModel):
    domains: list[str] = Field(default_factory=list, max_length=50)


class PaperQAIndexRequest(StrictModel):
    path: str = Field(min_length=1, max_length=32_000)
    role: str = Field(default="reasoning", min_length=1, max_length=32)


class PaperQAAskRequest(StrictModel):
    question: str = Field(min_length=1, max_length=2000)
    role: str = Field(default="reasoning", min_length=1, max_length=32)
    max_tokens: int = Field(default=1024, ge=1, le=8192)
    temperature: float = Field(default=0.2, ge=0, le=2)


class DeepTutorRunRequest(StrictModel):
    capability: str = Field(default="chat", min_length=1, max_length=64)
    prompt: str = Field(min_length=1, max_length=4000)
    role: str = Field(default="reasoning", min_length=1, max_length=32)
    language: str = Field(default="zh", min_length=2, max_length=16)
    session_id: str | None = Field(default=None, max_length=128)
    timeout_seconds: int = Field(default=300, ge=10, le=600)


def concept_trend(database: Database, concept_id: int) -> str:
    attempts = database.query_all(
        "SELECT score FROM learning_attempts WHERE concept_id = ? ORDER BY id DESC LIMIT 2",
        (concept_id,),
    )
    if not attempts:
        return "new"
    if len(attempts) == 1:
        return "started"
    earlier = float(attempts[-1]["score"])
    latest = float(attempts[0]["score"])
    if latest - earlier >= 0.05:
        return "improving"
    if earlier - latest >= 0.05:
        return "declining"
    return "stable"


def create_app(
    database_path: Path | None = None,
    serve_static: bool = True,
    allowed_library_roots: Sequence[Path] | None = None,
    credential_backend: KeyringBackend | None = None,
    research_transport: httpx.BaseTransport | None = None,
    model_transport: httpx.AsyncBaseTransport | None = None,
    semantic_index: SemanticIndex | None = None,
    agent_handoff: AgentHandoff | None = None,
    tool_registry: ToolRegistry | None = None,
    zotero_database: Path | None = None,
    zotero_auto_sync_hours: float = 6.0,
    browser_executor: BrowserExecutor | None = None,
    browser_controller: BrowserController | None = None,
    paperqa_service: PaperQAService | None = None,
    deeptutor_service: DeepTutorService | None = None,
) -> FastAPI:
    configured_path = os.getenv("AI_PC_DB_PATH")
    db_path = database_path or (Path(configured_path) if configured_path else PROJECT_DIR / "data" / "ai-pc.sqlite3")
    database = Database(db_path)
    credential_store = ApiCredentialStore(credential_backend)
    model_gateway = ModelGateway(credential_store, transport=model_transport)
    storage_root = db_path.parent if database_path is not None else Path(os.getenv("AI_PC_ROOT", r"C:\AI-PC"))
    library_roots = tuple(
        allowed_library_roots
        if allowed_library_roots is not None
        else (Path(r"C:\AI-PC\data\library"), Path(r"C:\AI-PC\vault"))
    )
    index_root = Path(os.getenv("AI_PC_INDEX_PATH", str(storage_root / "data" / "index")))
    owns_semantic_index = semantic_index is None and database_path is None
    agent_workspace_root = storage_root / "workspaces"
    agent_workspace = Path(
        os.getenv("AI_PC_AGENT_WORKSPACE", str(agent_workspace_root / "ai-pc-dashboard"))
    )
    agent_task_root = Path(
        os.getenv("AI_PC_AGENT_TASK_ROOT", str(storage_root / "data" / "agent" / "tasks"))
    )
    active_zotero_database = zotero_database or Path(
        os.getenv("AI_PC_ZOTERO_DB", str(storage_root / "data" / "zotero" / "zotero.sqlite"))
    )
    zotero_auto_sync = database_path is None and active_zotero_database.is_file()
    auto_backup_enabled = database_path is None
    active_agent_handoff = agent_handoff or AgentHandoff(
        agent_workspace,
        agent_task_root,
        allowed_workspace_root=agent_workspace_root,
    )
    active_tool_registry = tool_registry or ToolRegistry(storage_root, active_agent_handoff)
    active_browser_executor = browser_executor or PlaywrightExecutor()
    active_browser_controller = browser_controller or BrowserController(
        active_browser_executor,
        database,
        audit=database.audit,
    )
    active_paperqa_service = paperqa_service or PaperQAService(
        database=database,
        credential_store=credential_store,
        index_root=index_root,
        allowed_roots=library_roots,
    )
    active_deeptutor_service = deeptutor_service or DeepTutorService(
        database=database,
        credential_store=credential_store,
        auto_bootstrap=database_path is None,
    )

    def run_zotero_sync(database: Database) -> dict[str, object]:
        try:
            snapshot = ZoteroReader(active_zotero_database).snapshot()
        except ZoteroReadError as error:
            database.save_zotero_sync(
                items=[],
                collection_count=0,
                attachment_count=0,
                status="error",
                error=str(error),
                replace_items=False,
            )
            database.audit("zotero", "sync", None, result="error")
            raise
        record = database.save_zotero_sync(
            items=snapshot.items,
            collection_count=len(snapshot.collections),
            attachment_count=snapshot.attachment_count,
        )
        database.audit("zotero", "sync", str(record["id"]))
        return {
            "status": record["status"],
            "sync_id": record["id"],
            "items": record["item_count"],
            "collections": record["collection_count"],
            "attachments": record["attachment_count"],
        }

    async def zotero_auto_sync_loop(database: Database) -> None:
        interval_seconds = max(60.0, zotero_auto_sync_hours * 3600)
        while True:
            await asyncio.sleep(interval_seconds)
            try:
                await asyncio.to_thread(run_zotero_sync, database)
            except ZoteroReadError:
                logger.warning("Zotero automatic sync failed; snapshot preserved")
            except Exception:
                logger.exception("Zotero automatic sync failed")

    async def auto_backup_loop(database: Database) -> None:
        while True:
            settings = read_backup_settings(database)
            interval_seconds = max(
                300.0,
                float(settings.get("interval_hours") or DEFAULT_BACKUP_INTERVAL_HOURS) * 3600,
            )
            await asyncio.sleep(interval_seconds)
            if not read_backup_settings(database).get("enabled", True):
                continue
            try:
                await asyncio.to_thread(run_auto_backup, database, storage_root)
            except Exception:
                logger.exception("Automatic backup failed")

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        literature_client = LiteratureClient(transport=research_transport)
        active_semantic_index = semantic_index
        if owns_semantic_index:
            active_semantic_index = SemanticIndex(
                storage_path=index_root / "qdrant",
                model_cache_path=index_root / "models",
            )
        try:
            database.initialize()
            app.state.database = database
            app.state.credential_store = credential_store
            app.state.model_gateway = model_gateway
            app.state.literature_client = literature_client
            app.state.semantic_index = active_semantic_index
            app.state.agent_handoff = active_agent_handoff
            app.state.tool_registry = active_tool_registry
            app.state.paperqa_service = active_paperqa_service
            auto_sync_task: asyncio.Task[None] | None = None
            backup_task: asyncio.Task[None] | None = None
            if zotero_auto_sync:
                auto_sync_task = asyncio.create_task(zotero_auto_sync_loop(database))
            if auto_backup_enabled:
                backup_task = asyncio.create_task(auto_backup_loop(database))
            yield
        finally:
            if backup_task is not None:
                backup_task.cancel()
                try:
                    await backup_task
                except asyncio.CancelledError:
                    pass
            if auto_sync_task is not None:
                auto_sync_task.cancel()
                try:
                    await auto_sync_task
                except asyncio.CancelledError:
                    pass
            literature_client.close()
            await model_gateway.close()
            if owns_semantic_index and active_semantic_index is not None:
                active_semantic_index.close()

    app = FastAPI(
        title="Nexus AI-PC API",
        version="0.1.0",
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://127.0.0.1:3000",
            "http://localhost:3000",
        ],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.exception_handler(RequestValidationError)
    async def sanitized_validation_error(_request: Request, error: RequestValidationError) -> JSONResponse:
        details = [
            {
                "type": item.get("type", "validation_error"),
                "loc": item.get("loc", ()),
                "msg": "Invalid input",
            }
            for item in error.errors()
        ]
        return JSONResponse(status_code=422, content={"detail": details})

    def db(request: Request) -> Database:
        return request.app.state.database

    def research_client(request: Request) -> LiteratureClient:
        return request.app.state.literature_client

    def credential_provider(provider: str) -> str:
        canonical = normalize_provider(provider)
        if canonical is None:
            raise HTTPException(status_code=422, detail="Unsupported credential provider")
        return canonical

    def is_credential_configured(provider: str) -> bool:
        try:
            return credential_store.is_configured(provider)
        except CredentialStorageError:
            raise HTTPException(status_code=503, detail="Credential storage is unavailable") from None

    def paperqa_provider_for_role(request: Request, role: str) -> tuple[str, str | None]:
        config = next(
            (
                item
                for item in db(request).get_model_roles()
                if item["role"] == role
            ),
            None,
        )
        provider = (
            normalize_provider(config["provider"])
            if config and config.get("provider")
            else None
        )
        return (provider or "unconfigured"), (config.get("model") if config else None)

    def is_loopback_host(host: str | None) -> bool:
        if not host:
            return False
        if host.lower() == "localhost":
            return True
        try:
            return ip_address(host).is_loopback
        except ValueError:
            return False

    def origin_identity(value: str) -> tuple[str, str, int] | None:
        parsed = urlsplit(value)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            return None
        try:
            port = parsed.port or (443 if parsed.scheme == "https" else 80)
        except ValueError:
            return None
        return parsed.scheme, parsed.hostname.lower(), port

    def require_local_same_origin_handoff(request: Request) -> None:
        if request.headers.get("x-ai-pc-action") != "agent-handoff":
            raise HTTPException(status_code=403, detail="Agent handoff request was rejected")
        if not is_loopback_host(request.url.hostname):
            raise HTTPException(status_code=403, detail="Agent handoff request was rejected")
        request_origin = origin_identity(str(request.base_url).rstrip("/"))
        supplied_origin = origin_identity(request.headers.get("origin", ""))
        if request_origin is None or supplied_origin != request_origin:
            raise HTTPException(status_code=403, detail="Agent handoff request was rejected")
        fetch_site = request.headers.get("sec-fetch-site")
        if fetch_site and fetch_site not in {"same-origin", "none"}:
            raise HTTPException(status_code=403, detail="Agent handoff request was rejected")

    @app.get("/api/health")
    def health(request: Request) -> dict:
        database = db(request)
        return {
            "status": "ok" if database.health() else "degraded",
            "version": app.version,
            "database": "ok" if database.health() else "error",
            "local_only": True,
        }

    @app.get("/api/overview")
    def overview(request: Request) -> dict:
        database = db(request)
        counts = database.query_one(
            """
            SELECT
                (SELECT COUNT(*) FROM documents) AS documents,
                (SELECT COUNT(*) FROM research_projects) AS research_projects,
                (
                    SELECT COUNT(*) FROM agent_tasks
                    WHERE status IN ('queued', 'handoff_pending', 'handoff_requested')
                ) AS active_agent_tasks,
                (SELECT ROUND(AVG(mastery), 1) FROM learning_concepts) AS learning_mastery
            """
        )
        result = counts or {}
        usage = shutil.disk_usage(storage_root)
        result.update(
            {
                "storage_total_bytes": usage.total,
                "storage_used_bytes": usage.used,
                "storage_free_bytes": usage.free,
                "storage_root": str(storage_root),
            }
        )
        return result

    @app.get("/api/tools")
    def list_tools() -> dict[str, list[dict[str, object]]]:
        return {"tools": active_tool_registry.list_tools(app.version)}

    @app.get("/api/library/documents")
    def list_documents(
        request: Request,
        search: str = Query(default="", max_length=200),
        document_type: str | None = Query(default=None, max_length=24),
        document_status: str | None = Query(default=None, max_length=24),
    ) -> list[dict]:
        database = db(request)
        conditions: list[str] = []
        parameters: list[object] = []
        if search:
            conditions.append("(title LIKE ? OR source LIKE ?)")
            value = f"%{search}%"
            parameters.extend([value, value])
        if document_type:
            conditions.append("document_type = ?")
            parameters.append(document_type)
        if document_status:
            conditions.append("status = ?")
            parameters.append(document_status)
        where = f" WHERE {' AND '.join(conditions)}" if conditions else ""
        return database.query_all(f"SELECT * FROM documents{where} ORDER BY updated_at DESC, id DESC", tuple(parameters))

    @app.post("/api/library/documents", status_code=status.HTTP_201_CREATED)
    def create_document(payload: DocumentCreate, request: Request) -> dict:
        database = db(request)
        now = utc_now()
        document_id = database.execute(
            """
            INSERT INTO documents(title, document_type, status, location, source, created_at, updated_at)
            VALUES (?, ?, 'pending', ?, ?, ?, ?)
            """,
            (payload.title, payload.document_type.upper(), payload.location, payload.source, now, now),
        )
        database.audit("library", "create_document", str(document_id))
        return database.query_one("SELECT * FROM documents WHERE id = ?", (document_id,)) or {}

    @app.post("/api/library/import", status_code=status.HTTP_201_CREATED)
    def import_library_document(payload: LibraryImportRequest, request: Request) -> dict:
        try:
            source_path = resolve_source_path(payload.path, library_roots)
            source_files = discover_source_files(source_path, library_roots)
        except PermissionError as error:
            raise HTTPException(status_code=403, detail=str(error)) from error
        except FileNotFoundError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error

        database = db(request)
        indexed: list[dict] = []
        errors: list[dict[str, str]] = []
        total_chunks = 0
        changed_count = 0
        semantic_chunks = 0
        semantic_documents = 0
        semantic_degraded = False
        active_semantic_index = getattr(request.app.state, "semantic_index", None)
        for candidate in source_files:
            try:
                parsed = parse_document(candidate)
                document, chunks_indexed, changed = database.import_document(
                    title=parsed.title,
                    document_type=parsed.document_type,
                    source_path=parsed.source_path,
                    content_hash=parsed.content_hash,
                    file_size=parsed.file_size,
                    chunks=parsed.chunks,
                )
            except (OSError, ValueError) as error:
                errors.append({"path": str(candidate), "detail": str(error)})
                continue

            database.audit(
                "library",
                "index_document" if changed else "reuse_document",
                str(document["id"]),
            )
            indexed.append(document)
            total_chunks += chunks_indexed
            changed_count += int(changed)
            if changed and active_semantic_index is not None:
                try:
                    semantic_result = active_semantic_index.index_document(
                        SemanticDocument(
                            document_id=int(document["id"]),
                            title=str(document["title"]),
                            source_path=document.get("source_path"),
                            metadata={"document_type": document.get("document_type")},
                            chunks=[
                                SemanticChunk(
                                    chunk_id=ordinal,
                                    page=page_number,
                                    paragraph=paragraph_number,
                                    text=content,
                                )
                                for ordinal, page_number, paragraph_number, content in parsed.chunks
                            ],
                        )
                    )
                    semantic_chunks += int(semantic_result.chunks_indexed)
                    semantic_documents += int(semantic_result.success)
                    semantic_degraded = semantic_degraded or bool(semantic_result.degraded)
                except Exception:
                    semantic_degraded = True
                database.audit(
                    "library",
                    "semantic_index" if not semantic_degraded else "semantic_fallback",
                    str(document["id"]),
                    "success" if not semantic_degraded else "degraded",
                )

        if not indexed:
            detail = errors[0]["detail"] if errors else "No documents were indexed"
            raise HTTPException(status_code=422, detail=detail)

        if source_path.is_file():
            document = indexed[0]
            return {
                "document": document,
                "chunks_indexed": total_chunks,
                "changed": changed_count == 1,
                "semantic_documents_indexed": semantic_documents,
                "semantic_chunks_indexed": semantic_chunks,
                "semantic_degraded": semantic_degraded,
            }

        return {
            "documents": indexed,
            "documents_seen": len(source_files),
            "imported_count": changed_count,
            "reused_count": len(indexed) - changed_count,
            "failed_count": len(errors),
            "chunks_indexed": total_chunks,
            "changed": changed_count > 0,
            "semantic_documents_indexed": semantic_documents,
            "semantic_chunks_indexed": semantic_chunks,
            "semantic_degraded": semantic_degraded,
            "errors": errors,
        }

    def lexical_search(database: Database, query: str, limit: int) -> list[dict]:
        results = database.search_document_chunks(query, limit)
        for result in results:
            result["search_mode"] = "lexical"
            result["semantic_score"] = None
            result["semantic_degraded"] = False
        return results

    def semantic_search(request: Request, query: str, limit: int) -> tuple[list[dict], bool]:
        active_semantic_index = getattr(request.app.state, "semantic_index", None)
        if active_semantic_index is None:
            return [], True
        result = active_semantic_index.search(query, limit=limit)
        if result.degraded:
            return [], True
        hits = []
        for hit in result.hits:
            hits.append(
                {
                    "document_id": hit.document_id,
                    "title": hit.title,
                    "document_type": hit.metadata.get("document_type"),
                    "source_path": hit.source_path,
                    "page": hit.page,
                    "paragraph": hit.paragraph,
                    "chunk_index": hit.chunk_id,
                    "chunk": hit.text,
                    "snippet": hit.text,
                    "search_mode": "semantic",
                    "semantic_score": round(hit.score, 6),
                    "semantic_degraded": False,
                }
            )
        return hits, False

    def fuse_results(lexical_results: list[dict], semantic_results: list[dict], limit: int) -> list[dict]:
        fused: dict[tuple[int, object], dict] = {}
        for source, results in (("lexical", lexical_results), ("semantic", semantic_results)):
            for rank, result in enumerate(results, start=1):
                key = (int(result["document_id"]), result["chunk_index"])
                existing = fused.get(key)
                if existing is None:
                    existing = dict(result)
                    existing["_fusion_score"] = 0.0
                    fused[key] = existing
                elif source == "semantic":
                    existing["semantic_score"] = result["semantic_score"]
                existing["_fusion_score"] += 1.0 / (60 + rank)

        ordered = sorted(
            fused.values(),
            key=lambda item: (-float(item["_fusion_score"]), int(item["document_id"]), str(item["chunk_index"])),
        )[:limit]
        for result in ordered:
            result.pop("_fusion_score", None)
            result["search_mode"] = "hybrid"
        return ordered

    @app.get("/api/library/search")
    def search_library(
        request: Request,
        q: str = Query(min_length=1, max_length=500),
        limit: int = Query(default=20, ge=1, le=100),
        mode: Literal["lexical", "semantic", "hybrid"] = "hybrid",
    ) -> list[dict]:
        query = q.strip()
        database = db(request)
        if mode == "lexical":
            return lexical_search(database, query, limit)

        semantic_results, degraded = semantic_search(request, query, limit)
        if mode == "semantic" and not degraded:
            return semantic_results
        if degraded:
            fallback = lexical_search(database, query, limit)
            for result in fallback:
                result["semantic_degraded"] = True
            return fallback

        lexical_results = lexical_search(database, query, limit)
        return fuse_results(lexical_results, semantic_results, limit)

    @app.get("/api/library/semantic/status")
    def semantic_index_status(request: Request) -> dict:
        active_semantic_index = getattr(request.app.state, "semantic_index", None)
        if active_semantic_index is None:
            return {
                "available": False,
                "degraded": True,
                "model_name": DEFAULT_MODEL_NAME,
                "collection_name": DEFAULT_COLLECTION_NAME,
                "storage_path": str(index_root / "qdrant"),
                "point_count": None,
                "reason": DEGRADED_REASON,
            }
        semantic_status = active_semantic_index.status()
        return {
            "available": semantic_status.available,
            "degraded": semantic_status.degraded,
            "model_name": semantic_status.model_name,
            "collection_name": semantic_status.collection_name,
            "storage_path": semantic_status.storage_path,
            "point_count": semantic_status.point_count,
            "reason": semantic_status.reason,
        }

    @app.post("/api/library/semantic/rebuild")
    def rebuild_semantic_index(request: Request) -> dict:
        database = db(request)
        active_semantic_index = getattr(request.app.state, "semantic_index", None)
        if active_semantic_index is None:
            raise HTTPException(status_code=503, detail=DEGRADED_REASON)

        semantic_documents: list[SemanticDocument] = []
        for document in database.query_all(
            "SELECT id, title, document_type, source_path FROM documents WHERE status = 'ready' ORDER BY id"
        ):
            chunks = database.query_all(
                """
                SELECT ordinal, page_number, paragraph_number, content
                FROM document_chunks WHERE document_id = ? ORDER BY ordinal
                """,
                (document["id"],),
            )
            semantic_documents.append(
                SemanticDocument(
                    document_id=int(document["id"]),
                    title=str(document["title"]),
                    source_path=document.get("source_path"),
                    metadata={"document_type": document.get("document_type")},
                    chunks=[
                        SemanticChunk(
                            chunk_id=chunk["ordinal"],
                            page=chunk["page_number"],
                            paragraph=chunk["paragraph_number"],
                            text=chunk["content"],
                        )
                        for chunk in chunks
                    ],
                )
            )
        result = active_semantic_index.rebuild(semantic_documents)
        database.audit(
            "library",
            "semantic_rebuild",
            str(result.documents_processed),
            "success" if result.success else "degraded",
        )
        if not result.success:
            raise HTTPException(status_code=503, detail=result.reason or DEGRADED_REASON)
        return {
            "success": result.success,
            "documents_processed": result.documents_processed,
            "chunks_indexed": result.chunks_indexed,
            "degraded": result.degraded,
        }

    @app.get("/api/learning/courses")
    def list_learning_courses(request: Request) -> list[dict]:
        return db(request).query_all(
            """
            SELECT
                course.*,
                COUNT(concept.id) AS concept_count,
                ROUND(AVG(concept.mastery), 1) AS mastery
            FROM learning_courses AS course
            LEFT JOIN learning_concepts AS concept ON concept.course_id = course.id
            GROUP BY course.id
            ORDER BY course.status = 'active' DESC, course.updated_at DESC, course.id DESC
            """
        )

    @app.post("/api/learning/courses", status_code=status.HTTP_201_CREATED)
    def create_learning_course(payload: LearningCourseCreate, request: Request) -> dict:
        database = db(request)
        try:
            course = database.create_learning_course(
                title=payload.title,
                goal=payload.goal,
                target_date=payload.target_date.isoformat() if payload.target_date else None,
            )
        except ValueError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        database.audit("learning", "create_course", str(course["id"]))
        return course

    @app.post("/api/learning/concepts", status_code=status.HTTP_201_CREATED)
    def create_learning_concept(payload: LearningConceptCreate, request: Request) -> dict:
        database = db(request)
        try:
            concept = database.create_learning_concept(
                course_id=payload.course_id,
                name=payload.name,
                description=payload.description,
                prerequisite_ids=payload.prerequisite_ids,
            )
        except LookupError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        except ValueError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        database.audit("learning", "create_concept", str(concept["id"]))
        concept.pop("fsrs_card_json", None)
        return concept

    @app.get("/api/learning/progress")
    def learning_progress(
        request: Request,
        course_id: int | None = Query(default=None, gt=0),
    ) -> list[dict]:
        where = "WHERE concept.course_id = ?" if course_id is not None else ""
        parameters = (course_id,) if course_id is not None else ()
        return db(request).query_all(
            f"""
            SELECT
                concept.id, concept.course_id, course.title AS course_title,
                concept.name, concept.description, concept.mastery, concept.status,
                concept.attempt_count, concept.last_score, concept.due_at,
                concept.created_at, concept.updated_at
            FROM learning_concepts AS concept
            LEFT JOIN learning_courses AS course ON course.id = concept.course_id
            {where}
            ORDER BY concept.course_id, concept.id
            """,
            parameters,
        )

    @app.get("/api/learning/dashboard")
    def learning_dashboard(
        request: Request,
        course_id: int | None = Query(default=None, gt=0),
    ) -> dict:
        database = db(request)
        courses = list_learning_courses(request)
        concepts = learning_progress(request, course_id)
        now = utc_now()
        scoped_ids = [concept["id"] for concept in concepts]
        due = [concept for concept in concepts if concept.get("due_at") and concept["due_at"] <= now]
        next_concept = (due or [concept for concept in concepts if concept["attempt_count"] == 0] or concepts)[:1]
        attempts: list[dict] = []
        total_seconds = 0
        if scoped_ids:
            placeholders = ",".join("?" for _ in scoped_ids)
            attempts = database.query_all(
                f"""
                SELECT attempt.id, attempt.concept_id, concept.name AS concept_name,
                       attempt.score, attempt.confidence, attempt.duration_seconds,
                       attempt.hints_used, attempt.rating, attempt.created_at
                FROM learning_attempts AS attempt
                JOIN learning_concepts AS concept ON concept.id = attempt.concept_id
                WHERE attempt.concept_id IN ({placeholders})
                ORDER BY attempt.id DESC LIMIT 20
                """,
                tuple(scoped_ids),
            )
            total_seconds = int(
                database.query_one(
                    f"SELECT COALESCE(SUM(duration_seconds), 0) AS total FROM learning_attempts WHERE concept_id IN ({placeholders})",
                    tuple(scoped_ids),
                )["total"]
            )
        mastery = round(sum(float(item["mastery"]) for item in concepts) / len(concepts), 1) if concepts else None
        return {
            "courses": courses,
            "concepts": concepts,
            "due_reviews": due,
            "next_concept": next_concept[0] if next_concept else None,
            "recent_attempts": attempts,
            "summary": {
                "concept_count": len(concepts),
                "attempt_count": sum(int(item["attempt_count"]) for item in concepts),
                "due_count": len(due),
                "mastery": mastery,
                "study_seconds": total_seconds,
            },
        }

    @app.post("/api/learning/attempts", status_code=status.HTTP_201_CREATED)
    def record_attempt(payload: LearningAttemptCreate, request: Request) -> dict:
        database = db(request)
        concept = database.query_one("SELECT * FROM learning_concepts WHERE id = ?", (payload.concept_id,))
        if not concept:
            raise HTTPException(status_code=404, detail="Concept not found")
        review = review_concept(
            concept,
            score=payload.score,
            hints_used=payload.hints_used,
            duration_seconds=payload.duration_seconds,
        )
        attempt_id, updated = database.record_learning_review(
            concept_id=payload.concept_id,
            score=payload.score,
            prompt=payload.prompt,
            answer=payload.answer,
            feedback=payload.feedback,
            confidence=payload.confidence,
            duration_seconds=payload.duration_seconds,
            hints_used=payload.hints_used,
            mastery=review.mastery,
            status=review.status,
            rating=review.rating,
            due_at=review.due_at,
            card_json=review.card_json,
            review_log_json=review.review_log_json,
        )
        database.audit("learning", "record_attempt", str(attempt_id))
        updated.pop("fsrs_card_json", None)
        return {
            "attempt_id": attempt_id,
            "concept": updated,
            "rating": review.rating,
            "due_at": review.due_at,
        }

    @app.get("/api/learning/attempts")
    def list_learning_attempts(
        request: Request,
        concept_id: int | None = Query(default=None, gt=0),
        limit: int = Query(default=50, ge=1, le=200),
    ) -> list[dict]:
        where = "WHERE attempt.concept_id = ?" if concept_id is not None else ""
        parameters: tuple[object, ...] = (concept_id, limit) if concept_id is not None else (limit,)
        return db(request).query_all(
            f"""
            SELECT attempt.*, concept.name AS concept_name, concept.course_id
            FROM learning_attempts AS attempt
            JOIN learning_concepts AS concept ON concept.id = attempt.concept_id
            {where}
            ORDER BY attempt.id DESC LIMIT ?
            """,
            parameters,
        )

    def coach_snapshot(request: Request, course_id: int | None) -> dict[str, object]:
        database = db(request)
        concepts = learning_progress(request, course_id)
        now = utc_now()
        scoped_ids = [int(concept["id"]) for concept in concepts]
        prerequisite_rows: list[dict[str, object]] = []
        if scoped_ids:
            placeholders = ",".join("?" for _ in scoped_ids)
            prerequisite_rows = database.query_all(
                f"""
                SELECT prerequisite.concept_id, prerequisite.prerequisite_id,
                       prerequisite_concept.name AS prerequisite_name,
                       prerequisite_concept.mastery AS prerequisite_mastery,
                       prerequisite_concept.status AS prerequisite_status
                FROM learning_prerequisites AS prerequisite
                JOIN learning_concepts AS prerequisite_concept
                  ON prerequisite_concept.id = prerequisite.prerequisite_id
                WHERE prerequisite.concept_id IN ({placeholders})
                ORDER BY prerequisite.concept_id, prerequisite_concept.name
                """,
                tuple(scoped_ids),
            )

        prerequisites_by_concept: dict[int, list[dict[str, object]]] = {}
        for row in prerequisite_rows:
            prerequisites_by_concept.setdefault(int(row["concept_id"]), []).append(row)

        concept_reports: list[dict[str, object]] = []
        weak_foundations: list[dict[str, object]] = []
        for concept in concepts:
            concept_id = int(concept["id"])
            prerequisites = prerequisites_by_concept.get(concept_id, [])
            missing = [
                {
                    "id": int(row["prerequisite_id"]),
                    "name": str(row["prerequisite_name"]),
                    "mastery": float(row["prerequisite_mastery"] or 0),
                    "status": str(row["prerequisite_status"] or "not_started"),
                }
                for row in prerequisites
                if float(row["prerequisite_mastery"] or 0) < 60
                or str(row["prerequisite_status"] or "not_started") in {"not_started", "review"}
            ]
            if missing:
                weak_foundations.append(
                    {
                        "concept_id": concept_id,
                        "concept_name": concept["name"],
                        "missing_prerequisites": missing,
                    }
                )
            concept_reports.append(
                {
                    **concept,
                    "prerequisites": prerequisites,
                    "weak_prerequisites": missing,
                    "trend": concept_trend(database, concept_id),
                }
            )

        due = [c for c in concepts if c.get("due_at") and c["due_at"] <= now]
        candidates = (
            due
            or [c for c in concepts if c["attempt_count"] == 0]
            or sorted(
                (c for c in concepts if float(c["mastery"]) < 80),
                key=lambda c: float(c["mastery"]),
            )
            or concepts
        )
        next_step: dict[str, object] = {"kind": "none", "concept": None}
        if candidates:
            candidate = candidates[0]
            kind = (
                "review"
                if candidate in due
                else "new"
                if candidate["attempt_count"] == 0
                else "practice"
            )
            next_step = {"kind": kind, "concept": candidate}

        study_seconds = 0
        if scoped_ids:
            placeholders = ",".join("?" for _ in scoped_ids)
            study_seconds = int(
                database.query_one(
                    f"""
                    SELECT COALESCE(SUM(duration_seconds), 0) AS total
                    FROM learning_attempts WHERE concept_id IN ({placeholders})
                    """,
                    tuple(scoped_ids),
                )["total"]
            )
        mastery = round(sum(float(c["mastery"]) for c in concepts) / len(concepts), 1) if concepts else None
        return {
            "generated_at": now,
            "summary": {
                "concept_count": len(concepts),
                "attempt_count": sum(int(c["attempt_count"]) for c in concepts),
                "due_count": len(due),
                "mastery": mastery,
                "weak_foundation_count": len(weak_foundations),
                "study_seconds": study_seconds,
            },
            "concepts": concept_reports,
            "weak_foundations": weak_foundations,
            "next_step": next_step,
            "due": due,
            "scoped_ids": scoped_ids,
            "study_seconds": study_seconds,
            "database": database,
        }

    @app.get("/api/coach/report")
    def coach_report(
        request: Request,
        course_id: int | None = Query(default=None, gt=0),
    ) -> dict[str, object]:
        snapshot = coach_snapshot(request, course_id)
        return {
            "generated_at": snapshot["generated_at"],
            "summary": snapshot["summary"],
            "concepts": snapshot["concepts"],
            "weak_foundations": snapshot["weak_foundations"],
            "next_step": snapshot["next_step"],
        }

    @app.get("/api/coach/plan")
    def coach_plan(
        request: Request,
        course_id: int | None = Query(default=None, gt=0),
        days: int = Query(default=7, ge=1, le=14),
    ) -> dict[str, object]:
        snapshot = coach_snapshot(request, course_id)
        database: Database = snapshot["database"]
        concepts: list[dict[str, object]] = snapshot["concepts"]
        today = datetime.now().date()

        due_items: list[tuple[dict[str, object], date]] = []
        for concept in concepts:
            due_at = concept.get("due_at")
            if not due_at:
                continue
            try:
                due_datetime = datetime.fromisoformat(str(due_at))
            except ValueError:
                continue
            if due_datetime.tzinfo is None:
                due_datetime = due_datetime.replace(tzinfo=timezone.utc)
            due_day = due_datetime.astimezone().date()
            if due_day < today:
                due_day = today
            due_items.append((concept, due_day))
        due_items.sort(key=lambda item: item[1].isoformat() + str(item[0].get("due_at", "")))

        new_pool = [c for c in concepts if int(c["attempt_count"]) == 0]
        foundation_ids: set[int] = set()
        for item in snapshot["weak_foundations"]:
            for prerequisite in item["missing_prerequisites"]:
                foundation_ids.add(int(prerequisite["id"]))
        foundation_by_id = {int(c["id"]): c for c in concepts}

        max_reviews_per_day = 5
        max_new_per_day = 2
        max_foundations_per_day = 2
        planned_review_ids: set[int] = set()
        planned_new_ids: set[int] = set()
        planned_foundation_ids: set[int] = set()
        plan_days: list[dict[str, object]] = []

        for offset in range(days):
            day = today + timedelta(days=offset)
            reviews: list[dict[str, object]] = []
            for concept, due_day in due_items:
                if due_day > day:
                    continue
                concept_id = int(concept["id"])
                if concept_id in planned_review_ids or len(reviews) >= max_reviews_per_day:
                    continue
                reviews.append(concept)
                planned_review_ids.add(concept_id)

            new_concepts: list[dict[str, object]] = []
            for concept in new_pool:
                concept_id = int(concept["id"])
                if concept_id in planned_new_ids or concept_id in planned_review_ids:
                    continue
                if len(new_concepts) >= max_new_per_day:
                    break
                new_concepts.append(concept)
                planned_new_ids.add(concept_id)

            foundations: list[dict[str, object]] = []
            for concept_id in sorted(foundation_ids):
                if concept_id in planned_foundation_ids or concept_id in planned_review_ids or concept_id in planned_new_ids:
                    continue
                concept = foundation_by_id.get(concept_id)
                if concept is None or len(foundations) >= max_foundations_per_day:
                    continue
                foundations.append(concept)
                planned_foundation_ids.add(concept_id)

            plan_days.append(
                {
                    "date": day.isoformat(),
                    "reviews": reviews,
                    "new_concepts": new_concepts,
                    "foundation_concepts": foundations,
                }
            )

        scoped_ids = snapshot["scoped_ids"]
        average_attempt_seconds = 600.0
        if scoped_ids:
            placeholders = ",".join("?" for _ in scoped_ids)
            average_row = database.query_one(
                f"""
                SELECT AVG(duration_seconds) AS average_seconds
                FROM learning_attempts
                WHERE concept_id IN ({placeholders}) AND duration_seconds IS NOT NULL
                """,
                tuple(scoped_ids),
            )
            if average_row and average_row["average_seconds"] is not None:
                average_attempt_seconds = float(average_row["average_seconds"])

        planned_reviews = sum(len(day["reviews"]) for day in plan_days)
        planned_new = sum(len(day["new_concepts"]) for day in plan_days)
        planned_foundations = sum(len(day["foundation_concepts"]) for day in plan_days)
        planned_total = planned_reviews + planned_new + planned_foundations
        estimated_minutes = round(planned_total * average_attempt_seconds / 60)

        return {
            "generated_at": snapshot["generated_at"],
            "start_date": today.isoformat(),
            "days": plan_days,
            "summary": {
                "planned_reviews": planned_reviews,
                "planned_new_concepts": planned_new,
                "planned_foundations": planned_foundations,
                "estimated_minutes": estimated_minutes,
                "average_attempt_minutes": round(average_attempt_seconds / 60, 1),
                "due_count": len(snapshot["due"]),
                "new_count": len(new_pool),
                "weak_foundation_count": len(snapshot["weak_foundations"]),
            },
        }

    @app.get("/api/coach/context")
    def coach_context(
        request: Request,
        question: str = Query(min_length=1, max_length=500),
        course_id: int | None = Query(default=None, gt=0),
        limit: int = Query(default=8, ge=1, le=20),
    ) -> dict[str, object]:
        database = db(request)
        query = question.strip()
        lexical_results = lexical_search(database, query, limit)
        semantic_results, semantic_degraded = semantic_search(request, query, limit)
        evidence = fuse_results(lexical_results, semantic_results, limit)
        concepts = learning_progress(request, course_id)
        now = utc_now()
        due = [c for c in concepts if c.get("due_at") and c["due_at"] <= now]
        return {
            "question": query,
            "generated_at": now,
            "semantic_degraded": semantic_degraded,
            "evidence": evidence,
            "learning_state": {
                "course_id": course_id,
                "concept_count": len(concepts),
                "due_count": len(due),
                "concepts": concepts,
            },
        }

    def require_chat_role(
        database: Database,
        role: str,
        *,
        operation: str,
        source: str,
        category: str,
        action: str,
    ) -> tuple[str, dict[str, str]]:
        roles = {item["role"]: item for item in database.get_model_roles()}
        config = roles.get(role)
        canonical = (
            normalize_provider(config["provider"])
            if config and config.get("provider")
            else None
        )
        if not config or not config.get("model") or canonical is None:
            database.record_model_call(
                provider=canonical or "unconfigured",
                operation=operation,
                source=source,
                duration_ms=0,
                status="error",
                error_code="role_not_configured",
                role=role,
            )
            database.audit(category, action, role, result="role_not_configured")
            raise HTTPException(status_code=409, detail="Model role is not configured")
        return canonical, config

    def openai_content_to_text(content: object) -> str:
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts: list[str] = []
            for item in content:
                if isinstance(item, str):
                    parts.append(item)
                elif isinstance(item, dict) and isinstance(item.get("text"), str):
                    parts.append(item["text"])
            return "".join(parts)
        return ""

    def openai_conversation_prompt(
        messages: list[dict[str, object]],
    ) -> tuple[str, str]:
        history: list[str] = []
        extra_system: list[str] = []
        for message in messages:
            role = str(message.get("role") or "")
            text = openai_content_to_text(message.get("content") or "").strip()
            if role not in {"system", "user", "assistant"}:
                continue
            if not text:
                continue
            if role == "system":
                extra_system.append(text)
                continue
            label = "用户" if role == "user" else "助手"
            history.append(f"{label}：{text}")
        conversation = "\n\n".join(history)
        return conversation, "\n".join(extra_system).strip()

    def openai_requested_role(database: Database, requested_model: str) -> str:
        model = requested_model.strip()
        roles = {item["role"]: item for item in database.get_model_roles()}
        if model in roles:
            return model
        for role, config in roles.items():
            if config.get("model") == model:
                return role
        return "reasoning"

    def chat_context(
        request: Request,
        question: str,
        scope: str,
        course_id: int | None,
        limit: int = 8,
    ) -> tuple[list[dict[str, object]], dict[str, object], bool]:
        database = db(request)
        evidence: list[dict[str, object]] = []
        semantic_degraded = False
        if scope in {"all", "library"}:
            def retrieve(query: str) -> tuple[list[dict], bool]:
                lexical_results = lexical_search(database, query, limit)
                semantic_results, degraded = semantic_search(request, query, limit)
                return fuse_results(lexical_results, semantic_results, limit), degraded

            candidates, degraded = retrieve(question)
            semantic_degraded = semantic_degraded or degraded
            if not candidates and len(question) > 4:
                fallback_tokens = [
                    token
                    for token in sorted(
                        {match.group(0) for match in re.finditer(r"[\u4e00-\u9fff]{2,}", question)},
                        key=len,
                        reverse=True,
                    )
                    if len(token) >= 4
                ]
                for token in fallback_tokens:
                    candidates, degraded = retrieve(token)
                    semantic_degraded = semantic_degraded or degraded
                    if candidates:
                        break

            for item in candidates:
                snippet = str(item.get("snippet") or item.get("chunk") or "").strip()
                if len(snippet) > 600:
                    snippet = snippet[:597].rstrip() + "…"
                evidence.append(
                    {
                        "document_id": item.get("document_id"),
                        "title": item.get("title"),
                        "document_type": item.get("document_type"),
                        "source_path": item.get("source_path"),
                        "page": item.get("page"),
                        "paragraph": item.get("paragraph"),
                        "chunk_index": item.get("chunk_index"),
                        "snippet": snippet,
                        "search_mode": item.get("search_mode"),
                        "semantic_score": item.get("semantic_score"),
                    }
                )

        learning_state: dict[str, object] = {
            "scope": scope,
            "course_id": course_id,
            "concept_count": 0,
            "due_count": 0,
            "weak_foundation_count": 0,
            "next_step": {"kind": "none", "concept_name": None},
            "concepts": [],
        }
        if scope in {"all", "learning"}:
            snapshot = coach_snapshot(request, course_id)
            concepts = [
                {
                    "id": item["id"],
                    "name": item["name"],
                    "mastery": round(float(item["mastery"]), 1),
                    "status": item["status"],
                    "attempt_count": item["attempt_count"],
                    "due_at": item["due_at"],
                }
                for item in snapshot["concepts"]
            ][:20]
            next_step = snapshot["next_step"]
            learning_state = {
                "scope": scope,
                "course_id": course_id,
                "concept_count": int(snapshot["summary"]["concept_count"]),
                "due_count": int(snapshot["summary"]["due_count"]),
                "weak_foundation_count": int(snapshot["summary"]["weak_foundation_count"]),
                "next_step": {
                    "kind": next_step["kind"],
                    "concept_name": next_step["concept"]["name"] if next_step.get("concept") else None,
                },
                "concepts": concepts,
            }
        return evidence, learning_state, semantic_degraded

    def chat_system_prompt(
        evidence: list[dict[str, object]],
        learning_state: dict[str, object],
        scope: str,
    ) -> str:
        lines = [
            "你是 Nexus AI-PC 的本地知识助手，帮助用户学习和研究。",
            "回答要求：",
            "1. 优先使用下方【本地资料】中的证据；引用时在对应句子后标注 [1]、[2] 等编号，编号与资料列表一致。",
            "2. 明确区分资料中的事实、你的推断、用户假设和待验证建议；没有证据时直接说明，不要编造来源。",
            "3. 对不确定的内容说明剩余不确定性；如果用户观点有误，应给出反例或替代解释，而不是迎合用户。",
            "4. 回答默认使用中文，简洁、条理清楚，适合快速阅读。",
        ]
        if evidence:
            lines.append("")
            lines.append("【本地资料】")
            for index, item in enumerate(evidence, start=1):
                title = str(item.get("title") or "未命名资料")
                source = str(item.get("source_path") or "")
                page = item.get("page")
                paragraph = item.get("paragraph")
                location = (
                    f"第 {page} 页"
                    if page is not None
                    else f"第 {paragraph} 段"
                    if paragraph is not None
                    else ""
                )
                lines.append(
                    f"[{index}]《{title}》 {source} {location}\n{str(item.get('snippet') or '').strip()}"
                )
        else:
            lines.append("")
            lines.append("【本地资料】未检索到相关证据。请如实告诉用户，并明确标注哪些内容只是你的推测。")

        concept_count = int(learning_state.get("concept_count") or 0)
        if scope in {"all", "learning"} and concept_count:
            lines.append("")
            lines.append("【学习进度】")
            lines.append(
                f"共 {concept_count} 个知识点，{int(learning_state.get('due_count') or 0)} 个待复习，"
                f"{int(learning_state.get('weak_foundation_count') or 0)} 个薄弱前置。"
            )
            next_step = learning_state.get("next_step") or {}
            next_name = next_step.get("concept_name")
            if next_name:
                lines.append(f"建议下一步：{next_name}（{next_step.get('kind')}）。")
            concept_lines = [
                f"- {item['name']}（掌握度 {item['mastery']}%，{item['status']}）"
                for item in learning_state.get("concepts") or []
            ]
            if concept_lines:
                lines.append("知识点：")
                lines.extend(concept_lines)
        return "\n".join(lines)

    @app.post("/api/chat/ask")
    async def chat_ask(payload: ChatAskRequest, request: Request) -> dict[str, object]:
        role = payload.role.strip()
        if role not in {"reasoning", "fast"}:
            raise HTTPException(status_code=422, detail="Chat supports only reasoning and fast roles")
        database = db(request)
        canonical, config = require_chat_role(
            database,
            role,
            operation="chat",
            source="dashboard_chat",
            category="chat",
            action="ask",
        )

        question = payload.question.strip()
        evidence, learning_state, semantic_degraded = chat_context(
            request,
            question,
            payload.scope,
            payload.course_id,
        )
        system = chat_system_prompt(evidence, learning_state, payload.scope)
        try:
            result = await request.app.state.model_gateway.generate(
                provider=canonical,
                endpoint=config["endpoint"],
                model=config["model"],
                prompt=question,
                system=system,
                max_tokens=payload.max_tokens,
                temperature=payload.temperature,
                role=role,
            )
        except ModelRequestCancelled as error:
            database.record_model_call(
                provider=canonical,
                operation="chat",
                source="dashboard_chat",
                duration_ms=error.duration_ms,
                status="cancelled",
                error_code="cancelled",
                role=role,
            )
            database.audit("chat", "ask", role, result="cancelled")
            raise asyncio.CancelledError from None
        except CredentialStorageError:
            database.record_model_call(
                provider=canonical,
                operation="chat",
                source="dashboard_chat",
                duration_ms=0,
                status="error",
                error_code="credential_store_unavailable",
                role=role,
            )
            database.audit("chat", "ask", role, result="credential_store_unavailable")
            raise HTTPException(status_code=503, detail="Credential storage is unavailable") from None
        except ModelGatewayError as error:
            database.record_model_call(
                provider=canonical,
                operation="chat",
                source="dashboard_chat",
                duration_ms=error.duration_ms,
                status="error",
                error_code=error.code,
                role=role,
            )
            database.audit("chat", "ask", role, result=error.code)
            raise HTTPException(status_code=error.status_code, detail=error.detail) from None

        database.record_model_call(
            provider=result.provider,
            operation="chat",
            source="dashboard_chat",
            duration_ms=result.latency_ms,
            status="success",
            model=result.model,
            role=result.role,
            prompt_tokens=result.prompt_tokens,
            completion_tokens=result.completion_tokens,
            total_tokens=result.total_tokens,
        )
        database.audit("chat", "ask", role)
        return {
            "role": result.role,
            "provider": result.provider,
            "model": result.model,
            "status": "ok",
            "answer": result.content,
            "latency_ms": result.latency_ms,
            "usage": {
                "prompt_tokens": result.prompt_tokens,
                "completion_tokens": result.completion_tokens,
                "total_tokens": result.total_tokens,
            },
            "evidence": evidence,
            "learning_state": learning_state,
            "semantic_degraded": semantic_degraded,
        }

    @app.post("/v1/chat/completions")
    async def openai_chat_completions(
        payload: OpenAIChatRequest,
        request: Request,
    ):
        database = db(request)
        normalized: list[dict[str, object]] = []
        for message in payload.messages:
            role = message.role.strip()
            if role not in {"system", "user", "assistant"}:
                raise HTTPException(status_code=422, detail="Unsupported message role")
            content = openai_content_to_text(message.content)
            if len(content) > 100_000:
                raise HTTPException(status_code=422, detail="Message content is too long")
            if role != "system" and not content.strip():
                raise HTTPException(status_code=422, detail="Message content must not be empty")
            normalized.append({"role": role, "content": content.strip()})

        latest_user = next(
            (
                str(item["content"])
                for item in reversed(normalized)
                if item["role"] == "user" and str(item["content"]).strip()
            ),
            "",
        )
        if not latest_user:
            raise HTTPException(
                status_code=422,
                detail="At least one user message is required",
            )

        conversation, extra_system = openai_conversation_prompt(normalized)
        role = openai_requested_role(database, payload.model)
        if role not in {"reasoning", "fast"}:
            role = "reasoning"
        canonical, config = require_chat_role(
            database,
            role,
            operation="openai_compat_chat",
            source="nextchat",
            category="chat",
            action="openai_completions",
        )

        evidence, learning_state, semantic_degraded = chat_context(
            request,
            latest_user,
            "all",
            None,
        )
        system = chat_system_prompt(evidence, learning_state, "all")
        if extra_system:
            system = f"{system}\n\n【用户附加要求】\n{extra_system}"
        if conversation:
            prompt = (
                "以下是本次对话的完整多轮记录（按时间顺序）：\n\n"
                f"{conversation}\n\n请针对最后一条用户消息继续回答。"
            )
        else:
            prompt = latest_user

        max_tokens = payload.max_tokens or 1024
        temperature = payload.temperature if payload.temperature is not None else 0.2
        try:
            result = await request.app.state.model_gateway.generate(
                provider=canonical,
                endpoint=config["endpoint"],
                model=config["model"],
                prompt=prompt,
                system=system,
                max_tokens=max_tokens,
                temperature=temperature,
                role=role,
            )
        except ModelRequestCancelled as error:
            database.record_model_call(
                provider=canonical,
                operation="openai_compat_chat",
                source="nextchat",
                duration_ms=error.duration_ms,
                status="cancelled",
                error_code="cancelled",
                role=role,
            )
            database.audit("chat", "openai_completions", role, result="cancelled")
            raise asyncio.CancelledError from None
        except CredentialStorageError:
            database.record_model_call(
                provider=canonical,
                operation="openai_compat_chat",
                source="nextchat",
                duration_ms=0,
                status="error",
                error_code="credential_store_unavailable",
                role=role,
            )
            database.audit(
                "chat",
                "openai_completions",
                role,
                result="credential_store_unavailable",
            )
            raise HTTPException(status_code=503, detail="Credential storage is unavailable") from None
        except ModelGatewayError as error:
            database.record_model_call(
                provider=canonical,
                operation="openai_compat_chat",
                source="nextchat",
                duration_ms=error.duration_ms,
                status="error",
                error_code=error.code,
                role=role,
            )
            database.audit("chat", "openai_completions", role, result=error.code)
            raise HTTPException(status_code=error.status_code, detail=error.detail) from None

        database.record_model_call(
            provider=result.provider,
            operation="openai_compat_chat",
            source="nextchat",
            duration_ms=result.latency_ms,
            status="success",
            model=result.model,
            role=result.role,
            prompt_tokens=result.prompt_tokens,
            completion_tokens=result.completion_tokens,
            total_tokens=result.total_tokens,
        )
        database.audit("chat", "openai_completions", role)

        completion_id = f"chatcmpl-{uuid4().hex}"
        created = int(datetime.now(timezone.utc).timestamp())

        def build_evidence_footer(evidence_items: list[dict[str, object]]) -> str:
            if not evidence_items:
                return ""
            lines = ["", "---", "**本地资料引用**"]
            for index, item in enumerate(evidence_items, start=1):
                title = str(item.get("title") or "未命名资料")
                source = str(item.get("source_path") or "")
                page = item.get("page")
                paragraph = item.get("paragraph")
                location = (
                    f"第 {page} 页"
                    if page is not None
                    else f"第 {paragraph} 段"
                    if paragraph is not None
                    else ""
                )
                suffix = f"（{location}）" if location else ""
                lines.append(f"[{index}]《{title}》{source}{suffix}")
            return "\n".join(lines)

        footer = build_evidence_footer(evidence)
        answer = result.content + footer

        def sse_payload(chunk_payload: dict[str, object]) -> str:
            return f"data: {json.dumps(chunk_payload, ensure_ascii=False)}\n\n"

        if payload.stream:

            async def event_stream() -> object:
                chunk_size = 96
                for index in range(0, len(answer), chunk_size):
                    yield sse_payload(
                        {
                            "id": completion_id,
                            "object": "chat.completion.chunk",
                            "created": created,
                            "model": result.model,
                            "choices": [
                                {
                                    "index": 0,
                                    "delta": {"content": answer[index : index + chunk_size]},
                                    "finish_reason": None,
                                }
                            ],
                        }
                    )
                yield sse_payload(
                    {
                        "id": completion_id,
                        "object": "chat.completion.chunk",
                        "created": created,
                        "model": result.model,
                        "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
                    }
                )
                yield "data: [DONE]\n\n"

            return StreamingResponse(
                event_stream(),
                media_type="text/event-stream",
                headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
            )

        return {
            "id": completion_id,
            "object": "chat.completion",
            "created": created,
            "model": result.model,
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": answer},
                    "finish_reason": "stop",
                }
            ],
            "usage": {
                "prompt_tokens": result.prompt_tokens,
                "completion_tokens": result.completion_tokens,
                "total_tokens": result.total_tokens,
            },
            "semantic_degraded": semantic_degraded,
        }

    @app.get("/v1/models")
    def openai_list_models(request: Request) -> dict[str, object]:
        roles = db(request).get_model_roles()
        data: list[dict[str, object]] = []
        for item in roles:
            if item["role"] not in {"reasoning", "fast"} or not item.get("model"):
                continue
            data.append(
                {
                    "id": item["role"],
                    "object": "model",
                    "created": int(datetime.now(timezone.utc).timestamp()),
                    "owned_by": item.get("provider") or "local",
                }
            )
            data.append(
                {
                    "id": item["model"],
                    "object": "model",
                    "created": int(datetime.now(timezone.utc).timestamp()),
                    "owned_by": item.get("provider") or "local",
                }
            )
        return {"object": "list", "data": data}

    @app.get("/api/research/projects")
    def list_projects(request: Request) -> list[dict]:
        return db(request).query_all("SELECT * FROM research_projects ORDER BY updated_at DESC, id DESC")

    @app.post("/api/research/projects", status_code=status.HTTP_201_CREATED)
    def create_project(payload: ResearchProjectCreate, request: Request) -> dict:
        database = db(request)
        now = utc_now()
        project_id = database.execute(
            """
            INSERT INTO research_projects(name, question, research_type, status, created_at, updated_at)
            VALUES (?, ?, ?, 'active', ?, ?)
            """,
            (payload.name, payload.question, payload.research_type, now, now),
        )
        database.audit("research", "create_project", str(project_id))
        return database.query_one("SELECT * FROM research_projects WHERE id = ?", (project_id,)) or {}

    @app.get("/api/research/projects/{project_id}/notes")
    def list_research_notes(project_id: int, request: Request) -> list[dict]:
        database = db(request)
        if not database.query_one("SELECT id FROM research_projects WHERE id = ?", (project_id,)):
            raise HTTPException(status_code=404, detail="Project not found")
        return database.query_all(
            "SELECT * FROM research_notes WHERE project_id = ? ORDER BY created_at DESC, id DESC",
            (project_id,),
        )

    @app.post("/api/research/projects/{project_id}/notes", status_code=status.HTTP_201_CREATED)
    def create_research_note(project_id: int, payload: ResearchNoteCreate, request: Request) -> dict:
        database = db(request)
        if not database.query_one("SELECT id FROM research_projects WHERE id = ?", (project_id,)):
            raise HTTPException(status_code=404, detail="Project not found")
        note_id = database.execute(
            "INSERT INTO research_notes(project_id, body, created_at) VALUES (?, ?, ?)",
            (project_id, payload.body, utc_now()),
        )
        database.audit("research", "create_note", str(note_id))
        return database.query_one("SELECT * FROM research_notes WHERE id = ?", (note_id,)) or {}

    @app.post(
        "/api/research/projects/{project_id}/searches",
        status_code=status.HTTP_201_CREATED,
    )
    def search_research_literature(
        project_id: int,
        payload: ResearchSearchCreate,
        request: Request,
    ) -> dict:
        database = db(request)
        if not database.query_one("SELECT id FROM research_projects WHERE id = ?", (project_id,)):
            raise HTTPException(status_code=404, detail="Project not found")
        try:
            papers = research_client(request).search(payload.query, limit=payload.limit)
        except ResearchUpstreamError as error:
            raise HTTPException(status_code=error.status_code, detail=error.detail) from error
        try:
            result = database.save_research_search(
                project_id=project_id,
                query=payload.query,
                providers=["crossref", "openalex"],
                papers=[paper.as_record() for paper in papers],
            )
        except LookupError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        database.audit("research", "literature_search", str(result["search"]["id"]))
        return result

    @app.get("/api/research/projects/{project_id}/searches")
    def list_research_searches(
        project_id: int,
        request: Request,
        limit: int = Query(default=20, ge=1, le=100),
    ) -> list[dict]:
        database = db(request)
        if not database.query_one("SELECT id FROM research_projects WHERE id = ?", (project_id,)):
            raise HTTPException(status_code=404, detail="Project not found")
        return database.list_research_searches(project_id, limit)

    @app.get("/api/research/searches/{search_run_id}")
    def get_research_search(search_run_id: int, request: Request) -> dict:
        result = db(request).get_research_search(search_run_id)
        if not result:
            raise HTTPException(status_code=404, detail="Research search not found")
        return result

    @app.get("/api/research/projects/{project_id}/screening")
    def list_research_screening(project_id: int, request: Request) -> list[dict]:
        database = db(request)
        if not database.query_one("SELECT id FROM research_projects WHERE id = ?", (project_id,)):
            raise HTTPException(status_code=404, detail="Project not found")
        return database.list_screening_decisions(project_id)

    @app.put("/api/research/projects/{project_id}/papers/{paper_id}/screening")
    def update_research_screening(
        project_id: int,
        paper_id: int,
        payload: ResearchScreeningUpdate,
        request: Request,
    ) -> dict:
        database = db(request)
        try:
            decision = database.save_screening_decision(
                project_id=project_id,
                paper_id=paper_id,
                decision=payload.decision,
                reason=payload.reason,
            )
        except LookupError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        database.audit("research", "screen_paper", f"{project_id}:{paper_id}")
        return decision

    @app.get("/api/agent/tasks")
    def list_agent_tasks(request: Request) -> list[dict]:
        return db(request).query_all("SELECT * FROM agent_tasks ORDER BY created_at DESC, id DESC")

    @app.get("/api/agent/status")
    def get_agent_status() -> dict[str, object]:
        return active_agent_handoff.status()

    @app.post("/api/agent/tasks", status_code=status.HTTP_201_CREATED)
    def create_agent_task(payload: AgentTaskCreate, request: Request) -> dict:
        database = db(request)
        task_id = database.execute(
            """
            INSERT INTO agent_tasks(
                project, title, status, run_tests, generate_summary,
                allow_dependencies, created_at, updated_at
            )
            VALUES (?, ?, 'queued', ?, ?, ?, ?, ?)
            """,
            (
                payload.project,
                payload.title,
                int(payload.run_tests),
                int(payload.generate_summary),
                int(payload.allow_dependencies),
                utc_now(),
                utc_now(),
            ),
        )
        database.audit("agent", "create_task", str(task_id))
        return database.query_one("SELECT * FROM agent_tasks WHERE id = ?", (task_id,)) or {}

    @app.post("/api/agent/tasks/{task_id}/handoff")
    def handoff_agent_task(task_id: int, request: Request) -> dict[str, object]:
        require_local_same_origin_handoff(request)
        database = db(request)
        existing = database.query_one("SELECT * FROM agent_tasks WHERE id = ?", (task_id,))
        if not existing:
            raise HTTPException(status_code=404, detail="Agent task not found")
        if not active_agent_handoff.status()["available"]:
            raise HTTPException(status_code=503, detail="VS Code, Cline, or the approved workspace is unavailable")

        task = database.claim_agent_handoff(task_id)
        if task is None:
            current = database.query_one("SELECT status FROM agent_tasks WHERE id = ?", (task_id,))
            current_status = current["status"] if current else "missing"
            raise HTTPException(status_code=409, detail=f"Agent task cannot be handed off from {current_status}")

        try:
            prepared_task = active_agent_handoff.prepare_task(task)
            active_agent_handoff.open_in_cline(task, prepared_task.path)
        except AgentHandoffError as error:
            database.fail_agent_handoff(task_id, "agent_handoff_failed")
            database.audit("agent", "handoff", str(task_id), result="error")
            raise HTTPException(status_code=503, detail=str(error)) from None

        completed = database.complete_agent_handoff(
            task_id,
            task_file=str(prepared_task.path),
            task_sha256=prepared_task.sha256,
        )
        if completed is None:
            database.audit("agent", "handoff", str(task_id), result="state_error")
            raise HTTPException(status_code=409, detail="Agent handoff state could not be finalized")
        database.audit("agent", "handoff", str(task_id))
        return {
            "status": "handoff_requested",
            "task": completed,
            "task_file": str(prepared_task.path),
            "task_sha256": prepared_task.sha256,
        }

    @app.get("/api/settings")
    def get_settings(request: Request) -> dict[str, str]:
        rows = db(request).query_all("SELECT key, value FROM settings ORDER BY key")
        return {row["key"]: row["value"] for row in rows}

    @app.put("/api/settings")
    def update_settings(payload: SettingsUpdate, request: Request) -> dict[str, str]:
        database = db(request)
        canonical = credential_provider(payload.provider)
        try:
            build_probe_url(canonical, str(payload.endpoint))
        except ModelGatewayError as error:
            raise HTTPException(status_code=error.status_code, detail=error.detail) from None
        now = utc_now()
        values = {
            "provider": payload.provider,
            "endpoint": str(payload.endpoint),
            "data_path": payload.data_path,
        }
        database.execute_many(
            """
            INSERT INTO settings(key, value, updated_at) VALUES (?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
            """,
            [(key, value, now) for key, value in values.items()],
        )
        database.audit("settings", "update", "non_secret_settings")
        return values

    @app.get("/api/credentials")
    def list_credentials() -> dict[str, list[dict[str, object]]]:
        return {
            "providers": [
                {"provider": provider, "configured": is_credential_configured(provider)}
                for provider in SUPPORTED_PROVIDERS
            ]
        }

    @app.get("/api/credentials/{provider}")
    def get_credential_status(provider: str) -> dict[str, object]:
        canonical = credential_provider(provider)
        return {"provider": canonical, "configured": is_credential_configured(canonical)}

    @app.put("/api/credentials/{provider}")
    def set_credential(provider: str, payload: CredentialUpdate, request: Request) -> dict[str, object]:
        canonical = credential_provider(provider)
        secret = payload.api_key.get_secret_value()
        try:
            credential_store.set(canonical, secret)
        except CredentialStorageError:
            raise HTTPException(status_code=503, detail="Credential storage is unavailable") from None
        finally:
            secret = ""
        db(request).audit("credentials", "set", canonical)
        return {"provider": canonical, "configured": True}

    @app.delete("/api/credentials/{provider}")
    def delete_credential(provider: str, request: Request) -> dict[str, object]:
        canonical = credential_provider(provider)
        try:
            credential_store.delete(canonical)
        except CredentialStorageError:
            raise HTTPException(status_code=503, detail="Credential storage is unavailable") from None
        db(request).audit("credentials", "delete", canonical)
        return {"provider": canonical, "configured": False}

    @app.post("/api/models/test")
    async def test_model_connection(
        payload: ModelConnectionTestRequest,
        request: Request,
    ) -> dict[str, object]:
        canonical = credential_provider(payload.provider)
        database = db(request)
        try:
            result = await request.app.state.model_gateway.probe(canonical, str(payload.endpoint))
        except ModelProbeCancelled as error:
            database.record_model_call(
                provider=canonical,
                operation="connection_test",
                source="dashboard_settings",
                duration_ms=error.duration_ms,
                status="cancelled",
                error_code="cancelled",
            )
            database.audit("models", "connection_test", canonical, result="cancelled")
            raise asyncio.CancelledError from None
        except CredentialStorageError:
            database.record_model_call(
                provider=canonical,
                operation="connection_test",
                source="dashboard_settings",
                duration_ms=0,
                status="error",
                error_code="credential_store_unavailable",
            )
            database.audit("models", "connection_test", canonical, result="credential_store_unavailable")
            raise HTTPException(status_code=503, detail="Credential storage is unavailable") from None
        except ModelGatewayError as error:
            database.record_model_call(
                provider=canonical,
                operation="connection_test",
                source="dashboard_settings",
                duration_ms=error.duration_ms,
                status="error",
                error_code=error.code,
            )
            database.audit("models", "connection_test", canonical, result=error.code)
            raise HTTPException(status_code=error.status_code, detail=error.detail) from None

        database.record_model_call(
            provider=canonical,
            operation="connection_test",
            source="dashboard_settings",
            duration_ms=result.latency_ms,
            status="success",
        )
        database.audit("models", "connection_test", canonical)
        return {
            "provider": result.provider,
            "status": "ok",
            "latency_ms": result.latency_ms,
        }

    @app.get("/api/models/roles")
    def list_model_roles(request: Request) -> dict[str, list[dict[str, object]]]:
        result: list[dict[str, object]] = []
        for role in db(request).get_model_roles():
            canonical = normalize_provider(role["provider"])
            credential_configured = False
            if canonical is not None:
                credential_configured = is_credential_configured(canonical)
            result.append(
                {
                    "role": role["role"],
                    "provider": role["provider"],
                    "model": role["model"],
                    "endpoint": role["endpoint"],
                    "credential_configured": credential_configured,
                    "ready": bool(role["model"]) and canonical is not None and credential_configured,
                }
            )
        result.append(
            {
                "role": "embedding",
                "provider": "local",
                "model": "BAAI/bge-small-zh-v1.5",
                "endpoint": "",
                "credential_configured": False,
                "ready": True,
                "local_only": True,
            }
        )
        return {"roles": result}

    @app.put("/api/models/roles/{role}")
    def update_model_role(role: str, payload: ModelRoleUpdate, request: Request) -> dict[str, object]:
        if role == "embedding":
            raise HTTPException(
                status_code=422,
                detail="Embedding uses the local model and cannot be configured as an external route",
            )
        if role not in MODEL_ROLES:
            raise HTTPException(status_code=422, detail="Unsupported model role")
        canonical = credential_provider(payload.provider)
        endpoint = str(payload.endpoint)
        try:
            build_chat_url(canonical, endpoint, payload.model)
        except ModelGatewayError as error:
            raise HTTPException(status_code=error.status_code, detail=error.detail) from None
        database = db(request)
        database.save_model_role(
            role=role,
            provider=payload.provider,
            model=payload.model,
            endpoint=endpoint,
        )
        database.audit("models", "update_role", role)
        return {
            "role": role,
            "provider": canonical,
            "model": payload.model,
            "endpoint": endpoint,
        }

    @app.post("/api/models/generate")
    async def generate_model_text(payload: ModelGenerateRequest, request: Request) -> dict[str, object]:
        role = payload.role.strip()
        if role == "embedding":
            raise HTTPException(status_code=422, detail="Embedding role does not generate text")
        if role not in MODEL_ROLES:
            raise HTTPException(status_code=422, detail="Unsupported model role")
        database = db(request)
        roles = {item["role"]: item for item in database.get_model_roles()}
        config = roles.get(role)
        canonical = (
            credential_provider(config["provider"])
            if config and config.get("provider")
            else None
        )
        if not config or not config.get("model") or canonical is None:
            database.record_model_call(
                provider=canonical or "unconfigured",
                operation="generate",
                source="dashboard_generation",
                duration_ms=0,
                status="error",
                error_code="role_not_configured",
                role=role,
            )
            database.audit("models", "generate", role, result="role_not_configured")
            raise HTTPException(status_code=409, detail="Model role is not configured")

        try:
            result = await request.app.state.model_gateway.generate(
                provider=canonical,
                endpoint=config["endpoint"],
                model=config["model"],
                prompt=payload.prompt,
                system=payload.system,
                max_tokens=payload.max_tokens,
                temperature=payload.temperature,
                role=role,
            )
        except ModelRequestCancelled as error:
            database.record_model_call(
                provider=canonical,
                operation="generate",
                source="dashboard_generation",
                duration_ms=error.duration_ms,
                status="cancelled",
                error_code="cancelled",
                role=role,
            )
            database.audit("models", "generate", role, result="cancelled")
            raise asyncio.CancelledError from None
        except CredentialStorageError:
            database.record_model_call(
                provider=canonical,
                operation="generate",
                source="dashboard_generation",
                duration_ms=0,
                status="error",
                error_code="credential_store_unavailable",
                role=role,
            )
            database.audit("models", "generate", role, result="credential_store_unavailable")
            raise HTTPException(status_code=503, detail="Credential storage is unavailable") from None
        except ModelGatewayError as error:
            database.record_model_call(
                provider=canonical,
                operation="generate",
                source="dashboard_generation",
                duration_ms=error.duration_ms,
                status="error",
                error_code=error.code,
                role=role,
            )
            database.audit("models", "generate", role, result=error.code)
            raise HTTPException(status_code=error.status_code, detail=error.detail) from None

        database.record_model_call(
            provider=result.provider,
            operation="generate",
            source="dashboard_generation",
            duration_ms=result.latency_ms,
            status="success",
            model=result.model,
            role=result.role,
            prompt_tokens=result.prompt_tokens,
            completion_tokens=result.completion_tokens,
            total_tokens=result.total_tokens,
        )
        database.audit("models", "generate", role)
        return {
            "role": result.role,
            "provider": result.provider,
            "model": result.model,
            "status": "ok",
            "content": result.content,
            "latency_ms": result.latency_ms,
            "usage": {
                "prompt_tokens": result.prompt_tokens,
                "completion_tokens": result.completion_tokens,
                "total_tokens": result.total_tokens,
            },
        }

    @app.get("/api/zotero/status")
    def zotero_status(request: Request) -> dict[str, object]:
        database = db(request)
        status = database.get_zotero_status()
        return {
            "available": active_zotero_database.is_file(),
            "database_path": str(active_zotero_database),
            "last_sync": status["last_sync"],
            "item_count": status["item_count"],
            "auto_sync_enabled": zotero_auto_sync,
            "auto_sync_interval_hours": zotero_auto_sync_hours,
        }

    @app.post("/api/zotero/sync", status_code=status.HTTP_201_CREATED)
    def sync_zotero(request: Request) -> dict[str, object]:
        database = db(request)
        try:
            return run_zotero_sync(database)
        except ZoteroReadError as error:
            raise HTTPException(status_code=503, detail=str(error)) from None

    @app.get("/api/paperqa/status")
    def paperqa_status(request: Request) -> dict[str, object]:
        try:
            return request.app.state.paperqa_service.status()
        except CredentialStorageError:
            raise HTTPException(
                status_code=503, detail="Credential storage is unavailable"
            ) from None

    @app.post("/api/paperqa/index", status_code=status.HTTP_201_CREATED)
    async def paperqa_index(
        payload: PaperQAIndexRequest,
        request: Request,
    ) -> dict[str, object]:
        if payload.role not in SUPPORTED_PAPERQA_ROLES:
            raise HTTPException(status_code=422, detail="该模型角色不支持论文问答")
        database = db(request)
        try:
            source_path = resolve_source_path(payload.path, library_roots)
            source_files = discover_source_files(source_path, library_roots)
        except PermissionError as error:
            database.audit("paperqa", "index", payload.path, result="path_forbidden")
            raise HTTPException(status_code=403, detail=str(error)) from error
        except FileNotFoundError as error:
            database.audit("paperqa", "index", payload.path, result="path_not_found")
            raise HTTPException(status_code=404, detail=str(error)) from error
        except ValueError as error:
            database.audit("paperqa", "index", payload.path, result="invalid_path")
            raise HTTPException(status_code=400, detail=str(error)) from error

        try:
            result = await request.app.state.paperqa_service.build_index(source_files)
        except PaperQAError as error:
            database.audit("paperqa", "index", payload.path, result=error.code)
            raise HTTPException(
                status_code=error.status_code, detail=error.detail
            ) from None
        database.audit("paperqa", "index", payload.path)
        return result

    @app.post("/api/paperqa/ask")
    async def paperqa_ask(
        payload: PaperQAAskRequest,
        request: Request,
    ) -> dict[str, object]:
        if payload.role not in SUPPORTED_PAPERQA_ROLES:
            raise HTTPException(status_code=422, detail="该模型角色不支持论文问答")
        database = db(request)
        provider, model = paperqa_provider_for_role(request, payload.role)
        try:
            result = await request.app.state.paperqa_service.ask(
                question=payload.question,
                role=payload.role,
                max_tokens=payload.max_tokens,
                temperature=payload.temperature,
            )
        except PaperQAError as error:
            database.record_model_call(
                provider=provider,
                operation="paperqa_ask",
                source="dashboard_paperqa",
                duration_ms=0,
                status="error",
                error_code=error.code,
                role=payload.role,
                model=model,
            )
            database.audit("paperqa", "ask", payload.role, result=error.code)
            raise HTTPException(
                status_code=error.status_code, detail=error.detail
            ) from None
        except CredentialStorageError:
            database.record_model_call(
                provider=provider,
                operation="paperqa_ask",
                source="dashboard_paperqa",
                duration_ms=0,
                status="error",
                error_code="credential_store_unavailable",
                role=payload.role,
                model=model,
            )
            database.audit(
                "paperqa",
                "ask",
                payload.role,
                result="credential_store_unavailable",
            )
            raise HTTPException(
                status_code=503, detail="Credential storage is unavailable"
            ) from None
        database.record_model_call(
            provider=provider,
            operation="paperqa_ask",
            source="dashboard_paperqa",
            duration_ms=int(result["latency_ms"]),
            status="success",
            role=payload.role,
            model=result.get("model") or model,
            prompt_tokens=result.get("prompt_tokens"),
            completion_tokens=result.get("completion_tokens"),
            total_tokens=result.get("total_tokens"),
        )
        database.audit("paperqa", "ask", payload.role)
        return result

    @app.get("/api/ops/status")
    def ops_status(request: Request) -> dict[str, object]:
        database = db(request)
        quick_check = database.quick_check()
        usage = shutil.disk_usage(storage_root)
        free_percent = round(usage.free / usage.total * 100, 1) if usage.total else 0.0
        backup_dir = storage_root / "backups" / "database"
        latest_backup: dict[str, object] | None = None
        if backup_dir.is_dir():
            candidates = sorted(
                backup_dir.glob("ai-pc-*.sqlite3"),
                key=lambda path: path.stat().st_mtime,
                reverse=True,
            )
            if candidates:
                latest = candidates[0]
                age_days = max(
                    0.0,
                    (datetime.now() - datetime.fromtimestamp(latest.stat().st_mtime)).total_seconds()
                    / 86_400,
                )
                latest_backup = {
                    "path": str(latest),
                    "size_bytes": latest.stat().st_size,
                    "age_days": round(age_days, 1),
                }

        warnings: list[str] = []
        if quick_check != "ok":
            warnings.append("数据库完整性检查未通过")
        if free_percent < 15 or usage.free < 20 * 1024**3:
            warnings.append("磁盘剩余空间低于建议阈值")
        if latest_backup is None:
            warnings.append("尚未创建一致性备份")
        elif float(latest_backup["age_days"]) > 7:
            warnings.append("最近一次备份已超过 7 天")

        return {
            "database": {
                "path": str(database.path),
                "size_bytes": database.path.stat().st_size,
                "quick_check": quick_check,
            },
            "storage": {
                "root": str(storage_root),
                "total_bytes": usage.total,
                "free_bytes": usage.free,
                "free_percent": free_percent,
            },
            "backup": latest_backup,
            "backup_settings": read_backup_settings(database),
            "warnings": warnings,
            "ok": not warnings,
        }

    @app.post("/api/ops/backup", status_code=status.HTTP_201_CREATED)
    def run_backup(request: Request) -> dict[str, object]:
        database = db(request)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        destination = storage_root / "backups" / "database" / f"ai-pc-{stamp}.sqlite3"
        try:
            database.backup_to(destination)
            quick_check = database.verify_backup(destination)
        except Exception:
            raise HTTPException(status_code=503, detail="Database backup failed") from None
        if quick_check != "ok":
            raise HTTPException(status_code=503, detail="Database backup failed verification")
        database.audit("ops", "backup", destination.name)
        return {
            "path": str(destination),
            "size_bytes": destination.stat().st_size,
            "quick_check": quick_check,
        }

    @app.get("/api/ops/backup/settings")
    def get_backup_settings(request: Request) -> dict[str, object]:
        return read_backup_settings(db(request))

    @app.put("/api/ops/backup/settings")
    def update_backup_settings(
        payload: BackupSettingsUpdate,
        request: Request,
    ) -> dict[str, object]:
        return save_backup_settings(
            db(request),
            enabled=payload.enabled,
            interval_hours=payload.interval_hours,
            keep_count=payload.keep_count,
        )

    @app.get("/api/deeptutor/status")
    def deeptutor_status() -> dict[str, object]:
        return active_deeptutor_service.status()

    @app.post("/api/deeptutor/run")
    def deeptutor_run(payload: DeepTutorRunRequest) -> dict[str, object]:
        try:
            return active_deeptutor_service.run(
                capability=payload.capability,
                prompt=payload.prompt,
                role=payload.role,
                language=payload.language,
                session_id=payload.session_id,
                timeout_seconds=float(payload.timeout_seconds),
            )
        except DeepTutorError as error:
            raise HTTPException(
                status_code=error.status_code,
                detail=error.detail,
            ) from None

    @app.get("/api/browser/status")
    def browser_status() -> dict[str, object]:
        return active_browser_controller.status()

    @app.put("/api/browser/allowlist")
    def browser_allowlist(payload: BrowserAllowlistUpdate, request: Request) -> dict[str, object]:
        domains = active_browser_controller.set_allowlist(payload.domains)
        db(request).audit("browser", "update_allowlist", None)
        return {"allowlist": domains}

    @app.get("/api/browser/actions")
    def browser_actions(
        limit: int = Query(default=20, ge=1, le=50),
    ) -> list[dict[str, object]]:
        return active_browser_controller.list_actions(limit)

    @app.post("/api/browser/actions", status_code=status.HTTP_202_ACCEPTED)
    async def browser_submit(payload: BrowserActionCreate) -> dict[str, object]:
        try:
            return await active_browser_controller.submit(
                action=payload.action,
                url=payload.url,
                selector=payload.selector,
                text=payload.text,
                timeout_ms=payload.timeout_ms,
                source="dashboard",
            )
        except BrowserError as error:
            raise HTTPException(status_code=error.status_code, detail=error.detail) from None

    @app.post("/api/browser/actions/{action_id}/approve")
    async def browser_approve(action_id: str) -> dict[str, object]:
        try:
            return await active_browser_controller.approve(action_id)
        except BrowserError as error:
            raise HTTPException(status_code=error.status_code, detail=error.detail) from None

    @app.post("/api/browser/actions/{action_id}/reject")
    async def browser_reject(action_id: str) -> dict[str, object]:
        try:
            return await active_browser_controller.reject(action_id)
        except BrowserError as error:
            raise HTTPException(status_code=error.status_code, detail=error.detail) from None

    @app.post("/api/browser/stop")
    async def browser_stop() -> dict[str, object]:
        await active_browser_controller.stop()
        return {"stopped": True}

    @app.post("/api/browser/resume")
    async def browser_resume() -> dict[str, object]:
        await active_browser_controller.resume()
        return {"stopped": False}

    @app.get("/api/audit")
    def list_audit(request: Request, limit: int = Query(default=50, ge=1, le=200)) -> list[dict]:
        return db(request).query_all("SELECT * FROM audit_events ORDER BY id DESC LIMIT ?", (limit,))

    if serve_static:
        assets = PROJECT_DIR
        app.mount("/assets", StaticFiles(directory=assets), name="assets")

        @app.get("/", include_in_schema=False)
        def dashboard() -> FileResponse:
            return FileResponse(PROJECT_DIR / "index.html", headers={"Cache-Control": "no-store"})

        @app.get("/styles.css", include_in_schema=False)
        def styles() -> FileResponse:
            return FileResponse(
                PROJECT_DIR / "styles.css",
                media_type="text/css",
                headers={"Cache-Control": "no-store"},
            )

        @app.get("/app.js", include_in_schema=False)
        def script() -> FileResponse:
            return FileResponse(
                PROJECT_DIR / "app.js",
                media_type="text/javascript",
                headers={"Cache-Control": "no-store"},
            )

    return app


app = create_app()
