import asyncio
import json
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

import app.source_admission as admission
import knowledge_api
from app.database import (
    DBCourse,
    DBLearningEvent,
    DBPathNode,
    DBProfileSnapshot,
    DBSourceRef,
    DBUser,
    DBWebSourceCandidate,
    SessionLocal,
)
from app.main import app
from web_search_api import WebSearchResults
from tests.api_test_helpers import auth_headers


class _DeepSeekQueryLLM:
    provider = "openai"
    model = "deepseek-v4-flash"
    thinking_mode = "max"
    reasoning_effort = "max"


def _profile(snapshot_id, *, learning_goal, weak_direction, course_goal="掌握课程核心概念"):
    return {
        "profile_snapshot_id": snapshot_id,
        "profile_version": "profile.continuous.v1",
        "course_goals": [course_goal],
        "learning_goals": [learning_goal],
        "weak_directions": [weak_direction],
        "preferences": ["先看案例"],
        "time_budget": "每周 3 小时",
    }


def _course():
    return {"course_id": "course-b27", "title": "机器学习导论", "course_goals": ["掌握课程核心概念"]}


def test_three_profiles_generate_different_query_and_ranked_results(monkeypatch):
    calls = []

    async def fake_audited(_llm, *, user_prompt, **_kwargs):
        payload = json.loads(user_prompt)
        profile = payload["profile"]
        weak = profile["weak_directions"][0]
        calls.append(weak)
        return json.dumps({
            "query": f"{payload['course']['title']} {profile['learning_goals'][0]} {weak} 公开讲义",
            "focus_terms": [weak, profile["learning_goals"][0]],
            "rationale": f"围绕 {weak} 和学习目标检索公开来源",
        }, ensure_ascii=False)

    async def fake_search(query, *, max_results):
        return WebSearchResults([
            {"title": f"{query} 讲义", "url": "https://example.test/shared", "snippet": query},
            {"title": "通用课程说明", "url": "https://example.test/common", "snippet": "课程概览"},
            {"title": "重复地址", "url": "https://example.test/shared/", "snippet": "duplicate"},
        ])

    monkeypatch.setattr(admission, "audited_legacy_text_call", fake_audited)
    monkeypatch.setattr(admission, "_perform_web_search", fake_search)
    llm = _DeepSeekQueryLLM()
    results = []
    for index, weak in enumerate(("卷积", "正则化", "梯度下降"), start=1):
        results.append(asyncio.run(admission.search_web_materials(
            "推荐学习资料",
            8,
            course_context=_course(),
            profile_context=_profile(f"ps-{index}", learning_goal=f"理解{weak}应用", weak_direction=weak),
            llm=llm,
            owner_public_id="user-b27",
        )))
    assert calls == ["卷积", "正则化", "梯度下降"]
    assert len({item["generatedQuery"] for item in results}) == 3
    assert all(item["profileBasis"]["status"] == "available" for item in results)
    assert all(item["queryPlan"]["model"]["model"] == "deepseek-v4-flash" for item in results)
    assert all(item["ranking"]["deduplicatedCount"] == 1 for item in results)
    assert all(len(item["items"]) == 2 for item in results)
    assert all(item["items"][0]["relevanceScore"] >= item["items"][1]["relevanceScore"] for item in results)


def test_missing_profile_is_explicit_and_preserves_user_query(monkeypatch):
    queries = []

    async def fake_search(query, *, max_results):
        queries.append(query)
        return WebSearchResults([{"title": "公开资料", "url": "https://example.test/a", "snippet": "资料"}])

    monkeypatch.setattr(admission, "_perform_web_search", fake_search)
    payload = asyncio.run(admission.search_web_materials(
        "机器学习公开讲义",
        4,
        course_context=_course(),
        profile_context={},
    ))
    assert queries == ["机器学习公开讲义"]
    assert payload["profileBasis"]["status"] == "missing"
    assert payload["queryPlan"]["source"] == "user_query_profile_missing"
    assert payload["generatedQuery"] == "机器学习公开讲义"
    assert payload["items"][0]["authoritative"] is False
    assert payload["authorityBoundary"].endswith("推荐本身不会改变 mastery/path。")


def test_profile_query_model_policy_and_invalid_output_are_retryable(monkeypatch):
    async def fake_audited(_llm, **_kwargs):
        return "not-json"

    async def fake_search(query, *, max_results):
        pytest.fail("invalid query plan must not call web search")

    monkeypatch.setattr(admission, "audited_legacy_text_call", fake_audited)
    monkeypatch.setattr(admission, "_perform_web_search", fake_search)
    with pytest.raises(admission.HTTPException) as raised:
        asyncio.run(admission.search_web_materials(
            "推荐资料", 4, course_context=_course(), profile_context=_profile("ps-invalid", learning_goal="理解原理", weak_direction="概念混淆"), llm=_DeepSeekQueryLLM(), owner_public_id="user-b27"
        ))
    assert raised.value.status_code == 503
    assert raised.value.detail["code"] == "profile_query_failed"

    class _WrongModel(_DeepSeekQueryLLM):
        model = "deepseek-chat"

    with pytest.raises(admission.HTTPException) as blocked:
        asyncio.run(admission.search_web_materials(
            "推荐资料", 4, course_context=_course(), profile_context=_profile("ps-policy", learning_goal="理解原理", weak_direction="概念混淆"), llm=_WrongModel(), owner_public_id="user-b27"
        ))
    assert blocked.value.status_code == 503
    assert blocked.value.detail["code"] == "profile_query_model_policy_blocked"


def test_provider_failure_keeps_generated_query_for_retry(monkeypatch):
    async def fake_audited(_llm, **_kwargs):
        return json.dumps({"query": "机器学习 正则化 公开资料", "focus_terms": ["正则化"], "rationale": "画像薄弱方向"}, ensure_ascii=False)

    async def failing_search(query, *, max_results):
        raise RuntimeError("provider offline")

    monkeypatch.setattr(admission, "audited_legacy_text_call", fake_audited)
    monkeypatch.setattr(admission, "_perform_web_search", failing_search)
    with pytest.raises(admission.HTTPException) as raised:
        asyncio.run(admission.search_web_materials(
            "推荐资料", 4, course_context=_course(), profile_context=_profile("ps-failure", learning_goal="理解原理", weak_direction="正则化"), llm=_DeepSeekQueryLLM(), owner_public_id="user-b27"
        ))
    assert raised.value.status_code == 503
    detail = raised.value.detail
    assert detail["code"] == "web_discovery_unavailable"
    assert detail["generatedQuery"] == "机器学习 正则化 公开资料"


def test_discovery_api_projects_course_profile_context_and_keeps_read_only_boundary(monkeypatch):
    suffix = uuid4().hex[:10]
    username = f"p1_b27_api_{suffix}"
    course_id = f"p1-b27-course-{suffix}"
    public_course_id = f"p1-b27-public-{suffix}"
    snapshot_id = f"p1-b27-snapshot-{suffix}"
    captured = []

    async def fake_audited(_llm, *, user_prompt, **_kwargs):
        payload = json.loads(user_prompt)
        captured.append(payload)
        weak = payload["profile"]["weak_directions"][0]
        return json.dumps({
            "query": f"{payload['course']['title']} {weak} 公开讲义",
            "focus_terms": [weak, payload["profile"]["learning_goals"][0]],
            "rationale": "按当前课程目标、学习目标和薄弱方向检索公开来源",
        }, ensure_ascii=False)

    async def fake_search(query, *, max_results):
        return WebSearchResults([
            {"title": "画像命中讲义", "url": "https://example.test/profile.pdf", "snippet": query},
            {"title": "通用资料", "url": "https://example.test/common", "snippet": "课程概览"},
        ])

    monkeypatch.setattr(admission, "audited_legacy_text_call", fake_audited)
    monkeypatch.setattr(admission, "_perform_web_search", fake_search)
    monkeypatch.setattr(knowledge_api, "build_swarm_from_headers", lambda _headers: _DeepSeekQueryLLM())

    with TestClient(app) as client:
        headers = auth_headers(client, username)
        with SessionLocal() as session:
            user = session.query(DBUser).filter_by(username=username).one()
            session.add(DBCourse(
                id=course_id,
                version="1",
                title="画像课程",
                subject="机器学习",
                description="课程说明",
                visibility="private",
                status="published",
                owner_public_id=user.public_id,
                manifest_version="p1-b27-v1",
                manifest_data={"course_goals": ["掌握卷积基础"]},
            ))
            session.add(DBCourse(
                id=public_course_id,
                version="1",
                title="公开课程",
                subject="机器学习",
                description="公开课程说明",
                visibility="public",
                status="published",
                owner_public_id=user.public_id,
                manifest_version="p1-b27-public-v1",
                manifest_data={"course_goals": ["掌握公开课程目标"]},
            ))
            session.add(DBProfileSnapshot(
                id=snapshot_id,
                owner_public_id=user.public_id,
                legacy_student_id=username,
                profile_version="profile.continuous.v1",
                snapshot={
                    "course_id": course_id,
                    "learning_goals": ["理解卷积应用"],
                    "weak_points": ["卷积"],
                    "interaction_preferences": ["先看案例"],
                    "weekly_time_budget": "每周 3 小时",
                },
                content_hash=f"hash-{suffix}",
                trace_id=f"trace-{suffix}",
            ))
            session.commit()

        with SessionLocal() as session:
            protected_before = {
                "events": session.query(DBLearningEvent).count(),
                "snapshots": session.query(DBProfileSnapshot).count(),
                "path_nodes": session.query(DBPathNode).count(),
                "source_refs": session.query(DBSourceRef).count(),
                "candidates": session.query(DBWebSourceCandidate).count(),
            }

        response = client.get(
            "/api/knowledge/discovery/search",
            params={"q": "推荐学习资料", "course_id": course_id, "profile_snapshot_id": snapshot_id},
            headers=headers,
        )
        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload["profileBasis"]["status"] == "available"
        assert payload["profileBasis"]["courseGoals"] == ["掌握卷积基础"]
        assert payload["profileBasis"]["learningGoals"] == ["理解卷积应用"]
        assert payload["profileBasis"]["weakDirections"] == ["卷积"]
        assert payload["queryPlan"]["model"]["model"] == "deepseek-v4-flash"
        assert payload["items"][0]["relevanceScore"] >= payload["items"][1]["relevanceScore"]
        assert captured[0]["course"]["course_goals"] == ["掌握卷积基础"]
        assert captured[0]["profile"]["weak_directions"] == ["卷积"]
        assert payload["authorityBoundary"].endswith("推荐本身不会改变 mastery/path。")

        with SessionLocal() as session:
            protected_after = {
                "events": session.query(DBLearningEvent).count(),
                "snapshots": session.query(DBProfileSnapshot).count(),
                "path_nodes": session.query(DBPathNode).count(),
                "source_refs": session.query(DBSourceRef).count(),
                "candidates": session.query(DBWebSourceCandidate).count(),
            }
        assert protected_after == protected_before

        first = client.post(
            "/api/knowledge/discovery/candidates",
            headers=headers,
            json={
                "query": payload["generatedQuery"],
                "title": payload["items"][0]["title"],
                "url": payload["items"][0]["url"],
                "snippet": payload["items"][0]["snippet"],
            },
        )
        replay = client.post(
            "/api/knowledge/discovery/candidates",
            headers=headers,
            json={
                "query": payload["generatedQuery"],
                "title": payload["items"][0]["title"],
                "url": payload["items"][0]["url"],
                "snippet": payload["items"][0]["snippet"],
            },
        )
        assert first.status_code == 200, first.text
        assert replay.status_code == 200, replay.text
        assert first.json()["created"] is True
        assert replay.json()["created"] is False
        assert replay.json()["candidate"]["authorityScope"] == "candidate_only"


def test_discovery_api_rejects_cross_owner_and_mismatched_profile_context(monkeypatch):
    suffix = uuid4().hex[:10]
    owner_name = f"p1_b27_owner_{suffix}"
    outsider_name = f"p1_b27_outsider_{suffix}"
    course_id = f"p1-b27-public-context-{suffix}"
    private_course_id = f"p1-b27-private-context-{suffix}"
    owner_snapshot_id = f"p1-b27-owner-snapshot-{suffix}"
    mismatch_snapshot_id = f"p1-b27-mismatch-snapshot-{suffix}"

    async def fake_search(_query, *, max_results):
        return WebSearchResults([])

    monkeypatch.setattr(admission, "_perform_web_search", fake_search)
    with TestClient(app) as client:
        owner_headers = auth_headers(client, owner_name)
        outsider_headers = auth_headers(client, outsider_name)
        with SessionLocal() as session:
            owner = session.query(DBUser).filter_by(username=owner_name).one()
            session.add(DBCourse(
                id=course_id, version="1", title="公开上下文课程", subject="机器学习",
                visibility="public", status="published", owner_public_id=owner.public_id,
                manifest_version="p1-b27-public-context-v1", manifest_data={"course_goals": ["目标"]},
            ))
            session.add(DBCourse(
                id=private_course_id, version="1", title="私有上下文课程", subject="机器学习",
                visibility="private", status="published", owner_public_id=owner.public_id,
                manifest_version="p1-b27-private-context-v1", manifest_data={"course_goals": ["私有目标"]},
            ))
            session.add(DBProfileSnapshot(
                id=owner_snapshot_id, owner_public_id=owner.public_id, legacy_student_id=owner_name,
                profile_version="profile.continuous.v1", snapshot={"course_id": course_id, "weak_points": ["卷积"]},
                content_hash=f"hash-owner-{suffix}", trace_id=f"trace-owner-{suffix}",
            ))
            session.add(DBProfileSnapshot(
                id=mismatch_snapshot_id, owner_public_id=owner.public_id, legacy_student_id=owner_name,
                profile_version="profile.continuous.v1", snapshot={"course_id": private_course_id, "weak_points": ["正则化"]},
                content_hash=f"hash-mismatch-{suffix}", trace_id=f"trace-mismatch-{suffix}",
            ))
            session.commit()

        outsider_course = client.get(
            "/api/knowledge/discovery/search",
            params={"q": "资料", "course_id": private_course_id},
            headers=outsider_headers,
        )
        assert outsider_course.status_code == 403

        outsider_profile = client.get(
            "/api/knowledge/discovery/search",
            params={"q": "资料", "course_id": course_id, "profile_snapshot_id": owner_snapshot_id},
            headers=outsider_headers,
        )
        assert outsider_profile.status_code == 403

        mismatch = client.get(
            "/api/knowledge/discovery/search",
            params={"q": "资料", "course_id": course_id, "profile_snapshot_id": mismatch_snapshot_id},
            headers=owner_headers,
        )
        assert mismatch.status_code == 409
