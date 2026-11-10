"""Build one current evaluator runtime. Earlier three-archive helpers are retained
for historical use; the default entry point does not rebuild presentation files.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "outputs"
PACKAGING = ROOT / "packaging"
BUILD = ROOT / "outputs" / "package_build"
RAW_REPOS = ROOT / "data" / "raw" / "github_repos"
M0_RUNTIME = ROOT / "outputs" / "M0_阶段0基线与架构契约"

WORK_ZIP = OUTPUT / "00015352作品.zip"
SOURCE_ZIP = OUTPUT / "00015352源码.zip"
INFO_ZIP = OUTPUT / "00015352介绍.zip"

COMMON_ROOT_FILES = [
    ".env.example",
    ".dockerignore",
    "LICENSE",
    "NOTICE",
    "README.md",
    "requirements.txt",
    "pytest.ini",
    "run.py",
]

SOURCE_ROOT_FILES = COMMON_ROOT_FILES + ["Dockerfile", "docker-compose.yml", "start.bat"]
RUNTIME_SCRIPTS = [
    "db_heal.py",
    "e2e_no_docker.py",
    "runtime_preflight.py",
    "seed_students.py",
    "bootstrap_item_bank.py",
    "trusted_local_smoke.py",
    "synthesize_sapi_speech.ps1",
]

INFO_DOCS = [
    ("outputs/README.md", "README.md"),
    ("outputs/EduMatrix_评委阅读说明.md", "00_评委阅读说明.md"),
    ("outputs/EduMatrix_评委最终技术文档.docx", "01_EduMatrix_评委最终技术文档.docx"),
    ("outputs/EduMatrix_评委最终技术文档.pdf", "01_EduMatrix_评委最终技术文档.pdf"),
    ("outputs/EduMatrix_完整技术文档总稿.md", "02_EduMatrix_完整技术文档总稿.md"),
    ("outputs/EduMatrix_系统设计与实现方案.md", "03_EduMatrix_系统设计与实现方案.md"),
    ("outputs/EduMatrix_API与数据字典.md", "04_EduMatrix_API与数据字典.md"),
    ("outputs/EduMatrix_测试说明书.md", "05_EduMatrix_测试说明书.md"),
    ("outputs/EduMatrix_部署运维说明书.md", "06_EduMatrix_部署运维说明书.md"),
    ("outputs/EduMatrix_评委环境安装与复现备忘录.md", "07_EduMatrix_评委环境安装与复现备忘录.md"),
    ("outputs/EduMatrix_需求实现测试追踪矩阵.md", "08_EduMatrix_需求实现测试追踪矩阵.md"),
    ("outputs/EduMatrix_公开依据与引用清单.md", "09_EduMatrix_公开依据与引用清单.md"),
    ("outputs/EduMatrix_A3_评委阅读版_方向A.pptx", "10_EduMatrix_A3_评委阅读版_方向A.pptx"),
    ("outputs/EduMatrix_A3_评委阅读版_方向A.pdf", "10_EduMatrix_A3_评委阅读版_方向A.pdf"),
]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def add_file(archive: zipfile.ZipFile, source: Path, target: str, added: set[str]) -> bool:
    if not source.is_file():
        return False
    target = target.replace("\\", "/")
    if target in added:
        return True
    archive.write(source, target)
    added.add(target)
    return True


def safe_path(path: Path) -> bool:
    excluded_parts = {
        ".git", ".venv", "node_modules", "__pycache__", ".pytest_cache", ".mypy_cache",
        ".codex", ".agents", ".claude", ".cursor", ".gemini", ".grok", ".qwen",
        ".reasonix", ".serena", ".trae", ".ipynb_checkpoints", "_build", "build",
        "dist", "site", "html", "__macosx", "render", "recovery", "package_build",
    }
    if any(part in excluded_parts for part in path.parts):
        return False
    if path.suffix.lower() in {
        ".pyc", ".pyo", ".log", ".db", ".sqlite", ".wal", ".shm", ".pack", ".idx",
        ".rev", ".icloud", ".ds_store", ".doctree", ".inv", ".buildinfo", ".joblib",
        ".pkl", ".pickle", ".ckpt", ".lock", ".gz",
    }:
        return False
    if path.name.startswith("~$") or path.name.lower() in {".env", "proxy.log", "task.md", "test_member6_all_tasks.py"}:
        return False
    return True


def raw_path_allowed(path: Path) -> bool:
    return safe_path(path)


def runtime_dist_path_allowed(path: Path) -> bool:
    if path.name.startswith("~$") or path.name.lower() == ".env":
        return False
    return path.suffix.lower() not in {
        ".pyc", ".pyo", ".log", ".db", ".sqlite", ".wal", ".shm",
    }


def add_tree(
    archive: zipfile.ZipFile,
    source: Path,
    prefix: str,
    added: set[str],
    path_allowed=safe_path,
) -> int:
    if not source.is_dir():
        return 0
    count = 0
    for path in sorted(source.rglob("*")):
        if not path.is_file() or not path_allowed(path):
            continue
        relative = path.relative_to(source).as_posix()
        if add_file(archive, path, f"{prefix.rstrip('/')}/{relative}", added):
            count += 1
    return count


def build_readme_docx(source: Path, target: Path, title: str) -> None:
    """Render a compact, printable Word version of a package README."""
    from docx import Document
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.shared import Pt
    from docx.oxml.ns import qn

    document = Document()
    section = document.sections[0]
    section.top_margin = Pt(50)
    section.bottom_margin = Pt(50)
    section.left_margin = Pt(58)
    section.right_margin = Pt(58)

    normal = document.styles["Normal"]
    normal.font.name = "等线"
    normal.font.size = Pt(10.5)
    normal._element.get_or_add_rPr().rFonts.set(qn("w:eastAsia"), "等线")
    normal.paragraph_format.space_after = Pt(4)
    normal.paragraph_format.line_spacing = 1.12

    for style_name, size in (("Heading 1", 16), ("Heading 2", 13), ("Heading 3", 11)):
        style = document.styles[style_name]
        style.font.name = "等线"
        style.font.size = Pt(size)
        style.font.bold = True
        style._element.get_or_add_rPr().rFonts.set(qn("w:eastAsia"), "等线")

    heading = document.add_paragraph()
    heading.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = heading.add_run(title)
    run.bold = True
    run.font.name = "等线"
    run.font.size = Pt(20)
    heading.paragraph_format.space_after = Pt(12)

    source_note = document.add_paragraph(f"文件来源：{source.name}")
    source_note.alignment = WD_ALIGN_PARAGRAPH.CENTER
    source_note.runs[0].italic = True
    source_note.runs[0].font.size = Pt(9)

    in_code = False
    for raw_line in source.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw_line.rstrip()
        stripped = line.strip()
        if stripped.startswith("```"):
            in_code = not in_code
            continue
        if in_code:
            paragraph = document.add_paragraph()
            paragraph.paragraph_format.left_indent = Pt(12)
            code_run = paragraph.add_run(line)
            code_run.font.name = "Consolas"
            code_run.font.size = Pt(9)
            continue
        if not stripped:
            document.add_paragraph().paragraph_format.space_after = Pt(1)
            continue
        if stripped == "---":
            document.add_paragraph("-" * 72)
            continue
        if stripped.startswith("#"):
            level = min(len(stripped) - len(stripped.lstrip("#")), 3)
            text = stripped[level:].strip()
            document.add_paragraph(text, style=f"Heading {level}")
            continue
        if stripped.startswith(">"):
            paragraph = document.add_paragraph(style="Intense Quote")
            paragraph.add_run(stripped.lstrip("> "))
            continue
        if re.match(r"^[-*+]\s+", stripped):
            document.add_paragraph(re.sub(r"^[-*+]\s+", "", stripped), style="List Bullet")
            continue
        if re.match(r"^\d+[.]\s+", stripped):
            document.add_paragraph(re.sub(r"^\d+[.]\s+", "", stripped), style="List Number")
            continue
        document.add_paragraph(stripped)

    document.core_properties.title = title
    document.core_properties.subject = "EduMatrix package README"
    target.parent.mkdir(parents=True, exist_ok=True)
    document.save(target)


def build_readme_documents() -> dict[str, Path]:
    BUILD.mkdir(parents=True, exist_ok=True)
    documents = {
        "project": BUILD / "README.docx",
        "work": BUILD / "README_作品运行说明.docx",
        "source": BUILD / "README_SOURCE_PACKAGE.docx",
        "info_overview": BUILD / "README_INFO_OVERVIEW.docx",
        "info": BUILD / "README_INFO_PACKAGE.docx",
    }
    build_readme_docx(ROOT / "README.md", documents["project"], "EduMatrix 项目 README")
    build_readme_docx(
        PACKAGING / "README_作品运行说明.txt",
        documents["work"],
        "EduMatrix 作品安装与运行说明",
    )
    build_readme_docx(
        PACKAGING / "README_源码包说明.txt",
        documents["source"],
        "EduMatrix 源码包说明",
    )
    build_readme_docx(
        OUTPUT / "README.md",
        documents["info_overview"],
        "EduMatrix 评委材料目录",
    )
    build_readme_docx(
        PACKAGING / "README_介绍包说明.txt",
        documents["info"],
        "EduMatrix 介绍材料包说明",
    )
    return documents


def build_raw_repo_manifest() -> Path:
    """Create a reviewer-facing inventory for the bundled public repo materials."""
    BUILD.mkdir(parents=True, exist_ok=True)
    source_metadata: dict[str, dict] = {}
    source_manifest = ROOT / "data" / "manifest" / "source_manifest.jsonl"
    if source_manifest.is_file():
        for line in source_manifest.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if record.get("key"):
                source_metadata[str(record["key"])] = record
    repositories: list[dict] = []
    total_files = 0
    total_bytes = 0
    if RAW_REPOS.is_dir():
        for repo in sorted(path for path in RAW_REPOS.iterdir() if path.is_dir()):
            selected_files: list[Path] = []
            excluded_images: list[dict] = []
            for path in sorted(repo.rglob("*")):
                if path.is_file() and raw_path_allowed(path):
                    selected_files.append(path)
            license_files = [
                path.relative_to(RAW_REPOS).as_posix()
                for path in selected_files
                if path.name.lower().startswith(("license", "copying", "notice"))
            ]
            bytes_count = sum(path.stat().st_size for path in selected_files)
            total_files += len(selected_files)
            total_bytes += bytes_count
            repositories.append({
                "repository": repo.name,
                "source_metadata": source_metadata.get(repo.name, {}),
                "selected_files": len(selected_files),
                "selected_bytes": bytes_count,
                "license_candidates": license_files,
                "excluded_oversized_images": excluded_images,
            })
    manifest = {
        "source_root": "data/raw/github_repos",
        "purpose": "预置课程知识库原始输入与可追溯素材",
        "selection": {
            "included": "仓库中的课程文档、Notebook、代码、数据、演示文稿、图像和许可证文件",
            "excluded": "Git 历史对象、构建产物、缓存、解释器缓存、私密配置、运行数据库及模型二进制缓存",
            "license_note": "许可证候选文件仅作来源索引；实际使用须遵守每个仓库随附的许可证及原始平台条款。",
        },
        "repositories": repositories,
        "totals": {"selected_files": total_files, "selected_bytes": total_bytes},
    }
    target = BUILD / "github_repos_package_manifest.json"
    target.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return target


def lock_text() -> str:
    candidates = [ROOT / ".venv" / "Scripts" / "python.exe", Path(os.sys.executable)]
    for python in candidates:
        if not python.is_file():
            continue
        try:
            result = subprocess.run(
                [str(python), "-m", "pip", "freeze", "--all"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=True,
            )
            return result.stdout
        except (OSError, subprocess.CalledProcessError):
            continue
    return "# pip freeze unavailable on the packaging host\n"


def build_seed_database() -> Path | None:
    source = ROOT / "edumatrix.db"
    if not source.is_file():
        return None
    BUILD.mkdir(parents=True, exist_ok=True)
    target = BUILD / "edumatrix.db"
    if target.exists():
        target.unlink()
    source_conn = sqlite3.connect(source)
    target_conn = sqlite3.connect(target)
    try:
        source_conn.backup(target_conn)
        tables = [row[0] for row in target_conn.execute(
            "select name from sqlite_master where type='table' and name not like 'sqlite_%'"
        )]
        for table in tables:
            columns = {row[1] for row in target_conn.execute(f'pragma table_info("{table}")')}
            quoted = '"' + table.replace('"', '""') + '"'
            if "student_id" in columns:
                if table == "knowledge_documents":
                    target_conn.execute(
                        f"delete from {quoted} where student_id not in ('public', 'lzz')"
                    )
                else:
                    target_conn.execute(
                        f"delete from {quoted} where student_id not like 'stu-%' "
                        "and student_id not in ('public', 'demo-student', 'lzz')"
                    )
            if table == "users":
                target_conn.execute(
                    f"delete from {quoted} where username not in "
                    "('lzz', 'teacher', 'demo-admin', 'demo-student') "
                    "and username not like 'stu-%'"
                )
        target_conn.commit()
        target_conn.execute("vacuum")
    finally:
        source_conn.close()
        target_conn.close()
    return target


def evaluator_report() -> dict:
    source = OUTPUT / "e2e_no_docker" / "report.json"
    if not source.is_file():
        return {"result": "not_available"}
    raw = json.loads(source.read_text(encoding="utf-8"))
    checks = raw.get("checks", {})
    health = dict(checks.get("health", {}))
    sandbox = dict(checks.get("sandbox_status", {}))
    for key in ("llm_endpoint", "llm_api_key_configured", "llm_model", "user_api_key_provided"):
        health.pop(key, None)
    for key in ("python_executable", "multiprocessing_executable", "process_id"):
        sandbox.pop(key, None)
    return {
        "result": raw.get("result", "unknown"),
        "mode": raw.get("mode", "trusted_local"),
        "started_at": raw.get("started_at"),
        "finished_at": raw.get("finished_at"),
        "checks": {
            "health": health,
            "sandbox_status": sandbox,
            "landing_page": checks.get("landing_page", {}),
            "login_page": checks.get("login_page", {}),
            "learning_workspace": checks.get("learning_workspace", {}),
            "knowledge_page": checks.get("knowledge_page", {}),
            "safe_execution": checks.get("safe_execution", {}),
            "blocked_execution": checks.get("blocked_execution", {}),
        },
    }


def video_files() -> list[Path]:
    candidates: list[Path] = []
    for directory in (ROOT / "submission_media", ROOT / "media"):
        if not directory.is_dir():
            continue
        candidates.extend(
            path for path in sorted(directory.rglob("*"))
            if path.is_file() and path.suffix.lower() in {".mp4", ".mov", ".mkv", ".webm"}
        )
    return candidates


def add_common_runtime(archive: zipfile.ZipFile, added: set[str]) -> int:
    count = 0
    for filename in COMMON_ROOT_FILES:
        count += int(add_file(archive, ROOT / filename, filename, added))
    for path in sorted(ROOT.glob("*.py")):
        count += int(add_file(archive, path, path.name, added))
    count += add_tree(archive, ROOT / "app", "app", added)
    count += add_tree(archive, ROOT / "vendor" / "whisper.cpp", "vendor/whisper.cpp", added)
    for filename in RUNTIME_SCRIPTS:
        count += int(add_file(archive, ROOT / "scripts" / filename, f"scripts/{filename}", added))
    return count


def build_work_package(
    seed_db: Path | None,
    lock: str,
    readmes: dict[str, Path],
    raw_manifest: Path,
) -> None:
    added: set[str] = set()
    with zipfile.ZipFile(WORK_ZIP, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        add_common_runtime(archive, added)
        add_file(archive, ROOT / "frontend" / "dist" / "index.html", "frontend/dist/index.html", added)
        add_tree(
            archive, ROOT / "frontend" / "dist", "frontend/dist", added,
            runtime_dist_path_allowed,
        )
        for directory in ("curated", "datasets", "domain_plugins", "manifest", "patches"):
            add_tree(archive, ROOT / "data" / directory, f"data/{directory}", added)
        for directory in ("baseline_course", "datasets"):
            add_tree(
                archive, M0_RUNTIME / directory,
                f"outputs/M0_阶段0基线与架构契约/{directory}", added,
            )
        add_tree(archive, RAW_REPOS, "data/raw/github_repos", added, raw_path_allowed)
        add_file(archive, raw_manifest, "data/manifest/github_repos_package_manifest.json", added)
        for filename in ("poincare_projection.npy", "dkt_weights.pth"):
            add_file(archive, ROOT / "data" / filename, f"data/{filename}", added)
        if seed_db:
            add_file(archive, seed_db, "edumatrix.db", added)
        for filename in (
            "install_and_run.bat", "stop_services.bat", "verify_runtime.bat",
            ".env.runtime.template", "README_作品运行说明.txt",
        ):
            add_file(archive, PACKAGING / filename, filename, added)
        add_file(archive, readmes["project"], "README.docx", added)
        add_file(archive, readmes["work"], "README_作品运行说明.docx", added)
        archive.writestr("requirements-lock.txt", lock)
        archive.writestr("PACKAGE_MANIFEST.json", json.dumps({
            "package": "00015352作品.zip",
            "runtime": "Windows + Python 3.11",
            "frontend": "frontend/dist served by FastAPI on port 8000",
            "knowledge_source": "data/raw/github_repos (13 repositories, filtered public course materials)",
            "knowledge_manifest": "data/manifest/github_repos_package_manifest.json",
            "default_mode": "deterministic + trusted_local evaluator demo",
            "dependency_install": "online first-run pip install from pinned requirements-lock.txt (requirements.txt fallback)",
            "created_at": datetime.now(timezone.utc).isoformat(),
        }, ensure_ascii=False, indent=2))


def build_source_package(lock: str, readmes: dict[str, Path]) -> None:
    added: set[str] = set()
    with zipfile.ZipFile(SOURCE_ZIP, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for filename in SOURCE_ROOT_FILES:
            add_file(archive, ROOT / filename, filename, added)
        for path in sorted(ROOT.glob("*.py")):
            add_file(archive, path, path.name, added)
        for directory in ("app", "scripts", "tests", "docs", "packaging"):
            add_tree(archive, ROOT / directory, directory, added)
        add_tree(archive, ROOT / "frontend" / "src", "frontend/src", added)
        add_tree(archive, ROOT / "frontend" / "public", "frontend/public", added)
        for filename in ("package.json", "package-lock.json", "vite.config.js", "README.md"):
            add_file(archive, ROOT / "frontend" / filename, f"frontend/{filename}", added)
        # The source archive carries provenance metadata, not the evaluator's
        # course corpus. The runnable archive is the owner of those inputs.
        for directory in ("manifest",):
            add_tree(archive, ROOT / "data" / directory, f"data/{directory}", added)
        for filename in ("poincare_projection.npy", "dkt_weights.pth"):
            add_file(archive, ROOT / "data" / filename, f"data/{filename}", added)
        archive.writestr("requirements-lock.txt", lock)
        archive.writestr("README_SOURCE_PACKAGE.txt", (PACKAGING / "README_源码包说明.txt").read_text(encoding="utf-8"))
        add_file(archive, readmes["project"], "README.docx", added)
        add_file(archive, readmes["source"], "README_SOURCE_PACKAGE.docx", added)
        archive.writestr("PACKAGE_MANIFEST.json", json.dumps({
            "package": "00015352源码.zip",
            "contains": ["backend_source", "frontend_source", "tests", "source_metadata", "dependency_files"],
            "excludes": [".env", "knowledge_base_raw_materials", "course_datasets", "database_runtime_files", "frontend_dist", "node_modules", "virtual_environment", "private_logs"],
            "created_at": datetime.now(timezone.utc).isoformat(),
        }, ensure_ascii=False, indent=2))


def build_info_package() -> None:
    added: set[str] = set()
    with zipfile.ZipFile(INFO_ZIP, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for source_name, target_name in INFO_DOCS:
            add_file(archive, ROOT / source_name, target_name, added)
        add_tree(archive, OUTPUT / "figures", "figures", added)
        # Keep only the image evidence. The raw capture report contains local
        # paths and process identifiers; evaluator_report.json below is the
        # sanitized reviewer-facing equivalent.
        screenshot_root = OUTPUT / "evaluator_screenshots"
        for path in sorted(screenshot_root.rglob("*")):
            if not path.is_file() or path.name == "report.json" or not safe_path(path):
                continue
            add_file(archive, path, f"screenshots/{path.relative_to(screenshot_root).as_posix()}", added)
        for path in sorted((ROOT / "render").glob("slide*.png")):
            add_file(archive, path, f"ppt_preview/{path.name}", added)
        add_file(archive, ROOT / "render" / "viewer.html", "ppt_preview/viewer.html", added)
        add_file(archive, OUTPUT / "runtime_security_matrix.json", "runtime_security_matrix.json", added)
        add_file(archive, OUTPUT / "trusted_local_smoke.json", "trusted_local_smoke.json", added)
        add_file(archive, BUILD / "README_INFO_OVERVIEW.docx", "README.docx", added)
        add_file(archive, BUILD / "README_INFO_PACKAGE.docx", "README_INFO_PACKAGE.docx", added)
        archive.writestr("evaluator_report.json", json.dumps(evaluator_report(), ensure_ascii=False, indent=2))
        videos = video_files()
        if videos:
            for video in videos:
                add_file(archive, video, f"video/{video.name}", added)
        else:
            archive.writestr(
                "video/VIDEO_PENDING.txt",
                "演示视频尚未由参赛队伍提供。收到视频后放入 submission_media/ 并重新运行 scripts/create_competition_packages.py。\n",
            )
        archive.writestr("README_INFO_PACKAGE.txt", (PACKAGING / "README_介绍包说明.txt").read_text(encoding="utf-8"))
        archive.writestr("PACKAGE_MANIFEST.json", json.dumps({
            "package": "00015352介绍.zip",
            "word_pages": 62,
            "ppt_pages": 20,
            "video_included": bool(videos),
            "created_at": datetime.now(timezone.utc).isoformat(),
        }, ensure_ascii=False, indent=2))


CURRENT_TASKS = (
    'task-7246f1d6f3004a9fa2fee21d8b696c08',  # representative nine-resource package
    'task-fd30eb8b784e457d85e1d56faa86a2a9',  # training and linked resources
    'task-32490ca4251d44b59e0e0a14dd2df605',  # new learner's first path quiz
    'task-687d04215ad347488682c96127160df9',  # review handout and questions
)
DEMO_ACCOUNTS = {
    'auto_r207_software_developer': ('learner', '学习者 · 软件背景'),
    'auto_r207_shop_ai': ('reviewer', '学习者 · 经营背景'),
    'auto_r208_new_learner': ('explorer', '新学习者'),
    'validation_teacher_20261025': ('teacher', '课程教师'),
    'validation_admin_20261025': ('admin', '系统管理员'),
}
DEMO_PASSWORD = 'EduMatrix2026!'


def build_current_seed(source: Path, target: Path) -> dict:
    """Prepare only a copy of the synthetic acceptance data for distribution."""
    import bcrypt
    source = source.resolve()
    assert source != target.resolve() and source.name == 'acceptance.sqlite3'
    target.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(source.as_uri() + '?mode=ro', uri=True) as original:
        users = original.execute('select username, public_id from users').fetchall()
        assert all(name.startswith(('validation_', 'extension-', 'auto_r207_', 'auto_r208_'))
                   for name, _ in users), 'The source must contain only the audited synthetic accounts.'
        published_artifacts = set()
        for task_id in CURRENT_TASKS:
            state = original.execute('select status from generation_tasks where id=?', (task_id,)).fetchone()
            assert state and state[0] == 'completed', f'Current resource task unfinished: {task_id}'
            publication = original.execute("select payload from task_events where task_id=? and event_type='publish.completed' order by sequence desc limit 1", (task_id,)).fetchone()
            assert publication, f'Missing published output: {task_id}'
            published_artifacts.update(ref.split(':')[0] for ref in json.loads(publication[0])['output_refs'])
        assert not original.execute("select 1 from generation_tasks where automation_state in ('queued','running','retry_wait') limit 1").fetchone()
        with sqlite3.connect(target) as copy_db:
            original.backup(copy_db)
    aliases = {old: value[0] for old, value in DEMO_ACCOUNTS.items()}
    active_ids = [public for name, public in users if name in DEMO_ACCOUNTS]
    with sqlite3.connect(target) as db:
        # This is an export-only identity/privacy migration in a fresh copy.
        # Restore the exact immutability rules before committing that copy.
        db.execute('begin')
        frozen_triggers = db.execute(
            "select name,sql from sqlite_master where type='trigger' and lower(sql) like '%immutable%'"
        ).fetchall()
        for trigger_name, _ in frozen_triggers:
            db.execute('drop trigger "' + trigger_name.replace('"', '""') + '"')
        tables = [r[0] for r in db.execute("select name from sqlite_master where type='table' and name not like 'sqlite_%'")]
        # The original synthesis and failure evidence stays in the workspace.
        # Historical identities remain as provenance but cannot be signed into.
        db.execute('update users set is_active=0, hashed_password=?',
                   (bcrypt.hashpw(os.urandom(32).hex().encode(), bcrypt.gensalt()).decode(),))
        for old, (alias, label) in DEMO_ACCOUNTS.items():
            db.execute('update users set username=?, display_name=?, hashed_password=?, is_active=1 where username=?',
                       (alias, label, bcrypt.hashpw(DEMO_PASSWORD.encode(), bcrypt.gensalt()).decode(), old))
        private_keys = {'reasoning_content', 'reasoning_details', 'private_thinking', 'chain_of_thought',
                        'api_key', 'apiKey', 'access_token', 'refresh_token', 'authorization', 'secret'}
        def scrub(value):
            if isinstance(value, dict):
                return {k: scrub(v) for k, v in value.items() if k.lower() not in {s.lower() for s in private_keys}}
            if isinstance(value, list):
                return [scrub(v) for v in value]
            if isinstance(value, str):
                if value in aliases:
                    return aliases[value]
                if value.startswith(('{', '[')):
                    try:
                        return json.dumps(scrub(json.loads(value)), ensure_ascii=False)
                    except ValueError:
                        pass
            return value
        for table in tables:
            quoted = '"' + table.replace('"', '""') + '"'
            columns = db.execute(f'pragma table_info({quoted})').fetchall()
            for column in columns:
                name, kind = column[1], column[2].upper()
                if name in {'student_id', 'legacy_student_id', 'username'}:
                    for old, alias in aliases.items():
                        db.execute(f'update {quoted} set "{name}"=? where "{name}"=?', (alias, old))
                if kind == 'JSON':
                    for row_id, raw in db.execute(f'select rowid,"{name}" from {quoted} where "{name}" is not null').fetchall():
                        try:
                            value = json.loads(raw)
                        except (ValueError, TypeError):
                            continue
                        clean = scrub(value)
                        if clean != value:
                            db.execute(f'update {quoted} set "{name}"=? where rowid=?',
                                       (json.dumps(clean, ensure_ascii=False), row_id))
        db.execute("delete from model_quota_buckets")
        db.execute("delete from worker_leases")
        db.execute("delete from audit_logs")
        # Keep originals and decisions in development evidence, not in the
        # evaluator's task history. The published versions remain unchanged.
        for event_type in ('resource_generation.part_result', 'resource_generation.review_group_result',
                           'learning_generation.component'):
            db.execute('delete from task_events where event_type=?', (event_type,))
        db.execute("update courses set status='withdrawn' where id not in (?,?)",
                   ('course-ai-deep-learning-agents-v1', 'course-machine-learning-foundations-v1'))
        placeholders = ','.join('?' for _ in active_ids)
        db.execute(f'delete from course_memberships where user_public_id not in ({placeholders})', active_ids)
        db.execute("delete from course_memberships where course_id not in (?,?)",
                   ('course-ai-deep-learning-agents-v1', 'course-machine-learning-foundations-v1'))
        marks = ','.join('?' for _ in published_artifacts)
        db.execute(f"update artifacts set status='archived', archived_at=CURRENT_TIMESTAMP where owner_public_id in ({placeholders}) and id not in ({marks})",
                   [*active_ids, *sorted(published_artifacts)])
        for _, trigger_sql in frozen_triggers:
            db.execute(trigger_sql)
        db.commit()
        assert db.execute('pragma integrity_check').fetchone()[0] == 'ok'
        # Existing legacy references are checked against the input, so package
        # preparation cannot introduce a new broken foreign key.
        foreign_keys = db.execute('pragma foreign_key_check').fetchall()
        with sqlite3.connect(source.as_uri()+'?mode=ro', uri=True) as original:
            original_foreign = set(original.execute('pragma foreign_key_check').fetchall())
        assert set(foreign_keys).issubset(original_foreign), foreign_keys[:10]
        counts = {table: db.execute(f'select count(*) from "{table}"').fetchone()[0]
                  for table in ('users', 'artifacts', 'learning_paths', 'assessment_attempts')}
        db.execute('vacuum')
    return {'data_kind': '合成学习者与真实模型生成的课程成果', 'active_accounts': [v[0] for v in DEMO_ACCOUNTS.values()],
            'source_modified': False, 'counts': counts, 'existing_legacy_foreign_keys': len(foreign_keys)}


def build_current_package(runtime_python: Path, source_db: Path, embedding_cache: Path | None = None) -> Path:
    destination = OUTPUT / 'current-runtime-20261110'
    destination.mkdir(parents=True, exist_ok=True)
    subprocess.run([str(runtime_python), '-m', 'pip', 'check'], check=True)
    lock = subprocess.check_output([str(runtime_python), '-m', 'pip', 'freeze'], text=True, encoding='utf8')
    # pip records a machine-local wheel URL; distribute the same official wheel
    # and reference its package-relative path instead.
    lock = '\n'.join('./packaging/wheels/hipporag-2.0.0a5-py3-none-any.whl' if line.lower().startswith('hipporag') else line
                     for line in lock.splitlines()) + '\n'
    assert not re.search(r'file:///|[A-Za-z]:[/\\]', lock)
    seed = destination / 'build' / 'edumatrix.db'
    data_report = build_current_seed(source_db, seed)
    profile_report = destination / 'build' / 'demo-profile-preparation.json'
    subprocess.run([str(runtime_python), str(Path(__file__).resolve()),
                    '--prepare-demo-profiles', str(seed), '--profile-report', str(profile_report)], check=True)
    data_report['profile_preparation'] = json.loads(profile_report.read_text('utf8'))
    archive_path = destination / 'EduMatrix_当前运行包.zip'
    added = set()
    with zipfile.ZipFile(archive_path, 'w', zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        # The runtime's obvious entry files must agree with its launcher,
        # rather than point evaluators back to historical developer setup.
        for name, content in {
            'README.md': '# EduMatrix 当前版本运行包\n\n' + (PACKAGING/'README_作品运行说明.txt').read_text('utf8'),
            'requirements.txt': lock,
            '.env.example': (PACKAGING/'.env.runtime.template').read_text('utf8'),
        }.items():
            archive.writestr(name, content)
            added.add(name)
        add_common_runtime(archive, added)
        add_tree(archive, ROOT/'frontend/dist', 'frontend/dist', added,
                 lambda p: p.name != 'demo-accounts.json' and runtime_dist_path_allowed(p))
        archive.writestr('frontend/dist/demo-accounts.json', json.dumps({
            'student': {'username': 'learner', 'password': DEMO_PASSWORD, 'label': '学生演示账号'},
            'teacher': {'username': 'teacher', 'password': DEMO_PASSWORD, 'label': '教师演示账号'},
            'admin': {'username': 'admin', 'password': DEMO_PASSWORD, 'label': '管理员演示账号'},
        }, ensure_ascii=False))
        for directory in ('datasets', 'domain_plugins', 'manifest', 'patches'):
            add_tree(archive, ROOT/'data'/directory, 'data/'+directory, added)
        for course in ('ai_deep_learning_agents_v1', 'machine_learning_foundations_v1'):
            add_tree(archive, ROOT/'data/curated'/course, 'data/curated/'+course, added)
        # Historical source versions remain reachable from current learning
        # records. Include only their exact audited assets, not the scratch tree.
        with sqlite3.connect(seed) as db:
            for raw, in db.execute("select parser_metadata from source_documents where course_id in (?,?)",
                    ('course-ai-deep-learning-agents-v1','course-machine-learning-foundations-v1')):
                asset = (json.loads(raw or '{}').get('bundle_asset') or {})
                if not asset.get('path'):
                    continue
                path = (ROOT/asset['path']).resolve()
                relative = path.relative_to(ROOT).as_posix()
                assert path.is_file(), relative
                if asset.get('sha256'):
                    assert sha256(path) == asset['sha256'], relative
                assert add_file(archive, path, relative, added), relative
        add_tree(archive, ROOT/'data/models/multilingual-e5-small', 'data/models/multilingual-e5-small', added,
                 lambda p: '.cache' not in p.parts and safe_path(p))
        for directory in ('baseline_course', 'datasets'):
            add_tree(archive, M0_RUNTIME/directory, f'outputs/M0_阶段0基线与架构契约/{directory}', added)
        add_tree(archive, RAW_REPOS, 'data/raw/github_repos', added, raw_path_allowed)
        for filename in ('poincare_projection.npy', 'dkt_weights.pth'):
            add_file(archive, ROOT/'data'/filename, 'data/'+filename, added)
        add_file(archive, seed, 'edumatrix.db', added)
        if embedding_cache is not None:
            # Built in the empty validation runtime before any learner request;
            # only model/content hashes and vectors, never document text.
            import math
            with sqlite3.connect(embedding_cache.resolve().as_uri()+'?mode=ro', uri=True) as cache:
                rows = cache.execute('select text,vector_json from embedding_cache').fetchall()
            assert rows and all(re.fullmatch(r'[0-9a-f]{64}', key) for key, _ in rows)
            assert all(len(values := json.loads(vector)) == 384 and
                       all(math.isfinite(value) for value in values) for _, vector in rows)
            add_file(archive, embedding_cache, 'embeddings_cache.db', added)
            data_report['public_course_vectors'] = {'count': len(rows), 'sha256': sha256(embedding_cache),
                'model': 'data/models/multilingual-e5-small', 'contains_original_text': False}
        add_tree(archive, PACKAGING/'wheels', 'packaging/wheels', added)
        for filename in ('install_and_run.bat','stop_services.bat','launch.ps1',
                         '.env.runtime.template','README_作品运行说明.txt','THIRD_PARTY_RUNTIME.md'):
            assert add_file(archive, PACKAGING/filename, filename, added), filename
        archive.writestr('requirements-runtime.txt', (PACKAGING/'requirements-runtime.txt').read_text('utf8'))
        archive.writestr('requirements-lock.txt', lock)
        archive.writestr('PACKAGE_MANIFEST.json', json.dumps({
            'created_at': datetime.now(timezone.utc).isoformat(), 'runtime': 'Windows / Python 3.11 / CPU',
            'course_version': '1.4.4', 'model': '用户在.env配置的真实模型API',
            'frontend': '当前已构建dist，由FastAPI提供', 'data': data_report,
            'contents': sorted(added), 'validation': '实际解压验证结果见同目录DELIVERY_RESULT.json'}, ensure_ascii=False, indent=2))
    (destination/'PACKAGE_SHA256.txt').write_text(sha256(archive_path)+'  '+archive_path.name+'\n',encoding='utf8')
    print(f'Created {archive_path}; {archive_path.stat().st_size} bytes', flush=True)
    return archive_path


def prepare_current_demo_profiles(target: Path) -> dict:
    """Finalize confirmed synthetic profiles through the normal product service."""
    target = target.resolve()
    assert target.is_file() and target != ROOT/'edumatrix.db' and target.name != 'acceptance.sqlite3'
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from app.database import DBUser, DBOnboardingSession, DBProfileSnapshot
    from app.profile_onboarding import DIMENSIONS, finalize_initial_profile, onboarding_status
    with sqlite3.connect(target) as db:
        active = {row[0] for row in db.execute('select username from users where is_active=1')}
        assert active == {value[0] for value in DEMO_ACCOUNTS.values()}
        profiles_before = db.execute('select * from student_profiles order by student_id').fetchall()
        attempts_before = db.execute('select count(*) from assessment_attempts').fetchone()[0]
    report = {'scope': '交付副本合成账号准备，复用已确认画像；不新增回答或学习成绩。', 'accounts': {}}
    engine = create_engine('sqlite:///' + target.as_posix())
    try:
        with Session(engine) as db:
            for alias in ('learner', 'reviewer', 'explorer'):
                user = db.query(DBUser).filter_by(username=alias, is_active=True).one()
                before = onboarding_status(db, user, feature_enabled=True)
                restored_from = None
                if not before['exists'] and not before['finalized'] and not before['legacyComplete']:
                    # The acceptance seed copied the original confirmed profile
                    # inside its diagnostic snapshot, but omitted its session.
                    # Restore that exact evidence in the export; do not invent
                    # answers or project old self-reports over later learning.
                    for snapshot in db.query(DBProfileSnapshot).filter_by(owner_public_id=user.public_id).order_by(DBProfileSnapshot.created_at.asc()):
                        original = snapshot.snapshot or {}
                        confirmed = original.get('self_report') or {}
                        if all(confirmed.get(key, {}).get('values') and
                               confirmed[key].get('turnId') and confirmed[key].get('confirmedAt') for key in DIMENSIONS):
                            session = DBOnboardingSession(owner_public_id=user.public_id, student_id=alias,
                                status='confirmed', current_dimension=DIMENSIONS[-1],
                                confirmed_fields=confirmed, missing_fields=[], checkpoint=len(DIMENSIONS),
                                course_context=original.get('course_context') or {})
                            db.add(session)
                            db.commit()
                            restored_from = snapshot.id
                            break
                    assert restored_from, f'Missing confirmed profile evidence: {alias}'
                ready = onboarding_status(db, user, feature_enabled=True)
                if ready['exists'] and not ready['finalized']:
                    assert ready['status'] == 'confirmed', alias
                    finalize_initial_profile(db, user, feature_enabled=True)
                after = onboarding_status(db, user, feature_enabled=True)
                assert after['finalized'] or (not after['exists'] and after['legacyComplete']), alias
                report['accounts'][alias] = {'before': before, 'after': after,
                    'restored_confirmed_evidence_from': restored_from}
    finally:
        engine.dispose()
    with sqlite3.connect(target) as db:
        assert db.execute('select * from student_profiles order by student_id').fetchall() == profiles_before
        assert db.execute('select count(*) from assessment_attempts').fetchone()[0] == attempts_before
    report['profile_and_learning_records_unchanged'] = True
    return report


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description='Build one current evaluator runtime; leave previous presentations unchanged.')
    parser.add_argument('--runtime-python', type=Path)
    parser.add_argument('--prepare-demo-profiles', type=Path)
    parser.add_argument('--profile-report', type=Path)
    parser.add_argument('--source-db', type=Path, default=ROOT/'scratch/automatic-generation-r207/acceptance.sqlite3')
    parser.add_argument('--embedding-cache', type=Path)
    args = parser.parse_args()
    if args.prepare_demo_profiles:
        os.environ['EDUMATRIX_DB_PATH'] = str(args.prepare_demo_profiles.resolve())
        sys.path.insert(0, str(ROOT))
        report = prepare_current_demo_profiles(args.prepare_demo_profiles)
        assert args.profile_report
        args.profile_report.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf8')
        print('Synthetic demo profiles finalized through the normal service.', flush=True)
        return
    if not args.runtime_python:
        parser.error('--runtime-python is required to build the runtime package')
    build_current_package(args.runtime_python.resolve(), args.source_db, args.embedding_cache)


if __name__ == "__main__":
    main()
