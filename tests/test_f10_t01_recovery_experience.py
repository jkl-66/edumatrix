from __future__ import annotations

import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ROUTER = ROOT / "frontend/src/router/index.js"
RECOVERY = ROOT / "frontend/src/views/ContextRecovery.vue"
KNOWLEDGE = ROOT / "frontend/src/views/Knowledge.vue"
DASHBOARD_ROUTE = ROOT / "frontend/src/views/DashboardRoute.vue"
DASHBOARD = ROOT / "frontend/src/views/Dashboard.vue"
COURSE_CONTEXT = ROOT / "frontend/src/stores/courseContext.js"
INTERACTIVE_MODEL = ROOT / "frontend/src/views/InteractiveLabWorkspace.vue"
ROLE_LANDING = ROOT / "frontend/src/utils/roleLanding.js"
SERVER_ROLE_LANDING = ROOT / "app/role_landing.py"
F10_E2E = ROOT / "scripts/e2e_f10_t01_route_migration.py"
F9_T03_REPORT = ROOT / "outputs/原系统融合重构执行/evidence/f9_t03_admin_teacher/report.json"
F9_T04_REPORT = ROOT / "outputs/原系统融合重构执行/evidence/f9_t04_authorization_audit/report.json"
ROUTE_CONTRACT = ROOT / "frontend/src/router/routeMigrationContract.json"
TARGET_SPEC = ROOT / "outputs/原系统融合重构执行/evidence/target_product_spec/target_product_route_spec.json"
CHAT = ROOT / "frontend/src/views/Chat.vue"
QUIZ_WORKSPACE = ROOT / "frontend/src/views/QuizResourceWorkspace.vue"
INLINE_QUIZ = ROOT / "frontend/src/components/InlineQuizCard.vue"


def _source(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _route_line(source: str, path: str) -> str:
    match = re.search(rf"\{{ path: '{re.escape(path)}'.*", source)
    assert match, path
    return match.group(0)


def test_unknown_paths_reach_the_explained_recovery_surface():
    source = _source(ROUTER)

    for fragment in (
        "function unknownRouteRedirect(to)",
        "reason: 'route_unknown'",
        "legacy_path: to.path",
        "return_to: to.fullPath",
        "name: 'NotFound', beforeEnter: unknownRouteRedirect",
    ):
        assert fragment in source
    assert "name: 'NotFound', beforeEnter: () => roleLandingPath" not in source


def test_recovery_copy_explains_every_disabled_route_reason_in_business_language():
    source = _source(RECOVERY)
    contract = json.loads(_source(ROUTE_CONTRACT))
    required_reasons = {
        item["recoveryReason"]
        for item in contract
        if item.get("destination") == "/context-recovery"
    }

    assert required_reasons == {"feature_deferred", "feature_internal", "feature_removed"}
    for reason in [*sorted(required_reasons), "route_unknown"]:
        assert f"{reason}: {{" in source
    for visible_copy in (
        "此功能暂未开放",
        "此入口仅供内部验证",
        "此入口已停止使用",
        "没有找到这个页面",
        "你的课程和学习记录没有发生变化",
        "没有创建空对象，也没有修改现有学习记录",
    ):
        assert visible_copy in source


def test_context_failures_and_feature_recovery_have_different_safe_actions():
    source = _source(RECOVERY)

    assert "reason.value.startsWith('context_')" in source
    assert "if (isContextIssue.value) reselectCourse()" in source
    assert "else returnToRoleHome()" in source
    assert "context.clear({ keepCourse: false })" in source
    assert "router.push(roleLandingPath(localStorage.getItem('edumatrix_role')))" in source
    assert 'v-if="isContextIssue" type="button" class="button-secondary"' in source
    assert "route.query.return_to" not in source
    assert "返回原页面" not in source


def test_admin_role_home_matches_server_and_closed_f9_browser_contract():
    client_landing = _source(ROLE_LANDING)
    server_landing = _source(SERVER_ROLE_LANDING)
    e2e = _source(F10_E2E)

    assert "if (role === 'admin') return '/admin/system'" in client_landing
    assert 'if role == "admin":\n        return "/admin/system"' in server_landing
    assert e2e.count('assert_path(page, "/admin/system")') == 3
    assert 'assert_path(page, "/admin/accounts")' not in e2e

    for report_path in (F9_T03_REPORT, F9_T04_REPORT):
        report = json.loads(_source(report_path))
        assert report["admin_entry_order"] == ["/landing", "/login", "/admin/system"]


def test_target_route_roles_match_the_approved_teacher_preview_boundaries():
    source = _source(ROUTER)
    target = {item["path"]: item for item in json.loads(_source(TARGET_SPEC))}

    assert target["/knowledge"]["role"] == "学生、教师"
    assert target["/marketplace"]["role"] == "学生、教师"
    assert "教师可在课程资源中使用同一资源模型" in target["/workspace/resources"]["role"]

    shared_roots = ["/knowledge", "/marketplace"]
    shared_details = [
        "/knowledge/courses/:courseId",
        "/knowledge/documents/:documentId",
        "/knowledge/graph/:courseId",
        "/knowledge/discover",
        "/marketplace/items/:itemId",
        "/marketplace/publish",
        "/marketplace/mine",
        "/workspace/resources/handouts/:resourceId",
        "/workspace/resources/training-tasks/:resourceId",
        "/workspace/resources/mindmaps/:resourceId",
        "/workspace/resources/videos/:resourceId",
        "/workspace/resources/decks/:resourceId",
        "/workspace/resources/models/:resourceId",
        "/workspace/resources/bundles/:bundleId",
        "/workspace/resources/quizzes/:resourceId",
    ]
    for path in [*shared_roots, *shared_details]:
        assert "STUDENT_AND_TEACHER" in _route_line(source, path), path
    assert "STUDENT," in _route_line(source, "/workspace/resources")
    assert "STUDENT_AND_TEACHER" not in _route_line(source, "/workspace/resources")
    assert "const STUDENT_AND_TEACHER = ['student', 'teacher']" in source


def test_recovery_page_uses_the_approved_light_visual_tokens():
    source = _source(RECOVERY)

    assert "#2f261f" not in source.lower()
    assert "green" not in source.lower()
    assert "gradient(" not in source.lower()
    assert "background: var(--color-accent);" in source
    assert "color: #ffffff;" in source
    assert "font-size: 14px;" in source
    assert not re.search(r"font-size:\s*(?:[0-9]|1[0-3])px", source)
    assert ":focus-visible" in source


def test_knowledge_search_destination_is_visually_integrated_without_losing_behavior():
    source = _source(KNOWLEDGE)
    section = source.split("<!-- 成员 3: 跨模态搜索 -->", 1)[1].split("<!-- 文档和标签的派生关联视图 -->", 1)[0]

    for forbidden in ("backdrop-blur", "bg-gradient", "rounded-xl", "text-xs", "text-["):
        assert forbidden not in section
    for required in (
        "rounded-lg border border-slate-200 bg-white p-5",
        "bg-[#11212d]",
        'v-model="crossModalQuery"',
        '@keyup.enter="doCrossModalSearch"',
        'v-model="crossModalMode"',
        ':disabled="crossModalLoading"',
        'v-if="crossModalLoading"',
        'v-else-if="crossModalError"',
        'v-else-if="crossModalResults.length > 0"',
        "r.matched_modality",
    ):
        assert required in section


def test_dashboard_route_uses_the_original_body_as_one_static_entry():
    router = _source(ROUTER)
    dashboard = _source(DASHBOARD)

    assert "import Dashboard from '../views/Dashboard.vue'" in router
    assert "DashboardRoute" not in router
    assert router.count("path: '/',") == 1
    assert "component: Dashboard" in _route_line(router, "/")
    assert not DASHBOARD_ROUTE.exists()
    assert "getCompetitionDemoContext" not in dashboard
    assert "demoContext" not in dashboard
    assert "localStorage.getItem('edumatrix_course_id')" in dashboard
    assert "getM5WorkspaceOverview(courseId)" in dashboard
    assert "getM5DashboardSummary(courseId)" in dashboard


def test_legacy_interactive_model_sentinel_keeps_course_guard_without_fake_resource_lookup():
    router = _source(ROUTER)
    store = _source(COURSE_CONTEXT)
    interactive_model = _source(INTERACTIVE_MODEL)
    migration = next(
        item for item in json.loads(_source(ROUTE_CONTRACT))
        if item["sourcePath"] == "/interactive-lab"
    )

    assert migration["destination"] == "/workspace/resources/models/legacy"
    assert "const legacyMode = computed(() => resourceId.value === 'legacy')" in interactive_model
    for fragment in (
        "function courseContextOverride(to)",
        "to.name === 'InteractiveModelResource'",
        "String(to.params?.resourceId || '') === 'legacy'",
        "return isLegacyInteractiveModel ? { resourceId: null } : null",
        "restoreFromRoute(to, courseContextOverride(to))",
    ):
        assert fragment in router
    for fragment in (
        "async function restoreFromRoute(route, contextOverride = null)",
        "const candidate = normalizeContextRef({",
        "...contextRefFromRoute(route)",
        "...(contextOverride || {})",
        "const result = await resolveContext(candidate)",
    ):
        assert fragment in store
    assert "if (to.params?.resourceId)" not in router


def test_chat_quiz_context_converges_on_the_formal_resource_workspace():
    chat = _source(CHAT)
    quiz_workspace = _source(QUIZ_WORKSPACE)
    inline_quiz = _source(INLINE_QUIZ)

    for required in (
        'data-testid="chat-quiz-context"',
        "quizQuestion.prompt",
        "quizSourceTitle",
        "openQuizSource",
        "quizResourceLocation",
        "question_version_id",
        "course_id",
        "进入测验题资源作答",
        "作答、提交、判分和历史记录统一在测验题资源中完成",
        "quiz_follow_up",
        "attempt_id",
        "createIfEmpty: !quizResourceId.value",
    ):
        assert required in chat
    for forbidden in (
        "InlineQuizCard",
        "handleQuizSubmitted",
        "handleQuizFollowUp",
        "submitM5AssessmentAttempt",
        'data-testid="chat-inline-quiz-context"',
    ):
        assert forbidden not in chat

    assert "import InlineQuizCard" in quiz_workspace
    assert '<InlineQuizCard' in quiz_workspace
    assert '@submitted="handleSubmitted"' in quiz_workspace
    assert '@follow-up="openFollowUp"' in quiz_workspace
    for context_key in ("quiz_resource_id", "question_version_id", "attempt_id", "quiz_follow_up"):
        assert context_key in quiz_workspace
    assert "submitM5AssessmentAttempt" in inline_quiz
