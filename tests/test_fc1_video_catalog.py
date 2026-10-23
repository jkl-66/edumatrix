from fastapi.testclient import TestClient

from app.main import app
from tests.api_test_helpers import TEST_PASSWORD, auth_headers


def login(client, username="fc_video_catalog_owner"):
    auth_headers(client, username)
    row = client.post("/api/auth/login", data={"username": username, "password": TEST_PASSWORD})
    return {"Authorization": "Bearer " + row.json()["access_token"]}


def test_catalog_is_authenticated_local_whitelist_with_license_boundaries():
    with TestClient(app) as client:
        assert client.get("/api/v1/video-catalog").status_code == 401
        headers = login(client)
        response = client.get("/api/v1/video-catalog", headers=headers)
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["schema_version"] == "fc.video-catalog-response.v1"
        assert body["total"] == body["manifest"]["item_count"] >= 6
        assert len(body["manifest"]["sha256"]) == 64
        assert body["catalog_policy"]["distribution"] == "metadata_only"
        for item in body["items"]:
            assert item["url"].startswith("https://")
            assert item["license_status"] in {"reference_only_unverified", "repository_license_required", "platform_link_only"}
            assert any(
                marker in item["license_label"]
                for marker in ("不导入", "不下载", "不缓存", "不转存", "未获", "须按来源")
            )
            assert item["source_author"] and item["language"] and item["topics"] and item["selection_rationale"]


def test_catalog_filters_and_unknown_source_are_truthful():
    with TestClient(app) as client:
        headers = login(client, "fc_video_catalog_filter_owner")
        chinese = client.get("/api/v1/video-catalog", params={"language": "Chinese"}, headers=headers)
        assert chinese.status_code == 200
        assert chinese.json()["total"] == 1
        assert chinese.json()["items"][0]["source_key"] == "bilibili-watermelon-book-reference"
        filtered = client.get("/api/v1/video-catalog", params={"topic": "SHAP"}, headers=headers)
        assert filtered.status_code == 200 and filtered.json()["total"] == 1
        empty = client.get("/api/v1/video-catalog", params={"query": "not-a-known-resource"}, headers=headers)
        assert empty.status_code == 200 and empty.json()["items"] == []
        missing = client.get("/api/v1/video-catalog/not-real", headers=headers)
        assert missing.status_code == 404
        assert missing.json()["detail"]["code"] == "video.catalog_not_found"
