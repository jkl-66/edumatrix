from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app
from tests.api_test_helpers import auth_headers


CHAT_VUE = Path("frontend/src/views/Chat.vue")


def test_chat_course_picker_creates_a_new_context_branch() -> None:
    source = CHAT_VUE.read_text(encoding="utf-8")
    assert "pendingCourseIds" in source
    assert "finishCourseSelection" in source
    assert "await chatStore.createConversation" in source
    assert "courseContext.setChatCourseIds(next)" in source
    assert "@click=\"finishCourseSelection\"" in source
    assert "@click=\"openCoursePicker\"" in source
    assert "当前回答进行中，请完成或停止后再切换课程" in source


def test_course_branch_keeps_previous_conversation_unchanged() -> None:
    with TestClient(app) as client:
        headers = auth_headers(client, "b35-course-switch-contract")
        first = client.post(
            "/api/v1/chat/conversations",
            headers=headers,
            json={"course_id": "course-machine-learning-foundations-v1", "title": "课程 A"},
        )
        second = client.post(
            "/api/v1/chat/conversations",
            headers=headers,
            json={"title": "通用对话"},
        )
        assert first.status_code == 201, first.text
        assert second.status_code == 201, second.text
        assert first.json()["id"] != second.json()["id"]
        assert first.json()["courseId"] == "course-machine-learning-foundations-v1"
        assert second.json()["courseId"] is None
