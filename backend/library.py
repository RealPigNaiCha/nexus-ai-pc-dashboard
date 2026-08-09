from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from statistics import fmean
from typing import Callable, Iterable, Sequence
from uuid import uuid4

import fitz

from .ocr import OCRBackend, OCRLine, get_default_ocr_backend


SUPPORTED_TYPES = {
    ".md": "MARKDOWN",
    ".markdown": "MARKDOWN",
    ".pdf": "PDF",
    ".txt": "TXT",
}
MAX_CHUNK_CHARACTERS = 1_800
MAX_DOCUMENT_BYTES = 512 * 1024 * 1024
MAX_DIRECTORY_FILES = 500
EXTRACTION_VERSION = "ocr-evidence-v1"
DEFAULT_OCR_DPI = 120
MIN_NATIVE_PAGE_CHARACTERS = 24
OCR_GROUP_MAX_CHARACTERS = 900
OCR_GROUP_MAX_LINES = 8


@dataclass(frozen=True, slots=True)
class ParsedChunk:
    ordinal: int
    page_number: int | None
    paragraph_number: int | None
    content: str
    text_source: str = "native"
    confidence: float | None = None
    evidence_json: str | None = None


@dataclass(frozen=True, slots=True)
class ParsedDocument:
    title: str
    document_type: str
    source_path: str
    content_hash: str
    file_size: int
    chunks: list[ParsedChunk]
    status: str = "ready"
    page_count: int = 0
    native_page_count: int = 0
    ocr_page_count: int = 0
    unreadable_page_count: int = 0
    ocr_engine: str | None = None
    evidence_path: str | None = None
    extraction_version: str = EXTRACTION_VERSION


@dataclass(frozen=True, slots=True)
class _EvidenceRegion:
    text: str
    confidence: float
    bbox: tuple[float, float, float, float]


def resolve_source_path(raw_path: str, allowed_roots: Sequence[Path]) -> Path:
    candidate = Path(raw_path).expanduser().resolve(strict=False)
    roots = tuple(root.expanduser().resolve(strict=False) for root in allowed_roots)
    if not any(_is_relative_to(candidate, root) for root in roots):
        raise PermissionError("Path is outside the configured library roots")
    if not candidate.exists():
        raise FileNotFoundError("Document does not exist")
    if not candidate.is_file() and not candidate.is_dir():
        raise ValueError("Path must point to a file or directory")
    if candidate.is_file() and candidate.suffix.lower() not in SUPPORTED_TYPES:
        raise ValueError("Supported document types are PDF, Markdown, and TXT")
    return candidate


def discover_source_files(source: Path, allowed_roots: Sequence[Path]) -> list[Path]:
    if source.is_file():
        return [source]

    files: list[Path] = []
    for candidate in sorted(source.rglob("*"), key=lambda path: str(path).casefold()):
        if not candidate.is_file() or candidate.suffix.lower() not in SUPPORTED_TYPES:
            continue
        resolved = candidate.resolve(strict=True)
        if not any(_is_relative_to(resolved, root.resolve(strict=False)) for root in allowed_roots):
            continue
        files.append(resolved)
        if len(files) > MAX_DIRECTORY_FILES:
            raise ValueError(f"A directory import is limited to {MAX_DIRECTORY_FILES} documents")

    if not files:
        raise ValueError("No supported PDF, Markdown, or TXT documents were found")
    return files


def parse_document(
    path: Path,
    *,
    evidence_root: Path | None = None,
    ocr_backend: OCRBackend | None = None,
    ocr_enabled: bool = True,
    progress: Callable[[dict[str, object]], None] | None = None,
) -> ParsedDocument:
    file_size = path.stat().st_size
    if file_size > MAX_DOCUMENT_BYTES:
        raise ValueError("Document exceeds the 512 MB import limit")
    data = path.read_bytes()
    document_type = SUPPORTED_TYPES[path.suffix.lower()]
    content_hash = hashlib.sha256(data).hexdigest()

    if document_type == "PDF":
        result = _parse_pdf(
            data,
            content_hash=content_hash,
            evidence_root=evidence_root,
            ocr_backend=ocr_backend,
            ocr_enabled=ocr_enabled,
            progress=progress,
        )
        allowed_unreadable = max(2, result[1] // 20)
        status = "ready" if result[0] and result[4] <= allowed_unreadable else "needs-review"
        return ParsedDocument(
            title=path.stem,
            document_type=document_type,
            source_path=str(path),
            content_hash=content_hash,
            file_size=file_size,
            chunks=result[0],
            status=status,
            page_count=result[1],
            native_page_count=result[2],
            ocr_page_count=result[3],
            unreadable_page_count=result[4],
            ocr_engine=result[5],
            evidence_path=result[6],
        )

    chunks: list[ParsedChunk] = []
    for page_number, paragraph_number, paragraph in _text_paragraphs(_decode_text(data)):
        for content in _split_long_text(paragraph):
            chunks.append(
                ParsedChunk(
                    ordinal=len(chunks),
                    page_number=page_number,
                    paragraph_number=paragraph_number,
                    content=content,
                )
            )
    return ParsedDocument(
        title=path.stem,
        document_type=document_type,
        source_path=str(path),
        content_hash=content_hash,
        file_size=file_size,
        chunks=chunks,
    )


def render_pdf_page(path: Path, page_number: int, *, dpi: int = 144) -> bytes:
    if page_number < 1:
        raise ValueError("Page number must be positive")
    try:
        with fitz.open(path) as document:
            if page_number > len(document):
                raise ValueError("PDF page does not exist")
            page = document[page_number - 1]
            scale = max(72, min(300, dpi)) / 72
            pixmap = page.get_pixmap(matrix=fitz.Matrix(scale, scale), colorspace=fitz.csRGB, alpha=False)
            return pixmap.tobytes("png")
    except (RuntimeError, ValueError) as error:
        if isinstance(error, ValueError) and str(error) in {"Page number must be positive", "PDF page does not exist"}:
            raise
        raise ValueError("Unable to render PDF page") from error


def _parse_pdf(
    data: bytes,
    *,
    content_hash: str,
    evidence_root: Path | None,
    ocr_backend: OCRBackend | None,
    ocr_enabled: bool,
    progress: Callable[[dict[str, object]], None] | None,
) -> tuple[list[ParsedChunk], int, int, int, int, str | None, str | None]:
    chunks: list[ParsedChunk] = []
    native_pages = 0
    ocr_pages = 0
    unreadable_pages = 0
    active_backend = ocr_backend
    evidence_dir = _evidence_directory(evidence_root, content_hash)
    dpi = _ocr_dpi()
    try:
        with fitz.open(stream=data, filetype="pdf") as document:
            page_count = len(document)
            for page_number, page in enumerate(document, start=1):
                native_regions = _native_regions(page)
                if _native_text_is_usable(native_regions):
                    native_pages += 1
                    chunks.extend(_regions_to_chunks(native_regions, page_number, len(chunks), "native"))
                    _report_progress(progress, page_number, page_count, "native", False)
                    continue

                if not ocr_enabled:
                    unreadable_pages += 1
                    _report_progress(progress, page_number, page_count, "unreadable", False)
                    continue
                if active_backend is None:
                    active_backend = get_default_ocr_backend()
                if active_backend is None:
                    unreadable_pages += 1
                    _report_progress(progress, page_number, page_count, "unreadable", False)
                    continue

                regions = _cached_ocr_regions(evidence_dir, page_number, active_backend, dpi)
                cached = regions is not None
                if regions is None:
                    image = _render_page(page, dpi)
                    regions = _ocr_regions(active_backend.recognize(image[0]), image[1], image[2])
                    if evidence_dir is not None:
                        _save_ocr_page(
                            evidence_dir,
                            page_number=page_number,
                            image=image[0],
                            width=image[1],
                            height=image[2],
                            regions=regions,
                            backend=active_backend,
                            dpi=dpi,
                        )
                if not regions:
                    unreadable_pages += 1
                    _report_progress(progress, page_number, page_count, "unreadable", cached)
                    continue
                ocr_pages += 1
                chunks.extend(_regions_to_chunks(regions, page_number, len(chunks), "ocr"))
                _report_progress(progress, page_number, page_count, "ocr", cached)

            engine_name = None
            if ocr_pages and active_backend is not None:
                engine_name = f"{active_backend.name}/{active_backend.version}"
            if evidence_dir is not None:
                _write_json(
                    evidence_dir / "manifest.json",
                    {
                        "extraction_version": EXTRACTION_VERSION,
                        "source_sha256": content_hash,
                        "page_count": page_count,
                        "native_page_count": native_pages,
                        "ocr_page_count": ocr_pages,
                        "unreadable_page_count": unreadable_pages,
                        "ocr_engine": engine_name,
                        "ocr_dpi": dpi,
                    },
                )
            return (
                chunks,
                page_count,
                native_pages,
                ocr_pages,
                unreadable_pages,
                engine_name,
                str(evidence_dir) if evidence_dir is not None else None,
            )
    except (RuntimeError, ValueError, OSError) as error:
        raise ValueError("Unable to read PDF document") from error


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _decode_text(data: bytes) -> str:
    for encoding in ("utf-8-sig", "gb18030"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise ValueError("Text document must be UTF-8 or GB18030 encoded")


def _text_paragraphs(text: str) -> Iterable[tuple[None, int, str]]:
    paragraphs = re.split(r"(?:\r?\n\s*){2,}", text)
    paragraph_number = 0
    for value in paragraphs:
        content = _normalize_text(value)
        if content:
            paragraph_number += 1
            yield None, paragraph_number, content


def _native_regions(page: fitz.Page) -> list[_EvidenceRegion]:
    regions: list[_EvidenceRegion] = []
    page_width = max(float(page.rect.width), 1.0)
    page_height = max(float(page.rect.height), 1.0)
    for block in page.get_text("blocks", sort=True):
        content = _normalize_text(block[4])
        if not content:
            continue
        bbox = _normalize_bbox((float(block[0]), float(block[1]), float(block[2]), float(block[3])), page_width, page_height)
        regions.append(_EvidenceRegion(text=content, confidence=1.0, bbox=bbox))
    return regions


def _native_text_is_usable(regions: Sequence[_EvidenceRegion]) -> bool:
    text = "".join(region.text for region in regions)
    if len(text) < MIN_NATIVE_PAGE_CHARACTERS:
        return False
    meaningful = sum(character.isalnum() or "\u3400" <= character <= "\u9fff" for character in text)
    return meaningful / max(len(text), 1) >= 0.45


def _render_page(page: fitz.Page, dpi: int) -> tuple[bytes, int, int]:
    scale = dpi / 72
    pixmap = page.get_pixmap(matrix=fitz.Matrix(scale, scale), colorspace=fitz.csRGB, alpha=False)
    return pixmap.tobytes("png"), int(pixmap.width), int(pixmap.height)


def _ocr_regions(lines: Sequence[OCRLine], width: int, height: int) -> list[_EvidenceRegion]:
    regions: list[_EvidenceRegion] = []
    for line in lines:
        xs = [point[0] for point in line.polygon]
        ys = [point[1] for point in line.polygon]
        if not xs or not ys:
            continue
        regions.append(
            _EvidenceRegion(
                text=_normalize_text(line.text),
                confidence=line.confidence,
                bbox=_normalize_bbox((min(xs), min(ys), max(xs), max(ys)), width, height),
            )
        )
    return sorted(regions, key=lambda region: (region.bbox[1], region.bbox[0]))


def _regions_to_chunks(
    regions: Sequence[_EvidenceRegion],
    page_number: int,
    start_ordinal: int,
    source: str,
) -> list[ParsedChunk]:
    if source == "native":
        groups = [[region] for region in regions]
    else:
        groups: list[list[_EvidenceRegion]] = []
        current: list[_EvidenceRegion] = []
        current_characters = 0
        for region in regions:
            projected = current_characters + len(region.text) + int(bool(current))
            if current and (len(current) >= OCR_GROUP_MAX_LINES or projected > OCR_GROUP_MAX_CHARACTERS):
                groups.append(current)
                current = []
                current_characters = 0
            current.append(region)
            current_characters += len(region.text) + int(len(current) > 1)
        if current:
            groups.append(current)

    chunks: list[ParsedChunk] = []
    for paragraph_number, group in enumerate(groups, start=1):
        content = " ".join(region.text for region in group)
        evidence = {
            "page": page_number,
            "regions": [
                {"bbox": [round(value, 6) for value in region.bbox], "confidence": round(region.confidence, 6)}
                for region in group
            ],
        }
        confidence = fmean(region.confidence for region in group) if group else None
        for part in _split_long_text(content):
            chunks.append(
                ParsedChunk(
                    ordinal=start_ordinal + len(chunks),
                    page_number=page_number,
                    paragraph_number=paragraph_number,
                    content=part,
                    text_source=source,
                    confidence=confidence,
                    evidence_json=json.dumps(evidence, ensure_ascii=False, separators=(",", ":")),
                )
            )
    return chunks


def _evidence_directory(root: Path | None, content_hash: str) -> Path | None:
    if root is None:
        return None
    directory = root.expanduser().resolve(strict=False) / content_hash[:2] / content_hash
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def _cached_ocr_regions(
    evidence_dir: Path | None,
    page_number: int,
    backend: OCRBackend,
    dpi: int,
) -> list[_EvidenceRegion] | None:
    if evidence_dir is None:
        return None
    metadata_path = evidence_dir / "pages" / f"page-{page_number:04d}.json"
    image_path = evidence_dir / "pages" / f"page-{page_number:04d}.png"
    if not metadata_path.is_file() or not image_path.is_file():
        return None
    try:
        payload = json.loads(metadata_path.read_text(encoding="utf-8"))
        if (
            payload.get("extraction_version") != EXTRACTION_VERSION
            or payload.get("ocr_engine") != backend.name
            or payload.get("ocr_version") != backend.version
            or int(payload.get("dpi")) != dpi
            or payload.get("image_sha256") != _file_sha256(image_path)
        ):
            return None
        regions = []
        for item in payload.get("regions", []):
            bbox = tuple(float(value) for value in item["bbox"])
            if len(bbox) != 4:
                return None
            regions.append(
                _EvidenceRegion(
                    text=_normalize_text(str(item["text"])),
                    confidence=max(0.0, min(1.0, float(item["confidence"]))),
                    bbox=(bbox[0], bbox[1], bbox[2], bbox[3]),
                )
            )
        return regions
    except (KeyError, TypeError, ValueError, OSError, json.JSONDecodeError):
        return None


def _save_ocr_page(
    evidence_dir: Path,
    *,
    page_number: int,
    image: bytes,
    width: int,
    height: int,
    regions: Sequence[_EvidenceRegion],
    backend: OCRBackend,
    dpi: int,
) -> None:
    pages_dir = evidence_dir / "pages"
    pages_dir.mkdir(parents=True, exist_ok=True)
    image_path = pages_dir / f"page-{page_number:04d}.png"
    _write_bytes(image_path, image)
    _write_json(
        pages_dir / f"page-{page_number:04d}.json",
        {
            "extraction_version": EXTRACTION_VERSION,
            "ocr_engine": backend.name,
            "ocr_version": backend.version,
            "dpi": dpi,
            "width": width,
            "height": height,
            "image_sha256": hashlib.sha256(image).hexdigest(),
            "regions": [
                {
                    "text": region.text,
                    "confidence": round(region.confidence, 6),
                    "bbox": [round(value, 6) for value in region.bbox],
                }
                for region in regions
            ],
        },
    )


def _ocr_dpi() -> int:
    try:
        value = int(os.getenv("AI_PC_OCR_DPI", str(DEFAULT_OCR_DPI)))
    except ValueError:
        value = DEFAULT_OCR_DPI
    return max(96, min(300, value))


def _report_progress(
    callback: Callable[[dict[str, object]], None] | None,
    processed_pages: int,
    page_count: int,
    page_source: str,
    cached: bool,
) -> None:
    if callback is None:
        return
    try:
        callback(
            {
                "status": "processing",
                "processed_pages": processed_pages,
                "page_count": page_count,
                "page_source": page_source,
                "cached": cached,
            }
        )
    except Exception:
        return


def _normalize_bbox(
    bbox: tuple[float, float, float, float], width: float, height: float
) -> tuple[float, float, float, float]:
    x0, y0, x1, y1 = bbox
    return (
        max(0.0, min(1.0, x0 / width)),
        max(0.0, min(1.0, y0 / height)),
        max(0.0, min(1.0, x1 / width)),
        max(0.0, min(1.0, y1 / height)),
    )


def _write_bytes(path: Path, content: bytes) -> None:
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    temporary.write_bytes(content)
    temporary.replace(path)


def _write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _normalize_text(value: str) -> str:
    return " ".join(value.split())


def _split_long_text(value: str) -> Iterable[str]:
    remaining = value
    while len(remaining) > MAX_CHUNK_CHARACTERS:
        boundary = remaining.rfind(" ", 0, MAX_CHUNK_CHARACTERS + 1)
        if boundary < MAX_CHUNK_CHARACTERS // 2:
            boundary = MAX_CHUNK_CHARACTERS
        yield remaining[:boundary].strip()
        remaining = remaining[boundary:].strip()
    if remaining:
        yield remaining
