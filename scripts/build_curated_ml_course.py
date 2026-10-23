from __future__ import annotations

import hashlib
import json
import re
import subprocess
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
AUDIT_PATH = ROOT / "data" / "manifest" / "course_source_audit.json"
OUTPUT_DIR = ROOT / "data" / "curated" / "machine_learning_foundations_v1"
MANIFEST_PATH = OUTPUT_DIR / "course_manifest.json"
PRIMARY_REPOSITORY = "nyandwi-machine-learning-complete"
SCHEMA_VERSION = "edumatrix.course-version-manifest.v1"
PARSER_VERSION = "edumatrix-notebook-to-markdown-v1"

REVIEWED_CANDIDATES = {
    "data-science-from-scratch": "本版不选：以源代码为主，不适合作为零基础主教材。",
    "dtreeviz": "本版不选：聚焦决策树可解释性，适合作为后续专题扩展。",
    "edge-impulse-courseware": "本版不选：面向 TinyML，超出本课程的通用机器学习基础范围。",
    "mlbook-dafriedman": "本版不选：统计推导较深入，适合作为进阶理论课程。",
    "nyandwi-machine-learning-complete": "本版主教材：章节连续，兼顾概念、代码和可验证实验。",
    "rasbt-ml-book-code": "本版不选：与商业教材配套，代码质量高但上下文依赖较强。",
    "ruban-iris-classification": "本版不选：单项目体量较小，后续可作为课程结课案例。",
}

KNOWLEDGE_POINTS = [
    {"code": "ML-KP-01", "title": "Python 机器学习编程基础", "level": "foundation", "prerequisites": []},
    {"code": "ML-KP-02", "title": "NumPy 数组与向量化计算", "level": "foundation", "prerequisites": ["ML-KP-01"]},
    {"code": "ML-KP-03", "title": "Pandas 表格数据处理", "level": "foundation", "prerequisites": ["ML-KP-01", "ML-KP-02"]},
    {"code": "ML-KP-04", "title": "探索性数据分析", "level": "core", "prerequisites": ["ML-KP-03"]},
    {"code": "ML-KP-05", "title": "数据清洗与特征准备", "level": "core", "prerequisites": ["ML-KP-03"]},
    {"code": "ML-KP-06", "title": "监督学习与无监督学习基本范式", "level": "core", "prerequisites": ["ML-KP-04"]},
    {"code": "ML-KP-07", "title": "scikit-learn 训练与推理接口", "level": "core", "prerequisites": ["ML-KP-05", "ML-KP-06"]},
    {"code": "ML-KP-08", "title": "线性分类模型", "level": "core", "prerequisites": ["ML-KP-07"]},
    {"code": "ML-KP-09", "title": "分类任务评估与泛化", "level": "core", "prerequisites": ["ML-KP-08"]},
    {"code": "ML-KP-10", "title": "决策树分类", "level": "core", "prerequisites": ["ML-KP-07"]},
    {"code": "ML-KP-11", "title": "集成学习", "level": "advanced", "prerequisites": ["ML-KP-10"]},
    {"code": "ML-KP-12", "title": "K-Means 聚类", "level": "advanced", "prerequisites": ["ML-KP-06", "ML-KP-07"]},
    {"code": "ML-KP-13", "title": "主成分分析", "level": "advanced", "prerequisites": ["ML-KP-02", "ML-KP-05"]},
]

SELECTIONS = [
    {
        "source_path": "docs/00_intro_to_python.ipynb",
        "output_path": "chapters/00_Python机器学习编程基础.md",
        "title": "Python 机器学习编程基础",
        "objective": "掌握后续实验所需的 Python 语法、数据结构、函数与基础编程模式。",
        "knowledge_point_codes": ["ML-KP-01"],
        "reason": "为没有完整 Python 基础的学习者提供可执行先修入口。",
    },
    {
        "source_path": "docs/01_intro_to_Numpy_for_data_computation.ipynb",
        "output_path": "chapters/01_NumPy数组与向量化计算.md",
        "title": "NumPy 数组与向量化计算",
        "objective": "理解数组形状、索引、广播与向量化，为数值特征处理建立基础。",
        "knowledge_point_codes": ["ML-KP-02"],
        "reason": "机器学习数值计算的核心先修材料，概念与代码单元完整。",
    },
    {
        "source_path": "docs/02_data_manipulation_with_pandas.ipynb",
        "output_path": "chapters/02_Pandas表格数据处理.md",
        "title": "Pandas 表格数据处理",
        "objective": "掌握表格数据读取、选择、变换、聚合和连接的标准工作流。",
        "knowledge_point_codes": ["ML-KP-03"],
        "reason": "覆盖真实机器学习项目前的数据处理主链。",
    },
    {
        "source_path": "docs/06_exploratory_data_analysis.ipynb",
        "output_path": "chapters/03_探索性数据分析.md",
        "title": "探索性数据分析",
        "objective": "通过统计摘要和可视化识别分布、关系、异常与数据质量问题。",
        "knowledge_point_codes": ["ML-KP-04"],
        "reason": "将原始数据转化为可解释建模假设的关键实践章节。",
    },
    {
        "source_path": "docs/07_intro_to_data_preparation.ipynb",
        "output_path": "chapters/04_数据准备概览.md",
        "title": "数据准备概览",
        "objective": "理解训练前清洗、编码、缩放和数据划分的目的与边界。",
        "knowledge_point_codes": ["ML-KP-05"],
        "reason": "以短章节建立数据准备全局框架，承接后续模型实验。",
    },
    {
        "source_path": "docs/11_ml_fundamentals.md",
        "output_path": "chapters/05_机器学习基本范式.md",
        "title": "机器学习基本范式",
        "objective": "建立任务、数据、模型、损失、训练、验证和泛化的统一概念框架。",
        "knowledge_point_codes": ["ML-KP-06", "ML-KP-09"],
        "reason": "原生 Markdown 理论材料完整，适合作为算法章节的概念总纲。",
    },
    {
        "source_path": "docs/12_intro_to_sklearn.ipynb",
        "output_path": "chapters/06_scikit-learn标准工作流.md",
        "title": "scikit-learn 标准工作流",
        "objective": "掌握估计器、fit/predict、数据划分和常用训练接口。",
        "knowledge_point_codes": ["ML-KP-07", "ML-KP-09"],
        "reason": "提供后续经典算法实验共同依赖的工程接口。",
    },
    {
        "source_path": "docs/14_linear_models_for_classification.ipynb",
        "output_path": "chapters/07_线性分类模型.md",
        "title": "线性分类模型",
        "objective": "理解线性决策边界，并完成分类训练、预测和结果评估。",
        "knowledge_point_codes": ["ML-KP-08", "ML-KP-09"],
        "reason": "从基础模型建立监督分类与泛化评估闭环。",
    },
    {
        "source_path": "docs/18_decision_trees_for_classification.ipynb",
        "output_path": "chapters/08_决策树分类.md",
        "title": "决策树分类",
        "objective": "理解树模型的划分、复杂度控制、训练和解释方法。",
        "knowledge_point_codes": ["ML-KP-09", "ML-KP-10"],
        "reason": "提供非线性、可解释分类模型及完整实验。",
    },
    {
        "source_path": "docs/21_ensemble_models.ipynb",
        "output_path": "chapters/09_集成学习.md",
        "title": "集成学习",
        "objective": "理解 Bagging、Boosting 等组合策略及其相对单模型的收益。",
        "knowledge_point_codes": ["ML-KP-09", "ML-KP-11"],
        "reason": "形成从单棵树到高性能组合模型的进阶路径。",
    },
    {
        "source_path": "docs/22_intro_to_unsupervised_learning_with_kmeans_clustering.ipynb",
        "output_path": "chapters/10_K-Means聚类.md",
        "title": "K-Means 聚类",
        "objective": "理解无监督聚类目标、训练过程、结果解释和适用限制。",
        "knowledge_point_codes": ["ML-KP-12"],
        "reason": "补足监督学习之外的无监督学习完整实验。",
    },
    {
        "source_path": "docs/23_a_practical_intro_to_principal_components_analysis.ipynb",
        "output_path": "chapters/11_主成分分析.md",
        "title": "主成分分析",
        "objective": "理解方差保持、线性降维和低维表示的训练与解释。",
        "knowledge_point_codes": ["ML-KP-13"],
        "reason": "以可验证实验连接数值计算、特征准备和无监督表示。",
    },
]


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _canonical_text_bytes(raw: bytes) -> bytes:
    return raw.replace(b"\r\n", b"\n").replace(b"\r", b"\n")


def _git_blob(repo: Path, revision: str, relative_path: str) -> bytes:
    if not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise ValueError("repository revision must be a frozen 40-character SHA")
    result = subprocess.run(
        ["git", "-C", str(repo), "show", f"{revision}:{relative_path}"],
        check=False,
        capture_output=True,
    )
    if result.returncode != 0:
        raise ValueError(f"selected file is absent from frozen commit: {relative_path}")
    return result.stdout


def _source_text(value: Any) -> str:
    if isinstance(value, list):
        return "".join(str(item) for item in value)
    return str(value or "")


def _notebook_markdown(raw: bytes) -> tuple[str, dict[str, int]]:
    notebook = json.loads(raw.decode("utf-8"))
    if int(notebook.get("nbformat", 0)) < 4:
        raise ValueError("only notebook format 4 or newer is accepted")
    blocks: list[str] = []
    markdown_cells = code_cells = stripped_outputs = 0
    for cell in notebook.get("cells", []):
        source = _source_text(cell.get("source")).strip()
        if not source:
            continue
        cell_type = cell.get("cell_type")
        if cell_type == "markdown":
            markdown_cells += 1
            blocks.append(source)
        elif cell_type == "code":
            code_cells += 1
            stripped_outputs += len(cell.get("outputs") or [])
            blocks.append(f"```python\n{source}\n```")
    return "\n\n".join(blocks).strip() + "\n", {
        "markdown_cells": markdown_cells,
        "code_cells": code_cells,
        "stripped_output_count": stripped_outputs,
    }


def _build_document(selection: dict[str, Any], source_raw: bytes, revision: str) -> tuple[bytes, dict[str, int]]:
    if selection["source_path"].endswith(".ipynb"):
        body, conversion = _notebook_markdown(source_raw)
    else:
        body = source_raw.decode("utf-8").replace("\r\n", "\n").replace("\r", "\n").strip() + "\n"
        conversion = {"markdown_cells": 0, "code_cells": 0, "stripped_output_count": 0}
    source_url = (
        "https://github.com/Nyandwi/machine_learning_complete/blob/"
        f"{revision}/{selection['source_path']}"
    )
    header = (
        f"# {selection['title']}\n\n"
        f"> 课程：机器学习基础与实践  \\n"
        f"> 上游来源：[{PRIMARY_REPOSITORY}]({source_url})  \\n"
        f"> 固定版本：`{revision}`  \\n"
        f"> 上游文件：`{selection['source_path']}`  \\n"
        f"> 许可证：MIT，Copyright (c) 2021 Jean de Dieu Nyandwi  \\n"
        f"> 转换说明：Notebook 未执行，所有执行输出与单元元数据均已移除。\n\n"
        f"## 本章目标\n\n{selection['objective']}\n\n"
        "## 精选教材内容\n\n"
    )
    return (header + body).encode("utf-8"), conversion


def build_course() -> dict[str, Any]:
    audit = json.loads(AUDIT_PATH.read_text(encoding="utf-8"))
    approved = {
        item["key"]: item
        for item in audit["sources"]
        if item["default_course_eligibility"] == "approved_default_course_candidate"
    }
    if set(approved) != set(REVIEWED_CANDIDATES):
        raise ValueError("approved repository set differs from the reviewed course selection set")
    source = approved[PRIMARY_REPOSITORY]
    detected = {entry["detected_spdx"] for entry in source["license_files"]}
    if detected != {"MIT"}:
        raise ValueError("primary repository must have a locally hashed MIT license")

    revision = source["git_revision"]
    repo = Path(source["local_path"])
    license_path = source["license_files"][0]["path"]
    license_raw = _git_blob(repo, revision, license_path)
    audited_license = (repo / license_path).read_bytes()
    if _sha256(audited_license) != source["license_files"][0]["sha256"]:
        raise ValueError("working-tree license hash differs from the source audit")
    if _canonical_text_bytes(audited_license) != _canonical_text_bytes(license_raw):
        raise ValueError("frozen commit license content differs from the audited license")
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUTPUT_DIR / "LICENSE.upstream.txt").write_bytes(license_raw)

    known_codes = {item["code"] for item in KNOWLEDGE_POINTS}
    files: list[dict[str, Any]] = []
    for order, selection in enumerate(SELECTIONS):
        if not set(selection["knowledge_point_codes"]).issubset(known_codes):
            raise ValueError(f"unknown knowledge point in {selection['source_path']}")
        source_raw = _git_blob(repo, revision, selection["source_path"])
        transformed, conversion = _build_document(selection, source_raw, revision)
        output_path = OUTPUT_DIR / selection["output_path"]
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(transformed)
        files.append(
            {
                "chapter_order": order,
                "title": selection["title"],
                "repository_key": PRIMARY_REPOSITORY,
                "repository_url": source["url"],
                "git_revision": revision,
                "source_path": selection["source_path"],
                "source_type": Path(selection["source_path"]).suffix.lstrip("."),
                "source_bytes": len(source_raw),
                "source_sha256": _sha256(source_raw),
                "path": selection["output_path"],
                "bytes": len(transformed),
                "sha256": _sha256(transformed),
                "parser_version": PARSER_VERSION,
                "conversion": conversion,
                "license_spdx": "MIT",
                "license_file": "LICENSE.upstream.txt",
                "license_sha256": _sha256(license_raw),
                "source_audit_license_sha256": source["license_files"][0]["sha256"],
                "obligations": ["retain_copyright_notice", "retain_license"],
                "knowledge_point_codes": selection["knowledge_point_codes"],
                "selection_reason": selection["reason"],
            }
        )

    manifest = {
        "schema_version": SCHEMA_VERSION,
        "manifest_version": "course-ml-foundations-1.0.0",
        "generated_at": "2026-08-02T00:00:00+08:00",
        "course_id": "course-machine-learning-foundations-v1",
        "title": "机器学习基础与实践",
        "subject": "人工智能 / 机器学习",
        "description": "覆盖数据处理、监督与无监督学习的 12 章高校机器学习实践课程。",
        "domain_pack": "domain-machine-learning-foundations-v1",
        "knowledge_point_version": "ml-kp-1.0.0",
        "language": "en",
        "content_origin": "GitHub 许可审计后的精选课程；EduMatrix 仅添加来源说明与中文学习目标。",
        "license": "MIT; Copyright (c) 2021 Jean de Dieu Nyandwi. See LICENSE.upstream.txt.",
        "visibility": "public",
        "status": "published",
        "external_material_policy": "Only files enumerated by this manifest are importable.",
        "source_audit": {
            "schema_version": audit["schema_version"],
            "source_manifest_sha256": audit["source_manifest_sha256"],
            "approved_repository_count": len(approved),
        },
        "reviewed_candidates": [
            {
                "repository_key": key,
                "git_revision": approved[key]["git_revision"],
                "license_spdx": approved[key]["license_files"][0]["detected_spdx"],
                "selected_file_count": len(SELECTIONS) if key == PRIMARY_REPOSITORY else 0,
                "decision": reason,
            }
            for key, reason in REVIEWED_CANDIDATES.items()
        ],
        "knowledge_points": KNOWLEDGE_POINTS,
        "files": files,
    }
    MANIFEST_PATH.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return manifest


if __name__ == "__main__":
    result = build_course()
    print(
        json.dumps(
            {
                "manifest": str(MANIFEST_PATH.relative_to(ROOT)),
                "course_id": result["course_id"],
                "documents": len(result["files"]),
                "source_repository": PRIMARY_REPOSITORY,
            },
            ensure_ascii=False,
        )
    )
