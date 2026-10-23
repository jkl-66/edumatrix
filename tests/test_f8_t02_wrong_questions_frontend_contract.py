from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VIEW = ROOT / "frontend" / "src" / "views" / "WrongQuestionBook.vue"
ROUTER = ROOT / "frontend" / "src" / "router" / "index.js"


def source(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_list_detail_workspace_has_one_primary_action_and_progressive_depth() -> None:
    view = source(VIEW)

    for marker in (
        'data-testid="wrong-question-workspace"',
        'data-testid="wrong-question-filters"',
        'data-testid="wrong-question-list"',
        'data-testid="wrong-question-detail"',
        'data-testid="wrong-question-attempt-history"',
        'data-testid="wrong-question-diagnosis"',
        'data-testid="wrong-question-sources"',
        'data-testid="wrong-question-related-resources"',
        'data-testid="wrong-question-notes"',
        'data-testid="wrong-question-deep-practice"',
        'data-testid="wrong-question-analytics"',
    ):
        assert marker in view
    assert "grid-template-columns:360px minmax(0,1fr)" in view
    assert view.count('class="primary-action"') == 1
    assert view.count('data-testid="wrong-question-primary-action"') == 1
    assert "重做是" not in view


def test_redo_uses_canonical_attempt_and_preserves_result_after_refresh() -> None:
    view = source(VIEW)
    block = view[view.index("async function submitRedo"):view.index("async function loadFlashcard")]

    for marker in (
        "submitM5AssessmentAttempt",
        "question_version_id: item.question_version_id",
        "idempotency_key: redoKey.value",
        "mode: 'practice'",
        "const submittedResult = response.attempt || response",
        "await loadData()",
        "redoResult.value = submittedResult",
        "答案已保留，可直接重试",
        "不会重复计分",
    ):
        assert marker in view
    assert block.index("const submittedResult") < block.index("await loadData()")
    assert block.index("await loadData()") < block.index("redoResult.value = submittedResult")


def test_redo_prepares_missing_legacy_identity_and_supports_every_canonical_answer_shape() -> None:
    view = source(VIEW)
    api = source(ROOT / "frontend" / "src" / "api" / "quiz.js")

    for marker in (
        "prepareWrongQuestionRedo",
        "redoPreparing",
        "createRedoResponse",
        "response_spec?.blank_count",
        "type === 'single_choice'",
        "type === 'multiple_choice'",
        "type === 'true_false'",
        "type === 'fill_blank'",
        "type === 'code'",
        "redoResponse.value.value !== null",
        "redoResponse.value.blanks.every",
        "{ choice: redoResponse.value.choice }",
        "{ choices: redoResponse.value.choices }",
        "{ value: redoResponse.value.value }",
        "{ blanks: redoResponse.value.blanks",
        "{ code: redoResponse.value.code }",
        "{ text: redoResponse.value.text.trim() }",
        'data-testid="wrong-question-redo-prepare"',
        'data-testid="wrong-question-redo-submit"',
    ):
        assert marker in view
    assert "/prepare-redo" in api
    assert "evaluateQuizAnswer" not in view[
        view.index("async function submitRedo"):view.index("async function loadFlashcard")
    ]


def test_redo_failure_keeps_answer_and_reuses_one_idempotency_key() -> None:
    view = source(VIEW)
    submit = view[view.index("async function submitRedo"):view.index("async function loadFlashcard")]

    assert "resetRedoResponse" not in submit
    assert "redoKey.value" in submit
    assert "答案已保留，可直接重试" in submit
    assert "不会重复计分" in view


def test_similar_challenge_preserves_result_after_refresh_and_shows_feedback() -> None:
    view = source(VIEW)
    submit = view[view.index("async function submitSimilar"):view.index("function openRoute")]

    for marker in (
        "const submittedResult = await evaluateQuizAnswer(",
        "const submittedQuiz = similarQuiz.value",
        "await loadData()",
        "similarQuiz.value = submittedQuiz",
        "similarResult.value = submittedResult",
        'data-testid="wrong-question-similar-result"',
        "得分 {{ Math.round(Number(similarResult.accuracy_score || 0) * 100) }}%",
        "正确答案：",
        "解析：",
    ):
        assert marker in view
    assert submit.index("await loadData()") < submit.index("similarResult.value = submittedResult")


def test_practice_and_formal_sources_keep_their_routes_and_feedback_boundary() -> None:
    view = source(VIEW)

    for marker in (
        "sourceFilter",
        "测验题资源",
        "智能组卷",
        "formal_exam_links",
        "attempt.feedback_released",
        "selectedQuestion.question?.answer_available !== false",
        "查看原题",
        "打开复习日历",
        "selectedQuestion.actions?.chat?.route",
        "问学习伙伴",
    ):
        assert marker in view
    assert "完整生成产物" not in view


def test_all_protected_720_wrong_question_actions_remain_available() -> None:
    view = source(VIEW)

    for capability in (
        "togglePinWrongQuestion",
        "deleteWrongQuestion",
        "updateWrongQuestionNotes",
        "appendWrongQuestionReflection",
        "generateFlashcard",
        "generateSimilarQuiz",
        "evaluateQuizAnswer",
        "exportSelected",
        "decideM5Misconception",
    ):
        assert capability in view
    for visible_label in (
        "置顶",
        "移除记录",
        "保存笔记",
        "写入笔记本",
        "生成闪卡",
        "生成相似题",
        "导出当前错题复盘",
    ):
        assert visible_label in view


def test_embedded_video_generation_and_parallel_fact_sources_are_absent() -> None:
    view = source(VIEW)

    for forbidden in (
        "generateWrongQuestionVideo",
        "createWrongQuestionVideo",
        "wrongQuestionVideos",
        "wrong-question-video-generator",
        "createLearningEvent",
        "updateMastery",
        "completePathTask",
        "unlockExam",
    ):
        assert forbidden not in view


def test_route_and_full_user_states_are_preserved() -> None:
    view = source(VIEW)
    router = source(ROUTER)

    assert "path: '/workspace/review/wrong-questions'" in router
    assert "legacy('/wrong-questions'" in router
    for marker in (
        'data-testid="wrong-question-error"',
        'data-testid="wrong-question-empty"',
        'data-testid="wrong-question-filter-empty"',
        "错题加载中",
        "反馈尚未开放",
        "来源已撤回或定位缺失",
        "判分中",
        "本次仍需巩固",
        "回答正确",
    ):
        assert marker in view


def test_frozen_light_visual_contract_has_no_theme_or_text_regression() -> None:
    view = source(VIEW).lower()

    for required in (
        "#f5f7f7",
        "#06141b",
        "#11212d",
        "var(--font-sans)",
    ):
        assert required in view
    for forbidden in (
        "linear-gradient",
        "radial-gradient",
        "backdrop-filter",
        "source han serif",
        "noto serif",
        "#10b981",
        "#22c55e",
        "#0ea5e9",
        "#3b82f6",
        "#8b5cf6",
        "#a855f7",
        "font-size:10px",
        "font-size:11px",
        "font-size:12px",
        "font-size:13px",
    ):
        assert forbidden not in view
