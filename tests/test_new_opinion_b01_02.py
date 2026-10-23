"""Focused automatic checks for NOC-T01 batch B01-02 (A14-A18)."""

import asyncio
import ast
from pathlib import Path
from types import SimpleNamespace

import pytest

import flashcard_api


ROOT = Path(__file__).resolve().parents[1]


def read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def function_source(relative: str, name: str) -> str:
    tree = ast.parse(read(relative))
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return ast.get_source_segment(read(relative), node) or ""
    raise AssertionError(f"function not found: {relative}:{name}")


def test_a14_path_is_vertical_multicourse_and_has_no_budget_gate() -> None:
    view = read("frontend/src/views/LearningPathGraph.vue")
    task_list = read("frontend/src/components/PathTaskList.vue")
    learning = read("app/m5_learning.py")

    assert "v-for=\"subject in visibleSubjects\"" in view
    assert 'class="path-course-path"' in view
    assert ".path-course-paths { display: grid;" in view
    assert "所有任务按先修关系开放" in view
    assert "调整预算与重建" not in view
    assert "time_budget_minutes" not in function_source("app/m5_learning.py", "multi_course_schedule")
    assert "every currently-unblocked candidate" in function_source("app/m5_learning.py", "multi_course_schedule")
    assert 'class="path-task-list__rows"' in task_list
    assert "path-task__criteria" in task_list


def test_a14_schedule_keeps_prerequisites_and_returns_all_courses() -> None:
    source = function_source("app/m5_learning.py", "multi_course_schedule")
    assert "DBLearningPath.course_id == course_id" in source
    assert "DBLearningPath.status.in_((\"active\", \"paused\"))" in source
    assert "prerequisite_keys - resolved[projection[\"path_id\"]]" in source
    assert '"courses": courses' in source
    assert '"learning_state_written": False' in source


def test_a15_flashcard_requires_completed_evidence_before_generation() -> None:
    api = read("flashcard_api.py")
    generation = function_source("flashcard_api.py", "generate_flashcard")
    evidence = function_source("flashcard_api.py", "_has_completed_learning_evidence")

    assert 'evidence_status="accepted"' in api
    assert "mastery_eligible=True" in api
    assert 'completion_effect="complete"' in api
    assert "existing_version is None and not _has_completed_learning_evidence" in generation
    assert '"code": "flashcard_generation_requires_completion"' in generation
    assert "evidence_status=\"accepted\"" in evidence
    assert "mastery_eligible=True" in evidence
    assert "completion_effect=\"complete\"" in evidence


def test_a15_flashcard_model_prompt_requires_answer_and_dimension_reduction() -> None:
    source = function_source("flashcard_api.py", "_generate_flashcard_answer")
    assert "JSON 必须包含 answer 和 explanation 字段" in source
    assert "真实降维解释" in source
    assert "困难知识点：必须先给出真实降维解释" in source
    assert "generate_review_model_json" in source


def test_a15_flashcard_generation_uses_real_model_metadata_and_explanation(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []

    async def fake_generate_review_model_json(**kwargs):
        calls.append(kwargs)
        return (
            {"answer": "回答不是固定模板，而是由模型结合知识点生成。", "explanation": "把概念化成一个可以复述的最小例子。"},
            "deepseek-v4-flash",
            "OpenAI-compatible DeepSeek",
        )

    monkeypatch.setattr(flashcard_api, "generate_review_model_json", fake_generate_review_model_json)
    answer, metadata = asyncio.run(
        flashcard_api._generate_flashcard_answer(
            concept="梯度下降",
            owner_public_id="user-a15",
            course_id="course-a15",
            record=SimpleNamespace(
                accuracy_score=0.2,
                correct_answer="沿负梯度方向更新参数",
                student_answer="随机调整参数",
            ),
        )
    )

    assert len(calls) == 1
    assert calls[0]["operation"] == "review_flashcard_answer"
    assert "explanation" in calls[0]["system_prompt"]
    assert "降维解释" in calls[0]["user_prompt"]
    assert metadata == {
        "model": "deepseek-v4-flash",
        "provider": "OpenAI-compatible DeepSeek",
        "thinking": "enabled",
        "reasoning_effort": "max",
        "allow_fallback": False,
        "explanation_generated": True,
    }
    assert "降维解释：" in answer


def test_a15_model_failure_is_not_replaced_by_template(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fail_generate_review_model_json(**kwargs):
        raise flashcard_api.ReviewModelError("model_unavailable", "模型不可用")

    monkeypatch.setattr(flashcard_api, "generate_review_model_json", fail_generate_review_model_json)
    with pytest.raises(flashcard_api.ReviewModelError):
        asyncio.run(
            flashcard_api._generate_flashcard_answer(
                concept="测试知识点", owner_public_id="user-a15"
            )
        )


def test_a16_review_keeps_sm2_data_but_removes_internal_english_copy() -> None:
    board = read("frontend/src/components/ReviewScheduleBoard.vue")
    schedule = read("flashcard_api.py")
    assert "SM-2 due date and legacy review priority" not in board
    assert "humanTaskType" in board
    assert "interval_days" in schedule
    assert "next_review_at" in schedule
    assert "easiness_factor" in schedule


def test_a17_note_scroll_is_local_and_does_not_reload_or_replace_route() -> None:
    view = read("frontend/src/views/Notes.vue")
    start = view.index("function persistNotesListScroll")
    source = view[start:view.index("async function setSourceFilter", start)]
    assert "const notesScrollTop = ref(0)" in view
    assert "@scroll.passive=\"persistNotesListScroll\"" in view
    assert "notesScrollTop.value" in source
    assert "router.replace" not in source
    assert "load()" not in source
    assert "page-level refresh" in source


def test_a18_digital_twin_profile_is_restored_without_emoji_or_demo_history() -> None:
    view = read("frontend/src/views/StudentAnalysis.vue")
    assert 'data-testid="digital-twin-tab"' in view
    assert 'data-testid="digital-twin-profile"' in view
    assert "mental_state_history" in view
    assert "kalman_history" in view
    assert "记忆保持" in view
    assert "布鲁姆认知层级" in view
    assert "showEditModal" in view
    assert "mental_state_history || [" not in view
    assert "kalman_history || [" not in view
    digital_twin = view[view.index('data-testid="digital-twin-profile"'):]
    digital_twin = digital_twin[:digital_twin.index('</div>', digital_twin.index('</div>') + 1)]
    assert not any(ord(char) > 0x1F000 for char in digital_twin)


def test_b01_02_preserves_real_model_governance_and_visual_spacing() -> None:
    flashcards = read("flashcard_api.py")
    governance = read("app/crud.py")
    path = read("frontend/src/views/LearningPathGraph.vue")
    profile = read("frontend/src/views/StudentAnalysis.vue")
    assert '"model": model' in flashcards
    assert '"reasoning_effort": "max"' in flashcards
    assert '"allow_fallback": False' in flashcards
    assert 'model != "deepseek-v4-flash"' in governance
    assert 'reasoning_effort != "max"' in governance
    for source in (path, profile):
        assert "gap:" in source
        assert "padding" in source
