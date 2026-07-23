"""Create the evaluator-facing documentation and evidence archive."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "outputs" / "EduMatrix_评委最终介绍文档包_上杉绘梨衣.zip"

DOCS = [
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


def add_file(archive: zipfile.ZipFile, source: Path, target: str) -> bool:
    if not source.exists() or not source.is_file():
        print(f"missing: {source}")
        return False
    archive.write(source, target)
    return True


def evaluator_report() -> dict:
    source = ROOT / "outputs" / "e2e_no_docker" / "report.json"
    raw = json.loads(source.read_text(encoding="utf-8")) if source.exists() else {}
    checks = raw.get("checks", {})
    sandbox = dict(checks.get("sandbox_status", {}))
    health = dict(checks.get("health", {}))
    # Keep only evaluator-useful facts; do not distribute local .env or machine details.
    for key in ("llm_endpoint", "llm_api_key_configured", "llm_model"):
        health.pop(key, None)
    for key in ("python_executable", "multiprocessing_executable", "process_id"):
        sandbox.pop(key, None)
    return {
        "result": raw.get("result", "unknown"),
        "mode": raw.get("mode", "disabled"),
        "started_at": raw.get("started_at"),
        "finished_at": raw.get("finished_at"),
        "checks": {
            "health": health,
            "sandbox_status": sandbox,
            "chat_response": checks.get("chat_response", {}),
            "frontend_sandbox_guard": checks.get("frontend_sandbox_guard", {}),
            "knowledge_page": checks.get("knowledge_page", {}),
            "profile_analysis_page": checks.get("profile_analysis_page", {}),
            "settings_page": checks.get("settings_page", {}),
        },
        "screenshots": [
            "screenshots/01-login.png",
            "screenshots/02-dashboard.png",
            "screenshots/03-chat-empty.png",
            "screenshots/04-chat-response.png",
            "screenshots/05-code-sandbox-disabled.png",
            "screenshots/06-learning-path.png",
            "screenshots/07-knowledge.png",
            "screenshots/08-student-analysis.png",
            "screenshots/09-settings-multimodal.png",
            "screenshots/10-code-sandbox-trusted-local.png",
        ],
    }


def build() -> None:
    if OUTPUT.exists():
        OUTPUT.unlink()
    included = 0
    with zipfile.ZipFile(OUTPUT, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        archive.writestr(
            "README.md",
            "# EduMatrix 评委最终介绍文档包\n\n"
            "队伍：上杉绘梨衣｜学校：西交利物浦大学｜赛题：A3\n\n"
            "本包包含 62 页 Word 技术文档、20 页 PPT、复现说明、技术图、当前前端验收截图和脱敏证据。\n\n"
            "已排除团队任务清单、整改过程、故障诊断笔记、视频、私人联系方式、密码和 API Key。\n\n"
            "默认验收：Windows 原生、deterministic 模式、EDUMATRIX_SANDBOX_MODE=disabled；\n"
            "trusted_local 与 Docker 仅作为按环境配置的代码执行模式。\n",
        )
        for source_name, target_name in DOCS:
            if add_file(archive, ROOT / source_name, target_name):
                included += 1

        figures = ROOT / "outputs" / "figures"
        for path in sorted(figures.glob("*.png")):
            archive.write(path, f"figures/{path.name}")
            included += 1

        screenshots = ROOT / "outputs" / "evaluator_screenshots"
        for path in sorted(screenshots.glob("*.png")):
            archive.write(path, f"screenshots/{path.name}")
            included += 1

        preview = ROOT / "render"
        for path in sorted(preview.glob("slide*.png")):
            archive.write(path, f"ppt_preview/{path.name}")
            included += 1
        add_file(archive, preview / "viewer.html", "ppt_preview/viewer.html")

        archive.writestr("evaluator_report.json", json.dumps(evaluator_report(), ensure_ascii=False, indent=2))
        for source_name, target_name in (
            ("outputs/runtime_security_matrix.json", "runtime_security_matrix.json"),
            ("outputs/trusted_local_smoke.json", "trusted_local_smoke.json"),
        ):
            add_file(archive, ROOT / source_name, target_name)

    print(f"created: {OUTPUT}")
    print(f"document_and_asset_count: {included}")
    print(f"size_bytes: {OUTPUT.stat().st_size}")


if __name__ == "__main__":
    build()
