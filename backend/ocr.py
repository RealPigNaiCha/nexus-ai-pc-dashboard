from __future__ import annotations

import importlib.metadata
import importlib.util
import math
import threading
from dataclasses import dataclass
from typing import Protocol, Sequence


DEFAULT_OCR_ENGINE = "rapidocr"


@dataclass(frozen=True, slots=True)
class OCRLine:
    text: str
    confidence: float
    polygon: tuple[tuple[float, float], ...]


class OCRBackend(Protocol):
    name: str
    version: str

    def recognize(self, image: bytes) -> Sequence[OCRLine]: ...


class RapidOCRBackend:
    name = DEFAULT_OCR_ENGINE

    def __init__(self) -> None:
        from rapidocr import RapidOCR

        self.version = importlib.metadata.version("rapidocr")
        self._engine = RapidOCR()
        self._lock = threading.Lock()

    def recognize(self, image: bytes) -> list[OCRLine]:
        with self._lock:
            result = self._engine(image)
        texts = list(result.txts) if result.txts is not None else []
        scores = list(result.scores) if result.scores is not None else []
        boxes = list(result.boxes) if result.boxes is not None else []
        lines: list[OCRLine] = []
        for text, score, box in zip(texts, scores, boxes, strict=False):
            normalized = " ".join(str(text).split())
            confidence = float(score)
            polygon = tuple((float(point[0]), float(point[1])) for point in box)
            if not normalized or not math.isfinite(confidence) or len(polygon) < 4:
                continue
            lines.append(
                OCRLine(
                    text=normalized,
                    confidence=max(0.0, min(1.0, confidence)),
                    polygon=polygon,
                )
            )
        return lines


_default_backend: OCRBackend | None = None
_default_backend_lock = threading.Lock()


def get_default_ocr_backend() -> OCRBackend | None:
    global _default_backend
    if _default_backend is not None:
        return _default_backend
    if importlib.util.find_spec("rapidocr") is None or importlib.util.find_spec("onnxruntime") is None:
        return None
    with _default_backend_lock:
        if _default_backend is None:
            _default_backend = RapidOCRBackend()
    return _default_backend


def ocr_status(backend: OCRBackend | None = None) -> dict[str, object]:
    if backend is not None:
        return {
            "available": True,
            "engine": backend.name,
            "version": backend.version,
            "local_only": True,
        }
    available = importlib.util.find_spec("rapidocr") is not None and importlib.util.find_spec("onnxruntime") is not None
    version = None
    if available:
        try:
            version = importlib.metadata.version("rapidocr")
        except importlib.metadata.PackageNotFoundError:
            available = False
    return {
        "available": available,
        "engine": DEFAULT_OCR_ENGINE if available else None,
        "version": version,
        "local_only": True,
    }
