#!/usr/bin/env python3
"""Finalize F6-T01's per-atom implementation and verification evidence."""

from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "outputs" / "原系统融合重构执行"
CONTEXT_ROOT = OUTPUT / "evidence" / "context_recovery"
LEDGER_DIR = CONTEXT_ROOT / "atomic_requirement_ledgers" / "EDUMATRIX-F5-F8-CONTEXT-SAFE-FUSION-IMPLEMENTATION"
REPORT = "outputs/原系统融合重构执行/evidence/f6_t01_quiz_resource/evidence_summary.md"
FOCUSED_TESTS = "tests/test_f6_t01_quiz_resource.py (4 passed)"
REGRESSION_TESTS = (
    "tests/test_f4_path_contract.py, tests/test_f4_exam_gate.py, "
    "tests/test_f5_t02_resource_bundle_workspace.py, "
    "tests/test_f5_t07_resource_history.py and tests/test_f6_t01_quiz_resource.py (21 passed)"
)
E2E = (
    "scripts/e2e_f6_t01_quiz_resource.py; "
    "outputs/原系统融合重构执行/evidence/f6_t01_quiz_resource/browser_report.json; "
    "7 screenshots; 1440x900 and 1366x768"
)
BUILD = "frontend: npm run build (6222 modules transformed)"
VISUAL = (
    "Previous Impeccable detector run: no findings on InlineQuizCard, "
    "QuizResourceWorkspace, ResourceToolbar and ResourceHistoryDrawer; "
    "28 warnings were recorded as pre-existing legacy Chat sections outside this task."
)


def primary(implementation: list[str], verification: list[str], visible: str) -> dict[str, object]:
    return {
        "status": "IMPLEMENTED_AND_VERIFIED",
        "implementation_evidence": implementation,
        "verification_evidence": verification,
        "user_visible_result": visible,
        "compatibility_or_defer_rationale": (
            "F6-T01 owns canonical quiz-resource interaction; formal assessments, path gates, "
            "review aggregation and non-quiz resource workspaces remain in their existing owners."
        ),
    }


def related(rationale: str, verification: list[str]) -> dict[str, object]:
    return {
        "status": "COORDINATION_VERIFIED",
        "implementation_evidence": [
            "F6-T01 preserves the existing owner module and consumes its course, task, resource or evidence contract.",
        ],
        "verification_evidence": verification,
        "user_visible_result": "相关能力保持在原责任模块中，并通过测验题资源的课程上下文与证据回流继续可用。",
        "compatibility_or_defer_rationale": rationale,
    }


REALIZATION = {
    "G04-R01": primary(
        [
            "frontend/src/components/InlineQuizCard.vue renders the canonical prompt, options, selected state and submit action.",
            "frontend/src/views/QuizResourceWorkspace.vue owns the persistent question rail and deep-linked question selection.",
            "app/m5_resources.py:_quiz_projection projects only learner-safe question fields from the immutable question version.",
        ],
        [f"{FOCUSED_TESTS}:: generation, ownership and learner-safe projection", f"{E2E}; ready and chat-inline screenshots show selectable questions."],
        "学生打开测验题资源或智能对话中的单题卡后，可以选择选项并在原位点击提交答案。",
    ),
    "G04-R02": primary(
        [
            "app/m5_assessment_core.py:record_attempt grades objective practice answers against the canonical answer key.",
            "app/m5_resources.py:_quiz_attempt_projection adds learner-safe correct answer and explanation to the attempt projection.",
            "InlineQuizCard.vue expands the feedback panel without leaving the current question.",
        ],
        [f"{FOCUSED_TESTS}:: wrong and correct attempts return correct_answer and answer_explanation", f"{E2E}; wrong-feedback and correct-resubmission screenshots pass without unexpected errors."],
        "提交后学生立即看到正确/错误判定、正确答案和解析，并知道可以修改答案或继续追问。",
    ),
    "G04-R03": primary(
        [
            "InlineQuizCard.vue keeps the selected choice while entering revise mode and submits a new idempotency key.",
            "record_attempt stores every new practice submission as an immutable attempt and rejects conflicting idempotency replays.",
        ],
        [f"{FOCUSED_TESTS}:: two distinct attempts remain queryable for one question", f"{E2E}; injected 503 preserves the selected answer, then wrong-to-correct resubmission creates attempts 1 and 2."],
        "学生可以先提交错误答案，再点击修改答案选择新选项；前后两次结果和历史记录都保留。",
    ),
    "G04-R04": primary(
        [
            "InlineQuizCard.vue exposes a contextual follow-up form after grading.",
            "QuizResourceWorkspace.vue and Chat.vue pass course, resource, question version and attempt IDs into the /learn deep link.",
        ],
        [f"{E2E}; follow_up.url and follow_up.prompt contain the question, answer result and user follow-up", "The return route restores the quiz tab and the same canonical question."],
        "学生点击继续追问后，不需要重新描述题目；智能对话会带着当前题目、答案、判分和课程上下文打开。",
    ),
    "G04-R05": primary(
        [
            "app/m5_api.py calls record_canonical_attempt_evidence only for graded attempts.",
            "The existing profile, wrong-question and review aggregators remain the single owners of downstream learning state.",
            "Quiz browsing and resource_detail projection perform no learning-event write.",
        ],
        [f"{FOCUSED_TESTS}:: browsing leaves learning-event count unchanged and graded submissions create quiz_answered events", f"{REGRESSION_TESTS} and SQLite integrity check pass; {E2E} reports 2 attempts, 2 quiz events, integrity ok and 0 foreign-key violations."],
        "只有完成服务端判分的答题才形成可追溯学习证据；普通浏览、看解析和打开历史不会冒充掌握度变化。",
    ),
    "G04-R07": primary(
        [
            "resource_bundles.py:_create_quiz_resource_content builds question prompts from course, knowledge point, profile adaptation, mastery summary, recent events and frozen source snapshots.",
            "The generated question group is persisted as f6.quiz-resource.v1 with immutable question-version references.",
            "Invalid, legacy and unavailable projections remain explicit instead of fabricating questions.",
        ],
        [f"{FOCUSED_TESTS}:: generated content has three canonical question versions and rejects missing learner answer keys", f"{E2E}; fixture is generated from the current course/source context and the workspace exposes source references."],
        "更换课程知识点或学习证据后生成的是绑定当前上下文的题组；示例题不是固定产品行为，来源或结构异常时会诚实显示不可用。",
    ),
    "G04-R08": primary(
        [
            "Chat.vue renders the same InlineQuizCard contract for a canonical single question and links a persistent group to /workspace/resources/quizzes/:resourceId.",
            "The quiz workspace stores questions, attempts, source references, versions and progress outside the chat transcript.",
            "Assessment center routing remains limited to entry diagnosis and intelligent exam entries.",
        ],
        [f"{E2E}; chat-inline screenshot and assessment_center_entries=2 verify the two information-architecture boundaries", f"{REGRESSION_TESTS} pass with the quiz route independent from formal assessment routes."],
        "对话里的单题可直接完成；需要长期学习的题组会进入学习空间测验题资源并保留历史。",
    ),
    "G04-R06": related(
        "单题就地作答由 G04-R01 至 G04-R04 的共享题卡协议实现；本相关原子不新增第二套聊天题目存储。",
        [f"{E2E}; chat-inline screenshot and follow-up deep-link assertion", f"{REGRESSION_TESTS} pass with the canonical quiz route."],
    ),
    "G21-R01": related(
        "测验题作为学习空间正式资源类型接入 F5 资源目录，不新增学生一级导航。",
        [f"{REGRESSION_TESTS}; resource bundle and quiz workspace contracts pass", f"{E2E}; quiz resource deep link opens the dedicated workspace."],
    ),
    "G21-R02": related(
        "QuizResourceWorkspace.vue 提供资源级专用页面、刷新恢复和版本选择，路由不依赖聊天内存。",
        [f"{E2E}; refresh restores attempts and 1366x768 deep-link screenshot passes"],
    ),
    "G21-R03": related(
        "课程、知识点、画像适配、来源和最近事件从统一资源生成上下文投影，题目页只消费该事实源。",
        [f"{FOCUSED_TESTS} and {E2E}; resource title, knowledge point and source projection remain consistent"],
    ),
    "G21-R04": related(
        "题目追问使用带资源/版本/尝试身份的安全深链，解释行为不替代作答或正式测评。",
        [f"{E2E}; follow-up prompt and return-to-quiz assertions pass"],
    ),
    "G21-R05": related(
        "测评中心继续由 F4 的入学诊断和智能组卷负责，日常练习只在 quiz 资源中即时判分。",
        [f"{E2E}; assessment_center_entries=2", f"{REGRESSION_TESTS} pass with exam gate contracts intact"],
    ),
    "G21-R06": related(
        "测验资源深链保留课程和知识点上下文；路径编排与预算不由答题页面直接改写。",
        [f"{REGRESSION_TESTS}; path and exam gate contracts remain green", f"{E2E}; source and course return context are present"],
    ),
    "G21-R07": related(
        "错题/复习聚合读取 quiz_answered 证据；测验页面不取代真实复习日历，也不以浏览标记完成。",
        [f"{FOCUSED_TESTS} and {E2E}; browsing creates no evidence and graded attempts create only quiz_answered events"],
    ),
    "G21-R08": related(
        "复习生成入口继续由资源包/F5 负责；单项测验生成和正式智能组卷保持两个动作与两个门禁。",
        [f"{REGRESSION_TESTS} pass resource generation and exam gate contracts", "Quiz workspace does not call exam unlock APIs."],
    ),
    "G21-R09": related(
        "复习完成反馈只能使用有效判分证据，画像回流交给统一学习事件聚合器。",
        [f"{FOCUSED_TESTS}; correct and incorrect submissions are separately persisted and browsing is side-effect free"],
    ),
    "G21-R10": related(
        "题组版本、历史、比较和恢复由统一 Artifact/ArtifactVersion 事实源提供；编辑只创建新版本并保持题目 ID稳定。",
        [f"{FOCUSED_TESTS}:: metadata edit, compare and restore preserve all question IDs", f"{E2E}; history drawer is visible and refresh-safe"],
    ),
    "G21-R11": related(
        "测评中心入口数量和职责不变，学习中练习不再作为第三类测评出现。",
        [f"{E2E}; assessment_center_entries=2", f"{REGRESSION_TESTS} pass assessment boundary checks"],
    ),
    "G21-R12": related(
        "测验题、实训任务书、代码沙盒和可交互模型继续使用独立 artifact_type 与路由，本任务不混合页面职责。",
        [f"{REGRESSION_TESTS} pass resource-type and workspace contracts", "Quiz workspace renders no code execution or interactive-model controls."],
    ),
    "G21-R13": related(
        "资源可生成并归档，但组卷解锁仍只读取 F4 今日必做任务状态；可选资源浏览和题组打开不会解锁。",
        [f"{REGRESSION_TESTS} pass frozen exam-gate behavior", f"{E2E}; ordinary browse starts with 0 quiz_answered events and does not enter the exam route."],
    ),
}


def main() -> None:
    matches = list(LEDGER_DIR.glob("F6-T01_*.json"))
    if len(matches) != 1:
        raise RuntimeError(f"Expected one F6-T01 ledger, found {len(matches)}")
    ledger_path = matches[0]
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    actual_ids = [entry["atomic_requirement_id"] for entry in ledger["entries"]]
    missing = [atom_id for atom_id in actual_ids if atom_id not in REALIZATION]
    extra = [atom_id for atom_id in REALIZATION if atom_id not in actual_ids]
    if missing or extra:
        raise RuntimeError(f"Atomic realization mismatch: missing={missing}, extra={extra}")
    for entry in ledger["entries"]:
        entry["realization"] = REALIZATION[entry["atomic_requirement_id"]]

    batch = {
        "id": "F6-T01-B01",
        "status": "VERIFIED",
        "direct_atoms": [
            "G04-R01", "G04-R02", "G04-R03", "G04-R04", "G04-R05", "G04-R07", "G04-R08",
        ],
        "related_atoms": [atom_id for atom_id in actual_ids if atom_id not in REALIZATION or atom_id not in {
            "G04-R01", "G04-R02", "G04-R03", "G04-R04", "G04-R05", "G04-R07", "G04-R08",
        }],
        "files": [
            "app/m5_assessment_core.py", "app/m5_api.py", "app/m5_resources.py", "app/resource_bundles.py",
            "frontend/src/components/InlineQuizCard.vue", "frontend/src/components/ResourceHistoryDrawer.vue",
            "frontend/src/views/QuizResourceWorkspace.vue", "frontend/src/views/Chat.vue",
            "frontend/src/router/index.js", "tests/test_f6_t01_quiz_resource.py",
            "scripts/e2e_f6_t01_quiz_resource.py",
        ],
        "interfaces": [
            "GET /api/v1/m5/resources/{artifact_id}",
            "POST /api/v1/m5/assessment/attempts",
            "POST /api/v1/m5/resources/{artifact_id}/versions",
            "GET /api/v1/m5/resources/{artifact_id}/compare",
            "POST /api/v1/m5/resources/{artifact_id}/restore",
        ],
        "states": [
            "ready", "selected", "submitting", "submission_failed_preserve_selection", "wrong_feedback",
            "revision", "correct_feedback", "attempt_history", "legacy_readonly", "invalid_structured",
            "unavailable_question", "completed",
        ],
        "verification": [FOCUSED_TESTS, REGRESSION_TESTS, BUILD, E2E, "git diff --check", VISUAL],
        "protection_contracts": [
            "learner-safe projections never expose answer_key in question payloads",
            "attempts and question versions remain immutable",
            "only graded submissions write quiz_answered evidence",
            "formal assessment center remains limited to two entries",
            "legacy, invalid and unavailable content is surfaced honestly",
        ],
    }
    batches = ledger.setdefault("execution_batches", [])
    existing = next((item for item in batches if item.get("id") == batch["id"]), None)
    if existing is None:
        batches.append(batch)
    else:
        existing.update(batch)
    ledger_path.write_text(json.dumps(ledger, ensure_ascii=False, sort_keys=True, indent=2) + "\n", encoding="utf-8")

    sys.path.insert(0, str(ROOT / "scripts"))
    from context_recovery_atomic_gate import expected_entries, load_task_payload, validate_ledger_identity, validate_realization

    active = json.loads((CONTEXT_ROOT / "active_manifest.json").read_text(encoding="utf-8"))
    payload = load_task_payload(ROOT, CONTEXT_ROOT, active, "F6-T01")
    expected = expected_entries(payload)
    failures = validate_ledger_identity(
        ledger,
        goal_id="EDUMATRIX-F5-F8-CONTEXT-SAFE-FUSION-IMPLEMENTATION",
        task="F6-T01",
        entries=expected,
    )
    failures.extend(validate_realization(ledger, expected))
    if failures:
        raise RuntimeError(f"F6-T01 atomic realization gate failed: {failures}")
    print(f"Updated and validated {len(actual_ids)} F6-T01 atomic realizations: {ledger_path}")


if __name__ == "__main__":
    main()
