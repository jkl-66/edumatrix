from __future__ import annotations

import asyncio
from uuid import uuid4

import httpx
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

import knowledge_api
from app.main import app
from app.resource_bundles import ResourceBundleError, _profile_snapshot
from app.database import DBCourse, DBProfileSnapshot, DBUser, SessionLocal
from tests.api_test_helpers import auth_headers


class _StreamContext:
    def __init__(self, response=None, error=None):
        self.response = response
        self.error = error

    async def __aenter__(self):
        if self.error:
            raise self.error
        return self.response

    async def __aexit__(self, *_args):
        return False


class _Response:
    def __init__(self, status_code=200, body=b"parsed material", content_type="text/markdown"):
        self.status_code = status_code
        self.headers = {"content-length": str(len(body)), "content-type": content_type}
        self.url = "https://public.example/material.md"
        self.history = []
        self._body = body

    async def aiter_bytes(self, _chunk_size=65536):
        yield self._body


def test_shared_remote_download_retries_timeout_then_succeeds(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(knowledge_api, "_validated_public_url", lambda value: value)
    calls = []
    contexts = iter([
        _StreamContext(error=httpx.ReadTimeout("upstream timeout")),
        _StreamContext(response=_Response()),
    ])

    def stream(_client, *_args, **_kwargs):
        calls.append(1)
        return next(contexts)

    monkeypatch.setattr(httpx.AsyncClient, "stream", stream)
    raw, final_url, content_type = asyncio.run(
        knowledge_api._download_remote_bytes(
            url="https://public.example/material.md",
            headers={"User-Agent": "test"},
        )
    )

    assert calls == [1, 1]
    assert raw == b"parsed material"
    assert final_url.endswith("material.md")
    assert content_type == "text/markdown"


def test_shared_remote_download_reports_permanent_http_failure_after_bounded_retry(
    monkeypatch: pytest.MonkeyPatch,
):
    monkeypatch.setattr(knowledge_api, "_validated_public_url", lambda value: value)
    calls = []
    contexts = iter([
        _StreamContext(response=_Response(status_code=503)),
        _StreamContext(response=_Response(status_code=503)),
    ])

    def stream(_client, *_args, **_kwargs):
        calls.append(1)
        return next(contexts)

    monkeypatch.setattr(httpx.AsyncClient, "stream", stream)
    with pytest.raises(HTTPException) as raised:
        asyncio.run(
            knowledge_api._download_remote_bytes(
                url="https://public.example/material.md",
                headers={"User-Agent": "test"},
            )
        )

    assert len(calls) == 2
    assert raised.value.status_code == 502
    assert raised.value.detail["code"] == "download_http_503"
    assert raised.value.detail["retryable"] is True
    assert "自动重试 1 次" in raised.value.detail["message"]


def test_personal_course_creation_bootstraps_idempotent_course_profile_snapshot():
    username = f"course_profile_repair_{uuid4().hex[:10]}"
    with TestClient(app) as client:
        headers = auth_headers(client, username)
        payload = {
            "title": "课程画像快照修复验证",
            "subject": "资料导入",
            "description": "创建课程后应有独立画像上下文",
        }
        first = client.post("/api/knowledge/courses", headers=headers, json=payload)
        assert first.status_code == 201, first.text
        course_id = first.json()["course"]["id"]
        snapshot_id = first.json()["profile_snapshot_id"]
        assert snapshot_id

        replay = client.post("/api/knowledge/courses", headers=headers, json=payload)
        assert replay.status_code == 201, replay.text
        assert replay.json()["created"] is False
        assert replay.json()["profile_snapshot_id"] == snapshot_id

        with SessionLocal() as db:
            rows = [
                row
                for row in db.query(DBProfileSnapshot).filter_by(
                    id=snapshot_id,
                ).all()
                if (row.snapshot or {}).get("course_id") == course_id
            ]
            assert len(rows) == 1
            assert rows[0].owner_public_id == db.query(
                DBCourse
            ).filter_by(id=course_id).one().owner_public_id
            assert (rows[0].snapshot or {}).get("mastery_status") == "awaiting_assessment"


def test_resource_profile_snapshot_rejects_a_different_course():
    username = f"course_profile_scope_{uuid4().hex[:10]}"
    with TestClient(app) as client:
        headers = auth_headers(client, username)
        first = client.post(
            "/api/knowledge/courses",
            headers=headers,
            json={"title": "画像课程一", "subject": "资料"},
        )
        second = client.post(
            "/api/knowledge/courses",
            headers=headers,
            json={"title": "画像课程二", "subject": "资料"},
        )
        assert first.status_code == 201 and second.status_code == 201
        course_one = first.json()["course"]["id"]
        course_two = second.json()["course"]["id"]
        profile_one = first.json()["profile_snapshot_id"]

        with SessionLocal() as db:
            owner = db.query(DBCourse).filter_by(id=course_one).one().owner_public_id
            actor = db.query(DBUser).filter_by(public_id=owner).one()
            with pytest.raises(ResourceBundleError) as raised:
                _profile_snapshot(db, actor, profile_one, course_id=course_two)
            assert raised.value.code == "resource_generation.profile_course_conflict"
