from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class ZoteroReadError(RuntimeError):
    """A deliberately generic Zotero read failure."""


@dataclass(frozen=True)
class ZoteroSnapshot:
    items: list[dict[str, Any]]
    collections: list[dict[str, Any]]
    attachment_count: int


class ZoteroReader:
    """Read a Zotero SQLite database strictly read-only."""

    def __init__(self, database_path: Path) -> None:
        self.database_path = Path(database_path)

    def snapshot(self) -> ZoteroSnapshot:
        if not self.database_path.is_file():
            raise ZoteroReadError("Zotero database not found")
        try:
            connection = sqlite3.connect(f"file:{self.database_path}?mode=ro", uri=True)
        except sqlite3.Error as error:
            raise ZoteroReadError("Zotero database is unavailable") from error
        try:
            connection.row_factory = sqlite3.Row
            return self._read(connection)
        except sqlite3.Error as error:
            raise ZoteroReadError("Zotero database could not be read") from error
        finally:
            connection.close()

    def _read(self, connection: sqlite3.Connection) -> ZoteroSnapshot:
        item_types = {
            row["itemTypeID"]: row["typeName"]
            for row in connection.execute("SELECT itemTypeID, typeName FROM itemTypes")
        }
        metadata: dict[int, dict[str, str]] = {}
        for row in connection.execute(
            """
            SELECT item_data.itemID, field.fieldName, value.value
            FROM itemData AS item_data
            JOIN fields AS field ON field.fieldID = item_data.fieldID
            JOIN itemDataValues AS value ON value.valueID = item_data.valueID
            """
        ):
            metadata.setdefault(row["itemID"], {})[row["fieldName"]] = row["value"]

        creators_by_item: dict[int, list[str]] = {}
        for row in connection.execute(
            """
            SELECT item_creator.itemID, creator.firstName, creator.lastName
            FROM itemCreators AS item_creator
            JOIN creators AS creator ON creator.creatorID = item_creator.creatorID
            ORDER BY item_creator.orderIndex
            """
        ):
            first = (row["firstName"] or "").strip()
            last = (row["lastName"] or "").strip()
            name = f"{first} {last}".strip() if (first or last) else "Unknown"
            creators_by_item.setdefault(row["itemID"], []).append(name)

        collections = [
            {
                "key": row["key"],
                "name": row["collectionName"],
                "parent_key": row["parentCollectionID"],
            }
            for row in connection.execute(
                "SELECT key, collectionName, parentCollectionID FROM collections ORDER BY collectionName"
            )
        ]
        collection_names = {
            row["collectionID"]: row["collectionName"]
            for row in connection.execute("SELECT collectionID, collectionName FROM collections")
        }
        item_collections: dict[int, list[str]] = {}
        for row in connection.execute("SELECT collectionID, itemID FROM collectionItems"):
            name = collection_names.get(row["collectionID"])
            if name:
                item_collections.setdefault(row["itemID"], []).append(name)

        attachments: dict[int, dict[str, object]] = {}
        for row in connection.execute(
            "SELECT itemID, parentItemID, path FROM itemAttachments"
        ):
            attachments[row["itemID"]] = {
                "parent_item_id": row["parentItemID"],
                "path": row["path"] or "",
            }

        parent_attachments: dict[int, list[str]] = {}
        attachment_count = 0
        for item_row in connection.execute("SELECT itemID, key, itemTypeID FROM items"):
            item_type = item_types.get(item_row["itemTypeID"], "unknown")
            if item_type != "attachment":
                continue
            attachment = attachments.get(item_row["itemID"])
            if attachment is None:
                continue
            parent_id = attachment["parent_item_id"]
            resolved = self._resolve_attachment_path(
                str(attachment["path"]), item_row["key"]
            )
            if parent_id is not None and resolved:
                parent_attachments.setdefault(parent_id, []).append(resolved)
            attachment_count += 1

        snapshot_items: list[dict[str, Any]] = []
        for item_row in connection.execute("SELECT itemID, key, itemTypeID FROM items"):
            item_type = item_types.get(item_row["itemTypeID"], "unknown")
            if item_type in {"attachment", "note"}:
                continue
            meta = metadata.get(item_row["itemID"], {})
            snapshot_items.append(
                {
                    "key": item_row["key"],
                    "item_type": item_type,
                    "title": meta.get("title") or None,
                    "year": self._extract_year(meta.get("date")),
                    "doi": meta.get("DOI") or None,
                    "url": meta.get("url") or None,
                    "creators": creators_by_item.get(item_row["itemID"], []),
                    "collections": sorted(item_collections.get(item_row["itemID"], [])),
                    "attachment_paths": sorted(parent_attachments.get(item_row["itemID"], [])),
                }
            )
        return ZoteroSnapshot(
            items=snapshot_items,
            collections=collections,
            attachment_count=attachment_count,
        )

    def _resolve_attachment_path(self, path: str, attachment_key: str) -> str:
        if not path:
            return ""
        if path.startswith("storage:"):
            filename = path[len("storage:") :].lstrip("\\/")
            return str(self.database_path.parent / "storage" / attachment_key / filename)
        candidate = Path(path)
        if candidate.is_absolute():
            return str(candidate)
        return str((self.database_path.parent / candidate).resolve())

    @staticmethod
    def _extract_year(value: str | None) -> str | None:
        if not value:
            return None
        match = re.search(r"\b(1[89]\d{2}|20\d{2})\b", value)
        return match.group(1) if match else None
