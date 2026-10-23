from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
API = ROOT / "frontend" / "src" / "api" / "m5.js"
COMPONENT = ROOT / "frontend" / "src" / "components" / "AggregationStatus.vue"
CONSUMERS = (
    ROOT / "frontend" / "src" / "views" / "Dashboard.vue",
    ROOT / "frontend" / "src" / "views" / "StudentAnalysis.vue",
    ROOT / "frontend" / "src" / "views" / "LearningPathGraph.vue",
    ROOT / "frontend" / "src" / "views" / "WrongQuestionBook.vue",
    ROOT / "frontend" / "src" / "views" / "Review.vue",
    ROOT / "frontend" / "src" / "views" / "History.vue",
)
FORMAL_EXAM = ROOT / "frontend" / "src" / "views" / "FormalExamWorkspace.vue"


def source(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_shared_feedback_component_is_used_by_all_six_views_and_exam_result() -> None:
    for consumer in (*CONSUMERS, FORMAL_EXAM):
        view = source(consumer)
        assert "import AggregationStatus from '../components/AggregationStatus.vue'" in view
        assert "<AggregationStatus" in view


def test_feedback_client_has_one_read_contract_and_replays_only_existing_events() -> None:
    api = source(API)

    for marker in (
        "export function getLatestM5LearningFeedback(params = {})",
        "'/v1/m5/learning-feedback/latest'",
        "export function getM5LearningAggregation(eventId)",
        "`/v1/m5/learning-events/${encodeURIComponent(eventId)}/aggregation`",
        "export function replayM5LearningEvent(eventId)",
        "`/v1/m5/learning-events/${encodeURIComponent(eventId)}/process`",
    ):
        assert marker in api
    assert "createM5LearningEvent" not in source(COMPONENT)


def test_component_exposes_complete_honest_states_without_a_second_report_wall() -> None:
    component = source(COMPONENT)

    for marker in (
        "正在核对学习结果",
        "还没有可用的学习反馈",
        "学习结果处理中",
        "部分学习结果待恢复",
        "学习反馈暂时无法读取",
        "本次学习已记录",
        "结果已经保存",
        "重试同步",
        "跨页面同步状态",
        "下一日安排",
        "一致版本",
    ):
        assert marker in component
    for forbidden in (
        "props.eventId ? response.feedback : response.feedback",
        "已完全掌握",
        "完成即掌握",
        "trace",
        "worker",
        "lease",
        "private chain",
    ):
        assert forbidden.lower() not in component.lower()
    assert "feedback.value = response.feedback" in component
    assert "feedback.value?.event?.id || props.eventId" in component
    assert ":disabled=\"retrying\"" in component


def test_formal_exam_gate_and_original_result_sections_remain_authoritative() -> None:
    view = source(FORMAL_EXAM)

    for marker in (
        "if (!gate.value?.unlocked || !selectionComplete.value) return",
        'data-testid="exam-gate-locked"',
        "智能组卷尚未解锁",
        "gate.missing_tasks",
        'data-testid="exam-builder-unlocked"',
        'data-testid="formal-exam-report"',
        ':initial-feedback="reportEnvelope?.learning_feedback || null"',
    ):
        assert marker in view


def test_feedback_component_preserves_the_frozen_light_visual_contract() -> None:
    component = source(COMPONENT).lower()

    font_sizes = [int(value) for value in re.findall(r"font-size:\s*(\d+)px", component)]
    radii = [int(value) for value in re.findall(r"border-radius:\s*(\d+)px", component)]
    assert font_sizes and min(font_sizes) >= 14
    assert radii and max(radii) <= 8
    for required in ("#11212d", "#ffffff", "var(--font-sans"):
        assert required in component
    for forbidden in (
        "linear-gradient",
        "radial-gradient",
        "backdrop-filter",
        "#10b981",
        "#22c55e",
        "#0ea5e9",
        "#3b82f6",
        "#8b5cf6",
        "#a855f7",
        "green-",
        "emerald-",
        "purple-",
        "indigo-",
        "amber-",
        "orange-",
    ):
        assert forbidden not in component
