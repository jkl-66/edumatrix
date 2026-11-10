"""Shared background slide rendering for reading and course ingestion."""
from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import tempfile
import threading
from pathlib import Path

from config import CONFIG

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PPTX_PREVIEW_VERSION = "libreoffice-png-v1"
_PPTX_PREVIEW_LOCK = threading.Lock()


class PptxPreviewError(RuntimeError):
    pass


def _pptx_preview_root() -> Path:
    configured = str(os.getenv("EDUMATRIX_PPTX_PREVIEW_DIR") or "").strip()
    return Path(configured).resolve() if configured else (PROJECT_ROOT / "data" / "derived" / "pptx_previews").resolve()


def _libreoffice_executable() -> Path | None:
    configured = str(os.getenv("EDUMATRIX_LIBREOFFICE_PATH") or "").strip()
    candidates = [
        configured,
        shutil.which("soffice") or "",
        shutil.which("libreoffice") or "",
        "C:/Program Files/LibreOffice/program/soffice.com",
        "C:/Program Files/LibreOffice/program/soffice.exe",
        "C:/Program Files (x86)/LibreOffice/program/soffice.com",
        "C:/Program Files (x86)/LibreOffice/program/soffice.exe",
    ]
    for candidate in candidates:
        path = Path(candidate) if candidate else None
        if path and path.is_file():
            console_path = path.with_suffix(".com")
            return (console_path if path.suffix.lower() == ".exe" and console_path.is_file() else path).resolve()
    return None


def _cached_pptx_preview(cache_dir: Path) -> list[Path]:
    if not cache_dir.is_dir():
        return []
    slides = sorted(cache_dir.glob("slide-*.png"))
    if not slides or any(path.stat().st_size < 100 for path in slides):
        return []
    return slides


def _png_dimensions(path: Path) -> tuple[int, int]:
    with path.open("rb") as handle:
        header = handle.read(24)
    if len(header) != 24 or header[:8] != b"\x89PNG\r\n\x1a\n" or header[12:16] != b"IHDR":
        raise PptxPreviewError("preview_invalid")
    width = int.from_bytes(header[16:20], "big")
    height = int.from_bytes(header[20:24], "big")
    if width < 1 or height < 1:
        raise PptxPreviewError("preview_invalid")
    return width, height


def _render_pptx_preview(source_path: Path, source_hash: str) -> list[Path]:
    executable = _libreoffice_executable()
    if executable is None:
        raise PptxPreviewError("renderer_unavailable")
    version_root = _pptx_preview_root() / PPTX_PREVIEW_VERSION
    cache_dir = version_root / source_hash
    cached = _cached_pptx_preview(cache_dir)
    if cached:
        return cached

    with _PPTX_PREVIEW_LOCK:
        cached = _cached_pptx_preview(cache_dir)
        if cached:
            return cached
        version_root.mkdir(parents=True, exist_ok=True)
        profile_dir = version_root / ".libreoffice-profile"
        profile_dir.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(prefix=f".{source_hash[:12]}-", dir=version_root) as temp_name:
            work_dir = Path(temp_name)
            rendered_dir = work_dir / "rendered"
            rendered_dir.mkdir()
            timeout = min(300, max(10, int(os.getenv("EDUMATRIX_PPTX_RENDER_TIMEOUT_SECONDS", "90"))))
            command = [
                str(executable),
                f"-env:UserInstallation={profile_dir.resolve().as_uri()}",
                "--headless",
                "--nologo",
                "--nodefault",
                "--nolockcheck",
                "--nofirststartwizard",
                "--norestore",
                "--convert-to",
                "pdf:impress_pdf_Export",
                "--outdir",
                str(work_dir),
                str(source_path),
            ]
            try:
                completed = subprocess.run(
                    command,
                    capture_output=True,
                    check=False,
                    timeout=timeout,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
            except subprocess.TimeoutExpired as exc:
                raise PptxPreviewError("render_timeout") from exc
            pdf_path = next(work_dir.glob("*.pdf"), None)
            if completed.returncode != 0 or pdf_path is None or pdf_path.stat().st_size < 100:
                raise PptxPreviewError("render_failed")
            try:
                import fitz

                document = fitz.open(pdf_path)
                if len(document) < 1 or (CONFIG.max_document_pages > 0 and len(document) > CONFIG.max_document_pages):
                    document.close()
                    raise PptxPreviewError("page_count_invalid")
                matrix = fitz.Matrix(2, 2)
                for index, page in enumerate(document):
                    pixmap = page.get_pixmap(matrix=matrix, alpha=False)
                    (rendered_dir / f"slide-{index + 1:04d}.png").write_bytes(pixmap.tobytes("png"))
                document.close()
            except ImportError as exc:
                raise PptxPreviewError("pdf_renderer_unavailable") from exc
            except PptxPreviewError:
                raise
            except Exception as exc:
                raise PptxPreviewError("pdf_render_failed") from exc
            if cache_dir.exists():
                shutil.rmtree(cache_dir)
            os.replace(rendered_dir, cache_dir)
    return _cached_pptx_preview(cache_dir)


def render_pptx_bytes(raw: bytes) -> list[Path]:
    source_hash = hashlib.sha256(raw).hexdigest()
    cached = _cached_pptx_preview(_pptx_preview_root() / PPTX_PREVIEW_VERSION / source_hash)
    if cached:
        return cached
    with tempfile.TemporaryDirectory(prefix="edumatrix-slide-reading-") as name:
        original = Path(name) / "course.pptx"
        original.write_bytes(raw)
        return _render_pptx_preview(original, source_hash)
