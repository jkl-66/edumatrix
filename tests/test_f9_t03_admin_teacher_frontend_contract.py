from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ROUTER = ROOT / "frontend" / "src" / "router" / "index.js"
APP = ROOT / "frontend" / "src" / "App.vue"
INTERVENTIONS = ROOT / "frontend" / "src" / "views" / "TeacherInterventions.vue"
ADMIN_ACCOUNTS = ROOT / "frontend" / "src" / "views" / "AdminAccounts.vue"
ADMIN_MODELS = ROOT / "frontend" / "src" / "views" / "ModelOperationsWorkspace.vue"
ADMIN_SYSTEM = ROOT / "frontend" / "src" / "views" / "AdminSystem.vue"
CONTENT_REVIEW = ROOT / "frontend" / "src" / "views" / "ContentReviewWorkspace.vue"
CONTENT_REVIEW_API = ROOT / "frontend" / "src" / "api" / "contentReview.js"


def source(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_teacher_assessment_and_intervention_have_separate_task_routes():
    router = source(ROUTER)
    app = source(APP)

    assert "path: '/teacher/assessment', name: 'TeacherAssessment', component: FormalExamWorkspace" in router
    assert "path: '/teacher/interventions', name: 'TeacherInterventions', component: TeacherInterventions" in router
    assert "{ path: '/teacher/assessment', label: '测评管理', icon: ListChecks }" in app
    assert "{ path: '/teacher/interventions', label: '干预任务', icon: ClipboardCheck }" in app
    assert "label: '测评与干预'" not in app


def test_teacher_intervention_page_uses_authorized_courses_and_evidence():
    page = source(INTERVENTIONS)

    for required in (
        "getTeacherCourses",
        "getTeacherStudent",
        "getM6TeacherInterventions",
        "publishM6TeacherIntervention",
        "confirmM6TeacherIntervention",
        'data-testid="teacher-interventions-page"',
        "AI 建议的公开校验摘要",
        "发布只增加学习路径任务，不会直接改变掌握度",
    ):
        assert required in page

    for forbidden in (
        "demo-course-rag-trust-v1",
        "bootstrapM6TrainingDemo",
        "初始化课程学员",
        "JSON.stringify(detail",
        "system_prompt",
        "api_key",
        "chain_of_thought",
        "raw_log",
    ):
        assert forbidden not in page

    import re

    numeric_font_sizes = [int(value) for value in re.findall(r"font-size:\s*(\d+)px", page)]
    assert numeric_font_sizes and min(numeric_font_sizes) >= 14
    for forbidden_color in ("#356b50", "#285a42", "#2f5943", "#2d5b43"):
        assert forbidden_color not in page.lower()


def test_admin_routes_use_three_minimal_task_pages():
    router = source(ROUTER)

    assert "const AdminAccounts = () => import('../views/AdminAccounts.vue')" in router
    assert "const AdminSystem = () => import('../views/AdminSystem.vue')" in router
    assert "path: '/admin/accounts', name: 'AdminAccounts', component: AdminAccounts" in router
    assert "path: '/admin/models', name: 'AdminModels', component: ModelOperationsWorkspace" in router
    assert "path: '/admin/system', name: 'AdminSystem', component: AdminSystem" in router
    assert "path: '/admin/accounts', name: 'AdminAccounts', component: AdvancedCapabilities" not in router
    assert "path: '/admin/system', name: 'AdminSystem', component: Settings" not in router


def test_admin_account_page_limits_roles_and_recovers_conflicts():
    page = source(ADMIN_ACCOUNTS)

    for required in (
        "getAdminAccounts",
        "updateAdminAccount",
        'data-testid="admin-accounts-page"',
        "刷新并保留修改",
        "已载入账号的最新版本，您的修改仍保留",
        "value: 'student'",
        "value: 'teacher'",
        "value: 'admin'",
        "overflow-wrap: anywhere",
    ):
        assert required in page

    for forbidden in ("assistant", "visitor", "enterprise", "judge"):
        assert forbidden not in page.lower()


def test_admin_model_page_only_exposes_sanitized_configuration_and_health():
    page = source(ADMIN_MODELS)

    for required in (
        "getAdminModels",
        'data-testid="admin-models-page"',
        "三个配置槽位",
        "认证状态",
        "容量状态",
        "限流状态",
        "超时状态",
        "不会发起模型调用",
    ):
        assert required in page

    for forbidden in (
        "getModelOperationsDashboard",
        "downloadModelOperations",
        "recent_calls",
        "quota_buckets",
        "input_summary",
        "provider",
        "trace_id",
        "Token",
        "成本",
        "配额",
        "SLA",
    ):
        assert forbidden not in page


def test_admin_system_page_preserves_results_and_replays_only_failed_work():
    page = source(ADMIN_SYSTEM)

    for required in (
        "getAdminSystem",
        "retryAdminTask",
        "cancelAdminTask",
        'data-testid="admin-system-page"',
        "失败任务只重试失败步骤",
        "已有结果始终保留",
        "失败不会被显示为完成",
        "重试失败步骤",
        "最近后台操作",
        "beforeSummary",
        "afterSummary",
        '<details class="audit-panel">',
    ):
        assert required in page

    for forbidden in ("raw_log", "system_prompt", "api_key", "trace_id", "worker", "lease"):
        assert forbidden not in page.lower()


def test_admin_pages_inherit_f1_visual_floor():
    import re

    for path in (ADMIN_ACCOUNTS, ADMIN_MODELS, ADMIN_SYSTEM):
        page = source(path)
        numeric_font_sizes = [int(value) for value in re.findall(r"font-size:\s*(\d+)px", page)]
        assert not numeric_font_sizes or min(numeric_font_sizes) >= 14
        assert "linear-gradient" not in page
        assert "radial-gradient" not in page
        assert "backdrop-filter" not in page
        for forbidden_color in ("#356b50", "#285a42", "#2f5943", "#2d5b43", "#60a5fa"):
            assert forbidden_color not in page.lower()


def test_content_review_page_exposes_provenance_public_audit_and_conflict_recovery():
    page = source(CONTENT_REVIEW)
    api = source(CONTENT_REVIEW_API)

    for required in (
        "getContentReviewCase",
        'data-testid="content-review-page"',
        "grid-template-columns: 340px minmax(0, 1fr)",
        "版本内容",
        "可定位来源",
        "质量检查",
        "声明支持",
        "公开校验摘要",
        "item.candidateSummary",
        "item.disagreement",
        "item.validation",
        "item.revision",
        "item.decisionSummary",
        "未提交的审核理由仍保留",
        "primary: false",
        "primary: true",
    ):
        assert required in page

    assert "/v1/content-review/cases/${encodeURIComponent(id)}" in api
    assert "证据与版本检查完成，按演示审核流程处理。" not in page
    for forbidden in ("system_prompt", "api_key", "chain_of_thought", "raw_log"):
        assert forbidden not in page.lower()


def test_content_review_page_inherits_f1_visual_floor():
    import re

    page = source(CONTENT_REVIEW)
    numeric_font_sizes = [int(value) for value in re.findall(r"font-size:\s*(\d+)px", page)]
    assert numeric_font_sizes and min(numeric_font_sizes) >= 14
    for forbidden in ("linear-gradient", "radial-gradient", "backdrop-filter"):
        assert forbidden not in page
    for forbidden_color in ("#356b50", "#285a42", "#2f5943", "#2d5b43", "#60a5fa"):
        assert forbidden_color not in page.lower()
