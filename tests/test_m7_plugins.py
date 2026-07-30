import hashlib
import json
import shutil
import uuid
from pathlib import Path

import pytest

from app.m7_plugins import DomainPluginError, DomainPluginManifest, validate_plugin_package


ROOT = Path(__file__).resolve().parents[1]
FIXTURE_ROOT = ROOT / "tests" / "m8_runtime_fixture"


def _package():
    root = FIXTURE_ROOT / uuid.uuid4().hex
    root.mkdir(parents=True)
    payload = json.dumps({"chapters": [{"id": "chapter-1"}]}).encode()
    (root / "chapters.json").write_bytes(payload)
    manifest = {
        "schema_version": "edumatrix.domain-plugin.v1",
        "plugin_id": "robotics-basics", "plugin_version": "1.0.0",
        "domain_key": "robotics", "title": "Robotics", "license": "CC-BY-4.0",
        "assets": [{
            "path": "chapters.json", "sha256": hashlib.sha256(payload).hexdigest(),
            "media_type": "application/json", "purpose": "chapters",
        }],
        "allowed_actions": ["validate_data", "register_domain"],
    }
    (root / "plugin.json").write_text(json.dumps(manifest), encoding="utf-8")
    return root, manifest


def test_restricted_plugin_package_verifies_declared_assets():
    root, _ = _package()
    try:
        report = validate_plugin_package(root)
        assert report["verified_assets"][0]["bytes"] > 0
        assert report["capability_boundary"] == {
            "network": False, "secrets": False, "executable_code": False,
            "allowed_actions": ["validate_data", "register_domain"],
        }
    finally:
        shutil.rmtree(root)


def test_plugin_rejects_tampering_and_ambient_capabilities():
    root, manifest = _package()
    try:
        (root / "chapters.json").write_text("tampered", encoding="utf-8")
        with pytest.raises(DomainPluginError) as raised:
            validate_plugin_package(root)
        assert raised.value.code == "plugin_asset_hash_mismatch"
        manifest["requires_network"] = True
        with pytest.raises(Exception):
            DomainPluginManifest.model_validate(manifest)
        manifest["requires_network"] = False
        manifest["allowed_actions"] = ["run_python"]
        with pytest.raises(Exception):
            DomainPluginManifest.model_validate(manifest)
    finally:
        shutil.rmtree(root)
