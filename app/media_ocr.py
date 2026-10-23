from __future__ import annotations

import hashlib
import importlib.metadata
import re
from dataclasses import dataclass, field
from io import BytesIO
from pathlib import Path
from typing import Any, Callable, Iterable


OCR_REGION_SCHEMA_VERSION = "edumatrix.ocr-region.v1"
OCR_DOCUMENT_SCHEMA_VERSION = "edumatrix.ocr-document.v1"
OCR_ENGINE_NAME = "rapidocr-onnxruntime"
OCR_DPI = 150

_EMAIL_RE = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I)
_PHONE_RE = re.compile(r"(?<!\d)(?:\+?86[- ]?)?1[3-9]\d{9}(?!\d)")
_CN_ID_RE = re.compile(r"(?<!\d)\d{6}(?:19|20)\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])\d{3}[0-9Xx](?!\d)")
_SECRET_RE = re.compile(
    r"\b(?:sk|api[_-]?key|token|secret)[-_:= ]+[A-Za-z0-9_-]{8,}\b",
    re.I,
)
_FORMULA_RE = re.compile(r"(?:[A-Za-z0-9)]\s*[=+*/^<>]\s*[A-Za-z0-9(])|(?:\b(?:sin|cos|log|sqrt)\s*\()")


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha256_text(value: str) -> str:
    return _sha256_bytes(value.encode("utf-8"))


def _clamp(value: float) -> float:
    return round(min(1.0, max(0.0, float(value))), 8)


def _normalize_polygon(
    polygon: Iterable[Iterable[float]], width: int, height: int
) -> tuple[tuple[float, float], ...]:
    if width <= 0 or height <= 0:
        raise ValueError("page dimensions must be positive")
    points = tuple((_clamp(float(x) / width), _clamp(float(y) / height)) for x, y in polygon)
    if len(points) < 4:
        raise ValueError("OCR polygon must contain at least four points")
    return points


def _bbox_from_polygon(points: tuple[tuple[float, float], ...]) -> dict[str, float]:
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    left, right = min(xs), max(xs)
    top, bottom = min(ys), max(ys)
    if right <= left or bottom <= top:
        raise ValueError("OCR region must have positive area")
    return {
        "x": left,
        "y": top,
        "width": round(right - left, 8),
        "height": round(bottom - top, 8),
    }


def detect_sensitive_categories(text: str) -> tuple[str, ...]:
    categories: list[str] = []
    for category, pattern in (
        ("email", _EMAIL_RE),
        ("phone", _PHONE_RE),
        ("cn_identity_number", _CN_ID_RE),
        ("credential", _SECRET_RE),
    ):
        if pattern.search(text):
            categories.append(category)
    return tuple(categories)


def classify_region_type(text: str) -> str:
    compact = text.strip()
    if _FORMULA_RE.search(compact):
        return "formula"
    if "|" in compact or "\t" in compact:
        return "table"
    return "text"


def _infer_table_region(regions: tuple["OCRRegion", ...]) -> "OCRRegion | None":
    candidates = [region for region in regions if region.region_type == "text"]
    if len(candidates) < 4:
        return None
    ordered = sorted(candidates, key=lambda region: (region.bbox["y"], region.bbox["x"]))
    typical_height = sorted(region.bbox["height"] for region in ordered)[len(ordered) // 2]
    tolerance = max(0.012, typical_height * 0.75)
    rows: list[list[OCRRegion]] = []
    for region in ordered:
        center_y = region.bbox["y"] + region.bbox["height"] / 2
        if not rows:
            rows.append([region])
            continue
        previous_centers = [
            item.bbox["y"] + item.bbox["height"] / 2 for item in rows[-1]
        ]
        if abs(center_y - sum(previous_centers) / len(previous_centers)) <= tolerance:
            rows[-1].append(region)
        else:
            rows.append([region])
    rows = [sorted(row, key=lambda region: region.bbox["x"]) for row in rows if len(row) >= 2]
    if len(rows) < 2:
        return None
    column_count = min(len(row) for row in rows)
    if column_count < 2:
        return None
    rows = [row[:column_count] for row in rows]
    reference_x = [item.bbox["x"] for item in rows[0]]
    if any(
        abs(row[index].bbox["x"] - reference_x[index]) > 0.08
        for row in rows[1:]
        for index in range(column_count)
    ):
        return None

    table_rows = [[cell.text for cell in row] for row in rows]
    markdown = "\n".join(
        [
            "| " + " | ".join(table_rows[0]) + " |",
            "| " + " | ".join("---" for _ in range(column_count)) + " |",
            *("| " + " | ".join(row) + " |" for row in table_rows[1:]),
        ]
    )
    left = min(cell.bbox["x"] for row in rows for cell in row)
    top = min(cell.bbox["y"] for row in rows for cell in row)
    right = max(cell.bbox["x"] + cell.bbox["width"] for row in rows for cell in row)
    bottom = max(cell.bbox["y"] + cell.bbox["height"] for row in rows for cell in row)
    polygon = ((left, top), (right, top), (right, bottom), (left, bottom))
    first = rows[0][0]
    table_hash = _sha256_text(markdown)
    return OCRRegion(
        region_id="ocr-table-" + _sha256_text(
            f"{first.source_sha256}:{first.page_number}:{table_hash}"
        )[:24],
        page_number=first.page_number,
        page_width_px=first.page_width_px,
        page_height_px=first.page_height_px,
        polygon=polygon,
        bbox=_bbox_from_polygon(polygon),
        region_type="table",
        text=markdown,
        confidence=sum(cell.confidence for row in rows for cell in row)
        / sum(len(row) for row in rows),
        source_sha256=first.source_sha256,
        page_image_sha256=first.page_image_sha256,
        content_sha256=table_hash,
        table={
            "row_count": len(table_rows),
            "column_count": column_count,
            "rows": table_rows,
            "source_region_ids": [cell.region_id for row in rows for cell in row],
        },
        recognition_status="spatial_table_candidate",
    )


@dataclass(frozen=True)
class OCRRegion:
    region_id: str
    page_number: int
    page_width_px: int
    page_height_px: int
    polygon: tuple[tuple[float, float], ...]
    bbox: dict[str, float]
    region_type: str
    text: str
    confidence: float
    source_sha256: str
    page_image_sha256: str
    content_sha256: str
    sensitive_categories: tuple[str, ...] = ()
    latex: str = ""
    table: dict[str, Any] = field(default_factory=dict)
    recognition_status: str = "recognized"

    @property
    def sensitive(self) -> bool:
        return bool(self.sensitive_categories)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": OCR_REGION_SCHEMA_VERSION,
            "region_id": self.region_id,
            "page": {
                "number": self.page_number,
                "width_px": self.page_width_px,
                "height_px": self.page_height_px,
                "dpi": OCR_DPI,
            },
            "coordinate_space": "normalized_top_left",
            "polygon": [[x, y] for x, y in self.polygon],
            "bbox": dict(self.bbox),
            "region_type": self.region_type,
            "content": {
                "text": self.text,
                "latex": self.latex,
                "table": dict(self.table),
                "recognition_status": self.recognition_status,
            },
            "confidence": round(self.confidence, 6),
            "engine": {"name": OCR_ENGINE_NAME, "mode": "offline_cpu"},
            "hashes": {
                "source_sha256": self.source_sha256,
                "page_image_sha256": self.page_image_sha256,
                "region_content_sha256": self.content_sha256,
            },
            "privacy": {
                "sensitive": self.sensitive,
                "categories": list(self.sensitive_categories),
                "redaction_state": "redacted" if self.sensitive else "not_required",
                "externalization_allowed": not self.sensitive,
                "raw_text_persisted": False if self.sensitive else True,
            },
        }


@dataclass(frozen=True)
class OCRPage:
    page_number: int
    width_px: int
    height_px: int
    image_sha256: str
    redacted_image_sha256: str
    asset_name: str
    regions: tuple[OCRRegion, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "page_number": self.page_number,
            "width_px": self.width_px,
            "height_px": self.height_px,
            "image_sha256": self.image_sha256,
            "redacted_image_sha256": self.redacted_image_sha256,
            "asset_name": self.asset_name,
            "sensitive_region_count": sum(region.sensitive for region in self.regions),
            "regions": [region.to_dict() for region in self.regions],
        }


@dataclass(frozen=True)
class OCRDocumentResult:
    status: str
    source_sha256: str
    engine_version: str = ""
    pages: tuple[OCRPage, ...] = ()
    failure_code: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": OCR_DOCUMENT_SCHEMA_VERSION,
            "status": self.status,
            "engine": {
                "name": OCR_ENGINE_NAME,
                "version": self.engine_version,
                "mode": "offline_cpu",
            },
            "source_sha256": self.source_sha256,
            "page_count": len(self.pages),
            "region_count": sum(len(page.regions) for page in self.pages),
            "sensitive_region_count": sum(
                region.sensitive for page in self.pages for region in page.regions
            ),
            "failure_code": self.failure_code,
            "external_model_used": False,
            "pages": [page.to_dict() for page in self.pages],
        }


class RapidOCROfflineAdapter:
    def __init__(self, engine_factory: Callable[[], Any] | None = None) -> None:
        self._engine_factory = engine_factory
        self._engine: Any | None = None

    def runtime(self) -> tuple[bool, str]:
        try:
            version = importlib.metadata.version("rapidocr-onnxruntime")
            if self._engine_factory is None:
                from rapidocr_onnxruntime import RapidOCR  # noqa: F401
            return True, version
        except (ImportError, importlib.metadata.PackageNotFoundError):
            return False, ""

    def _load(self) -> Any:
        if self._engine is None:
            if self._engine_factory is not None:
                self._engine = self._engine_factory()
            else:
                from rapidocr_onnxruntime import RapidOCR

                self._engine = RapidOCR()
        return self._engine

    def recognize(
        self,
        image: Any,
        *,
        page_number: int,
        source_sha256: str,
        page_image_sha256: str,
    ) -> tuple[OCRRegion, ...]:
        width, height = image.size
        raw_result, _ = self._load()(image)
        regions: list[OCRRegion] = []
        for ordinal, item in enumerate(raw_result or (), 1):
            if not isinstance(item, (list, tuple)) or len(item) < 3:
                continue
            raw_polygon, raw_text, raw_confidence = item[0], str(item[1]).strip(), float(item[2])
            if not raw_text:
                continue
            polygon = _normalize_polygon(raw_polygon, width, height)
            bbox = _bbox_from_polygon(polygon)
            sensitive_categories = detect_sensitive_categories(raw_text)
            visible_text = (
                f"[敏感信息已遮盖:{','.join(sensitive_categories)}]"
                if sensitive_categories
                else raw_text
            )
            region_type = classify_region_type(raw_text)
            recognition_status = "formula_candidate" if region_type == "formula" else "recognized"
            region_id = "ocr-" + _sha256_text(
                f"{source_sha256}:{page_number}:{ordinal}:{raw_text}:{polygon}"
            )[:24]
            regions.append(
                OCRRegion(
                    region_id=region_id,
                    page_number=page_number,
                    page_width_px=width,
                    page_height_px=height,
                    polygon=polygon,
                    bbox=bbox,
                    region_type=region_type,
                    text=visible_text,
                    confidence=max(0.0, min(1.0, raw_confidence)),
                    source_sha256=source_sha256,
                    page_image_sha256=page_image_sha256,
                    content_sha256=_sha256_text(raw_text),
                    sensitive_categories=sensitive_categories,
                    recognition_status=recognition_status,
                )
            )
        result = tuple(regions)
        table = _infer_table_region(result)
        return result + ((table,) if table is not None else ())


def _pixel_bbox(region: OCRRegion) -> tuple[int, int, int, int]:
    bbox = region.bbox
    left = int(bbox["x"] * region.page_width_px)
    top = int(bbox["y"] * region.page_height_px)
    right = int((bbox["x"] + bbox["width"]) * region.page_width_px)
    bottom = int((bbox["y"] + bbox["height"]) * region.page_height_px)
    return left, top, max(left + 1, right), max(top + 1, bottom)


def _atomic_save_png(image: Any, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    try:
        image.save(temporary, format="PNG")
        temporary.replace(path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _redacted_image(image: Any, regions: Iterable[OCRRegion]) -> Any:
    from PIL import ImageDraw

    redacted = image.copy().convert("RGB")
    draw = ImageDraw.Draw(redacted)
    for region in regions:
        if region.sensitive:
            draw.rectangle(_pixel_bbox(region), fill=(20, 24, 31), outline=(239, 68, 68), width=2)
    return redacted


def _render_pdf_pages(raw: bytes, page_numbers: set[int]) -> list[tuple[int, Any]]:
    import pypdfium2 as pdfium

    document = pdfium.PdfDocument(raw)
    rendered: list[tuple[int, Any]] = []
    try:
        for index in range(len(document)):
            page_number = index + 1
            if page_number not in page_numbers:
                continue
            page = document[index]
            try:
                bitmap = page.render(scale=OCR_DPI / 72.0)
                rendered.append((page_number, bitmap.to_pil().convert("RGB")))
            finally:
                page.close()
    finally:
        document.close()
    return rendered


def run_pdf_ocr(
    raw: bytes,
    *,
    source_sha256: str,
    page_numbers: Iterable[int],
    asset_dir: Path | None = None,
    adapter: RapidOCROfflineAdapter | None = None,
) -> OCRDocumentResult:
    adapter = adapter or RapidOCROfflineAdapter()
    available, engine_version = adapter.runtime()
    requested = {int(page) for page in page_numbers if int(page) > 0}
    if not requested:
        return OCRDocumentResult(
            status="not_required", source_sha256=source_sha256, engine_version=engine_version
        )
    if not available:
        return OCRDocumentResult(
            status="unavailable",
            source_sha256=source_sha256,
            engine_version=engine_version,
            failure_code="offline_ocr_runtime_unavailable",
        )
    try:
        pages: list[OCRPage] = []
        for page_number, image in _render_pdf_pages(raw, requested):
            buffer = BytesIO()
            image.save(buffer, format="PNG")
            image_hash = _sha256_bytes(buffer.getvalue())
            regions = adapter.recognize(
                image,
                page_number=page_number,
                source_sha256=source_sha256,
                page_image_sha256=image_hash,
            )
            redacted = _redacted_image(image, regions)
            redacted_buffer = BytesIO()
            redacted.save(redacted_buffer, format="PNG")
            asset_name = f"page-{page_number:04d}-redacted.png"
            if asset_dir is not None:
                _atomic_save_png(redacted, asset_dir / asset_name)
            pages.append(
                OCRPage(
                    page_number=page_number,
                    width_px=image.width,
                    height_px=image.height,
                    image_sha256=image_hash,
                    redacted_image_sha256=_sha256_bytes(redacted_buffer.getvalue()),
                    asset_name=asset_name,
                    regions=regions,
                )
            )
        return OCRDocumentResult(
            status="ready",
            source_sha256=source_sha256,
            engine_version=engine_version,
            pages=tuple(pages),
        )
    except Exception:
        return OCRDocumentResult(
            status="failed",
            source_sha256=source_sha256,
            engine_version=engine_version,
            failure_code="offline_ocr_processing_failed",
        )
