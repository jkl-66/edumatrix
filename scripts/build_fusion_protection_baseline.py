#!/usr/bin/env python3
"""Create a compact, reproducible protection baseline for the 7.20 core pages.

This is an evidence builder only. It reads the isolated baseline source and
writes audit artifacts; it does not touch runtime code, databases, or Git.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any


PROTECTED_PAGES: list[dict[str, Any]] = [
    {
        "id": "profile",
        "title": "学习画像",
        "route": "/student-analysis",
        "view": "frontend/src/views/StudentAnalysis.vue",
        "required_capabilities": [
            "掌握度分析与雷达图",
            "知识点/能力维度查看",
            "薄弱点或问题原因查看",
            "个性化建议查看",
            "一键生成个性化资源",
            "画像内容自定义编辑",
        ],
        "allowed_reduction": ["重复说明", "内部算法字段", "低频操作的首屏曝光"],
        "required_enhancement": ["节点证据侧栏", "推荐资源和下一步动作", "完成事件回流"],
    },
    {
        "id": "learning_path",
        "title": "学习路径",
        "route": "/learning-path",
        "view": "frontend/src/views/LearningPathGraph.vue",
        "required_capabilities": [
            "路径节点/知识关系展示",
            "路径项目选择与切换",
            "路径预算或节奏调整",
            "按新预算重建/更新",
            "节点资源进入学习",
            "学习进度和节点状态展示",
        ],
        "allowed_reduction": ["重复解释", "内部状态机术语", "高级参数的默认展开"],
        "required_enhancement": ["今日任务优先", "完成条件", "合法重规划提示和恢复"],
    },
    {
        "id": "notes",
        "title": "笔记本",
        "route": "/notes",
        "view": "frontend/src/views/Notes.vue",
        "required_capabilities": [
            "笔记列表与选择",
            "笔记编辑与保存",
            "AI 排版/润色",
            "标签和知识点整理",
            "知识库来源关联",
            "生成闪卡或加入复习",
            "笔记导出",
            "错题反思追加",
        ],
        "allowed_reduction": ["同屏重复按钮", "低频设置", "工程字段"],
        "required_enhancement": ["课程/章节/知识点上下文", "生成练习", "保存事件进入成长动态"],
    },
    {
        "id": "wrong_questions",
        "title": "错题本",
        "route": "/wrong-questions",
        "view": "frontend/src/views/WrongQuestionBook.vue",
        "required_capabilities": [
            "错题列表和筛选",
            "题目、答案与解析查看",
            "错因/反思记录",
            "相似题生成",
            "笔记与固定",
            "闪卡生成",
            "重做/复测",
            "导出",
        ],
        "allowed_reduction": ["视频生成前置", "复杂审核状态", "内部对象标识"],
        "required_enhancement": ["错因确认主动作", "复测后更新画像/路径", "统一复习队列"],
    },
]

SUPPORTING_FILES = [
    "frontend/src/views/ProfileDashboard.vue",
    "frontend/src/views/Review.vue",
    "frontend/src/views/RevisionCalendar.vue",
    "frontend/src/api/profile.js",
    "frontend/src/api/path.js",
    "frontend/src/api/notes.js",
    "frontend/src/api/quiz.js",
    "frontend/src/api/review.js",
]


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8-sig", errors="replace")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def clean_markup(value: str) -> str:
    value = re.sub(r"<[^>]+>", " ", value)
    value = re.sub(r"\{\{.*?\}\}", " ", value, flags=re.S)
    return re.sub(r"\s+", " ", value).strip()


def visible_text(source: str, tag: str) -> list[str]:
    values = re.findall(rf"<{tag}\b[^>]*>(.*?)</{tag}>", source, flags=re.I | re.S)
    return sorted({clean_markup(value) for value in values if clean_markup(value)})


def file_evidence(root: Path, relative: str) -> dict[str, Any]:
    path = root / relative
    if not path.exists():
        return {"file": relative, "exists": False}
    source = read_text(path)
    api_imports = re.findall(
        r"import\s+\{(?P<symbols>[^}]*)\}\s+from\s+['\"](?P<module>\.\.?/api(?:/[^'\"]*)?)['\"]",
        source,
    )
    api_symbols: list[str] = []
    api_modules: list[str] = []
    for symbols, module in api_imports:
        api_modules.append(module)
        for raw_symbol in symbols.split(","):
            symbol = raw_symbol.strip().split(" as ")[-1].strip()
            if symbol:
                api_symbols.append(symbol)
    called_api_symbols = sorted(
        symbol for symbol in set(api_symbols) if re.search(rf"\b{re.escape(symbol)}\s*\(", source)
    )
    return {
        "file": relative,
        "exists": True,
        "bytes": path.stat().st_size,
        "lines": len(source.splitlines()),
        "sha256": sha256(path),
        "headings": visible_text(source, r"h[1-4]"),
        "button_text": visible_text(source, r"(?:button|UiButton)"),
        "api_modules": sorted(set(api_modules)),
        "api_symbols": sorted(set(api_symbols)),
        "called_api_symbols": called_api_symbols,
        "api_paths": sorted(set(re.findall(r"['\"](/api/[^'\"]+)['\"]", source))),
        "route_targets": sorted(
            set(re.findall(r"(?:router\.(?:push|replace)|to)\s*[:=]?\s*['\"]([^'\"]+)", source))
        ),
        "interaction_counts": {
            "buttons": len(re.findall(r"<(?:button|UiButton)\b", source)),
            "inputs": len(re.findall(r"<(?:input|textarea|select)\b", source)),
            "click_handlers": len(re.findall(r"(?:@click|@submit|@change)=", source)),
            "api_calls": len(called_api_symbols)
            + len(re.findall(r"\b(?:api|axios|client)\.(?:get|post|put|patch|delete)\s*\(", source)),
        },
    }


def keyword_evidence(source: str, capability: str) -> dict[str, Any]:
    keywords = [word for word in re.findall(r"[\u4e00-\u9fff]{2,}|[A-Za-z][A-Za-z_-]{2,}", capability)]
    matched = [word for word in keywords if word in source]
    return {"capability": capability, "matched_keywords": matched, "supported_by_text": bool(matched)}


def build_baseline(root: Path, current_root: Path | None = None) -> dict[str, Any]:
    pages: list[dict[str, Any]] = []
    for page in PROTECTED_PAGES:
        evidence = file_evidence(root, page["view"])
        source = read_text(root / page["view"]) if evidence.get("exists") else ""
        pages.append(
            {
                **page,
                "file_evidence": evidence,
                "current_file_evidence": file_evidence(current_root, page["view"]) if current_root else None,
                "capability_evidence": [keyword_evidence(source, item) for item in page["required_capabilities"]],
            }
        )
    supporting = [file_evidence(root, relative) for relative in SUPPORTING_FILES]
    return {
        "schema_version": "1.0",
        "baseline_label": "7.20 original submission source",
        "source_root": str(root.resolve()),
        "current_root": str(current_root.resolve()) if current_root else None,
        "protected_page_count": len(pages),
        "pages": pages,
        "supporting_files": supporting,
        "rules": {
            "preserve_content_richness": True,
            "allowed_changes": ["layout", "copy hierarchy", "visual density", "entry grouping", "closed-loop links"],
            "forbidden_changes": [
                "delete substantive learning capability",
                "replace protected page with an empty summary",
                "force users into an independent technical workbench",
            ],
        },
    }


def render_markdown(report: dict[str, Any]) -> str:
    lines = [
        "# 7.20 原版四个核心页面保护基线",
        "",
        "> 本文件由 `scripts/build_fusion_protection_baseline.py` 生成。它是 F0 保护证据，不是对当前复杂版本已经完成融合的宣称。",
        "",
        f"- 基线源码：`{report['source_root']}`",
        f"- 保护页面：{report['protected_page_count']} 个",
        "- 使用规则：保留原有实质学习价值，允许排版减负，必须增加闭环联动；不得删空或另起技术工作台。",
        "",
        "## 页面事实",
        "",
        "| 页面 | 原版行数 | 当前行数 | 原版按钮/输入/点击 | 当前按钮/输入/点击 | 原版 API 函数 | 当前 API 函数 |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for page in report["pages"]:
        evidence = page["file_evidence"]
        counts = evidence.get("interaction_counts", {})
        current = page.get("current_file_evidence") or {}
        current_counts = current.get("interaction_counts", {})
        lines.append(
            f"| {page['title']} `{page['route']}` | {evidence.get('lines', 0)} | {current.get('lines', '-')} | "
            f"{counts.get('buttons', 0)}/{counts.get('inputs', 0)}/{counts.get('click_handlers', 0)} | "
            f"{current_counts.get('buttons', '-')}/{current_counts.get('inputs', '-')}/{current_counts.get('click_handlers', '-')} | "
            f"{counts.get('api_calls', 0)} | {current_counts.get('api_calls', '-')} |"
        )
    for page in report["pages"]:
        evidence = page["file_evidence"]
        lines.extend(
            [
                "",
                f"## {page['title']} `{page['route']}`",
                "",
                f"- 文件哈希：`{evidence.get('sha256', 'MISSING')}`",
                f"- 原版必须保留：{'、'.join(page['required_capabilities'])}",
                f"- 允许减负：{'、'.join(page['allowed_reduction'])}",
                f"- 必须增强：{'、'.join(page['required_enhancement'])}",
                f"- 原版标题线索：{'、'.join(evidence.get('headings', [])) or '未解析到标准标题标签'}",
                f"- 原版按钮线索：{'、'.join(evidence.get('button_text', [])[:20]) or '主要按钮由动态模板生成'}",
                f"- 原版 API 模块线索：{'、'.join(evidence.get('api_modules', [])) or '通过集中 API 导入'}",
                f"- 原版 API 函数线索：{'、'.join(evidence.get('called_api_symbols', [])) or '未解析到直接调用'}",
                "",
                "### F0 保护门禁",
                "",
                "1. 修改前后必须保留上述能力，不能只保留统计摘要。",
                "2. 主要动作仍须在该页面或自然的学习空间子模块内完成。",
                "3. 每项新增能力必须说明它如何连接诊断、路径、资源、练习/实操、反馈或复习。",
                "4. 页面需保留加载、空、失败、保存/恢复和深链状态。",
            ]
        )
    lines.extend(
        [
            "",
            "## 支撑文件",
            "",
            "| 文件 | 行数 | SHA-256 |",
            "|---|---:|---|",
        ]
    )
    for item in report["supporting_files"]:
        if item.get("exists"):
            lines.append(f"| `{item['file']}` | {item['lines']} | `{item['sha256']}` |")
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--current", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    report = build_baseline(
        args.baseline.resolve(), args.current.resolve() if args.current else None
    )
    (args.output / "protected_pages_baseline.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (args.output / "protected_pages_baseline.md").write_text(render_markdown(report), encoding="utf-8")
    print(json.dumps({"pages": len(report["pages"]), "supporting_files": len(report["supporting_files"])}, ensure_ascii=False))


if __name__ == "__main__":
    main()
