import sqlite3
from pathlib import Path

from fastapi.testclient import TestClient

from backend.app import create_app


def create_zotero_database(path: Path, *, include_attachment: bool = True) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    try:
        connection.executescript(
            """
            CREATE TABLE itemTypes (itemTypeID INTEGER PRIMARY KEY, typeName TEXT);
            CREATE TABLE items (itemID INTEGER PRIMARY KEY, key TEXT, itemTypeID INTEGER, dateModified TEXT);
            CREATE TABLE fields (fieldID INTEGER PRIMARY KEY, fieldName TEXT);
            CREATE TABLE itemDataValues (valueID INTEGER PRIMARY KEY, value TEXT);
            CREATE TABLE itemData (itemID INTEGER, fieldID INTEGER, valueID INTEGER);
            CREATE TABLE collections (collectionID INTEGER PRIMARY KEY, key TEXT, collectionName TEXT, parentCollectionID INTEGER);
            CREATE TABLE collectionItems (collectionID INTEGER, itemID INTEGER);
            CREATE TABLE creators (creatorID INTEGER PRIMARY KEY, firstName TEXT, lastName TEXT);
            CREATE TABLE itemCreators (itemID INTEGER, creatorID INTEGER, creatorTypeID INTEGER, orderIndex INTEGER);
            CREATE TABLE itemAttachments (itemID INTEGER, parentItemID INTEGER, linkMode TEXT, path TEXT);
            """
        )
        connection.executemany(
            "INSERT INTO itemTypes(itemTypeID, typeName) VALUES (?, ?)",
            [(1, "journalArticle"), (2, "attachment"), (3, "note")],
        )
        connection.executemany(
            "INSERT INTO fields(fieldID, fieldName) VALUES (?, ?)",
            [(1, "title"), (2, "date"), (3, "DOI"), (4, "url")],
        )
        connection.executemany(
            "INSERT INTO itemDataValues(valueID, value) VALUES (?, ?)",
            [
                (1, "Limits and Continuity"),
                (2, "2024-05-01"),
                (3, "10.1000/xyz"),
                (4, "https://example.com/paper"),
            ],
        )
        connection.executemany(
            "INSERT INTO items(itemID, key, itemTypeID, dateModified) VALUES (?, ?, ?, ?)",
            [
                (1, "AAAA1111", 1, "2024-05-01 10:00:00"),
                (2, "ATTACH1", 2, "2024-05-01 10:01:00"),
                (3, "NOTE01", 3, "2024-05-01 10:02:00"),
            ],
        )
        connection.executemany(
            "INSERT INTO itemData(itemID, fieldID, valueID) VALUES (?, ?, ?)",
            [(1, 1, 1), (1, 2, 2), (1, 3, 3), (1, 4, 4)],
        )
        connection.execute(
            "INSERT INTO collections(collectionID, key, collectionName, parentCollectionID) VALUES (1, 'COLL1', '分析学', NULL)"
        )
        connection.execute("INSERT INTO collectionItems(collectionID, itemID) VALUES (1, 1)")
        connection.execute(
            "INSERT INTO creators(creatorID, firstName, lastName) VALUES (1, 'Alan', 'Turing')"
        )
        connection.execute(
            "INSERT INTO itemCreators(itemID, creatorID, creatorTypeID, orderIndex) VALUES (1, 1, 1, 0)"
        )
        if include_attachment:
            connection.execute(
                "INSERT INTO itemAttachments(itemID, parentItemID, linkMode, path) VALUES (2, 1, 'imported_file', 'storage:limits.pdf')"
            )
        connection.commit()
    finally:
        connection.close()


def make_client(tmp_path: Path, zotero_path: Path) -> TestClient:
    return TestClient(
        create_app(
            tmp_path / "zotero.sqlite3",
            serve_static=False,
            zotero_database=zotero_path,
        )
    )


def test_zotero_sync_persists_metadata_without_copying_files(tmp_path: Path) -> None:
    zotero_path = tmp_path / "zotero.sqlite"
    create_zotero_database(zotero_path)

    with make_client(tmp_path, zotero_path) as client:
        status_before = client.get("/api/zotero/status").json()
        response = client.post("/api/zotero/sync")
        items = client.app.state.database.query_all("SELECT * FROM zotero_items")
        status_after = client.get("/api/zotero/status").json()

    assert status_before["available"] is True
    assert status_before["item_count"] == 0
    assert response.status_code == 201
    assert response.json()["items"] == 1
    assert response.json()["collections"] == 1
    assert response.json()["attachments"] == 1
    assert len(items) == 1
    assert items[0]["key"] == "AAAA1111"
    assert items[0]["doi"] == "10.1000/xyz"
    assert items[0]["year"] == "2024"
    assert "Turing" in items[0]["creators_json"]
    assert "分析学" in items[0]["collections_json"]
    assert "limits.pdf" in items[0]["attachment_paths_json"]
    assert status_after["item_count"] == 1
    assert status_after["last_sync"]["status"] == "success"


def test_zotero_sync_replaces_previous_snapshot(tmp_path: Path) -> None:
    zotero_path = tmp_path / "zotero.sqlite"
    create_zotero_database(zotero_path)

    with make_client(tmp_path, zotero_path) as client:
        client.post("/api/zotero/sync")
        first_count = client.app.state.database.query_one(
            "SELECT COUNT(*) AS count FROM zotero_items"
        )["count"]
        # Simulate the library changing: drop the item, keep only a new attachment-less item.
        connection = sqlite3.connect(zotero_path)
        connection.execute("DELETE FROM itemData")
        connection.execute("DELETE FROM items")
        connection.execute("INSERT INTO items(itemID, key, itemTypeID, dateModified) VALUES (9, 'BBBB2222', 1, '2025-01-01 00:00:00')")
        connection.commit()
        connection.close()

        client.post("/api/zotero/sync")
        second = client.app.state.database.query_one(
            "SELECT key, title FROM zotero_items"
        )

    assert first_count == 1
    assert second["key"] == "BBBB2222"
    assert second["title"] is None


def test_zotero_missing_database_is_sanitized_and_audited(tmp_path: Path) -> None:
    missing = tmp_path / "does-not-exist.sqlite"
    with make_client(tmp_path, missing) as client:
        response = client.post("/api/zotero/sync")
        sync = client.app.state.database.query_one(
            "SELECT * FROM zotero_syncs ORDER BY id DESC LIMIT 1"
        )
        audit = client.get("/api/audit", params={"limit": 5}).json()

    assert response.status_code == 503
    assert response.json() == {"detail": "Zotero database not found"}
    assert sync["status"] == "error"
    assert sync["error"] == "Zotero database not found"
    assert any(item["action"] == "sync" and item["result"] == "error" for item in audit)


def test_zotero_status_reports_missing_database(tmp_path: Path) -> None:
    missing = tmp_path / "missing.sqlite"
    with make_client(tmp_path, missing) as client:
        status = client.get("/api/zotero/status").json()

    assert status["available"] is False
    assert status["item_count"] == 0
    assert status["last_sync"] is None


def test_zotero_sync_failure_preserves_existing_snapshot(tmp_path: Path) -> None:
    zotero_path = tmp_path / "zotero.sqlite"
    create_zotero_database(zotero_path)
    with make_client(tmp_path, zotero_path) as client:
        client.post("/api/zotero/sync")
        zotero_path.unlink()
        response = client.post("/api/zotero/sync")
        items = client.app.state.database.query_all("SELECT key FROM zotero_items")
        sync = client.app.state.database.query_one(
            "SELECT * FROM zotero_syncs ORDER BY id DESC LIMIT 1"
        )

    assert response.status_code == 503
    assert len(items) == 1
    assert items[0]["key"] == "AAAA1111"
    assert sync["status"] == "error"


def test_zotero_status_reports_auto_sync_fields(tmp_path: Path) -> None:
    zotero_path = tmp_path / "zotero.sqlite"
    create_zotero_database(zotero_path)
    with make_client(tmp_path, zotero_path) as client:
        status = client.get("/api/zotero/status").json()

    assert status["auto_sync_enabled"] is False
    assert status["auto_sync_interval_hours"] == 6.0
