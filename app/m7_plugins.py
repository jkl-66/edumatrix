"""Restricted vertical-domain plugin manifest contract.

This is a data contract, not a Python extension loader. It deliberately gives
domain packages no ambient filesystem, network, database, or secret access.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Literal

from pydantic import Field, model_validator

from app.m2_contracts import StrictModel


_IDENTIFIER = re.compile(r"^[a-z][a-z0-9_-]{2,63}$")
_SAFE_RELATIVE = re.compile(r"^[a-zA-Z0-9_./-]+$")


class DomainPluginError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class PluginAsset(StrictModel):
    path: str = Field(min_length=1, max_length=256)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    media_type: Literal["application/json", "text/markdown", "text/csv"]
    purpose: Literal["chapters", "knowledge_points", "source_catalog", "evaluation_cases", "rubric"]

    @model_validator(mode="after")
    def safe_path(self):
        path = Path(self.path)
        if path.is_absolute() or ".." in path.parts or not _SAFE_RELATIVE.fullmatch(self.path):
            raise ValueError("plugin asset path must be a safe relative path")
        return self


class CheckerDeclaration(StrictModel):
    artifact_type: Literal["lesson", "lab_guide", "tiered_quiz", "interactive_skill_artifact"]
    schema_key: str = Field(min_length=3, max_length=64)
    schema_version: str = Field(pattern=r"^[0-9]+\.[0-9]+$")


class DomainPluginManifest(StrictModel):
    schema_version: Literal["edumatrix.domain-plugin.v1"] = "edumatrix.domain-plugin.v1"
    plugin_id: str
    plugin_version: str = Field(pattern=r"^[0-9]+\.[0-9]+\.[0-9]+$")
    domain_key: str
    title: str = Field(min_length=1, max_length=128)
    license: str = Field(min_length=1, max_length=128)
    assets: tuple[PluginAsset, ...]
    checkers: tuple[CheckerDeclaration, ...] = ()
    allowed_actions: tuple[Literal["validate_data", "register_domain", "register_checker"], ...] = ("validate_data",)
    requires_network: Literal[False] = False
    requires_secrets: Literal[False] = False
    executable_code: Literal[False] = False

    @model_validator(mode="after")
    def validate_manifest(self):
        if not _IDENTIFIER.fullmatch(self.plugin_id) or not _IDENTIFIER.fullmatch(self.domain_key):
            raise ValueError("plugin_id and domain_key must be stable lowercase identifiers")
        if not self.assets:
            raise ValueError("plugin must contain at least one declared data asset")
        paths = [item.path for item in self.assets]
        if len(paths) != len(set(paths)):
            raise ValueError("plugin asset paths must be unique")
        if len(self.allowed_actions) != len(set(self.allowed_actions)):
            raise ValueError("allowed actions must be unique")
        return self


def validate_plugin_package(package_dir: str | Path) -> dict:
    root = Path(package_dir).resolve()
    manifest_path = root / "plugin.json"
    try:
        manifest = DomainPluginManifest.model_validate_json(manifest_path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise DomainPluginError("plugin_manifest_invalid", "plugin manifest is missing or invalid") from exc
    verified: list[dict[str, str | int]] = []
    for asset in manifest.assets:
        target = (root / asset.path).resolve()
        if root not in target.parents or not target.is_file():
            raise DomainPluginError("plugin_asset_missing", f"declared asset is unavailable: {asset.path}")
        payload = target.read_bytes()
        actual = hashlib.sha256(payload).hexdigest()
        if actual != asset.sha256:
            raise DomainPluginError("plugin_asset_hash_mismatch", f"asset hash mismatch: {asset.path}")
        if asset.media_type == "application/json":
            try:
                json.loads(payload.decode("utf-8"))
            except Exception as exc:
                raise DomainPluginError("plugin_asset_invalid_json", f"invalid JSON asset: {asset.path}") from exc
        verified.append({"path": asset.path, "sha256": actual, "bytes": len(payload)})
    return {
        "schema_version": "edumatrix.domain-plugin-validation.v1",
        "plugin_id": manifest.plugin_id,
        "plugin_version": manifest.plugin_version,
        "domain_key": manifest.domain_key,
        "verified_assets": verified,
        "capability_boundary": {
            "network": False, "secrets": False, "executable_code": False,
            "allowed_actions": list(manifest.allowed_actions),
        },
    }
