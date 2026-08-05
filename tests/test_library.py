import hashlib
import sqlite3
from pathlib import Path

import fitz
from fastapi.testclient import TestClient

from backend.app import create_app


def make_library_client(tmp_path: Path) -> tuple[Path, TestClient]:
    library_root = tmp_path / "library"
    library_root.mkdir()
    app = create_app(
        tmp_path / "library.sqlite3",
        serve_static=False,
        allowed_library_roots=[library_root],
    )
    return library_root, TestClient(app)


def test_import_markdown_and_search(tmp_path: Path) -> None:
    library_root, client = make_library_client(tmp_path)
    source = library_root / "limits.md"
    original = b"# Limits\n\nAn epsilon neighborhood controls the delta response.\n"
    source.write_bytes(original)

    with client:
        response = client.post("/api/library/import", json={"path": str(source)})
        assert response.status_code == 201
        imported = response.json()
        assert imported["changed"] is True
        assert imported["chunks_indexed"] == 2
        assert imported["document"]["title"] == "limits"
        assert imported["document"]["document_type"] == "MARKDOWN"
        assert imported["document"]["source_path"] == str(source.resolve())
        assert imported["document"]["content_hash"] == hashlib.sha256(original).hexdigest()

        search = client.get("/api/library/search", params={"q": "epsilon neighborhood", "limit": 5})
        assert search.status_code == 200
        result = search.json()[0]
        assert result["title"] == "limits"
        assert result["source_path"] == str(source.resolve())
        assert result["page"] is None
        assert result["paragraph"] == 2
        assert result["chunk_index"] == 1
        assert "epsilon neighborhood" in result["chunk"]
        assert "<mark>epsilon</mark>" in result["snippet"]
        assert "<mark>neighborhood</mark>" in result["snippet"]

    assert source.read_bytes() == original


def test_hash_idempotency_and_modified_file_rebuild(tmp_path: Path) -> None:
    library_root, client = make_library_client(tmp_path)
    source = library_root / "lecture.txt"
    duplicate = library_root / "duplicate.txt"
    source.write_text("legacytoken appears only in the old index.", encoding="utf-8")
    duplicate.write_bytes(source.read_bytes())

    with client:
        first = client.post("/api/library/import", json={"path": str(source)}).json()
        same_path = client.post("/api/library/import", json={"path": str(source)}).json()
        same_hash = client.post("/api/library/import", json={"path": str(duplicate)}).json()

        assert same_path["changed"] is False
        assert same_hash["changed"] is False
        assert same_path["document"]["id"] == first["document"]["id"]
        assert same_hash["document"]["id"] == first["document"]["id"]

        source.write_text("replacementtoken belongs to the rebuilt index.", encoding="utf-8")
        rebuilt = client.post("/api/library/import", json={"path": str(source)}).json()
        assert rebuilt["changed"] is True
        assert rebuilt["document"]["id"] == first["document"]["id"]
        assert client.get("/api/library/search", params={"q": "legacytoken"}).json() == []
        replacement = client.get("/api/library/search", params={"q": "replacementtoken"}).json()
        assert replacement[0]["document_id"] == first["document"]["id"]


def test_import_pdf_indexes_page_number_without_changing_source(tmp_path: Path) -> None:
    library_root, client = make_library_client(tmp_path)
    source = library_root / "linear-algebra.pdf"
    document = fitz.open()
    page = document.new_page()
    page.insert_text((72, 72), "The spectral radius bounds every eigenvalue.")
    document.save(source)
    document.close()
    original_hash = hashlib.sha256(source.read_bytes()).hexdigest()

    with client:
        imported = client.post("/api/library/import", json={"path": str(source)})
        assert imported.status_code == 201
        assert imported.json()["document"]["document_type"] == "PDF"
        results = client.get("/api/library/search", params={"q": "spectral radius"}).json()
        assert results[0]["page"] == 1
        assert results[0]["paragraph"] == 1

    assert hashlib.sha256(source.read_bytes()).hexdigest() == original_hash


def test_directory_import_and_chinese_substring_search(tmp_path: Path) -> None:
    library_root, client = make_library_client(tmp_path)
    notes = library_root / "notes"
    notes.mkdir()
    (notes / "limits.md").write_text("数列极限的定义与性质。", encoding="utf-8")
    (notes / "continuity.txt").write_text("连续函数保留极限运算。", encoding="utf-8")
    (notes / "ignored.docx").write_bytes(b"not supported")

    with client:
        imported = client.post("/api/library/import", json={"path": str(notes)})
        assert imported.status_code == 201
        payload = imported.json()
        assert payload["documents_seen"] == 2
        assert payload["imported_count"] == 2
        assert payload["failed_count"] == 0

        results = client.get("/api/library/search", params={"q": "极限"}).json()
        assert {result["title"] for result in results} == {"limits", "continuity"}
        assert all("<mark>极限</mark>" in result["snippet"] for result in results)


def test_modified_path_deduplicates_without_leaving_stale_chunks(tmp_path: Path) -> None:
    library_root, client = make_library_client(tmp_path)
    first = library_root / "first.txt"
    second = library_root / "second.txt"
    first.write_text("staleuniquetoken", encoding="utf-8")
    second.write_text("sharedreplacementtoken", encoding="utf-8")

    with client:
        first_id = client.post("/api/library/import", json={"path": str(first)}).json()["document"]["id"]
        second_id = client.post("/api/library/import", json={"path": str(second)}).json()["document"]["id"]
        first.write_bytes(second.read_bytes())

        rebuilt = client.post("/api/library/import", json={"path": str(first)}).json()
        assert rebuilt["changed"] is True
        assert rebuilt["document"]["id"] == second_id
        assert rebuilt["document"]["id"] != first_id
        assert client.get("/api/library/search", params={"q": "staleuniquetoken"}).json() == []
        documents = client.get("/api/library/documents").json()
        assert all(document["id"] != first_id for document in documents)


def test_import_rejects_paths_outside_allowed_roots(tmp_path: Path) -> None:
    library_root, client = make_library_client(tmp_path)
    outside = tmp_path / "outside.txt"
    outside.write_text("must not be indexed", encoding="utf-8")
    unsupported = library_root / "notes.docx"
    unsupported.write_bytes(b"not really a docx")
    empty_directory = library_root / "empty"
    empty_directory.mkdir()

    with client:
        assert client.post("/api/library/import", json={"path": str(outside)}).status_code == 403
        assert client.post("/api/library/import", json={"path": str(unsupported)}).status_code == 400
        assert client.post("/api/library/import", json={"path": str(empty_directory)}).status_code == 400
        assert client.post(
            "/api/library/import",
            json={"path": str(library_root / "missing.txt")},
        ).status_code == 404


def test_existing_database_is_migrated_without_losing_documents(tmp_path: Path) -> None:
    database_path = tmp_path / "legacy.sqlite3"
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            """
            CREATE TABLE documents (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                document_type TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                location TEXT,
                source TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            """
            INSERT INTO documents(title, document_type, status, created_at, updated_at)
            VALUES ('Existing note', 'NOTE', 'ready', '2026-01-01', '2026-01-01')
            """
        )

    library_root = tmp_path / "library"
    library_root.mkdir()
    app = create_app(
        database_path,
        serve_static=False,
        allowed_library_roots=[library_root],
    )
    with TestClient(app) as client:
        documents = client.get("/api/library/documents").json()
        assert documents[0]["title"] == "Existing note"
        assert documents[0]["source_path"] is None
        assert client.get("/api/health").json()["database"] == "ok"
