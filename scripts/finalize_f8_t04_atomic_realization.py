#!/usr/bin/env python3
"""Finalize F8-T04 after regression, browser, data, and visual acceptance."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LEDGER_DIR = (
    ROOT
    / "outputs"
    / "原系统融合重构执行"
    / "evidence"
    / "context_recovery"
    / "atomic_requirement_ledgers"
    / "EDUMATRIX-F5-F8-CONTEXT-SAFE-FUSION-IMPLEMENTATION"
)
EVIDENCE_DIR = (
    ROOT / "outputs" / "原系统融合重构执行" / "evidence" / "f8_t04_profile_history"
)

PRIMARY_IDS = [
    "G19-R01",
    "G19-R02",
    "G19-R03",
    "G19-R04",
    "G19-R05",
    "G19-R06",
    "G19-R07",
    "G19-R08",
    "G20-R03",
]

FINAL_EVIDENCE = [
    "F8-T01 through F8-T04 and navigation protection regression: 49 passed, 5 existing framework deprecation warnings in 9.25s.",
    "Context recovery regression: 20 passed in 1.62s.",
    "Production build: frontend npm run build passed with 6937 modules transformed; only the existing large-chunk advisory remains.",
    "Browser E2E: scripts/e2e_f8_t04_profile_history.py passed with 7 full-size screenshots at 1440x900 and 1366x768.",
    "Visual acceptance: all six measured profile/history/empty surfaces have zero overflow, clipping, sub-14px text, collisions, forbidden theme colors, and gradients; Impeccable detector returned [].",
    "Database acceptance: both learner and empty-account read-only journeys preserved learning events, consumptions, profile snapshots, review plans, assessment attempts, generation tasks, and mastery; integrity_check=ok and foreign-key violations=0.",
    "Boundary acceptance: the browser report records no unexpected HTTP, request, page, console, external-request, or external-model activity; the formal database and delivery packages were not used.",
]


PER_ATOM = {
    "G19-R01": {
        "implementation": [
            "app/profile_summary.py:_event_minutes and build_personal_activity derive today, seven-day, and selected-period minutes only from explicit actual_minutes, duration_minutes, or active_seconds fields.",
            "app/m5_api.py:get_personal_activity and frontend/src/views/ProfileDashboard.vue expose the same owner-scoped period, calculation, and sourceEventIds without creating a second statistic source.",
        ],
        "verification": [
            "tests/test_f8_t04_personal_activity.py::test_duration_heatmap_streak_and_processed_trend_use_only_real_evidence verifies explicit duration accounting and rejects inferred minutes.",
            "The browser report shows 20 minutes today and 25 minutes in seven/30 days, with learner state unchanged before and after browsing.",
        ],
        "visible": "学生在个人中心看到今日20分钟、近7日25分钟和所选周期25分钟，并可展开查看统计周期、口径和18条来源事件；没有明确时长证据时显示0。",
    },
    "G19-R02": {
        "implementation": [
            "app/profile_summary.py:_counts_as_active_learning and build_personal_activity build a fixed 30-day evidence heatmap and current streak from explicit learning activity only.",
            "frontend/src/views/ProfileDashboard.vue renders the returned dates as a stable heatmap grid with event/minute evidence instead of synthetic colors.",
        ],
        "verification": [
            "tests/test_f8_t04_personal_activity.py::test_duration_heatmap_streak_and_processed_trend_use_only_real_evidence verifies active-day and two-day streak calculations.",
            "The populated and empty profile screenshots show respectively a real two-day streak/30-day heatmap and a zero-day/all-empty heatmap.",
        ],
        "visible": "学生看到最近30日真实学习热力图和连续学习2天；空账号保持30个未着色日期格和连续学习0天，不会出现演示色块。",
    },
    "G19-R03": {
        "implementation": [
            "app/dashboard_summary.py:mastery_trend and app/profile_summary.py:build_personal_activity return only processed aggregation mastery points with sourceEventId and occurredAt.",
            "frontend/src/components/LearningTrendChart.vue renders the frozen ink-gray line and an explanatory empty state without an invented area fill.",
        ],
        "verification": [
            "tests/test_f8_t04_personal_activity.py::test_duration_heatmap_streak_and_processed_trend_use_only_real_evidence excludes pending and failed aggregation rows.",
            "tests/test_f8_t04_profile_frontend_contract.py::test_trend_has_real_empty_state_and_no_decorative_area_fill verifies the chart and honest empty state.",
        ],
        "visible": "学生可切换7、30、90天查看由已处理学习事件形成的真实掌握趋势；没有合格聚合结果时只显示原因明确的空态。",
    },
    "G19-R04": {
        "implementation": [
            "app/profile_summary.py:_event_item and build_personal_activity project an owner-scoped, stable, paginated business timeline from DBLearningEvent.",
            "frontend/src/views/History.vue implements course/period/object filters, a central timeline, source detail, and read-only pagination under /profile/history.",
        ],
        "verification": [
            "tests/test_f8_t04_personal_activity.py::test_empty_owner_course_scope_filters_and_pagination_are_honest verifies isolation, filters, and non-overlapping pages.",
            "Browser evidence shows 13 note events across two pages and a populated 18-event timeline; opening, filtering, and pagination leave all protected business counts unchanged.",
        ],
        "visible": "学生可按课程、7/30/90天和学习对象筛选真实历史，在时间线选择记录后查看来源、证据影响与继续动作；第二页仍可找回较早记录。",
    },
    "G19-R05": {
        "implementation": [
            "app/profile_summary.py:build_profile_summary and build_personal_activity expose compact profile sections, deterministic period-report facts, and the next owned learning action.",
            "frontend/src/views/ProfileDashboard.vue keeps the full ten-dimension profile on /profile/learning and presents only compact profile/report entrances in the lower section.",
        ],
        "verification": [
            "tests/test_f8_t04_profile_frontend_contract.py::test_profile_uses_figure_29_reading_order_and_honest_fact_sections verifies the profile-summary/report placement.",
            "The two profile screenshots preserve the lower profile/report region after the statistics and trend/activity sections, while the empty account remains honest.",
        ],
        "visible": "学生在个人中心下方看到简明画像摘要、阶段报告和下一步入口，可进入完整学习画像、路径或复习对象，而不是在个人中心复制整页画像。",
    },
    "G19-R06": {
        "implementation": [
            "frontend/src/views/ProfileDashboard.vue follows figure 29's identity/statistics, trend/activity, profile/report reading order; History.vue uses a stable filter/timeline/detail layout.",
            "ProfileDashboard.vue, History.vue, and LearningTrendChart.vue use the frozen mist-white, white, ink-blue, and gray desktop system with progressive details and one primary action per state.",
        ],
        "verification": [
            "tests/test_f8_t04_profile_frontend_contract.py::test_profile_surfaces_keep_the_frozen_light_visual_contract and the Impeccable detector reject forbidden theme and layout regressions.",
            "Manual review of all seven full-size screenshots confirms readable hierarchy, no card nesting, stable columns, and coherent loading/empty/complete layouts at both desktop sizes.",
        ],
        "visible": "个人中心先呈现身份与关键事实，再呈现趋势和动态，最后呈现画像与报告；历史页按筛选、时间线、详情阅读，内容丰富但无需先理解内部技术术语。",
    },
    "G19-R07": {
        "implementation": [
            "app/profile_summary.py centralizes duration, heatmap, trend, activity, profile, and report projections and attaches period, calculation, and sourceEventIds to the returned facts.",
            "ProfileDashboard.vue and History.vue consume only this projection and render independent empty/error states instead of local mock numbers or random chart points.",
        ],
        "verification": [
            "tests/test_f8_t04_personal_activity.py::test_empty_owner_course_scope_filters_and_pagination_are_honest verifies zero values, empty trend/history, course scope, and owner isolation.",
            "The empty-account E2E preserves all six protected business counts at zero and displays no fake growth, activity, or heatmap evidence.",
        ],
        "visible": "个人中心的分钟、连续天数、热力图、趋势、动态和报告都能回查来源；新账号明确显示0和空态，不用好看的假数据装饰页面。",
    },
    "G19-R08": {
        "implementation": [
            "app/profile_summary.py:_event_target maps only supported owned business-object types to controlled internal routes and keeps unavailable objects auditable.",
            "ProfileDashboard.vue and History.vue use the server target for one continue action while retaining the event summary and source state when no target is available.",
        ],
        "verification": [
            "tests/test_f8_t04_personal_activity.py::test_activity_deep_links_are_controlled_and_withdrawn_artifacts_stay_auditable rejects arbitrary targets and preserves withdrawn evidence.",
            "The E2E opens the selected accepted-answer event at the owned review knowledge point with course, month, and date context, and proves that the round trip creates no learning write.",
        ],
        "visible": "学生可从动态、报告或画像摘要安全返回对应知识点、资源、笔记、测评、复习、路径或完整画像；来源失效时仍看到记录说明而不是跳到未知地址。",
    },
    "G20-R03": {
        "implementation": [
            "frontend/src/views/ProfileDashboard.vue remains the /profile primary entry, History.vue remains the /profile/history child, and the existing /history compatibility redirect is preserved.",
            "The profile/history rewrite stays inside the single AppShell and does not add a ninth student primary entry or duplicate profile, path, review, resource, chat, or knowledge surfaces.",
        ],
        "verification": [
            "tests/test_f8_t04_profile_frontend_contract.py::test_student_navigation_remains_exactly_eight_primary_entries and tests/test_r1_navigation_contract.py verify the approved eight-entry shell and role boundaries.",
            "The browser screenshots preserve the same eight student entries and active Personal Center state while profile/history/source deep links remain in their owning spaces.",
        ],
        "visible": "个人中心仍是八个学生一级入口之一，历史只作为个人中心深链；学生可返回其他所属空间，不会遇到第二套侧栏、技术工作台或重复功能入口。",
    },
}


def unique(values: list[str], additions: list[str]) -> list[str]:
    return list(dict.fromkeys([*values, *additions]))


def validate_report() -> dict:
    report_path = EVIDENCE_DIR / "report.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    if report.get("status") != "passed":
        raise RuntimeError("F8-T04 browser report is not passed")
    screenshots = report.get("screenshots") or []
    if len(screenshots) != 7 or any(
        not (EVIDENCE_DIR / "browser" / name).is_file() for name in screenshots
    ):
        raise RuntimeError("F8-T04 screenshot evidence is incomplete")
    if not report.get("checks") or not all(report["checks"].values()):
        raise RuntimeError("F8-T04 browser checks are incomplete")
    for key in ("http_errors", "failed_requests", "page_errors", "console_errors", "external_requests"):
        if report.get(key) != []:
            raise RuntimeError(f"F8-T04 browser report contains {key}")
    if report.get("external_model_called") is not False:
        raise RuntimeError("F8-T04 browser report used an external model")

    expected_visual = {
        "profile_1440x900",
        "history_1440x900",
        "profile_1366x768",
        "history_1366x768",
        "empty_profile_1440x900",
        "empty_history_1440x900",
    }
    visual = report.get("visual") or {}
    if set(visual) != expected_visual:
        raise RuntimeError("F8-T04 visual evidence is incomplete")
    for result in visual.values():
        for key in ("clipped", "smallText", "collisions", "forbiddenThemeHits", "gradients"):
            if result.get(key) != []:
                raise RuntimeError(f"F8-T04 visual report contains {key}")
        if result.get("pageOverflow") or result.get("rootOverflow"):
            raise RuntimeError("F8-T04 visual report contains overflow")

    database = report.get("database") or {}
    for prefix in ("learner", "empty"):
        before = database.get(f"{prefix}_before")
        after = database.get(f"{prefix}_after")
        if before != after:
            raise RuntimeError(f"F8-T04 {prefix} browsing changed business state")
        if (after or {}).get("integrity") != "ok" or (after or {}).get("foreign_key_violations") != 0:
            raise RuntimeError(f"F8-T04 {prefix} database integrity failed")
    return report


def main() -> None:
    report = validate_report()
    matches = list(LEDGER_DIR.glob("F8-T04_*.json"))
    if len(matches) != 1:
        raise RuntimeError(f"Expected one F8-T04 ledger, found {len(matches)}")
    ledger_path = matches[0]
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    entries = {entry["atomic_requirement_id"]: entry for entry in ledger["entries"]}
    if set(entries) != set(PRIMARY_IDS) or any(entries[item]["role"] != "primary" for item in PRIMARY_IDS):
        raise RuntimeError("F8-T04 atomic identity no longer matches the verified contract")

    for batch in ledger.get("execution_batches", []):
        batch["verification"] = unique(list(batch.get("verification") or []), FINAL_EVIDENCE)
        batch["status"] = "VERIFIED"

    for atom_id in PRIMARY_IDS:
        realization = entries[atom_id]["realization"]
        atom = PER_ATOM[atom_id]
        realization["implementation_evidence"] = unique(
            list(realization.get("implementation_evidence") or []), atom["implementation"]
        )
        realization["verification_evidence"] = unique(
            list(realization.get("verification_evidence") or []),
            [f"{atom_id} final verification: {item}" for item in atom["verification"]]
            + FINAL_EVIDENCE,
        )
        realization["user_visible_result"] = atom["visible"]
        realization["compatibility_or_defer_rationale"] = (
            "无延期。实现复用既有身份、学习事件、画像、路径、复习、资源和路由事实源，"
            "普通浏览保持只读。"
        )
        realization["status"] = "IMPLEMENTED_AND_VERIFIED"

    ledger["final_acceptance"] = {
        "status": "VERIFIED",
        "report": (EVIDENCE_DIR / "report.json").relative_to(ROOT).as_posix(),
        "screenshots": report["screenshots"],
        "primary_atoms": len(PRIMARY_IDS),
        "related_atoms": 0,
        "regression": "49 passed",
        "context_recovery": "20 passed",
        "frontend_build_modules": 6937,
        "external_model_called": False,
        "formal_database_modified": False,
        "git_write_operation_performed": False,
        "impeccable_detector": "[]",
    }
    temporary = ledger_path.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(ledger, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    temporary.replace(ledger_path)
    print(
        json.dumps(
            {
                "status": "FINALIZED",
                "task": "F8-T04",
                "primary": len(PRIMARY_IDS),
                "related": 0,
                "screenshots": len(report["screenshots"]),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
