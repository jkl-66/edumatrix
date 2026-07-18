from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Any
import re

from fastapi import APIRouter, File, HTTPException, UploadFile, Request, BackgroundTasks

from app.database import DBKnowledgeDocument, run_db_op
from document_parser import chunk_document, parse_uploaded_file, parse_pptx_slides, parse_pdf_visually
from rag_engine import hybrid_rag
from ingestion import build_graph_after_upload, _get_graph_builder

router = APIRouter(prefix="/api/knowledge", tags=["knowledge"])

UPLOAD_DIR = Path("data/uploads")
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

SUPPORTED_EXTENSIONS = {
    ".md": "markdown",
    ".txt": "text",
    ".pdf": "pdf",
    ".docx": "word",
    ".json": "json",
    ".py": "python_code",
    ".pptx": "presentation",
    ".mp4": "video",
    ".avi": "video",
    ".mov": "video",
    ".mkv": "video",
    ".webm": "video",
    ".flv": "video",
}


@router.post("/upload")
async def upload_document(
    request: Request,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    student_id: str = "default",
) -> dict[str, Any]:
    # 安全: 无条件 sanitize student_id
    student_id = re.sub(r"[^a-zA-Z0-9_-]", "", str(student_id))[:64]
    if student_id == "default":
        try:
            form = await request.form()
            form_student_id = form.get("student_id")
            if form_student_id:
                student_id = re.sub(r"[^a-zA-Z0-9_-]", "", str(form_student_id))[:64]
        except Exception:
            pass
    if not student_id:
        student_id = "default"

    filename = file.filename or "unnamed"
    ext = os.path.splitext(filename)[1].lower()

    if ext not in SUPPORTED_EXTENSIONS:
        if ext == ".ppt":
            raise HTTPException(status_code=400, detail="不支持旧版 PPT 二进制格式，请在 PowerPoint 中另存为 .pptx 格式后再上传。")
        allowed = ", ".join(SUPPORTED_EXTENSIONS.keys())
        raise HTTPException(status_code=400, detail=f"不支持的文件类型: {ext}，支持 {allowed}")

    raw = await file.read()
    file_size = len(raw)

    doc_id = hashlib.sha256(f"{student_id}:{filename}:{os.urandom(4).hex()}".encode()).hexdigest()[:16]

    file_category = SUPPORTED_EXTENSIONS[ext]
    is_multimodal = file_category in ("video", "presentation")

    text_content = parse_uploaded_file(type("buf", (), {"read": lambda s: raw})(), filename)
    evidence_chunks = chunk_document(text_content, source=filename)

    # ── 成员 3 任务 1: PDF 多模态视觉解析 ──
    visual_evidence: list = []
    if ext == ".pdf":
        try:
            visual_evidence = parse_pdf_visually(raw, filename)
            if visual_evidence:
                # 注册视觉证据到 VisRAG 索引
                hybrid_rag.visual_index.index.upsert(tuple(visual_evidence))
        except Exception as e:
            print(f"  [knowledge_api] PDF 视觉解析失败（非致命）: {e}")

    # ── 成员 3 任务 2: 增量图谱自生长（句级别 diff + 三元组提取）──
    graph_report = build_graph_after_upload(evidence_chunks, source=filename, previous_text="")

    extra_metadata = {}
    if ext in (".pptx", ".ppt"):
        try:
            slides = parse_pptx_slides(raw)
            extra_metadata["slide_count"] = len(slides)
            extra_metadata["has_images"] = any(s["images"] for s in slides)
        except Exception:
            pass
    elif file_category == "video":
        extra_metadata["video_duration"] = _estimate_video_duration(raw)

    db_doc = DBKnowledgeDocument(
        id=doc_id,
        student_id=student_id,
        filename=filename,
        file_type=ext.lstrip("."),
        file_size=file_size,
        title=os.path.splitext(filename)[0],
        content=text_content,
        tags=list({tag for chunk in evidence_chunks for tag in chunk.tags}),
        chunk_count=len(evidence_chunks),
        is_multimodal=is_multimodal,
        multimodal_metadata=extra_metadata,
    )
    
    def save_doc(session):
        session.add(db_doc)
        session.commit()
        
    await run_db_op(save_doc)

    doc_dir = UPLOAD_DIR / student_id
    doc_dir.mkdir(parents=True, exist_ok=True)
    doc_file_path = doc_dir / f"{doc_id}{ext}"
    with open(doc_file_path, "wb") as f:
        f.write(raw)

    hybrid_rag.ingest_user_documents(evidence_chunks)

    try:
        from learning_strategy import invalidate_graph_cache
        invalidate_graph_cache()
    except Exception:
        pass

    # 调度异步文档导读生成（NotebookLM 风格）
    if text_content.strip():
        background_tasks.add_task(
            _generate_doc_guide_for_document,
            doc_id=doc_id,
            student_id=student_id,
            text_content=text_content[:12000],
        )

    return {
        "id": doc_id,
        "filename": filename,
        "file_type": ext.lstrip("."),
        "file_category": file_category,
        "file_size": file_size,
        "chunk_count": len(evidence_chunks),
        "tags": list({tag for chunk in evidence_chunks for tag in chunk.tags}),
        "is_multimodal": is_multimodal,
        "multimodal_metadata": extra_metadata,
        "doc_guide_status": "pending",
        "content_preview": text_content[:300],
        # 成员 3: 视觉解析 & 图谱自生长
        "visual_pages_parsed": len(visual_evidence),
        "graph_triplets_extracted": graph_report.raw_triplets if graph_report else 0,
        "graph_edges_written": graph_report.written_edges if graph_report else 0,
        "graph_backend": graph_report.backend if graph_report else "",
    }


def _estimate_video_duration(raw: bytes) -> float:
    try:
        import io
        from moviepy import VideoFileClip
        import tempfile
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
            f.write(raw)
            tmp = f.name
        try:
            with VideoFileClip(tmp) as clip:
                return clip.duration
        finally:
            os.unlink(tmp)
    except Exception:
        pass
    return 0.0


@router.get("/list")
async def list_documents(
    student_id: str = "default",
) -> list[dict[str, Any]]:
    def fetch_docs(session):
        return (
            session.query(DBKnowledgeDocument)
            .filter(DBKnowledgeDocument.student_id == student_id)
            .order_by(DBKnowledgeDocument.created_at.desc())
            .all()
        )
        
    docs = await run_db_op(fetch_docs)
    return [
        {
            "id": doc.id,
            "filename": doc.filename,
            "file_type": doc.file_type,
            "file_size": doc.file_size,
            "title": doc.title,
            "content_preview": (doc.content or "")[:200],
            "tags": doc.tags or [],
            "chunk_count": doc.chunk_count,
            "is_multimodal": doc.is_multimodal,
            "multimodal_metadata": doc.multimodal_metadata or {},
            "created_at": doc.created_at.isoformat() if doc.created_at else "",
        }
        for doc in docs
    ]



# ── 成员 3 任务 2: 图谱统计端点 ──
@router.get("/graph/stats")
async def graph_stats() -> dict[str, Any]:
    """返回当前知识图谱的统计信息（节点数、边数、后端类型）。"""
    try:
        builder = _get_graph_builder()
        if builder is None:
            return {"status": "unavailable", "nodes": 0, "edges": 0, "backend": "none"}
        repo = builder.repository
        backend = "neo4j" if hasattr(repo, "_driver") and repo._driver else "memory"
        return {
            "status": "ok",
            "nodes": repo.count_nodes(),
            "edges": repo.count_edges(),
            "backend": backend,
        }
    except Exception as e:
        return {"status": "error", "detail": str(e), "nodes": 0, "edges": 0, "backend": "error"}


# ── 成员 3 任务 3: 跨模态特征对齐搜索端点 ──
@router.get("/cross-search")
async def cross_modal_search(
    query: str = "",
    mode: str = "text",
    top_k: int = 5,
) -> dict[str, Any]:
    """跨模态搜索：用文字搜图片/公式，或用公式搜文字/图片。

    Args:
        query: 搜索词（文字描述或 LaTeX 公式）
        mode: 搜索模式 — "text" 用文字搜图片， "formula" 用公式搜文字
        top_k: 返回结果数量
    """
    if not query.strip():
        return {"status": "error", "detail": "查询不能为空", "results": []}

    try:
        from multimodal_alignment import get_cross_modal_aligner
        aligner = get_cross_modal_aligner()
        results = aligner.search(query, mode=mode, top_k=top_k)
        return {
            "status": "ok",
            "query": query,
            "mode": mode,
            "total": len(results),
            "results": results,
        }
    except ImportError:
        return {
            "status": "not_initialized",
            "detail": "跨模态对齐数据尚未构建。请先上传包含公式的教材文档以构建对齐索引。",
            "results": [],
        }
    except Exception as e:
        return {"status": "error", "detail": str(e), "results": []}


# === 异步文档导读生成（NotebookLM 风格）===

_DOC_GUIDE_PROMPT = """\
请仔细阅读以下文档内容，并生成一个 JSON 字典（不要包含任何额外字符或代码块标记）：

{
  "brief_summary": "一句话核心梗概",
  "highlights": ["核心看点1", "核心看点2", "核心看点3", "核心看点4", "核心看点5"],
  "faqs": [
    {"q": "常见问题1", "a": "答案1"},
    {"q": "常见问题2", "a": "答案2"},
    {"q": "常见问题3", "a": "答案3"}
  ]
}"""


async def _generate_doc_guide_for_document(doc_id: str, student_id: str, text_content: str) -> None:
    """后台任务：调用 LLM 生成文档导读指南并写入 DB。"""
    import json
    import re as _re

    try:
        from llm_client import DEFAULT_ASYNC_LLM

        result = await DEFAULT_ASYNC_LLM.generate(
            system_prompt=_DOC_GUIDE_PROMPT,
            user_prompt=f"文档内容：\n\n{text_content[:12000]}",
            role="文档导读分析师",
        )

        # 鲁棒解析：移除可能的 ```json 围栏
        cleaned = result.strip()
        cleaned = _re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = _re.sub(r"\s*```$", "", cleaned)
        
        guide_data = json.loads(cleaned)
        
        if not isinstance(guide_data, dict):
            raise ValueError("LLM 返回不是 JSON 对象")
        if "brief_summary" not in guide_data:
            guide_data["brief_summary"] = "（无摘要）"
        if "highlights" not in guide_data or not isinstance(guide_data["highlights"], list):
            guide_data["highlights"] = ["（无看点）"]
        if "faqs" not in guide_data or not isinstance(guide_data["faqs"], list):
            guide_data["faqs"] = []
        
        def update_doc_guide(session):
            doc = session.query(DBKnowledgeDocument).filter(
                DBKnowledgeDocument.id == doc_id,
                DBKnowledgeDocument.student_id == student_id,
            ).first()
            if doc is None:
                print(f"  [DocGuide] 文档 {doc_id} 不存在，跳过")
                return
            meta = dict(doc.multimodal_metadata or {}) if doc.multimodal_metadata else {}
            meta["doc_guide"] = guide_data
            doc.multimodal_metadata = meta
            session.commit()
            print(f"  [DocGuide] 文档 {doc_id} 导读已生成: {guide_data['brief_summary'][:50]}...")

        await run_db_op(update_doc_guide)
        
    except json.JSONDecodeError as e:
        print(f"  [DocGuide] 文档 {doc_id} 导读 JSON 解析失败: {e}")
    except Exception as e:
        print(f"  [DocGuide] 文档 {doc_id} 导读生成失败: {e}")


@router.post("/add-web-source")
async def add_web_source(
    request: Request,
) -> dict[str, Any]:
    """将网页搜索结果显式拉取加入知识库，利用 LLM 智能脱水总结为 Markdown。"""
    import re
    from swarm_factory import build_swarm_from_headers
    payload = await request.json()
    query = str(payload.get("query", "")).strip()
    title = str(payload.get("title", "")).strip()
    url = str(payload.get("url", "")).strip()
    snippet = str(payload.get("snippet", "")).strip()
    student_id = str(payload.get("student_id", "default")).strip()

    if not title or not snippet:
        raise HTTPException(status_code=400, detail="标题和摘要内容不能为空")

    # 1. 采用 LLM 智能总结脱水
    try:
        swarm = build_swarm_from_headers(request.headers)
        llm = swarm.llm
        system_prompt = (
            "你是一个顶级的学术与教育内容整理专家。你的任务是将给定的网页搜索标题 and 摘要片段进行“脱水总结”，"
            "提炼整理成一篇逻辑严密、排版美观的结构化 Markdown 读书要点笔记。\n"
            "要求：\n"
            "1. 概括该网页所涉知识的核心定义与原理，剔除广告、杂音等不相干文本。\n"
            "2. 以 Markdown 格式排版，必须包含 # 标题、## 核心概念定义、## 核心推导/要点概括、## 拓展/知识拓扑。\n"
            "3. 保持中立学术风格，全中文回复。"
        )
        user_prompt = (
            f"网页标题: {title}\n"
            f"网页来源URL: {url}\n"
            f"关联搜索词: {query}\n\n"
            f"网页内容摘要:\n{snippet}\n\n"
            "请开始生成脱水 Markdown 笔记："
        )
        text_content = await llm.generate(system_prompt, user_prompt, role="极客助教")
    except Exception as e:
        print(f"  [AddWebSource] LLM Dehydration failed, falling back: {e}")
        text_content = (
            f"# {title}\n\n"
            f"**来源URL**: {url}\n"
            f"**关联搜索词**: {query}\n\n"
            f"## 网页摘要\n{snippet}"
        )

    # 2. 生成友情文件名并过滤非法字符
    safe_title = re.sub(r'[\\/*?:\"<>|]', "", title)[:40]
    filename = f"[网页] {safe_title}.txt"
    doc_id = hashlib.sha256(f"{student_id}:{filename}:{os.urandom(4).hex()}".encode()).hexdigest()[:16]

    file_size = len(text_content.encode("utf-8"))

    # 3. 对内容进行分块并向量化 RAG 入库
    evidence_chunks = chunk_document(text_content, source=filename)
    
    # 4. 创建并写入数据库记录
    db_doc = DBKnowledgeDocument(
        id=doc_id,
        student_id=student_id,
        filename=filename,
        file_type="txt",
        file_size=file_size,
        title=title,
        content=text_content,
        tags=["网页检索", query],
        chunk_count=len(evidence_chunks),
        is_multimodal=False,
        multimodal_metadata={"url": url, "query": query},
    )

    def save_doc(session):
        session.add(db_doc)
        session.commit()

    await run_db_op(save_doc)

    # 5. 写入物理上传目录备份，确保重启后课件仍然持久
    doc_dir = UPLOAD_DIR / student_id
    doc_dir.mkdir(parents=True, exist_ok=True)
    doc_file_path = doc_dir / f"{doc_id}.txt"
    with open(doc_file_path, "wb") as f:
        f.write(text_content.encode("utf-8"))

    # 6. 加载进 RAG
    hybrid_rag.ingest_user_documents(evidence_chunks)

    try:
        from learning_strategy import invalidate_graph_cache
        invalidate_graph_cache()
    except Exception:
        pass

    return {
        "status": "success",
        "id": doc_id,
        "filename": filename,
        "chunk_count": len(evidence_chunks),
        "content_preview": text_content[:300]
    }


@router.post("/download-web-file")
async def download_web_file(
    request: Request,
) -> dict[str, Any]:
    """通过 URL 直链流式下载网页文档，并调用本地解析器进行深度导入。"""
    import re
    import httpx
    payload = await request.json()
    url = str(payload.get("url", "")).strip()
    file_type = str(payload.get("file_type", "")).strip().lower()
    title = str(payload.get("title", "")).strip()
    student_id = str(payload.get("student_id", "default")).strip()

    if not url:
        raise HTTPException(status_code=400, detail="直链 URL 不能为空")
    if not file_type:
        raise HTTPException(status_code=400, detail="文件类型 (file_type) 不能为空")
    if not title:
        raise HTTPException(status_code=400, detail="标题不能为空")

    # 1. 过滤文件名
    safe_title = re.sub(r'[\\/*?:\"<>|]', "", title)[:40]
    ext = f".{file_type}"
    filename = f"[下载] {safe_title}{ext}"

    if ext not in SUPPORTED_EXTENSIONS:
        if ext == ".ppt":
            raise HTTPException(status_code=400, detail="不支持旧版 PPT 格式，仅支持 .pptx、.pdf 等现代格式。")
        allowed = ", ".join(SUPPORTED_EXTENSIONS.keys())
        raise HTTPException(status_code=400, detail=f"不支持的文件类型: {ext}，支持 {allowed}")

    # 2. 流式下载网页文档
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            }
            resp = await client.get(url, headers=headers, follow_redirects=True)
            if resp.status_code != 200:
                raise HTTPException(
                    status_code=400, 
                    detail=f"文件下载失败，HTTP 状态码: {resp.status_code}"
                )
            raw = resp.content
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"无法从直链下载文件: {e}")

    file_size = len(raw)
    if file_size == 0:
        raise HTTPException(status_code=400, detail="下载的文件大小为 0 字节。")

    doc_id = hashlib.sha256(f"{student_id}:{filename}:{os.urandom(4).hex()}".encode()).hexdigest()[:16]

    file_category = SUPPORTED_EXTENSIONS[ext]
    is_multimodal = file_category in ("video", "presentation")

    # 3. 提取文本内容并分块
    text_content = parse_uploaded_file(type("buf", (), {"read": lambda s: raw})(), filename)
    evidence_chunks = chunk_document(text_content, source=filename)

    # 4. PDF 视觉解析
    visual_evidence: list = []
    if ext == ".pdf":
        try:
            visual_evidence = parse_pdf_visually(raw, filename)
            if visual_evidence:
                hybrid_rag.visual_index.index.upsert(tuple(visual_evidence))
        except Exception as e:
            print(f"  [download_web_file] PDF 视觉解析失败（非致命）: {e}")

    # 5. 增量图谱自生长
    graph_report = build_graph_after_upload(evidence_chunks, source=filename, previous_text="")

    extra_metadata = {"url": url}
    if ext in (".pptx", ".ppt"):
        try:
            from document_parser import parse_pptx_slides
            slides = parse_pptx_slides(raw)
            extra_metadata["slide_count"] = len(slides)
            extra_metadata["has_images"] = any(s["images"] for s in slides)
        except Exception:
            pass

    # 6. 保存至数据库记录
    db_doc = DBKnowledgeDocument(
        id=doc_id,
        student_id=student_id,
        filename=filename,
        file_type=ext.lstrip("."),
        file_size=file_size,
        title=safe_title,
        content=text_content,
        tags=list({tag for chunk in evidence_chunks for tag in chunk.tags}),
        chunk_count=len(evidence_chunks),
        is_multimodal=is_multimodal,
        multimodal_metadata=extra_metadata,
    )
    
    def save_doc(session):
        session.add(db_doc)
        session.commit()
        
    await run_db_op(save_doc)

    # 7. 写入物理上传目录备份，确保重启后课件仍然持久
    doc_dir = UPLOAD_DIR / student_id
    doc_dir.mkdir(parents=True, exist_ok=True)
    doc_file_path = doc_dir / f"{doc_id}{ext}"
    with open(doc_file_path, "wb") as f:
        f.write(raw)

    # 8. 加载并灌入 RAG 索引
    hybrid_rag.ingest_user_documents(evidence_chunks)

    try:
        from learning_strategy import invalidate_graph_cache
        invalidate_graph_cache()
    except Exception:
        pass

    return {
        "status": "success",
        "id": doc_id,
        "filename": filename,
        "file_type": ext.lstrip("."),
        "file_category": file_category,
        "file_size": file_size,
        "chunk_count": len(evidence_chunks),
        "tags": list({tag for chunk in evidence_chunks for tag in chunk.tags}),
        "is_multimodal": is_multimodal,
        "multimodal_metadata": extra_metadata,
        "content_preview": text_content[:300],
        "visual_pages_parsed": len(visual_evidence),
        "graph_triplets_extracted": graph_report.raw_triplets if graph_report else 0,
        "graph_edges_written": graph_report.written_edges if graph_report else 0,
    }


@router.get("/{doc_id}")
async def get_document(
    doc_id: str,
    student_id: str = "default",
) -> dict[str, Any]:
    """获取单个知识库文档的完整详情（含完整文本内容）。"""
    def fetch_doc(session):
        return (
            session.query(DBKnowledgeDocument)
            .filter(DBKnowledgeDocument.id == doc_id, DBKnowledgeDocument.student_id == student_id)
            .first()
        )
        
    doc = await run_db_op(fetch_doc)
    if not doc:
        raise HTTPException(status_code=404, detail="文档未找到")
        
    return {
        "id": doc.id,
        "filename": doc.filename,
        "file_type": doc.file_type,
        "file_size": doc.file_size,
        "title": doc.title,
        "content": doc.content or "无文本内容",
        "tags": doc.tags or [],
        "chunk_count": doc.chunk_count,
        "is_multimodal": doc.is_multimodal,
        "multimodal_metadata": doc.multimodal_metadata or {},
        "created_at": doc.created_at.isoformat() if doc.created_at else "",
    }


@router.delete("/{doc_id}")
async def delete_document(
    doc_id: str,
    student_id: str = "default",
) -> dict[str, str]:
    def do_delete(session):
        doc = (
            session.query(DBKnowledgeDocument)
            .filter(DBKnowledgeDocument.id == doc_id, DBKnowledgeDocument.student_id == student_id)
            .first()
        )
        if not doc:
            return None
            
        filename = doc.filename
        file_type = doc.file_type or "txt"
        session.delete(doc)
        session.commit()
        return filename, file_type

    res = await run_db_op(do_delete)
    if not res:
        raise HTTPException(status_code=404, detail="文档未找到")

    filename, file_type = res
    ext = "." + file_type
    doc_file = UPLOAD_DIR / student_id / f"{doc_id}{ext}"
    if doc_file.exists():
        doc_file.unlink()

    hybrid_rag.remove_user_documents(filename)

    try:
        from learning_strategy import invalidate_graph_cache
        invalidate_graph_cache()
    except Exception:
        pass

    return {"status": "deleted", "id": doc_id}
