from __future__ import annotations

import re
from pathlib import Path


APP = Path(__file__).parents[1] / "frontend" / "src" / "App.vue"


def _navigation(name: str) -> list[tuple[str, str]]:
    source = APP.read_text(encoding="utf-8")
    match = re.search(rf"const {name} = \[(.*?)\n\]", source, flags=re.DOTALL)
    assert match, f"missing navigation declaration: {name}"
    return re.findall(r"\{ path: '([^']+)', label: '([^']+)', icon: \w+ \}", match.group(1))


def test_f1_primary_navigation_matches_approved_role_contract():
    expected = {
        "studentNav": [
            ("/", "首页"),
            ("/profile", "个人中心"),
            ("/profile/learning", "学习画像"),
            ("/workspace", "学习空间"),
            ("/learn", "智能对话"),
            ("/knowledge", "知识库"),
            ("/marketplace", "学习市场"),
            ("/settings", "设置"),
        ],
        "teacherNav": [
            ("/teacher/overview", "教学总览"),
            ("/teacher/courses", "课程与资源"),
            ("/teacher/students", "学生学情"),
            ("/teacher/assessment", "测评管理"),
            ("/teacher/interventions", "干预任务"),
        ],
        "adminNav": [
            ("/admin/accounts", "账号权限"),
            ("/admin/models", "模型配置"),
            ("/admin/content-review", "内容审核"),
            ("/admin/system", "系统状态"),
        ],
    }
    for name, items in expected.items():
        assert _navigation(name) == items


def test_f1_primary_navigation_hides_internal_stage_and_enterprise_labels():
    labels = [label for name in ("studentNav", "teacherNav", "adminNav") for _, label in _navigation(name)]
    forbidden = (
        "M0", "M1", "M2", "M3", "M4", "M5", "M6", "M7", "M8",
        "评委旅程", "黄金闭环", "竞赛闭环", "对象检查", "企业", "集成", "专家认证",
    )
    assert all(token not in label for label in labels for token in forbidden)


def test_f1_role_selection_uses_only_the_current_role_navigation():
    source = APP.read_text(encoding="utf-8")
    assert "if (role.value === 'admin') return adminNav" in source
    assert "if (role.value === 'teacher') return teacherNav" in source
    assert "role.value === 'teacher' || role.value === 'assistant'" not in source
    assert "return studentNav" in source
    assert "operatorNav" not in source
