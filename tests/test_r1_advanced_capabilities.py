from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).parents[1]
ROUTER = ROOT / "frontend" / "src" / "router" / "index.js"
APP = ROOT / "frontend" / "src" / "App.vue"


def test_advanced_capability_routes_exist_and_primary_navigation_stays_small():
    router = ROUTER.read_text(encoding="utf-8")
    app = APP.read_text(encoding="utf-8")
    contracts = {item["sourcePath"]: item for item in json.loads(
        (ROUTER.parent / "routeMigrationContract.json").read_text(encoding="utf-8")
    )}
    assert contracts["/advanced-capabilities"]["disposition"] != "primary"
    assert "routeMigrationContract" in router and ".map(legacy)" in router
    assert "path: '/advanced-capabilities'" not in app
    for path in (
        "/enterprise-training", "/certification-lifecycle", "/video-studio",
        "/marketplace", "/plugins", "/integration-sandbox", "/local-sso",
        "/model-operations", "/content-review", "/internal/objects",
    ):
        assert path in contracts
        assert contracts[path]["destination"]


