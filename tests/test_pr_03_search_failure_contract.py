from __future__ import annotations

import asyncio

import httpx
from fastapi.testclient import TestClient
from unittest.mock import AsyncMock

from app.main import app
from app.source_admission import search_web_materials
from app.database import DBWebSourceCandidate, DBUser, SessionLocal
from tests.api_test_helpers import auth_headers
from web_search_api import WebSearchResults, _perform_web_search


class _FailingSearchClient:
    def __init__(self, *_args, **_kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False

    async def post(self, *_args, **_kwargs):
        raise httpx.ConnectError("offline")

    async def get(self, *_args, **_kwargs):
        raise httpx.ConnectError("offline")


class _EmptySearchResponse:
    status_code = 200
    text = ""
    encoding = None


class _EmptySearchClient:
    def __init__(self, *_args, **_kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False

    async def post(self, *_args, **_kwargs):
        return _EmptySearchResponse()

    async def get(self, *_args, **_kwargs):
        return _EmptySearchResponse()


class _MixedSearchClient(_EmptySearchClient):
    calls = 0

    async def post(self, *_args, **_kwargs):
        type(self).calls += 1
        if type(self).calls == 1:
            raise httpx.ConnectError("duckduckgo offline")
        return _EmptySearchResponse()


def test_all_search_providers_fail_without_placeholder(monkeypatch):
    monkeypatch.setattr(httpx, "AsyncClient", _FailingSearchClient)

    results = asyncio.run(_perform_web_search("机器学习教材", max_results=8))

    assert isinstance(results, WebSearchResults)
    assert results.status == "provider_failed"
    assert results == []
    assert not any(item.get("url") for item in results)


def test_successful_providers_with_no_matches_return_no_results(monkeypatch):
    monkeypatch.setattr(httpx, "AsyncClient", _EmptySearchClient)

    results = asyncio.run(_perform_web_search("没有匹配的课程资料", max_results=8))

    assert results.status == "no_results"
    assert results == []


def test_single_provider_failure_falls_back_to_no_results(monkeypatch):
    _MixedSearchClient.calls = 0
    monkeypatch.setattr(httpx, "AsyncClient", _MixedSearchClient)

    results = asyncio.run(_perform_web_search("单提供方失败测试", max_results=8))

    assert results.status == "no_results"
    assert results == []


def test_discovery_projects_provider_failure_and_preserves_query(monkeypatch):
    monkeypatch.setattr(
        "app.source_admission._perform_web_search",
        AsyncMock(return_value=WebSearchResults(status="provider_failed")),
    )

    with TestClient(app) as client:
        headers = auth_headers(client, "pr03_provider_failure")
        before = _candidate_count("pr03_provider_failure")
        response = client.get(
            "/api/knowledge/discovery/search",
            params={"q": "机器学习教材", "max_results": 8},
            headers=headers,
        )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["status"] == "provider_failed"
    assert payload["query"] == "机器学习教材"
    assert payload["items"] == []
    assert "暂时不可用" in payload["message"]
    assert _candidate_count("pr03_provider_failure") == before


def test_discovery_empty_results_filter_invalid_urls_without_candidate_creation(monkeypatch):
    monkeypatch.setattr(
        "app.source_admission._perform_web_search",
        AsyncMock(return_value=[
            {"title": "无原站", "url": "", "snippet": "不可保存"},
            {"title": "本地路径", "url": "file:///tmp/course.md", "snippet": "不可保存"},
        ]),
    )
    payload = asyncio.run(
        search_web_materials(
            "机器学习教材",
            max_results=8,
        )
    )
    assert payload["status"] == "no_results"
    assert payload["items"] == []
    assert payload["filteredResultCount"] == 2


def test_frontend_distinguishes_provider_failure_from_empty_result():
    source = open(
        "frontend/src/views/KnowledgeDiscoveryWorkspace.vue",
        encoding="utf-8",
    ).read()
    assert "payload.status === 'provider_failed'" in source
    assert "联网搜索没有完成" in source
    assert "没有找到带真实原站地址的结果" in source
    assert "搜索词和已有候选已保留" in source


def _candidate_count(username: str) -> int:
    with SessionLocal() as session:
        user = session.query(DBUser).filter_by(username=username).one_or_none()
        if user is None:
            return 0
        return session.query(DBWebSourceCandidate).filter_by(owner_public_id=user.public_id).count()
