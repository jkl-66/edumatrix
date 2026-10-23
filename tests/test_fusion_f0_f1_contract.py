from __future__ import annotations

import json
import re
from pathlib import Path


ROOT = Path(__file__).parents[1]
FRONTEND = ROOT / "frontend" / "src"
EVIDENCE = ROOT / "outputs" / "原系统融合重构执行" / "evidence"


def _source(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8-sig")


def test_router_declares_each_approved_target_route_once():
    source = _source("frontend/src/router/index.js")
    block = re.search(r"export const TARGET_ROUTE_PATHS = \[(.*?)\n\]", source, flags=re.DOTALL)
    assert block, "TARGET_ROUTE_PATHS is missing"
    declared = re.findall(r"'([^']+)'", block.group(1))
    route_spec = json.loads((EVIDENCE / "target_product_spec" / "target_product_route_spec.json").read_text(encoding="utf-8"))
    approved = [item["path"] for item in route_spec]

    assert len(declared) == len(set(declared))
    assert declared == approved


def test_f1_login_exposes_only_student_teacher_and_admin():
    source = _source("frontend/src/views/Login.vue")
    role_block = re.search(r"const roles = \[(.*?)\n\]", source, flags=re.DOTALL)
    assert role_block
    assert re.findall(r"value: '([^']+)'", role_block.group(1)) == ["student", "teacher", "admin"]
    assert "demo-assistant" not in source
    assert "demo-visitor" not in source
    assert "助教" not in source
    assert "访客" not in source


def test_f1_visual_tokens_are_explicit_and_target_pages_reject_old_ai_styling():
    tokens = _source("frontend/src/styles/tokens.css")
    for token in (
        "--font-sans", "--font-size-body: 15px", "--font-size-supporting: 14px",
        "--radius-panel: 8px", "--nav-width: 224px", "--topbar-height: 56px",
        "--color-page: #f5f7f7", "--color-text: #06141b", "--color-accent: #11212d",
    ):
        assert token in tokens

    target_source = "\n".join(
        _source(path)
        for path in (
            "frontend/src/views/Landing.vue",
            "frontend/src/views/Login.vue",
            "frontend/src/views/Settings.vue",
            "frontend/src/components/AppShell.vue",
        )
    ).lower()
    forbidden = (
        "bg-gradient", "linear-gradient", "radial-gradient", "purple", "indigo",
        "green", "emerald", "teal", "brown", "#6b4b37", "glow", "backdrop-filter",
    )
    assert all(token not in target_source for token in forbidden)
    assert not re.search(r"letter-spacing:\s*-", target_source)


def test_protected_pages_follow_their_current_phase_contracts():
    report = json.loads((EVIDENCE / "protection_baseline" / "protected_pages_baseline.json").read_text(encoding="utf-8"))
    assert report["protected_page_count"] == 4
    pages = {page["id"]: page for page in report["pages"]}

    evolved_pages = {
        "profile": {
            "evidence": "f4_t02_profile/report.json",
            "markers": (
                "知识图谱", "能力掌握度雷达图", "十维分析", "数字孪生画像",
                "薄弱点归因", "成因分析", "教学建议", "编辑画像", "一键生成个性化资源",
            ),
        },
        "learning_path": {
            "evidence": "f4_t03_path/report.json",
            "markers": (
                "总路径", "科目路径", "今日任务", "调整预算与重建", "路径分析与历史",
                "学习链条", "教材锚定路径草稿", "A* 动态推荐路线", "一键生成完整资源包",
            ),
        },
        "notes": {
            "evidence": "f8_t03_notes/report.json",
            "markers": (
                'data-testid="notes-workspace"', 'data-testid="notes-explorer"',
                'data-testid="notes-document"', 'data-testid="notes-context"',
                "getNoteVersions", "restoreNoteVersion", "triggerAiPolish",
                "startFlashcardReview", "triggerAddReviewPlan", "exportMarkdown", "exportPdf",
            ),
        },
        "wrong_questions": {
            "evidence": "f8_t02_wrong_questions/report.json",
            "markers": (
                'data-testid="wrong-question-workspace"', 'data-testid="wrong-question-list"',
                'data-testid="wrong-question-detail"', 'data-testid="wrong-question-attempt-history"',
                "submitM5AssessmentAttempt", "togglePinWrongQuestion", "updateWrongQuestionNotes",
                "appendWrongQuestionReflection", "generateFlashcard", "generateSimilarQuiz",
            ),
        },
    }
    for page_id, contract in evolved_pages.items():
        snapshot = pages[page_id]["current_file_evidence"]
        path = ROOT / snapshot["file"]
        assert path.exists(), snapshot["file"]
        source = path.read_text(encoding="utf-8-sig")
        for marker in contract["markers"]:
            assert marker in source, f"{snapshot['file']} lost protected capability: {marker}"

        phase_report = json.loads((EVIDENCE / contract["evidence"]).read_text(encoding="utf-8"))
        assert phase_report.get("result", phase_report.get("status")) == "passed", contract["evidence"]


def test_f1_role_landings_use_minimal_teacher_and_admin_workspaces():
    frontend = _source("frontend/src/utils/roleLanding.js")
    backend = _source("app/role_landing.py")
    for source in (frontend, backend):
        assert "/teacher/overview" in source
        assert "/admin/system" in source
        assert "/competition-showcase" not in source
