from __future__ import annotations

import re
import sqlite3

import scripts.create_competition_packages as packages


M0_RUNTIME = packages.M0_RUNTIME
ROOT = packages.ROOT
RUNTIME_SCRIPTS = packages.RUNTIME_SCRIPTS
runtime_dist_path_allowed = packages.runtime_dist_path_allowed


def test_work_package_declares_all_code_and_browser_runtime_scripts():
    assert {
        "db_heal.py",
        "runtime_preflight.py",
        "e2e_no_docker.py",
        "trusted_local_smoke.py",
    }.issubset(RUNTIME_SCRIPTS)


def test_m0_runtime_allowlist_contains_course_and_all_frozen_benchmarks():
    required = {
        "baseline_course/00_课程说明.md",
        "baseline_course/08_故障恢复与技能验收.md",
        "datasets/course_manifest.json",
        "datasets/core_knowledge_points.json",
        "datasets/baseline_profiles.json",
        "datasets/evaluation_cases.jsonl",
    }
    actual = {
        path.relative_to(M0_RUNTIME).as_posix()
        for directory in ("baseline_course", "datasets")
        for path in (M0_RUNTIME / directory).rglob("*") if path.is_file()
    }
    assert required.issubset(actual)
    assert not any(path.startswith("evidence/") for path in actual)


def test_frontend_dist_allowlist_contains_every_local_index_resource():
    dist = ROOT / "frontend" / "dist"
    index = (dist / "index.html").read_text(encoding="utf-8")
    references = {
        match.lstrip("/")
        for match in re.findall(r'(?:src|href)="(/[^"]+)"', index)
        if not match.startswith("//")
    }
    actual = {
        path.relative_to(dist).as_posix()
        for path in dist.rglob("*") if path.is_file() and runtime_dist_path_allowed(path)
    }
    assert any(path.startswith("assets/index-") and path.endswith(".js") for path in references)
    assert references.issubset(actual)


def test_evaluator_runtime_uses_trusted_local_but_source_default_stays_disabled():
    source_env = (ROOT / ".env.example").read_text(encoding="utf-8")
    runtime_env = (ROOT / "packaging" / ".env.runtime.template").read_text(encoding="utf-8")
    launcher = (ROOT / "packaging" / "install_and_run.bat").read_text(encoding="utf-8")
    evaluator_readme = (ROOT / "packaging" / "README_作品运行说明.txt").read_text(encoding="utf-8")

    assert "EDUMATRIX_SANDBOX_MODE=disabled" in source_env
    assert "EDUMATRIX_SANDBOX_MODE=trusted_local" in runtime_env
    assert 'set "EDUMATRIX_SANDBOX_MODE=trusted_local"' in launcher
    assert "不具备 Docker 容器" in evaluator_readme
    assert "lzz / 404404aA" in evaluator_readme
    assert "teacher / admin123" in evaluator_readme
    assert "demo-admin / EduMatrix-Demo-2026" in evaluator_readme


def test_launcher_never_prints_api_key_fragments_or_browser_key_instructions():
    launcher = (ROOT / "run.py").read_text(encoding="utf-8")
    assert "api_key[:" not in launcher
    assert "api_key[-" not in launcher
    assert "浏览器 Settings 页面配置" not in launcher
    assert "API Key: 已配置（仅后端读取）" in launcher


def test_current_evaluator_smoke_targets_final_routes_and_trusted_local():
    smoke = (ROOT / "scripts" / "e2e_no_docker.py").read_text(encoding="utf-8")
    for route in ("/landing", "/login", "/workspace", "/knowledge", "/api/code/run"):
        assert route in smoke
    assert "/learning-path" not in smoke
    assert "/student-analysis" not in smoke
    assert 'EXPECTED_SANDBOX_MODE = "trusted_local"' in smoke


def test_sanitized_evaluator_database_keeps_documented_demo_identities_and_learning_rows(
    tmp_path, monkeypatch
):
    source_root = tmp_path / "source"
    build_root = tmp_path / "build"
    source_root.mkdir()
    source_db = source_root / "edumatrix.db"
    with sqlite3.connect(source_db) as db:
        db.execute("create table users (id integer primary key, username text unique)")
        db.execute("create table learning_events (id integer primary key, student_id text)")
        db.execute("create table knowledge_documents (id integer primary key, student_id text)")
        db.executemany(
            "insert into users(username) values (?)",
            [(name,) for name in ("lzz", "teacher", "demo-admin", "demo-student", "stu-01", "private-user")],
        )
        db.executemany(
            "insert into learning_events(student_id) values (?)",
            [(name,) for name in ("lzz", "public", "demo-student", "stu-01", "private-user")],
        )
        db.executemany(
            "insert into knowledge_documents(student_id) values (?)",
            [(name,) for name in ("lzz", "public", "private-user")],
        )
        db.commit()

    monkeypatch.setattr(packages, "ROOT", source_root)
    monkeypatch.setattr(packages, "BUILD", build_root)
    target = packages.build_seed_database()
    assert target is not None

    with sqlite3.connect(target) as db:
        users = {row[0] for row in db.execute("select username from users")}
        events = {row[0] for row in db.execute("select student_id from learning_events")}
        documents = {row[0] for row in db.execute("select student_id from knowledge_documents")}
        integrity = db.execute("pragma integrity_check").fetchone()[0]

    assert users == {"lzz", "teacher", "demo-admin", "demo-student", "stu-01"}
    assert events == {"lzz", "public", "demo-student", "stu-01"}
    assert documents == {"lzz", "public"}
    assert integrity == "ok"
