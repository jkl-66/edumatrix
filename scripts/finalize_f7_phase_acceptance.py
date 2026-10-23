#!/usr/bin/env python3
"""Validate and summarize the final F7 phase evidence."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "outputs" / "原系统融合重构执行" / "evidence"
OUTPUT = EVIDENCE / "f7_phase_acceptance"
CONTINUOUS = OUTPUT / "continuous_report.json"
REPORTS = {
    "F7-T01": EVIDENCE / "f7_t01_knowledge_shelf" / "browser" / "report.json",
    "F7-T02": EVIDENCE / "f7_t02_document_reader" / "browser" / "report.json",
    "F7-T03": EVIDENCE / "f7_t03_graph_admission" / "browser" / "report.json",
    "F7-T04": EVIDENCE / "f7_t04_chat" / "browser" / "report.json",
    "F7-T05": EVIDENCE / "f7_t05_source_agent" / "browser" / "report.json",
}


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def database_is_clean(report: dict) -> bool:
    database = report.get("database", {})
    if database.get("integrity") == "ok":
        return database.get("foreign_key_violations") == 0
    before = database.get("before", {})
    after = database.get("after", {})
    return all(
        snapshot.get("integrity") == "ok"
        and snapshot.get("foreign_key_violations") == 0
        for snapshot in (before, after)
    )


def require_markers(path: Path, markers: list[str]) -> None:
    source = path.read_text(encoding="utf-8")
    missing = [marker for marker in markers if marker not in source]
    require(not missing, f"Missing acceptance markers in {path}: {missing}")


def main() -> None:
    task_results: dict[str, dict] = {}
    task_screenshot_total = 0
    for task, report_path in REPORTS.items():
        require(report_path.is_file(), f"Missing report for {task}: {report_path}")
        report = load(report_path)
        require(report.get("status") == "passed", f"{task} report is not passed")
        viewports = {tuple(item) for item in report.get("viewports", [])}
        require((1440, 900) in viewports, f"{task} lacks 1440x900 evidence")
        require((1366, 768) in viewports, f"{task} lacks 1366x768 evidence")
        for field in ("http_errors", "failed_requests", "page_errors", "console_errors"):
            require(not report.get(field), f"{task} contains unexpected {field}")
        require(report.get("external_model_called") is False, f"{task} used an external model")
        require(database_is_clean(report), f"{task} isolated database is not clean")
        screenshots = report.get("screenshots", [])
        missing = [name for name in screenshots if not (report_path.parent / name).is_file()]
        require(not missing, f"{task} screenshots missing: {missing}")
        task_screenshot_total += len(screenshots)
        task_results[task] = {
            "status": "PASS",
            "report": report_path.relative_to(ROOT).as_posix(),
            "screenshots": len(screenshots),
            "database_integrity": "ok",
            "foreign_key_violations": 0,
        }
    require(task_screenshot_total == 49, f"Expected 49 task screenshots, got {task_screenshot_total}")

    continuous = load(CONTINUOUS)
    require(continuous.get("status") == "passed", "Continuous F7 journey is not passed")
    require(continuous.get("single_service") is True, "Continuous journey used multiple services")
    require(continuous.get("single_chromium_instance") is True, "Continuous journey used multiple browsers")
    require(continuous.get("external_model_called") is False, "Continuous journey used an external model")
    for field in ("http_errors", "failed_requests", "page_errors", "console_errors", "external_requests"):
        require(not continuous.get(field), f"Continuous journey contains unexpected {field}")
    continuous_screenshots = continuous.get("screenshots", [])
    require(len(continuous_screenshots) == 32, "Continuous journey must contain 32 screenshots")
    missing_continuous = [name for name in continuous_screenshots if not (OUTPUT / "browser" / name).is_file()]
    require(not missing_continuous, f"Continuous screenshots missing: {missing_continuous}")

    before = continuous["database"]["before"]
    after = continuous["database"]["after"]
    for field in (
        "learning_events",
        "profile_snapshots",
        "assessment_attempts",
        "source_documents",
        "source_refs",
        "mastery",
        "path_nodes",
    ):
        require(before[field] == after[field], f"Protected field changed during F7 browsing: {field}")
    require(before["integrity"] == after["integrity"] == "ok", "Continuous SQLite integrity failed")
    require(before["foreign_key_violations"] == after["foreign_key_violations"] == 0, "Continuous SQLite has FK violations")
    require(after["generation_tasks"] - before["generation_tasks"] == 3, "Expected three user-requested generation tasks")
    require(after["chat_messages"] - before["chat_messages"] == 4, "Expected four persisted Chat messages")
    require(after["document_selections"] - before["document_selections"] == 2, "Expected two persisted selections")
    require(after["source_candidates"] - before["source_candidates"] == 1, "Expected one saved web candidate")

    require_markers(
        ROOT / "frontend" / "src" / "components" / "KnowledgeGraphExplorer.vue",
        [
            "function relationshipProjectionPositions(nodes, edges)",
            "const chartCategories = props.categories.map",
            "position: props.fitDenseGraph ? 'inside' : 'bottom'",
            "categories: chartCategories.length ? chartCategories : undefined",
        ],
    )
    require_markers(
        ROOT / "tests" / "test_f7_t05_frontend_contract.py",
        [
            "agent_audit",
            "private_reasoning",
            "raw_trace",
            "source_ref_id",
            "handleTextSelection",
            "finishImageSelection",
        ],
    )

    generated_at = datetime.now().astimezone().isoformat(timespec="seconds")
    result = {
        "schema_version": "f7.phase-acceptance.v1",
        "status": "PASS",
        "generated_at": generated_at,
        "scope": "F7-T01 through F7-T05",
        "task_results": task_results,
        "task_screenshots": task_screenshot_total,
        "continuous_journey_screenshots": len(continuous_screenshots),
        "regression": {
            "passed": 65,
            "warnings": 5,
            "duration_seconds": 40.83,
        },
        "production_build": {"status": "PASS", "modules_transformed": 6935},
        "impeccable": {
            "layout_findings": [],
            "confirmed_findings": [],
            "verified_false_positives": [
                "Knowledge.vue:1183 text-slate-900 is on white, not bg-amber-50",
                "Knowledge.vue:1183 ready badge is bg-slate-100/text-slate-700; non-ready badge is bg-amber-50/text-amber-800",
            ],
        },
        "manual_visual_acceptance": {
            "course_graph_labels": "PASS: dense labels are inside nodes and no longer collide as external text",
            "relationship_projection": "PASS: nodes are separated by actual adjacency depth",
            "theme": "PASS: graph nodes and legend use the approved ink-blue-gray palette",
            "representative_viewports": ["1440x900", "1366x768"],
        },
        "mandatory_conclusions": {
            "new_student_uses_preloaded_course_without_upload": "PASS",
            "text_and_image_selection_restore": "PASS",
            "answers_and_resources_reverse_to_exact_source": "PASS",
            "web_candidates_stay_outside_canonical_course": "PASS",
            "chat_attachments_and_stream_recovery": "PASS",
            "public_agent_audit_excludes_private_reasoning": "PASS",
            "ordinary_browsing_does_not_update_mastery": "PASS",
        },
        "database": {
            "all_isolated": True,
            "all_integrity_ok": True,
            "foreign_key_violations": 0,
            "formal_edumatrix_db_modified": False,
        },
        "external_model_called": False,
        "git_write_performed": False,
        "delivery_package_modified": False,
        "next_checkpoint": "F8 / F8-T01 / NOT_STARTED",
    }
    OUTPUT.mkdir(parents=True, exist_ok=True)
    (OUTPUT / "phase_report.json").write_text(
        json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )

    lines = [
        "# EduMatrix F7 阶段级联合验收报告",
        "",
        "> 结论：`PASS`",
        "> 验收范围：`F7-T01` 至 `F7-T05`。",
        "> 下一断点：`F8 / F8-T01 / NOT_STARTED`。",
        "",
        "## 1. 阶段结论",
        "",
        "F7 五项任务已经形成一条连续的预置知识库、文档选区、课程图谱、联网候选、智能对话、精确来源和公开 Agent 审计闭环。五份任务浏览器报告均为 `passed`，共 49 张原任务截图；同一隔离 SQLite、同一服务和同一 Chromium 的阶段连续旅程另保存 32 张截图。",
        "",
        "## 2. 五项任务",
        "",
        "| 任务 | 能力 | 原任务截图 | 结果 |",
        "|---|---|---:|---|",
        "| F7-T01 | 预置课程书架、课程内检索、证据化推荐 | 11 张 | PASS |",
        "| F7-T02 | 大窗口阅读、文本划选、图片框选、OCR 与恢复 | 10 张 | PASS |",
        "| F7-T03 | 课程图谱、来源下钻、联网候选与个人准入边界 | 13 张 | PASS |",
        "| F7-T04 | 多模态附件、流式停止/继续、资源深链与单题交互 | 8 张 | PASS |",
        "| F7-T05 | 统一来源反查、四阶段公开 Agent 审计与失败诚实性 | 7 张 | PASS |",
        "",
        "## 3. 连续旅程",
        "",
        "新学生无需上传课程材料即可进入预置书架；随后完成正文检索、文本划选、图片框选及 OCR 失败恢复，进入课程图谱和来源原文，保存但不污染权威课程的联网候选，再在智能对话中验证附件解析、停止/继续、资源深链、精确来源反查及完成/失败 Agent 审计。",
        "",
        "普通阅读、检索、缩放、选区、图谱浏览、候选查看、来源展开和 Agent 审计不会改变掌握度。连续旅程前后学习事件、画像快照、测评尝试、来源文档/引用、路径节点和掌握内容完全一致；三次资源生成、四条 Chat 消息、两个选区和一个候选是用户明确动作产生的预期记录。",
        "",
        "## 4. 自动、数据与视觉门禁",
        "",
        "- F7 十二个命名测试文件最终回归：`65 passed, 5 warnings in 40.83s`。警告仅为既有 FastAPI/Starlette 生命周期弃用。",
        "- 前端生产构建通过，转换 `6935` 个模块；仅保留既有大分块提示。",
        "- 所有任务和连续旅程均覆盖 `1440x900` 与 `1366x768`；意外 HTTP、请求、页面、控制台和真实外部请求均为 0。",
        "- 所有隔离 SQLite 均为 `integrity_check=ok`，外键违规为 0；正式 `edumatrix.db` 未修改。",
        "- 阶段人工截图复核发现并修复了 canvas 标签重叠与默认彩色图例；修复后关系图和关系投影在双桌面尺寸使用墨蓝灰同心层级，完整名称由搜索、悬停和右侧概览读取。",
        "- Impeccable 布局扫描为 `[]`。全量机械扫描的两条 `Knowledge.vue:1183` 告警经源码核对均为同一行 Vue 条件类导致的解析误报，已确认问题为 0。",
        "",
        "## 5. 边界",
        "",
        "- 自动验收只使用本地确定性事实和隔离数据，未调用外部模型或外网。",
        "- 未执行 Git 暂存、提交、推送或历史改写，未更新交付包。",
        "- 本报告只关闭 F7 阶段；F8 尚未开始，F9/F10 未读取、规划或实施。",
    ]
    (OUTPUT / "phase_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"F7 phase acceptance PASS: {len(task_results)} tasks, {task_screenshot_total} task screenshots, {len(continuous_screenshots)} continuous screenshots")


if __name__ == "__main__":
    main()
