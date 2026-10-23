from __future__ import annotations

import hashlib
import json
import re
import subprocess
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
REPOSITORY = ROOT / "data" / "raw" / "github_repos" / "edge-impulse-courseware"
OUTPUT_DIR = ROOT / "data" / "curated" / "embedded_edge_intelligence_v1"
MANIFEST_PATH = OUTPUT_DIR / "course_manifest.json"
PROCESSING_REPORT_PATH = OUTPUT_DIR / "processing_report.json"
REVISION = "a3d5f9df06d0b6750d5227eb3e0359e9ffbbe1e6"
REPOSITORY_KEY = "edge-impulse-courseware"
REPOSITORY_URL = "https://github.com/edgeimpulse/courseware-embedded-machine-learning"
SOURCE_PATH = "README.md"
PARSER_VERSION = "edumatrix-edge-course-readme-v1"
LICENSE_SPDX = "CC-BY-NC-SA-4.0"

MODULES = [
    ("Module 1", "边缘机器学习导论", "EDGE-KP-01", "foundation", []),
    ("Module 2", "深度学习与嵌入式约束", "EDGE-KP-02", "foundation", ["EDGE-KP-01"]),
    ("Module 3", "边缘机器学习工作流", "EDGE-KP-03", "core", ["EDGE-KP-01", "EDGE-KP-02"]),
    ("Module 4", "模型量化与部署", "EDGE-KP-04", "core", ["EDGE-KP-03"]),
    ("Module 5", "边缘异常检测", "EDGE-KP-05", "advanced", ["EDGE-KP-03"]),
    ("Module 6", "嵌入式图像分类", "EDGE-KP-06", "advanced", ["EDGE-KP-02", "EDGE-KP-03"]),
    ("Module 7", "目标检测与负责任 AI", "EDGE-KP-07", "advanced", ["EDGE-KP-06"]),
    ("Module 8", "关键词唤醒系统", "EDGE-KP-08", "advanced", ["EDGE-KP-03"]),
]


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _git_blob(path: str) -> bytes:
    if not re.fullmatch(r"[0-9a-f]{40}", REVISION):
        raise ValueError("frozen_revision_required")
    result = subprocess.run(
        ["git", "-C", str(REPOSITORY), "show", f"{REVISION}:{path}"],
        check=False,
        capture_output=True,
    )
    if result.returncode != 0:
        raise ValueError(f"frozen_source_missing:{path}")
    return result.stdout.replace(b"\r\n", b"\n").replace(b"\r", b"\n")


def _module_extract(readme: str, module_number: int) -> tuple[str, list[str], list[str]]:
    pattern = rf"(?ms)^### Module {module_number}:.*?(?=^### Module {module_number + 1}:|^## Attribution)"
    match = re.search(pattern, readme)
    if not match:
        raise ValueError(f"module_not_found:{module_number}")
    block = match.group(0)
    heading, _, rest = block.partition("\n")
    intro, marker, remaining = rest.partition("#### Learning Objectives")
    if not marker:
        raise ValueError(f"learning_objectives_not_found:{module_number}")
    objective_block = remaining.split("#### Section", 1)[0]
    objectives = [
        item.strip()
        for item in re.findall(r"(?m)^\d+\.\s+(.+)$", objective_block)
        if item.strip()
    ]
    sections = re.findall(r"(?m)^#### Section \d+:\s+(.+)$", remaining)
    if not objectives or not sections:
        raise ValueError(f"module_structure_incomplete:{module_number}")
    description = " ".join(line.strip() for line in intro.strip().splitlines() if line.strip())
    return heading.removeprefix("### ").strip(), [description, *objectives], sections


def _license_notice(readme: str) -> bytes:
    general = re.search(r"(?ms)^## License\n(.*?)(?=^## Professional Development)", readme)
    attribution = re.search(r"(?ms)^## Attribution\n(.*)$", readme)
    if not general or not attribution:
        raise ValueError("license_or_attribution_section_missing")
    notice = (
        "# Upstream course-content license and attribution\n\n"
        "Frozen source: " + REPOSITORY_URL + "/tree/" + REVISION + "\n\n"
        "The excerpts below are copied from the upstream README at the frozen revision. "
        "EduMatrix uses only the module descriptions and learning objectives, adapts them "
        "into eight Markdown chapters, adds Chinese titles and source metadata, and does "
        "not redistribute linked videos or binary slide/document assets.\n\n"
        "## Upstream License Notice\n\n" + general.group(1).strip() + "\n\n"
        "## Upstream Attribution\n\n" + attribution.group(1).strip() + "\n"
    )
    return notice.encode("utf-8")


def build_course() -> dict[str, Any]:
    readme_raw = _git_blob(SOURCE_PATH)
    readme = readme_raw.decode("utf-8")
    if "CC BY-NC-SA 4.0" not in readme or "Harvard University" not in readme:
        raise ValueError("required_course_attribution_missing")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    license_raw = _license_notice(readme)
    license_path = OUTPUT_DIR / "LICENSE-AND-ATTRIBUTION.upstream.md"
    license_path.write_bytes(license_raw)

    files: list[dict[str, Any]] = []
    knowledge_points: list[dict[str, Any]] = []
    for order, (module_key, title, code, level, prerequisites) in enumerate(MODULES):
        module_number = order + 1
        upstream_title, content_items, sections = _module_extract(readme, module_number)
        description, *objectives = content_items
        source_url = f"{REPOSITORY_URL}/blob/{REVISION}/{SOURCE_PATH}"
        body = (
            f"# {title}\n\n"
            f"> 上游模块：{upstream_title}  \n"
            f"> 固定来源：[{REPOSITORY_KEY}]({source_url})  \n"
            f"> 固定版本：`{REVISION}`  \n"
            f"> 许可证：CC BY-NC-SA 4.0（署名、非商业、相同方式共享）  \n"
            "> 改编说明：EduMatrix 仅精选上游 README 的模块说明、学习目标和章节名称，"
            "增加中文章名与可追溯元数据；未导入外链视频、博客或二进制课件。\n\n"
            "## 模块说明\n\n"
            f"{description}\n\n"
            "## 学习目标\n\n"
            + "\n".join(f"{index}. {objective}" for index, objective in enumerate(objectives, 1))
            + "\n\n## 学习单元\n\n"
            + "\n".join(f"- {section}" for section in sections)
            + "\n"
        ).encode("utf-8")
        output_path = f"chapters/{order:02d}_{title}.md"
        destination = OUTPUT_DIR / output_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(body)
        knowledge_points.append(
            {"code": code, "title": title, "level": level, "prerequisites": prerequisites}
        )
        files.append(
            {
                "chapter_order": order,
                "title": title,
                "repository_key": REPOSITORY_KEY,
                "repository_url": REPOSITORY_URL,
                "git_revision": REVISION,
                "source_path": SOURCE_PATH,
                "source_type": "md",
                "source_bytes": len(readme_raw),
                "source_sha256": _sha256(readme_raw),
                "source_selector": module_key,
                "path": output_path,
                "bytes": len(body),
                "sha256": _sha256(body),
                "parser_version": PARSER_VERSION,
                "conversion": {
                    "strategy": "readme_module_description_objectives_and_section_titles",
                    "external_links_imported": 0,
                    "binary_assets_imported": 0,
                    "learning_objective_count": len(objectives),
                    "section_count": len(sections),
                },
                "license_spdx": LICENSE_SPDX,
                "license_file": license_path.name,
                "license_sha256": _sha256(license_raw),
                "obligations": ["attribution", "noncommercial", "share_alike", "indicate_changes"],
                "attribution": ["Edge Impulse", "Harvard TinyML / Prof. Vijay Janapa Reddi"],
                "knowledge_point_codes": [code],
                "selection_reason": "公开 README 中具有明确 CC BY-NC-SA 4.0 许可和署名链的模块学习材料。",
            }
        )

    manifest = {
        "schema_version": "edumatrix.course-version-manifest.v1",
        "manifest_version": "course-embedded-edge-intelligence-1.0.0",
        "generated_at": "2026-08-04T00:00:00+08:00",
        "course_id": "course-embedded-edge-intelligence-v1",
        "title": "嵌入式边缘智能技能实践",
        "subject": "电子信息 / 嵌入式人工智能",
        "description": "基于合法公开材料的 8 章嵌入式边缘智能技能领域泛化演示。",
        "domain_pack": "domain-embedded-edge-intelligence-v1",
        "knowledge_point_version": "edge-kp-1.0.0",
        "language": "en",
        "tags": ["嵌入式系统", "边缘智能", "TinyML"],
        "content_origin": "固定 Git commit 的公开课程 README 精选；无领域专家复核，不宣称行业认证。",
        "license": "CC BY-NC-SA 4.0; Edge Impulse and Harvard TinyML attribution retained. See LICENSE-AND-ATTRIBUTION.upstream.md.",
        "visibility": "public",
        "status": "published",
        "claim_boundary": "基于公开材料的第二领域泛化演示；不是独立专家验证或行业认证。",
        "external_material_policy": "Only README excerpts enumerated by this manifest are imported; linked and binary materials are excluded.",
        "source_repository": {
            "key": REPOSITORY_KEY,
            "url": REPOSITORY_URL,
            "git_revision": REVISION,
            "source_path": SOURCE_PATH,
            "source_sha256": _sha256(readme_raw),
        },
        "processing": {
            "parser_version": PARSER_VERSION,
            "deterministic": True,
            "network_required": False,
            "external_model_used": False,
            "selected_material": "module descriptions, learning objectives, section titles",
            "excluded_material": "linked videos, external blogs, PPTX, DOCX, notebooks and other binary assets",
        },
        "knowledge_points": knowledge_points,
        "files": files,
    }
    MANIFEST_PATH.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    processing_report = {
        "schema_version": "edumatrix.course-processing-report.v1",
        "course_id": manifest["course_id"],
        "source_revision": REVISION,
        "source_sha256": _sha256(readme_raw),
        "parser_version": PARSER_VERSION,
        "output_manifest_sha256": _sha256(MANIFEST_PATH.read_bytes()),
        "chapter_count": len(files),
        "license_sha256": _sha256(license_raw),
        "network_calls": 0,
        "external_model_calls": 0,
        "excluded_binary_assets": True,
    }
    PROCESSING_REPORT_PATH.write_text(
        json.dumps(processing_report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return manifest


if __name__ == "__main__":
    result = build_course()
    print(json.dumps({"manifest": str(MANIFEST_PATH), "chapters": len(result["files"])}, ensure_ascii=False))
