from __future__ import annotations

import json
import math
import threading
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Mapping, Protocol, Sequence

from fastembed import TextEmbedding
from qdrant_client import QdrantClient, models


DEFAULT_MODEL_NAME = "BAAI/bge-small-zh-v1.5"
DEFAULT_VECTOR_SIZE = 512
DEFAULT_COLLECTION_NAME = "nexus_ai_pc_chunks"
DEFAULT_STORAGE_PATH = Path(r"C:\AI-PC\data\index\qdrant")
DEGRADED_REASON = "Semantic index unavailable; use SQLite FTS fallback."

_POINT_NAMESPACE = uuid.UUID("9d6acb4b-f434-58f6-973d-36f31bf09ba8")
_REFERENCE_KEYS = frozenset(
    {"document_id", "chunk_id", "text", "title", "source_path", "page", "paragraph"}
)


class EmbeddingBackend(Protocol):
    def embed(self, documents: Iterable[str], **kwargs: Any) -> Iterable[Any]: ...

    def query_embed(self, query: str | Iterable[str], **kwargs: Any) -> Iterable[Any]: ...


@dataclass(frozen=True, slots=True)
class SemanticChunk:
    chunk_id: int | str
    text: str
    page: int | None = None
    paragraph: int | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class SemanticDocument:
    document_id: int
    title: str
    source_path: str | None
    chunks: Sequence[SemanticChunk]
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class SemanticSearchHit:
    point_id: str
    score: float
    document_id: int
    chunk_id: int | str
    text: str
    title: str
    source_path: str | None
    page: int | None
    paragraph: int | None
    metadata: dict[str, Any]


@dataclass(frozen=True, slots=True)
class SemanticSearchResult:
    hits: list[SemanticSearchHit]
    degraded: bool
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class SemanticStatus:
    available: bool
    degraded: bool
    model_name: str
    collection_name: str
    storage_path: str
    point_count: int | None
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class SemanticOperationResult:
    success: bool
    degraded: bool
    documents_processed: int
    chunks_indexed: int
    reason: str | None = None


class SemanticIndex:
    def __init__(
        self,
        storage_path: Path | str = DEFAULT_STORAGE_PATH,
        *,
        model_name: str = DEFAULT_MODEL_NAME,
        collection_name: str = DEFAULT_COLLECTION_NAME,
        vector_size: int = DEFAULT_VECTOR_SIZE,
        embedding_batch_size: int = 64,
        upsert_batch_size: int = 64,
        model_cache_path: Path | str | None = None,
        embedder: EmbeddingBackend | None = None,
        client: Any | None = None,
    ) -> None:
        if vector_size < 1:
            raise ValueError("vector_size must be positive")
        if embedding_batch_size < 1 or upsert_batch_size < 1:
            raise ValueError("batch sizes must be positive")

        self.storage_path = Path(storage_path)
        self.model_name = model_name
        self.collection_name = collection_name
        self.vector_size = vector_size
        self.embedding_batch_size = embedding_batch_size
        self.upsert_batch_size = upsert_batch_size
        self._lock = threading.RLock()
        self._embedder: EmbeddingBackend | None = embedder
        self._client: Any | None = client
        self._degraded_reason: str | None = None

        try:
            if self._embedder is None:
                cache_path = Path(model_cache_path) if model_cache_path else self.storage_path.parent / "models" / "fastembed"
                self._embedder = TextEmbedding(
                    model_name=self.model_name,
                    cache_dir=str(cache_path),
                    lazy_load=True,
                )
            if self._client is None:
                self.storage_path.mkdir(parents=True, exist_ok=True)
                self._client = QdrantClient(path=str(self.storage_path))
            self._ensure_collection()
        except Exception:
            self._mark_degraded()

    def index_document(self, document: SemanticDocument) -> SemanticOperationResult:
        self._validate_document(document)
        with self._lock:
            if not self._dependencies_ready():
                return self._failed_operation()
            try:
                self._ensure_collection()
                indexed = self._replace_document(document)
            except Exception:
                self._mark_degraded()
                return self._failed_operation()
            self._mark_ready()
            return SemanticOperationResult(
                success=True,
                degraded=False,
                documents_processed=1,
                chunks_indexed=indexed,
            )

    def delete_document(self, document_id: int) -> SemanticOperationResult:
        self._validate_document_id(document_id)
        with self._lock:
            if not self._dependencies_ready():
                return self._failed_operation()
            try:
                self._ensure_collection()
                self._delete_document_points(document_id)
            except Exception:
                self._mark_degraded()
                return self._failed_operation()
            self._mark_ready()
            return SemanticOperationResult(
                success=True,
                degraded=False,
                documents_processed=1,
                chunks_indexed=0,
            )

    def search(
        self,
        query: str,
        *,
        limit: int = 10,
        score_threshold: float | None = None,
        document_id: int | None = None,
    ) -> SemanticSearchResult:
        query = query.strip()
        if not query:
            raise ValueError("query must not be blank")
        if not 1 <= limit <= 100:
            raise ValueError("limit must be between 1 and 100")
        if score_threshold is not None and not math.isfinite(score_threshold):
            raise ValueError("score_threshold must be finite")
        if document_id is not None:
            self._validate_document_id(document_id)

        with self._lock:
            if not self._dependencies_ready():
                return self._degraded_search()
            try:
                self._ensure_collection()
                vectors = self._embedder.query_embed(query)
                vector = self._first_vector(vectors)
                response = self._client.query_points(
                    collection_name=self.collection_name,
                    query=vector,
                    query_filter=self._document_filter(document_id) if document_id is not None else None,
                    limit=limit,
                    score_threshold=score_threshold,
                    with_payload=True,
                    with_vectors=False,
                )
                hits = self._search_hits(response.points)
            except Exception:
                self._mark_degraded()
                return self._degraded_search()
            self._mark_ready()
            return SemanticSearchResult(hits=hits, degraded=False)

    def status(self) -> SemanticStatus:
        point_count: int | None = None
        with self._lock:
            if self._dependencies_ready():
                try:
                    self._ensure_collection()
                    point_count = int(
                        self._client.count(
                            collection_name=self.collection_name,
                            exact=True,
                        ).count
                    )
                except Exception:
                    self._mark_degraded()

            degraded = self._degraded_reason is not None or not self._dependencies_ready()
            return SemanticStatus(
                available=not degraded,
                degraded=degraded,
                model_name=self.model_name,
                collection_name=self.collection_name,
                storage_path=str(self.storage_path),
                point_count=point_count,
                reason=DEGRADED_REASON if degraded else None,
            )

    def rebuild(self, documents: Iterable[SemanticDocument]) -> SemanticOperationResult:
        materialized = list(documents)
        document_ids: set[int] = set()
        for document in materialized:
            self._validate_document(document)
            if document.document_id in document_ids:
                raise ValueError("rebuild documents must have unique document_id values")
            document_ids.add(document.document_id)

        with self._lock:
            if not self._dependencies_ready():
                return self._failed_operation()
            processed = 0
            chunks_indexed = 0
            try:
                if self._client.collection_exists(self.collection_name):
                    if hasattr(self._client, "scroll"):
                        self._clear_collection_points()
                    else:
                        self._client.delete_collection(self.collection_name)
                self._ensure_collection()
                for document in materialized:
                    chunks_indexed += self._replace_document(document)
                    processed += 1
            except Exception:
                self._mark_degraded()
                return self._failed_operation(processed, chunks_indexed)
            self._mark_ready()
            return SemanticOperationResult(
                success=True,
                degraded=False,
                documents_processed=processed,
                chunks_indexed=chunks_indexed,
            )

    def close(self) -> None:
        with self._lock:
            close = getattr(self._client, "close", None)
            if close is not None:
                try:
                    close()
                except Exception:
                    self._mark_degraded()

    def __enter__(self) -> SemanticIndex:
        return self

    def __exit__(self, *_args: object) -> None:
        self.close()

    def _ensure_collection(self) -> None:
        if self._client is None:
            raise RuntimeError("Qdrant client is unavailable")
        if not self._client.collection_exists(self.collection_name):
            self._client.create_collection(
                collection_name=self.collection_name,
                vectors_config=models.VectorParams(
                    size=self.vector_size,
                    distance=models.Distance.COSINE,
                    on_disk=True,
                ),
                on_disk_payload=True,
            )

    def _replace_document(self, document: SemanticDocument) -> int:
        points = self._document_points(document)
        self._delete_document_points(document.document_id)
        for start in range(0, len(points), self.upsert_batch_size):
            self._client.upsert(
                collection_name=self.collection_name,
                points=points[start : start + self.upsert_batch_size],
                wait=True,
            )
        return len(points)

    def _document_points(self, document: SemanticDocument) -> list[models.PointStruct]:
        texts = [chunk.text for chunk in document.chunks]
        if not texts:
            return []
        vectors = list(
            self._embedder.embed(
                texts,
                batch_size=self.embedding_batch_size,
            )
        )
        if len(vectors) != len(document.chunks):
            raise RuntimeError("Embedding count mismatch")

        points: list[models.PointStruct] = []
        for chunk, raw_vector in zip(document.chunks, vectors, strict=True):
            payload = dict(document.metadata)
            payload.update(chunk.metadata)
            payload.update(
                {
                    "document_id": document.document_id,
                    "chunk_id": chunk.chunk_id,
                    "text": chunk.text,
                    "title": document.title,
                    "source_path": document.source_path,
                    "page": chunk.page,
                    "paragraph": chunk.paragraph,
                }
            )
            json.dumps(payload, ensure_ascii=False, allow_nan=False)
            points.append(
                models.PointStruct(
                    id=self._point_id(document.document_id, chunk.chunk_id),
                    vector=self._vector(raw_vector),
                    payload=payload,
                )
            )
        return points

    def _delete_document_points(self, document_id: int) -> None:
        self._client.delete(
            collection_name=self.collection_name,
            points_selector=models.FilterSelector(filter=self._document_filter(document_id)),
            wait=True,
        )

    def _clear_collection_points(self) -> None:
        """Remove every point explicitly; local Qdrant can retain deleted collections briefly."""
        while True:
            points, _next_offset = self._client.scroll(
                collection_name=self.collection_name,
                limit=256,
                offset=None,
                with_payload=False,
                with_vectors=False,
            )
            if not points:
                return
            self._client.delete(
                collection_name=self.collection_name,
                points_selector=models.PointIdsList(points=[point.id for point in points]),
                wait=True,
            )

    @staticmethod
    def _document_filter(document_id: int) -> models.Filter:
        return models.Filter(
            must=[
                models.FieldCondition(
                    key="document_id",
                    match=models.MatchValue(value=document_id),
                )
            ]
        )

    def _first_vector(self, vectors: Iterable[Any]) -> list[float]:
        iterator = iter(vectors)
        try:
            raw_vector = next(iterator)
        except StopIteration as error:
            raise RuntimeError("Embedding backend returned no query vector") from error
        return self._vector(raw_vector)

    def _vector(self, raw_vector: Any) -> list[float]:
        values = raw_vector.tolist() if hasattr(raw_vector, "tolist") else list(raw_vector)
        if len(values) != self.vector_size:
            raise RuntimeError("Embedding dimension mismatch")
        vector = [float(value) for value in values]
        if not all(math.isfinite(value) for value in vector):
            raise RuntimeError("Embedding contains a non-finite value")
        return vector

    @staticmethod
    def _point_id(document_id: int, chunk_id: int | str) -> str:
        identity = f"{document_id}:{type(chunk_id).__name__}:{chunk_id}"
        return str(uuid.uuid5(_POINT_NAMESPACE, identity))

    @staticmethod
    def _search_hits(points: Iterable[Any]) -> list[SemanticSearchHit]:
        hits: list[SemanticSearchHit] = []
        for point in points:
            payload = dict(point.payload or {})
            document_id = payload.get("document_id")
            chunk_id = payload.get("chunk_id")
            if not isinstance(document_id, int) or isinstance(document_id, bool):
                continue
            if not isinstance(chunk_id, (int, str)) or isinstance(chunk_id, bool):
                continue
            metadata = {key: value for key, value in payload.items() if key not in _REFERENCE_KEYS}
            hits.append(
                SemanticSearchHit(
                    point_id=str(point.id),
                    score=float(point.score),
                    document_id=document_id,
                    chunk_id=chunk_id,
                    text=str(payload.get("text", "")),
                    title=str(payload.get("title", "")),
                    source_path=payload.get("source_path"),
                    page=payload.get("page"),
                    paragraph=payload.get("paragraph"),
                    metadata=metadata,
                )
            )
        return hits

    @staticmethod
    def _validate_document_id(document_id: int) -> None:
        if not isinstance(document_id, int) or isinstance(document_id, bool) or document_id < 1:
            raise ValueError("document_id must be a positive integer")

    def _validate_document(self, document: SemanticDocument) -> None:
        self._validate_document_id(document.document_id)
        if not isinstance(document.title, str):
            raise ValueError("title must be a string")
        if document.source_path is not None and not isinstance(document.source_path, str):
            raise ValueError("source_path must be a string or None")
        if not isinstance(document.metadata, Mapping):
            raise ValueError("document metadata must be a mapping")
        self._validate_metadata(document.metadata)

        chunk_ids: set[tuple[type, int | str]] = set()
        for chunk in document.chunks:
            if not isinstance(chunk.chunk_id, (int, str)) or isinstance(chunk.chunk_id, bool):
                raise ValueError("chunk_id must be an integer or string")
            if isinstance(chunk.chunk_id, str) and not chunk.chunk_id:
                raise ValueError("chunk_id must not be blank")
            identity = (type(chunk.chunk_id), chunk.chunk_id)
            if identity in chunk_ids:
                raise ValueError("chunk_id values must be unique within a document")
            chunk_ids.add(identity)
            if not isinstance(chunk.text, str) or not chunk.text.strip():
                raise ValueError("chunk text must not be blank")
            for field_name, value in (("page", chunk.page), ("paragraph", chunk.paragraph)):
                if value is not None and (
                    not isinstance(value, int) or isinstance(value, bool) or value < 1
                ):
                    raise ValueError(f"{field_name} must be a positive integer or None")
            if not isinstance(chunk.metadata, Mapping):
                raise ValueError("chunk metadata must be a mapping")
            self._validate_metadata(chunk.metadata)

    @staticmethod
    def _validate_metadata(metadata: Mapping[str, Any]) -> None:
        if not all(isinstance(key, str) for key in metadata):
            raise ValueError("metadata keys must be strings")
        try:
            json.dumps(dict(metadata), ensure_ascii=False, allow_nan=False)
        except (TypeError, ValueError):
            raise ValueError("metadata must be JSON serializable") from None

    def _dependencies_ready(self) -> bool:
        return self._client is not None and self._embedder is not None

    def _mark_degraded(self) -> None:
        self._degraded_reason = DEGRADED_REASON

    def _mark_ready(self) -> None:
        self._degraded_reason = None

    def _degraded_search(self) -> SemanticSearchResult:
        self._mark_degraded()
        return SemanticSearchResult(hits=[], degraded=True, reason=DEGRADED_REASON)

    def _failed_operation(
        self,
        documents_processed: int = 0,
        chunks_indexed: int = 0,
    ) -> SemanticOperationResult:
        self._mark_degraded()
        return SemanticOperationResult(
            success=False,
            degraded=True,
            documents_processed=documents_processed,
            chunks_indexed=chunks_indexed,
            reason=DEGRADED_REASON,
        )
