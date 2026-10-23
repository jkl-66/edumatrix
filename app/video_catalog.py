from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parents[1]
CATALOG_PATH = ROOT / "data" / "raw" / "videos_metadata" / "legal_video_catalog.json"
REQUIRED_FIELDS = {
    "source_key", "title", "url", "source_author", "source_type", "license_status",
    "license_label", "license_url", "language", "topics", "course_node", "selection_rationale",
}
ALLOWED_SOURCE_HOSTS = {
    "github.com", "ml-course.github.io", "mlvu.github.io", "slds-lmu.github.io",
    "uvaml1.github.io", "www.bilibili.com",
}


class VideoCatalogError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _load() -> dict[str, Any]:
    try:
        raw = CATALOG_PATH.read_bytes()
        payload = json.loads(raw.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise VideoCatalogError("video.catalog_unavailable", "视频目录元数据不可用") from exc
    if payload.get("schema_version") != "fc.video-catalog.v1" or not isinstance(payload.get("items"), list):
        raise VideoCatalogError("video.catalog_invalid", "视频目录元数据格式无效")
    seen: set[str] = set()
    for item in payload["items"]:
        if not isinstance(item, dict) or not REQUIRED_FIELDS <= set(item) or item["source_key"] in seen:
            raise VideoCatalogError("video.catalog_invalid", "视频目录条目无效")
        source_url = urlparse(str(item["url"]))
        if source_url.scheme != "https" or source_url.hostname not in ALLOWED_SOURCE_HOSTS or not isinstance(item["topics"], list):
            raise VideoCatalogError("video.catalog_source_rejected", "视频目录来源不符合安全白名单规则")
        seen.add(item["source_key"])
    payload["manifest"] = {
        "source_path": str(CATALOG_PATH.relative_to(ROOT)).replace("\\", "/"),
        "sha256": hashlib.sha256(raw).hexdigest(),
        "item_count": len(payload["items"]),
    }
    return payload


def list_catalog(*, query: str = "", topic: str = "", language: str = "", license_status: str = "") -> dict[str, Any]:
    payload = _load()
    query_terms = [term.casefold() for term in query.split() if term.strip()]
    topic_term = topic.strip().casefold()
    language_term = language.strip().casefold()
    license_term = license_status.strip().casefold()

    def matches(item: dict[str, Any]) -> bool:
        searchable = " ".join([
            item["title"], item["source_author"], item["language"], item["course_node"],
            item["selection_rationale"], *item["topics"],
        ]).casefold()
        return (
            all(term in searchable for term in query_terms)
            and (not topic_term or any(topic_term in value.casefold() for value in item["topics"]))
            and (not language_term or language_term == item["language"].casefold())
            and (not license_term or license_term == item["license_status"].casefold())
        )

    items = [item for item in payload["items"] if matches(item)]
    return {
        "schema_version": "fc.video-catalog-response.v1",
        "catalog_version": payload["catalog_version"],
        "catalog_policy": payload["catalog_policy"],
        "manifest": payload["manifest"],
        "filters": {"query": query, "topic": topic, "language": language, "license_status": license_status},
        "facets": {
            "topics": sorted({topic for item in payload["items"] for topic in item["topics"]}),
            "languages": sorted({item["language"] for item in payload["items"]}),
            "license_statuses": sorted({item["license_status"] for item in payload["items"]}),
        },
        "total": len(items),
        "items": items,
    }


def get_catalog_item(source_key: str) -> dict[str, Any]:
    for item in _load()["items"]:
        if item["source_key"] == source_key:
            return item
    raise VideoCatalogError("video.catalog_not_found", "视频目录条目不存在")
