from __future__ import annotations

import hashlib
import re
import uuid
import time
from typing import Any
from urllib.parse import urlparse

import urllib.request
import urllib.parse
import urllib.error
import xml.etree.ElementTree as ET

from fastapi import APIRouter, Depends, HTTPException, Request

from app.database import DBWebSearchHistory, run_db_op
from document_parser import chunk_document
from rag_engine import hybrid_rag
from swarm_factory import build_swarm_from_headers
from models import Evidence, EvidenceModality

router = APIRouter(prefix="/api/web", tags=["web_search"])


async def _get_llm(request: Request):
    swarm = build_swarm_from_headers(request.headers)
    return swarm.llm


def _generate_id() -> str:
    return uuid.uuid4().hex[:16]


# 搜索缓存（内存）：相同关键词5分钟内复用结果
_search_cache: dict[str, tuple[float, list[dict[str, str]]]] = {}
_SEARCH_CACHE_TTL = 300  # 5分钟


@router.post("/search")
async def web_search(
    request: Request,
) -> dict[str, Any]:
    payload = await request.json()
    query = str(payload.get("query", "")).strip()
    student_id = str(payload.get("student_id", "default"))
    max_results = int(payload.get("max_results", 5))

    if not query:
        raise HTTPException(status_code=400, detail="搜索查询不能为空")

    # 检查缓存
    import time as _time
    cache_key = query.lower().strip()
    now = _time.time()
    if cache_key in _search_cache:
        ts, cached_results = _search_cache[cache_key]
        if now - ts < _SEARCH_CACHE_TTL:
            search_results = cached_results[:max_results]
        else:
            del _search_cache[cache_key]
            search_results = await _perform_web_search(query, max_results)
    else:
        search_results = await _perform_web_search(query, max_results)

    # 写缓存
    if search_results:
        _search_cache[cache_key] = (now, search_results)

    # Summarize search results with LLM
    llm = await _get_llm(request)
    system_prompt = (
        "你是一个知识整理助手。以下是从网络搜索到的信息，请提取与查询最相关的关键知识点。\n"
        "不要编造信息，只基于所给内容总结。以中文回复。"
    )
    user_prompt = f"用户查询：{query}\n\n搜索结果：\n" + "\n\n".join(
        f"[{i+1}] {r['title']}\n{r['snippet']}\n来源: {r['url']}"
        for i, r in enumerate(search_results)
    )

    summary = ""
    try:
        summary = await llm.generate(system_prompt, user_prompt, role="极客助教")
    except Exception:
        summary = f"已搜索到 {len(search_results)} 条关于 '{query}' 的结果"

    # Ingest search results into RAG
    combined_text = "\n\n".join(
        f"标题: {r['title']}\n内容: {r['snippet']}" for r in search_results
    )
    evidence_chunks = chunk_document(combined_text, source=f"web_search:{query}")
    if evidence_chunks:
        hybrid_rag.ingest_user_documents(evidence_chunks)

    search_id = _generate_id()
    db_record = DBWebSearchHistory(
        id=search_id,
        student_id=student_id,
        query=query,
        source_type="web_search",
        title=f"搜索: {query}",
        content_preview=combined_text[:500],
        chunk_count=len(evidence_chunks),
    )
    
    def save_record(session):
        session.add(db_record)
        session.commit()
        
    await run_db_op(save_record)

    return {
        "search_id": search_id,
        "query": query,
        "results": [
            {
                "title": r["title"],
                "url": r["url"],
                "snippet": r["snippet"],
            }
            for r in search_results
        ],
        "summary": summary,
        "chunks_ingested": len(evidence_chunks),
    }


async def _perform_web_search(query: str, max_results: int = 5) -> list[dict[str, str]]:
    results = []

    try:
        import httpx
        async with httpx.AsyncClient(timeout=15.0) as client:
            search_url = f"https://html.duckduckgo.com/html/?q={query}"
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            }
            resp = await client.get(search_url, headers=headers, follow_redirects=True)
            if resp.status_code == 200:
                results = _parse_duckduckgo_html(resp.text, max_results)
    except Exception:
        pass

    if not results:
        try:
            import httpx
            async with httpx.AsyncClient(timeout=15.0) as client:
                url = f"https://api.duckduckgo.com/?q={query}&format=json&no_html=1"
                resp = await client.get(url, headers={"User-Agent": "EduMatrix/1.0"})
                if resp.status_code == 200:
                    data = resp.json()
                    abstract = data.get("AbstractText", "")
                    if abstract:
                        results.append({
                            "title": data.get("Heading", query),
                            "url": data.get("AbstractURL", ""),
                            "snippet": abstract[:300],
                        })
        except Exception:
            pass

    if not results:
        results = [{
            "title": f"关于 '{query}' 的搜索结果",
            "url": "",
            "snippet": f"已收录关于 {query} 的知识，将在问答中直接应用。"
        }]

    return results[:max_results]


def _parse_duckduckgo_html(html: str, max_results: int) -> list[dict[str, str]]:
    results = []
    try:
        import html as html_lib
        result_blocks = re.findall(
            r'<a[^>]*class="result__a"[^>]*href="([^"]*)"[^>]*>(.*?)</a>',
            html,
            re.DOTALL,
        )
        snippet_blocks = re.findall(
            r'<a[^>]*class="result__snippet"[^>]*>(.*?)</a>',
            html,
            re.DOTALL,
        )
        for i, (url, title_html) in enumerate(result_blocks[:max_results]):
            title = re.sub(r"<[^>]+>", "", title_html).strip()
            snippet = ""
            if i < len(snippet_blocks):
                snippet = re.sub(r"<[^>]+>", "", snippet_blocks[i]).strip()
            title = html_lib.unescape(title)
            snippet = html_lib.unescape(snippet)
            clean_url = re.sub(r"^//", "https://", url.split("?uddg=")[-1] if "?uddg=" in url else url)
            results.append({
                "title": title or f"搜索结果 {i+1}",
                "url": clean_url,
                "snippet": snippet[:300],
            })
    except Exception:
        pass
    return results


@router.post("/load-url")
async def load_url(
    request: Request,
) -> dict[str, Any]:
    payload = await request.json()
    url = str(payload.get("url", "")).strip()
    student_id = str(payload.get("student_id", "default"))

    if not url:
        raise HTTPException(status_code=400, detail="URL不能为空")

    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        raise HTTPException(status_code=400, detail="仅支持 http/https URL")

    content = await _fetch_url_content(url)
    if not content:
        raise HTTPException(status_code=400, detail=f"无法加载URL内容: {url}")

    # Extract title
    title_match = re.search(r"<title[^>]*>(.*?)</title>", content, re.DOTALL | re.IGNORECASE)
    title = title_match.group(1).strip() if title_match else parsed.netloc

    # Clean HTML to text
    text_content = re.sub(r"<[^>]+>", " ", content)
    text_content = re.sub(r"\s+", " ", text_content).strip()
    text_content = text_content[:50000]

    # Chunk and ingest
    evidence_chunks = chunk_document(text_content, source=f"url:{url}")
    if evidence_chunks:
        hybrid_rag.ingest_user_documents(evidence_chunks)

    # Summarize with LLM
    summary = ""
    try:
        llm = await _get_llm(request)
        system_prompt = "你是一个知识提取助手。请从以下网页内容中提取关键知识要点。以中文回复，分点列出。"
        user_prompt = f"URL: {url}\n标题: {title}\n\n内容摘要:\n{text_content[:3000]}"
        summary = await llm.generate(system_prompt, user_prompt, role="极客助教")
    except Exception:
        summary = f"已从 {url} 加载内容并索引"

    doc_id = _generate_id()
    db_record = DBWebSearchHistory(
        id=doc_id,
        student_id=student_id,
        query=title,
        source_type="url_load",
        source_url=url,
        title=title,
        content_preview=text_content[:500],
        chunk_count=len(evidence_chunks),
    )
    
    def save_load_url_record(session):
        session.add(db_record)
        session.commit()
        
    await run_db_op(save_load_url_record)

    return {
        "doc_id": doc_id,
        "title": title,
        "url": url,
        "content_preview": text_content[:500],
        "summary": summary,
        "chunks_ingested": len(evidence_chunks),
    }


async def _fetch_url_content(url: str) -> str:
    try:
        import httpx
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            }
            resp = await client.get(url, headers=headers)
            if resp.status_code == 200:
                content_type = resp.headers.get("content-type", "")
                if "text/html" in content_type or "text/plain" in content_type:
                    return resp.text
                return resp.text
    except Exception:
        pass
    return ""


@router.get("/history/{student_id}")
async def get_search_history(
    student_id: str,
    limit: int = 20,
) -> list[dict[str, Any]]:
    def fetch_history(session):
        return (
            session.query(DBWebSearchHistory)
            .filter(DBWebSearchHistory.student_id == student_id)
            .order_by(DBWebSearchHistory.created_at.desc())
            .limit(limit)
            .all()
        )
        
    records = await run_db_op(fetch_history)
    return [
        {
            "id": r.id,
            "query": r.query,
            "source_type": r.source_type,
            "source_url": r.source_url,
            "title": r.title,
            "chunk_count": r.chunk_count,
            "created_at": r.created_at.isoformat() if r.created_at else "",
        }
        for r in records
    ]


def search_arxiv(query: str, max_results: int = 3) -> tuple[Evidence, ...]:
    """内部函数：并发调用的 arXiv 学术检索接口（带自动重试抗压机制）

    === 任务 2.4: 优先使用本地缓存 ===
    """
    from rag_engine import check_arxiv_cache, save_arxiv_cache

    # 先检查本地缓存
    cached = check_arxiv_cache(query)
    if cached:
        evidences = [
            Evidence(
                id=f"arxiv-cache-{uuid.uuid4().hex[:8]}",
                title=paper.get("title", "")[:200],
                content=f"摘要: {paper.get('abstract', '')[:500]}",
                modality=EvidenceModality.TEXT,
                source="arxiv_cache",
                tags=("arxiv", "academic"),
                score=0.85,
            )
            for paper in cached
        ]
        return tuple(evidences[:max_results])

    safe_query = urllib.parse.quote(query)
    url = f"http://export.arxiv.org/api/query?search_query=all:{safe_query}&max_results={max_results}"
    
    xml_data = None
    max_retries = 3  # 最多重试 3 次
    
    # 带有指数退避的重试循环
    for attempt in range(max_retries):
        try:
            # 超时放宽到 10 秒，给 arXiv 喘息的时间
            with urllib.request.urlopen(url, timeout=10.0) as response:
                xml_data = response.read()
            break  # 成功拿到数据，跳出循环
            
        except urllib.error.HTTPError as e:
            if e.code == 429:
                sleep_time = 2 ** attempt  # 指数退避：1秒 -> 2秒 -> 4秒
                print(f"  [arXiv] 触发官方限流(429)，等待 {sleep_time} 秒后进行第 {attempt+1} 次重试...")
                time.sleep(sleep_time)
            else:
                print(f"  [arXiv] HTTP 错误: {e}")
                break
        except Exception as e:
            print(f"  [arXiv] 网络超时或错误 ({e})，正在进行第 {attempt+1} 次重试...")
            time.sleep(1.5)  # 普通超时等 1.5 秒重试
            
    # 如果重试 3 次还是失败，优雅降级，返回空结果
    if not xml_data:
        print("  [arXiv] 多次尝试失败，放弃本次学术检索，继续主线任务。")
        return tuple()

    results = []
    try:
        root = ET.fromstring(xml_data)
        namespace = {'atom': 'http://www.w3.org/2005/Atom'}
        
        for entry in root.findall('atom:entry', namespace):
            title_elem = entry.find('atom:title', namespace)
            summary_elem = entry.find('atom:summary', namespace)
            if title_elem is None or summary_elem is None:
                continue
                
            title = title_elem.text.replace('\n', ' ').strip()
            summary = summary_elem.text.replace('\n', ' ').strip()
            link = entry.find("atom:link[@type='text/html']", namespace)
            pdf_url = link.attrib['href'] if link is not None else ""
            
            authors = [
                author.find('atom:name', namespace).text 
                for author in entry.findall('atom:author', namespace) 
                if author.find('atom:name', namespace) is not None
            ]
            
            evidence = Evidence(
                id=f"ARXIV_{pdf_url.split('/')[-1]}",
                title=f"[学术文献] {title}",
                content=summary,
                modality=EvidenceModality.TEXT,
                source="arXiv.org",
                tags=("学术论文", "arXiv"),
                anchors=tuple(authors[:2]),
                score=0.65,
                metadata={
                    "is_academic": True,
                    "url": pdf_url,
                    "authors": authors
                }
            )
            results.append(evidence)
    except Exception as e:
        print(f"  [arXiv] XML 数据解析失败: {e}")

    # === 任务 2.4: 缓存检索结果到本地 ===
    if results:
        try:
            root = ET.fromstring(xml_data)
            namespace = {'atom': 'http://www.w3.org/2005/Atom'}
            cached_papers = []
            for entry in root.findall('atom:entry', namespace):
                title_elem = entry.find('atom:title', namespace)
                summary_elem = entry.find('atom:summary', namespace)
                if title_elem is None:
                    continue
                title = title_elem.text.replace('\n', ' ').strip() if title_elem.text else ""
                summary = summary_elem.text.replace('\n', ' ').strip() if summary_elem is not None and summary_elem.text else ""
                link = entry.find("atom:link[@type='text/html']", namespace)
                pdf_url = link.attrib['href'] if link is not None else ""
                id_elem = entry.find('atom:id', namespace)
                arxiv_id = id_elem.text.strip() if id_elem is not None else ""
                authors = [
                    author.find('atom:name', namespace).text
                    for author in entry.findall('atom:author', namespace)
                    if author.find('atom:name', namespace) is not None
                ]
                published_elem = entry.find('atom:published', namespace)
                published = published_elem.text.strip() if published_elem is not None else ""
                cached_papers.append({
                    "arxiv_id": arxiv_id,
                    "title": title[:500],
                    "authors": ", ".join(authors)[:1000],
                    "abstract": summary[:2000],
                    "pdf_url": pdf_url[:500],
                    "published": published,
                })
            save_arxiv_cache(query, cached_papers)
        except Exception as ce:
            print(f"  [arXiv] 缓存写入失败: {ce}")

    return tuple(results)


@router.get("/arxiv-search")
async def explicit_arxiv_search(query: str, max_results: int = 5) -> dict[str, Any]:
    """
    供前端学术探索专区直接调用的显式搜索接口。
    不会将结果喂给大模型，而是直接返回结构化的论文列表供用户自行阅读。
    """
    if not query:
        raise HTTPException(status_code=400, detail="搜索查询不能为空")
        
    # 直接调用上面的内部并发函数
    results = search_arxiv(query, max_results)
    
    # 将后端的 Evidence 对象转换为前端友好的 JSON 格式
    formatted_papers = []
    for r in results:
        # 清洗掉我们在后端为了 RAG 区分加的 "[学术文献] " 前缀
        clean_title = r.title.replace("[学术文献] ", "")
        
        formatted_papers.append({
            "id": r.id,
            "title": clean_title,
            "abstract": r.content,
            "authors": r.metadata.get("authors", []),
            "pdf_url": r.metadata.get("url", ""),
            "score": r.score
        })
        
    return {
        "status": "success",
        "query": query,
        "total_returned": len(formatted_papers),
        "papers": formatted_papers
    }