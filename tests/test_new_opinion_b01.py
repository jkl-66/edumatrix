from pathlib import Path

from app.m5_exam_core import IntelligentExamConfigInput, LEARNER_EXAM_TYPES


ROOT = Path(__file__).resolve().parents[1]


def read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_entry_diagnostic_never_uses_object_to_string_for_errors() -> None:
    view = read("frontend/src/views/EntryDiagnostic.vue")
    assert "Object.values(detail)" in view
    assert "message !== '[object Object]'" in view
    assert "诊断服务暂不可用，请稍后重试。" in view
    assert 'data-testid="diagnostic-error-retry"' in view


def test_formal_exam_normalizes_option_labels_to_abcd_and_keeps_text() -> None:
    view = read("frontend/src/views/FormalExamWorkspace.vue")
    assert "function optionLabel(option, index)" in view
    assert "String.fromCharCode(65 + index)" in view
    assert "function optionText(option)" in view
    assert "v-for=\"(option, index) in currentQuestion.options\"" in view
    assert "optionLabel(option, index)" in view
    assert "optionText(option)" in view
    assert "option.slice(0, 1)" not in view


def test_assessment_exam_supports_mixed_question_types_through_one_schema() -> None:
    assert {"single_choice", "multiple_choice", "true_false", "short_answer"}.issubset(
        set(LEARNER_EXAM_TYPES),
    )
    config = IntelligentExamConfigInput(
        idempotency_key="new-opinion-b01-mixed",
        course_id="course-b01",
        question_type_counts={
            "single_choice": 2,
            "multiple_choice": 1,
            "true_false": 1,
            "short_answer": 1,
        },
    )
    assert sum(config.question_type_counts.values()) == 5


def test_assessment_text_wraps_without_shrinking_or_clipping() -> None:
    assessment = read("frontend/src/views/AssessmentWorkspace.vue")
    formal = read("frontend/src/views/FormalExamWorkspace.vue")
    for source in (assessment, formal):
        assert "overflow-wrap:anywhere" in source
        assert "white-space:normal" in source
        assert "word-break:break-word" in source
    assert ".option-list label span{font-size:14px}" in assessment
    assert ".question-stage h2{font-size:18px}" in assessment
