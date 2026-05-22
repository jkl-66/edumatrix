from __future__ import annotations

import hashlib
import os
import re
from io import BytesIO
from pathlib import Path
from typing import BinaryIO

from models import Evidence, EvidenceModality


def parse_uploaded_file(file: BinaryIO, filename: str) -> str:
    ext = Path(filename).suffix.lower()
    raw = file.read()
    if ext == ".pdf":
        return _parse_pdf(raw)
    elif ext == ".pptx" or ext == ".ppt":
        return _parse_pptx(raw)
    elif ext == ".md":
        return raw.decode("utf-8", errors="replace")
    elif ext == ".txt":
        return raw.decode("utf-8", errors="replace")
    elif ext in (".mp4", ".avi", ".mov", ".mkv", ".webm", ".flv"):
        return _transcribe_video(raw, filename)
    else:
        return raw.decode("utf-8", errors="replace")


def _parse_pdf(raw: bytes) -> str:
    try:
        import PyPDF2
        reader = PyPDF2.PdfReader(raw)
        return "\n".join(page.extract_text() or "" for page in reader.pages)
    except ImportError:
        pass
    try:
        import pdfplumber
        import io
        with pdfplumber.open(io.BytesIO(raw)) as pdf:
            return "\n".join(page.extract_text() or "" for page in pdf.pages)
    except ImportError:
        pass
    return raw.decode("utf-8", errors="replace")


def _parse_pptx(raw: bytes) -> str:
    try:
        from pptx import Presentation
        from pptx.util import Inches, Pt
        prs = Presentation(BytesIO(raw))
        pages = []
        for slide_num, slide in enumerate(prs.slides, 1):
            slide_texts = [f"--- 幻灯片 {slide_num} ---"]
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
                        img_desc = _describe_image(img_bytes)
                        if img_desc:
                            slide_texts.append(f"[图片描述] {img_desc}")
                    except Exception:
                        pass
            if slide.has_notes_slide:
                notes_text = slide.notes_slide.notes_text_frame.text.strip()
                if notes_text:
                    slide_texts.append(f"[演讲者备注] {notes_text}")
            pages.append("\n".join(slide_texts))
        return "\n\n".join(pages)
    except ImportError:
        pass
    try:
        import zipfile
        import xml.etree.ElementTree as ET
        with zipfile.ZipFile(BytesIO(raw)) as z:
            texts = []
            for name in z.namelist():
                if name.startswith("ppt/slides/slide") and name.endswith(".xml"):
                    content = z.read(name)
                    root = ET.fromstring(content)
                    ns = {"a": "http://schemas.openxmlformats.org/drawingml/2006/main"}
                    slide_texts = []
                    for t in root.iter("{http://schemas.openxmlformats.org/drawingml/2006/main}t"):
                        if t.text:
                            slide_texts.append(t.text)
                    if slide_texts:
                        texts.append("--- 幻灯片 ---\n" + "\n".join(slide_texts))
            return "\n\n".join(texts) if texts else raw.decode("utf-8", errors="replace")
    except ImportError:
        pass
    return raw.decode("utf-8", errors="replace")


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


def _transcribe_video(raw: bytes, filename: str) -> str:
    temp_path = None
    try:
        import tempfile
        temp_dir = Path("data/uploads/temp_videos")
        temp_dir.mkdir(parents=True, exist_ok=True)
        temp_path = temp_dir / filename
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
                video.audio.write_audiofile(audio_path, logger=None)
            with open(audio_path, "rb") as af:
                audio_bytes = af.read()
            os.remove(audio_path)
            text = _speech_to_text(audio_bytes)
            duration = "(语音转文字完成)"
            return f"[视频 {filename}] {duration}\n{text}" if text else f"[视频 {filename}] 语音转文字未返回结果"
        except ImportError:
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


def _audio_transcription(audio_path: str) -> str:
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
    except ImportError:
        pass
    return tuple(slides)


def chunk_document(text: str, source: str, chunk_size: int = 520, overlap: int = 80) -> tuple[Evidence, ...]:
    normalized = re.sub(r"\s+", " ", text).strip()
    if not normalized:
        return ()
    chunks: list[Evidence] = []
    start = 0
    idx = 1
    while start < len(normalized):
        end = min(len(normalized), start + chunk_size)
        content = normalized[start:end].strip()
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
        if end == len(normalized):
            break
        start = end - overlap
        idx += 1
    return tuple(chunks)


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
