import json
from uuid import uuid4

import app.source_admission as admission
import knowledge_api
from app.database import DBCourse, DBProfileSnapshot, DBUser, SessionLocal
from app.main import app
from fastapi.testclient import TestClient
from tests.api_test_helpers import auth_headers
from web_search_api import WebSearchResults


class _DeepSeekQueryBackend:
    provider = "openai"
    model = "deepseek-v4-flash"
    thinking_mode = "max"
    reasoning_effort = "max"


class _SwarmContainer:
    """Mirror the factory result: orchestration object with a text backend."""

    def __init__(self, backend):
        self.llm = backend


def test_discovery_endpoint_projects_swarm_text_backend_for_profile_query(monkeypatch):
    suffix = uuid4().hex[:10]
    username = f"noc_t12_{suffix}"
    course_id = f"noc-t12-course-{suffix}"
    snapshot_id = f"noc-t12-snapshot-{suffix}"
    backend = _DeepSeekQueryBackend()
    captured_backend = []

    async def fake_audited(llm, *, user_prompt, **_kwargs):
        # The endpoint must pass the configured backend, not the Swarm container.
        assert llm is backend
        captured_backend.append(llm)
        payload = json.loads(user_prompt)
        return json.dumps(
            {
                "query": f"{payload['course']['title']} {payload['profile']['weak_directions'][0]} 公开资料",
                "focus_terms": [payload["profile"]["weak_directions"][0]],
                "rationale": "按当前课程画像生成联网检索词",
            },
            ensure_ascii=False,
        )

    async def fake_search(query, *, max_results):
        return WebSearchResults(
            [{"title": "画像推荐资料", "url": "https://example.test/t12", "snippet": query}]
        )

    monkeypatch.setattr(admission, "audited_legacy_text_call", fake_audited)
    monkeypatch.setattr(admission, "_perform_web_search", fake_search)
    monkeypatch.setattr(
        knowledge_api,
        "build_swarm_from_headers",
        lambda _headers: _SwarmContainer(backend),
    )

    with TestClient(app) as client:
        headers = auth_headers(client, username)
        with SessionLocal() as session:
            user = session.query(DBUser).filter_by(username=username).one()
            session.add(
                DBCourse(
                    id=course_id,
                    version="1",
                    title="NOC-T12 画像课程",
                    subject="机器学习",
                    description="用于画像联网 Query 回归",
                    visibility="public",
                    status="published",
                    owner_public_id=user.public_id,
                    manifest_version="noc-t12-v1",
                    manifest_data={"course_goals": ["掌握画像驱动检索"]},
                )
            )
            session.add(
                DBProfileSnapshot(
                    id=snapshot_id,
                    owner_public_id=user.public_id,
                    legacy_student_id=username,
                    profile_version="profile.continuous.v1",
                    snapshot={
                        "course_id": course_id,
                        "weak_points": ["检索排序"],
                        "learning_goals": ["理解课程资料发现"],
                    },
                    content_hash=f"hash-{suffix}",
                    trace_id=f"trace-{suffix}",
                )
            )
            session.commit()

        response = client.get(
            "/api/knowledge/discovery/search",
            params={
                "q": "教材",
                "course_id": course_id,
                "profile_snapshot_id": snapshot_id,
            },
            headers=headers,
        )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert captured_backend == [backend]
    assert payload["generatedQuery"] == "NOC-T12 画像课程 检索排序 公开资料"
    assert payload["queryPlan"]["model"] == {
        "provider": "openai",
        "model": "deepseek-v4-flash",
        "thinking": "enabled",
        "reasoning_effort": "max",
        "allow_fallback": False,
    }
    assert payload["items"][0]["url"] == "https://example.test/t12"
