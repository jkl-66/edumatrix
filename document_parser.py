from __future__ import annotations

import base64
import csv
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import zipfile
from dataclasses import dataclass, field
from io import BytesIO, StringIO
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, BinaryIO
from urllib.parse import urljoin, urlparse

try:
    from models import Evidence, EvidenceModality
except ImportError:
    # 如果无法导入，定义简单的替代类
    class Evidence:
        def __init__(self, **kwargs):
            for k, v in kwargs.items():
                setattr(self, k, v)

    class StrEnumMock:
        """模拟 Enum 成员，提供 .value 属性以兼容真实 EvidenceModality 的调用方式"""
        def __init__(self, value: str):
            self.value = value

        def __str__(self) -> str:
            return self.value

        def __repr__(self) -> str:
            return f"StrEnumMock({self.value!r})"

    class EvidenceModality:
        TEXT = StrEnumMock('text')
        CODE = StrEnumMock('code')
        IMAGE = StrEnumMock('image')


# ---------------------------------------------------------------------------
# 多模态视觉文档 RAG 管道 (Task 1)
# ---------------------------------------------------------------------------

_VISION_LLM_AVAILABLE: bool | None = None  # 延迟检测缓存


class DocumentLimitError(ValueError):
    """Raised before parsing when a document exceeds a resource limit."""


class DocumentParseError(ValueError):
    """A sanitized, format-aware parse failure safe to return through the API."""

    def __init__(self, code: str, message: str, *, file_format: str = "") -> None:
        super().__init__(message)
        self.code = code
        self.file_format = file_format


@dataclass(frozen=True)
class DocumentLocation:
    kind: str
    index: int
    label: str
    char_start: int
    char_end: int
    page_number: int | None = None
    slide_number: int | None = None
    cell_index: int | None = None
    cell_type: str = ""
    image_region: dict[str, Any] | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "index": self.index,
            "label": self.label,
            "char_start": self.char_start,
            "char_end": self.char_end,
            "page_number": self.page_number,
            "slide_number": self.slide_number,
            "cell_index": self.cell_index,
            "cell_type": self.cell_type,
            "image_region": dict(self.image_region) if self.image_region else None,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class ParsedDocument:
    filename: str
    file_format: str
    parser_version: str
    text: str
    source_sha256: str
    processed_sha256: str
    locations: tuple[DocumentLocation, ...]
    metadata: dict[str, Any] = field(default_factory=dict)
    warnings: tuple[str, ...] = ()
    schema_version: str = "edumatrix.document-parse.v1"

    def provenance(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "filename": self.filename,
            "file_format": self.file_format,
            "parser_version": self.parser_version,
            "source_sha256": self.source_sha256,
            "processed_sha256": self.processed_sha256,
            "locations": [location.to_dict() for location in self.locations],
            "metadata": dict(self.metadata),
            "warnings": list(self.warnings),
        }


PARSER_VERSIONS = {
    ".ppt": "edumatrix-ppt-legacy-v1",
    ".pdf": "edumatrix-pdf-text-v2",
    ".docx": "edumatrix-docx-v2",
    ".pptx": "edumatrix-pptx-v2",
    ".ipynb": "edumatrix-notebook-to-markdown-v2",
    ".csv": "edumatrix-csv-text-v1",
    ".tex": "edumatrix-tex-text-v1",
    ".epub": "edumatrix-epub-html-v1",
    ".md": "edumatrix-markdown-v1",
    ".txt": "edumatrix-text-v1",
    ".json": "edumatrix-json-text-v1",
    ".py": "edumatrix-python-text-v1",
    ".html": "edumatrix-html-assets-v1",
    ".htm": "edumatrix-html-assets-v1",
}


def _convert_legacy_ppt(raw: bytes, filename: str) -> tuple[bytes, dict[str, Any]]:
    """Convert an OLE .ppt only when a local office converter is available."""
    converter = shutil.which("soffice") or shutil.which("libreoffice")
    if not converter:
        raise DocumentParseError(
            "legacy_ppt_converter_unavailable",
            "旧版 PPT 需要本机 LibreOffice/soffice 转换为 PPTX；当前环境未提供转换器，请稍后重试或先另存为 PPTX。",
            file_format="ppt",
        )

    with tempfile.TemporaryDirectory(prefix="edumatrix-ppt-") as temp_dir:
        input_path = Path(temp_dir) / Path(filename).name
        output_path = Path(temp_dir) / f"{input_path.stem}.pptx"
        input_path.write_bytes(raw)
        try:
            completed = subprocess.run(
                [converter, "--headless", "--convert-to", "pptx", "--outdir", temp_dir, str(input_path)],
                capture_output=True,
                text=True,
                timeout=45,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise DocumentParseError(
                "legacy_ppt_conversion_failed",
                "旧版 PPT 转换暂时失败，原文件已保留，请重试或先另存为 PPTX。",
                file_format="ppt",
            ) from exc
        if completed.returncode != 0 or not output_path.is_file():
            raise DocumentParseError(
                "legacy_ppt_conversion_failed",
                "旧版 PPT 转换暂时失败，原文件已保留，请重试或先另存为 PPTX。",
                file_format="ppt",
            )
        converted = output_path.read_bytes()
        if not converted:
            raise DocumentParseError(
                "legacy_ppt_conversion_failed",
                "旧版 PPT 转换结果为空，原文件已保留，请重试或先另存为 PPTX。",
                file_format="ppt",
            )
        return converted, {
            "source_format": "ppt",
            "converted_format": "pptx",
            "conversion_mode": "local_office",
            "converter": Path(converter).name[:64],
        }


def _compose_located_blocks(
    blocks: list[tuple[str, dict[str, Any]]],
) -> tuple[str, tuple[DocumentLocation, ...]]:
    output: list[str] = []
    locations: list[DocumentLocation] = []
    cursor = 0
    for ordinal, (block, locator) in enumerate(blocks, 1):
        clean = block.strip()
        if not clean:
            continue
        if output:
            output.append("\n\n")
            cursor += 2
        start = cursor
        output.append(clean)
        cursor += len(clean)
        locations.append(
            DocumentLocation(
                kind=str(locator.get("kind") or "section"),
                index=int(locator.get("index") or ordinal),
                label=str(locator.get("label") or f"Section {ordinal}"),
                char_start=start,
                char_end=cursor,
                page_number=locator.get("page_number"),
                slide_number=locator.get("slide_number"),
                cell_index=locator.get("cell_index"),
                cell_type=str(locator.get("cell_type") or ""),
                image_region=dict(locator["image_region"]) if locator.get("image_region") else None,
                metadata=dict(locator.get("metadata") or {}),
            )
        )
    return "".join(output), tuple(locations)


def validate_document_limits(
    raw: bytes,
    filename: str,
    *,
    max_pages: int | None = None,
    max_archive_members: int | None = None,
    max_archive_uncompressed_bytes: int | None = None,
) -> None:
    """Validate page and archive expansion limits before invoking parsers."""
    from config import CONFIG

    if not raw:
        raise DocumentLimitError("文件内容为空")
    max_pages = CONFIG.max_document_pages if max_pages is None else max_pages
    max_archive_members = CONFIG.max_archive_members if max_archive_members is None else max_archive_members
    max_archive_uncompressed_bytes = (
        CONFIG.max_archive_uncompressed_bytes
        if max_archive_uncompressed_bytes is None
        else max_archive_uncompressed_bytes
    )
    ext = Path(filename).suffix.lower()

    if ext in {".docx", ".pptx", ".epub"}:
        try:
            with zipfile.ZipFile(BytesIO(raw)) as archive:
                infos = archive.infolist()
                if len(infos) > max_archive_members:
                    raise DocumentLimitError(
                        f"文档压缩包包含过多内部文件（上限 {max_archive_members}）"
                    )
                expanded_size = sum(max(0, info.file_size) for info in infos)
                if expanded_size > max_archive_uncompressed_bytes:
                    raise DocumentLimitError(
                        f"文档解压后体积超过限制（上限 {max_archive_uncompressed_bytes} bytes）"
                    )
                for info in infos:
                    if info.file_size > max_archive_uncompressed_bytes:
                        raise DocumentLimitError("文档内部文件超过解压体积限制")
                    if info.compress_size and info.file_size > info.compress_size * 1000:
                        raise DocumentLimitError("文档压缩比异常，已拒绝可能的压缩炸弹")
                if ext == ".pptx":
                    slide_count = sum(
                        1
                        for info in infos
                        if re.fullmatch(r"ppt/slides/slide\d+\.xml", info.filename)
                    )
                    if slide_count > max_pages:
                        raise DocumentLimitError(f"演示文稿页数超过限制（上限 {max_pages}）")
        except DocumentLimitError:
            raise
        except (zipfile.BadZipFile, OSError) as exc:
            raise DocumentLimitError(f"文档压缩包损坏或无法读取: {exc}") from exc

    if ext == ".pdf":
        page_count: int | None = None
        try:
            import fitz

            with fitz.open(stream=raw, filetype="pdf") as pdf:
                page_count = len(pdf)
        except ImportError:
            try:
                import PyPDF2

                page_count = len(PyPDF2.PdfReader(BytesIO(raw)).pages)
            except Exception:
                page_count = None
        except Exception as exc:
            raise DocumentLimitError(f"PDF 无法读取: {exc}") from exc
        if page_count is not None and page_count > max_pages:
            raise DocumentLimitError(f"PDF 页数超过限制（上限 {max_pages}）")


def _check_vision_llm() -> bool:
    """检测是否配置了多模态视觉大模型，结果缓存到模块级变量。"""
    global _VISION_LLM_AVAILABLE
    if _VISION_LLM_AVAILABLE is not None:
        return _VISION_LLM_AVAILABLE
    try:
        from config import CONFIG
        if CONFIG.multimodal_llm_api_key and CONFIG.multimodal_llm_endpoint:
            _VISION_LLM_AVAILABLE = True
            return True
        if os.getenv("ZHIPUAI_API_KEY", ""):
            _VISION_LLM_AVAILABLE = True
            return True
    except Exception:
        pass
    _VISION_LLM_AVAILABLE = False
    return False


def _render_pdf_to_images(raw: bytes, dpi: int = 150) -> list[dict]:
    """使用 PyMuPDF 将 PDF 每一页渲染为 PNG 图像。

    Args:
        raw: PDF 文件原始字节
        dpi: 渲染分辨率

    Returns:
        [{page: int, image_bytes: bytes, width: int, height: int}, ...]
        如果 PyMuPDF 不可用或渲染失败，返回空列表
    """
    pages = []
    try:
        import fitz  # PyMuPDF
        doc = fitz.open(stream=raw, filetype="pdf")
        zoom = dpi / 72.0  # PDF 默认 72 DPI
        matrix = fitz.Matrix(zoom, zoom)
        for page_num in range(len(doc)):
            page = doc.load_page(page_num)
            pix = page.get_pixmap(matrix=matrix)
            pages.append({
                "page": page_num + 1,
                "image_bytes": pix.tobytes("png"),
                "width": pix.width,
                "height": pix.height,
            })
        doc.close()
    except ImportError:
        pass  # fitz 未安装
    except Exception as e:
        print(f"  [document_parser] PDF 页面渲染失败: {e}")
    return pages


def _describe_image_with_multimodal_llm(
    image_base64: str,
    page_num: int,
    filename: str,
    *,
    owner_public_id: str | None = None,
    model_call_context: dict | None = None,
) -> str | None:
    """调用多模态视觉大模型描述 PDF 页面图片内容。

    Args:
        image_base64: Base64 编码的图片
        page_num: 页码（用于提示词）
        filename: 文件名（用于提示词）

    Returns:
        大模型生成的图片语义描述；如果调用失败返回 None
    """
    if not owner_public_id or not _check_vision_llm():
        return None
    try:
        import requests
        from config import CONFIG

        endpoint = CONFIG.multimodal_llm_endpoint
        api_key = CONFIG.multimodal_llm_api_key
        model = CONFIG.multimodal_llm_model or "glm-4v"

        if not endpoint or not api_key:
            # 尝试智谱 GLM-4v 兜底
            zhipu_key = os.getenv("ZHIPUAI_API_KEY", "")
            if zhipu_key:
                endpoint = "https://open.bigmodel.cn/api/paas/v4/chat/completions"
                api_key = zhipu_key
                model = "glm-4v"
            else:
                return None

        prompt = (
            f"你是一位知识图谱助教。请仔细查看教材 PDF 的第 {page_num} 页，"
            f"用 2-4 句话描述该页面的核心教学内容，包括：\n"
            f"1. 页面主要讲解的知识点/概念\n"
            f"2. 出现的公式、图表或代码的作用\n"
            f"3. 与机器学习课程中哪些前置知识相关\n\n"
            f"请用中文直接回答，不要加前缀。"
        )

        class VisionPageBackend:
            provider = "multimodal-openai-compatible"

            def __init__(self) -> None:
                self.model = model

            def generate(self, system_prompt: str, user_prompt: str, *, role: str) -> str:
                payload = {
                    "model": model,
                    "messages": [{
                        "role": "user",
                        "content": [
                            {"type": "text", "text": user_prompt},
                            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{image_base64}"}},
                        ],
                    }],
                    "temperature": 0.2,
                    "max_tokens": 1024,
                }
                headers = {
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {api_key}",
                }
                response = requests.post(endpoint, json=payload, headers=headers, timeout=60)
                response.raise_for_status()
                data = response.json()
                return data["choices"][0]["message"]["content"].strip()

        from app.m5_legacy_calls import audited_legacy_sync_text_call

        context = model_call_context or {}
        kwargs = {
            "system_prompt": "你是知识图谱教材页面视觉描述器。",
            "user_prompt": prompt,
            "role": "PDF视觉描述",
            "operation": "pdf_visual_description",
            "capability": "vision",
            "owner_public_id": owner_public_id,
            "course_id": context.get("course_id"),
            "trace_id": context.get("trace_id"),
            "input_summary": {
                "page_number": page_num,
                "image_bytes": len(image_base64) * 3 // 4,
                "image_payload_included": False,
                "filename_payload_included": False,
            },
            "response_validator": lambda raw: raw.strip() or (_ for _ in ()).throw(ValueError("empty visual description")),
        }
        if context.get("session_factory") is not None:
            kwargs["session_factory"] = context["session_factory"]
        return audited_legacy_sync_text_call(VisionPageBackend(), **kwargs)
    except ImportError:
        return None  # requests 未安装
    except Exception:
        print(f"  [document_parser] 多模态大模型图片描述失败 (第{page_num}页)，使用本地降级。")
        return None


def _describe_image_with_pil(image_bytes: bytes) -> str:
    """使用 PIL 生成基础图片元数据描述（非视觉模型时的降级方案）。"""
    try:
        from PIL import Image
        img = Image.open(BytesIO(image_bytes))
        w, h = img.size
        mode = img.mode
        fmt = img.format or "PNG"
        dominant = _get_dominant_colors(img)
        return f"教材图片 {fmt} {w}x{h} 模式:{mode} 主色调:{dominant}"
    except Exception:
        return f"教材图片 {len(image_bytes)} bytes"


def parse_pdf_visually(
    raw: bytes,
    filename: str,
    *,
    owner_public_id: str | None = None,
    model_call_context: dict | None = None,
) -> list[Evidence]:
    """解析 PDF 的视觉内容：逐页渲染为图片 → 调用多模态大模型生成语义描述。

    Args:
        raw: PDF 文件原始字节
        filename: 文件名（用于生成 Evidence ID）

    Returns:
        Evidence 列表（modality=IMAGE），包含视觉描述和页面图片路径
    """
    pages = _render_pdf_to_images(raw, dpi=150)
    if not pages:
        return []

    # 确保 patches 目录存在
    patches_dir = Path("data/patches")
    patches_dir.mkdir(parents=True, exist_ok=True)

    evidence_list = []
    base_name = Path(filename).stem.replace("..", "").replace("/", "").replace(chr(92), "")[:40]
    vision_available = _check_vision_llm()

    for page_info in pages:
        page_num = page_info["page"]
        img_bytes = page_info["image_bytes"]

        # 保存页面图片到 patches 目录
        img_filename = f"{base_name}_p{page_num}.png"
        img_path = patches_dir / img_filename
        with open(img_path, "wb") as f:
            f.write(img_bytes)

        # 生成图片语义描述
        if vision_available:
            img_b64 = base64.b64encode(img_bytes).decode("utf-8")
            description = _describe_image_with_multimodal_llm(
                img_b64,
                page_num,
                filename,
                owner_public_id=owner_public_id,
                model_call_context=model_call_context,
            )
            if not description:
                description = _describe_image_with_pil(img_bytes)
        else:
            description = _describe_image_with_pil(img_bytes)

        # 自动推断标签
        tags = _infer_tags(description)

        evidence_id = hashlib.sha256(f"{filename}:page{page_num}".encode()).hexdigest()[:16]
        evidence_list.append(Evidence(
            id=f"VIS_{evidence_id}",
            title=f"{filename} 第{page_num}页 视觉解析",
            content=description,
            modality=EvidenceModality.IMAGE,
            source=f"PDF视觉解析:{filename}",
            tags=tags,
            anchors=tuple(),
            metadata={
                "raw_image_ref": str(img_path),
                "page": page_num,
                "width": page_info["width"],
                "height": page_info["height"],
                "doc_source": filename,
            },
        ))

    return evidence_list


# ---------------------------------------------------------------------------
# 原有文档解析逻辑
# ---------------------------------------------------------------------------

def parse_uploaded_file(file: BinaryIO, filename: str) -> str:
    raw = file.read()
    return parse_document(raw, filename).text


class _HtmlAssetParser(HTMLParser):
    """Extract readable HTML text and preserve public image references."""

    _BLOCK_TAGS = {"article", "br", "div", "figcaption", "h1", "h2", "h3", "h4", "li", "p", "section"}
    _IGNORED_TAGS = {"script", "style", "noscript", "svg", "template"}

    def __init__(self, *, base_url: str = "") -> None:
        super().__init__(convert_charrefs=True)
        self.base_url = str(base_url or "")
        self.parts: list[str] = []
        self.image_assets: list[dict[str, Any]] = []
        self._ignored_depth = 0
        self._caption_depth = 0
        self._caption_parts: list[str] = []

    def _append_break(self) -> None:
        if self.parts and not self.parts[-1].endswith("\n"):
            self.parts.append("\n")

    def handle_starttag(self, tag: str, attrs) -> None:
        tag = str(tag or "").lower()
        attr_map = {str(key).lower(): str(value or "") for key, value in attrs}
        if tag in self._IGNORED_TAGS:
            self._ignored_depth += 1
            return
        if self._ignored_depth:
            return
        if tag in self._BLOCK_TAGS:
            self._append_break()
        if tag == "figcaption":
            self._caption_depth += 1
            self._caption_parts = []
        if tag != "img":
            return
        self._append_break()
        raw_src = attr_map.get("src") or attr_map.get("data-src") or ""
        resolved_src = urljoin(self.base_url, raw_src) if raw_src else ""
        parsed = urlparse(resolved_src)
        allowed = parsed.scheme in {"http", "https"} or resolved_src.startswith("data:image/")
        status = "candidate" if allowed else "needs_base_url" if raw_src else "missing_src"
        asset_index = len(self.image_assets) + 1
        alt = " ".join(attr_map.get("alt", "").split())
        caption = ""
        asset = {
            "asset_id": f"html-image-{asset_index}",
            "asset_type": "image",
            "url": resolved_src,
            "alt": alt,
            "caption": caption,
            "position": asset_index,
            "status": status,
            "citation_ready": False,
            "ocr_status": "pending_authorized_fetch" if allowed else "blocked",
            "text_source": "alt" if alt else "none",
        }
        self.image_assets.append(asset)
        label = alt or "未提供文字说明"
        self.parts.append(f"[网页图片 {asset_index} · alt 文本] {label}")
        self._append_break()

    def handle_endtag(self, tag: str) -> None:
        tag = str(tag or "").lower()
        if tag in self._IGNORED_TAGS and self._ignored_depth:
            self._ignored_depth -= 1
            return
        if self._ignored_depth:
            return
        if tag == "figcaption" and self._caption_depth:
            self._caption_depth -= 1
            caption = " ".join("".join(self._caption_parts).split())
            if caption and self.image_assets:
                self.image_assets[-1]["caption"] = caption
                if self.image_assets[-1]["text_source"] == "none":
                    self.image_assets[-1]["text_source"] = "caption"
            self._caption_parts = []
        if tag in self._BLOCK_TAGS:
            self._append_break()

    def handle_data(self, data: str) -> None:
        if self._ignored_depth:
            return
        clean = " ".join(str(data or "").split())
        if not clean:
            return
        if self._caption_depth:
            self._caption_parts.append(clean)
        self.parts.append(clean)

    def text(self) -> str:
        return "\n".join(line.strip() for line in " ".join(self.parts).splitlines() if line.strip())


def _parse_html_structured(
    raw: bytes,
    filename: str,
    *,
    base_url: str = "",
) -> tuple[str, tuple[DocumentLocation, ...], dict[str, Any], tuple[str, ...]]:
    charset = "utf-8"
    try:
        text_source = raw.decode(charset, errors="replace")
    except Exception as exc:
        raise DocumentParseError("html_decode_failed", "HTML 页面无法解码", file_format="html") from exc
    parser = _HtmlAssetParser(base_url=base_url)
    try:
        parser.feed(text_source)
        parser.close()
    except Exception as exc:
        raise DocumentParseError("html_parse_failed", "HTML 页面结构损坏或无法解析", file_format="html") from exc
    text = parser.text().strip()
    if not text and parser.image_assets:
        text = "\n".join(
            f"[网页图片 {asset['position']} · alt 文本] {asset['alt'] or '未提供文字说明'}"
            for asset in parser.image_assets
        )
    if not text:
        raise DocumentParseError("document_text_empty", "网页解析完成但没有可索引正文或图片说明", file_format="html")
    locations: list[DocumentLocation] = []
    for index, asset in enumerate(parser.image_assets, 1):
        marker = f"[网页图片 {index} · alt 文本]"
        char_start = text.find(marker)
        char_end = char_start + len(text[char_start: text.find("\n", char_start) if "\n" in text[char_start:] else len(text)]) if char_start >= 0 else 0
        locations.append(
            DocumentLocation(
                kind="html_image",
                index=index,
                label=f"网页图片 {index}",
                char_start=max(char_start, 0),
                char_end=max(char_end, 0),
                image_region={"asset_id": asset["asset_id"], "url": asset["url"]},
                metadata=dict(asset),
            )
        )
    warnings = ("html_images_require_authorized_fetch_or_ocr",) if parser.image_assets else ()
    metadata = {
        "engine": "html.parser",
        "image_count": len(parser.image_assets),
        "image_assets": [dict(asset) for asset in parser.image_assets],
        "capabilities": {
            "text": "best_effort",
            "images": "metadata_and_authorized_ocr" if parser.image_assets else "none_detected",
            "dynamic_content": "not_guaranteed",
        },
        "citation_ready": bool(text),
    }
    return text, tuple(locations), metadata, warnings


def parse_document(
    raw: bytes,
    filename: str,
    *,
    offline_ocr: bool = False,
    ocr_asset_dir: Path | None = None,
    base_url: str = "",
) -> ParsedDocument:
    """Parse a supported document without hiding corruption or provenance."""
    ext = Path(filename).suffix.lower()
    source_sha256 = hashlib.sha256(raw).hexdigest()
    if not raw:
        raise DocumentParseError("document_empty", "文件内容为空", file_format=ext.lstrip("."))

    if ext in {".pdf", ".docx", ".ppt", ".pptx", ".ipynb"}:
        try:
            validate_document_limits(raw, filename)
        except DocumentLimitError as exc:
            raise DocumentParseError(
                "document_limit_rejected", str(exc), file_format=ext.lstrip(".")
            ) from exc

    conversion_metadata: dict[str, Any] = {}
    if ext == ".ppt":
        raw, conversion_metadata = _convert_legacy_ppt(raw, filename)

    if ext in {".html", ".htm"}:
        text, locations, metadata, warnings = _parse_html_structured(raw, filename, base_url=base_url)
    elif ext == ".pdf":
        text, locations, metadata, warnings = _parse_pdf_structured(raw)
    elif ext == ".docx":
        text, locations, metadata, warnings = _parse_docx_structured(raw)
    elif ext in {".ppt", ".pptx"}:
        text, locations, metadata, warnings = _parse_pptx_structured(raw)
    elif ext == ".ipynb":
        text, locations, metadata, warnings = _parse_notebook_structured(raw)
    elif ext == ".csv":
        text, locations, metadata, warnings = _parse_csv_structured(raw, filename)
    elif ext == ".tex":
        text, locations, metadata, warnings = _parse_tex_structured(raw, filename)
    elif ext == ".epub":
        text, locations, metadata, warnings = _parse_epub_structured(raw, filename)
    elif ext in {".md", ".txt", ".json"}:
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise DocumentParseError(
                "document_encoding_invalid", "文本文件不是有效的 UTF-8", file_format=ext.lstrip(".")
            ) from exc
        text = text.replace("\r\n", "\n").replace("\r", "\n").strip()
        locations = (
            DocumentLocation(
                kind="document", index=1, label=filename, char_start=0, char_end=len(text)
            ),
        ) if text else ()
        metadata, warnings = {}, ()
    elif ext == ".py":
        try:
            code = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise DocumentParseError(
                "document_encoding_invalid", "Python 文件不是有效的 UTF-8", file_format="py"
            ) from exc
        text = f"【这是 Python 代码文件】\n{code}".strip()
        locations = (
            DocumentLocation(kind="code", index=1, label=filename, char_start=0, char_end=len(text)),
        )
        metadata, warnings = {}, ()
    elif ext in (".mp4", ".avi", ".mov", ".mkv", ".webm", ".flv"):
        text, locations, metadata, warnings = _parse_video_structured(raw, filename)
    else:
        raise DocumentParseError(
            "document_format_unsupported",
            f"不支持的文件类型: {ext or 'unknown'}",
            file_format=ext.lstrip("."),
        )

    if not text.strip():
        raise DocumentParseError(
            "document_text_empty",
            "文档解析完成但没有可索引文本",
            file_format=ext.lstrip("."),
        )
    normalized = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    metadata = {**conversion_metadata, **dict(metadata or {})}
    parsed = ParsedDocument(
        filename=filename,
        file_format=ext.lstrip("."),
        parser_version=PARSER_VERSIONS.get(ext, "edumatrix-media-text-v1"),
        text=normalized,
        source_sha256=source_sha256,
        processed_sha256=hashlib.sha256(normalized.encode("utf-8")).hexdigest(),
        locations=locations,
        metadata=metadata,
        warnings=tuple(warnings),
    )
    if ext == ".pdf" and offline_ocr:
        return enrich_pdf_with_offline_ocr(parsed, raw, asset_dir=ocr_asset_dir)
    return parsed


def enrich_pdf_with_offline_ocr(
    parsed: ParsedDocument,
    raw: bytes,
    *,
    asset_dir: Path | None = None,
) -> ParsedDocument:
    """OCR only image-like PDF pages and append typed, privacy-filtered regions."""
    from app.media_ocr import run_pdf_ocr

    scan_pages: list[int] = []
    for location in parsed.locations:
        if location.kind != "page" or location.page_number is None:
            continue
        page_text = parsed.text[location.char_start:location.char_end]
        page_text = re.sub(r"---\s*Page\s+\d+\s*---", "", page_text, flags=re.I)
        if len(re.sub(r"\W", "", page_text, flags=re.UNICODE)) < 24:
            scan_pages.append(location.page_number)

    result = run_pdf_ocr(
        raw,
        source_sha256=parsed.source_sha256,
        page_numbers=scan_pages,
        asset_dir=asset_dir,
    )
    report = result.to_dict()
    metadata = {**dict(parsed.metadata), "ocr": report}
    warnings = list(parsed.warnings)
    if result.status == "unavailable":
        warnings.append("offline_ocr_runtime_unavailable")
    elif result.status == "failed":
        warnings.append("offline_ocr_processing_failed")

    text = parsed.text
    locations = list(parsed.locations)
    region_index = 0
    for page in result.pages:
        for region in page.regions:
            region_index += 1
            block = f"[OCR 第 {page.page_number} 页 · {region.region_type}]\n{region.text}"
            separator = "\n\n" if text else ""
            start = len(text) + len(separator)
            text += separator + block
            end = len(text)
            region_contract = region.to_dict()
            locations.append(
                DocumentLocation(
                    kind="ocr_region",
                    index=region_index,
                    label=f"第 {page.page_number} 页 OCR 区域 {region_index}",
                    char_start=start,
                    char_end=end,
                    page_number=page.page_number,
                    image_region=region_contract,
                    metadata={
                        "region_id": region.region_id,
                        "region_type": region.region_type,
                        "confidence": region.confidence,
                        "asset_name": page.asset_name,
                        "redacted_image_sha256": page.redacted_image_sha256,
                    },
                )
            )
    normalized = text.replace("\r\n", "\n").replace("\r", "\n").strip()
    return ParsedDocument(
        filename=parsed.filename,
        file_format=parsed.file_format,
        parser_version="edumatrix-pdf-ocr-v1" if result.pages else parsed.parser_version,
        text=normalized,
        source_sha256=parsed.source_sha256,
        processed_sha256=hashlib.sha256(normalized.encode("utf-8")).hexdigest(),
        locations=tuple(locations),
        metadata=metadata,
        warnings=tuple(dict.fromkeys(warnings)),
    )


def _parse_pdf(raw: bytes) -> str:
    return _parse_pdf_structured(raw)[0]


def _parse_pdf_structured(
    raw: bytes,
) -> tuple[str, tuple[DocumentLocation, ...], dict[str, Any], tuple[str, ...]]:
    """Extract PDF pages and retain an exact page-to-character map."""
    primary_error: Exception | None = None
    try:
        import pdfplumber

        blocks: list[tuple[str, dict[str, Any]]] = []
        with pdfplumber.open(BytesIO(raw)) as pdf:
            for page_num, page in enumerate(pdf.pages, 1):
                page_parts = [f"--- Page {page_num} ---"]
                text = page.extract_text(x_tolerance=3, y_tolerance=3) or ""
                if text.strip():
                    page_parts.append(text.strip())
                tables = page.extract_tables()
                for table in tables:
                    if not table:
                        continue
                    md_lines = []
                    header = [_markdown_escape_cell(c) for c in (table[0] or [])]
                    if header:
                        md_lines.append("| " + " | ".join(header) + " |")
                        md_lines.append("| " + " | ".join("---" for _ in header) + " |")
                    for row in table[1:]:
                        cells = [_markdown_escape_cell(c) for c in (row or [])]
                        if cells:
                            md_lines.append("| " + " | ".join(cells) + " |")
                    if md_lines:
                        page_parts.append("\n".join(md_lines))
                blocks.append((
                    "\n\n".join(page_parts),
                    {
                        "kind": "page",
                        "index": page_num,
                        "label": f"第 {page_num} 页",
                        "page_number": page_num,
                        "metadata": {"table_count": len(tables)},
                    },
                ))
        text, locations = _compose_located_blocks(blocks)
        return text, locations, {"page_count": len(blocks), "engine": "pdfplumber"}, ()
    except Exception as exc:
        primary_error = exc

    try:
        import PyPDF2

        reader = PyPDF2.PdfReader(BytesIO(raw))
        blocks = [
            (
                f"--- Page {page_num} ---\n\n{page.extract_text() or ''}",
                {
                    "kind": "page",
                    "index": page_num,
                    "label": f"第 {page_num} 页",
                    "page_number": page_num,
                },
            )
            for page_num, page in enumerate(reader.pages, 1)
        ]
        text, locations = _compose_located_blocks(blocks)
        return (
            text,
            locations,
            {"page_count": len(blocks), "engine": "PyPDF2"},
            ("pdfplumber_failed_used_pypdf2",),
        )
    except Exception as fallback_error:
        raise DocumentParseError(
            "pdf_parse_failed",
            "PDF 文件损坏、加密或无法提取文本",
            file_format="pdf",
        ) from (fallback_error if primary_error is None else primary_error)


def _markdown_escape_cell(value: str | None) -> str:
    """转义表格单元格中可能破坏 Markdown 表格的字符。"""
    if value is None:
        return ""
    return value.replace("|", "\\|").replace("\n", " ").strip()


def _parse_docx(raw: bytes) -> str:
    return _parse_docx_structured(raw)[0]


def _parse_docx_structured(
    raw: bytes,
) -> tuple[str, tuple[DocumentLocation, ...], dict[str, Any], tuple[str, ...]]:
    try:
        import docx

        doc = docx.Document(BytesIO(raw))
        blocks: list[tuple[str, dict[str, Any]]] = []
        paragraph_metadata: list[dict[str, Any]] = []
        heading_candidates: list[dict[str, Any]] = []
        paragraph_count = 0
        table_count = 0
        for para_index, para in enumerate(doc.paragraphs, 1):
            text = para.text.strip()
            style_name = str(getattr(para.style, "name", "") or "")
            style_lower = style_name.casefold()
            heading_level = None
            style_match = re.search(r"(?:heading|标题)\s*([1-9])", style_lower)
            if style_match:
                heading_level = int(style_match.group(1))
            elif re.match(r"^(?:第\s*[0-9一二三四五六七八九十百]+\s*[章节篇]|[一二三四五六七八九十]+[、.]|\d+(?:\.\d+)*[、.])\s*\S+", text):
                heading_level = 1
            paragraph_metadata.append({
                "index": para_index,
                "text": text,
                "style": style_name,
                "heading_level": heading_level,
            })
            if text and heading_level:
                heading_candidates.append({
                    "index": para_index,
                    "text": text,
                    "style": style_name,
                    "heading_level": heading_level,
                })
            if text:
                paragraph_count += 1
                blocks.append((
                    text,
                    {
                        "kind": "paragraph",
                        "index": para_index,
                        "label": f"段落 {para_index}",
                        "metadata": {"style": style_name},
                    },
                ))
        for table_index, table in enumerate(doc.tables, 1):
            table_count += 1
            rows: list[str] = []
            for row in table.rows:
                cells = [cell.text.strip() for cell in row.cells]
                rows.append(" | ".join(cells))
            blocks.append((
                "\n".join(rows),
                {
                    "kind": "table",
                    "index": table_index,
                    "label": f"表格 {table_index}",
                    "metadata": {"row_count": len(rows)},
                },
            ))
        text, locations = _compose_located_blocks(blocks)
        return text, locations, {
            "paragraph_count": paragraph_count,
            "table_count": table_count,
            "engine": "python-docx",
            "paragraphs": paragraph_metadata,
            "heading_candidates": heading_candidates,
        }, ()
    except Exception as exc:
        raise DocumentParseError(
            "docx_parse_failed",
            "DOCX 文件损坏或无法读取",
            file_format="docx",
        ) from exc


def _parse_pptx(raw: bytes) -> str:
    return _parse_pptx_structured(raw)[0]


def _parse_pptx_structured(
    raw: bytes,
) -> tuple[str, tuple[DocumentLocation, ...], dict[str, Any], tuple[str, ...]]:
    try:
        from pptx import Presentation

        prs = Presentation(BytesIO(raw))
        blocks: list[tuple[str, dict[str, Any]]] = []
        image_count = 0
        notes_count = 0
        for slide_num, slide in enumerate(prs.slides, 1):
            slide_texts = [f"--- 幻灯片 {slide_num} ---"]
            slide_images = 0
            for shape in slide.shapes:
                if shape.has_text_frame:
                    for para in shape.text_frame.paragraphs:
                        text = para.text.strip()
                        if text:
                            slide_texts.append(text)
                if shape.has_table:
                    table = shape.table
                    for row in table.rows:
                        cells = [cell.text.strip() for cell in row.cells]
                        slide_texts.append(" | ".join(cells))
                if hasattr(shape, "image"):
                    try:
                        img_bytes = shape.image.blob
                        image_count += 1
                        slide_images += 1
                        img_desc = _describe_image(img_bytes)
                        if img_desc:
                            slide_texts.append(f"[图片描述] {img_desc}")
                    except Exception:
                        pass
            if slide.has_notes_slide:
                notes_text = slide.notes_slide.notes_text_frame.text.strip()
                if notes_text:
                    notes_count += 1
                    slide_texts.append(f"[演讲者备注] {notes_text}")
            blocks.append((
                "\n".join(slide_texts),
                {
                    "kind": "slide",
                    "index": slide_num,
                    "label": f"幻灯片 {slide_num}",
                    "slide_number": slide_num,
                    "metadata": {"image_count": slide_images},
                },
            ))
        text, locations = _compose_located_blocks(blocks)
        return text, locations, {
            "slide_count": len(blocks),
            "image_count": image_count,
            "notes_count": notes_count,
            "engine": "python-pptx",
        }, ()
    except Exception as exc:
        raise DocumentParseError(
            "pptx_parse_failed",
            "PPTX 文件损坏或无法读取",
            file_format="pptx",
        ) from exc


def _parse_notebook_structured(
    raw: bytes,
) -> tuple[str, tuple[DocumentLocation, ...], dict[str, Any], tuple[str, ...]]:
    try:
        import nbformat

        notebook = nbformat.reads(raw.decode("utf-8"), as_version=4)
    except Exception as exc:
        raise DocumentParseError(
            "notebook_parse_failed",
            "Notebook 不是有效的 Jupyter nbformat 4 文档",
            file_format="ipynb",
        ) from exc

    from config import CONFIG

    if len(notebook.cells) > CONFIG.max_document_pages:
        raise DocumentParseError(
            "document_limit_rejected",
            f"Notebook 单元数量超过限制（上限 {CONFIG.max_document_pages}）",
            file_format="ipynb",
        )
    blocks: list[tuple[str, dict[str, Any]]] = []
    markdown_cells = 0
    code_cells = 0
    stripped_outputs = 0
    skipped_cells = 0
    for zero_index, cell in enumerate(notebook.cells):
        source = str(cell.get("source") or "").strip()
        cell_type = str(cell.get("cell_type") or "")
        if not source or cell_type not in {"markdown", "code", "raw"}:
            skipped_cells += 1
            continue
        if cell_type == "markdown":
            markdown_cells += 1
            rendered = source
        elif cell_type == "code":
            code_cells += 1
            stripped_outputs += len(cell.get("outputs") or [])
            rendered = f"```python\n{source}\n```"
        else:
            rendered = f"```text\n{source}\n```"
        blocks.append((
            rendered,
            {
                "kind": "cell",
                "index": zero_index + 1,
                "label": f"单元 {zero_index + 1} ({cell_type})",
                "cell_index": zero_index,
                "cell_type": cell_type,
            },
        ))
    text, locations = _compose_located_blocks(blocks)
    return text, locations, {
        "nbformat": int(notebook.nbformat),
        "nbformat_minor": int(notebook.nbformat_minor),
        "cell_count": len(notebook.cells),
        "markdown_cells": markdown_cells,
        "code_cells": code_cells,
        "skipped_cells": skipped_cells,
        "stripped_output_count": stripped_outputs,
        "outputs_included": False,
        "execution_counts_included": False,
        "engine": "nbformat",
    }, ()


def _parse_csv_structured(
    raw: bytes,
    filename: str,
) -> tuple[str, tuple[DocumentLocation, ...], dict[str, Any], tuple[str, ...]]:
    """Parse CSV rows into the same located text representation as other documents."""
    try:
        decoded = raw.decode("utf-8-sig")
        rows = list(csv.reader(StringIO(decoded)))
    except (UnicodeDecodeError, csv.Error) as exc:
        raise DocumentParseError(
            "csv_parse_failed", "CSV 文件不是有效的 UTF-8 或格式损坏", file_format="csv"
        ) from exc
    blocks: list[tuple[str, dict[str, Any]]] = []
    for index, row in enumerate(rows, 1):
        values = [str(value).strip() for value in row]
        if not any(values):
            continue
        blocks.append((
            " | ".join(values),
            {"kind": "row", "index": index, "label": f"第 {index} 行"},
        ))
    text, locations = _compose_located_blocks(blocks)
    return text, locations, {
        "row_count": len(rows),
        "non_empty_row_count": len(blocks),
        "column_count": max((len(row) for row in rows), default=0),
        "engine": "python-csv",
    }, ()


def _parse_tex_structured(
    raw: bytes,
    filename: str,
) -> tuple[str, tuple[DocumentLocation, ...], dict[str, Any], tuple[str, ...]]:
    """Strip TeX control syntax while retaining readable source text and location."""
    try:
        source = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise DocumentParseError(
            "tex_decode_failed", "TeX 文件不是有效的 UTF-8", file_format="tex"
        ) from exc
    text = re.sub(r"(?m)%[^\n]*", "", source)
    text = re.sub(r"\\(?:[A-Za-z]+|.)", " ", text)
    text = re.sub(r"\{([^{}]*)\}", r"\1", text)
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        raise DocumentParseError("document_text_empty", "TeX 文件没有可索引正文", file_format="tex")
    return text, (
        DocumentLocation(kind="document", index=1, label=filename, char_start=0, char_end=len(text)),
    ), {"engine": "tex-text-normalizer"}, ()


def _parse_epub_structured(
    raw: bytes,
    filename: str,
) -> tuple[str, tuple[DocumentLocation, ...], dict[str, Any], tuple[str, ...]]:
    """Read EPUB XHTML chapters through the canonical HTML parser."""
    try:
        archive = zipfile.ZipFile(BytesIO(raw))
    except (zipfile.BadZipFile, OSError) as exc:
        raise DocumentParseError("epub_parse_failed", "EPUB 压缩包损坏或无法读取", file_format="epub") from exc
    blocks: list[tuple[str, dict[str, Any]]] = []
    skipped = 0
    with archive:
        names = [name for name in archive.namelist() if name.lower().endswith((".xhtml", ".html", ".htm"))]
        for index, name in enumerate(names, 1):
            try:
                chapter_text, _, _, _ = _parse_html_structured(archive.read(name), name)
            except (KeyError, DocumentParseError):
                skipped += 1
                continue
            blocks.append((chapter_text, {"kind": "chapter", "index": index, "label": name}))
    text, locations = _compose_located_blocks(blocks)
    if not text:
        raise DocumentParseError("document_text_empty", "EPUB 没有可索引正文", file_format="epub")
    warnings = ("epub_chapters_skipped",) if skipped else ()
    return text, locations, {
        "chapter_count": len(names),
        "parsed_chapter_count": len(blocks),
        "skipped_chapter_count": skipped,
        "engine": "zipfile-html-parser",
    }, warnings


def _describe_image(img_bytes: bytes) -> str:
    try:
        import io
        from PIL import Image
        img = Image.open(io.BytesIO(img_bytes))
        w, h = img.size
        mode = img.mode
        format_name = img.format or "unknown"
        dominant_colors = _get_dominant_colors(img)
        return f"图片 {format_name} {w}x{h} 模式:{mode} 主色调:{dominant_colors}"
    except ImportError:
        return f"图片 {len(img_bytes)} bytes (需安装Pillow以解析)"


def _get_dominant_colors(img, n=3):
    try:
        reduced = img.resize((32, 32))
        palette = reduced.getcolors(1024)
        if not palette:
            return "未知"
        palette.sort(key=lambda x: x[0], reverse=True)
        colors = []
        for count, color in palette[:n]:
            colors.append(f"rgb{color[:3]}")
        return ", ".join(colors)
    except Exception:
        return "未知"


def _parse_video_structured(
    raw: bytes,
    filename: str,
) -> tuple[str, tuple[DocumentLocation, ...], dict[str, Any], tuple[str, ...]]:
    """Return honest media evidence without treating metadata as a transcript."""
    text = _transcribe_video(raw, filename).strip()
    if not text:
        text = f"[视频 {filename}] 仅保留媒体记录，尚未取得可引用字幕或转写。"
    lowered = text.lower()
    transcript_ready = not any(
        marker in lowered
        for marker in ("未启用", "未返回", "需安装", "转写失败", "无音轨", "仅元数据", "仅保留媒体记录")
    )
    transcript_status = "ready" if transcript_ready else "unavailable"
    warning = () if transcript_ready else ("video_transcript_unavailable_metadata_only",)
    metadata = {
        "media": {
            "metadata_status": "available",
            "transcript_status": transcript_status,
            "subtitles_status": "not_requested",
            "keyframes_status": "not_requested",
            "citation_ready": transcript_ready,
            "citation_boundary": "仅实际取得字幕/转写/关键帧后可引用；媒体链接和元数据不等于正文。",
        },
        "capabilities": {
            "metadata": True,
            "transcript": transcript_ready,
            "subtitles": "when_available",
            "keyframes": "not_requested",
        },
    }
    locations = (
        DocumentLocation(
            kind="media",
            index=1,
            label=filename,
            char_start=0,
            char_end=len(text),
            metadata=dict(metadata["media"]),
        ),
    )
    return text, locations, metadata, warning


def _transcribe_video(raw: bytes, filename: str) -> str:
    temp_path = None
    try:
        import tempfile
        temp_dir = Path("data/uploads/temp_videos")
        temp_dir.mkdir(parents=True, exist_ok=True)
        temp_path = temp_dir / Path(filename).name
        with open(temp_path, "wb") as f:
            f.write(raw)

        transcription = _audio_transcription(str(temp_path))
        if transcription:
            return transcription

        try:
            from moviepy import VideoFileClip
            audio_path = str(temp_path) + ".wav"
            with VideoFileClip(str(temp_path)) as video:
                if video.audio is None:
                    return f"[视频 {filename}] 无音轨，仅元数据: {video.duration:.1f}s {video.size}"
                if not _local_whisper_enabled():
                    return (
                        f"[视频 {filename}] 已检测到音轨，本地语音转写未启用；"
                        f"仅元数据: {video.duration:.1f}s {video.size}"
                    )
                video.audio.write_audiofile(audio_path, logger=None)
            with open(audio_path, "rb") as af:
                audio_bytes = af.read()
            os.remove(audio_path)
            text = _speech_to_text(audio_bytes)
            duration = "(语音转文字完成)"
            return f"[视频 {filename}] {duration}\n{text}" if text else f"[视频 {filename}] 语音转文字未返回结果"
        except Exception:
            pass

        return f"[视频 {filename}] 需安装 moviepy + whisper 实现语音转文字"
    except Exception as e:
        return f"[视频 {filename}] 转写失败: {e}"
    finally:
        if temp_path and temp_path.exists():
            try:
                os.remove(temp_path)
            except Exception:
                pass


def _local_whisper_enabled() -> bool:
    return os.getenv("EDUMATRIX_ENABLE_LOCAL_WHISPER", "").strip().lower() in {
        "1", "true", "yes", "on",
    }


def _audio_transcription(audio_path: str) -> str:
    if not _local_whisper_enabled():
        return ""
    try:
        import whisper
        model = whisper.load_model("base")
        result = model.transcribe(audio_path, language="zh")
        segments = result.get("segments", [])
        texts = []
        for seg in segments:
            start = seg.get("start", 0)
            end = seg.get("end", 0)
            text = seg.get("text", "").strip()
            if text:
                texts.append(f"[{start:.1f}s-{end:.1f}s] {text}")
        return "\n".join(texts) if texts else result.get("text", "")
    except ImportError:
        pass
    try:
        import subprocess
        result = subprocess.run(
            ["whisper", audio_path, "--model", "base", "--output_format", "txt"],
            capture_output=True, text=True, timeout=300
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass
    return ""


def _speech_to_text(audio_bytes: bytes) -> str:
    if not _local_whisper_enabled():
        return ""
    try:
        import io
        import whisper
        model = whisper.load_model("base")
        import tempfile
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            f.write(audio_bytes)
            tmp_path = f.name
        try:
            result = model.transcribe(tmp_path, language="zh")
            return result.get("text", "")
        finally:
            os.unlink(tmp_path)
    except ImportError:
        pass
    return ""


def parse_pptx_slides(raw: bytes) -> tuple[dict, ...]:
    slides = []
    try:
        from pptx import Presentation
        from pptx.util import Inches, Pt
        prs = Presentation(BytesIO(raw))
        for slide_num, slide in enumerate(prs.slides, 1):
            texts = []
            images = []
            for shape in slide.shapes:
                if shape.has_text_frame:
                    for para in shape.text_frame.paragraphs:
                        t = para.text.strip()
                        if t:
                            texts.append(t)
                if hasattr(shape, "image"):
                    try:
                        img_bytes = shape.image.blob
                        import base64
                        img_b64 = base64.b64encode(img_bytes).decode("utf-8")
                        images.append({"data": img_b64, "content_type": shape.image.content_type})
                    except Exception:
                        pass
            slides.append({
                "slide_num": slide_num,
                "text": "\n".join(texts),
                "images": images,
                "notes": slide.notes_slide.notes_text_frame.text.strip() if slide.has_notes_slide else "",
            })
    except Exception:
        pass
    return tuple(slides)


def chunk_document(text: str, source: str, chunk_size: int = 520, overlap: int = 80) -> tuple[Evidence, ...]:
    """将文档切分为父子分块结构。

    对于非代码文档：
      -父块 (Parent): ~1000-1500 字，按段落边界切分
      -子块 (Child): ~200-250 字，在父块内部切分
      -每个子块的 Evidence.metadata 包含 parent_content 供 RAG 替换
    对于代码文件：保持原有类和函数边界切分逻辑。
    """
    if not text.strip():
        return ()
    
    # 判断是否是代码文件
    is_code_file = source.lower().endswith('.py')
    
    if is_code_file:
        # 代码文件：优先按类和函数边界切分（保持原有逻辑）
        return _chunk_code(text, source)
    else:
        # 普通文档：父子分块
        return _chunk_with_parent_child(text, source, child_size=chunk_size)


def _chunk_code(text: str, source: str) -> tuple[Evidence, ...]:
    """代码文件分块（保持原有逻辑）。"""
    separators = ["\nclass ", "\ndef ", "\n\n", "\n", " ", ""]
    chunk_size = 1000
    overlap = 200
    text = text.strip()
    
    chunks: list[Evidence] = []
    start = 0
    idx = 1
    text_len = len(text)
    
    while start < text_len:
        end = min(text_len, start + chunk_size)
        content = text[start:end]
        
        if end < text_len:
            best_split = end
            for sep in separators:
                pos = content.rfind(sep)
                if pos > chunk_size // 2:
                    best_split = start + pos + len(sep)
                    break
            end = best_split
        
        content = text[start:end].strip()
        if not content:
            start += 1
            continue
            
        chunk_id = hashlib.sha256(f"{source}:{idx}:{content[:64]}".encode()).hexdigest()[:16]
        chunks.append(Evidence(
            id=chunk_id,
            title=f"{source} chunk {idx}",
            content=content,
            modality=EvidenceModality.TEXT,
            source=source,
            tags=_infer_tags(content),
            anchors=tuple(),
            metadata={"chunk_index": idx, "doc_source": source},
        ))
        if end == text_len:
            break
        start = max(0, end - overlap)
        idx += 1
    return tuple(chunks)


def _chunk_with_parent_child(text: str, source: str, child_size: int = 250) -> tuple[Evidence, ...]:
    """父子分块：先切父块(~1000-1500字)，再在每个父块内切子块(~200-250字)。"""
    if not text.strip():
        return ()
    
    # 保留原始段落: 按双换行切分出自然段落
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    if not paragraphs:
        paragraphs = [text.strip()]
    
    # 合并段落为父块 (~1000-1500 字)
    parents: list[str] = []
    current_parent = ""
    for para in paragraphs:
        if len(current_parent) + len(para) < 1200:
            current_parent = (current_parent + "\n\n" + para).strip()
        else:
            if current_parent:
                parents.append(current_parent)
            current_parent = para
    if current_parent:
        parents.append(current_parent)
    
    # 如果父块太大(>2000字)，按句号/换行再分割
    refined_parents: list[str] = []
    for p in parents:
        if len(p) > 2000:
            # 尝试按句号分割
            sub_parts = re.split(r'(?<=[。！？.!?])\s+', p)
            buffer = ""
            for sp in sub_parts:
                if len(buffer) + len(sp) < 1200:
                    # Keep an explicit separator when sentence splitting
                    # consumed newlines. Without it, adjacent Markdown list
                    # items become concatenated and canonical evidence
                    # locations can no longer be reconstructed from the
                    # frozen document text.
                    buffer = (buffer + " " + sp).strip()
                else:
                    if buffer:
                        refined_parents.append(buffer)
                    buffer = sp
            if buffer:
                refined_parents.append(buffer)
        else:
            refined_parents.append(p)
    parents = refined_parents
    
    children: list[Evidence] = []
    for parent_idx, parent_text in enumerate(parents, 1):
        # 在父块内切子块 (~200-250 字)
        # 优先在句子边界切割
        sentences = re.split(r'(?<=[。！？.!?\n])\s*', parent_text)
        sentences = [s.strip() for s in sentences if s.strip()]
        
        child_idx = 1
        child_buffer = ""
        for sent in sentences:
            if len(child_buffer) + len(sent) < child_size:
                child_buffer = (child_buffer + " " + sent).strip()
            else:
                if child_buffer:
                    chunk_id = hashlib.sha256(f"{source}:p{parent_idx}c{child_idx}:{child_buffer[:64]}".encode()).hexdigest()[:16]
                    children.append(Evidence(
                        id=chunk_id,
                        title=f"{source} P{parent_idx}C{child_idx}",
                        content=child_buffer,
                        modality=EvidenceModality.TEXT,
                        source=source,
                        tags=_infer_tags(child_buffer),
                        anchors=tuple(),
                        metadata={
                            "chunk_index": child_idx,
                            "parent_index": parent_idx,
                            "child_index": child_idx,
                            "doc_source": source,
                            "parent_content": parent_text,
                        },
                    ))
                    child_idx += 1
                child_buffer = sent
        if child_buffer:
            chunk_id = hashlib.sha256(f"{source}:p{parent_idx}c{child_idx}:{child_buffer[:64]}".encode()).hexdigest()[:16]
            children.append(Evidence(
                id=chunk_id,
                title=f"{source} P{parent_idx}C{child_idx}",
                content=child_buffer,
                modality=EvidenceModality.TEXT,
                source=source,
                tags=_infer_tags(child_buffer),
                anchors=tuple(),
                metadata={
                    "chunk_index": child_idx,
                    "parent_index": parent_idx,
                    "child_index": child_idx,
                    "doc_source": source,
                    "parent_content": parent_text,
                },
            ))
    
    return tuple(children)


def _infer_tags(content: str) -> tuple[str, ...]:
    tags: list[str] = []
    topic_map = {
        "池化": "池化层", "卷积": "卷积", "梯度": "梯度下降",
        "反向传播": "反向传播", "链式法则": "链式法则",
        "逻辑回归": "逻辑回归", "线性回归": "线性回归",
        "过拟合": "过拟合", "正则化": "正则化",
        "交叉验证": "交叉验证", "混淆矩阵": "混淆矩阵",
        "机器学习": "机器学习", "分类": "分类", "回归": "回归",
        "聚类": "聚类", "神经网络": "神经网络",
        "Python": "Python", "numpy": "NumPy", "pandas": "Pandas",
        "matplotlib": "Matplotlib", "scikit-learn": "ScikitLearn",
        "CNN": "CNN", "RNN": "RNN", "transformer": "Transformer",
        "注意力": "注意力机制", "损失函数": "损失函数",
        "激活函数": "激活函数", "归一化": "归一化",
    }
    seen = set()
    for keyword, tag in topic_map.items():
        if keyword in content and tag not in seen:
            tags.append(tag)
            seen.add(tag)
    return tuple(tags[:8])
