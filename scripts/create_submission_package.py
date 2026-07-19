"""Create a clean, reviewable provisional submission archive."""

from __future__ import annotations

import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "outputs" / "EduMatrix_软件杯提交包_待补团队信息.zip"

ROOT_FILES = [
    ".env.example", ".gitignore", ".dockerignore", "README.md", "LICENSE", "NOTICE",
    "Dockerfile", "docker-compose.yml", "requirements.txt", "pytest.ini", "run.py",
    "start.bat", "团队协同开发守则.md", "组内分工.md",
]
OUTPUT_FILES = [
    "EduMatrix_API与数据字典.md", "EduMatrix_完整技术文档总稿.md",
    "EduMatrix_完整技术文档_可提交版.docx", "EduMatrix_本轮整改记录_20260719.md",
    "EduMatrix_比赛答辩演示脚本.md", "EduMatrix_测试说明书.md",
    "EduMatrix_评委环境安装与复现备忘录.md", "EduMatrix_软件杯赛题冲刺任务清单.md",
    "EduMatrix_部署运维说明书.md", "EduMatrix_需求实现测试追踪矩阵.md",
    "EduMatrix_风险整改清单.md", "EduMatrix_系统设计与实现方案.md",
    "EduMatrix_公开依据与引用清单.md", "EduMatrix_AI编程工具使用说明.md",
    "EduMatrix_软件杯答辩PPT_待补团队信息.pptx", "EduMatrix_软件杯PPT逐页讲解备注.md",
    "EduMatrix_提交包内容说明.md",
]


def add_file(archive: zipfile.ZipFile, path: Path, arcname: str) -> None:
    if path.exists() and path.is_file():
        archive.write(path, arcname)


def add_tree(archive: zipfile.ZipFile, directory: Path, prefix: str, *, include_suffixes=None) -> None:
    if not directory.exists():
        return
    for path in directory.rglob("*"):
        if not path.is_file():
            continue
        relative = path.relative_to(directory)
        if any(part in {".venv", "node_modules", "__pycache__", ".git", ".pytest_cache", "dist"} for part in path.parts):
            if not ("frontend" in path.parts and "dist" in path.parts):
                continue
        if include_suffixes and path.suffix.lower() not in include_suffixes:
            continue
        arcname = f"{prefix}/{relative.as_posix()}"
        archive.write(path, arcname)


def build() -> None:
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    if OUTPUT.exists():
        OUTPUT.unlink()
    with zipfile.ZipFile(OUTPUT, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for filename in ROOT_FILES:
            add_file(archive, ROOT / filename, filename)
        for directory in ("app", "scripts", "tests"):
            add_tree(archive, ROOT / directory, directory)
        add_tree(archive, ROOT / "frontend/src", "frontend/src")
        add_tree(archive, ROOT / "frontend/public", "frontend/public")
        for filename in ("package.json", "package-lock.json"):
            add_file(archive, ROOT / "frontend" / filename, f"frontend/{filename}")
        add_tree(archive, ROOT / "frontend/dist", "frontend/dist")
        for path in (ROOT / "data" / "manifest", ROOT / "data" / "patches"):
            add_tree(archive, path, path.relative_to(ROOT).as_posix())
        for filename in ("poincare_projection.npy", "dkt_weights.pth"):
            add_file(archive, ROOT / "data" / filename, f"data/{filename}")
        for filename in OUTPUT_FILES:
            add_file(archive, ROOT / "outputs" / filename, f"outputs/{filename}")
        add_tree(archive, ROOT / "outputs" / "e2e_no_docker", "outputs/e2e_no_docker")
        add_tree(archive, ROOT / "outputs" / "innovation_evidence", "outputs/innovation_evidence")
        add_file(archive, ROOT / "outputs" / "runtime_security_matrix.json", "outputs/runtime_security_matrix.json")
        archive.writestr(
            "SUBMISSION_PACKAGE_README.txt",
            "EduMatrix provisional submission package.\n"
            "Before official submission, add team information, official naming, video and authorization confirmation.\n"
            "Default evaluator mode: EDUMATRIX_SANDBOX_MODE=disabled.\n",
        )
    print(f"created: {OUTPUT}")
    print(f"size_bytes: {OUTPUT.stat().st_size}")


if __name__ == "__main__":
    build()
