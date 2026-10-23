from __future__ import annotations

import importlib.util
import sys
import types
import zipfile
from pathlib import Path

from scripts import create_competition_packages as packaging


ROOT = Path(__file__).resolve().parents[1]


def test_config_respects_dotenv_disabled(monkeypatch):
    called = []
    fake_dotenv = types.ModuleType("dotenv")
    fake_dotenv.load_dotenv = lambda *args, **kwargs: called.append((args, kwargs))
    monkeypatch.setitem(sys.modules, "dotenv", fake_dotenv)
    monkeypatch.setenv("PYTHON_DOTENV_DISABLED", "1")
    spec = importlib.util.spec_from_file_location("w5_isolated_config", ROOT / "config.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        sys.modules.pop(spec.name, None)
    assert called == []


def test_runtime_preflight_covers_bundled_media_runtimes():
    source = (ROOT / "scripts" / "runtime_preflight.py").read_text(encoding="utf-8")
    assert "app.offline_speech" in source
    assert "app.video_rendering" in source


def test_runnable_package_contains_sapi_and_whisper_runtime(tmp_path):
    target = tmp_path / "runtime.zip"
    with zipfile.ZipFile(target, "w", zipfile.ZIP_STORED) as archive:
        added: set[str] = set()
        packaging.add_common_runtime(archive, added)
    with zipfile.ZipFile(target) as archive:
        names = set(archive.namelist())
    assert "scripts/synthesize_sapi_speech.ps1" in names
    assert "vendor/whisper.cpp/runtime-manifest.json" in names
    assert "vendor/whisper.cpp/LICENSE" in names
    assert "vendor/whisper.cpp/bin/Release/whisper-cli.exe" in names
    assert "vendor/whisper.cpp/models/ggml-base-q5_1.bin" in names


def test_runnable_package_declares_canonical_courses_and_data_plugins():
    source = (ROOT / "scripts" / "create_competition_packages.py").read_text(encoding="utf-8")
    assert '("curated", "datasets", "domain_plugins", "manifest", "patches")' in source
    assert (ROOT / "data" / "curated" / "machine_learning_foundations_v1" / "course_manifest.json").is_file()
    assert (ROOT / "data" / "curated" / "embedded_edge_intelligence_v1" / "course_manifest.json").is_file()
    assert (ROOT / "data" / "domain_plugins" / "robotics-skill-demo" / "plugin.json").is_file()
