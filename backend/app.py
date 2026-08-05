from __future__ import annotations

import os
import shutil
from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path
from typing import Literal, Sequence

import httpx
from fastapi import FastAPI, HTTPException, Query, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, HttpUrl, SecretStr

from .credentials import (
    SUPPORTED_PROVIDERS,
    ApiCredentialStore,
    CredentialStorageError,
    KeyringBackend,
    normalize_provider,
)
from .database import Database, utc_now
from .learning import review_concept
from .library import discover_source_files, parse_document, resolve_source_path
from .research import LiteratureClient, ResearchUpstreamError
from .semantic import (
    DEFAULT_COLLECTION_NAME,
    DEFAULT_MODEL_NAME,
    DEGRADED_REASON,
    SemanticChunk,
    SemanticDocument,
    SemanticIndex,
)


PROJECT_DIR = Path(__file__).resolve().parents[1]


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


class CredentialUpdate(StrictModel):
    api_key: SecretStr = Field(min_length=1, max_length=8_192)


def create_app(
    database_path: Path | None = None,
    serve_static: bool = True,
    allowed_library_roots: Sequence[Path] | None = None,
    credential_backend: KeyringBackend | None = None,
    research_transport: httpx.BaseTransport | None = None,
    semantic_index: SemanticIndex | None = None,
) -> FastAPI:
    configured_path = os.getenv("AI_PC_DB_PATH")
    db_path = database_path or (Path(configured_path) if configured_path else PROJECT_DIR / "data" / "ai-pc.sqlite3")
    database = Database(db_path)
    credential_store = ApiCredentialStore(credential_backend)
    storage_root = db_path.parent if database_path is not None else Path(os.getenv("AI_PC_ROOT", r"C:\AI-PC"))
    library_roots = tuple(
        allowed_library_roots
        if allowed_library_roots is not None
        else (Path(r"C:\AI-PC\data\library"), Path(r"C:\AI-PC\vault"))
    )
    index_root = Path(os.getenv("AI_PC_INDEX_PATH", str(storage_root / "data" / "index")))
    owns_semantic_index = semantic_index is None and database_path is None

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
            app.state.literature_client = literature_client
            app.state.semantic_index = active_semantic_index
            yield
        finally:
            literature_client.close()
            if owns_semantic_index and active_semantic_index is not None:
                active_semantic_index.close()

    app = FastAPI(
        title="Nexus AI-PC API",
        version="0.1.0",
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
        lifespan=lifespan,
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
                (SELECT COUNT(*) FROM agent_tasks WHERE status != 'completed') AS active_agent_tasks,
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

    @app.post("/api/agent/tasks", status_code=status.HTTP_201_CREATED)
    def create_agent_task(payload: AgentTaskCreate, request: Request) -> dict:
        database = db(request)
        task_id = database.execute(
            """
            INSERT INTO agent_tasks(project, title, status, run_tests, generate_summary, allow_dependencies, created_at)
            VALUES (?, ?, 'queued', ?, ?, ?, ?)
            """,
            (
                payload.project,
                payload.title,
                int(payload.run_tests),
                int(payload.generate_summary),
                int(payload.allow_dependencies),
                utc_now(),
            ),
        )
        database.audit("agent", "create_task", str(task_id))
        return database.query_one("SELECT * FROM agent_tasks WHERE id = ?", (task_id,)) or {}

    @app.get("/api/settings")
    def get_settings(request: Request) -> dict[str, str]:
        rows = db(request).query_all("SELECT key, value FROM settings ORDER BY key")
        return {row["key"]: row["value"] for row in rows}

    @app.put("/api/settings")
    def update_settings(payload: SettingsUpdate, request: Request) -> dict[str, str]:
        database = db(request)
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

    @app.get("/api/audit")
    def list_audit(request: Request, limit: int = Query(default=50, ge=1, le=200)) -> list[dict]:
        return db(request).query_all("SELECT * FROM audit_events ORDER BY id DESC LIMIT ?", (limit,))

    if serve_static:
        assets = PROJECT_DIR
        app.mount("/assets", StaticFiles(directory=assets), name="assets")

        @app.get("/", include_in_schema=False)
        def dashboard() -> FileResponse:
            return FileResponse(PROJECT_DIR / "index.html")

        @app.get("/styles.css", include_in_schema=False)
        def styles() -> FileResponse:
            return FileResponse(PROJECT_DIR / "styles.css", media_type="text/css")

        @app.get("/app.js", include_in_schema=False)
        def script() -> FileResponse:
            return FileResponse(PROJECT_DIR / "app.js", media_type="text/javascript")

    return app


app = create_app()
