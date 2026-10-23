from __future__ import annotations

from unittest.mock import AsyncMock

from fastapi.testclient import TestClient

import knowledge_api

from app.database import (
    DBCourse,
    DBCourseMembership,
    DBLearningEvent,
    DBPathNode,
    DBProfileSnapshot,
    DBSourceRef,
    DBUser,
    DBWebSourceCandidate,
    SessionLocal,
)
from app.main import app
from tests.api_test_helpers import auth_headers


FLAGSHIP_COURSE_ID = "course-machine-learning-foundations-v1"


def _protected_counts() -> dict[str, int]:
    with SessionLocal() as session:
        return {
            "events": session.query(DBLearningEvent).count(),
            "snapshots": session.query(DBProfileSnapshot).count(),
            "path_nodes": session.query(DBPathNode).count(),
            "source_refs": session.query(DBSourceRef).count(),
        }


def test_course_graph_uses_only_canonical_facts_and_opens_reader() -> None:
    with TestClient(app) as client:
        headers = auth_headers(client, "f7_t03_graph_reader")
        before = _protected_counts()

        response = client.get(
            f"/api/knowledge/courses/{FLAGSHIP_COURSE_ID}/graph",
            headers=headers,
        )

        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload["schemaVersion"] == "edumatrix.course-knowledge-graph.v1"
        assert payload["status"] == "ready"
        assert payload["course"]["id"] == FLAGSHIP_COURSE_ID
        assert payload["statistics"]["chapterCount"] == 12
        assert payload["statistics"]["sourceCount"] == 12
        assert payload["statistics"]["nodeCount"] == len(payload["nodes"])
        assert payload["statistics"]["edgeCount"] == len(payload["edges"])
        assert len({item["id"] for item in payload["nodes"]}) == len(payload["nodes"])
        assert len({item["id"] for item in payload["edges"]}) == len(payload["edges"])
        assert {item["relationType"] for item in payload["edges"]} >= {
            "contains",
            "teaches",
            "grounds",
        }
        assert set(payload["projectionModes"]) == {"graph", "relationship_projection"}
        assert "联网候选不会进入本图谱" in payload["authorityBoundary"]
        assert not any(node["id"].startswith("webcand:") for node in payload["nodes"])

        source_node = next(
            node
            for node in payload["nodes"]
            if node["nodeType"] == "source" and node["sourceRefId"]
        )
        reader = client.get(
            f"/api/v1/document-reader/documents/{source_node['sourceDocumentId']}",
            headers=headers,
        )
        assert reader.status_code == 200, reader.text
        assert reader.json()["course"]["id"] == FLAGSHIP_COURSE_ID
        assert reader.json()["source_refs"]
        assert _protected_counts() == before


def test_course_graph_requires_authentication_and_course_access() -> None:
    with TestClient(app) as client:
        assert client.get(
            f"/api/knowledge/courses/{FLAGSHIP_COURSE_ID}/graph"
        ).status_code == 401
        owner_headers = auth_headers(client, "f7_t03_private_owner")
        outsider_headers = auth_headers(client, "f7_t03_private_outsider")
        with SessionLocal() as session:
            owner = session.query(DBUser).filter_by(username="f7_t03_private_owner").one()
            course = DBCourse(
                id="f7-t03-private-course",
                version="1",
                title="私有课程图谱",
                description="验证课程图谱权限",
                visibility="private",
                status="published",
                owner_public_id=owner.public_id,
                manifest_version="f7-t03-private-v1",
            )
            session.merge(course)
            session.merge(DBCourseMembership(
                course_id=course.id,
                user_public_id=owner.public_id,
                role="student",
                status="active",
            ))
            session.commit()

        owner = client.get(
            "/api/knowledge/courses/f7-t03-private-course/graph",
            headers=owner_headers,
        )
        outsider = client.get(
            "/api/knowledge/courses/f7-t03-private-course/graph",
            headers=outsider_headers,
        )
        assert owner.status_code == 200, owner.text
        assert owner.json()["status"] == "empty"
        assert outsider.status_code == 403


def test_discovery_filters_unusable_results_and_reports_network_failure(monkeypatch) -> None:
    search = AsyncMock(return_value=[
        {
            "title": "公开机器学习讲义",
            "url": "https://example.edu/course/notes.pdf",
            "snippet": "课程讲义",
        },
        {"title": "无原站保底文本", "url": "", "snippet": "不可保存"},
        {
            "title": "重复地址",
            "url": "https://example.edu/course/notes.pdf",
            "snippet": "重复",
        },
    ])
    monkeypatch.setattr("app.source_admission._perform_web_search", search)
    with TestClient(app) as client:
        headers = auth_headers(client, "f7_t03_discovery_reader")
        before = _protected_counts()
        response = client.get(
            "/api/knowledge/discovery/search",
            params={"q": "机器学习教材", "max_results": 8},
            headers=headers,
        )
        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload["query"] == "机器学习教材"
        assert len(payload["items"]) == 1
        item = payload["items"][0]
        assert item["url"] == "https://example.edu/course/notes.pdf"
        assert item["fileFormat"] == "pdf"
        assert item["licenseStatus"] == "unknown"
        assert item["authoritative"] is False
        assert payload["filteredResultCount"] == 2
        with SessionLocal() as session:
            assert session.query(DBWebSourceCandidate).filter_by(
                owner_public_id=session.query(DBUser).filter_by(
                    username="f7_t03_discovery_reader"
                ).one().public_id
            ).count() == 0
        assert _protected_counts() == before

        monkeypatch.setattr(
            "app.source_admission._perform_web_search",
            AsyncMock(side_effect=TimeoutError("offline")),
        )
        failed = client.get(
            "/api/knowledge/discovery/search",
            params={"q": "机器学习教材"},
            headers=headers,
        )
        assert failed.status_code == 503, failed.text
        assert failed.json()["detail"]["query"] == "机器学习教材"


def test_candidate_admission_is_owner_scoped_license_gated_and_imports_real_course_source(monkeypatch) -> None:
    with TestClient(app) as client:
        headers = auth_headers(client, "f7_t03_candidate_owner")
        other_headers = auth_headers(client, "f7_t03_candidate_other")
        before = _protected_counts()
        course_response = client.post(
            "/api/knowledge/courses",
            headers=headers,
            json={
                "title": "个人机器学习课程",
                "subject": "机器学习",
                "description": "验证联网来源的真实导入闭环",
            },
        )
        assert course_response.status_code == 201, course_response.text
        course_id = course_response.json()["course"]["id"]
        candidate_payload = {
            "query": "机器学习课程",
            "title": "开放课程讲义",
            "url": "https://open.example.org/ml/guide.md",
            "snippet": "公开课程目录和实验说明",
        }
        created = client.post(
            "/api/knowledge/discovery/candidates",
            headers=headers,
            json=candidate_payload,
        )
        replay = client.post(
            "/api/knowledge/discovery/candidates",
            headers=headers,
            json=candidate_payload,
        )
        assert created.status_code == 200, created.text
        assert created.json()["created"] is True
        assert replay.status_code == 200, replay.text
        assert replay.json()["created"] is False
        candidate = created.json()["candidate"]
        assert candidate["reviewStatus"] == "pending_review"
        assert candidate["licenseStatus"] == "unknown"
        assert candidate["canAdmit"] is False
        assert candidate["resourceGenerationEligible"] is False
        assert "许可未确认" in candidate["blockers"]

        other_list = client.get(
            "/api/knowledge/discovery/candidates",
            headers=other_headers,
        )
        assert other_list.status_code == 200
        assert other_list.json()["items"] == []
        forbidden = client.post(
            f"/api/knowledge/discovery/candidates/{candidate['id']}/reject",
            headers=other_headers,
        )
        assert forbidden.status_code == 404

        blocked = client.post(
            f"/api/knowledge/discovery/candidates/{candidate['id']}/admit",
            headers=headers,
            json={
                "course_id": course_id,
                "author_or_organization": "开放课程组织",
                "license_status": "restricted",
                "license_text": "仅限原站阅读",
                "usage_hint": "不允许复制到课程库",
                "trust_level": "source_declared",
            },
        )
        assert blocked.status_code == 409
        listed = client.get(
            "/api/knowledge/discovery/candidates",
            params={"review_status": "license_required"},
            headers=headers,
        )
        assert [item["id"] for item in listed.json()["items"]] == [candidate["id"]]

        async def fake_download(**_kwargs):
            return (
                b"# Open machine learning guide\n\nThis is a complete public lesson used to verify real import.",
                "open-machine-learning-guide.md",
                "https://open.example.org/ml/guide.md",
            )

        monkeypatch.setattr(knowledge_api, "_download_remote_material", fake_download)

        admitted = client.post(
            f"/api/knowledge/discovery/candidates/{candidate['id']}/admit",
            headers=headers,
            json={
                "course_id": course_id,
                "author_or_organization": "开放课程组织",
                "license_status": "open_permissive",
                "license_text": "CC BY 4.0",
                "usage_hint": "允许个人学习引用并保留署名",
                "trust_level": "source_declared",
            },
        )
        assert admitted.status_code == 200, admitted.text
        imported = admitted.json()["candidate"]
        assert imported["reviewStatus"] == "imported"
        assert imported["importedVersion"].endswith("-v1")
        assert imported["authorityScope"] == "personal_course_source"
        assert imported["authoritative"] is False
        assert imported["resourceGenerationEligible"] is True
        assert admitted.json()["document"]["course_id"] == course_id
        assert imported["importResult"]["source_document_id"] == admitted.json()["document"]["source_document_id"]
        assert client.post(
            f"/api/knowledge/discovery/candidates/{candidate['id']}/admit",
            headers=headers,
            json={
                "course_id": course_id,
                "license_status": "open_permissive",
                "usage_hint": "允许个人学习引用并保留署名",
            },
        ).json()["created"] is False

        withdrawn = client.post(
            f"/api/knowledge/discovery/candidates/{candidate['id']}/withdraw",
            headers=headers,
        )
        assert withdrawn.status_code == 200
        assert withdrawn.json()["candidate"]["reviewStatus"] == "withdrawn"
        after = _protected_counts()
        assert after["events"] == before["events"]
        assert after["snapshots"] == before["snapshots"]
        assert after["path_nodes"] == before["path_nodes"]
        assert after["source_refs"] > before["source_refs"]

        invalid = client.post(
            "/api/knowledge/discovery/candidates",
            headers=headers,
            json={**candidate_payload, "url": "file:///tmp/course.md"},
        )
        assert invalid.status_code == 422
