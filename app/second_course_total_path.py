from __future__ import annotations

"""Deterministic two-course path baseline used for demos and verification.

This adapter reads the two packaged manifests, creates a stable set of path
nodes and delegates all scheduling checks to ``validate_total_schedule``.
It is deliberately read-only: no learner progress or completion rows are
written while a baseline is generated.
"""

import json
from pathlib import Path
from typing import Any

from app.multicourse_diagnostic import validate_total_schedule
from course_catalog import (
    ALL_CURATED_COURSE_MANIFESTS,
    MASTER_COURSE_ID,
    SECONDARY_COURSE_ID,
)


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE_DIR = ROOT / "outputs" / "原系统融合重构执行" / "evidence" / "custom_tasks" / "SECOND-COURSE-TOTAL-PATH-01"
TOTAL_PATH_REPORT_PATH = EVIDENCE_DIR / "total_path_report.json"


def _manifest(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _chapter_by_code(manifest: dict[str, Any]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for item in manifest.get("files") or []:
        for code in item.get("knowledge_point_codes") or []:
            result[str(code)] = item
    return result


def _subject_nodes(
    manifest: dict[str, Any],
    *,
    course_id: str,
    start_sequence: int = 1,
) -> list[dict[str, Any]]:
    chapters = _chapter_by_code(manifest)
    points = list(manifest.get("knowledge_points") or [])
    nodes: list[dict[str, Any]] = []
    for offset, point in enumerate(points):
        code = str(point["code"])
        prerequisites = [str(item) for item in point.get("prerequisites") or []]
        nodes.append(
            {
                "id": f"{course_id}::{code}",
                "node_key": code,
                "course_id": course_id,
                "title": str(point["title"]),
                "sequence": start_sequence + offset,
                "prerequisites": prerequisites,
                "target_object_id": str(chapters.get(code, {}).get("chapter_key") or code),
                "estimate_minutes": 35 if point.get("level") == "foundation" else 45 if point.get("level") == "core" else 55,
                "priority": 3 if point.get("level") in {"core", "capstone"} else 2,
                "status": "pending",
                "difficulty": str(point.get("level") or "core"),
                "required": True,
                "rationale": f"{manifest['title']} 的 {point['title']}，按固定知识点先修关系安排。",
            }
        )
    return nodes


def build_total_path_baseline(*, time_budget_minutes: int = 90, max_days: int = 40) -> dict[str, Any]:
    manifests = {_manifest(path)["course_id"]: _manifest(path) for path in ALL_CURATED_COURSE_MANIFESTS}
    master = manifests[MASTER_COURSE_ID]
    secondary = manifests[SECONDARY_COURSE_ID]
    master_codes = {str(point["code"]) for point in master.get("knowledge_points") or []}
    secondary_codes = {str(point["code"]) for point in secondary.get("knowledge_points") or []}

    # Keep each course's canonical prerequisites intact and add only aggregate
    # bridge edges.  These edges belong to the total plan, never to either
    # course manifest: ML orientation unlocks algorithm foundations, graph
    # traversal is a useful gate before Transformer, and the final algorithm
    # capstone is completed before the AI learning-agent project.
    ai_nodes = _subject_nodes(master, course_id=MASTER_COURSE_ID)
    dsa_nodes = _subject_nodes(secondary, course_id=SECONDARY_COURSE_ID)
    by_ai = {item["node_key"]: item for item in ai_nodes}
    by_dsa = {item["node_key"]: item for item in dsa_nodes}
    if "DSA-KP-01" in by_dsa and "AI-KP-01" in master_codes:
        by_dsa["DSA-KP-01"]["prerequisites"].append(f"{MASTER_COURSE_ID}::AI-KP-01")
    if "AI-KP-10" in by_ai and "DSA-KP-14" in secondary_codes:
        by_ai["AI-KP-10"]["prerequisites"].append(f"{SECONDARY_COURSE_ID}::DSA-KP-14")
    if "AI-KP-20" in by_ai and "DSA-KP-25" in secondary_codes:
        by_ai["AI-KP-20"]["prerequisites"].append(f"{SECONDARY_COURSE_ID}::DSA-KP-25")

    subject_paths = [
        {"course_id": MASTER_COURSE_ID, "path_id": "ai-mainline-v1", "nodes": ai_nodes},
        {"course_id": SECONDARY_COURSE_ID, "path_id": "dsa-mainline-v1", "nodes": dsa_nodes},
    ]
    validation = validate_total_schedule(
        subject_paths,
        time_budget_minutes=time_budget_minutes,
        max_days=max_days,
    )
    return {
        "schema_version": "edumatrix.second-course-total-path.v1",
        "status": "ready" if validation["status"] == "valid" else "needs_review",
        "courses": [
            {"course_id": MASTER_COURSE_ID, "title": master["title"], "role": "主课程", "node_count": len(ai_nodes)},
            {"course_id": SECONDARY_COURSE_ID, "title": secondary["title"], "role": "第二课程", "node_count": len(dsa_nodes)},
        ],
        "learning_order": [
            "主课程：AI 与机器学习基础",
            "第二课程：复杂度与数据结构基础",
            "第二课程：图、排序查找与算法设计",
            "主课程：Transformer、LLM、RAG 与 Agent",
            "第二课程：算法综合项目",
            "主课程：个性化学习智能体综合项目",
        ],
        "bridge_edges": [
            {"from": f"{MASTER_COURSE_ID}::AI-KP-01", "to": f"{SECONDARY_COURSE_ID}::DSA-KP-01", "reason": "先建立 AI 学习目标和问题建模，再进入算法基础。"},
            {"from": f"{SECONDARY_COURSE_ID}::DSA-KP-14", "to": f"{MASTER_COURSE_ID}::AI-KP-10", "reason": "图遍历思维为注意力和结构化关系建模提供桥接。"},
            {"from": f"{SECONDARY_COURSE_ID}::DSA-KP-25", "to": f"{MASTER_COURSE_ID}::AI-KP-20", "reason": "完成算法综合实践后再进入学习智能体综合项目。"},
        ],
        "subject_paths": subject_paths,
        "validation": validation,
        "read_only": True,
        "learning_state_written": False,
    }


def write_total_path_report(*, time_budget_minutes: int = 90, max_days: int = 40) -> dict[str, Any]:
    report = build_total_path_baseline(time_budget_minutes=time_budget_minutes, max_days=max_days)
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)
    TOTAL_PATH_REPORT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    return report


if __name__ == "__main__":
    report = write_total_path_report()
    print(json.dumps({"status": report["status"], "days": len(report["validation"]["days"]), "total_minutes": report["validation"]["total_minutes"], "issues": report["validation"]["issues"]}, ensure_ascii=False))
