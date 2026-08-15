from pathlib import Path

from fastapi.testclient import TestClient

from backend.app import create_app
from backend.semantic import SemanticOperationResult


class StubSemanticIndex:
    def index_document(self, document):
        return SemanticOperationResult(
            success=True,
            degraded=False,
            documents_processed=1,
            chunks_indexed=len(document.chunks),
        )


def test_runtime_paths_follow_configured_install_root(tmp_path: Path, monkeypatch) -> None:
    install_root = tmp_path / "portable install"
    library_root = install_root / "data" / "library"
    library_root.mkdir(parents=True)
    source = library_root / "portable.md"
    source.write_text("portable root content", encoding="utf-8")

    database_path = install_root / "data" / "database" / "ai-pc.sqlite3"
    monkeypatch.setenv("AI_PC_ROOT", str(install_root))
    monkeypatch.setenv("AI_PC_DB_PATH", str(database_path))

    app = create_app(serve_static=False, semantic_index=StubSemanticIndex())
    with TestClient(app) as client:
        settings = client.get("/api/settings").json()
        assert settings["data_path"] == str(install_root)

        imported = client.post("/api/library/import", json={"path": str(source)})
        assert imported.status_code == 201

        outside = tmp_path / "outside.md"
        outside.write_text("must stay outside the import boundary", encoding="utf-8")
        assert client.post("/api/library/import", json={"path": str(outside)}).status_code == 403

        deeptutor = client.get("/api/deeptutor/status").json()
        assert deeptutor["workspace"] == str(install_root / "data" / "deeptutor")
