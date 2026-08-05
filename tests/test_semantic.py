import math
from pathlib import Path
from types import SimpleNamespace

import pytest

from backend.semantic import (
    DEFAULT_MODEL_NAME,
    DEGRADED_REASON,
    SemanticChunk,
    SemanticDocument,
    SemanticIndex,
)


class FakeEmbedder:
    def __init__(self) -> None:
        self.document_batches: list[list[str]] = []
        self.queries: list[str] = []

    def embed(self, documents, **_kwargs):
        batch = list(documents)
        self.document_batches.append(batch)
        return [self._vector(text) for text in batch]

    def query_embed(self, query, **_kwargs):
        self.queries.append(query)
        return [self._vector(query)]

    @staticmethod
    def _vector(text: str) -> list[float]:
        text = text.casefold()
        if "limit" in text:
            return [1.0, 0.0, 0.0]
        if "matrix" in text:
            return [0.0, 1.0, 0.0]
        return [0.0, 0.0, 1.0]


class RecordingQdrant:
    def __init__(self) -> None:
        self.exists = False
        self.points = {}
        self.events: list[tuple[str, object]] = []
        self.vector_config = None
        self.closed = False

    def collection_exists(self, _collection_name: str) -> bool:
        return self.exists

    def create_collection(self, collection_name: str, vectors_config, **_kwargs) -> bool:
        self.exists = True
        self.vector_config = vectors_config
        self.events.append(("create_collection", collection_name))
        return True

    def delete_collection(self, collection_name: str) -> bool:
        self.exists = False
        self.points.clear()
        self.events.append(("delete_collection", collection_name))
        return True

    def delete(self, collection_name: str, points_selector, **_kwargs):
        document_id = points_selector.filter.must[0].match.value
        self.points = {
            point_id: point
            for point_id, point in self.points.items()
            if point.payload["document_id"] != document_id
        }
        self.events.append(("delete_document", document_id))
        return SimpleNamespace(status="completed")

    def upsert(self, collection_name: str, points, **_kwargs):
        batch = list(points)
        for point in batch:
            self.points[str(point.id)] = point
        self.events.append(("upsert", len(batch)))
        return SimpleNamespace(status="completed")

    def query_points(
        self,
        collection_name: str,
        query,
        query_filter,
        limit: int,
        score_threshold,
        **_kwargs,
    ):
        document_id = None
        if query_filter is not None:
            document_id = query_filter.must[0].match.value
        matches = []
        for point in self.points.values():
            if document_id is not None and point.payload["document_id"] != document_id:
                continue
            score = _cosine(query, point.vector)
            if score_threshold is None or score >= score_threshold:
                matches.append(
                    SimpleNamespace(id=point.id, score=score, payload=dict(point.payload))
                )
        matches.sort(key=lambda item: item.score, reverse=True)
        self.events.append(("query", document_id))
        return SimpleNamespace(points=matches[:limit])

    def count(self, collection_name: str, **_kwargs):
        return SimpleNamespace(count=len(self.points))

    def close(self) -> None:
        self.closed = True


class BrokenQdrant:
    def collection_exists(self, _collection_name: str) -> bool:
        raise RuntimeError("private backend details must not escape")


def _cosine(left, right) -> float:
    numerator = sum(a * b for a, b in zip(left, right, strict=True))
    denominator = math.sqrt(sum(value * value for value in left)) * math.sqrt(
        sum(value * value for value in right)
    )
    return numerator / denominator


def _document(
    document_id: int,
    *chunks: SemanticChunk,
    title: str = "Calculus notes",
) -> SemanticDocument:
    return SemanticDocument(
        document_id=document_id,
        title=title,
        source_path=f"C:\\library\\{document_id}.md",
        chunks=list(chunks),
        metadata={"course": "mathematics"},
    )


def test_document_replace_is_filtered_batched_and_keeps_references(tmp_path: Path) -> None:
    embedder = FakeEmbedder()
    client = RecordingQdrant()
    index = SemanticIndex(
        tmp_path / "unused",
        embedder=embedder,
        client=client,
        vector_size=3,
        upsert_batch_size=2,
    )
    document = _document(
        7,
        SemanticChunk(11, "limit definition", page=2, paragraph=1, metadata={"kind": "definition"}),
        SemanticChunk(12, "limit example", page=2, paragraph=2),
        SemanticChunk(13, "limit exercise", page=3, paragraph=1),
    )

    result = index.index_document(document)

    assert index.model_name == DEFAULT_MODEL_NAME
    assert result.success is True
    assert result.chunks_indexed == 3
    assert client.vector_config.size == 3
    assert client.events[-3:] == [("delete_document", 7), ("upsert", 2), ("upsert", 1)]
    first_payload = next(
        point.payload for point in client.points.values() if point.payload["chunk_id"] == 11
    )
    assert first_payload == {
        "course": "mathematics",
        "kind": "definition",
        "document_id": 7,
        "chunk_id": 11,
        "text": "limit definition",
        "title": "Calculus notes",
        "source_path": "C:\\library\\7.md",
        "page": 2,
        "paragraph": 1,
    }

    replacement = _document(
        7,
        SemanticChunk(21, "matrix replacement", page=4, paragraph=1),
        title="Linear algebra notes",
    )
    replaced = index.index_document(replacement)
    assert replaced.success is True
    assert len(client.points) == 1
    assert client.events[-2:] == [("delete_document", 7), ("upsert", 1)]
    assert index.search("limit", score_threshold=0.9).hits == []
    hit = index.search("matrix", score_threshold=0.9).hits[0]
    assert hit.document_id == 7
    assert hit.chunk_id == 21
    assert hit.title == "Linear algebra notes"
    assert hit.metadata == {"course": "mathematics"}


def test_search_supports_document_filter_and_status(tmp_path: Path) -> None:
    embedder = FakeEmbedder()
    client = RecordingQdrant()
    index = SemanticIndex(tmp_path, embedder=embedder, client=client, vector_size=3)
    index.index_document(_document(1, SemanticChunk(1, "matrix eigenvalue")))
    index.index_document(_document(2, SemanticChunk(2, "matrix determinant")))

    result = index.search("matrix", document_id=2, limit=5)
    status = index.status()

    assert result.degraded is False
    assert [hit.document_id for hit in result.hits] == [2]
    assert embedder.queries == ["matrix"]
    assert status.available is True
    assert status.degraded is False
    assert status.point_count == 2
    assert status.reason is None


def test_rebuild_recreates_collection_and_validates_documents(tmp_path: Path) -> None:
    client = RecordingQdrant()
    index = SemanticIndex(tmp_path, embedder=FakeEmbedder(), client=client, vector_size=3)
    index.index_document(_document(1, SemanticChunk(1, "old limit chunk")))

    rebuilt = index.rebuild(
        [
            _document(2, SemanticChunk(2, "matrix one")),
            _document(3, SemanticChunk(3, "limit one"), SemanticChunk(4, "limit two")),
        ]
    )

    assert rebuilt.success is True
    assert rebuilt.documents_processed == 2
    assert rebuilt.chunks_indexed == 3
    assert ("delete_collection", index.collection_name) in client.events
    assert index.status().point_count == 3
    assert all(point.payload["document_id"] != 1 for point in client.points.values())

    events_before = list(client.events)
    with pytest.raises(ValueError, match="unique document_id"):
        index.rebuild(
            [
                _document(4, SemanticChunk(5, "limit")),
                _document(4, SemanticChunk(6, "matrix")),
            ]
        )
    assert client.events == events_before


def test_qdrant_path_persists_without_loading_real_model(tmp_path: Path) -> None:
    storage_path = tmp_path / "qdrant"
    document = _document(9, SemanticChunk(90, "matrix original", page=4))
    replacement = _document(9, SemanticChunk(91, "limit persisted", page=5))

    with SemanticIndex(storage_path, embedder=FakeEmbedder(), vector_size=3) as index:
        assert index.index_document(document).success is True
        assert index.index_document(replacement).success is True
        assert index.status().point_count == 1

    with SemanticIndex(storage_path, embedder=FakeEmbedder(), vector_size=3) as reopened:
        assert reopened.status().point_count == 1
        assert reopened.search("matrix", score_threshold=0.9).hits == []
        hit = reopened.search("limit", score_threshold=0.9).hits[0]
        assert hit.document_id == 9
        assert hit.chunk_id == 91
        assert hit.page == 5


def test_real_qdrant_rebuild_clears_stale_points(tmp_path: Path) -> None:
    storage_path = tmp_path / "rebuild-qdrant"
    old_document = _document(
        1,
        SemanticChunk(1, "old first chunk"),
        SemanticChunk(2, "old second chunk"),
    )
    new_document = _document(2, SemanticChunk(3, "new only chunk"))

    with SemanticIndex(storage_path, embedder=FakeEmbedder(), vector_size=3) as index:
        assert index.index_document(old_document).success is True
        rebuilt = index.rebuild([new_document])
        assert rebuilt.success is True
        assert index.status().point_count == 1
        assert all(hit.document_id != 1 for hit in index.search("old").hits)


def test_unavailable_index_returns_explicit_fts_degradation(tmp_path: Path) -> None:
    index = SemanticIndex(
        tmp_path,
        embedder=FakeEmbedder(),
        client=BrokenQdrant(),
        vector_size=3,
    )
    document = _document(1, SemanticChunk(1, "limit"))

    status = index.status()
    search = index.search("limit")
    indexed = index.index_document(document)
    rebuilt = index.rebuild([document])

    assert status.available is False
    assert status.degraded is True
    assert status.reason == DEGRADED_REASON
    assert search.hits == []
    assert search.degraded is True
    assert search.reason == DEGRADED_REASON
    assert indexed.success is False and indexed.degraded is True
    assert rebuilt.success is False and rebuilt.degraded is True
    assert "private backend details" not in status.reason


def test_invalid_input_is_rejected_before_index_mutation(tmp_path: Path) -> None:
    client = RecordingQdrant()
    index = SemanticIndex(tmp_path, embedder=FakeEmbedder(), client=client, vector_size=3)
    events_before = list(client.events)

    with pytest.raises(ValueError, match="JSON serializable"):
        index.index_document(
            SemanticDocument(
                document_id=1,
                title="Invalid metadata",
                source_path=None,
                chunks=[SemanticChunk(1, "limit", metadata={"path": tmp_path})],
            )
        )
    with pytest.raises(ValueError, match="query must not be blank"):
        index.search("   ")
    assert client.events == events_before
