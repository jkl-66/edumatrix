"""Chromium acceptance for automatic entry-diagnostic coverage sizing."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import e2e_entry_diagnostic_quality as base


TASK_DIR = Path("outputs/原系统融合重构执行/evidence/custom_tasks/ENTRY-DIAGNOSTIC-KNOWLEDGE-COUNT-01")
BASE_QUESTION_COUNT = 15
EFFECTIVE_QUESTION_COUNT = 20

base.EVIDENCE = TASK_DIR
base.OUTPUT_DIR = TASK_DIR / "browser"
base.DB_PATH = TASK_DIR / "browser" / "entry_diagnostic_knowledge_count.sqlite3"
base.PORT = 8941
base.BASE_URL = f"http://127.0.0.1:{base.PORT}"
base.QUESTION_COUNT = EFFECTIVE_QUESTION_COUNT
base.USERNAME = "entry_knowledge_count_20260905"
base.PASSWORD = "EntryKnowledgeCount-2026!"


def create_blueprint_with_default_size(page, report):
    """Select the UI default (15) while keeping the audit expectation at 20."""
    page.goto(
        f"{base.BASE_URL}/workspace/assessment/entry?course_id={base.COURSE_ID}",
        wait_until="domcontentloaded",
        timeout=60_000,
    )
    page.get_by_test_id("entry-diagnostic").wait_for(state="visible", timeout=60_000)
    page.get_by_test_id("diagnostic-overview").wait_for(state="visible", timeout=60_000)
    page.get_by_label("诊断题目数量").select_option(str(BASE_QUESTION_COUNT))
    page.wait_for_function(
        "() => { const button = document.querySelector('[data-testid=\"generate-diagnostic\"]'); return button && !button.disabled; }",
        timeout=60_000,
    )
    report["checks"]["preflight_adjustment"] = page.evaluate(
        "() => ({requested: document.body.innerText.includes('当前课程知识点较多'), text: document.querySelector('[data-testid=diagnostic-overview]')?.innerText || ''})"
    )
    base.capture(page, report, "1440x900-01-preflight-adjusted.png", "entry-diagnostic")
    with page.expect_response(
        lambda response: response.url.endswith("/api/v1/diagnostics/blueprints") and response.status == 201,
        timeout=300_000,
    ) as response_info:
        page.get_by_test_id("generate-diagnostic").click()
    blueprint = response_info.value.json()["blueprint"]
    page.get_by_test_id("diagnostic-ready").wait_for(state="visible", timeout=60_000)
    report["checks"]["generation"] = {
        "requested_question_count": BASE_QUESTION_COUNT,
        "question_count": blueprint["questionCount"],
        "coverage_count": len(blueprint.get("knowledgePointCoverage") or []),
        "coverage_gap": blueprint.get("coverageContract", {}).get("coverageGap", []),
        "question_count_adjusted": blueprint.get("reviewDecision", {}).get("questionCountAdjusted"),
    }
    base.capture(page, report, "1440x900-02-generated-ready-adjusted.png", "entry-diagnostic")
    return blueprint


def main() -> int:
    original_create = base.create_blueprint
    original_question_count = base.QUESTION_COUNT
    base.create_blueprint = create_blueprint_with_default_size
    try:
        # The shared runner handles isolated seeding, session entry, report audits,
        # second desktop viewport and formal DB immutability checks.
        return base.main()
    finally:
        base.create_blueprint = original_create
        base.QUESTION_COUNT = original_question_count


if __name__ == "__main__":
    raise SystemExit(main())
