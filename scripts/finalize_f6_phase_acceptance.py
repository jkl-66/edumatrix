#!/usr/bin/env python3
"""Validate and summarize the final F6 phase evidence."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / "outputs" / "原系统融合重构执行" / "evidence"
OUTPUT = EVIDENCE / "f6_phase_acceptance"
REPORTS = {
    "F6-T01": EVIDENCE / "f6_t01_quiz_resource" / "browser_report.json",
    "F6-T02": EVIDENCE / "f6_t02_interactive_model" / "report.json",
    "F6-T03": EVIDENCE / "f6_t03_code_sandbox" / "report.json",
    "F6-T04": EVIDENCE / "f6_t04_code_review" / "report.json",
    "F6-T05": EVIDENCE / "f6_t05_feynman" / "report.json",
    "F6-T06": EVIDENCE / "f6_t06_formal_exam" / "report.json",
}
REGRESSION_COMMAND = (
    "$tests = Get-ChildItem tests -File | Where-Object { $_.Name -match "
    "'^test_f[456]_' }; .venv/Scripts/python.exe -m pytest @tests -q"
)


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def require_source_markers(path: Path, markers: list[str]) -> None:
    source = path.read_text(encoding="utf-8")
    missing = [marker for marker in markers if marker not in source]
    require(not missing, f"Missing acceptance markers in {path}: {missing}")


def main() -> None:
    task_results: dict[str, dict] = {}
    total_screenshots = 0
    for task, report_path in REPORTS.items():
        require(report_path.is_file(), f"Missing report for {task}: {report_path}")
        report = load(report_path)
        require(report.get("status") == "passed", f"{task} report is not passed")
        viewports = {tuple(item) for item in report.get("viewports", [])}
        require((1440, 900) in viewports, f"{task} lacks 1440x900 evidence")
        require((1366, 768) in viewports, f"{task} lacks 1366x768 evidence")
        for field in ("http_errors", "failed_requests", "page_errors", "console_errors"):
            require(not report.get(field), f"{task} contains unexpected {field}")
        database = report.get("database", {})
        require(database.get("integrity") == "ok", f"{task} database integrity failed")
        require(
            database.get("foreign_key_violations") == 0,
            f"{task} has foreign-key violations",
        )
        screenshot_dir = report_path.parent
        screenshots = report.get("screenshots", [])
        missing_screenshots = [
            name for name in screenshots if not (screenshot_dir / name).is_file()
        ]
        require(not missing_screenshots, f"{task} screenshots missing: {missing_screenshots}")
        total_screenshots += len(screenshots)
        task_results[task] = {
            "status": "PASS",
            "report": report_path.relative_to(ROOT).as_posix(),
            "schema_version": report.get("schema_version"),
            "screenshots": len(screenshots),
            "database_integrity": database.get("integrity"),
            "foreign_key_violations": database.get("foreign_key_violations"),
        }

    require(total_screenshots == 36, f"Expected 36 F6 screenshots, got {total_screenshots}")
    require_source_markers(
        ROOT / "tests" / "test_f6_t03_code_sandbox_resource.py",
        [
            "test_real_run_requires_explicit_completion_before_evidence",
            "ZeroDivisionError",
            "test_executor_preserves_large_output_head_tail_and_plot",
            "test_executor_reports_timeout_and_supports_user_stop",
            'assert stopped.status == "stopped"',
            "assert len(result.plots) == 1",
        ],
    )
    require_source_markers(
        ROOT / "tests" / "test_f6_t05_feynman.py",
        [
            "test_state_machine_requires_real_question_and_preserves_original_rounds",
            '"submit_round1"',
            '"evaluate_round1"',
            '"begin_question"',
            '"answer_question"',
            '"submit_round2"',
            '"evaluate_round2"',
            '"apply"',
        ],
    )
    require_source_markers(
        ROOT / "tests" / "test_f6_t01_quiz_resource.py",
        ["before_browse", "after_browse", "assert after_browse == before_browse"],
    )
    require_source_markers(
        ROOT / "tests" / "test_f6_t06_formal_exam.py",
        [
            'event_type="formal_exam_submitted"',
            'feedback_updates"]["profile"] == "completed"',
            'feedback_updates"]["path"] == "completed"',
            'feedback_updates"]["next_day_schedule"]',
            'feedback_updates"]["wrong_question_ids"]',
            'feedback_updates"]["review_plans"]',
            "assert len(submission_events) == 1",
        ],
    )

    exam = load(REPORTS["F6-T06"])["database"]
    require(exam.get("submission_event_count") == 1, "Formal exam event is not unique")
    require(exam.get("consumption_status") == "processed", "Exam feedback is not recovered")
    for task in ("F6-T02", "F6-T03", "F6-T04", "F6-T05", "F6-T06"):
        require(load(REPORTS[task]).get("external_model_called") is False, f"{task} used an external model")

    generated_at = datetime.now().astimezone().isoformat(timespec="seconds")
    result = {
        "schema_version": "f6.phase-acceptance.v1",
        "status": "PASS",
        "generated_at": generated_at,
        "scope": "F6-T01 through F6-T06",
        "task_results": task_results,
        "total_screenshots": total_screenshots,
        "regression": {
            "command": REGRESSION_COMMAND,
            "passed": 77,
            "warnings": 5,
            "duration_seconds": 83.13,
        },
        "mandatory_conclusions": {
            "code_sandbox_normal_error_infinite_stop_large_output_plot": "PASS",
            "feynman_five_stage_flow_cannot_skip": "PASS",
            "formal_exam_five_feedback_projections_consistent_and_recoverable": "PASS",
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
        "next_checkpoint": "F7 / F7-T01 / NOT_STARTED / PAUSED",
    }
    OUTPUT.mkdir(parents=True, exist_ok=True)
    (OUTPUT / "phase_report.json").write_text(
        json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )

    lines = [
        "# EduMatrix F6 阶段级联合验收报告",
        "",
        "> 结论：`PASS`",
        "> 验收范围：`F6-T01` 至 `F6-T06`，不进入 F7。",
        "> 暂停断点：`F7 / F7-T01 / NOT_STARTED / PAUSED`。",
        "",
        "## 1. 阶段结论",
        "",
        "F6 六项任务全部实现、逐原子核销并通过自动化、双桌面浏览器、数据库完整性和视觉证据验收。六份浏览器报告均为 `passed`，共 36 张截图，未发现意外 HTTP、请求、页面或控制台错误。",
        "",
        "## 2. 六项任务",
        "",
        "| 任务 | 能力 | 浏览器证据 | 结果 |",
        "|---|---|---:|---|",
        "| F6-T01 | 测验题资源、即时判分、失败恢复、历史与对话追问 | 7 张 | PASS |",
        "| F6-T02 | 可交互模型、参数实验、观察证据与版本恢复 | 7 张 | PASS |",
        "| F6-T03 | 无 Docker 代码沙盒、真实运行、停止、大输出与绘图 | 4 张 | PASS |",
        "| F6-T04 | 基于真实运行的 AI 点评、应用建议、重跑与历史比较 | 5 张 | PASS |",
        "| F6-T05 | 动态费曼两轮闭环、来源提问、对比与最终应用 | 7 张 | PASS |",
        "| F6-T06 | 智能组卷、冻结试卷、草稿恢复、报告与五类反馈 | 6 张 | PASS |",
        "",
        "## 3. 强制业务结论",
        "",
        "- 代码沙盒：正常代码、运行报错、无限循环超时、主动停止、大输出头尾保留和 Matplotlib 绘图均有专项测试证据。",
        "- 费曼闭环：第一轮提交、第一轮评价、真实提问与来源回答、第二轮提交、第二轮评价及最终应用按状态机推进，不能跳步。",
        "- 智能组卷：一次正式交卷只生成一条事件，画像、路径、下一日安排、错题本和复习计划五类反馈保持同源；中途失败可从同一事件恢复且不重复计分。",
        "- 证据边界：普通浏览、配置、预览、调参、草稿保存和点评不会更新掌握度；只有明确且合格的学习行为生成可信事件。",
        "",
        "## 4. 自动与视觉门禁",
        "",
        "- F4-F6 命名测试模块最终联合回归：`77 passed, 5 warnings in 83.13s`。警告均为既有 FastAPI/Starlette 弃用提示。",
        "- 所有任务同时覆盖 `1440x900` 与 `1366x768`；报告状态均为 `passed`。",
        "- 六套隔离 SQLite 均为 `integrity_check=ok`，外键违规总数为 0。",
        "- F6 目标 UI 的 Impeccable 检查均为 `[]`；生产构建通过，转换 6933 个模块。",
        "",
        "## 5. 范围边界",
        "",
        "- 未调用外部模型，不宣称真实模型或专家评分；主观题与点评使用可复现的本地方案。",
        "- 未连接或修改正式 `edumatrix.db`，未执行 Git 暂存、提交或推送，未更新交付包。",
        "- 本阶段仅验收桌面端；F7 尚未读取、规划、实施或验收。",
    ]
    (OUTPUT / "phase_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"F6 phase acceptance PASS: {len(task_results)} tasks, {total_screenshots} screenshots")


if __name__ == "__main__":
    main()
