from __future__ import annotations

import argparse
import csv
import json
import os
import re
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen, urlretrieve

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
ANIMATIONS = DATA / "animations"
ANIMATIONS.mkdir(parents=True, exist_ok=True)

# ── 知识点定义（与 LearningPathGraph.vue / rag_engine.py 同步） ──
@dataclass(frozen=True)
class KnowledgePoint:
    name: str
    en_name: str
    category: str
    search_queries: tuple[str, ...]


KNOWLEDGE_POINTS: tuple[KnowledgePoint, ...] = (
    KnowledgePoint("池化层", "Pooling Layer", "神经网络",
        ("池化层 动画", "pooling layer animation", "max pooling visualization")),
    KnowledgePoint("最大池化", "Max Pooling", "神经网络",
        ("最大池化 动画", "max pooling animation", "2x2 max pooling demo")),
    KnowledgePoint("平均池化", "Average Pooling", "神经网络",
        ("平均池化 动画", "average pooling animation", "avg pooling visualization")),
    KnowledgePoint("卷积核", "Convolution Kernel", "神经网络",
        ("卷积核 滑动 动画", "convolution kernel animation", "卷积核 可视化")),
    KnowledgePoint("特征图", "Feature Map", "神经网络",
        ("特征图 可视化", "feature map animation", "CNN 特征图 动画")),
    KnowledgePoint("反向传播", "Backpropagation", "优化",
        ("反向传播 动画", "backpropagation animation", "反向传播 可视化")),
    KnowledgePoint("链式法则", "Chain Rule", "优化",
        ("链式法则 动画", "chain rule animation", "链式法则 求导 可视化")),
    KnowledgePoint("梯度下降", "Gradient Descent", "优化",
        ("梯度下降 动画", "gradient descent animation", "梯度下降 3D 可视化")),
    KnowledgePoint("逻辑回归", "Logistic Regression", "监督学习",
        ("逻辑回归 动画", "sigmoid 动画", "logistic regression animation")),
    KnowledgePoint("线性回归", "Linear Regression", "监督学习",
        ("线性回归 动画", "linear regression animation", "线性拟合 动画")),
    KnowledgePoint("决策树", "Decision Tree", "监督学习",
        ("决策树 动画", "decision tree animation", "决策树 可视化 分裂")),
    KnowledgePoint("支持向量机", "SVM", "监督学习",
        ("支持向量机 动画", "SVM animation", "间隔最大化 可视化")),
    KnowledgePoint("过拟合", "Overfitting", "模型评估",
        ("过拟合 动画", "overfitting animation", "过拟合 欠拟合 对比")),
    KnowledgePoint("正则化", "Regularization", "模型评估",
        ("正则化 动画", "L1 L2 regularization animation", "正则化 可视化")),
    KnowledgePoint("交叉验证", "Cross Validation", "模型评估",
        ("交叉验证 动画", "cross validation animation", "k-fold 动画")),
    KnowledgePoint("神经网络", "Neural Network", "神经网络",
        ("神经网络 动画", "neural network animation", "神经网络 前向传播 动画")),
    KnowledgePoint("卷积神经网络", "CNN", "神经网络",
        ("卷积神经网络 动画", "CNN animation", "CNN 卷积 池化 全连接 动画")),
    KnowledgePoint("Transformer", "Transformer", "前沿",
        ("Transformer 动画", "Transformer attention animation", "自注意力 动画")),
    KnowledgePoint("注意力机制", "Attention Mechanism", "前沿",
        ("注意力机制 动画", "attention mechanism animation", "self-attention visualization")),
    KnowledgePoint("机器学习", "Machine Learning", "基础",
        ("机器学习 动画 入门", "machine learning animation", "机器学习 可视化")),
    KnowledgePoint("监督学习", "Supervised Learning", "基础",
        ("监督学习 动画", "supervised learning animation", "监督学习 分类 回归 动画")),
    KnowledgePoint("模型评估", "Model Evaluation", "基础",
        ("混淆矩阵 动画", "ROC AUC 动画", "precision recall animation", "模型评估 可视化")),
)


# ── 数据模型 ──
@dataclass(frozen=True)
class AnimationResult:
    knowledge_point: str
    category: str
    title: str
    url: str
    platform: str
    media_type: str
    duration: str
    description: str
    thumbnail: str
    source_query: str
    local_path: str = ""
    file_size: int = 0
    downloaded: bool = False
    crawled_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


# ── 网络请求 ──
def _safe_request(url: str, headers: dict | None = None, timeout: int = 20) -> bytes | None:
    default_headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
        "Accept": "application/json, text/html, */*",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    }
    if headers:
        default_headers.update(headers)
    try:
        req = Request(url, headers=default_headers)
        with urlopen(req, timeout=timeout) as resp:
            return resp.read()
    except Exception as e:
        print(f"  [request] {url[:80]}... → {e}", file=sys.stderr)
        return None


def _parse_json(data: bytes | None) -> dict | list | None:
    if data is None:
        return None
    try:
        return json.loads(data)
    except json.JSONDecodeError:
        return None


# ── 下载到本地 ──
def _sanitize_filename(name: str, max_len: int = 80) -> str:
    safe = re.sub(r'[\\/*?:"<>|]', "_", name)
    return safe.strip()[:max_len]


def _guess_ext(url: str, content_type: str = "") -> str:
    parsed = urlparse(url.split("?")[0])
    ext = os.path.splitext(parsed.path)[1].lower()
    if ext in (".gif", ".png", ".jpg", ".jpeg", ".webp", ".mp4", ".webm", ".svg"):
        return ext
    if "gif" in content_type:
        return ".gif"
    if "png" in content_type:
        return ".png"
    if "jpeg" in content_type or "jpg" in content_type:
        return ".jpg"
    if "webp" in content_type:
        return ".webp"
    if "svg" in content_type:
        return ".svg"
    return ".gif"


def download_file(url: str, save_dir: Path, base_name: str) -> tuple[str, int]:
    """下载文件到本地，兼容B站CDN（需Referer头）"""
    save_dir.mkdir(parents=True, exist_ok=True)
    try:
        # B站CDN需要Referer头，否则返回403
        referer = "https://www.bilibili.com/" if "hdslb.com" in url else "https://image.baidu.com/"
        req = Request(url, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/125.0.0.0 Safari/537.36",
            "Accept": "image/webp,image/apng,image/*,*/*;q=0.8",
            "Referer": referer,
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        })
        with urlopen(req, timeout=30) as resp:
            data = resp.read()
            if len(data) < 100:
                print(f"    [skip] {url[:60]}... 太小({len(data)}B)", file=sys.stderr)
                return "", 0
            content_type = resp.headers.get("Content-Type", "")
            ext = _guess_ext(url, content_type)
            safe_name = _sanitize_filename(base_name)
            local_path = save_dir / f"{safe_name}{ext}"
            counter = 1
            while local_path.exists():
                local_path = save_dir / f"{safe_name}_{counter}{ext}"
                counter += 1
            local_path.write_bytes(data)
            print(f"    [OK] {local_path.name} ({len(data)/1024:.0f}KB)")
            return str(local_path.relative_to(ROOT)), len(data)
    except Exception as e:
        print(f"    [download] {url[:60]}... -> {e}", file=sys.stderr)
        return "", 0


# ── yt-dlp 通用视频下载（支持 YouTube / B站 / Vimeo 等）──
def _find_ytdlp() -> str | None:
    for cmd in ("yt-dlp", "yt-dlp.exe"):
        try:
            subprocess.run([cmd, "--version"], capture_output=True, timeout=5)
            return cmd
        except Exception:
            pass
    return None


def download_video_ytdlp(url: str, save_dir: Path, title: str) -> tuple[str, int]:
    """用 yt-dlp 下载任意平台视频"""
    ytdlp = _find_ytdlp()
    if not ytdlp:
        return "", 0
    save_dir.mkdir(parents=True, exist_ok=True)
    safe_title = _sanitize_filename(title, 50)
    out_tmpl = str(save_dir / f"{safe_title}_%(id)s.%(ext)s")
    try:
        result = subprocess.run([
            ytdlp, url,
            "-f", "best[height<=720]",
            "-o", out_tmpl,
            "--no-playlist",
            "--socket-timeout", "30",
            "--retries", "3",
            "--no-warnings",
            "--progress",
        ], capture_output=True, text=True, timeout=300, cwd=str(ROOT))
        combined = (result.stdout + "\n" + result.stderr)
        for line in combined.splitlines():
            if "Destination:" in line:
                dest = line.split("Destination:")[-1].strip()
                path = Path(dest)
                if path.exists():
                    print(f"    [video-OK] {path.name}")
                    return str(path.relative_to(ROOT)), path.stat().st_size
            if "Merging formats" in line:
                merged = line.split('"')[1] if '"' in line else ""
                if merged:
                    path = Path(merged)
                    if path.exists():
                        print(f"    [video-OK] {path.name}")
                        return str(path.relative_to(ROOT)), path.stat().st_size
        existing = sorted(save_dir.glob(f"{safe_title}*.mp4")) + sorted(save_dir.glob(f"{safe_title}*.mkv"))
        if existing:
            p = existing[0]
            print(f"    [video-OK] {p.name} (已存在)")
            return str(p.relative_to(ROOT)), p.stat().st_size
        last_lines = [l for l in result.stderr.splitlines() if l.strip()][-3:]
        if last_lines:
            print(f"    [video-fail] {' | '.join(last_lines)}", file=sys.stderr)
    except Exception as e:
        print(f"    [yt-dlp] {url[:60]}: {e}", file=sys.stderr)
    return "", 0


# ── 数据源 1: Bilibili 搜索 ──
def search_bilibili(query: str, max_results: int = 5) -> list[dict]:
    encoded = quote(query)
    url = (
        f"https://api.bilibili.com/x/web-interface/search/type"
        f"?search_type=video&keyword={encoded}&page=1&page_size={max_results}"
    )
    headers = {"Referer": "https://www.bilibili.com/", "Origin": "https://www.bilibili.com"}
    data = _parse_json(_safe_request(url, headers=headers))
    if not data or data.get("code") != 0:
        return []
    results = []
    for item in data.get("data", {}).get("result", [])[:max_results]:
        aid = item.get("aid")
        bvid = item.get("bvid", "")
        results.append({
            "title": item.get("title", "").replace('<em class="keyword">', "").replace("</em>", ""),
            "url": f"https://www.bilibili.com/video/{bvid}" if bvid else f"https://www.bilibili.com/video/av{aid}",
            "bvid": bvid or f"av{aid}",
            "platform": "bilibili",
            "media_type": "video",
            "duration": item.get("duration", ""),
            "description": item.get("description", "")[:200],
            "thumbnail": item.get("pic", ""),
            "play_count": item.get("play", 0),
        })
    return results


# ── 数据源 1.5: YouTube 搜索（yt-dlp 内置）──
def search_youtube(query: str, max_results: int = 5) -> list[dict]:
    """用 yt-dlp 搜索 YouTube 视频"""
    ytdlp = _find_ytdlp()
    if not ytdlp:
        return []
    try:
        result = subprocess.run([
            ytdlp,
            f"ytsearch{max_results}:{query}",
            "--dump-json", "--no-playlist",
            "--flat-playlist", "--socket-timeout", "30",
        ], capture_output=True, text=True, timeout=60, cwd=str(ROOT))
        results = []
        for line in result.stdout.strip().splitlines():
            if not line.strip():
                continue
            try:
                info = json.loads(line)
                vid = info.get("id", "")
                if not vid:
                    continue
                url = info.get("webpage_url", f"https://www.youtube.com/watch?v={vid}")
                results.append({
                    "title": info.get("title", query),
                    "url": url,
                    "video_id": vid,
                    "platform": "youtube",
                    "media_type": "video",
                    "duration": str(info.get("duration", "")),
                    "description": (info.get("description", "") or "")[:200],
                    "thumbnail": info.get("thumbnail", ""),
                    "view_count": info.get("view_count", 0),
                })
            except json.JSONDecodeError:
                continue
        return results[:max_results]
    except Exception as e:
        print(f"    [yt-search] {query}: {e}", file=sys.stderr)
        return []


# ── 数据源 2: GIPHY 搜索 GIF ──
def search_giphy(query: str, max_results: int = 5, api_key: str = "") -> list[dict]:
    if not api_key:
        return []
    encoded = quote(query)
    url = (
        f"https://api.giphy.com/v1/gifs/search"
        f"?api_key={api_key}&q={encoded}&limit={max_results}&rating=g&lang=zh"
    )
    data = _parse_json(_safe_request(url))
    if not data:
        return []
    results = []
    for item in data.get("data", [])[:max_results]:
        images = item.get("images", {})
        original = images.get("original", {})
        results.append({
            "title": item.get("title", query),
            "url": original.get("url", ""),
            "platform": "giphy",
            "media_type": "gif",
            "duration": "",
            "description": item.get("alt_text", "")[:200],
            "thumbnail": images.get("fixed_height_small", {}).get("url", ""),
        })
    return results


# ── 数据源 3: 百度图片搜索（替代已失效的搜狗API）──
def search_baidu_images(query: str, max_results: int = 5) -> list[dict]:
    """百度图片搜索，替代已失效的搜狗API"""
    encoded = quote(query)
    url = (
        f"https://image.baidu.com/search/acjson"
        f"?tn=resultjson_com&logid=&ipn=rj&ct=201326592&is=&fp=result"
        f"&queryWord={encoded}&cl=2&lm=&ie=utf-8&oe=utf-8&word={encoded}"
        f"&s=&se=&tab=&width=&height=&face=&istype=&qc=&nc=&fr=&pn=0&rn={max_results}"
    )
    headers = {
        "Referer": "https://image.baidu.com/",
        "Accept": "text/plain, */*; q=0.01",
    }
    raw = _safe_request(url, headers=headers)
    if not raw:
        return []
    # 百度返回的可能是 JSONP 格式，去掉可能的包装
    text = raw.decode("utf-8", errors="replace").strip()
    data = _parse_json(raw)
    if data is None:
        # 尝试 JSONP 格式
        if text.startswith("try{"):
            text = text[4:]
        data = _parse_json(text.encode("utf-8"))
    if not data:
        return []
    results = []
    items = data.get("data", []) if isinstance(data, dict) else (data if isinstance(data, list) else [])
    for item in items[:max_results]:
        if not isinstance(item, dict):
            continue
        thumb_url = item.get("thumbURL", "") or item.get("middleURL", "")
        if not thumb_url:
            continue
        is_gif = "gif" in item.get("type", "").lower() or "gif" in thumb_url.lower()
        title = (item.get("fromPageTitle", "") or item.get("fromPageTitleEnc", "") or query)
        title = title.replace("<em>", "").replace("</em>", "")
        results.append({
            "title": title,
            "url": thumb_url,
            "platform": "baidu",
            "media_type": "gif" if is_gif else "image",
            "duration": "",
            "description": title[:200],
            "thumbnail": thumb_url,
        })
    return results


# ── 数据源 3.5: Bing 图片搜索（更可靠）──
def search_bing_images(query: str, max_results: int = 5) -> list[dict]:
    """Bing 图片搜索，更稳定的图片源"""
    encoded = quote(query)
    url = (
        f"https://www.bing.com/images/search"
        f"?q={encoded}&qft=+filterui:photo-animatedgif&form=IRFLTR&first=1"
    )
    headers = {
        "Referer": "https://www.bing.com/",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }
    html = _safe_request(url, headers=headers)
    if not html:
        return []
    text = html.decode("utf-8", errors="replace")
    # 从 Bing 页面中提取图片 URL（murl 属性）
    results = []
    seen = set()
    # 匹配 Bing 图片搜索结果中的 murl
    for m in re.finditer(r'"murl"\s*:\s*"([^"]+)"', text):
        img_url = m.group(1)
        if img_url in seen:
            continue
        seen.add(img_url)
        if len(results) >= max_results:
            break
        is_gif = "gif" in img_url.lower() or ".gif" in img_url.lower()
        results.append({
            "title": query,
            "url": img_url,
            "platform": "bing",
            "media_type": "gif" if is_gif else "image",
            "duration": "",
            "description": query,
            "thumbnail": img_url,
        })
    return results


# ── 数据源 4: 公开教学动画仓库 ──
KNOWN_ANIMATION_REPOS = (
    ("https://distill.pub/", "Distill.pub 交互式 ML 可视化"),
    ("https://colah.github.io/", "Christopher Olah 博客"),
    ("https://mlu-explain.github.io/", "MLU Explain 交互式动画"),
    ("https://setosa.io/ev/", "Setosa 交互式可视化"),
    ("https://poloclub.github.io/cnn-explainer/", "CNN Explainer"),
    ("https://playground.tensorflow.org/", "TensorFlow Playground (神经网络)"),
    ("https://adamharley.com/nn_vis/", "3D CNN 可视化"),
    ("https://www.cs.ryerson.ca/~aharley/vis/conv/", "CNN 手写数字可视化"),
    ("https://github.com/3b1b/manim", "3Blue1Brown Manim 动画引擎"),
    ("https://github.com/dair-ai/ml-visuals", "dair-ai ML Visuals"),
    ("https://github.com/trekhleb/machine-learning-experiments", "ML Experiments 可视化"),
    ("https://github.com/parrt/dtreeviz", "dtreeviz 决策树可视化"),
    ("https://github.com/shap/shap", "SHAP 可解释性可视化"),
    ("https://github.com/alexlenail/NN-SVG", "NN-SVG 神经网络绘图"),
    ("https://github.com/HarisIqbal88/PlotNeuralNet", "PlotNeuralNet LaTeX 绘图"),
    ("https://github.com/lutzroeder/netron", "Netron 网络结构可视化"),
)


def _classify_repo_to_knowledge(repo_url: str, repo_desc: str) -> list[str]:
    lower = (repo_url + repo_desc).lower()
    matched = []
    for kp in KNOWLEDGE_POINTS:
        en_lower = kp.en_name.lower()
        if en_lower in lower or kp.name in lower:
            matched.append(kp.name)
    return matched


def build_known_repo_index() -> list[AnimationResult]:
    results = []
    for url, desc in KNOWN_ANIMATION_REPOS:
        for kp_name in _classify_repo_to_knowledge(url, desc):
            kp = next((k for k in KNOWLEDGE_POINTS if k.name == kp_name), None)
            results.append(AnimationResult(
                knowledge_point=kp_name,
                category=kp.category if kp else "未知",
                title=desc,
                url=url,
                platform="open_source_repo",
                media_type="interactive",
                duration="",
                description=desc,
                thumbnail="",
                source_query="known_repo_index",
            ))
    return results


# ── 主爬虫流程 ──
def crawl_all(
    bilibili: bool = True,
    youtube: bool = True,
    gifs: bool = True,
    giphy_key: str = "",
    known_repos: bool = True,
    max_per_query: int = 5,
    delay: float = 0.8,
    download: bool = False,
    download_videos: bool = False,
    video_only: bool = False,
    workers: int = 4,
) -> tuple[AnimationResult, ...]:
    all_results: list[AnimationResult] = []

    if known_repos and not video_only:
        print("[1/6] 索引已知开源动画仓库...")
        repo_results = build_known_repo_index()
        print(f"  → 匹配 {len(repo_results)} 条")
        all_results.extend(repo_results)

    if bilibili:
        print(f"[2/6] Bilibili 搜索 {len(KNOWLEDGE_POINTS)} 个知识点...")
        for i, kp in enumerate(KNOWLEDGE_POINTS, 1):
            query = f"{kp.name} 动画"
            print(f"  [{i:>2}/{len(KNOWLEDGE_POINTS)}] {kp.name} → {query}")
            try:
                for item in search_bilibili(query, max_results=max_per_query):
                    all_results.append(AnimationResult(
                        knowledge_point=kp.name, category=kp.category,
                        title=item["title"], url=item["url"],
                        platform=item["platform"], media_type=item["media_type"],
                        duration=item["duration"], description=item["description"],
                        thumbnail=item["thumbnail"], source_query=query,
                    ))
            except Exception as e:
                print(f"      失败: {e}")
            time.sleep(delay)

    if youtube:
        print(f"[3/6] YouTube 搜索 {len(KNOWLEDGE_POINTS)} 个知识点...")
        for i, kp in enumerate(KNOWLEDGE_POINTS, 1):
            query = f"{kp.en_name} animation explained"
            print(f"  [{i:>2}/{len(KNOWLEDGE_POINTS)}] {kp.name} → {query}")
            try:
                for item in search_youtube(query, max_results=max(3, max_per_query // 2)):
                    all_results.append(AnimationResult(
                        knowledge_point=kp.name, category=kp.category,
                        title=item["title"], url=item["url"],
                        platform=item["platform"], media_type=item["media_type"],
                        duration=item["duration"], description=item["description"],
                        thumbnail=item["thumbnail"], source_query=query,
                    ))
            except Exception as e:
                print(f"      失败: {e}")
            time.sleep(delay)

    if gifs and not video_only:
        print(f"[4/6] Bing + 百度图片搜索 GIF...")
        for i, kp in enumerate(KNOWLEDGE_POINTS, 1):
            query = kp.search_queries[0]
            print(f"  [{i:>2}/{len(KNOWLEDGE_POINTS)}] {kp.name} → {query}")
            try:
                # Bing 优先（更稳定）
                bing_items = search_bing_images(query, max_results=max_per_query)
                if bing_items:
                    for item in bing_items:
                        all_results.append(AnimationResult(
                            knowledge_point=kp.name, category=kp.category,
                            title=item["title"], url=item["url"],
                            platform=item["platform"], media_type=item["media_type"],
                            duration="", description=item["description"],
                            thumbnail=item["thumbnail"], source_query=query,
                        ))
                # 百度兜底
                for item in search_baidu_images(query, max_results=max(2, max_per_query // 2)):
                    all_results.append(AnimationResult(
                        knowledge_point=kp.name, category=kp.category,
                        title=item["title"], url=item["url"],
                        platform=item["platform"], media_type=item["media_type"],
                        duration="", description=item["description"],
                        thumbnail=item["thumbnail"], source_query=query,
                    ))
            except Exception as e:
                print(f"      失败: {e}")
            time.sleep(delay)

    if bilibili:
        print(f"[5/6] Bilibili 英文补充...")
        for i, kp in enumerate(KNOWLEDGE_POINTS, 1):
            query = f"{kp.en_name} animation"
            print(f"  [{i:>2}/{len(KNOWLEDGE_POINTS)}] {kp.name} → {query}")
            try:
                for item in search_bilibili(query, max_results=max(2, max_per_query // 2)):
                    all_results.append(AnimationResult(
                        knowledge_point=kp.name, category=kp.category,
                        title=item["title"], url=item["url"],
                        platform=item["platform"], media_type=item["media_type"],
                        duration=item["duration"], description=item["description"],
                        thumbnail=item["thumbnail"], source_query=query,
                    ))
            except Exception as e:
                print(f"      失败: {e}")
            time.sleep(delay)

    if giphy_key and gifs and not video_only:
        print(f"[6/6] GIPHY 搜索...")
        for i, kp in enumerate(KNOWLEDGE_POINTS, 1):
            query = kp.en_name
            print(f"  [{i:>2}/{len(KNOWLEDGE_POINTS)}] {kp.name} → {query}")
            try:
                for item in search_giphy(query, max_results=max_per_query, api_key=giphy_key):
                    all_results.append(AnimationResult(
                        knowledge_point=kp.name, category=kp.category,
                        title=item["title"], url=item["url"],
                        platform=item["platform"], media_type=item["media_type"],
                        duration="", description=item["description"],
                        thumbnail=item["thumbnail"], source_query=query,
                    ))
            except Exception as e:
                print(f"      失败: {e}")
            time.sleep(delay)

    results = tuple(all_results)

    # ── 下载到本地 ──
    if download and results:
        results = _download_assets(results, download_videos=download_videos, workers=workers)

    return results


def _download_assets(
    results: tuple[AnimationResult, ...],
    download_videos: bool = False,
    video_only: bool = False,
    workers: int = 4,
) -> tuple[AnimationResult, ...]:
    print(f"\n{'='*60}")
    print(f"📥 下载到本地...")
    print(f"{'='*60}")

    ytdlp = _find_ytdlp() if download_videos else None
    if download_videos and ytdlp:
        print(f"  yt-dlp: ✓ 可用")
    elif download_videos:
        print(f"  yt-dlp: ✗ 未安装，跳过视频下载 (pip install yt-dlp)")
    if video_only:
        print(f"  模式: 仅下载视频（跳过图片/GIF）")

    download_tasks = []
    for i, r in enumerate(results):
        save_dir = ANIMATIONS / _sanitize_filename(r.knowledge_point, 30)
        is_video_platform = r.platform in ("bilibili", "youtube")
        has_thumbnail = bool(r.thumbnail)

        if is_video_platform and download_videos and ytdlp:
            vid = ""
            if r.platform == "bilibili":
                vid = r.url.split("/video/")[-1].split("?")[0].rstrip("/") if "/video/" in r.url else ""
                vid = f"https://www.bilibili.com/video/{vid}" if vid else r.url
            else:
                vid = r.url
            if vid:
                download_tasks.append(("video", i, r, save_dir, vid))
            # 视频模式跳过图片，非视频模式下载缩略图
            if not video_only and has_thumbnail:
                download_tasks.append(("image", i, r, save_dir, ""))
        elif not video_only and has_thumbnail:
            download_tasks.append(("image", i, r, save_dir, ""))
        elif not video_only and r.url and r.media_type in ("gif", "image"):
            download_tasks.append(("image", i, r, save_dir, ""))

    print(f"  待下载: {len(download_tasks)} 个文件 ({workers} 线程并行)")
    if not download_tasks:
        print(f"  ⚠️ 没有可下载的文件，检查搜索结果中是否有缩略图URL")
        return results

    result_list = list(results)
    count = {"ok": 0, "fail": 0}

    def _do_download(task):
        kind, idx, item, sdir, extra = task
        try:
            if kind == "video":
                local, size = download_video_ytdlp(extra, sdir, item.title)
                if not local and item.thumbnail:
                    # 视频下载失败，回退到下载缩略图
                    local, size = download_file(item.thumbnail, sdir, item.title)
            else:
                url = item.thumbnail or item.url
                if not url:
                    return idx, item
                local, size = download_file(url, sdir, item.title)
            if local:
                count["ok"] += 1
                return idx, AnimationResult(
                    knowledge_point=item.knowledge_point, category=item.category,
                    title=item.title, url=item.url, platform=item.platform,
                    media_type=item.media_type, duration=item.duration,
                    description=item.description, thumbnail=item.thumbnail,
                    source_query=item.source_query, local_path=local,
                    file_size=size, downloaded=True,
                )
            else:
                count["fail"] += 1
        except Exception as exc:
            print(f"    [thread-error] {item.title[:30]}: {exc}", file=sys.stderr)
            count["fail"] += 1
        return idx, item
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [pool.submit(_do_download, t) for t in download_tasks]
        for f in as_completed(futures):
            idx, updated = f.result()
            result_list[idx] = updated

    print(f"  下载完成: {count['ok']} 个成功, {count['fail']} 个失败")
    return tuple(result_list)


# ── 输出 ──
def save_results(results: tuple[AnimationResult, ...]) -> None:
    print(f"\n{'='*60}")
    print(f"💾 保存结果...")

    jsonl_path = ANIMATIONS / "animation_results.jsonl"
    with jsonl_path.open("w", encoding="utf-8") as f:
        for r in results:
            f.write(json.dumps(asdict(r), ensure_ascii=False) + "\n")
    print(f"  JSONL: {jsonl_path}")

    grouped: dict[str, list[dict]] = {}
    for r in results:
        grouped.setdefault(r.knowledge_point, []).append(asdict(r))
    grouped_path = ANIMATIONS / "animations_by_knowledge.json"
    with grouped_path.open("w", encoding="utf-8") as f:
        json.dump(grouped, f, ensure_ascii=False, indent=2)

    csv_path = ANIMATIONS / "animation_results.csv"
    fieldnames = [
        "knowledge_point", "category", "title", "url", "platform",
        "media_type", "duration", "local_path", "file_size", "downloaded",
    ]
    with csv_path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for r in results:
            writer.writerow(asdict(r))

    summary = {}
    downloaded_count = 0
    total_size = 0
    for r in results:
        if r.knowledge_point not in summary:
            summary[r.knowledge_point] = {"count": 0, "platforms": set(), "media_types": set(), "downloaded": 0}
        summary[r.knowledge_point]["count"] += 1
        summary[r.knowledge_point]["platforms"].add(r.platform)
        summary[r.knowledge_point]["media_types"].add(r.media_type)
        if r.downloaded:
            summary[r.knowledge_point]["downloaded"] += 1
            downloaded_count += 1
            total_size += r.file_size

    report = {
        "total_results": len(results),
        "downloaded_files": downloaded_count,
        "total_size_mb": round(total_size / 1024 / 1024, 2),
        "crawled_at": datetime.now(timezone.utc).isoformat(),
        "knowledge_points": {
            name: {
                "count": info["count"],
                "downloaded": info["downloaded"],
                "platforms": sorted(info["platforms"]),
                "media_types": sorted(info["media_types"]),
            }
            for name, info in sorted(summary.items(), key=lambda x: -x[1]["count"])
        },
    }
    report_path = ANIMATIONS / "animation_summary.json"
    with report_path.open("w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    # 打印摘要
    print(f"\n{'='*60}")
    print(f"📊 爬虫结果摘要")
    print(f"{'='*60}")
    print(f"总结果数: {len(results)}")
    print(f"已下载文件: {downloaded_count} 个 ({report['total_size_mb']} MB)")
    print(f"覆盖知识点: {len(summary)}/{len(KNOWLEDGE_POINTS)}")
    print()
    print(f"{'知识点':<12} {'总数':>4} {'已下载':>5}   {'来源平台'}")
    print("-" * 55)
    for name, info in sorted(summary.items(), key=lambda x: -x[1]["count"]):
        platforms = ", ".join(info["platforms"])
        print(f"{name:<12} {info['count']:>4} {info['downloaded']:>5}   {platforms}")

    uncovered = [kp.name for kp in KNOWLEDGE_POINTS if kp.name not in summary]
    if uncovered:
        print(f"\n⚠️ 未找到资源: {', '.join(uncovered)}")

    # 列出已下载的文件目录
    downloaded_dirs = set()
    for r in results:
        if r.local_path:
            downloaded_dirs.add(str(ANIMATIONS / _sanitize_filename(r.knowledge_point, 30)))
    if downloaded_dirs:
        print(f"\n📁 下载文件目录:")
        for d in sorted(downloaded_dirs):
            count = sum(1 for r in results if d in r.local_path)
            print(f"  {d}/ ({count} 个文件)")


# ── CLI ──
def main() -> int:
    parser = argparse.ArgumentParser(
        description="爬取各知识点相关的动画/视频资源并下载到本地",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python scripts/crawl_animations.py                          # 搜索 + 保存URL
  python scripts/crawl_animations.py --download               # 搜索 + 下载GIF/缩略图到本地
  python scripts/crawl_animations.py --download --download-video  # 搜索 + 下载GIF+视频
  python scripts/crawl_animations.py --no-bilibili --download # 只下载GIF
  python scripts/crawl_animations.py --max 3 --delay 1.0      # 调整参数
  python scripts/crawl_animations.py --dry-run                # 只看知识点列表
  python scripts/crawl_animations.py --giphy-key YOUR_KEY     # 使用 GIPHY API
        """,
    )
    parser.add_argument("--download", action="store_true", help="下载 GIF/缩略图到本地")
    parser.add_argument("--download-video", action="store_true", help="下载视频到本地 (需 yt-dlp)")
    parser.add_argument("--video-only", action="store_true", help="只下载视频，跳过所有图片/GIF")
    parser.add_argument("--no-youtube", action="store_true", help="跳过 YouTube 搜索")
    parser.add_argument("--no-bilibili", action="store_true", help="跳过 Bilibili 搜索")
    parser.add_argument("--no-gifs", action="store_true", help="跳过 GIF 搜索")
    parser.add_argument("--no-known-repos", action="store_true", help="跳过已知仓库索引")
    parser.add_argument("--giphy-key", type=str, default="", help="GIPHY API Key (可选)")
    parser.add_argument("--max", type=int, default=5, dest="max_per_query", help="每查询最大结果数 (默认 5)")
    parser.add_argument("--delay", type=float, default=0.8, help="请求间隔秒数 (默认 0.8)")
    parser.add_argument("--workers", type=int, default=4, help="下载并行线程数 (默认 4)")
    parser.add_argument("--dry-run", action="store_true", help="只打印知识点列表")
    args = parser.parse_args()

    if args.dry_run:
        print("=" * 60)
        print(f"📚 知识点列表 (共 {len(KNOWLEDGE_POINTS)} 个)")
        print("=" * 60)
        for kp in KNOWLEDGE_POINTS:
            print(f"  [{kp.category}] {kp.name} ({kp.en_name})")
            for q in kp.search_queries[:2]:
                print(f"      → {q}")
        print()
        print("运行: python scripts/crawl_animations.py --download-video --video-only")
        return 0

    print("=" * 60)
    print("🎬 EduMatrix 动画爬虫")
    print("=" * 60)
    print(f"知识点: {len(KNOWLEDGE_POINTS)} 个")
    sources = []
    if not args.no_bilibili: sources.append("Bilibili")
    if not args.no_youtube: sources.append("YouTube")
    if not args.no_gifs: sources.append("图片")
    if not args.no_known_repos: sources.append("已知仓库")
    print(f"数据源: {' | '.join(sources) if sources else '无'}")
    mode = "仅视频" if args.video_only else ("图片+缩略图" if args.download else "仅URL")
    if args.download_video and not args.video_only:
        mode += " + 视频"
    print(f"下载模式: {mode}")
    print(f"输出目录: {ANIMATIONS}")
    print()

    results = crawl_all(
        bilibili=not args.no_bilibili,
        youtube=not args.no_youtube,
        gifs=not args.no_gifs,
        giphy_key=args.giphy_key,
        known_repos=not args.no_known_repos,
        max_per_query=args.max_per_query,
        delay=args.delay,
        download=args.download or args.download_video,
        download_videos=args.download_video,
        video_only=args.video_only,
        workers=args.workers,
    )

    save_results(results)
    print(f"\nDone. 输出目录: {ANIMATIONS}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())