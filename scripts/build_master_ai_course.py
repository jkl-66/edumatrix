from __future__ import annotations

"""Build the unified Chinese AI/deep-learning/LLM course bundle.

The bundle keeps a deterministic chapter order while retaining the upstream
repository, commit and source-path metadata for every imported chapter.
"""

import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw" / "github_repos"
OUT = ROOT / "data" / "curated" / "ai_deep_learning_agents_v1"
MANIFEST = OUT / "course_manifest.json"
COURSE_ID = "course-ai-deep-learning-agents-v1"


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def revision(repo: Path) -> str:
    import subprocess

    return subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip()


def read_utf8(path: Path) -> str:
    return path.read_text(encoding="utf-8").replace("\r\n", "\n").replace("\r", "\n")


def collect_dir(repo: Path, relative_dir: str) -> tuple[str, str]:
    base = repo / relative_dir
    paths = sorted(
        p for p in base.rglob("*.md")
        if not p.name.endswith("_origin.md") and "/." not in p.as_posix()
    )
    if not paths:
        raise ValueError(f"no markdown source files found under {relative_dir}")
    parts = []
    for path in paths:
        parts.append(f"\n\n<!-- 上游文件: {path.relative_to(repo).as_posix()} -->\n\n{read_utf8(path).strip()}")
    return "\n".join(parts).strip() + "\n", ";".join(p.relative_to(repo).as_posix() for p in paths)


def collect_files(repo: Path, paths: list[str]) -> tuple[str, str]:
    parts = []
    for relative in paths:
        path = repo / relative
        if not path.is_file():
            raise ValueError(f"missing source file: {repo.name}/{relative}")
        parts.append(f"\n\n<!-- 上游文件: {relative} -->\n\n{read_utf8(path).strip()}")
    return "\n".join(parts).strip() + "\n", ";".join(paths)


KNOWLEDGE_POINTS = [
    ("AI-KP-01", "人工智能、机器学习与深度学习概览", "foundation", []),
    ("AI-KP-02", "向量、矩阵与概率基础", "foundation", ["AI-KP-01"]),
    ("AI-KP-03", "数据集、特征工程与数据管道", "foundation", ["AI-KP-02"]),
    ("AI-KP-04", "线性回归与线性分类", "core", ["AI-KP-02", "AI-KP-03"]),
    ("AI-KP-05", "模型评估、泛化与交叉验证", "core", ["AI-KP-04"]),
    ("AI-KP-06", "多层感知机与反向传播", "core", ["AI-KP-04"]),
    ("AI-KP-07", "优化算法、正则化与训练稳定性", "core", ["AI-KP-05", "AI-KP-06"]),
    ("AI-KP-08", "卷积神经网络与视觉表征", "core", ["AI-KP-06"]),
    ("AI-KP-09", "循环神经网络与序列建模", "core", ["AI-KP-06"]),
    ("AI-KP-10", "注意力机制与 Transformer", "core", ["AI-KP-07", "AI-KP-09"]),
    ("AI-KP-11", "图神经网络与知识图谱", "advanced", ["AI-KP-10"]),
    ("AI-KP-12", "无监督学习、表示学习与降维", "advanced", ["AI-KP-03", "AI-KP-07"]),
    ("AI-KP-13", "计算机视觉应用", "advanced", ["AI-KP-08"]),
    ("AI-KP-14", "自然语言处理与预训练", "advanced", ["AI-KP-09", "AI-KP-10"]),
    ("AI-KP-15", "大语言模型架构与生成", "advanced", ["AI-KP-10", "AI-KP-14"]),
    ("AI-KP-16", "指令微调与偏好对齐", "advanced", ["AI-KP-15"]),
    ("AI-KP-17", "RAG 文档解析、切分与混合检索", "advanced", ["AI-KP-10", "AI-KP-15"]),
    ("AI-KP-18", "工具调用、ReAct 与 Agent", "advanced", ["AI-KP-15", "AI-KP-17"]),
    ("AI-KP-19", "Coding Agent、MCP 与 Skill", "advanced", ["AI-KP-18"]),
    ("AI-KP-20", "个性化学习智能体综合项目", "capstone", ["AI-KP-17", "AI-KP-18", "AI-KP-19"]),
]


CHAPTERS = [
    ("D2L 引言：人工智能与机器学习全景", "d2l-zh", "chapter_introduction", "D2L 中文第二版主教材", "Apache-2.0", ["AI-KP-01"]),
    ("D2L 预备知识：数学、数据与自动微分", "d2l-zh", "chapter_preliminaries", "D2L 中文第二版主教材", "Apache-2.0", ["AI-KP-02", "AI-KP-03"]),
    ("D2L 线性神经网络", "d2l-zh", "chapter_linear-networks", "D2L 中文第二版主教材", "Apache-2.0", ["AI-KP-04"]),
    ("D2L 多层感知机", "d2l-zh", "chapter_multilayer-perceptrons", "D2L 中文第二版主教材", "Apache-2.0", ["AI-KP-06"]),
    ("D2L 深度学习计算", "d2l-zh", "chapter_deep-learning-computation", "D2L 中文第二版主教材", "Apache-2.0", ["AI-KP-06", "AI-KP-07"]),
    ("D2L 优化算法", "d2l-zh", "chapter_optimization", "D2L 中文第二版主教材", "Apache-2.0", ["AI-KP-05", "AI-KP-07"]),
    ("D2L 卷积神经网络", "d2l-zh", "chapter_convolutional-neural-networks", "D2L 中文第二版主教材", "Apache-2.0", ["AI-KP-08"]),
    ("D2L 现代卷积网络", "d2l-zh", "chapter_convolutional-modern", "D2L 中文第二版主教材", "Apache-2.0", ["AI-KP-08"]),
    ("D2L 循环神经网络", "d2l-zh", "chapter_recurrent-neural-networks", "D2L 中文第二版主教材", "Apache-2.0", ["AI-KP-09"]),
    ("D2L 现代循环网络与序列任务", "d2l-zh", "chapter_recurrent-modern", "D2L 中文第二版主教材", "Apache-2.0", ["AI-KP-09"]),
    ("D2L 注意力机制与 Transformer", "d2l-zh", "chapter_attention-mechanisms", "D2L 中文第二版主教材", "Apache-2.0", ["AI-KP-10"]),
    ("D2L 无监督学习与表示", "d2l-zh", "chapter_computational-performance", "D2L 中文第二版主教材补充", "Apache-2.0", ["AI-KP-12"]),
    ("D2L 计算机视觉应用", "d2l-zh", "chapter_computer-vision", "D2L 中文第二版主教材", "Apache-2.0", ["AI-KP-13"]),
    ("D2L 自然语言处理预训练", "d2l-zh", "chapter_natural-language-processing-pretraining", "D2L 中文第二版主教材", "Apache-2.0", ["AI-KP-14"]),
    ("D2L 自然语言处理应用", "d2l-zh", "chapter_natural-language-processing-applications", "D2L 中文第二版主教材", "Apache-2.0", ["AI-KP-14"]),
    ("NNDL 第二版：神经网络与深度学习理论地图", "nndl", "README.md", "理论深化与通识版入口", "OTHER", ["AI-KP-01", "AI-KP-06", "AI-KP-10", "AI-KP-11", "AI-KP-15"]),
    ("NNDL 第二版完整电子书", "nndl", "nndl-v2.pdf", "理论深化完整电子书", "OTHER", ["AI-KP-01", "AI-KP-02", "AI-KP-04", "AI-KP-06", "AI-KP-07", "AI-KP-10", "AI-KP-11", "AI-KP-12", "AI-KP-15"]),
    ("NNDL 通识版完整电子书", "nndl", "nndl-ge.pdf", "零基础直觉完整电子书", "OTHER", ["AI-KP-01", "AI-KP-06", "AI-KP-10", "AI-KP-15"]),
    ("NNDL 案例与实践：PyTorch 工程实践", "nndl-practice", "README.md", "代码实践教材", "OTHER", ["AI-KP-04", "AI-KP-06", "AI-KP-08", "AI-KP-09", "AI-KP-10"]),
    ("大模型基础：Transformer 到 Mini-GPT", "llm-beginner", "task-1-transformer/README.md;task-2-mini-gpt/README.md", "大模型与智能体专题", "MIT", ["AI-KP-10", "AI-KP-15"]),
    ("指令微调与偏好对齐", "llm-beginner", "task-3-sft-dpo/README.md", "大模型与智能体专题", "MIT", ["AI-KP-16"]),
    ("RAG 知识库问答工程", "llm-beginner", "task-4-rag/README.md", "大模型与智能体专题", "MIT", ["AI-KP-17"]),
    ("工具调用与 ReAct Agent", "llm-beginner", "task-5-tool-agent/README.md", "大模型与智能体专题", "MIT", ["AI-KP-18"]),
    ("Coding Agent、MCP 与 Skill", "llm-beginner", "task-6-coding-agent/README.md", "大模型与智能体专题", "MIT", ["AI-KP-19"]),
]


def source_content(repo: Path, source_spec: str) -> tuple[str, str]:
    if ";" in source_spec:
        return collect_files(repo, source_spec.split(";"))
    path = repo / source_spec
    if path.is_dir():
        return collect_dir(repo, source_spec)
    return collect_files(repo, [source_spec])


def build() -> dict:
    OUT.mkdir(parents=True, exist_ok=True)
    license_text = """# 课程来源与许可说明

本课程由 EduMatrix 按用户已取得的使用许可整理为统一学习包，保留以下上游来源和版本信息：

- D2L 中文第二版 PyTorch：Apache License 2.0，https://github.com/d2l-ai/d2l-zh
- 《神经网络与深度学习》第二版与通识版：https://github.com/nndl/nndl
- 《神经网络与深度学习：案例与实践》：https://github.com/nndl/nndl-practice
- 《大模型与智能体》/LLM-Beginner：MIT License，https://github.com/nndl/llm-beginner

每章 manifest 条目保存上游仓库、固定 commit、源文件路径、源哈希、转换方式和本文件哈希，供课程来源追踪与证据引用使用。
"""
    license_path = OUT / "LICENSES.md"
    license_path.write_text(license_text, encoding="utf-8", newline="\n")
    license_hash = sha(license_path.read_bytes())
    files = []
    for order, (title, repo_key, source_spec, role, spdx, kp_codes) in enumerate(CHAPTERS):
        repo = RAW / repo_key
        rev = revision(repo)
        binary_source = source_spec.lower().endswith(".pdf")
        if binary_source:
            source_file = repo / source_spec
            if not source_file.is_file():
                raise ValueError(f"missing source file: {repo_key}/{source_spec}")
            source_raw = source_file.read_bytes()
            try:
                from pypdf import PdfReader

                reader = PdfReader(str(source_file))
                pages = []
                for page_number, page in enumerate(reader.pages, start=1):
                    page_text = (page.extract_text() or "").strip()
                    if page_text:
                        pages.append(f"\n\n--- 第 {page_number} 页 ---\n\n{page_text}")
                extracted = "".join(pages).strip()
            except Exception as exc:
                raise ValueError(f"failed to extract PDF text: {repo_key}/{source_spec}") from exc
            if not extracted:
                raise ValueError(f"PDF contains no extractable text: {repo_key}/{source_spec}")
            source_path = source_spec
            header = (
                f"# {title}\n\n> 课程：人工智能与深度学习：从机器学习基础到大模型智能体  \\n"
                f"> 来源角色：{role}  \\n"
                f"> 上游仓库：{repo_key}（固定版本 `{rev}`）  \\n"
                f"> 上游文件：`{source_path}`（PDF 已按页离线转为可检索 Markdown）  \\n"
                f"> 许可标识：{spdx}；详见 `LICENSES.md`\n\n"
                "## 本章学习目标\n\n"
                f"围绕 {', '.join(kp_codes)} 建立可解释、可检索的理论单元；保留完整电子书页码标记以便证据追溯。\n\n"
                "## 教材正文\n\n"
            )
            transformed = (header + extracted + "\n").encode("utf-8")
            extension = "md"
        else:
            content, source_path = source_content(repo, source_spec)
            header = (
                f"# {title}\n\n> 课程：人工智能与深度学习：从机器学习基础到大模型智能体  \\n"
                f"> 来源角色：{role}  \\n"
                f"> 上游仓库：{repo_key}（固定版本 `{rev}`）  \\n"
                f"> 上游文件：`{source_path}`  \\n"
                f"> 许可标识：{spdx}；详见 `LICENSES.md`\n\n"
                "## 本章学习目标\n\n"
                f"围绕 {', '.join(kp_codes)} 建立可解释、可实践、可检索的知识单元；正文保留上游章节结构并由系统按知识点切分。\n\n"
                "## 教材正文\n\n"
            )
            transformed = (header + content).encode("utf-8")
            source_raw = content.encode("utf-8")
            extension = "md"
        rel = f"chapters/{order:02d}_{title.replace('：', '_').replace(' ', '')}.{extension}"
        out_path = OUT / rel
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(transformed)
        files.append({
            "chapter_order": order,
            "title": title,
            "repository_key": repo_key,
            "repository_url": {
                "d2l-zh": "https://github.com/d2l-ai/d2l-zh",
                "nndl": "https://github.com/nndl/nndl",
                "nndl-practice": "https://github.com/nndl/nndl-practice",
                "llm-beginner": "https://github.com/nndl/llm-beginner",
            }[repo_key],
            "git_revision": rev,
            "source_path": source_path,
            "source_type": "pdf" if binary_source else "md",
            "source_bytes": len(source_raw),
            "source_sha256": sha(source_raw),
            "path": rel,
            "bytes": len(transformed),
            "sha256": sha(transformed),
            "parser_version": "edumatrix-course-source-v2",
            "license_spdx": spdx,
            "license_file": "LICENSES.md",
            "license_sha256": license_hash,
            "knowledge_point_codes": kp_codes,
            "source_role": role,
            "conversion": "markdown-concatenation-with-provenance-header",
        })
    manifest = {
        "schema_version": "edumatrix.course-version-manifest.v1",
        "manifest_version": "course-ai-deep-learning-agents-1.1.0",
        "generated_at": "2026-08-31T00:00:00+08:00",
        "course_id": COURSE_ID,
        "title": "人工智能与深度学习：从机器学习基础到大模型智能体",
        "subject": "人工智能 / 深度学习 / 大模型与智能体",
        "description": "从机器学习数学与数据基础、神经网络和 Transformer，逐步进入大语言模型、RAG、Agent 与个性化学习智能体综合项目的中文主课程。",
        "domain_pack": "domain-ai-deep-learning-agents-v1",
        "knowledge_point_version": "ai-deep-learning-agents-kp-1.0.0",
        "language": "zh-CN",
        "content_origin": "D2L 中文第二版 PyTorch、NNDL 理论与通识版、NNDL 案例与实践、LLM-Beginner 的固定版本整合；每章保留来源角色和可追溯元数据。",
        "license": "用户已取得课程资料使用许可；上游许可与署名见 LICENSES.md 及各文件 provenance 字段。",
        "visibility": "public",
        "status": "published",
        "tags": ["主课程", "机器学习", "深度学习", "Transformer", "大语言模型", "RAG", "Agent", "中文教材"],
        "source_roles": {"primary": "D2L 中文第二版 PyTorch", "theory": "NNDL 第二版", "intuition": "NNDL 通识版", "code": "NNDL 案例与实践", "llm_agent": "LLM-Beginner"},
        "pathways": {
            "main": ["AI-KP-01", "AI-KP-02", "AI-KP-03", "AI-KP-04", "AI-KP-05", "AI-KP-06", "AI-KP-07", "AI-KP-08", "AI-KP-09", "AI-KP-10", "AI-KP-15", "AI-KP-17", "AI-KP-18", "AI-KP-20"],
            "theory": ["AI-KP-02", "AI-KP-04", "AI-KP-06", "AI-KP-07", "AI-KP-10", "AI-KP-11", "AI-KP-12", "AI-KP-15"],
            "engineering": ["AI-KP-03", "AI-KP-04", "AI-KP-06", "AI-KP-08", "AI-KP-10", "AI-KP-15", "AI-KP-17", "AI-KP-18", "AI-KP-19", "AI-KP-20"],
        },
        "knowledge_points": [{"code": c, "title": t, "level": l, "prerequisites": p} for c, t, l, p in KNOWLEDGE_POINTS],
        "files": files,
    }
    MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    return manifest


if __name__ == "__main__":
    result = build()
    print(json.dumps({"course_id": result["course_id"], "documents": len(result["files"]), "knowledge_points": len(result["knowledge_points"]), "manifest": str(MANIFEST.relative_to(ROOT))}, ensure_ascii=False))
