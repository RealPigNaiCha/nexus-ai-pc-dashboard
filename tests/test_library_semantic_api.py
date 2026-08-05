from pathlib import Path

from fastapi.testclient import TestClient

from backend.app import create_app
from backend.semantic import (
    DEFAULT_MODEL_NAME,
    DEGRADED_REASON,
    SemanticOperationResult,
    SemanticSearchHit,
    SemanticSearchResult,
    SemanticStatus,
)


class StubSemanticIndex:
    def __init__(self, *, degraded: bool = False) -> None:
        self.degraded = degraded
        self.indexed = []
        self.rebuilt = []

    def index_document(self, document):
        self.indexed.append(document)
        return SemanticOperationResult(
            success=not self.degraded,
            degraded=self.degraded,
            documents_processed=0 if self.degraded else 1,
            chunks_indexed=0 if self.degraded else len(document.chunks),
            reason=DEGRADED_REASON if self.degraded else None,
        )

    def search(self, query: str, *, limit: int = 10):
        if self.degraded:
            return SemanticSearchResult(hits=[], degraded=True, reason=DEGRADED_REASON)
        document = self.indexed[0]
        chunk = document.chunks[0]
        return SemanticSearchResult(
            hits=[
                SemanticSearchHit(
                    point_id="point-1",
                    score=0.92,
                    document_id=document.document_id,
                    chunk_id=chunk.chunk_id,
                    text=chunk.text,
                    title=document.title,
                    source_path=document.source_path,
                    page=chunk.page,
                    paragraph=chunk.paragraph,
                    metadata={"document_type": "TXT"},
                )
            ],
            degraded=False,
        )

    def status(self):
        return SemanticStatus(
            available=not self.degraded,
            degraded=self.degraded,
            model_name=DEFAULT_MODEL_NAME,
            collection_name="test_chunks",
            storage_path="C:\\AI-PC\\data\\index\\qdrant",
            point_count=len(self.indexed),
            reason=DEGRADED_REASON if self.degraded else None,
        )

    def rebuild(self, documents):
        self.rebuilt = list(documents)
        return SemanticOperationResult(
            success=True,
            degraded=False,
            documents_processed=len(self.rebuilt),
            chunks_indexed=sum(len(document.chunks) for document in self.rebuilt),
        )


def make_client(tmp_path: Path, semantic_index: StubSemanticIndex):
    library_root = tmp_path / "library"
    library_root.mkdir()
    app = create_app(
        tmp_path / "semantic-api.sqlite3",
        serve_static=False,
        allowed_library_roots=[library_root],
        semantic_index=semantic_index,
    )
    return library_root, TestClient(app)


def test_import_hybrid_search_status_and_rebuild(tmp_path: Path) -> None:
    semantic_index = StubSemanticIndex()
    library_root, client = make_client(tmp_path, semantic_index)
    source = library_root / "linear-algebra.txt"
    source.write_text("The spectral radius is bounded by a matrix norm.", encoding="utf-8")

    with client:
        imported = client.post("/api/library/import", json={"path": str(source)})
        assert imported.status_code == 201
        assert imported.json()["semantic_documents_indexed"] == 1
        assert imported.json()["semantic_chunks_indexed"] == 1
        assert imported.json()["semantic_degraded"] is False
        assert semantic_index.indexed[0].source_path == str(source.resolve())

        hybrid = client.get(
            "/api/library/search",
            params={"q": "spectral radius", "mode": "hybrid", "limit": 10},
        )
        assert hybrid.status_code == 200
        assert len(hybrid.json()) == 1
        assert hybrid.json()[0]["search_mode"] == "hybrid"
        assert hybrid.json()[0]["semantic_score"] == 0.92

        semantic = client.get(
            "/api/library/search",
            params={"q": "eigenvalue magnitude", "mode": "semantic"},
        )
        assert semantic.json()[0]["search_mode"] == "semantic"

        status = client.get("/api/library/semantic/status").json()
        assert status["available"] is True
        assert status["model_name"] == DEFAULT_MODEL_NAME

        rebuilt = client.post("/api/library/semantic/rebuild")
        assert rebuilt.status_code == 200
        assert rebuilt.json()["documents_processed"] == 1
        assert rebuilt.json()["chunks_indexed"] == 1
        assert len(semantic_index.rebuilt) == 1


def test_degraded_semantic_search_falls_back_to_sqlite(tmp_path: Path) -> None:
    semantic_index = StubSemanticIndex(degraded=True)
    library_root, client = make_client(tmp_path, semantic_index)
    source = library_root / "fallback.txt"
    source.write_text("fallbacktoken remains searchable in SQLite.", encoding="utf-8")

    with client:
        imported = client.post("/api/library/import", json={"path": str(source)})
        assert imported.status_code == 201
        assert imported.json()["semantic_degraded"] is True

        results = client.get(
            "/api/library/search",
            params={"q": "fallbacktoken", "mode": "hybrid"},
        ).json()
        assert len(results) == 1
        assert results[0]["search_mode"] == "lexical"
        assert results[0]["semantic_degraded"] is True
        assert "<mark>fallbacktoken</mark>" in results[0]["snippet"]

        status = client.get("/api/library/semantic/status").json()
        assert status["degraded"] is True
        assert status["reason"] == DEGRADED_REASON
