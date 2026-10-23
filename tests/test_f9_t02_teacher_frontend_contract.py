from __future__ import annotations

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TEACHER = ROOT / "frontend" / "src" / "views" / "Teacher.vue"
API = ROOT / "frontend" / "src" / "api" / "teacher.js"
ROUTER = ROOT / "frontend" / "src" / "router" / "index.js"
APP = ROOT / "frontend" / "src" / "App.vue"
ROLE_LANDING = ROOT / "frontend" / "src" / "utils" / "roleLanding.js"


def source(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_five_teacher_routes_share_one_route_aware_workspace() -> None:
    router = source(ROUTER)
    teacher = source(TEACHER)

    for route_contract in (
        "path: '/teacher/overview', name: 'TeacherOverview', component: Teacher",
        "path: '/teacher/courses', name: 'TeacherCourses', component: Teacher",
        "path: '/teacher/courses/:courseId', name: 'TeacherCourseDetail', component: Teacher",
        "path: '/teacher/students', name: 'TeacherStudents', component: Teacher",
        "path: '/teacher/students/:studentId', name: 'TeacherStudentDetail', component: Teacher",
    ):
        assert route_contract in router

    assert "const TEACHING = ['teacher', 'admin']" in router
    assert "CourseGovernanceWorkspace" not in router
    for route_name in (
        "TeacherOverview", "TeacherCourses", "TeacherCourseDetail",
        "TeacherStudents", "TeacherStudentDetail",
    ):
        assert route_name in teacher


def test_teacher_client_uses_the_authenticated_v1_contract() -> None:
    api = source(API)
    for marker in (
        "buildHeaders",
        "'/v1/teacher/overview'",
        "'/v1/teacher/courses'",
        "'/v1/teacher/students'",
        "'/v1/teacher/interventions'",
        "course_id",
        "learner_public_id",
        "idempotency_key",
    ):
        assert marker in api


def test_teacher_navigation_excludes_assistant_as_a_formal_role() -> None:
    app = source(APP)
    role_landing = source(ROLE_LANDING)
    teacher_nav = re.search(r"const teacherNav = \[(.*?)\n\]", app, flags=re.DOTALL)
    assert teacher_nav
    for path in (
        "/teacher/overview", "/teacher/courses", "/teacher/students", "/teacher/interventions",
    ):
        assert path in teacher_nav.group(1)
    assert "role.value === 'teacher' || role.value === 'assistant'" not in app
    assert "if (role === 'teacher') return '/teacher/overview'" in role_landing
    assert "if (role === 'assistant') return '/landing'" in role_landing
    assert "role === 'teacher' || role === 'assistant'" not in role_landing
    assert "['student', 'teacher', 'assistant', 'admin']" not in source(ROUTER)


def test_clean_root_visit_preserves_landing_before_login() -> None:
    router = source(ROUTER)
    assert "if (to.path === '/') return '/landing'" in router
    assert "return { path: '/login', query: { redirect: to.fullPath } }" in router


def test_teacher_workspace_is_evidence_first_and_mastery_is_read_only() -> None:
    teacher = source(TEACHER)
    for marker in (
        'data-testid="teacher-workspace"',
        "待处理教学任务",
        "集中薄弱点",
        "需关注学生",
        "授权证据编号",
        "actionTitle(student.nextAction, student.evidenceMessage)",
        "actionTitle(point.nextAction)",
        "actionReason(point.nextAction)",
        "掌握度只读",
        "创建学习干预",
        "只增加路径任务，不会直接修改学生掌握度",
        "AI 建议的公开校验记录",
        "候选：",
        "分歧：",
        "校验：",
        "修订：",
        "决定：",
    ):
        assert marker in teacher

    assert "{{ student.nextAction || student.evidenceMessage }}" not in teacher
    assert "{{ point.nextAction }}" not in teacher

    for forbidden in (
        "updateMastery", "setMastery", 'v-model="mastery"', "冻结比赛", "演示指标", "企业治理", "专家认证",
        "系统提示词", "私有思维链", "原始 Agent 日志", "CompetitionDemoContextBand",
    ):
        assert forbidden not in teacher


def test_teacher_workspace_keeps_complete_honest_states() -> None:
    teacher = source(TEACHER)
    for marker in (
        "正在读取教学数据",
        "教学数据暂时无法读取",
        "已保留上一次读取结果",
        "暂无可查看课程",
        "证据不足",
        "重试创建干预",
        "该干预任务已经存在，没有重复创建",
        "当前没有可公开的协作证据",
    ):
        assert marker in teacher
    assert "getCompetitionDemoContext" not in teacher
    assert "getTeacherDashboard" not in teacher


def test_teacher_workspace_inherits_the_frozen_light_desktop_contract() -> None:
    teacher = source(TEACHER).lower()
    for required in (
        "var(--font-sans)",
        "var(--color-surface)",
        "var(--color-text)",
        "var(--color-accent)",
        "var(--color-border)",
        "border-radius: var(--radius-panel)",
        "border-radius: var(--radius-control)",
    ):
        assert required in teacher

    numeric_font_sizes = [int(value) for value in re.findall(r"font-size:\s*(\d+)px", teacher)]
    assert numeric_font_sizes
    assert min(numeric_font_sizes) >= 14

    for forbidden in (
        "linear-gradient", "radial-gradient", "backdrop-filter",
        "#10b981", "#22c55e", "#16a34a", "#0ea5e9", "#3b82f6",
        "#8b5cf6", "#a855f7", "#92400e", "#b45309", "#a16207",
        "green-", "emerald-", "lime-", "orange-", "amber-", "purple-", "indigo-",
    ):
        assert forbidden not in teacher
