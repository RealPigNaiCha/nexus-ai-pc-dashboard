from __future__ import annotations

import hashlib
import json
from pathlib import Path

import fitz
from fastapi.testclient import TestClient

from backend.app import create_app
from backend.library import parse_document
from backend.ocr import OCRLine


class FakeOCRBackend:
    name = "fake-ocr"
    version = "1.0"

    def __init__(self) -> None:
        self.calls = 0

    def recognize(self, image: bytes) -> list[OCRLine]:
        assert image.startswith(b"\x89PNG")
        self.calls += 1
        return [
            OCRLine(
                text="标准摩尔生成焓",
                confidence=0.97,
                polygon=((10.0, 20.0), (180.0, 20.0), (180.0, 45.0), (10.0, 45.0)),
            ),
            OCRLine(
                text="保留原页视觉证据",
                confidence=0.91,
                polygon=((10.0, 55.0), (210.0, 55.0), (210.0, 82.0), (10.0, 82.0)),
            ),
        ]


def _image_only_pdf(path: Path) -> bytes:
    source = fitz.open()
    page = source.new_page(width=240, height=320)
    pixmap = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 240, 320), False)
    pixmap.clear_with(245)
    page.insert_image(page.rect, stream=pixmap.tobytes("png"))
    source.save(path)
    source.close()
    return path.read_bytes()


def _mixed_pdf(path: Path) -> None:
    source = fitz.open()
    text_page = source.new_page(width=240, height=320)
    text_page.insert_text((24, 48), "Native text layer contains sufficient searchable content.")
    scan_page = source.new_page(width=240, height=320)
    pixmap = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 240, 320), False)
    pixmap.clear_with(238)
    scan_page.insert_image(scan_page.rect, stream=pixmap.tobytes("png"))
    source.save(path)
    source.close()


def test_scanned_pdf_ocr_is_citable_cached_and_does_not_change_source(tmp_path: Path) -> None:
    source = tmp_path / "scan.pdf"
    original = _image_only_pdf(source)
    evidence_root = tmp_path / "parsed"
    backend = FakeOCRBackend()

    parsed = parse_document(source, evidence_root=evidence_root, ocr_backend=backend)

    assert source.read_bytes() == original
    assert hashlib.sha256(original).hexdigest() == parsed.content_hash
    assert parsed.status == "ready"
    assert parsed.page_count == 1
    assert parsed.native_page_count == 0
    assert parsed.ocr_page_count == 1
    assert parsed.unreadable_page_count == 0
    assert parsed.ocr_engine == "fake-ocr/1.0"
    assert backend.calls == 1
    assert parsed.chunks[0].text_source == "ocr"
    assert "标准摩尔生成焓" in parsed.chunks[0].content
    evidence = json.loads(parsed.chunks[0].evidence_json or "{}")
    assert evidence["page"] == 1
    assert len(evidence["regions"]) == 2
    assert all(0 <= value <= 1 for region in evidence["regions"] for value in region["bbox"])

    evidence_path = Path(parsed.evidence_path or "")
    assert (evidence_path / "manifest.json").is_file()
    assert (evidence_path / "pages" / "page-0001.png").is_file()

    cached = parse_document(source, evidence_root=evidence_root, ocr_backend=backend)
    assert cached.chunks == parsed.chunks
    assert backend.calls == 1


def test_scanned_pdf_without_ocr_is_marked_for_review(tmp_path: Path) -> None:
    source = tmp_path / "scan.pdf"
    _image_only_pdf(source)

    parsed = parse_document(source, evidence_root=tmp_path / "parsed", ocr_enabled=False)

    assert parsed.status == "needs-review"
    assert parsed.page_count == 1
    assert parsed.unreadable_page_count == 1
    assert parsed.chunks == []


def test_mixed_pdf_only_ocr_processes_pages_without_native_text(tmp_path: Path) -> None:
    source = tmp_path / "mixed.pdf"
    _mixed_pdf(source)
    backend = FakeOCRBackend()

    parsed = parse_document(source, evidence_root=tmp_path / "parsed", ocr_backend=backend)

    assert parsed.status == "ready"
    assert parsed.page_count == 2
    assert parsed.native_page_count == 1
    assert parsed.ocr_page_count == 1
    assert backend.calls == 1
    assert {chunk.text_source for chunk in parsed.chunks} == {"native", "ocr"}


def test_ocr_search_returns_evidence_and_serves_original_page(tmp_path: Path) -> None:
    library_root = tmp_path / "library"
    library_root.mkdir()
    source = library_root / "scan.pdf"
    _image_only_pdf(source)
    backend = FakeOCRBackend()
    app = create_app(
        tmp_path / "ocr.sqlite3",
        serve_static=False,
        allowed_library_roots=[library_root],
        ocr_backend=backend,
        library_evidence_root=tmp_path / "parsed",
    )

    with TestClient(app) as client:
        imported = client.post("/api/library/import", json={"path": str(source)})
        assert imported.status_code == 201
        document = imported.json()["document"]
        assert document["status"] == "ready"
        assert document["ocr_page_count"] == 1

        progress = client.get("/api/library/ocr/progress", params={"path": str(source)}).json()
        assert progress["status"] == "completed"
        assert progress["processed_pages"] == 1
        assert progress["page_count"] == 1

        status = client.get("/api/library/ocr/status").json()
        assert status["available"] is True
        assert status["enabled"] is True
        assert status["engine"] == "fake-ocr"

        results = client.get(
            "/api/library/search",
            params={"q": "标准摩尔生成焓", "mode": "lexical"},
        ).json()
        assert len(results) == 1
        assert results[0]["text_source"] == "ocr"
        assert results[0]["confidence"] == 0.94
        assert results[0]["evidence"]["page"] == 1

        image = client.get(f"/api/library/documents/{document['id']}/pages/1/image")
        assert image.status_code == 200
        assert image.headers["content-type"] == "image/png"
        assert image.content.startswith(b"\x89PNG")
