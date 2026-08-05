from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence

import fitz


SUPPORTED_TYPES = {
    ".md": "MARKDOWN",
    ".markdown": "MARKDOWN",
    ".pdf": "PDF",
    ".txt": "TXT",
}
MAX_CHUNK_CHARACTERS = 1_800
MAX_DOCUMENT_BYTES = 512 * 1024 * 1024
MAX_DIRECTORY_FILES = 500


@dataclass(frozen=True)
class ParsedDocument:
    title: str
    document_type: str
    source_path: str
    content_hash: str
    file_size: int
    chunks: list[tuple[int, int | None, int | None, str]]


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


def parse_document(path: Path) -> ParsedDocument:
    file_size = path.stat().st_size
    if file_size > MAX_DOCUMENT_BYTES:
        raise ValueError("Document exceeds the 512 MB import limit")
    data = path.read_bytes()
    document_type = SUPPORTED_TYPES[path.suffix.lower()]
    if document_type == "PDF":
        paragraphs = _pdf_paragraphs(data)
    else:
        paragraphs = _text_paragraphs(_decode_text(data))

    chunks: list[tuple[int, int | None, int | None, str]] = []
    for page_number, paragraph_number, paragraph in paragraphs:
        for content in _split_long_text(paragraph):
            chunks.append((len(chunks), page_number, paragraph_number, content))

    return ParsedDocument(
        title=path.stem,
        document_type=document_type,
        source_path=str(path),
        content_hash=hashlib.sha256(data).hexdigest(),
        file_size=file_size,
        chunks=chunks,
    )


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


def _pdf_paragraphs(data: bytes) -> Iterable[tuple[int, int, str]]:
    try:
        with fitz.open(stream=data, filetype="pdf") as document:
            for page_number, page in enumerate(document, start=1):
                paragraph_number = 0
                for block in page.get_text("blocks", sort=True):
                    content = _normalize_text(block[4])
                    if content:
                        paragraph_number += 1
                        yield page_number, paragraph_number, content
    except (RuntimeError, ValueError) as error:
        raise ValueError("Unable to read PDF document") from error


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
