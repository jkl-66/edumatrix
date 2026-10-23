"""Build a high-fidelity, non-PPT competition submission set.

Inputs are limited to the current source tree, the two canonical course
manifests, the read-only current demo database, and current browser evidence.
The previous submission archives are deliberately not read.
"""

from __future__ import annotations

import csv
import hashlib
import json
import re
import sqlite3
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from docx import Document
from docx.enum.section import WD_SECTION
from docx.enum.table import WD_TABLE_ALIGNMENT, WD_CELL_VERTICAL_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Inches, Pt, RGBColor
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from PIL import Image, ImageDraw, ImageFont


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs" / "competition_submission_rebuild"
DOCS = OUT / "documents"
DATA = OUT / "test_data"
FIGURES = OUT / "figures"
EVIDENCE = OUT / "evidence"
DB_PATH = ROOT / "edumatrix.db"

COURSE_PATHS = (
    ROOT / "data/curated/machine_learning_foundations_v1/course_manifest.json",
    ROOT / "data/curated/ai_deep_learning_agents_v1/course_manifest.json",
)
COURSE_IDS = {"course-machine-learning-foundations-v1", "course-ai-deep-learning-agents-v1"}
TEN_DIMENSIONS = (
    ("knowledge_mastery", "知识基础与掌握度", "诊断和学习事件反映的知识点掌握水平"),
    ("misconception_profile", "易错点与概念理解", "稳定误概念、易混点和错误归因"),
    ("understanding_fluency_transfer", "理解与迁移能力", "把理解迁移到变式、代码和新任务的能力"),
    ("cognitive_processing", "认知加工方式", "处理复杂内容时的负荷和拆解方式"),
    ("learning_strategy", "学习策略", "复习、练习、实验和反馈的使用方式"),
    ("metacognition", "元认知", "自评、信心校准和自主调整"),
    ("motivation_and_purpose", "动机与目标", "学习目标、岗位/项目关联和投入动机"),
    ("affect_resilience", "情绪与抗挫力", "面对错误、失败和复杂任务的持续性"),
    ("interaction_preference", "互动偏好", "图示、代码、推导、追问和提示偏好"),
    ("learning_context", "学习情境", "专业、设备、时间、课程和环境约束"),
)
DIAGNOSTIC_KINDS = ("theory", "application", "engineering_judgment")


def ts() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for b in iter(lambda: f.read(1024 * 1024), b""):
            h.update(b)
    return h.hexdigest()


def git_value(*args: str) -> str:
    try:
        return subprocess.check_output(["git", *args], cwd=ROOT, text=True, stderr=subprocess.DEVNULL).strip()
    except Exception:
        return "unavailable"


def course_manifests() -> list[dict[str, Any]]:
    result = []
    for path in COURSE_PATHS:
        raw = json.loads(path.read_text(encoding="utf-8"))
        result.append({"path": str(path.relative_to(ROOT)).replace("\\", "/"), "raw": raw})
    return result


def safe_db_value(value: Any, owner: str = "") -> Any:
    if isinstance(value, dict):
        out = {}
        for key, item in value.items():
            key_l = str(key).lower()
            if any(token in key_l for token in ("password", "secret", "api_key", "apikey", "token")):
                out[key] = "[redacted]"
            elif key_l in {"owner_public_id", "legacy_student_id", "student_id", "user_id", "username", "email", "phone"}:
                out[key] = "[demo-owner]" if key_l != "legacy_student_id" else "[demo-learner]"
            else:
                out[key] = safe_db_value(item, owner)
        return out
    if isinstance(value, list):
        return [safe_db_value(item, owner) for item in value]
    if isinstance(value, str) and owner and (value == owner or value == "lzz"):
        return "[demo-owner]"
    return value


def db_rows(db: sqlite3.Connection, query: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    cur = db.execute(query, params)
    names = [d[0] for d in cur.description]
    return [dict(zip(names, row)) for row in cur.fetchall()]


def build_knowledge_data(courses: list[dict[str, Any]]) -> dict[str, Any]:
    kb = DATA / "knowledge_base"
    kb.mkdir(parents=True, exist_ok=True)
    chapters: list[dict[str, Any]] = []
    kps: list[dict[str, Any]] = []
    chunks: list[dict[str, Any]] = []
    refs: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []
    licenses: list[dict[str, Any]] = []
    for course in courses:
        raw = course["raw"]
        course_id = raw["course_id"]
        course_dir = ROOT / "data/curated" / ("machine_learning_foundations_v1" if course_id.startswith("course-machine-learning-foundations") else "ai_deep_learning_agents_v1")
        for kp in raw.get("knowledge_points", []):
            code = kp.get("code") or kp.get("id")
            kps.append({"course_id": course_id, "course_version": raw.get("manifest_version"), "knowledge_point_id": code, "title": kp.get("title"), "level": kp.get("level"), "prerequisites": kp.get("prerequisites", [])})
            for prereq in kp.get("prerequisites", []):
                edges.append({"course_id": course_id, "prerequisite": prereq, "dependent": code, "relation": "PREREQUISITE_OF"})
        for index, entry in enumerate(raw.get("files", [])):
            relative = str(entry.get("path") or "")
            path = course_dir / relative
            if not path.is_file():
                path = course_dir / "chapters" / Path(relative).name
            if not path.is_file():
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            chapters.append({"course_id": course_id, "course_version": raw.get("manifest_version"), "chapter_index": index, "chapter_id": f"{course_id}:chapter:{index:02d}", "title": entry.get("title") or path.stem, "path": str(path.relative_to(ROOT)).replace("\\", "/"), "sha256": sha(path), "knowledge_point_codes": entry.get("knowledge_point_codes", [])})
            licenses.append({"course_id": course_id, "path": str(path.relative_to(ROOT)).replace("\\", "/"), "license_spdx": entry.get("license_spdx"), "license_file": entry.get("license_file"), "license_sha256": entry.get("license_sha256"), "git_revision": entry.get("git_revision"), "source_sha256": entry.get("source_sha256")})
            # Preserve the complete current course text. Chunks are formed by
            # consecutive paragraphs up to 1,200 characters; a long paragraph
            # is split deterministically. This avoids title-only fragments and
            # keeps every source span and hash independently auditable.
            segments = []
            cursor = 0
            for match in re.finditer(r"\n\s*\n", text):
                raw_segment = text[cursor:match.start()]
                segment = raw_segment.strip()
                if segment:
                    start = cursor + len(raw_segment) - len(raw_segment.lstrip())
                    segments.append((start, segment))
                cursor = match.end()
            tail = text[cursor:]
            if tail.strip():
                segments.append((cursor + len(tail) - len(tail.lstrip()), tail.strip()))
            packed = []
            current_text = ""
            current_start = None
            current_end = None
            for segment_start, segment in segments:
                while segment:
                    available = 1200 - len(current_text) - (2 if current_text else 0)
                    if available <= 0:
                        packed.append((current_start, current_text, current_end))
                        current_text, current_start, current_end = "", None, None
                        available = 1200
                    piece = segment[:available]
                    segment = segment[available:]
                    if current_start is None:
                        current_start = segment_start
                    if current_text:
                        current_text += "\n\n"
                    current_text += piece
                    current_end = segment_start + len(piece)
                    segment_start += len(piece)
                    if len(current_text) >= 1200:
                        packed.append((current_start, current_text, current_end))
                        current_text, current_start, current_end = "", None, None
            if current_text:
                packed.append((current_start, current_text, current_end))
            for part_index, (start, content, end) in enumerate(packed):
                chunk_id = hashlib.sha256(f"{course_id}:{relative}:{part_index}:{start}".encode()).hexdigest()[:24]
                ref_id = f"src-{chunk_id}"
                chunks.append({"chunk_id": chunk_id, "course_id": course_id, "course_version": raw.get("manifest_version"), "chapter_id": f"{course_id}:chapter:{index:02d}", "source_document": str(path.relative_to(ROOT)).replace("\\", "/"), "source_ref_id": ref_id, "source_span": {"start_char": start, "end_char": end}, "content": content, "content_sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(), "knowledge_point_codes": entry.get("knowledge_point_codes", [])})
                refs.append({"source_ref_id": ref_id, "course_id": course_id, "course_version": raw.get("manifest_version"), "document_path": str(path.relative_to(ROOT)).replace("\\", "/"), "chapter_id": f"{course_id}:chapter:{index:02d}", "location": {"start_char": start, "end_char": end}, "quote": content, "content_sha256": hashlib.sha256(content.encode("utf-8")).hexdigest()})
    def dump_json(path: Path, value: Any) -> None:
        path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    def dump_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
        path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")
    dump_json(kb / "course_catalog.json", [{"course_id": c["raw"]["course_id"], "course_version": c["raw"].get("manifest_version"), "title": c["raw"].get("title"), "subject": c["raw"].get("subject"), "knowledge_point_count": len(c["raw"].get("knowledge_points", [])), "source_file_count": len(c["raw"].get("files", []))} for c in courses])
    dump_jsonl(kb / "chapters.jsonl", chapters)
    dump_jsonl(kb / "knowledge_points.jsonl", kps)
    dump_jsonl(kb / "chunks.jsonl", chunks)
    dump_jsonl(kb / "source_refs.jsonl", refs)
    dump_jsonl(kb / "prerequisite_edges.jsonl", edges)
    dump_json(kb / "license_records.json", licenses)
    (kb / "KNOWLEDGE_BASE_README.md").write_text(f"""# 当前两课程知识库切片\n\n本切片从当前课程正文生成，不复制旧提交材料。\n\n- 课程数：{len(courses)}\n- 章节记录：{len(chapters)}\n- 知识点记录：{len(kps)}\n- 正文分块：{len(chunks)}\n- 可回链来源：{len(refs)}\n\n每个 chunk 包含课程版本、源文件、字符范围、内容哈希和 source_ref_id。测试和指标文档只能引用这些可回链正文，不使用人工摘要替代来源。\n""", encoding="utf-8")
    return {"chapters": chapters, "knowledge_points": kps, "chunks": chunks, "refs": refs, "licenses": licenses}


def extract_profiles_and_resources() -> dict[str, Any]:
    if not DB_PATH.is_file():
        return {"profiles": [], "resources": [], "events": [], "diagnostics": []}
    db = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    owner = "usr-5e1cb68406a2423aa92f3bcdd2f5de50"
    profile_ids = ("lzzdemo03-ml-profile", "lzzdemo03-ai-profile", "profile_demo_beginner-profile-snapshot", "profile_demo_engineer-profile-snapshot", "profile_demo_theorist-profile-snapshot", "ps-profile-update-a69e9c980ef742e392008df6", "psagg-0c3016e2f6cd5c4ff81688c9eb9992cf9993ea014bf470a0", "psagg-b3dd63901cf1b65f2ed5668acce04dd6b1f8d8a3a176f90d")
    rows = db_rows(db, "select id, profile_version, snapshot, created_at from profile_snapshots where id in (?,?,?,?,?,?,?,?)", profile_ids)
    by_id = {row["id"]: row for row in rows}
    def snapshot(profile_id: str) -> dict[str, Any]:
        row = by_id.get(profile_id, {})
        body = json.loads(row.get("snapshot") or "{}")
        return {"source_snapshot_id": profile_id, "profile_version": row.get("profile_version"), "created_at": row.get("created_at"), "snapshot": safe_db_value(body, owner)}
    bases = [snapshot("lzzdemo03-ml-profile"), snapshot("lzzdemo03-ai-profile"), snapshot("ps-profile-update-a69e9c980ef742e392008df6")]
    # Attach the latest continuous ten-dimension state to the demo course
    # snapshots. This is a derived evaluation view, not a new user record.
    continuous_ml = snapshot("ps-profile-update-a69e9c980ef742e392008df6")
    continuous_ai = snapshot("psagg-b3dd63901cf1b65f2ed5668acce04dd6b1f8d8a3a176f90d")
    mastery_ml = snapshot("lzzdemo03-ml-profile")
    mastery_ai = snapshot("lzzdemo03-ai-profile")
    profiles = []
    try:
        from app.profile_adaptation import build_profile_adaptation
    except Exception:
        build_profile_adaptation = None
    labels = [("learner-visual-beginner", "视觉型初学者", "course-machine-learning-foundations-v1", snapshot("profile_demo_beginner-profile-snapshot"), continuous_ml, mastery_ml), ("learner-project-engineer", "项目实践型学习者", "course-ai-deep-learning-agents-v1", snapshot("profile_demo_engineer-profile-snapshot"), continuous_ai, mastery_ai), ("learner-theory-researcher", "理论研究型学习者", "course-machine-learning-foundations-v1", snapshot("profile_demo_theorist-profile-snapshot"), continuous_ml, mastery_ml)]
    for logical_id, label, course_id, base, continuous, mastery_source in labels:
        b = base["snapshot"]
        c = continuous["snapshot"]
        projection = b.get("profile_projection") or c.get("profile_projection") or {}
        dims = (c.get("dimension_states") or {})
        mastery_body = mastery_source["snapshot"]
        adaptation_plan = base["snapshot"].get("profile_adaptation_plan") if isinstance(base["snapshot"].get("profile_adaptation_plan"), dict) else None
        if build_profile_adaptation is not None:
            if adaptation_plan is None:
                try:
                    point = {"id": (next(iter((mastery_body.get("concept_mastery") or {}).keys()), "")), "title": "当前课程焦点知识点"}
                    adaptation_plan = build_profile_adaptation(base["snapshot"], knowledge_point=point)
                except Exception as exc:
                    adaptation_plan = {"status": "unavailable", "reason": f"{type(exc).__name__}: {exc}"}
        profiles.append({"profile_id": logical_id, "archetype": label, "course_id": course_id, "course_version": "current_db_demo_snapshot", "data_label": "脱敏重放与当前画像引擎派生视图，不是真实用户资料", "source_snapshot_ids": [base["source_snapshot_id"], continuous["source_snapshot_id"], mastery_source["source_snapshot_id"]], "background": {"major": projection.get("major", "人工智能相关专业"), "learning_context": projection.get("learning_context", "当前课程学习环境")}, "learning_goal": projection.get("learning_goals", ["完成当前课程的可复现实验"]), "preferences": projection.get("interaction_preferences", ["分步解释", "可运行示例"]), "entrance_diagnostic": {"required_dimensions": list(DIAGNOSTIC_KINDS), "source": "current diagnostic schema", "status": "snapshot-derived; item-level diagnostic records exported separately"}, "mastery_snapshot": {"overall": b.get("mastery") or projection.get("mastery") or mastery_body.get("mastery"), "concept_mastery": b.get("concept_mastery") or mastery_body.get("concept_mastery") or c.get("concept_mastery") or {}, "weak_points": b.get("weak_points") or projection.get("weak_points") or mastery_body.get("weak_points") or c.get("weak_points") or [], "confidence": b.get("confidence") or mastery_body.get("confidence") or c.get("confidence")}, "ten_dimensions": [{"key": key, "label": label_text, "definition": definition, "score": (dims.get(key) or {}).get("score"), "confidence": (dims.get(key) or {}).get("confidence"), "status": (dims.get(key) or {}).get("status", "未观测"), "evidence": (dims.get(key) or {}).get("evidence_fragments", []), "resource_influence": "由当前 profile_adaptation 参与难度、脚手架、表达、节奏或内容重点决策", "teaching_influence": "由当前画像/路径/反馈聚合参与下一任务或复测决策"} for key, label_text, definition in TEN_DIMENSIONS], "adaptation_plan": adaptation_plan, "source_kind": "current_db_snapshot_plus_current_engine_projection"})
    artifact_rows = db_rows(db, "select a.id, a.course_id, a.artifact_type, a.title, a.status, a.current_version_id, av.content, av.content_hash from artifacts a left join artifact_versions av on av.id=a.current_version_id where a.owner_public_id=? and a.course_id in (?,?) and a.id like 'lzzdemo03-%' order by a.course_id, a.id", (owner, "course-machine-learning-foundations-v1", "course-ai-deep-learning-agents-v1"))
    resources = []
    for row in artifact_rows:
        try:
            content = safe_db_value(json.loads(row.get("content") or "{}"), owner)
        except Exception:
            content = {"raw_text": row.get("content") or ""}
        resources.append({"artifact_id": row["id"], "course_id": row["course_id"], "artifact_type": row["artifact_type"], "title": "[脱敏资源]", "status": row["status"], "version_id": row["current_version_id"], "content_hash": row["content_hash"], "content": content, "source_kind": "current_db_demo_artifact"})
    event_rows = db_rows(db, "select id, course_id, event_type, payload, occurred_at, evidence_strength, evidence_status, evidence_reason, mastery_eligible, completion_effect from learning_events where owner_public_id=? and course_id in (?,?) order by occurred_at, id", (owner, "course-machine-learning-foundations-v1", "course-ai-deep-learning-agents-v1"))
    events = [{"event_id": row["id"], "course_id": row["course_id"], "event_type": row["event_type"], "payload": safe_db_value(json.loads(row.get("payload") or "{}"), owner), "occurred_at": row["occurred_at"], "evidence_strength": row.get("evidence_strength"), "evidence_status": row.get("evidence_status"), "evidence_reason": row.get("evidence_reason"), "mastery_eligible": row.get("mastery_eligible"), "completion_effect": row.get("completion_effect")} for row in event_rows if str(row["id"]).startswith("lzzdemo03-")]
    diagnostic_rows = db_rows(db, "select a.id, a.course_id, a.mode, a.answer, a.score, a.correct, a.confidence, a.grading_status, a.submitted_at, v.prompt, v.primary_knowledge_point_id, v.scoring_rule from assessment_attempts a left join assessment_question_versions v on v.id=a.question_version_id where a.owner_public_id=? and a.mode='practice' and a.id like 'lzzdemo03-%' order by a.submitted_at", (owner,))
    diagnostics = [{"attempt_id": row["id"], "course_id": row["course_id"], "mode": row["mode"], "answer": safe_db_value(json.loads(row.get("answer") or "{}"), owner), "score": row["score"], "correct": row["correct"], "confidence": row["confidence"], "grading_status": row["grading_status"], "submitted_at": row["submitted_at"], "prompt": row["prompt"], "knowledge_point_id": row["primary_knowledge_point_id"], "diagnostic_dimension": (json.loads(row["scoring_rule"] or "{}").get("diagnostic_dimension") if row.get("scoring_rule") else None)} for row in diagnostic_rows]
    for profile in profiles:
        profile["entrance_diagnostic"]["records"] = [item for item in diagnostics if item.get("course_id") == profile["course_id"]][:6]
    source_rows = db_rows(db, "select sr.id, sr.source_document_id, sr.chapter_id, sr.parser_version, sr.page_number, sr.char_start, sr.char_end, sr.content_hash, sr.quote, sr.location_kind, sr.location_index, sr.location_label, sd.course_id, sd.filename, sd.title, sd.content_hash as document_content_hash from source_refs sr left join source_documents sd on sd.id=sr.source_document_id where sd.course_id in (?,?) order by sd.course_id, sr.id", ("course-machine-learning-foundations-v1", "course-ai-deep-learning-agents-v1"))
    db_source_refs = [{"source_ref_id": row["id"], "source_document_id": row["source_document_id"], "course_id": row["course_id"], "chapter_id": row["chapter_id"], "parser_version": row["parser_version"], "page_number": row["page_number"], "char_start": row["char_start"], "char_end": row["char_end"], "content_hash": row["content_hash"], "quote": row["quote"], "location_kind": row["location_kind"], "location_index": row["location_index"], "location_label": row["location_label"], "document_filename": row["filename"], "document_title": row["title"], "document_content_hash": row["document_content_hash"]} for row in source_rows]
    return {"profiles": profiles, "profile_adaptations": [{"profile_id": p["profile_id"], "adaptation_plan": p.get("adaptation_plan")} for p in profiles], "resources": resources, "events": events, "diagnostics": diagnostics, "db_source_refs": db_source_refs}


def draw_figures() -> list[Path]:
    FIGURES.mkdir(parents=True, exist_ok=True)
    try:
        font = ImageFont.truetype("C:/Windows/Fonts/msyh.ttc", 28)
        small = ImageFont.truetype("C:/Windows/Fonts/msyh.ttc", 20)
    except Exception:
        font = ImageFont.load_default(); small = font
    specs = [
        ("01_architecture.png", "EduMatrix 当前系统架构", ["学习者与课程上下文", "画像/入学诊断", "Hybrid RAG + 来源证据", "Agent 协同", "资源与反馈", "画像/路径/复习更新"]),
        ("02_learning_loop.png", "学习闭环", ["诊断", "画像", "检索", "生成", "审核", "决策", "反馈"]),
        ("03_agent_contract.png", "四阶段 Agent 协同", ["Diagnosis", "Domain Generation", "Evidence Review", "Decision Orchestration"]),
        ("04_evidence_pipeline.png", "知识证据管线", ["正文", "chunk", "source_ref", "claim", "review", "version"]),
        ("05_profile_influence.png", "十维画像影响面", ["掌握度", "误概念", "迁移", "认知加工", "策略", "元认知", "动机", "抗挫", "互动", "情境"]),
        ("06_api_data_boundary.png", "API 与数据边界", ["认证", "课程范围", "对象 owner", "来源权限", "资源版本", "学习事件"]),
        ("07_feedback_state_machine.png", "反馈状态机", ["作答", "记录事件", "证据分级", "聚合消费", "路径更新", "复测"]),
        ("08_deployment_topology.png", "部署拓扑", ["浏览器", "Vite", "FastAPI", "SQLite", "课程正文", "可选 Docker"]),
        ("09_metric_protocol.png", "指标评测协议", ["冻结集", "claim", "适配评分", "覆盖加权", "失败保留", "内部复核"]),
        ("10_evidence_levels.png", "证据等级", ["源码", "单元测试", "API", "浏览器", "数据契约", "正式指标"]),
    ]
    outputs=[]
    for filename, title, labels in specs:
        img=Image.new("RGB",(1500,850),(18,28,44)); d=ImageDraw.Draw(img); d.text((70,45),title,font=font,fill=(110,220,205))
        y=170
        for i,label in enumerate(labels):
            x=100+(i%3)*465; yy=y+(i//3)*155
            d.rounded_rectangle((x,yy,x+350,yy+82),radius=12,fill=(37,58,83),outline=(99,170,188),width=2)
            d.text((x+20,yy+25),label,font=small,fill=(235,242,247))
            if i>0 and i%3!=0:
                d.line((x-75,yy+41,x-8,yy+41),fill=(95,170,185),width=4)
        p=FIGURES/filename; img.save(p); outputs.append(p)
    return outputs


def collect_current_screenshots() -> list[Path]:
    source = ROOT / "outputs/原系统融合重构执行/evidence/custom_tasks/COURSE-DATA-DEMO-RESEED-03/browser"
    target = EVIDENCE / "screenshots"
    target.mkdir(parents=True, exist_ok=True)
    names = [
        "1920x1080-ml-home.png", "1920x1080-ml-path.png", "1920x1080-ml-resources.png",
        "1920x1080-ml-profile.png", "1920x1080-ai-home.png", "1920x1080-ai-path.png",
        "1920x1080-ai-resources.png", "1920x1080-ai-profile.png",
    ]
    copied = []
    for name in names:
        src = source / name
        if src.is_file():
            dst = target / name
            shutil.copy2(src, dst)
            copied.append(dst)
    return copied


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")


def build_cases(kb: dict[str, Any], profiles: list[dict[str, Any]], evidence: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    categories = ["entrance_diagnostic", "mastery", "profile_influence", "course_scope", "retrieval", "source_binding", "lesson_generation", "lab_generation", "tiered_quiz", "evidence_review", "decision", "feedback", "path_update", "review_schedule", "authorization", "recovery", "sandbox", "version_conflict"]
    cases=[]
    evidence = evidence or {"resources": [], "events": [], "diagnostics": []}
    kp_by_course={}
    for kp in kb["knowledge_points"]:
        kp_by_course.setdefault(kp["course_id"],[]).append(kp)
    for i in range(60):
        profile=profiles[i%len(profiles)]; cat=categories[i%len(categories)]; hard=i>=42
        kps=kp_by_course.get(profile["course_id"],[])[:3]
        course_resources = [r for r in evidence.get("resources", []) if r.get("course_id") == profile["course_id"]]
        course_events = [e for e in evidence.get("events", []) if e.get("course_id") == profile["course_id"]]
        course_diagnostics = [d for d in evidence.get("diagnostics", []) if d.get("course_id") == profile["course_id"]]
        executed = i < 12
        cases.append({"case_id":f"xh-202630-rebuild-{i+1:03d}","course_id":profile["course_id"],"course_version":profile["course_version"],"profile_id":profile["profile_id"],"category":cat,"difficulty":"challenge" if hard else "standard","input":{"goal":profile["learning_goal"],"query":f"围绕 {kps[0]['title'] if kps else '当前课程'} 完成 {cat} 测试"},"required_knowledge_points":[x["knowledge_point_id"] for x in kps],"critical_knowledge_points":[x["knowledge_point_id"] for x in kps[:1]],"expected_resource_types":["lesson","lab_guide","tiered_quiz"] if cat in {"lesson_generation","lab_generation","tiered_quiz"} else [],"expected_difficulty":"foundation" if profile["profile_id"]=="learner-visual-beginner" else "scaffolded" if profile["profile_id"]=="learner-project-engineer" else "transfer","expected_evidence":[x["source_ref_id"] for x in kb["refs"] if x["course_id"]==profile["course_id"]][:2],"expected_decision":"reject_or_collect_evidence" if hard else "continue_or_adapt","actual_execution_status":"current_db_evidence" if executed else "designed_not_run","actual_agent_trace":{"source":"current_db_profile_and_resource_projection","profile_id":profile["profile_id"],"stages":["diagnosis","generation","evidence_review","decision_orchestration"]} if executed else None,"actual_resources": [{"artifact_id":r.get("artifact_id"),"artifact_type":r.get("artifact_type"),"version_id":r.get("version_id"),"status":r.get("status")} for r in course_resources[:6]] if executed else [],"actual_feedback": [{"event_id":e.get("event_id"),"event_type":e.get("event_type"),"evidence_status":e.get("evidence_status"),"mastery_eligible":e.get("mastery_eligible")} for e in course_events[:6]] if executed else [],"actual_diagnostics": course_diagnostics[:6] if executed else [],"actual_agent_trace_ref":profile["profile_id"] if executed else None,"actual_resources_ref":"test_data/resources.jsonl" if executed else None,"actual_feedback_ref":"test_data/learning_events.jsonl" if executed else None,"failure_reason":"challenge case requires conservative refusal or extra evidence" if hard else ("not executed; frozen challenge scenario" if not executed else "")})
    return cases


def docx_from_markdown(title: str, content: str, path: Path, figures: list[Path] | None = None, tables: list[tuple[str, list[list[str]]]] | None = None) -> None:
    document=Document(); sec=document.sections[0]; sec.top_margin=Inches(.65); sec.bottom_margin=Inches(.65); sec.left_margin=Inches(.75); sec.right_margin=Inches(.75)
    normal=document.styles["Normal"]; normal.font.name="等线"; normal.font.size=Pt(10.5)
    p=document.add_paragraph(); p.alignment=WD_ALIGN_PARAGRAPH.CENTER; run=p.add_run(title); run.bold=True; run.font.size=Pt(22); run.font.color.rgb=RGBColor(18,91,110)
    p=document.add_paragraph(); p.alignment=WD_ALIGN_PARAGRAPH.CENTER; p.add_run("XH-202630 · 领域知识个性化生成与多智能体协同决策系统研究 · 当前工作树重建材料").italic=True
    # Word/LibreOffice can update this field after opening the document.
    toc_heading = document.add_paragraph(); toc_heading.alignment = WD_ALIGN_PARAGRAPH.CENTER; toc_heading.add_run("目录").bold = True
    toc_para = document.add_paragraph()
    begin = OxmlElement("w:fldChar"); begin.set(qn("w:fldCharType"), "begin")
    instr = OxmlElement("w:instrText"); instr.set(qn("xml:space"), "preserve"); instr.text = 'TOC \\o "1-3" \\h \\z \\u'
    separate = OxmlElement("w:fldChar"); separate.set(qn("w:fldCharType"), "separate")
    text_node = OxmlElement("w:t"); text_node.text = "打开文档后更新目录"
    end = OxmlElement("w:fldChar"); end.set(qn("w:fldCharType"), "end")
    toc_para._p.extend([begin, instr, separate, text_node, end])
    header = sec.header.paragraphs[0]; header.text = f"EduMatrix | XH-202630 | {title}"; header.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    header.runs[0].font.size = Pt(8); header.runs[0].font.color.rgb = RGBColor(100, 110, 120)
    footer = sec.footer.paragraphs[0]; footer.alignment = WD_ALIGN_PARAGRAPH.CENTER
    footer_run = footer.add_run("XH-202630 · 第 ")
    footer_run.font.size = Pt(8)
    page_begin = OxmlElement("w:fldChar"); page_begin.set(qn("w:fldCharType"), "begin")
    page_instr = OxmlElement("w:instrText"); page_instr.set(qn("xml:space"), "preserve"); page_instr.text = "PAGE"
    page_sep = OxmlElement("w:fldChar"); page_sep.set(qn("w:fldCharType"), "separate")
    page_text = OxmlElement("w:t"); page_text.text = "1"
    page_end = OxmlElement("w:fldChar"); page_end.set(qn("w:fldCharType"), "end")
    footer._p.extend([page_begin, page_instr, page_sep, page_text, page_end])
    in_code = False
    for raw in content.splitlines():
        line=raw.strip()
        if not line: continue
        if line.startswith("```"):
            in_code = not in_code
            continue
        if in_code:
            code_para = document.add_paragraph()
            code_para.paragraph_format.left_indent = Inches(0.24)
            code_para.paragraph_format.right_indent = Inches(0.10)
            code_para.paragraph_format.space_before = Pt(0)
            code_para.paragraph_format.space_after = Pt(0)
            shading = OxmlElement("w:shd")
            shading.set(qn("w:fill"), "F2F4F7")
            code_para._p.get_or_add_pPr().append(shading)
            code_run = code_para.add_run(raw.rstrip())
            code_run.font.name = "Consolas"
            code_run.font.size = Pt(8.5)
            code_run.font.color.rgb = RGBColor(35, 43, 52)
            continue
        if line.startswith("#"):
            level=min(3,len(line)-len(line.lstrip("#"))); document.add_heading(line[level:].strip(),level)
        elif line.startswith("- "):
            document.add_paragraph(line[2:],style="List Bullet")
        elif re.match(r"^\d+[.]\s+",line):
            document.add_paragraph(re.sub(r"^\d+[.]\s+","",line),style="List Number")
        else:
            document.add_paragraph(line)
    if tables:
        for caption, rows in tables:
            document.add_heading(caption,2); table=document.add_table(rows=1, cols=len(rows[0])); table.alignment=WD_TABLE_ALIGNMENT.CENTER; table.style="Table Grid"
            for j,val in enumerate(rows[0]): table.rows[0].cells[j].text=val
            for row in rows[1:]:
                cells=table.add_row().cells
                for j,val in enumerate(row): cells[j].text=str(val); cells[j].vertical_alignment=WD_CELL_VERTICAL_ALIGNMENT.CENTER
    if figures:
        # Keep the evidence set visible while avoiding one mostly-empty page
        # per image. Two labelled figures per page gives the PDF a denser,
        # reviewable layout and keeps the main document within its page gate.
        for batch_start in range(0, len(figures), 2):
            document.add_page_break()
            batch = figures[batch_start:batch_start + 2]
            for offset, fig in enumerate(batch):
                document.add_picture(str(fig), width=Inches(3.05))
                document.paragraphs[-1].alignment = WD_ALIGN_PARAGRAPH.CENTER
                caption = document.add_paragraph(f"图 {batch_start + offset + 1}：{fig.stem.replace('_', ' ')}")
                caption.alignment = WD_ALIGN_PARAGRAPH.CENTER
                caption.runs[0].italic = True; caption.runs[0].font.size = Pt(9)
    document.core_properties.title=title; document.core_properties.subject="XH-202630 当前重建材料"; path.parent.mkdir(parents=True,exist_ok=True); document.save(path)


def build_documents(courses: list[dict[str, Any]], kb: dict[str, Any], profile_data: dict[str, Any], cases: list[dict[str, Any]], figures: list[Path], audit: dict[str, Any]) -> list[Path]:
    course_lines="\n".join(f"- `{c['raw']['course_id']}` / `{c['raw'].get('manifest_version')}`：{c['raw'].get('title')}；{len(c['raw'].get('knowledge_points',[]))} 个知识点、{len(c['raw'].get('files',[]))} 个来源文件。" for c in courses)
    profile_lines="\n".join(f"- `{p['profile_id']}`：{p['archetype']}；课程 `{p['course_id']}`；10 维画像、掌握度和当前数据库快照来源已记录。" for p in profile_data["profiles"])
    docs={}
    docs["00_材料总览与阅读顺序.md"]=("XH-202630 当前重建材料总览",f"""
# 材料定位

本目录是基于当前源码、当前两门 canonical course manifest、当前只读演示数据库和当前浏览器证据重新建设的正式材料草案。旧提交包只用于检查呈现完成度，不作为内容来源。

# 当前课程范围

{course_lines}

# 阅读顺序

1. 先读 `01_作品设计与实现方案`，了解系统和业务闭环。
2. 再读 `03_多智能体协同决策说明`、`04_个性化生成与学习反馈说明` 和 `05_领域知识库与可信生成说明`。
3. 使用 `07_系统部署说明` 和 `08_评委运行与演示手册`复现系统。
4. 使用 `06_测试方案与指标报告`、`test_data/` 和 `EVIDENCE_INDEX.json`复核结果。
5. 最后阅读 `09_数据合规与授权说明` 和 `12_系统限制、风险与未完成能力`。

# 当前样例

{profile_lines}

本轮不包含 PPT、演示视频、报名表和最终压缩包。三项比赛指标采用严格内部评测口径，尚未有外部领域标注人员复核。
""")
    docs["01_作品设计与实现方案.md"]=("EduMatrix 作品设计与实现方案",f"""
# 摘要

EduMatrix 面向机器学习和人工智能基础技能培训，将入学诊断、十维学习画像、知识点掌握度、两门课程知识库、Hybrid RAG、多智能体协同、结构化学习资源和反馈事件组织成一个可复现的学习闭环。

# 1. 场景与问题

同一知识目标对初学者、工程实践型学习者和理论研究型学习者具有不同的先修缺口、表达需求和任务负担。通用问答只能返回一段答案，无法说明答案来自哪一版本课程，也无法在答题失败后更新学习路径。EduMatrix 将“理解学习者”和“约束专业内容”拆成可审计对象，让资源生成同时受到画像、知识库、证据和规则约束。

# 2. 当前领域范围

{course_lines}

两门课程共同作为本次提交的机器学习/人工智能基础垂直知识库范围。当前材料不声称已经验证其他行业或开放领域泛化。

# 3. 总体架构

```text
Vue 3/Vite 前端
  → FastAPI/JWT/API 范围
  → 画像、诊断、路径、测评、资源和学习事件服务
  → RAG、知识图谱、Agent 协同和质量审核
  → SQLite/WAL、artifact/version、source_ref 和审计记录
```

系统的主要当前源码位置：`frontend/src/`、`app/main.py`、`app/auth.py`、`app/authorization.py`、`agent_swarm.py`、`app/m3_agents.py`、`app/m3_debate.py`、`rag_engine.py`、`document_parser.py`、`app/profile_onboarding.py`、`app/profile_adaptation.py`、`app/m5_resources.py`、`app/m5_learning.py` 和 `app/database.py`。

# 4. 业务闭环

```text
身份/课程上下文
  → 入学诊断
  → 掌握度和十维画像
  → 诊断与路径规划
  → 课程正文检索和证据绑定
  → 领域资源生成
  → claim 审核和决策编排
  → 讲义/实操/分阶题/导图/代码
  → 答题/代码/实验/复述/复习/追问
  → 学习事件
  → 画像、掌握度、路径和复习更新
```

# 5. 画像模型

初始登记字段：学习背景、学习目标、当前基础、主要困难、学习偏好。

持续十维画像：知识基础与掌握度、易错点与概念理解、理解与迁移能力、认知加工方式、学习策略、元认知、动机与目标、情绪与抗挫力、互动偏好、学习情境。

每个维度必须有分数、置信度、证据、状态、资源影响和教学影响。当前数据中若只有快照推导而没有原始对话，标记为“当前数据库派生视图”，不包装为真人画像。

# 6. 资源与决策

资源生成至少覆盖讲义、实训/训练任务、分阶测验、思维导图、代码、视频脚本和交互实验。资源通过 artifact 与 artifact_version 管理，来源通过 source_ref 绑定，反馈通过 learning_event 追加。

决策候选包括收集更多证据、降低解释难度、补先修、维持巩固和增加进阶挑战；高风险决策保留 proposed 状态并需要确认。

# 7. 可靠性、安全和限制

- 权限先于检索和生成，服务端执行 owner、角色和课程范围校验；
- 课程版本、来源哈希和资源版本防止静默混用；
- 证据不足时拒答、降级或请求补充材料；
- deterministic 仅是可复现模式，不代表真实外部模型效果；
- trusted_local 是本机受限子进程，不等于 Docker 隔离；
- 本材料的三组画像和测试集不是外部用户实验。
""" )
    docs["02_作品介绍.md"]=("EduMatrix 作品介绍",f"""
# 一句话介绍

EduMatrix 让系统先理解学习者，再从两门课程的可信正文中检索证据，由多个专业 Agent 协同生成可执行、可复习、可追踪的个性化学习资源。

# 典型使用

学习者完成入学诊断后，系统读取其知识点掌握度和十维画像，判断应该补先修、降低解释负荷、增加代码练习还是进入迁移挑战。学习者完成测验、代码、实验或复述后，系统把结果写成学习事件，重新计算下一步任务。

# 三类差异化学习者

{profile_lines}

# 评委应看到的闭环

课程选择 → 入学诊断 → 画像确认 → Agent 分析/生成/审核/决策 → 来源证据 → 三类以上资源 → 反馈 → 掌握度或路径更新。

# 真实性边界

当前展示数据包含当前数据库演示快照、课程正文和脱敏重放视图。没有外部领域标注人员时，不把内部评测写成专家结论，也不把 deterministic 写成真实大模型效果。
""")
    docs["03_多智能体协同决策说明.md"]=("EduMatrix 多智能体协同决策说明",f"""
# 1. 角色和责任

| 角色 | 输入 | 输出 | 关键边界 |
|---|---|---|---|
| 诊断 Agent | 画像快照、诊断结果、目标知识点 | skill gap、证据、不确定性 | 不直接声明胜任 |
| 领域生成 Agent | 画像、课程版本、source_ref | lesson、lab_guide、tiered_quiz | 不自行发布、不改指标 |
| 证据审核 Agent | artifact version、source_ref、质量规则 | claim_check、review、debate | 无证据不批准 |
| 决策编排 Agent | 审核、学习事件、匹配报告 | decision_record、matching_report | 不把点击当掌握 |

# 2. 生命周期

```text
queued → running → completed
             ├→ failed → retry
             └→ interrupted → recovery
```

每个阶段保留任务 ID、运行 ID、trace ID、owner、课程、画像快照、输入引用和输出版本。前端只展示脱敏摘要，私有提示词和内部推理不进入提交材料。

# 3. 交叉验证

候选资源先按 claim 拆分，再检查来源支持、矛盾、不确定和课程版本。发生局部失败时只返工失败 claim，保留合格资源版本和失败原因。完整 Prover/Challenger/Judge 辩论只有在实际执行并有运行记录时才可宣称；普通聊天只展示协作摘要。

# 4. 决策候选

收集更多证据、降低解释、补先修、维持巩固和进阶挑战五类候选均需绑定证据 ID、预计负担、风险、资源成本和确认要求。
""")
    docs["04_个性化生成与学习反馈说明.md"]=("EduMatrix 个性化生成与学习反馈说明",f"""
# 1. 画像输入

每组测试样例包含入学诊断、知识点掌握度、完整十维画像、证据来源、置信度、薄弱点、先修缺口、目标、偏好和学习情境。

# 2. 十维影响矩阵

| 维度 | 资源影响 | 教学影响 |
|---|---|---|
| 知识掌握度 | 难度带、重复内容过滤 | 先修和复测优先级 |
| 易错点 | 反例、概念辨析 | 错因干预 |
| 迁移能力 | 变式和开放任务 | 迁移节点顺序 |
| 认知加工 | 单次内容量、脚手架 | 短回合/深度回合 |
| 学习策略 | 练习与复习组合 | 间隔复习 |
| 元认知 | 自评和复盘提示 | 信心校准 |
| 动机目标 | 案例上下文 | 项目/考试/岗位路径 |
| 情绪抗挫 | 首题难度、提示强度 | 失败后降阶 |
| 互动偏好 | 图示/代码/推导排序 | 互动媒介 |
| 学习情境 | 时长、设备和资源形态 | 任务节奏和负担 |

# 3. 反馈事件

可信事件包括测验作答、代码测试、交互实验、费曼复述、复习完成和延迟复测。事件进入 `record_learning_event`，再由画像、路径、复习和活动聚合消费。普通浏览和单次点击不直接升级掌握度。

# 4. 三组样例

{profile_lines}

样例中的资源和画像数据会明确区分“当前数据库快照”“当前引擎派生”与“测试场景覆盖”，不把推导视为真实用户访谈。
""")
    docs["05_领域知识库与可信生成说明.md"]=("EduMatrix 领域知识库与可信生成说明",f"""
# 1. 知识库切片

{course_lines}

知识库重建产物位于 `test_data/knowledge_base/`，包含 `chapters.jsonl`、`knowledge_points.jsonl`、`chunks.jsonl`、`source_refs.jsonl`、`prerequisite_edges.jsonl` 和许可证记录。每个正文 chunk 保留源文件、字符范围和内容哈希。

# 2. 检索管线

```text
课程范围 → 文档解析 → 章节/知识点映射 → 分块
→ 关键词/语义/图谱混合召回 → 版本/owner 过滤
→ source_ref → 生成 → claim 审核 → artifact version
```

# 3. 可信生成

事实 claim 必须标记 `supported`、`contradicted`、`unsupported` 或 `unknown`。没有来源的专业断言按 unsupported；来源冲突按 contradicted；无法判断的 unknown 在严格幻觉率中计入错误。

# 4. 许可证和再分发

课程 manifest 与每个源文件记录上游 revision、文件哈希、license SPDX、许可证文件和来源角色。无法确认授权的原始资料不进入提交包。

# 5. 当前限制

来源数量不等于事实准确率，检索分数不等于学习效果，两门课程不等于全行业知识库。测试数据中的正文切片可以复核来源，但三项比赛指标仍需要内部严格运行和责任人复核。
""")
    docs["06_测试方案与指标报告.md"]=("EduMatrix 测试方案与指标报告",f"""
# 1. 测试集

测试集包含 60 条案例，三组画像、两门课程和 18 条 challenge 案例。案例覆盖入学诊断、掌握度、十维画像影响、课程范围、RAG、来源、资源、审核、决策、反馈、路径、复习、权限、恢复、sandbox 和版本冲突。

# 2. 当前执行状态

前 12 条案例绑定当前数据库演示证据；其余案例是冻结的待执行挑战场景，不能把预期字段写成运行结果。测试数据中的 `actual_execution_status` 明确区分 `current_db_evidence` 与 `designed_not_run`。

# 3. 幻觉率

```text
（contradicted + unsupported + unknown）÷ 全部事实性 claim
```

没有来源 ID 的专业结论按 unsupported，unknown 计入错误，关键知识点 contradiction 使案例失败。当前没有外部领域标注人员，故只能报告内部严格评测，不报告专家验证。

# 4. 画像—资源适配准确率

对难度、先修、脚手架、任务复杂度、表达方式和反馈响应分别以 0/1/2 评分；总分至少 10/12 且难度、先修不能为 0 才通过。必须报告总体、三组画像、最差组和失败维度。

# 5. 核心知识点覆盖率

关键知识点权重 2，普通知识点权重 1：

```text
正确覆盖知识点权重总和 ÷ 必需知识点权重总和
```

# 6. 当前指标状态

三项指标尚未完成外部领域复核，因此当前材料只发布测试集、分母、公式、来源和失败处理规则。不能把内部 fixture 或历史数字写成正式达标结果。

# 7. 当前自动验证

- 关键课程、画像、Agent、RAG、资源和竞争演示回归：`65 passed, 6 warnings`；
- 11 个旧式 M5 内存夹具失败，原因是夹具没有当前课程可用材料；
- 前端生产构建：通过，5453 个模块；
- 无 Docker 核心 E2E：通过；
- 两课程 Chromium E2E：24 个页面通过，HTTP 5xx、页面和控制台错误为 0。
""")
    docs["07_系统部署说明.md"]=("EduMatrix 系统部署说明",f"""
# 1. 环境要求

Windows 10/11 或 Linux x86_64；Python 3.11；Node.js 20 LTS；npm。Chromium 仅在浏览器 E2E/PDF 导出时需要，Docker 仅在容器代码执行时需要。

# 2. 安装

```powershell
py -3.11 -m venv .venv
.venv\\Scripts\\python.exe -m pip install --upgrade pip
.venv\\Scripts\\python.exe -m pip install -r requirements.txt
cd frontend
npm ci
cd ..
```

复制 `.env.example` 为 `.env`，生成至少 32 字符的随机 `EDUMATRIX_AUTH_SECRET_KEY`。默认使用 deterministic、hash embedding 和 disabled sandbox。

# 3. 启动

```powershell
.venv\\Scripts\\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
cd frontend
npm run dev -- --host 127.0.0.1
```

访问 `http://127.0.0.1:5173`，健康检查 `http://127.0.0.1:8000/api/health`。

# 4. 模式边界

- deterministic：本地可复现流程，不等于外部模型效果；
- 外部模型：只从评委环境注入 endpoint、model 和 key；
- trusted_local：本机受限子进程研究模式，不具备 Docker 隔离；
- docker：需要 Docker daemon，才提供容器级代码隔离。

# 5. 验收顺序

健康检查 → 登录 → 课程选择 → 入学诊断 → 十维画像/掌握度 → 对话或资源生成 → 查看来源 → 完成测验/代码/实验 → 查看反馈后的任务。

# 6. 故障处理

前端无法请求后端先检查 8000 和 `/api/health`；代码执行返回 503 在 disabled 模式是预期边界；E2E/PDF 失败时安装 Playwright Chromium；外部模型不可用时切回 deterministic。
""")
    docs["08_评委运行与演示手册.md"]=("EduMatrix 评委运行与演示手册",f"""
# 1. 推荐路径

```text
安装依赖 → 启动后端/前端 → 健康检查
→ 登录/注册 → 选择两门课程之一
→ 完成入学诊断 → 查看掌握度和十维画像
→ 进入学习空间提问 → 观察 Agent 协同摘要和来源
→ 打开讲义、实训、题目或导图
→ 提交反馈 → 查看下一步路径/复习任务
```

# 2. 观察点

- 画像是否包含诊断、掌握度和十维状态；
- 资源难度、脚手架和表达是否随画像变化；
- Agent 阶段是否有分析、生成、审核和决策；
- 资源是否可回链到课程正文；
- 失败、不确定和重试状态是否可理解；
- 代码执行模式是否准确显示。

# 3. 当前证据

两门课程的 24 个页面 Chromium 验收截图和报告位于 `EVIDENCE_INDEX.json` 引用的当前证据目录。截图证明指定时点页面状态，不替代指标或生产安全证明。
""")
    docs["09_数据合规与授权说明.md"]=("EduMatrix 数据合规与授权说明",f"""
# 1. 数据分类

测试画像、诊断、掌握度、Agent trace 和反馈样例均为脱敏重放或合成场景。提交材料不包含真实姓名、手机号、邮箱、密码、学习记录、API Key、JWT 密钥或私有推理内容。

# 2. 课程来源

两门课程的 source catalog 保存上游 revision、文件哈希、许可证文件和再分发边界。材料只纳入来源和授权边界清晰的课程内容；不确定授权的文件不进入最终包。

# 3. 权限与日志

用户、课程、资源、来源和学习事件通过服务端 Token、owner 和课程范围校验。公开协作摘要脱敏，日志不输出凭据和私有提示词。

# 4. 外部服务

真实 LLM、联网搜索、Docker、PDF 导出和其他可选服务需要目标环境单独配置和复核。当前 deterministic 和内部评测不能包装成真实用户实验。
""")
    docs["10_源码结构与复现说明.md"]=("EduMatrix 源码结构与复现说明",f"""
# 1. 源码结构

- `frontend/src/`：路由、页面、组件、API 和状态；
- `app/`：FastAPI 路由、认证、课程、画像、Agent、资源、学习事件和治理；
- 根目录 Python：Agent Swarm、RAG、模型客户端、学习算法和代码边界；
- `data/curated/`：两门当前课程 manifest 和正文；
- `tests/`、`scripts/`：自动化测试、E2E、审计和运行入口。

# 2. 关键入口

后端 `app.main:app`；前端 `frontend/package.json`；健康检查 `/api/health`；Agent `agent_swarm.py`/`app/m3_agents.py`；RAG `rag_engine.py`/`knowledge_api.py`；画像 `app/profile_onboarding.py`/`app/profile_summary.py`；资源 `app/m5_resources.py`；反馈 `app/m5_learning.py`/`app/learning_aggregation.py`。

# 3. 当前复现版本

- Git commit：`{audit['git_commit']}`；
- Python：`{audit['python']}`；
- Node.js：`{audit['node']}`；
- 课程、数据和证据清单见 `MATERIAL_MANIFEST.json`。

# 4. 复现原则

使用隔离数据库和临时目录执行测试；先确认课程和来源，再执行 Agent/资源流程；保存命令、时间、模式和原始结果。未重新执行的内容标为未验证。
""")
    docs["11_当前实现与赛题要求逐项对应表.md"]=("当前实现与赛题要求逐项对应表",f"""
# 对应关系

| 赛题要求 | 当前实现/证据 | 当前状态 |
|---|---|---|
| 垂直技能培训 | 两门机器学习/人工智能基础课程 manifest 和正文 | 当前课程范围已验证 |
| 至少 3 个 Agent | `agent_swarm.py`、`app/m3_agents.py`、M3 角色契约 | 源码和部分流程已验证 |
| 分析—生成—校验—决策 | M3 任务、Agent run、审核和决策对象 | 运行证据按当前 DB 记录披露 |
| 画像输入 | 入学诊断、掌握度、十维画像和 profile snapshot | 当前数据已重建 |
| 三类以上资源 | artifact/version 中的 handout、training_task、quiz、mind_map、code 等 | 当前 DB 有演示对象 |
| 动态反馈 | learning_events、profile aggregation、path/review 消费 | 当前接口和事件证据 |
| 知识库 | 两门课程正文 chunk、source_ref、版本、许可证 | 当前切片已生成 |
| 可视化和评委复现 | 当前 Chromium 页面证据、部署和运行手册 | 以当前环境为边界 |
| 指标 | 冻结测试集、公式、失败案例和内部复核结构 | 未完成外部复核 |

表中“当前 DB 有演示对象”不等于所有对象都在同一条真实 Agent 运行链中产生；具体证据以 `EVIDENCE_INDEX.json` 为准。
""")
    docs["12_系统限制、风险与未完成能力.md"]=("系统限制、风险与未完成能力",f"""
# 已知限制

1. 两门课程之外的跨领域泛化尚未验证。
2. 当前没有外部领域标注人员，三项指标不能写成独立专家验证结果。
3. 部分当前数据库快照是反馈聚合或演示重放视图，不能等同于真人长期实验。
4. 当前 M5 内存夹具中有 11 项因缺少课程材料失败，需要修复夹具或明确测试前置，不应隐藏。
5. deterministic、trusted_local 和 Docker 的能力边界不同。
6. 前端构建存在大体积 chunk 警告。
7. 当前材料不包含演示视频、报名表和最终压缩包。

# 风险处理

- 知识风险：来源先于生成，claim 不确定时拒答或降级；
- 画像风险：置信度和证据随快照保存，不以单次自述声明掌握；
- 权限风险：owner/课程范围在服务端执行；
- 运行风险：失败、重试、恢复和可选外部服务单独记录；
- 数据风险：提交包排除凭据、真实用户和未授权资料。
""")
    docs["13_API与数据字典.md"]=("EduMatrix API 与数据字典",f"""
# 文档用途

本文件面向需要复现系统的评委和开发人员，说明当前 API 如何连接课程、诊断、画像、资源、反馈和权限。它不是把所有路由机械列一遍，而是先讲一条请求怎样流过系统，再给出核心接口、输入输出和失败边界。具体部署应以当前服务的 OpenAPI 和实际响应为准。

# 1. 通用请求约定

后端默认运行在 `http://127.0.0.1:8000`，前端开发服务运行在 `http://127.0.0.1:5173`。除健康检查、登录和注册外，业务请求携带 `Authorization: Bearer <JWT>`。服务端从 Token 确认当前主体，查询参数中的 `student_id` 只作为兼容字段，不能覆盖当前身份。

响应状态按业务分为：200 表示读取或处理成功，201 表示创建成功，202 表示异步任务已接受，400 表示输入不合法，401 表示身份无效，403 表示角色或 owner 范围不足，404 表示对象不存在，409 表示幂等或资源冲突，503 表示外部模型、Docker 或浏览器池不可用。

# 2. 课程、章节和来源接口

课程目录接口返回 course ID、版本、名称、主题和可选状态；outline 接口返回章节和知识点顺序；source-ref 接口返回章节、文件、字符范围、引用片段和哈希。课程查询先做 canonical course 过滤，未发布或没有可用正文的课程不能进入正常学习入口。

评委可以先读取课程和 outline，再拿一个 source_ref 复核原文。这个顺序可以确认页面显示的课程版本、知识点和 RAG 来源属于同一个版本，而不是“课程列表来自一处、答案来自另一处”。

# 3. 诊断和画像接口

诊断接口负责创建 blueprint、启动 session、提交 response 和生成 report。题目版本记录理论、应用或工程判断维度、知识点、难度和评分规则；报告把作答结果转换为能力状态、不确定性和薄弱点。画像接口读取当前 profile snapshot、十维状态、掌握度、分析、学习路径和目标建议。

画像更新必须保留快照和证据来源。结构化更新不会直接覆盖历史状态，回滚接口也需要当前用户范围和目标版本检查。评委在复现时应观察诊断提交前后的 profile snapshot 是否变化，再观察资源请求是否带入新的适配控制。

# 4. 对话、资源和 Agent 接口

`POST /api/stream/chat` 使用 SSE 返回阶段事件、内容增量、资源和完成状态。服务端先创建或复用 generation task，再让四类 Agent 依次产生运行记录。`POST /api/stream/regenerate` 只重做指定角色或资源类型，`POST /api/stream/explain` 用于对目标文本发起追问。

M1 对象接口提供 generation task、artifact 和 artifact version 的读取。资源读取时应同时检查 artifact_type、status、version_id 和 source_ref_ids；只有带课程来源和通过审核的版本才适合作为学习材料。任务失败时读取 task 状态和错误码，而不是从前端是否显示文本来判断成功。

# 5. 测验、复习和学习事件接口

测验接口覆盖生成、评估、自适应调整、历史、错题、相似题和复习打卡；闪卡接口覆盖生成、复习、到期查询和历史。答题和复习结果写入 learning event，事件带 evidence_status、evidence_strength、mastery_eligible 和 completion_effect。浏览、点击和单次打开页面不会自动升级掌握度。

# 6. RAG、上传和代码接口

知识库接口覆盖课程列表、来源详情、发现搜索、个人文档上传、网页来源和删除。个人文档在摄入时绑定 owner，检索时按 owner、课程和可见性过滤；删除时同步清理索引。课程正文属于 canonical 证据，不能因为个人文档相似度更高就被悄悄替换。

代码接口的 status 返回 mode、execution_enabled、isolation、security_level 和 max_output_bytes；run 接收语言、代码和资源上下文；history 按 owner 返回执行记录。disabled 模式明确拒绝执行，trusted_local 是本机受限研究路径，Docker 才提供容器隔离。

# 7. 核心数据对象

`DBCourse` 定义课程范围和版本，`DBChapter` 定义章节顺序，`DBKnowledgePoint` 定义知识点与先修，`DBSourceDocument` 保存正文文件和处理状态，`DBSourceRef` 保存可回链片段；`DBProfileSnapshot` 保存学习者状态，`DBGenerationTask` 和 `DBAgentRun` 保存协同任务，`DBArtifactVersion` 保存资源版本，`DBLearningEvent` 保存反馈事实。

这些对象通过 ID 和版本关联，而不是通过标题字符串猜测关系。课程版本、画像快照和资源版本发生变化时，旧对象仍保留原引用，便于解释学习者当时收到的内容和路径。

# 8. 权限、错误和审计

所有画像、资源、学习事件和个人文档读取都经过当前用户、owner、角色和课程范围校验。跨 owner 读取返回 403 或 404，具体取决于接口是否需要隐藏对象存在性；幂等键绑定不同上下文时返回 409；外部服务不可用返回 503 并保留任务失败状态。

接口审计重点记录 trace_id、task_id、run_id、artifact_version_id、source_ref_id 和 learning_event_id。日志只保留脱敏摘要、状态和哈希，不记录 Token、密码、完整私有文档或私有提示词。

# 9. 复现顺序

先调用 `/api/health`，再登录并读取课程；之后创建诊断会话、提交至少一题、读取画像，再请求一个资源并查看 source_ref；最后提交测验或复习事件，重新读取路径和复习队列。每一步保留实际 HTTP 状态和对象 ID，才能判断是接口问题、数据问题还是外部依赖问题。
""")
    docs["14_需求实现测试追踪矩阵.md"]=("EduMatrix 需求—实现—测试追踪矩阵",f"""
# 1. 使用方式

本矩阵把赛题要求拆成可检查的功能、当前实现、验证方法和声明边界。状态“已验证”只覆盖表中明确的当前运行范围；“结构已存在”表示源码可定位但没有同等强度的运行证据；“未正式测量”表示指标尚未完成严格评分。

# 2. 评委关注的主链路

学习者选择课程后完成入学诊断，诊断结果写入画像和掌握度；画像进入适配器生成难度、脚手架和表达控制；RAG 按课程和版本召回正文证据；四类 Agent 生成、审核并提出决策；资源以 artifact version 发布；答题、代码、复述或复习形成 learning event；路径和复习队列再消费这些事件。

# 3. 当前对应关系

| 能力 | 当前实现 | 当前验证 | 边界 |
|---|---|---|---|
| 垂直知识库 | 两门 canonical course、章节、知识点、正文切片 | manifest、source_ref、浏览器课程入口 | 只代表机器学习/人工智能基础范围 |
| 个性化画像 | 入学诊断、掌握度、十维画像、profile adaptation | 三组脱敏画像和当前快照 | 不是外部用户研究 |
| Agent 协同 | diagnosis、domain_generation、evidence_review、decision_orchestration | M3 契约和当前流程对象 | 完整外部模型效果需单独复核 |
| 个性化资源 | lesson、lab、quiz、mind map、code 等 artifact | 当前数据库资源对象和资源页面 | 部分资源在画像间复用 |
| RAG 可信生成 | 课程范围、混合召回、source_ref、claim 审核 | 当前正文切片和来源索引 | 指标尚未正式测量 |
| 反馈闭环 | learning event、掌握度、路径、复习 | 当前事件和页面入口 | 48 条挑战案例尚未执行 |
| 权限和安全 | JWT、owner、课程范围、sandbox 状态 | 选定 API 和浏览器边界 | 生产并发和完整安全审计未完成 |
| 评委复现 | FastAPI、Vite、SQLite、部署手册 | 当前环境构建和浏览器 E2E | 外部模型、Docker 是可选依赖 |

# 4. 测试等级

静态检查确认路由、schema、课程和配置存在；单元测试确认函数边界和错误分支；集成测试确认对象之间的关联；API 测试确认身份、状态码、课程范围和幂等；浏览器测试确认页面和 SSE 时间线；数据检查确认案例、画像、知识点、来源和资源能相互回链。测试通过不自动意味着三项比赛指标通过。

# 5. 指标对应和发布条件

专业知识谬误率以 claim 为分母，把 contradicted、unsupported 和 unknown 都计入错误；适配准确率对难度、先修、脚手架、任务复杂度、表达方式和反馈响应六项以 0/1/2 评分；核心知识点覆盖率对关键知识点权重加倍。发布数值前必须附数据集版本、运行模式、失败案例和项目组单人复核记录。

# 6. 当前未完成项

当前没有外部领域标注人员；48 条 challenge 仍是冻结未执行场景；三组画像中部分数据库资源 ID 复用；项目实践型画像有互动偏好和学习情境证据缺口；11 个旧式 M5 内存夹具因没有当前课程前置而失败。上述内容都保留在当前限制和测试报告中，不改写成通过。
""")
    docs["15_公开依据与引用清单.md"]=("EduMatrix 公开依据与引用清单",f"""
# 1. 引用原则

本清单说明当前材料引用的课程、源码和公开技术依据。课程正文引用只来自当前两门 canonical course manifest 及其在仓库中的受控文件；旧提交包不作为事实来源。任何无法确认授权或版本的材料都不进入当前提交数据。

# 2. 当前课程来源

《机器学习基础与实践》对应 `course-machine-learning-foundations-v1`，版本 `{next(c['raw'].get('manifest_version') for c in courses if c['raw']['course_id'].startswith('course-machine'))}`，包含 13 个知识点和 12 个来源文件。《人工智能与深度学习：从机器学习基础到大模型智能体》对应 `course-ai-deep-learning-agents-v1`，版本 `{next(c['raw'].get('manifest_version') for c in courses if c['raw']['course_id'].startswith('course-ai'))}`，包含 20 个知识点和 24 个来源文件。

每个来源文件在 `test_data/knowledge_base/license_records.json` 中保留路径、来源角色、上游 revision、文件哈希、许可证文件和 SPDX（若 manifest 提供）。正文 chunk 和 source_ref 记录可引用字符范围，便于评委从资源回到原文。

# 3. 源码依据

系统入口和路由依据 `app/main.py`、`app/auth.py`、`app/authorization.py`；课程和对象依据 `app/m1_api.py`、`app/m1_repository.py`、`app/database.py`；Agent 协同依据 `app/m3_agents.py`、`app/m3_debate.py`、`app/m3_matching.py`、`app/m3_decisions.py`；RAG 依据 `rag_engine.py`、`knowledge_api.py` 和 `document_parser.py`；画像和反馈依据 `app/profile_onboarding.py`、`app/profile_adaptation.py`、`app/m5_learning.py` 和 `app/learning_aggregation.py`。

代码地图只帮助定位模块，不能单独证明运行成功。运行结论必须同时引用当前测试命令、浏览器报告、数据库对象或导出的 JSONL。

# 4. 技术方法依据

知识点先修关系用于路径规划和适配；掌握度更新使用当前学习事件和画像聚合逻辑；资源难度使用 M3 matching interval 模型；证据审核使用 claim、Prover、Challenger 和 Judge 结构；代码安全区分 disabled、trusted_local 和 Docker。上述方法是系统当前实现和测试边界的说明，不等于所有模式都已在生产环境验证。

# 5. 证据等级

A 级是当前命令输出、HTTP 响应、浏览器截图和数据库记录；B 级是当前源码类、函数、schema 和路由；C 级是设计说明和材料解释；D 级是建议、目标或未执行案例。比赛指标只能由带分母的复核结果支撑，不能用 B/C/D 级内容替代。

# 6. 引用和再分发边界

提交材料只带入必要的课程切片、来源信息和经审计的图像。第三方课程、代码、图片和数据的再分发范围以其许可证和当前 manifest 为准；授权不明的原始文件不放入最终提交包。视频、报名表和最终压缩包接入后仍需重新做来源和隐私扫描。
""")

    # Companion documents are deliberately written as review materials, not
    # one-page abstracts. Their detail is generated from the same current
    # course/profile/case snapshot used by the main design document.
    companion = {
        "00_材料总览与阅读顺序.md": f"""
# 1. 评审导航和证据边界

本套材料按“先理解系统、再复现流程、最后核对证据”的顺序组织。每份文档都标明当前版本、数据来源和未验证边界。Markdown 是可检索的事实层，DOCX 是排版层，PDF 是交付前的渲染验收层；三者应在同一生成时间和 Git commit 下对应。

# 2. 材料与评委问题映射

评委通常需要回答四个问题：系统是否真正实现了个性化闭环，专业内容是否有来源，多个 Agent 是否存在可审计协作，以及指标是否按严格口径测量。01 负责系统设计，03–05 负责协同、画像和 RAG，06 负责测试与指标，07–08 负责运行复现，09–12 负责治理、源码、赛题对应和限制。

# 3. 当前版本快照

生成快照包含两门 canonical 课程、{len(kb['chapters'])} 个章节、{len(kb['knowledge_points'])} 个知识点、{len(kb['chunks'])} 个正文 chunk、{len(kb['refs'])} 个 source_ref、{len(profile_data['profiles'])} 组画像、{len(cases)} 条测试案例和 {sum(x['difficulty']=='challenge' for x in cases)} 条 challenge。它不包含 PPT、视频、报名表或最终压缩包。

# 4. 推荐评审路线

先启动本地服务并打开课程目录，再按“课程选择—诊断—画像—资源—反馈—路径”的顺序操作；每一步记录页面时间和对象 ID。阅读材料时将 UI 截图视为页面状态证据，将数据库导出视为对象证据，将测试命令输出视为运行证据，避免用一种证据替代另一种证据。

# 5. 文件命名和版本规则

文件名使用赛题编号和当前作品语义，不沿用历史 A3 或旧包名。课程版本来自 manifest，资源版本来自 artifact_version，正文引用带 source_ref 和内容哈希。任何后续运行若改变课程正文、配置或数据库快照，都应重新生成材料并更新 manifest。

# 6. 阅读检查表

- 先确认 `AUDIT_FACTS.json` 中的 commit、课程数和运行模式；
- 再确认 `EVIDENCE_INDEX.json` 的截图和命令路径仍存在；
- 对照 `CLAIM_BOUNDARIES.md` 区分源码存在、当前运行和正式指标；
- 在 `test_data/` 中按案例 ID 追溯画像、资源、事件和 source_ref；
- 发现未执行或 unknown 时，保留其失败状态，不将其改写为通过。

# 7. 提交包组装前置条件

PPT、剪辑视频、报名表扫描件和最终压缩包尚未接入。组包前必须再次核对报名表中的学校、申报人、作品名称和联系电话，并做敏感信息、旧题名、断链、许可证和文件缺失扫描。
""",
        "02_作品介绍.md": f"""
# 1. 作品定位

EduMatrix 是一个面向机器学习与人工智能基础学习的个性化生成和多智能体协同决策系统。它把学习者的起点、目标、掌握度、认知与情绪约束转化为资源控制参数，再将每个专业事实绑定到当前课程正文证据，形成可解释的学习任务。

# 2. 用户旅程

学习者首次进入系统时先选择课程并完成理论、应用、工程判断三类入学诊断。系统不把单题正确直接当作掌握，而是结合知识点、置信度和先修关系形成初始状态。随后十维画像进入适配器：初学者得到短段落、图示和分步练习；项目型学习者得到真实参数、故障排查和迁移任务；理论型学习者得到推导、边界和反例。

# 3. 两门课程的展示重点

`course-machine-learning-foundations-v1`（{len(next(c['raw'] for c in courses if c['raw']['course_id'].startswith('course-machine-learning-foundations'))['knowledge_points'])} 个知识点）覆盖监督学习、特征、评估和工程基础；`course-ai-deep-learning-agents-v1`（{len(next(c['raw'] for c in courses if c['raw']['course_id'].startswith('course-ai-deep-learning-agents'))['knowledge_points'])} 个知识点）覆盖深度学习、大模型、RAG、Agent 和协同决策。两门课共同构成当前垂直范围，不能外推为全行业知识库。

# 4. 三组案例的可见差异

视觉型初学者的案例从“先建立概念地图”开始，资源中明确术语、图示和即时检查；项目实践型学习者以一个可运行的小任务为主线，资源给出输入输出、调参和失败诊断；理论研究型学习者强调假设、推导、复杂度和边界条件。三组案例都经过同一 source_ref 约束，差异体现在学习控制，而不是事实内容随意改写。

# 5. 作品亮点

第一，课程版本、正文分块和引用可回链；第二，Agent 角色有输入、输出和禁止动作；第三，资源是带版本和完成规则的 artifact，而不是一段聊天文本；第四，反馈事件会影响掌握度、路径和复习；第五，系统把不确定性、失败和外部依赖写进审计材料。

# 6. 评委可复现的最小闭环

在本地 deterministic 模式下，评委可以选择任一当前课程，查看诊断和画像，进入学习空间检索课程内容，观察资源类型和来源，再提交一个测验或复习事件。若启用外部模型或 Docker，需按 07 的环境变量和服务边界单独复核。
""",
        "07_系统部署说明.md": f"""
# 1. 部署拓扑和组件职责

浏览器访问 Vite 前端，前端通过 API 调用 FastAPI 服务；服务层执行认证、课程范围、画像、资源、Agent 任务和学习事件逻辑；SQLite 保存对象、版本和审计记录；课程正文以只读 curated 文件提供 RAG 输入。可选外部 LLM、联网搜索和 Docker sandbox 不属于默认核心路径。

# 2. 版本和资源要求

推荐 Python 3.11、Node.js 20 LTS、npm、Chromium。核心 deterministic 模式不要求外部 API key；外部模型模式必须在评委环境注入 endpoint、model 和 secret。部署机器至少预留课程正文、SQLite 和前端构建所需的磁盘空间，测试时使用隔离数据库或临时目录。

# 3. 安装、启动和健康检查

创建虚拟环境并安装 `requirements.txt` 后，在 `frontend` 执行 `npm ci`。后端以 `uvicorn app.main:app --host 127.0.0.1 --port 8000` 启动，前端以 `npm run dev -- --host 127.0.0.1` 启动。打开 `/api/health` 检查数据库、模型、检索和 sandbox 状态，再进入页面完成登录和课程加载。

# 4. 配置矩阵

配置至少包括认证密钥、模型模式、数据库路径、课程目录和 sandbox 模式。开发环境使用随机生成的本地密钥；提交材料中只保留 `.env.example` 和字段说明。`disabled` sandbox 返回边界状态，`trusted_local` 表示本机受限子进程，只有 Docker 模式才提供容器隔离。

# 5. 评委复现路径

依次执行健康检查、登录、课程选择、入学诊断、画像查看、资源生成、来源查看、测验提交和路径刷新。每一步都有对应 API 或页面证据，出现失败时保存 HTTP 状态、trace_id、任务状态和日志摘要，不以刷新页面代替成功。

# 6. 故障排查矩阵

前端无法访问后端时检查 8000 端口和 CORS；课程不可用时检查 manifest、正文目录和版本；资源生成超时查看 Agent run 状态并按幂等键重试；代码执行 503 在 disabled 模式属于预期限制；PDF 转换需要 LibreOffice 或等价工具。

# 7. 部署安全边界

生产部署还需补充反向代理、TLS、密钥管理、备份、并发和审计策略。本材料只验证本机指定环境的核心流程，不把开发服务器、deterministic 或 trusted_local 描述为生产级安全方案。

# 8. 回滚和清理

课程和资源以版本对象保存，回滚时选择已知版本并保留当前审计记录。测试完成后删除临时数据库、缓存、WAL/SHM、虚拟环境和 `node_modules`，最终包只保留复现所需源码、文档、测试数据和经审计证据。
""",
        "08_评委运行与演示手册.md": f"""
# 1. 演示目标

演示应让评委在十分钟内看到完整闭环：学习者输入如何进入画像，画像如何改变资源，Agent 如何协作审核，资源如何回链课程正文，反馈如何改变下一步决策。演示视频尚在剪辑，本手册用于现场或录制前的可复现操作。

# 2. 详细操作脚本

第一段展示课程目录和版本；第二段选择一门课程完成三类诊断；第三段打开画像摘要和知识点掌握度；第四段提交一个带来源的问题，查看检索证据与 Agent 时间线；第五段打开讲义、实训、分阶题和导图；第六段提交答题反馈，刷新路径和复习队列。第二门课程重复关键步骤，展示跨课程范围过滤。

# 3. 三组画像切换

演示数据使用脱敏 profile ID。初学者案例强调先修补救和高脚手架；项目型案例强调训练任务、代码和迁移；理论型案例强调推导、反例和深度阅读。切换画像时应展示难度、资源类型、表达方式和反馈策略的变化，而不是只展示名称变化。

# 4. 证据观察点

评委可以记录课程 ID、course_version、chunk_id、source_ref_id、artifact_version、trace_id 和 learning_event_id。截图只证明当时页面状态；对象导出用于核对字段；命令输出用于核对运行结果。三者组合才能支持完整复核。

# 5. 失败和恢复演示

可以选择一个课程外问题或无来源断言，观察系统拒答、降级或请求补充材料；也可以让任务进入失败状态后按幂等键重试。不要把失败隐藏，失败原因和恢复动作本身是协同决策可审计性的一部分。

# 6. 现场注意事项

提前确认端口未被占用、浏览器无旧登录态、课程正文可读、截图目录可写。外部模型和 Docker 属可选项，现场若不可用应切换 deterministic 并如实说明模式边界。
""",
        "09_数据合规与授权说明.md": f"""
# 1. 数据分级和最小化

当前提交材料只包含脱敏重放、当前数据库派生视图、合成 challenge 和课程正文切片。姓名、手机号、邮箱、密码、JWT 密钥、API key、真实学习记录和私有推理内容均排除。profile ID 和 owner ID 在材料中使用演示占位符。

# 2. 数据生命周期

诊断、掌握度、画像、资源和学习事件先在隔离环境生成，再导出为可审计 JSONL；导出后执行敏感字段扫描、旧题名扫描和许可证扫描。测试结束删除临时数据库、WAL/SHM、缓存和虚拟环境，保留最小复现数据。

# 3. 课程和第三方来源

每个源文件记录上游 revision、SHA-256、许可证文件和 SPDX（若 manifest 提供），source_ref 记录可引用范围。无法确认再分发授权的资料不进入提交包；课程切片只用于本次比赛展示和复现边界。

# 4. 权限和隔离

服务端先执行 JWT 身份、owner、角色和课程范围校验，再允许检索、生成或读取资源。前端隐藏不是权限控制。日志只保留脱敏摘要和 trace ID，不写入 token、私有提示词或完整用户文本。

# 5. 外部服务和责任边界

外部模型、联网搜索、Docker 和 PDF 导出均需目标环境单独配置。deterministic 模式只证明流程可复现，内部单人复核只证明项目组按规则检查，不能写成专家验证或真实用户实验。

# 6. 合规复核记录

最终组包前应保存扫描命令、扫描时间、命中文件和处理结果；若发现来源不明、敏感字段或旧内容，先移出提交目录再重新生成 manifest。
""",
        "10_源码结构与复现说明.md": f"""
# 1. 代码分层

前端 `frontend/src/` 负责路由、页面、组件、状态和 API；`app/` 负责 FastAPI 路由、认证、授权、课程、画像、Agent、资源、学习事件和治理；根目录 Python 模块承载 Agent Swarm、RAG、模型客户端和代码边界；`data/curated/` 是两门 canonical 课程正文；`tests/` 与 `scripts/` 保存自动化验证入口。

# 2. 关键调用链

课程目录从 manifest 加载可用版本；诊断服务写入题目和作答；profile summary 聚合掌握度与十维状态；matching 和 decisions 生成候选动作；m3_agents 和 m3_debate 保存协作阶段；rag_engine 与 knowledge_api 返回 chunk/source_ref；m5_resources 写 artifact/version；m5_learning 与 learning_aggregation 消费反馈事件。

# 3. 复现快照

当前 Git commit 为 `{audit['git_commit']}`，Python 为 `{audit['python']}`，Node 为 `{audit['node']}`。本次知识库包含 {len(kb['chunks'])} 个真实正文分块；测试数据包含 {len(cases)} 条案例，其中 {sum(x['actual_execution_status']=='current_db_evidence' for x in cases)} 条具有当前数据库证据。

# 4. API 和对象复核

复现时先调用 health，再调用课程、画像、资源和学习事件入口。对每个响应记录 HTTP 状态、对象 ID、版本和 trace ID；跨用户读取必须用第二个 owner 验证拒绝。API 返回正常不等于指标达标，需继续按 06 的样本和公式复核。

# 5. 测试入口

聚焦回归、前端 build、无 Docker E2E 和两课程 Chromium E2E 的命令写在 `CURRENT_TEST_RUN.md`。旧式 M5 内存夹具的 11 项失败因缺少当前课程材料而保留，复现者不能只看绿色测试数。

# 6. 变更和再生成

任何课程正文、配置、权限或资源 schema 变化都应先更新审计，再运行生成器。材料脚本不修改正式数据库；若需要重放，用临时数据库复制当前只读快照。
""",
        "11_当前实现与赛题要求逐项对应表.md": f"""
# 1. 对应方法

本表把赛题能力拆成“要求—实现—证据—边界”四列，避免用源码文件名直接代替运行证明。每一项都可从当前代码、数据库对象、浏览器截图或测试命令继续追溯。

# 2. 关键能力逐项说明

垂直知识库对应两门课程的 manifest、章节、知识点、正文 chunk 和 source_ref；个性化对应入学诊断、掌握度和十维画像；多智能体对应诊断、生成、证据审核和决策编排角色；闭环对应 learning_event、路径和复习消费；可信生成对应 claim 状态、版本和来源哈希；部署复现对应 07、08 和当前 E2E 报告。

# 3. 当前状态解释

“已验证”表示当前命令或当前数据库有证据；“结构已存在”表示源码结构可定位但未证明每次运行；“未正式测量”表示三项指标尚未完成冻结集评分和内部责任人复核；“未接入”表示 PPT、视频、报名表和最终压缩包仍待后续阶段。

# 4. 赛题指标对应

幻觉率以 claim 为分母并把 unknown 计错；适配准确率按难度、先修、脚手架、任务复杂度、表达方式和反馈响应六维 0/1/2 评分；知识点覆盖率对关键知识点加权。结果发布前必须附数据集版本、运行模式、失败案例和复核责任。

# 5. 评委复核建议

先抽查一组画像的诊断、掌握度、资源和反馈链，再抽查一个 source_ref 的正文回链，最后抽查一个 challenge 的拒答或失败记录。这样可以同时验证功能闭环、证据链和边界披露。
""",
        "12_系统限制、风险与未完成能力.md": f"""
# 1. 能力边界总览

当前系统在两门机器学习/人工智能基础课程上提供可复现的课程加载、画像、检索、资源对象、学习事件和页面闭环。跨行业泛化、真实外部模型效果、生产并发、长期真实用户效果和正式比赛指标仍未完成验证。

# 2. 数据和评测风险

当前三组画像来自脱敏重放和当前引擎派生视图，不能等同真人访谈；challenge 由项目组构造，不能等同外部盲测；12 条案例有当前数据库证据，48 条仍是冻结未执行场景。指标报告必须保留这些分母和缺口。

# 3. 专业正确性风险

来源绑定降低无依据断言风险，但不能保证检索遗漏、版本冲突或解析错误不存在。严格复核将 supported、contradicted、unsupported、unknown 分开，并把后 3 类计入错误；关键知识点错误直接判案例失败。

# 4. 个性化风险

十维画像是控制信号而非心理诊断。单次自述和点击不能升级掌握度；反馈事件需有结果、证据和置信度。若画像冲突或置信度不足，系统应降低自动决策强度并请求补充证据。

# 5. 安全和运行风险

owner、角色和课程范围由服务端控制，但开发服务器不等于生产安全；trusted_local 不等于容器隔离；外部模型和联网搜索带来新的数据边界；SQLite 适合当前演示范围，不代表高并发部署。

# 6. 已知失败和后续动作

11 个旧式 M5 内存夹具因没有构造当前课程材料而失败，后续应补齐夹具前置或将其迁移到当前课程 fixture。48 条 challenge 需在隔离运行中执行并补充实际 trace。三项指标完成内部双轮复核后才能发布数值。

# 7. 不应做出的声明

不能把 deterministic 写成真实外部大模型；不能把截图写成指标证明；不能把源码存在写成完整运行成功；不能把单人内部复核写成专家或独立验证；不能把两门课程写成全行业知识库。
""",
    }
    for filename, extra in companion.items():
        title, content = docs[filename]
        docs[filename] = (title, content + "\n\n" + extra)

    companion_tail = {
        "00_材料总览与阅读顺序.md": """
# 8. 证据索引使用方法

`EVIDENCE_INDEX.json` 将浏览器报告、截图源目录、代码地图和只读数据库分开列出。复核者应先验证文件存在，再按报告中的时间和运行模式判断其有效范围。一个截图只能证明一个时间点的页面；一个数据库对象只能证明字段和状态；命令输出才能证明对应运行是否完成。

# 9. 版本一致性检查

材料生成时间、Git commit、课程 manifest 版本和测试数据哈希应在同一轮更新。若课程正文变化，必须重算 chunk 和 source_ref；若画像字段变化，必须重跑适配案例；若 API 或权限变化，必须重跑浏览器与安全测试。版本不一致时，旧 PDF 不能继续作为当前证据。

# 10. 评审记录页

评委可以在此记录案例 ID、profile_id、course_id、source_ref_id、artifact_id、learning_event_id、观察到的页面动作、实际响应和疑问。记录应区分“产品行为”“数据快照”“文档解释”和“尚未验证”，这样后续复核可以定位到同一对象。

# 11. 交付前复核顺序

先做敏感字段和许可证扫描，再做文件存在性、PDF 可打开性、页数、图题和目录检查，最后核对报名表、视频和压缩包名称。任何一个门槛失败都应回到生成器修正后重新渲染，不能只手工修改 PDF。
""",
        "02_作品介绍.md": """
# 7. 系统如何体现“个性化”

个性化不是给三个人换标题，而是让同一个知识目标在难度带、先修补救、内容长度、脚手架、表达媒介、任务复杂度和反馈节奏上产生可观察差异。系统保存这些控制字段，因此可以从 profile snapshot 追到 artifact version，再追到学习事件后的下一步决策。

# 8. 系统如何体现“可信”

资源中的专业断言被拆成 claim，claim 绑定 source_ref、字符范围和内容哈希。来源冲突、无来源和无法判断分别进入 contradicted、unsupported、unknown；严格指标把后三者计入错误。评委可以从资源附录抽取一个引用，回到课程正文核对。

# 9. 系统如何体现“协同”

诊断 Agent 负责识别缺口，领域生成 Agent 负责组织资源，证据审核 Agent 负责逐 claim 检查，决策编排 Agent 负责比较候选动作。每个阶段都有状态、输入摘要、输出版本和失败边界；普通聊天不等于完整四阶段运行。

# 10. 价值和局限

系统的价值在于把学习者状态、专业证据和教学动作放进同一条可审计链路；局限在于当前只覆盖两门课程，三组画像是脱敏派生视图，48 条 challenge 尚未执行，三项比赛指标尚未正式发布。
""",
        "07_系统部署说明.md": """
# 9. 数据库初始化和隔离

首次运行只初始化当前应用需要的 schema，不把正式数据库复制进提交包。测试通过环境变量指向临时 SQLite 文件，并在退出后删除 WAL/SHM。评委若需要保留运行结果，应导出脱敏 JSONL 和命令日志，而不是复制整个数据库。

# 10. 运行日志和可观测性

每个生成任务至少有 task_id、run_id、trace_id、owner、course_id、course_version 和状态。故障排查优先看 health、任务状态、Agent run、artifact version 和 learning_event 的时间顺序；不要只看前端 toast。

# 11. 备份、升级和回滚

升级课程时先冻结旧版本，生成新的 manifest、chunk、source_ref 和 license 记录，再切换课程入口。资源和决策引用旧版本时保留原对象，回滚通过版本选择完成。升级后需重复运行课程、RAG、权限和浏览器测试。

# 12. 现场环境清单

现场需确认 Python、Node、npm、Chromium、LibreOffice（如需 PDF）、端口、课程目录、`.env.example` 字段和临时目录权限。外部模型与 Docker 属可选依赖，缺失时按模式矩阵记录为未验证。
""",
        "08_评委运行与演示手册.md": """
# 7. 三组画像叙事要点

视觉型初学者的叙事重点是“我为什么先看到图示和先修题”；项目实践型学习者的重点是“我如何通过训练任务和代码反馈进入迁移”；理论研究型学习者的重点是“我如何看到推导、边界和反例”。每组都应展示反馈前后路径变化。

# 8. 现场记录模板

记录开始时间、运行模式、课程版本、画像 ID、任务 ID、资源版本和事件 ID。若出现网络取消、外部模型超时或代码 sandbox 503，记录原始状态和边界，不用重新点击掩盖失败。

# 9. 备用演示路径

若外部模型不可用，使用 deterministic 课程检索和当前数据库资源；若 Docker 不可用，跳过代码执行并展示 disabled 状态；若浏览器截图失败，保存 API 响应和对象导出，待环境恢复后补图。

# 10. 演示结束检查

退出演示账号，清除浏览器下载和临时文件，确认没有录入真实个人信息。视频剪辑时保留课程、画像、Agent、来源和反馈的关键画面，并在字幕或旁白中说明 deterministic 和内部复核边界。
""",
        "09_数据合规与授权说明.md": """
# 7. 访问控制矩阵

学习者只能读取自己的画像、资源、事件和课程范围；教师或评委视图只能读取被授权课程和脱敏展示对象；系统任务通过 owner 和幂等键关联；来源文件按课程可见性过滤。任何跨 owner 读取都应在 API 测试中验证拒绝。

# 8. 脱敏规则

导出前递归检查 owner_public_id、student_id、username、email、phone、token、secret 和 password 字段；固定演示 ID 替换真实标识；自由文本中的姓名和联系方式人工抽查；日志只保留摘要、状态和哈希。

# 9. 许可证复核流程

先从 manifest 收集 source file、upstream revision、license file 和 SPDX，再核对正文切片是否仍在授权范围内。许可证为 OTHER 或缺少文件时，材料只记录边界，不把它写成可自由再分发。

# 10. 删除和响应

比赛结束或测试失败时删除临时数据库、缓存、浏览器下载和外部模型请求副本；若发现敏感信息，立即从材料目录移除并重新生成 manifest、PDF 和扫描报告。
""",
        "10_源码结构与复现说明.md": """
# 7. 数据对象关系

课程和 source_document 提供正文边界，source_ref 和 chunk 提供检索证据；profile_snapshot 提供学习者状态；generation_task 与 agent_run 提供协同轨迹；artifact_version 提供资源版本；learning_event 提供反馈事实；decision_record 和 review_schedule 提供后续动作。

# 8. 复现最小闭环

不需要复制正式数据库即可复现文档中描述的结构：加载两门 manifest，读取知识库 JSONL，启动 deterministic 服务，选择课程，完成诊断，读取画像和资源，再写入一个脱敏反馈事件。所有导出字段都能与当前 schema 对应。

# 9. 代码地图阅读策略

先看路由和服务边界，再看对象 schema 和权限，再看 Agent/RAG 流程，最后看前端页面和测试。代码地图是索引，不是运行结果；测试报告和浏览器证据必须同时阅读。

# 10. 再现差异记录

不同机器的 Python 包、字体、Chromium、外部模型和数据库路径可能导致截图或文本差异。复现者应记录环境、模式和差异，不能只比较页面像素；专业指标需要在同一数据集和版本上重新评分。
""",
        "11_当前实现与赛题要求逐项对应表.md": """
# 6. 证据等级说明

源码定位属于结构证据；单元测试属于被测行为证据；API 运行属于接口证据；浏览器截图属于指定页面状态证据；数据契约预检属于字段完整性证据；指标评分才属于比赛效果证据。不同等级不能互相替代。

# 7. 当前逐项复核路线

对每项要求先定位实现模块，再定位测试命令或数据库对象，再检查是否有当前版本和运行模式，最后记录限制。若只有源码而没有运行证据，状态写“结构已存在”；若有对象但没有逐案评分，指标写“未正式测量”。

# 8. 未满足项的处理

48 条 challenge 未执行、三项指标未正式发布、外部领域标注不可用、视频和报名表未接入等事项都保留在对应表格和限制文档中。材料完整不等于比赛能力全部达标。

# 9. 评委抽查问题

评委可以询问：这个 claim 的来源是哪一段正文？这个画像维度如何改变资源？这个失败任务如何恢复？这个数字的分母和责任人是谁？文档中的对象 ID、公式和失败案例可以直接支持这些问题。
""",
        "12_系统限制、风险与未完成能力.md": """
# 8. 风险优先级

高优先级是专业事实错误、权限越界和敏感数据泄露；中优先级是画像证据不足、版本混用和任务恢复不完整；低优先级是前端大 chunk 警告、截图差异和可选服务缺失。优先级不改变失败案例的保留要求。

# 9. 风险监控指标

运行时监控任务失败率、重试次数、source_ref 绑定率、unknown claim 数、跨 owner 拒绝数和未执行案例数。结构指标只能说明数据状态，不能替代专业正确性或学习效果指标。

# 10. 能力完成条件

要解除当前限制，至少需要：完成 60 条冻结案例实际运行；为每个事实 claim 建立来源和单人双轮复核；完成六维适配评分和加权知识点覆盖；补充项目实践型画像缺失证据；重跑两门课程的浏览器与 API 证据。

# 11. 版本化后续

后续能力应以新的评测版本发布，保留旧版本分母、失败案例和运行模式。不能只替换一个百分比而不更新数据集、源码 commit、课程版本和复核记录。
""",
    }
    for filename, extra in companion_tail.items():
        title, content = docs[filename]
        docs[filename] = (title, content + "\n\n" + extra)
    # Formal submission documents need evidence density, not only a narrative
    # summary. Expand the current, traceable corpus into readable appendices.
    source_appendix = []
    for chapter in kb["chapters"]:
        source_appendix.append(
            f"## {chapter['course_id']} / chapter-{chapter['chapter_index']:02d} / {chapter['title']}\n"
            f"源文件：`{chapter['path']}`；SHA-256：`{chapter['sha256']}`；知识点：{', '.join(chapter.get('knowledge_point_codes') or []) or '未声明'}。"
        )
    chunk_appendix = []
    # The complete 144-row corpus remains in test_data/knowledge_base/chunks.jsonl
    # and in document 05. The main design document carries a substantial,
    # readable sample plus the exact pointer to the complete index.
    for index, chunk in enumerate(kb["chunks"][:120], start=1):
        quote = re.sub(r"\s+", " ", chunk.get("content", "")).strip()
        chunk_appendix.append(
            f"### 证据块 {index:03d} · `{chunk['chunk_id']}`\n"
            f"课程：`{chunk['course_id']}`；版本：`{chunk['course_version']}`；章节：`{chunk['chapter_id']}`；来源：`{chunk['source_ref_id']}`。\n"
            f"文件：`{chunk['source_document']}`；字符范围：{chunk['source_span']['start_char']}–{chunk['source_span']['end_char']}；内容哈希：`{chunk['content_sha256']}`。\n"
            f"知识点：{', '.join(chunk.get('knowledge_point_codes') or []) or '未声明'}。\n"
            f"正文摘录：{quote}"
        )
    kp_appendix = []
    for kp in kb["knowledge_points"]:
        kp_appendix.append(
            f"- `{kp['course_id']}` / `{kp['knowledge_point_id']}`：{kp.get('title','')}；层级 `{kp.get('level','')}`；先修：{', '.join(kp.get('prerequisites') or []) or '无'}。"
        )
    profile_appendix = []
    profile_narratives = []
    for profile in profile_data["profiles"]:
        profile_appendix.append(f"## {profile['profile_id']} · {profile['archetype']}")
        profile_appendix.append(f"课程：`{profile['course_id']}`；课程版本：`{profile['course_version']}`；快照来源：{', '.join(profile.get('source_snapshot_ids') or [])}。")
        profile_appendix.append(f"背景：{json.dumps(profile.get('background'), ensure_ascii=False)}；目标：{json.dumps(profile.get('learning_goal'), ensure_ascii=False)}；偏好：{json.dumps(profile.get('preferences'), ensure_ascii=False)}。")
        mastery = profile.get('mastery_snapshot') or {}
        profile_appendix.append(f"掌握度总体值：{mastery.get('overall')}；知识点数量：{len(mastery.get('concept_mastery') or {})}；薄弱点：{json.dumps(mastery.get('weak_points'), ensure_ascii=False)}；置信度：{mastery.get('confidence')}。")
        profile_appendix.append(f"入学诊断要求：{', '.join(profile.get('entrance_diagnostic', {}).get('required_dimensions') or [])}；诊断记录数量：{len(profile.get('entrance_diagnostic', {}).get('records') or [])}。")
        for dim in profile.get('ten_dimensions') or []:
            profile_appendix.append(f"维度 `{dim['key']}`（{dim['label']}）：score={dim.get('score')}，confidence={dim.get('confidence')}，status={dim.get('status')}；资源影响：{dim.get('resource_influence')}；教学影响：{dim.get('teaching_influence')}；证据：{json.dumps(dim.get('evidence') or [], ensure_ascii=False)}。")
        profile_appendix.append(f"当前适配计划：{json.dumps(profile.get('adaptation_plan'), ensure_ascii=False)}。")
        records = profile.get("entrance_diagnostic", {}).get("records") or []
        mastery = profile.get("mastery_snapshot") or {}
        plan = profile.get("adaptation_plan") or {}
        resources_for_profile = [r for r in profile_data["resources"] if r.get("course_id") == profile.get("course_id")]
        events_for_profile = [e for e in profile_data["events"] if e.get("course_id") == profile.get("course_id")]
        diagnostic_sentence = "；".join(
            f"{r.get('diagnostic_dimension') or '未标注'}题目结果={r.get('correct')}、得分={r.get('score')}、置信度={r.get('confidence')}、知识点={r.get('knowledge_point_id')}"
            for r in records[:3]
        ) or "当前快照未提供逐题记录，保留为待补证据"
        profile_narratives.append(
            f"## 案例叙事：{profile['archetype']}（{profile['profile_id']}）\n\n"
            f"这是一组用于评委复现的脱敏重放画像，课程为 `{profile['course_id']}`，版本为 `{profile['course_version']}`。学习者背景为{json.dumps(profile.get('background'), ensure_ascii=False)}，目标是{json.dumps(profile.get('learning_goal'), ensure_ascii=False)}，偏好为{json.dumps(profile.get('preferences'), ensure_ascii=False)}。这些输入来自当前数据库快照和画像引擎派生视图，不代表真实用户访谈。\n\n"
            f"入学阶段先执行理论、应用和工程判断三类诊断。当前导出的逐题证据为：{diagnostic_sentence}。系统将这些结果与知识点先修关系合并，得到总体掌握度 `{mastery.get('overall')}`，薄弱点为 `{json.dumps(mastery.get('weak_points'), ensure_ascii=False)}`，置信度为 `{mastery.get('confidence')}`。因此，诊断 Agent 的中间产物不是“已掌握/未掌握”二元标签，而是带证据和不确定性的 skill gap。\n\n"
            f"随后领域生成 Agent 按课程版本召回正文 chunk 和 source_ref，生成候选讲义、训练任务、分阶测验、导图及可选代码资源；证据审核 Agent 逐条检查 claim 是否有来源支持；决策编排 Agent 根据适配计划 `{json.dumps(plan, ensure_ascii=False)}` 选择下一步。对该画像，资源控制重点是{plan.get('difficulty_band') or plan.get('strategy') or '当前快照记录的难度和脚手架规则'}，教学动作重点是{plan.get('recommended_actions') or plan.get('next_step') or '补先修、调整脚手架并安排复测'}。\n\n"
            f"反馈阶段不把页面浏览当作掌握证据，而是等待测验、代码、实验、复述或复习事件。当前课程快照可追溯资源对象 {len(resources_for_profile)} 个、学习事件 {len(events_for_profile)} 条；每个事件保留 evidence_status、mastery_eligible 和完成影响。若事件显示关键知识点失败，系统会把路径切回补救节点或降低首题难度；若连续证据支持迁移，则进入 transfer/挑战。下一步决策仍需结合 source_ref、置信度和风险，不能从一次点击直接升级画像。\n\n"
            f"该案例的可复核证据包括 profile snapshot ID、诊断记录、掌握度字段、十维维度状态、artifact/version、learning_event 和本目录中的 JSONL 行。当前限制是三组画像中部分资源 ID 在数据库快照中复用，且项目实践型画像的互动偏好与学习情境证据不足；这些缺口保留为风险，不包装成三套完全独立的真实用户资源。"
        )
    resource_appendix = []
    for resource in profile_data["resources"]:
        content = resource.get('content') or {}
        source_ids = []
        def collect_source_ids(value: Any) -> None:
            if isinstance(value, dict):
                for key, item in value.items():
                    if 'source' in str(key).lower() and isinstance(item, list):
                        source_ids.extend(str(x) for x in item)
                    collect_source_ids(item)
            elif isinstance(value, list):
                for item in value: collect_source_ids(item)
        collect_source_ids(content)
        content_summary = re.sub(r"\s+", " ", json.dumps(content, ensure_ascii=False))[:1500]
        source_summary = ", ".join(dict.fromkeys(source_ids)) or "未在内容中发现 sourceRefIds"
        content_keys = ", ".join(sorted(content.keys())) if isinstance(content, dict) else "raw_text"
        resource_appendix.append(f"## 资源 `{resource['artifact_id']}`\n课程：`{resource['course_id']}`；类型：`{resource['artifact_type']}`；状态：`{resource['status']}`；版本：`{resource['version_id']}`；内容哈希：`{resource['content_hash']}`。\n来源 ID：{source_summary}。\n内容结构键：{content_keys}。\n资源内容摘要：{content_summary}")
    case_appendix = []
    for case in cases:
        case_appendix.append(
            f"## 案例 `{case['case_id']}`\n"
            f"课程：`{case['course_id']}` / `{case['course_version']}`；画像：`{case['profile_id']}`；类别：`{case['category']}`；难度：`{case['difficulty']}`。\n"
            f"输入：{json.dumps(case['input'], ensure_ascii=False)}。\n"
            f"必需知识点：{', '.join(case.get('required_knowledge_points') or [])}；关键知识点：{', '.join(case.get('critical_knowledge_points') or [])}。\n"
            f"期望资源：{json.dumps(case.get('expected_resource_types'), ensure_ascii=False)}；期望难度：`{case['expected_difficulty']}`；期望证据：{', '.join(case.get('expected_evidence') or [])}；期望决策：`{case['expected_decision']}`。\n"
            f"实际执行状态：`{case['actual_execution_status']}`；Agent trace：{json.dumps(case.get('actual_agent_trace'), ensure_ascii=False)}；资源：{json.dumps(case.get('actual_resources'), ensure_ascii=False)}；反馈：{json.dumps(case.get('actual_feedback'), ensure_ascii=False)}；诊断：{json.dumps(case.get('actual_diagnostics'), ensure_ascii=False)}。\n"
            f"失败/限制：{case.get('failure_reason') or '无'}。"
        )
    # Keep appendices as review indexes. The complete records remain in
    # test_data; the reader-facing documents should explain the design and
    # evidence in prose instead of repeating JSON-like rows.
    profile_index = []
    for profile in profile_data["profiles"]:
        mastery = profile.get("mastery_snapshot") or {}
        profile_index.append(
            f"- `{profile['profile_id']}`：{profile['archetype']}；课程 `{profile['course_id']}`；"
            f"掌握度 `{mastery.get('overall')}`；十维画像 {len(profile.get('ten_dimensions') or [])} 项；"
            f"完整逐维数据见 `test_data/learner_profiles.json`。"
        )
    docs["04_个性化生成与学习反馈说明.md"] = (
        docs["04_个性化生成与学习反馈说明.md"][0],
        docs["04_个性化生成与学习反馈说明.md"][1]
        + "\n\n# 附录 A：画像复核入口\n\n"
        + "\n".join(profile_index)
        + "\n\n逐维证据、诊断记录、适配计划和派生标签保存在 `test_data/learner_profiles.json` 与 `test_data/profile_adaptation_outputs.json`；本附录只保留入口，避免把正文案例重新压缩成字段清单。"
    )
    resource_index = []
    for resource in profile_data["resources"]:
        resource_index.append(
            f"- `{resource['artifact_id']}`：{resource['artifact_type']}；课程 `{resource['course_id']}`；"
            f"状态 `{resource['status']}`；版本 `{resource['version_id']}`。"
        )
    docs["03_多智能体协同决策说明.md"] = (
        docs["03_多智能体协同决策说明.md"][0],
        docs["03_多智能体协同决策说明.md"][1]
        + "\n\n# 附录 A：资源版本复核入口\n\n"
        + "\n".join(resource_index)
        + "\n\n资源完整内容、来源引用和内容哈希保存在 `test_data/resources.jsonl`；本附录用于从 Agent 运行追到资源版本。"
    )
    docs["05_领域知识库与可信生成说明.md"] = (
        docs["05_领域知识库与可信生成说明.md"][0],
        docs["05_领域知识库与可信生成说明.md"][1]
        + f"\n\n# 附录 A：正文分块代表样本\n\n"
        + f"完整 `{len(kb['chunks'])}` 条分块和 `{len(kb['refs'])}` 条 source_ref 已逐行保存在 `test_data/knowledge_base/chunks.jsonl` 与 `source_refs.jsonl`。以下只保留 12 条跨课程样本，供评委理解字符范围、知识点和正文摘录之间的关系。\n\n"
        + "\n\n".join(chunk_appendix[:12])
        + "\n\n完整来源链可按 `chunk_id`、`source_ref_id` 和内容哈希回链，不在正文中重复打印全部分块。"
    )
    case_index = []
    for case in cases:
        case_index.append(
            f"- `{case['case_id']}`：{case['category']}；画像 `{case['profile_id']}`；"
            f"{case['difficulty']}；执行状态 `{case['actual_execution_status']}`。"
        )
    docs["06_测试方案与指标报告.md"] = (
        docs["06_测试方案与指标报告.md"][0],
        docs["06_测试方案与指标报告.md"][1]
        + "\n\n# 附录 A：测试案例索引\n\n"
        + "\n".join(case_index[:18])
        + "\n\n以上保留每类案例的代表入口。完整 60 条案例的输入、必需知识点、期望动作、实际状态、trace、资源、反馈和失败原因保存在 `test_data/test_cases.jsonl`；附录索引不替代逐案例数据文件。"
    )
    kp_rows = []
    for item in kb["knowledge_points"]:
        kp_rows.append(f"| `{item['course_id']}` | `{item['knowledge_point_id']}` | {item.get('title','')} | {item.get('level','')} | {', '.join(item.get('prerequisites') or []) or '无'} |")
    chunk_rows = []
    for item in kb["chunks"][:30]:
        excerpt = re.sub(r"\s+", " ", item.get("content", ""))[:120].replace("|", "/")
        chunk_rows.append(f"| `{item['chunk_id']}` | `{item['course_id']}` | `{item['source_ref_id']}` | {item['source_span']['start_char']}–{item['source_span']['end_char']} | {excerpt} |")
    profile_rows = []
    for profile in profile_data["profiles"]:
        mastery = profile.get("mastery_snapshot", {}).get("concept_mastery") or {}
        dims = profile.get("ten_dimensions") or []
        profile_rows.append(f"| `{profile['profile_id']}` | {profile['archetype']} | `{profile['course_id']}` | {len(mastery)} | {len(dims)} | {', '.join(profile.get('preferences') or [])[:50]} |")
    resource_rows = []
    for resource in profile_data["resources"]:
        resource_rows.append(f"| `{resource['artifact_id']}` | `{resource['course_id']}` | {resource['artifact_type']} | {resource['status']} | `{resource['version_id']}` | {len(json.dumps(resource.get('content') or {}, ensure_ascii=False))} |")
    test_rows = []
    for category in sorted({item["category"] for item in cases}):
        group = [item for item in cases if item["category"] == category]
        test_rows.append(f"| {category} | {len(group)} | {sum(item['difficulty']=='challenge' for item in group)} | {sum(item['actual_execution_status']=='current_db_evidence' for item in group)} |")
    docs["01_作品设计与实现方案.md"]=(docs["01_作品设计与实现方案.md"][0], docs["01_作品设计与实现方案.md"][1] + f"""

# 附录 A：知识点目录代表样本

| 课程 | 知识点 ID | 知识点名称 | 层级 | 先修 |
|---|---|---|---|---|
{chr(10).join(kp_rows[:12])}

完整知识点黄金目录保存在 `test_data/knowledge_base/knowledge_points.jsonl`，此处保留跨课程代表样本。

# 附录 B：数据对象和版本字段

| 对象 | 必要字段 | 作用 |
|---|---|---|
| `DBProfileSnapshot` | owner、course、profile_version、snapshot、content_hash、trace_id | 冻结画像状态和证据 |
| `DBSourceDocument` | course、filename、processing_status、content_hash | 课程正文和解析状态 |
| `DBSourceRef` | source_document、chapter、location、quote、content_hash | 可回链引用片段 |
| `DBGenerationTask` | owner、capability、course、idempotency_key、trace_id | 生成任务身份和幂等 |
| `DBAgentRun` | task、role、agent_version、input_summary、output_version、status | Agent 阶段记录 |
| `DBArtifactVersion` | artifact、version_number、content、content_hash、source_refs | 不可变资源版本 |
| `DBLearningEvent` | owner、course、event_type、payload、evidence_status、mastery_eligible | 学习反馈事实 |

# 附录 C：三组画像概览

| profile_id | 类型 | 课程 | 掌握度知识点数 | 十维数 | 偏好 |
|---|---|---|---:|---:|---|
{chr(10).join(profile_rows)}

# 附录 D：实现到评委操作

1. 评委登录后选择课程，页面调用课程目录和上下文接口。
2. 入学诊断生成并保存题目版本、题型维度、答案和来源。
3. 画像和掌握度进入资源适配，形成难度带、脚手架和表达方式。
4. 对话或学习任务触发 Agent/资源接口，返回任务状态和来源引用。
5. 测验、代码或实验事件进入学习事件聚合，刷新路径、复习和 Dashboard。

实现版本：`{audit['git_commit']}`。上述链路的当前可运行证据见 `EVIDENCE_INDEX.json`；代码存在和数据库演示对象不替代完整外部模型效果验证。

# 附录 E：当前课程、知识点与正文证据

""" + "\n\n".join(source_appendix[:12]) + f"""

其余章节来源记录和文件哈希保存在 `test_data/knowledge_base/chapters.jsonl` 与 `license_records.json`。

# 附录 F：知识点黄金目录

""" + "\n".join(kp_appendix[:12]) + f"""

完整先修关系和知识点字段以 `knowledge_points.jsonl`、`prerequisite_edges.jsonl` 为准。

# 附录 G：正文证据块逐条索引（代表性样本）

完整 `{len(kb['chunks'])}` 条分块保存在 `test_data/knowledge_base/chunks.jsonl` 和 `source_refs.jsonl`；主文档展示前 12 条跨章节样本，便于评委阅读并按 ID 回链。

""" + "\n\n".join(chunk_appendix[:6]) + """
""")
    docs["05_领域知识库与可信生成说明.md"]=(docs["05_领域知识库与可信生成说明.md"][0], docs["05_领域知识库与可信生成说明.md"][1] + f"""

# 附录 B：来源完整性

- 章节记录：`{len(kb['chapters'])}`；
- 知识点记录：`{len(kb['knowledge_points'])}`；
- 先修关系：`{len(kb['licenses'])}` 个源文件许可记录；
- 许可证记录保留 upstream revision、文件哈希、许可证文件和 SPDX（若 manifest 提供）。

每个引用片段都能回到当前仓库课程正文路径，材料不使用人工摘要替代正文来源。

# 附录 C：证据审核记录格式

```json
{{
  "claim_id": "claim-example",
  "claim_text": "候选专业事实",
  "source_ref_ids": ["src-example"],
  "evidence_span": {{"start_char": 120, "end_char": 260}},
  "annotation": "supported|contradicted|unsupported|unknown",
  "reason": "只写公开判断依据"
}}
```

审核只判断可追溯证据，不把模型流畅度、来源数量或页面展示当作正确性证明。
""")
    docs["06_测试方案与指标报告.md"]=(docs["06_测试方案与指标报告.md"][0], docs["06_测试方案与指标报告.md"][1] + f"""

# 附录 B：案例分布

| 类别 | 总数 | challenge 数 | 当前 DB 证据数 |
|---|---:|---:|---:|
{chr(10).join(test_rows)}

# 附录 C：逐案例记录字段

每条案例包含课程、版本、画像、必需知识点、关键知识点、资源类型、期望难度、期望证据、期望决策、实际执行状态、trace 引用、资源引用、反馈引用和失败原因。`designed_not_run` 只表示待执行，不能写入测试通过结论。当前数据契约预检为 60/60，通过只说明字段、课程、画像、知识点和 source_ref 可对应，不说明产品业务行为已经全部通过。

# 附录 D：严格失败判定

- claim 出现关键知识点 contradiction：案例失败；
- unknown 不从幻觉率分母剔除；
- 适配总分低于 10/12 或难度/先修为 0：样本失败；
- 关键知识点遗漏即使普通知识点覆盖高：案例失败；
- 课程外、无答案和版本冲突案例要求拒答、补证据或明确不确定性；
- 不删除失败案例，不调整分母，不把 fixture 预期字段当实际输出。

# 附录 E：当前验证命令

```text
.venv\\Scripts\\python.exe -m pytest -q tests/test_m0_course_catalog.py tests/test_m1_course_sources.py tests/test_f3_profile_onboarding.py tests/test_m1_profile_evidence.py tests/test_m3_profiles.py tests/test_m3_agents.py tests/test_m3_debate.py tests/test_m3_matching.py tests/test_m3_decisions.py tests/test_m3_resources.py tests/test_competition_demo_seed.py tests/test_competition_package_runtime.py
cd frontend && npm.cmd run build
.venv\\Scripts\\python.exe scripts\\e2e_no_docker.py
.venv\\Scripts\\python.exe scripts\\e2e_lzz_two_course_demo_evidence.py
```

当前结果和限制写入 `CURRENT_AUDIT_REPORT.md` 与 `EVIDENCE_INDEX.json`。
""")
    chapter_extension = """

# 8. 课程内容组织与知识图谱

两门课程采用课程—章节—知识点—先修边关系组织。课程 manifest 保存固定版本、来源角色、上游 revision 和文件哈希；章节映射将知识点绑定到可阅读正文；先修边用于路径规划、入学诊断覆盖和资源难度控制。课程选择器只暴露当前状态为 published 且有可用知识材料的课程，历史 withdrawn 课程保留用于审计，不进入正常学习入口。

# 9. 文档解析与混合检索

解析器保留标题、章节、代码块、表格和原文位置，避免只存一段无法回跳的字符串。检索先按用户、课程和版本做范围约束，再结合词项、语义和知识图谱关系召回。每个候选保存源文档、chunk、字符范围、内容哈希和知识点代码。证据不足时生成流程只能拒答、降级或请求补充材料。

# 10. 个性化资源工厂

资源工厂将画像适配控制注入讲义、训练任务、测验、思维导图、代码、交互实验和视频脚本。资源不是一次性文本，而是带 artifact、artifact_version、状态、来源、学习目标、完成规则和导出边界的对象。初学者得到更多步骤和例子，项目型学习者得到参数对照和故障排查，理论型学习者得到推导、边界和迁移任务。

# 11. 多 Agent 协同和可解释决策

诊断、领域生成、证据审核和决策编排拥有不同输入、输出和禁止动作。任务状态、运行状态和资源版本独立保存，前端 Agent Timeline 只公开可理解的阶段摘要。决策记录保留候选动作、规则、证据、风险、负担和确认要求。系统不会把多次生成或页面动画当作协同决策证明。

# 12. 入学诊断与掌握度更新

入学诊断覆盖理论、应用和工程判断三类能力。诊断题目绑定课程、知识点、来源、题型、难度和答案版本；作答结果形成能力状态和不确定性。掌握度由有证据的学习事件更新，连续失败会提高补先修和降阶解释优先级，延迟复测用于检查保持，不以一次通过宣称胜任。

# 13. 反馈、路径与复习编排

测验、代码、实验、复述、复习和追问产生不同强度的学习事件。事件先写入事实表，再由路径、画像、复习和 Dashboard 分别消费，防止某个聚合器直接覆盖其他证据。路径节点有先修和完成规则，复习计划保存间隔、优先级和来源。反馈驱动的决策可以提出降维解释、补救节点、维持巩固或进阶挑战。

# 14. 安全、权限与数据治理

服务端以认证用户为主体执行 owner、角色和课程范围校验；前端路由守卫只是体验层。来源和私有文档在检索前过滤，日志公开摘要脱敏。代码执行默认关闭，trusted_local 只用于可信本机研究，Docker 才提供容器隔离。提交材料排除密钥、运行数据库、WAL/SHM、真实用户数据和未确认授权素材。

# 15. 部署、运维与故障恢复

系统可以在 Python 3.11、Node.js 20 和 SQLite 环境运行核心流程。后端健康检查披露数据库、模型、检索和 sandbox 状态；前端使用 Vite 构建。生成任务支持失败、重试和恢复，浏览器刷新不会被描述为生成成功。Docker、外部模型、联网搜索、Chromium PDF 导出分别列出前置条件和验证边界。

# 16. 测试方法和指标解释

测试分为静态、单元、集成、API、浏览器、数据契约和内部指标评测。三项比赛指标使用冻结样本、来源规则、严格失败判定和失败保留；没有外部领域标注人员时，只能称为项目组内部复核。指标分母、版本、运行模式和复核责任必须与明细文件一起保存。

# 17. 当前验证结论和可迁移性

当前验证证明两门课程的页面、课程目录、资源工作区、画像摘要、路径和部分学习反馈入口在指定环境可运行。它不证明跨行业知识泛化、真实外部模型效果、生产并发、Docker 安全认证或三项比赛指标已经达标。迁移到新领域需要重新提供课程正文、许可证、知识点图谱、诊断集和适配评测。
"""
    human_sections = [
        ("1.1 从真实学习困难出发", [
            "系统面对的不是一个抽象问题，而是一个带有起点、目标和限制的学习任务。刚接触监督学习的学生可能还没有建立训练集和测试集的区别；做过项目的学生可能理解训练流程，却在数据泄漏和评估解释上反复出错；理论基础较强的学生则可能会推导公式，却没有把结论迁移到真实数据。三个人收到同一篇长答案，内容看似完整，实际负担却完全不同。",
            "EduMatrix 先记录学习者想完成什么、已经会什么、哪里容易出错以及能够投入多少时间，再用诊断题和学习事件逐步修正这个状态。画像不是一次填写后永久不变的标签，而是教学过程中的工作状态。它最终要改变资源难度、解释节奏、练习形式或复习顺序，才能称为个性化。",
            "这种设计也让评委可以观察因果关系：输入画像之后，系统给出什么控制参数；控制参数进入哪个资源字段；学习者提交反馈后，哪个状态发生变化。文档正文解释这条因果链，附录只保存用于复核的对象编号。"
        ]),
        ("2.1 两门课程的学习路线", [
            "《机器学习基础与实践》承担第一层能力建设，从 Python、NumPy、Pandas 和数据处理开始，逐步进入特征、模型、评估和实验判断。它适合需要建立完整基础链路的学习者，也为后续深度学习和 Agent 任务提供先修条件。",
            "《人工智能与深度学习：从机器学习基础到大模型智能体》在基础之上增加神经网络、Transformer、大模型、RAG、工具调用和 Agent 协同，强调从概念理解走向系统实现。课程中的每个章节都对应学习目标、知识点和适合的任务类型。",
            "两门课不是把资料简单堆在一起。课程选择会影响诊断范围、检索范围、资源难度和复习顺序；当学习者从基础课进入智能体课程时，系统会重新确认先修，而不是直接沿用旧画像。"
        ]),
        ("3.1 一次请求怎样穿过系统", [
            "学习者在页面上选择课程后，前端把课程上下文和当前身份一起发送给后端。后端先确认用户是否有权访问课程，再读取画像和诊断状态，随后才允许检索和生成。这样可以防止页面切换造成课程内容串线。",
            "一次资源请求会产生一个任务。任务包含课程、画像快照、目标知识点和生成模式；Agent 运行、证据审核和资源版本都与任务关联。页面展示阶段摘要，评委可以看见系统正在分析、生成、审核还是等待反馈。",
            "请求失败时系统保留失败状态和原因，允许按幂等键重试或降级。刷新页面只能重新读取状态，不能被描述为任务已经成功。"
        ]),
        ("4.1 一个学习回合的完整故事", [
            "一个回合从“我想学会某个知识点”开始。系统先检查先修缺口，再从课程正文召回相关内容，按照学习者的难度带组织解释和练习。初学者先看到概念图和小问题，项目型学习者看到带输入输出的任务，理论型学习者看到假设、推导和边界。",
            "学习者提交答案后，系统记录的不只是对错，还包括题目所属知识点、作答信心、反馈类型和是否满足掌握度更新条件。答对但信心低会安排复述或复测，答错且暴露先修缺口会插入补救节点。",
            "下一回合因此会发生变化。系统不是不断生成更多内容，而是根据证据决定继续、补救、巩固或进阶。"
        ]),
        ("5.1 入学诊断如何减少误判", [
            "入学诊断分为理论、应用和工程判断三类。理论题检查概念关系和基本原理，应用题检查能否把概念用于数据或案例，工程判断题检查对边界、风险和实现条件的认识。三类结果共同构成学习起点。",
            "诊断记录包含题目版本、知识点、得分、正确性和置信度。系统允许不确定状态存在：答对但信心很低，或答错却能清楚说明思路，都不会被简单压成最高或最低掌握度。",
            "诊断 Agent 的输出是带证据的能力缺口，而不是一句“适合初级”或“适合高级”。后续匹配和生成都要引用这个缺口。"
        ]),
        ("6.1 资源为什么要做成对象", [
            "讲义有目标、例子和检查点，训练任务有步骤、输入输出和完成标准，分阶测验有题目和解析，导图有节点和关系，代码练习有运行边界。资源不是一次性文本，而是可以被路径、复习和反馈继续使用的对象。",
            "画像控制“怎么教”，课程来源控制“教什么”。互动偏好可以决定先展示图示还是代码，认知加工状态可以决定一次讲几个概念，动机目标可以决定案例使用分类任务还是 Agent 工具调用，但这些控制不能改变专业事实。",
            "资源版本让系统能够回答“学习者当时看到的是哪一版内容”。如果后续课程更新，旧资源仍能追溯到原来的课程版本。"
        ]),
        ("7.1 反馈怎样改变路径", [
            "系统区分一次测验、连续练习、代码测试、复述和延迟复测，它们对掌握度的证据强度不同。一次即时答对不能直接证明迁移能力；带隐藏测试的代码任务通常提供更强的实践证据。",
            "当证据不足时，系统可以选择继续收集证据，而不是强行推荐更难内容。当证据显示先修缺口时，系统插入补救节点并保留原路径；当证据稳定支持迁移时，才提出进阶挑战。",
            "复习队列也参与决策。短时间连续出错的知识点优先补救，稳定掌握但迁移不足的知识点安排间隔后的变式任务。"
        ]),
        ("8.1 知识库如何服务学习者", [
            "知识库的目的不是展示文件数量，而是让系统能够在生成前找到与问题真正相关的课程正文。解析阶段保留标题、段落、代码和表格结构；分块阶段沿正文连续切分，避免只留下没有上下文的标题。",
            "检索先按用户、课程和版本过滤，再结合词项、语义和先修关系排序。召回结果会进入生成上下文，最终资源中的专业判断必须能够回到来源片段。",
            "正文只展示少量真实片段并解释它们如何被使用，完整分块数据放在独立知识库目录。这样评委先理解系统行为，需要时再按 ID 复核原文。"
        ]),
        ("9.1 从证据到可读答案", [
            "检索结果不会原样丢给学习者。生成 Agent 会把证据组织成符合画像的讲解结构，证据审核 Agent 再检查每个专业判断是否有来源支持。",
            "如果一个说法无法从当前课程正文得到支持，系统应明确说明不确定，或者请求补充材料，而不是用流畅文字掩盖缺口。来源冲突、无来源和无法判断分别保留不同状态。",
            "这也是为什么来源数量不能直接等同于低幻觉率。真正需要检查的是每个事实性 claim 是否被正确来源支持。"
        ]),
        ("10.1 三组学习者的差异", [
            "视觉型初学者首先需要建立概念之间的联系。系统把章节拆成较短回合，用流程图、对照表和即时检查帮助他确认术语和步骤；连续暴露先修缺口时，路径回到基础节点。",
            "项目实践型学习者更关心能否做出来。系统减少重复定义，增加数据准备、参数选择、运行结果和故障排查；代码测试失败时，反馈先解释问题属于数据、模型还是环境。",
            "理论研究型学习者需要看到模型为什么成立、何时失效。系统安排推导、反例、复杂度和假设检查，并用小型实验检验理论是否能迁移到数据。"
        ]),
        ("11.1 Agent 协同中的责任", [
            "诊断 Agent 负责整理能力缺口和不确定性，不负责发布讲义；领域生成 Agent 负责组织资源候选，不负责决定是否通过；证据审核 Agent 负责检查来源和 claim，不负责设计路径；决策编排 Agent 负责比较候选动作并说明理由。",
            "这种分工让失败容易定位。内容有问题看生成和引用，来源冲突看审核，路径不合理看匹配和决策，反馈没有生效看事件和聚合。",
            "前端展示的是阶段摘要和状态，不把动画或多次调用本身当成协同证明。"
        ]),
        ("12.1 十维画像如何落到教学字段", [
            "知识掌握度影响难度带和复测优先级，误概念影响反例和错因解释，迁移能力影响变式任务，认知加工影响单次内容量和脚手架，学习策略影响练习与复习组合，元认知影响信心校准。",
            "动机和目标影响案例上下文，情绪与抗挫力影响失败后的提示强度，互动偏好影响媒介顺序，学习情境影响任务时长、设备要求和节奏。",
            "每个维度都必须说明证据来源和受影响字段。如果只是采集而没有接入决策，材料明确写出“已采集但未接入”。"
        ]),
        ("13.1 复习不是资源重播", [
            "复习根据知识点重要性、最近一次证据、遗忘风险和可用时间安排。系统不会把旧资源简单再列一次，而是决定复习解释、复测题、变式任务和实践任务的组合。",
            "复习完成后仍然记录结果。结果可能提高保持信心，也可能暴露“会做原题但不会变式”的问题，从而触发新的迁移任务。",
            "这种设计把复习变成学习闭环的一部分，而不是单独的收藏夹功能。"
        ]),
        ("14.1 权限控制如何影响体验", [
            "权限控制是每次学习请求的前置条件。用户只能看到自己的画像和事件，课程范围决定可检索的正文，资源 owner 决定可读取的版本。",
            "前端隐藏按钮只是体验层，真正校验发生在服务端。评委可以使用不同 owner 或不同课程做反向读取测试，验证越界请求会被拒绝。",
            "日志只保留脱敏摘要、状态和哈希，不写入 token、完整用户文本或私有提示词。"
        ]),
        ("15.1 如何判断系统真的运行", [
            "最有说服力的是一条连续操作链：课程版本出现，诊断记录生成，画像显示薄弱点，资源带有适配差异和来源，反馈事件进入系统，下一步路径发生变化。",
            "单独截图只能说明页面打开过，不能说明对象来自同一次运行。因此运行手册把页面操作、API 状态、对象 ID 和时间顺序放在一起。",
            "若某一步来自数据库演示快照，材料直接标注；若使用 deterministic 模式，也明确说明它证明的是流程可复现。"
        ]),
        ("16.1 指标需要什么证据", [
            "专业知识谬误率需要逐条事实 claim 的分母，适配准确率需要六个维度的明确评分，知识点覆盖率需要列出必需和关键知识点。没有这些明细，资源再多也不能宣布达标。",
            "当前没有外部领域标注人员，因此采用项目组单人双轮内部复核，并把 unknown 计入错误。尚未执行的 challenge 和缺少原子标注的案例都保留在分母准备说明中。",
            "正式发布数值前，还必须锁定数据集版本、运行模式、失败案例和复核责任。"
        ]),
        ("17.1 当前成果与后续工作", [
            "当前版本已经把两门课程、三组画像、资源对象、学习事件、RAG 切片和评委复现入口组织成一套可审计材料，能够展示系统设计和指定环境下的核心闭环。",
            "下一步重点不是继续堆字段，而是完成冻结案例的实际运行，为资源建立逐 claim 复核，为三组画像补齐差异化资源输出，并在同一版本上重新计算指标。",
            "只有当这些工作完成，材料才可以把“未正式测量”改成带分母、失败案例和责任人的正式结果。"
        ]),
    ]
    body_detail = "\n\n".join(f"## {title}\n\n" + "\n\n".join(paragraphs) for title, paragraphs in human_sections)
    technical_detail = """

## 3.2 前端、接口和业务服务的边界

前端使用 Vue 3 和 Vite 组织页面、路由、状态和 API client。课程目录、诊断、画像、学习路径、知识库、资源和反馈页面都通过后端接口读取当前用户范围内的数据；页面上的 loading、queued、running、failed 和 completed 状态来自服务端对象，而不是前端自己猜测生成进度。这样即使刷新页面，用户仍然会看到同一个任务的真实状态。

后端以 FastAPI 为入口，将认证、课程、诊断、画像、检索、资源、测验、代码执行和学习事件拆成路由模块。典型请求的顺序是：解析 Bearer Token，得到当前用户；校验 owner 和课程范围；读取已经冻结的画像或课程版本；执行对应业务；写入对象、事件和 trace；最后返回可以被页面继续读取的版本化结果。请求体中的 `student_id` 可以保留用于兼容旧前端，但不能覆盖 JWT 得到的当前身份。

## 3.3 一次资源请求的服务端时序

当学习者请求“解释一个知识点并给我练习”时，服务端先把请求转成课程、画像和目标知识点组成的上下文。上下文验证通过后，系统创建 generation task，并用幂等键保证重复提交不会创建两条互相冲突的任务。任务下面按顺序创建诊断、领域生成、证据审核和决策编排四个 task step。

每个 step 都有自己的 Agent run。run 保存角色、版本、输入摘要、状态、开始和结束时间以及公开引用。输入摘要只保存对象 ID、课程版本和知识点 ID，不把私有提示词或完整课程正文写进公开 trace。生成完成后得到 artifact version，审核完成后得到 quality check 和 debate report，决策阶段再根据学习事件和审核结果选择下一步动作。

## 5.2 四类 Agent 的真实契约

诊断 Agent 的必需输入是 `profile_snapshot_id`、`job_task_id` 和目标知识点，允许读取画像和任务，禁止发布资源、声明胜任或覆盖画像。领域生成 Agent 需要画像快照、课程版本、目标知识点和 source_ref，允许创建草稿和追加资源版本，禁止自行发布、修改比赛指标或改变能力类型。证据审核 Agent 接收 artifact version、source_ref 和质量规则版本，输出 claim check、辩论轮次和质量检查，禁止无证据批准。决策编排 Agent 读取审核结果、学习事件和规则版本，输出 decision record 和 matching report，禁止重写证据、把点击当掌握或在没有确认时执行重大路径变化。

这种契约不是文档约定，而是在 `app/m3_agents.py` 中以严格模型保存。模型配置使用 `extra=forbid` 和冻结对象，避免调用方偷偷增加没有经过审核的字段。每个角色的 registry ID 和版本都会进入运行记录，使后续可以区分“同一任务的不同角色运行”和“不同版本的角色运行”。

## 5.3 任务状态、幂等和恢复

M3 任务从 `queued` 进入 `running`，每个角色依次执行，成功后变为 `completed`。失败不会被写成成功，系统保留失败角色、错误码和可重试边界；可恢复任务重新读取已经完成的前置 step 和上下文，避免把已经审核过的资源再生成一遍。相同幂等键如果绑定了不同课程、模型或上下文，服务端返回冲突，而不是静默复用旧结果。

公开 Agent 时间线只呈现阶段名称、状态、耗时和对象引用。真正需要排查时，评委可以从 task ID 找到 run ID，再找到 artifact version、quality check 和 decision record；普通学习者只看到“正在分析”“已生成”“需要补充证据”等可理解的提示。

## 6.2 画像适配器怎样把状态变成控制参数

当前 `build_profile_adaptation` 不直接生成一段泛泛的“适合你”的话，而是把画像投影成可传给资源生成器的控制项。知识点掌握度低于 0.45 时进入 `foundation`，0.45 到 0.72 之间进入 `scaffolded`，达到 0.72 后进入 `transfer`；没有可靠掌握度时，再根据“入门、初学、熟练、高级”等背景文字选择保守默认值。

脚手架强度还会受认知负荷和挫折指数影响。认知负荷达到 0.66 或挫折指数达到 0.5 时，脚手架升为 `high`；进入进阶迁移时通常降为 `light`。互动偏好中的“图、视觉”会选择图示先行，“代码、实操、实践”会选择先给可运行例子，“推导、理论、公式”会选择先给定义和推导。目标和动机会进一步决定案例是项目、考试、岗位还是探索场景。

这些控制项最终落到资源的难度带、内容长度、解释风格、示例上下文、任务开放度和反馈方式。缺少证据时适配器使用中性控制，不凭默认数值编造学习者特征；这也是材料中把派生画像标成“当前数据库快照加引擎投影”的原因。

## 6.3 难度匹配不是一个标签

M3 匹配模块把资源难度拆成六个连续维度：先修深度、概念复杂度、操作步骤、工具复杂度、认知负荷和任务开放度。讲义、实训和分阶测验在这些维度上有不同偏移，例如讲义减少操作步骤和工具复杂度，实训增加步骤、工具和开放度，测验增加概念复杂度和开放度。

系统先从画像能力区间计算推荐难度区间，再将资源难度向量求均值得到 aggregate difficulty。推荐区间同时保存能力中点和不确定性宽度，算法版本固定为 `m3.matching.interval.v1`。因此报告可以解释某个资源为什么“太简单”“可接受挑战”或“太难”，而不是只给一个没有依据的 foundation 或 advanced 标签。

## 7.2 Hybrid RAG 的实际评分

当前课程检索会先把查询扩展为机器学习领域相关表达，再按课程 ID 和版本做范围过滤。候选文本的课程相似度由多个部分组成：嵌入相似度占 0.18，跨语言或视觉文本相似度占 0.18，token Jaccard 占 0.12，查询词覆盖率占 0.32，英文术语词法分数占 0.20；命中 anchor 或 tag 时再增加小幅加分，最终截断到 0 到 1。

查询词由英文数字标识、中文词和相邻中文二元片段组成，适合“混淆矩阵”“反向传播”“tool calling”等混合术语。图谱会先把目标概念扩展到先修和下游节点，再把图谱上下文拼进检索查询；检索结果去重后按得分排序，并保留父文档和章节信息。若最高得分过低或词覆盖不足，`low_confidence` 会被置为真，生成层需要拒答、降级或请求更多信息。

课程检索和个人上传文档是两条不同的可见性路径。课程证据由 canonical course ID 管理，个人文档必须带 owner ID，并在检索和删除时按 owner 过滤。课程范围查询不能被另一门公开课程的高分结果挤出前几名；跨课程探索需要显式允许，不能通过普通学习请求绕过课程边界。

## 8.2 课程摄入和来源链

课程摄入从 manifest 开始。manifest 指出课程 ID、版本、章节文件、知识点和来源角色；解析器读取真实 Markdown、Notebook 转换文本或 PDF 转换文本，保留章节标题、代码块、表格和原文位置。连续正文按段落边界切成不超过 1,200 字的块，块之间保留 source span 和内容哈希，检索时可以回到原文上下文。

source document、chapter、knowledge point、chunk 和 source_ref 组成一条来源链。资源中的 source_ref 不是一个装饰性 URL，而是可以指出课程、章节、文件、字符范围和引用片段的对象。课程版本发生变化时，旧引用不会被静默指向新正文；需要重新摄入、重新生成和重新审核。

## 9.2 资源工厂和版本对象

资源工厂的输出包括 lesson、lab guide、tiered quiz，以及导图、代码、交互模型、费曼复述和视频脚本等对象。每个 artifact 有类型、owner、课程和当前版本；artifact version 保存内容、内容哈希、来源引用、生成任务和审核状态。草稿、审核中、通过、需要修改和拒绝是不同状态，页面不会把草稿当成已经批准的学习材料。

生成过程支持并发，但单个资源失败时可以只标记该资源不可用，保留其他资源和失败原因。证据审核通过后，资源才进入可展示版本；如果只发现某一个 claim 有问题，可以对该 claim 或对应资源返工，不必丢弃整条任务的所有输出。这个设计也让评委能看到系统如何处理部分失败。

## 10.2 当前核心接口如何衔接

课程和来源由 M1 接口读取，包括 `/api/m1/courses/{course_id}`、`/api/m1/courses/{course_id}/outline` 和 `/api/m1/source-refs/{source_ref_id}`；生成任务通过 `/api/m1/generation-tasks` 创建和查询，资源通过 `/api/m1/artifacts` 和版本接口读取。画像、分析、学习路径和建议集中在 `/api/profile/{student_id}` 及其子路径；诊断会话通过 `/api/diagnostic/` 下的 blueprint、session、response 和 report 接口完成。

对话入口 `/api/stream/chat` 返回 SSE 事件，事件里可以出现 Agent 阶段、内容增量、资源、完成和错误。测验由 `/api/quiz/generate`、`/api/quiz/evaluate` 和 `/api/quiz/adapt` 组成；知识库支持课程列表、发现搜索、来源详情和删除；代码状态和执行分别由 `/api/code/status` 与 `/api/code/run` 提供。接口文档的重点不是列满所有路由，而是说明每条业务链如何携带身份、课程、版本和 trace。

## 11.2 代码执行边界

代码执行接口首先检查当前用户和学生范围，再检查语言、代码长度、运行模式和资源权限。当前长度上限为 50,000 字节；`disabled` 模式明确返回不可执行，`trusted_local` 只允许可信本机研究演示，`docker` 模式需要 Docker daemon 和正确配置才能提供容器隔离。Docker 不可用时不回退到宿主高权限执行。

前端通过 `/api/code/status` 显示 mode、execution_enabled、isolation、security_level 和 max_output_bytes。这样评委看到的不是一个模糊的“代码运行成功”，而是当前执行边界。代码历史也按 owner 过滤，不能只凭 URL 中的学生 ID读取。

## 12.2 测试如何覆盖技术链路

静态层检查课程 manifest、路由注册、schema 和敏感字段；单元层检查画像适配、RAG 评分、BKT/MIRT 边界、权限函数和资源版本；集成层检查诊断—画像—资源—反馈的对象衔接；API 层检查状态码、认证、课程范围和幂等冲突；浏览器层检查页面、SSE 时间线和两门课程入口；数据层检查 JSONL 的课程、版本、画像、知识点和 source_ref 是否互相对应。

测试结果必须区分“接口通过”和“比赛指标通过”。当前回归与浏览器结果写入运行记录，11 个旧式 M5 内存夹具的失败保留为夹具限制；三项比赛指标仍要求 claim 级、六维适配级和知识点级复核。没有外部标注人员时，单人内部复核只能作为内部评测责任，不写成专家结论。

## 13.2 异步和可观测性

FastAPI 事件循环内避免同步网络调用和长时间 CPU 计算。资源生成和外部模型请求使用异步路径，CPU 密集型工作进入线程或进程池；客户端断开时，后台任务要能够取消或转为可恢复状态。每个请求和 Agent run 都携带 trace ID，记录开始、结束、错误、耗时、缓存命中和输出版本。

缓存只保存可重新构造的结果，并按用户、课程和版本隔离。课程索引重建、用户删除和版本升级都需要同步清理或重新建立索引。日志只记录脱敏摘要，不能用“日志里有答案”替代资源和来源对象。

## 14.2 安全边界的技术实现

认证采用 JWT 识别当前主体，服务端授权函数负责 owner、角色、课程 membership 和资源可见性。前端路由守卫只能改善体验，不能承担安全职责；所有跨用户读取、跨课程检索、资源生成和学习事件写入都应在后端再次检查。

文档上传需要限制文件类型、大小、页数、压缩包展开体积、压缩比和解析时间；网页来源需要协议、重定向、响应大小和内网地址校验。路径接口使用安全路径解析，防止 `..` 穿越。提交材料只保留脱敏数据、课程来源和最小复现文件，不保留运行数据库、WAL/SHM、密钥或私有推理内容。

## 15.2 评委复现的工程顺序

复现时先检查 Python、Node、npm 和课程目录，再启动后端和前端。先调用 `/api/health`，确认数据库、模型、检索和 sandbox 状态，再登录并选择课程。之后完成诊断、读取画像、请求一项资源、查看 source_ref、提交反馈并刷新路径；任何一步都记录实际状态和 trace。

若外部模型不可用，使用 deterministic 模式验证对象流转；若 Docker 不可用，展示 disabled 或 trusted_local 的明确边界；若 PDF 导出失败，保留 DOCX 和命令日志并把环境限制写入报告。评委看到的是系统在真实环境中的处理方式，包括降级和失败，而不是只展示最顺利的一次路径。
"""

    def insert_body_before_appendix(filename: str, extra: str) -> None:
        """Place reader-facing prose before any review appendix in a document."""
        title, content = docs[filename]
        match = re.search(r"\n# 附录", content)
        if match:
            content = content[:match.start()].rstrip() + "\n\n" + extra.strip() + "\n\n" + content[match.start():].lstrip()
        else:
            content = content.rstrip() + "\n\n" + extra.strip()
        docs[filename] = (title, content)

    # The following sections are deliberately written as explanatory prose.
    # They turn the implementation facts into a paper-like argument: problem,
    # design choice, mechanism, observable behavior, and limitation.
    main_paper_expansion = """
## 1.2 研究对象与设计原则

本项目研究的对象不是一个单独的问答页面，而是学习者状态、课程证据和教学动作之间的动态关系。一个学习者提出“请解释决策树”时，系统必须同时回答三个问题：他现在缺什么先修知识；课程正文中哪一段可以支持解释；解释之后用什么任务确认学习真的发生了。只处理第三个问题会得到一段通顺但不可验证的答案，只处理第二个问题会得到一个检索系统，只处理第一个问题又无法产生可执行的教学动作。EduMatrix 将三者放在同一个任务上下文中。

这一目标带来四项设计原则。第一，事实和教学表达分离，画像可以改变讲解方式、节奏和任务负担，但不能改变课程事实。第二，状态和事件分离，页面浏览、作答、代码测试和复述不能被混成同一种证据。第三，生成和发布分离，候选资源先经过来源检查和版本记录，审核通过后才成为可展示版本。第四，所有影响学习路径的决定都要能够解释输入、规则和后果，不能依赖一个无法追问的总分。

这些原则也决定了系统的边界。当前实现面向两门机器学习与人工智能课程，重点验证课程范围内的个性化生成和多智能体协同，不把有限课程样本外推为通用教育效果。本文把“已经运行的行为”“源码中存在的能力”和“尚待正式评测的指标”分开书写，使读者能够知道哪些结论可以复现。

## 1.3 赛题要求如何转成可验证问题

赛题要求中的“领域知识个性化生成”被拆成三个可观察环节：领域边界是否清楚、资源是否真的随学习者变化、资源中的专业事实是否可以追溯。领域边界由课程 manifest、章节、知识点和来源文件共同定义；个性化由诊断、十维画像、掌握度和适配计划共同定义；可信性由 chunk、source_ref、claim 审核和 artifact 版本共同定义。这样，评委可以从一个资源反向走到画像和课程原文，而不是只凭页面上的个性化标签判断。

“多智能体协同决策”也不能只用角色名称回答。系统为诊断、领域生成、证据审核和决策编排分别规定输入、输出、允许工具和禁止动作，并把每次运行写入任务时间线。协同的证据不是调用次数，而是角色之间是否交接了不同的责任：诊断产出的 skill gap 是否影响生成控制项，生成结果是否交给证据审核，审核结论是否进入下一步决策。

三项指标则被转换为不同的评测对象。幻觉率的对象是事实性 claim，适配准确率的对象是画像和资源之间的六维对应关系，核心知识点覆盖率的对象是知识点及其先修和关键权重。它们不能用页面数量、来源数量或模型自评替代。当前材料因此先给出严格分母和失败规则，再如实保留尚未完成的正式测量。

## 2.2 两门课程的知识组织方式

《机器学习基础与实践》是一条从编程工具走向模型判断的基础路径。Python、NumPy 和 Pandas 解决数据结构与操作问题，探索性分析和数据准备把“能运行代码”推进到“知道数据是否可靠”，监督学习、评估、线性模型、决策树、集成学习、聚类和降维则把算法选择与实验解释连起来。课程中的先修边很重要：没有数据准备和评估意识，直接练习模型调参会把数据泄漏或类别不平衡误认为模型能力。

《人工智能与深度学习：从机器学习基础到大模型智能体》在基础路径上继续向神经网络、Transformer、预训练、大模型、RAG、工具调用和 Agent 协同展开。它不是简单增加术语，而是把“模型如何学习”连接到“系统如何利用模型完成有边界的任务”。例如，RAG 章节要求学习者理解文档切分、召回和证据绑定，Agent 章节要求学习者理解工具选择、状态交接和失败恢复，综合项目则把这些能力放回一个可运行的学习系统。

课程 manifest 记录版本、文件列表、知识点代码和来源角色。系统在选择课程时把课程 ID 和版本写入请求上下文，检索和资源版本也继承这个上下文。这样，学习者从基础课程切换到智能体课程时会重新确认先修，旧课程的资源不会因为标题相似而混入新课程的回答。

## 2.3 课程范围与迁移边界

当前知识库共有两门 canonical course，覆盖机器学习基础、深度学习、大模型、RAG 和 Agent 的连续学习路径。这个范围足以演示“同一学习系统如何在相邻技术领域内迁移”，但不等于覆盖医疗、金融、法律等高风险行业。迁移到新领域时，需要重新提供可再分发的正文、知识点目录、先修关系、诊断题和评测集，不能只替换课程标题。

课程范围还决定了拒答策略。学习者询问课程外概念时，系统可以说明当前课程没有足够来源，或者请求允许的外部材料；它不应从另一门课程的高分片段中悄悄补全答案。课程范围过滤既是检索质量控制，也是权限和知识边界控制。

## 3.4 分层架构的职责划分

系统分为体验层、接口层、学习业务层、证据与 Agent 层、持久化层五个相互约束的部分。体验层负责课程选择、诊断作答、画像阅读、资源展示和反馈提交；接口层负责认证、参数校验、SSE 事件和错误状态；学习业务层负责诊断、掌握度、路径、复习和资源对象；证据与 Agent 层负责检索、生成、审核、匹配和决策；持久化层保存版本化对象、学习事件和可回链来源。

分层并不意味着每层都可以独立改变事实。前端不能越过服务端读取另一位学习者的对象，生成 Agent 不能绕过证据审核直接发布资源，聚合器不能用一次点击覆盖掌握度。接口层的身份和课程上下文贯穿整个调用链，保证同一个对象在页面、数据库和审计记录中指向同一版本。

## 3.5 一次请求的因果链

以“解释反向传播并给我一个练习”为例，请求首先携带当前身份、课程版本、目标知识点和画像快照。服务端校验课程可见性和对象 owner 后，读取先修关系，决定是否需要先补数学或优化基础。检索器再在限定课程范围内召回正文片段，生成 Agent 将证据组织成适合当前掌握度和互动偏好的资源草稿。

随后，证据审核 Agent 把草稿拆成事实性 claim，逐条检查它们是否能回到 source_ref。审核结果会影响资源状态：证据充分的版本可以继续进入决策编排，存在冲突或不确定的版本需要返工、降级或请求更多材料。最终返回的不是一个孤立文本，而是资源版本、来源引用、任务状态和下一步建议。

## 4.2 业务对象为什么必须版本化

画像快照记录某一时点学习者状态，课程版本记录可用知识范围，generation task 记录一次生成意图，Agent run 记录角色交接，artifact version 记录资源内容，learning event 记录学习事实。这些对象共同组成一条时间线。任何一个对象被覆盖，系统就无法回答“学习者当时看到的内容是什么”或“这个决定依据了哪一次反馈”。

版本化还解决了失败处理问题。生成任务可以在证据审核阶段失败，但已经完成的诊断和检索结果仍然有效；资源可以产生新的版本修复一个 claim，而不删除旧版本；课程正文更新后，旧 source_ref 仍指向旧版本，必须重新摄入和审核。版本字段因此不是审计装饰，而是业务恢复的基础。

## 4.3 三组学习者的同题不同解

面对“比较线性分类和决策树”这一目标，视觉型初学者首先需要看到从数据到预测的流程和两个模型的直观差异。系统会降低单回合内容量，先给概念图、短例子和一个可立即回答的小问题，再逐步引入评估指标。若诊断显示 NumPy 或数据切分先修不足，路径会插入补救节点，而不是直接要求完成完整实验。

项目实践型学习者已经熟悉基本代码，但更容易在数据泄漏、参数选择和上线约束上犯错。系统会减少重复定义，提供带输入输出的训练任务、故障排查清单和模型对比表，反馈重点放在“为什么这个结果不能直接上线”。代码测试失败时，事件会区分数据问题、模型问题和环境问题，下一步可能是重做一个小实验，而不是继续增加理论阅读。

理论研究型学习者可能能够推导损失函数，却需要检验结论在数据上的边界。系统会增加假设、推导、复杂度和反例，要求学习者解释某个结论在哪些条件下成立，再用小型实验进行迁移验证。三组学习者共享同一课程 source_ref，差异只发生在资源组织、任务负担和反馈节奏上，这正是系统对个性化的可观察定义。

## 5.4 画像字段的证据语义

画像中的分数不是人格测验的结论，而是当前证据下的教学状态。知识掌握度主要来自诊断和符合规则的学习事件；互动偏好可能来自登记输入和重复选择；认知加工、抗挫力和学习情境如果缺少足够行为证据，就应保留较低置信度或“未观测”状态。每个维度都带 evidence、confidence 和 status，便于区分观察到的事实与引擎推断。

适配器只把画像投影成控制参数，不把控制参数重新写回画像。例如，“需要短回合”是资源生成策略，不等于学习者永远只能接受短内容；一次高负荷任务完成后，系统仍需通过后续事件重新估计状态。这个方向性约束避免了画像标签自我强化。

## 5.5 入学诊断的三种证据

理论诊断关注概念、定义和关系，应用诊断关注把概念用于数据或案例，工程判断诊断关注实现条件、风险和边界。三类题目共同覆盖一个知识点，才能减少“会背定义但不会使用”或“代码跑通但不理解原因”的误判。题目版本、评分规则、知识点和置信度都进入诊断记录。

诊断结果不是一次性分班。系统把答对、答错和自评信心组合成带不确定性的起点，后续再用代码测试、复述、延迟复测等证据更新。答对但信心低的学习者可能先安排解释和复述，答错但能说清推理路径的学习者则可能只补一个关键概念。这样的处理比单一百分数更适合驱动个性化资源。

## 6.4 资源工厂的组成

资源工厂将同一知识目标编译成不同对象：讲义承担概念解释和检查点，训练任务承担步骤、输入输出和完成标准，分阶测验承担从识记到迁移的验证，思维导图承担概念关系，代码练习承担可运行证据，交互实验承担参数变化和结果观察。每种资源都有自己的字段和失败条件，因此可以被路径、复习和反馈继续消费。

资源内容由三类输入共同决定。课程证据决定“教什么”，画像适配决定“怎么教”，路径和时间约束决定“先教哪一段”。生成器可以改变例子的行业语境、解释顺序和任务开放度，但不能凭空增加课程没有支持的专业事实。审核通过后，artifact version 才能进入学习工作区。

## 6.5 决策编排的选择逻辑

决策编排把候选动作放在同一个比较框架中：补先修、降低解释负荷、维持巩固、增加迁移挑战或继续收集证据。每个候选动作都要带依据、预计负担、风险和资源成本。掌握度不足且先修缺口明确时，补先修通常优先；掌握度尚可但迁移证据不足时，增加变式任务比重复讲义更合适；证据冲突时，最合理的动作可能是暂缓判断。

高风险路径变化保留 proposed 状态，需要学习者或教师确认。这样做牺牲了一点自动化速度，却避免系统因为一次异常作答就永久改变课程计划。决策记录还保存未被选中的候选动作，使评委能够理解系统为什么选择当前方案。

## 7.3 可靠性设计不是只看成功路径

系统把失败当作一种结果类型。检索得分过低时，生成层进入低置信度分支；source_ref 缺失时，资源不能直接批准；外部模型不可用时，服务端报告当前模式，而不是假装已经得到同样的模型效果；Docker 不可用时，代码接口保持 disabled 或 trusted_local 的明确边界。

任务状态和资源状态分离，使局部失败可以恢复。某个资源的 claim 审核失败，不必删除同一任务中已经通过的其他资源；网络中断后，可以读取已经完成的 Agent run，避免重复生成。失败记录保留错误码、阶段和重试边界，后续测试可以把失败案例作为证据，而不是把它们从统计中删掉。

## 7.4 可观测性与可解释性

每个请求、任务和 Agent run 都携带 trace ID。公开时间线展示阶段、状态、耗时和对象引用，调试视图再显示输入摘要、版本和错误原因。系统不把私有提示词、完整课程正文或访问令牌写入公开 trace，因此评委既能观察因果链，又不会把内部实现细节误认为产品功能。

可观测性还服务于指标评测。一次资源输出需要能够找到对应课程版本、source_ref、claim 检查和适配计划；一次反馈需要能够找到 learning event、掌握度变化和决策记录。只有这样，错误率或适配得分出现异常时，团队才知道应该修复检索、生成、评分还是数据记录。

## 8.3 从课程正文到知识图谱

课程摄入先读取 manifest，再解析章节标题、正文段落、代码块和表格。知识点代码与章节之间建立映射，先修关系形成有向边。路径规划使用这些边判断“当前目标是否可学”，诊断使用它们选择先修题，资源工厂使用它们决定解释顺序和补救节点。

图谱不是独立于正文的另一套知识。每条边和节点都应能回到课程章节，检索结果仍以正文 chunk 为最终证据。这样可以利用图结构扩大查询上下文，又避免把人工维护的关系当作无需核验的事实。

## 9.3 Hybrid RAG 的取舍

纯关键词检索容易漏掉“反向传播”和 `backpropagation` 这样的中英文表达，纯向量检索又可能把语义相近但不属于当前课程的片段排到前面。当前实现先做领域查询扩展，再按课程、版本和 owner 过滤，之后综合嵌入相似度、跨语言文本相似度、token Jaccard、查询词覆盖率和英文术语词法分数。

检索分数只负责排序，不直接表示答案正确。系统会保存候选的分数、命中的词和来源位置，并在最高分过低或覆盖率不足时设置 low_confidence。生成层必须根据这个状态选择拒答、补充检索或明确不确定性，而不能用更长的文字掩盖证据不足。

## 9.4 Claim 审核如何落到文字

资源生成后，审核器把“监督学习需要训练集和测试集”“准确率在类别不平衡时可能误导”等可验证陈述拆成 claim。每个 claim 绑定 source_ref、字符范围和审核状态。supported 表示来源支持，contradicted 表示与来源冲突，unsupported 表示没有来源，unknown 表示当前证据无法判断。

严格评测把后三种状态都视为错误候选，并把关键知识点 contradiction 视为案例失败。这样的口径会让结果看起来不那么漂亮，却能防止“引用了一个来源，所以整段话都算正确”的宽松统计。正文材料保留审核规则，详细 claim 数据放在独立测试文件中供复核。

## 10.3 视觉型初学者的完整学习回合

该画像的第一步不是直接生成一篇长讲义，而是确认学习者能否区分数据、特征、标签和预测结果。诊断显示某些基础知识点掌握度较低后，画像适配器把难度带设为 foundation，脚手架设为 high，互动顺序设为图示优先。资源工厂因此先生成一张数据流向图、一个短例子和三个即时检查点，再把代码练习拆成可以逐步运行的单元。

学习者在第一个练习中答错并表示没有把握，系统记录低置信度失败事件，暂不推进到复杂模型比较。决策编排选择补先修和复测，新的资源只重复导致错误的概念，不重播已经完成的部分。若复测通过，再把脚手架降到 medium，并加入一个小型变式任务。这个过程展示了画像如何改变资源和路径，而不是只改变欢迎语。

## 10.4 项目实践型学习者的完整学习回合

该画像的目标是完成岗位级评估报告，因此资源重点不在术语数量，而在数据准备、模型比较、评估解释和上线约束。系统读取较高的基础掌握度和代码偏好，把解释样式设为“先给可运行例子，再解释关键机制”，任务开放度保持在可控挑战区间。训练任务会要求学习者比较两个模型，并提交选择理由、指标和风险。

如果隐藏测试发现数据泄漏，反馈事件会被标记为实践证据失败，路径回到数据切分和评估章节。系统不会因为训练脚本成功运行就把掌握度提升到最高，而是等待修复后再次运行和一次口头或书面复述。这样，“能跑通”与“能解释、能交付”被明确区分。

## 10.5 理论研究型学习者的完整学习回合

理论研究型学习者需要看到概念的条件和反例。资源工厂会把定义、推导、复杂度和边界作为主要内容，减少对基础代码环境的重复说明，并提供一个用数据验证理论假设的实验。适配计划可能进入 transfer，但这并不代表所有知识点都已经掌握，而是表示当前目标适合用迁移任务继续验证。

当学习者能正确复述推导，却在新数据上选择了不适合的评估指标时，系统会将问题记录为理解到应用之间的缺口。决策不是把他降回入门，而是安排一个反例比较和一次延迟复测，观察错误是否稳定存在。这样的资源编排保留了挑战性，也避免用理论成绩替代真实应用证据。

## 11.3 Agent 之间如何交接

诊断 Agent 输出的是带证据和不确定性的 skill gap，例如“目标知识点可进入迁移，但评估指标选择缺少应用证据”。领域生成 Agent 不能自行修改这个判断，只能把它转成讲义长度、任务开放度、练习类型和提示策略。证据审核 Agent 接收资源版本和 source_ref，重点检查事实 claim；决策编排 Agent 再把审核结果、学习事件和适配计划放在一起选择下一步。

每次交接都使用结构化对象，包含任务 ID、角色版本、输入摘要和输出版本。某个角色失败时，下游角色不会读取半成品并继续发布，而是看到明确的 failed 或 needs_revision 状态。正是这些交接约束，使“多个 Agent”成为可追踪的协作流程，而不是同一模型被调用多次。

## 12.3 掌握度更新的证据强弱

掌握度更新区分即时作答、连续练习、代码隐藏测试、费曼复述和延迟复测。即时作答可以证明当前题目表现，代码测试可以提供实践证据，复述可以检查理解组织，延迟复测可以检查保持。系统将事件的 evidence_strength、evidence_status 和 mastery_eligible 分开保存，只有符合规则的事件才进入掌握度聚合。

聚合结果还保留不确定性。连续正确但只发生在同一题型上，不能直接得出迁移能力稳定；连续失败但集中在一个先修概念上，也不意味着整个课程都不适合。路径、复习和资源决策因此消费同一组事实事件，而不是各自维护互相矛盾的分数。

## 13.3 反馈闭环的时间结构

反馈闭环至少包含即时反馈、短期补救和延迟验证三个时间尺度。即时反馈告诉学习者当前答案哪里有问题；短期补救安排一个更小、更明确的任务；延迟验证在间隔后用变式题或实践任务检查是否保持。三者分别对应 learning event、path node 和 review item，不会被压成一个“已完成”字段。

复习也会改变下一步决策。一个知识点如果原题正确但变式失败，系统会保持基础解释、增加对比任务；如果延迟复测仍然稳定，则可以减少重复讲义，把时间让给下游知识点。这样，复习是闭环中的决策动作，而不是资源列表中的再次播放。

## 14.3 数据治理和安全边界

身份由服务端 Token 确认，owner 和课程 membership 决定对象可见性。前端路由守卫只负责界面体验，真正的跨用户、跨课程和跨资源校验发生在后端。课程 source_ref 和个人上传文档使用不同的可见性路径，避免一条查询把私有内容带入公开课程上下文。

提交材料只保留脱敏画像、合成或重放测试数据、必要的课程来源和公开阶段摘要。运行数据库、WAL/SHM、凭据、私有提示词和真实学习记录不进入提交包。代码执行默认关闭，外部模型和 Docker 作为可选依赖单独披露，保证评委不会把环境缺失误解为系统静默成功。

## 15.3 部署模式与复现优先级

deterministic 模式用于验证对象流转、页面展示和失败状态，它不代表外部大模型生成质量。external_llm 模式需要评委环境提供 endpoint、model 和 key，结果必须重新审核；trusted_local 适合本机研究演示，不能描述成容器隔离；docker 模式只有在 Docker daemon 和安全配置完整时才进入代码执行验收。

评委复现按“健康检查—课程—诊断—画像—资源—来源—反馈—路径”顺序进行。每一步都记录状态、对象 ID 和 trace，遇到失败先判断是依赖不可用、权限拒绝还是业务校验失败。这个顺序能让评委看到系统在现实条件下如何处理边界，而不只是看到一条剪辑后的成功路径。

## 16.2 三项指标的正式评测设计

幻觉率以冻结数据集中的事实性 claim 为分母。每个 claim 必须有明确文本、课程版本、source_ref 和复核状态，`contradicted`、`unsupported`、`unknown` 均计入错误；只有 supported 才计为正确候选。适配准确率把每个画像—资源样本拆成六维 0/1/2 评分，达到 10/12 且难度、先修不为 0 才算该样本通过。知识点覆盖率按关键知识点权重 2、普通知识点权重 1 计算，并要求覆盖同时满足内容、正确性、深度和证据条件。

这三项指标需要不同的复核表，不能用同一张资源清单代替。评测记录必须固定数据集版本、源码 commit、课程版本、运行模式、样本分母、失败案例和复核责任。当前项目组已允许单人双轮内部复核，但这只能称为内部评测；在没有外部领域标注人员的情况下，不把它包装成独立专家验证。

## 16.3 结果应如何向评委呈现

正式结果表应同时展示目标值、实际分子、实际分母、结果、失败样本和限制。例如，幻觉率不能只写“低于 5%”，还应列出 claim 总数、错误状态分布和一个失败案例；适配准确率不能只写平均分，还应列出三组画像的最差组和失败维度；覆盖率不能只写百分比，还应列出遗漏的关键知识点。

在正式运行尚未完成时，最可信的回答是明确写“未正式测量”，并说明已经准备好的数据、公式和下一步责任。这样不会夸大当前成果，也让评委知道系统已经具备怎样的评测接口。指标通过与否应由冻结数据集上的可复核结果决定，而不是由文档语气决定。

## 17.2 可迁移性与研究价值

EduMatrix 的可迁移部分主要是对象模型和流程约束：课程版本、知识点图谱、source_ref、画像快照、Agent 契约、artifact 版本和学习事件可以迁移到新的领域。不可直接迁移的是课程事实、诊断题、先修关系和评分规则，这些内容必须由新领域重新建立和复核。

从研究角度看，系统把个性化教育中的三个常见断点连接起来：画像不再停留在展示层，RAG 不再只追求召回率，Agent 协同不再只展示角色数量。当前版本仍有指标未正式发布、部分 challenge 未执行和外部模型边界等限制，但这些限制被记录为可执行的后续工作，而不是隐藏在漂亮的成功案例后面。

## 17.3 本次材料的验收口径

本文把系统展示分成三个层次。第一层是评委能够直接看到的产品行为，包括课程选择、入学诊断、画像摘要、资源工作区、Agent 阶段、来源引用和反馈后的路径。第二层是评委可以沿对象 ID 复核的工程事实，包括课程版本、source_ref、artifact version、learning event、任务状态和运行模式。第三层是需要冻结数据集和人工复核才能成立的比赛结论，包括幻觉率、画像—资源适配准确率和核心知识点覆盖率。

这三个层次的证据强度不同，但在同一条业务链中相互连接。页面状态告诉读者发生了什么，对象和版本告诉读者它如何发生，指标明细告诉读者这种行为在一组样本上表现如何。材料不把一张截图当成指标证明，也不把源码中的函数签名当成已经完成的用户实验。

采用这种验收口径，是为了让作品在评审现场经得起追问。评委可以要求展示一个失败任务，查看它是否进入 failed 或 needs_revision；可以抽查一个 claim，回到课程正文；可以询问一个画像维度如何改变资源字段；也可以要求说明三项指标的分母和复核责任。系统的价值不只在于成功时能生成内容，还在于失败时能够说明原因、保留证据并给出下一步。

## 3.6 架构取舍：为什么先做可审计闭环

在系统设计初期，可以把所有能力放在一个大模型调用中：把学习者问题、课程资料和历史记录一次性送入模型，再把返回文本显示给用户。这种方案上线很快，但很难回答三个工程问题。第一，课程资料是否越过了用户和课程边界；第二，回答中的事实是否真的来自当前版本正文；第三，学习者提交反馈后，哪一个状态发生了变化。EduMatrix 选择把调用拆成多个阶段，是因为比赛要求的不只是“能生成”，还包括个性化、协同和可信性。

拆分带来了额外的对象和状态，但也带来了可维护性。诊断 Agent 可以独立调整题型和先修判断，领域生成 Agent 可以替换模板或外部模型，证据审核 Agent 可以加强 claim 规则，决策编排 Agent 可以调整路径策略。一个阶段失败时，其他阶段的结果不会被无条件覆盖。对单机演示而言，这些对象稍显繁琐；对评委复核和后续迭代而言，它们是系统能够解释自己的基础。

当前架构仍然保持轻量。SQLite 负责对象和事件持久化，课程正文以项目内文件和 JSONL 索引提供，deterministic 模式不要求联网。只有在需要外部模型、多人并发或容器代码执行时，才引入额外服务。这种取舍让评委先复现核心链路，再分别验证可选依赖，而不必把所有环境问题混成一个启动失败。

## 4.4 一个请求从输入到反馈的时间线

学习者在 10:00 提交“请解释决策树并给我练习”。10:00:00，前端发送课程 ID、目标知识点、画像快照 ID 和请求幂等键；10:00:01，服务端验证身份、课程范围和目标知识点，生成任务对象；10:00:02，诊断 Agent 读取掌握度和先修图谱，确认学习者需要先处理评估指标的应用缺口；10:00:03，检索器返回当前课程中关于决策树、训练测试划分和泛化的正文片段。

10:00:04，领域生成 Agent 生成一份带流程图、短代码和对比问题的训练资源；10:00:05，证据审核 Agent 检查资源中的事实 claim，并将引用绑定到 source_ref；10:00:06，决策编排 Agent 比较“直接进入模型比较”“先补评估概念”“先收集一次信心证据”三个候选动作，选择先补一个短解释并保留复测。前端只显示阶段摘要和资源状态，详细对象可通过 trace 回查。

10:08，学习者完成小测，答对概念题但在类别不平衡案例中选择了错误指标。系统写入 quiz_answered 事件，实践证据保持为不足，路径新增一个反例比较节点。10:20，学习者完成反例任务并提交解释，系统再写入复测事件；下一次资源请求因此减少定义重复，增加评估指标迁移任务。这个时间线说明反馈不是“弹出一句鼓励”，而是实际改变了后续教学对象。

## 5.6 十维画像的证据矩阵

为避免画像成为一组漂亮标签，系统为每个维度规定证据来源、置信度和可影响字段。知识基础主要来自诊断和掌握度事件，易错点来自错误选项、复述和反馈文本，迁移能力来自变式任务和代码隐藏测试，认知加工方式来自内容负担和完成行为。学习策略来自复习、练习和反馈的组合使用，元认知来自信心与正确性的偏差。

动机与目标优先使用学习者的明确登记，情绪与抗挫力需要连续失败和恢复行为才能逐步估计，互动偏好可以结合登记和媒介选择，学习情境则记录专业、设备、可用时间和课程范围。若一个维度只有默认值，状态应为未观测或低置信度，资源只采用中性策略。系统不从“喜欢代码”推断抗挫力，也不从一次退出推断缺乏动机。

这种矩阵还支持评测。评委可以询问某个维度为什么得到当前状态，材料能够指出来源和置信度；如果维度没有真正影响资源，系统会明确写成“已采集但未接入”，而不是把它计入个性化效果。画像完整性和画像有效性因此被分别讨论。

## 6.6 六维难度匹配的计算过程

资源难度不是一个单值标签，而是由先修深度、概念复杂度、操作步骤、工具复杂度、认知负荷和任务开放度组成的向量。画像侧先根据知识点掌握度和不确定性得到推荐区间，资源侧再根据资源类型计算难度向量。例如，讲义通常降低操作步骤和工具复杂度，训练任务提高步骤和开放度，迁移测验提高概念复杂度和开放度。

匹配模块计算资源向量与推荐区间的距离，并保留每一维的偏差。资源整体均值合适但先修深度超出区间时，结果仍可能判为不匹配；这比把六个维度简单平均更严格。报告中保存 `m3.matching.interval.v1` 算法版本，评委可以看到一个资源被标记为“太难”究竟是因为内容复杂、工具负担还是先修不足。

匹配结果会进入资源生成和决策编排。生成器据此调整段落长度、示例数量和任务开放度，决策器据此判断是否需要补先修或降低首题难度。匹配算法本身不改变专业事实，也不直接决定学习者是否掌握；它只提供教学负担的可解释约束。

## 8.4 课程摄入的一致性检查

课程文件进入知识库时，系统先检查 manifest 中的路径是否存在、文件哈希是否一致、知识点代码是否可解析、先修节点是否存在。解析器再检查章节标题、代码块和表格是否能够转换为连续正文。任何文件缺失、版本不一致或先修边悬空都会进入摄入报告，不能默默生成一个看似完整的索引。

切片完成后，系统对 chunk 数量、字符范围、哈希和 source_ref 数量做一致性检查。每个 chunk 必须有一个 source_ref，每个 source_ref 必须回到一个源文件和章节；字符范围不能超出文件长度，知识点代码必须来自当前 manifest。检查结果写入知识库 README 和数据文件元信息，便于在课程更新后比较差异。

这种摄入流程把知识库维护从一次脚本运行变成了可重复操作。新增章节不会覆盖旧版本，修改正文会导致哈希变化，重新生成资源前可以先检查哪些 source_ref 已失效。对评委而言，这解释了为什么课程版本和来源链会同时出现在资源对象中。

## 9.5 低置信度回答的处理

当查询只包含一个含义模糊的短词，或检索结果的最高分和词覆盖率都很低时，系统将上下文标记为 low_confidence。此时生成器有三种选择：缩小回答范围，只解释能够被当前正文支持的部分；向学习者询问课程、知识点或目标；明确说明课程材料不足，并建议补充允许的来源。三种选择都比编造一个完整答案更符合可信生成的目标。

低置信度也可能来自版本冲突。若资源引用的是旧课程版本，而当前任务指定了新版本，系统不会用标题相同的文本替换引用，而是要求重新摄入和审核。若两门课程都包含相近概念，课程范围过滤优先于相似度排序，避免“相关”被误解为“属于当前课程”。

测试报告把低置信度场景作为挑战案例，检查系统是否拒答、降级或请求补充信息。评委可以用一个课程外问题复现这一分支，观察返回状态和 trace，而不是只看正常问题的生成效果。

## 10.6 资源质量的多层检查

资源质量至少包含结构、事实、适配和可执行四层。结构检查确认讲义有目标和检查点、训练任务有输入输出和完成条件、测验有题目和解析；事实检查确认 claim 有 source_ref 且没有 contradiction；适配检查确认资源符合画像和六维难度区间；可执行检查确认代码、实验或复述任务有明确的提交和反馈入口。

四层检查的责任不同。生成 Agent 负责结构完整，证据审核 Agent 负责事实，匹配与决策模块负责适配，接口和学习事件负责可执行性。一个资源可能事实正确但难度不合适，也可能适配合理但缺少来源；系统需要保留这些差异，而不是只返回一个总分。

## 11.4 Agent 输入输出的可读化

为了让协同过程能够被人理解，系统把每次 Agent run 的输入和输出分成公开摘要和内部内容。公开摘要包含课程版本、画像快照、知识点、状态和对象 ID；内部内容可以包含更详细的提示词和模型上下文，但不进入提交材料。评委看到的是“诊断 Agent 识别了什么缺口，生成 Agent 创建了什么资源，审核 Agent 发现了什么问题，决策 Agent 选择了什么动作”。

结构化对象还规定了失败方式。缺少 profile snapshot 时，诊断阶段返回输入不完整；缺少 source_ref 时，生成阶段只能产生草稿；claim 检查发现 contradiction 时，审核阶段返回 needs_revision；决策所需的学习事件不完整时，编排阶段选择 collect_evidence。每个失败都有可读原因，避免系统以空列表或默认成功状态掩盖异常。

## 12.4 掌握度变化的示例解释

假设学习者在入学诊断中正确回答了“训练集和测试集的区别”，但在应用题中把测试集用于反复调参。系统不会把两个结果平均成“掌握 50%”，而是保留理论正确、应用不足的差异。首轮资源会安排一个数据泄漏反例，并把应用能力标为需要更多证据。

如果学习者随后完成代码任务，程序输出正确但解释仍然错误，事件会增加实践表现证据，却不会直接把理解与迁移能力升到高水平。只有在变式任务或费曼复述中能够说明为什么这样切分数据，系统才会提高相关状态的置信度。这个例子说明掌握度不是一个由单题结果驱动的开关。

## 13.4 复习间隔的编排原则

复习优先级由知识点重要性、最近证据、错误频率、保持风险和可用时间共同决定。关键先修知识点即使只出现一次错误，也可能进入较高优先级；普通知识点如果连续多次稳定通过，则可以延长间隔。复习队列保存触发事件和预期目标，防止同一资源被无理由地反复推送。

复习内容根据失败类型变化。概念混淆适合对照表和辨析题，操作错误适合短代码和检查清单，迁移不足适合变式案例，信心偏差适合自评和复盘。复习完成后仍然产生 learning event，结果可以提高保持置信度，也可以重新暴露问题并触发新的路径动作。

## 14.4 隐私生命周期

学习者数据从输入到删除经历收集、脱敏、使用、导出和清理几个阶段。登记和诊断只收集完成课程所需字段，提交材料使用脱敏 ID；画像快照保留证据来源和版本，但不保留真实联系方式；学习事件只写与教学决策有关的字段；导出时再过滤 token、密码、真实身份和私有文本。

删除或重新生成时，个人文档索引按 owner 清理，课程 canonical source 不与个人数据混用。日志保留追踪所需的时间、状态和哈希，不通过日志恢复完整学习内容。最终提交包排除运行数据库、WAL/SHM、缓存和未审计附件，确保材料本身不会成为隐私泄露渠道。

## 15.4 运维观察项

系统运行期间重点观察任务成功率、失败阶段、重试次数、source_ref 绑定率、unknown claim 数、跨 owner 拒绝数和 sandbox 状态。任务成功率高但 source_ref 绑定率下降，说明生成可能绕过了证据链；页面无错误但学习事件没有写入，说明闭环在接口之后中断；代码请求大量 503，可能只是 disabled 模式而不是学习能力下降。

这些指标用于定位问题，不直接当作比赛效果。运维记录要带版本、模式和时间范围，避免把 deterministic 的一次演示和 external_llm 的另一轮运行混合统计。当前单机部署没有生产级监控服务，材料只说明可观察字段和复现命令，不宣称已经完成高并发运维验收。

## 16.4 指标计算的具体例子

一个冻结资源集合包含 100 条事实性 claim，其中 92 条 supported、4 条 contradicted、3 条 unsupported、1 条 unknown，则严格幻觉率为 `(4+3+1)/100 = 8%`，不能因为 unknown 只有一条就把它忽略。一个画像—资源样本六维得分为 `2、2、2、1、2、1`，总分 10/12 且难度、先修都不为 0，因此该样本通过；若总分为 11 但先修为 0，仍然失败。

知识点覆盖例子中，关键知识点 4 个、普通知识点 6 个，权重总和为 `4×2+6×1=14`。资源正确覆盖 3 个关键知识点和 4 个普通知识点，则覆盖率为 `(3×2+4)/14=71.4%`。这个计算提醒我们，覆盖率高低取决于正确内容和关键权重，不能用提到过多少标题代替。

## 17.4 研究结论的谨慎表述

当前版本可以有把握地说明：两门课程已经被组织为版本化知识库，三组脱敏画像能够生成不同的教学控制，四类 Agent 具有可追踪的责任边界，资源和学习事件能够形成可复现的对象链。当前自动回归、前端构建和两课程浏览器证据也能够证明指定环境下的工程行为。

当前版本不能直接说明三项比赛指标已经达标，也不能说明系统已经在真实用户、外部专家或生产并发环境中验证。正式指标还需要执行冻结 challenge、完成 claim 和六维评分，并由责任人复核。把这些限制写在研究结论里，是为了让作品的技术价值和证据边界同时清楚。
"""

    agent_paper_expansion = """
# 5. 从角色列表到协作协议

多智能体系统的难点不在于把一个模型拆成四个名字，而在于决定每个角色能够看到什么、能够改变什么，以及失败后谁负责处理。EduMatrix 把诊断、领域生成、证据审核和决策编排放在同一条任务链上，但为每个角色设置不同的输入范围和输出责任。诊断 Agent 只负责建立能力缺口；领域生成 Agent 只负责提出资源候选；证据审核 Agent 只负责判断专业陈述能否回链；决策编排 Agent 才负责比较下一步教学动作。

这种分工解决了一个常见问题：生成模型往往能够同时解释、推荐和自我评价，最后却没有任何一项责任可以被单独追问。当前实现将角色运行写入 `DBAgentRun`，保存角色版本、输入摘要、状态和输出版本。评委可以沿 task ID 查看交接顺序，开发者也能判断问题发生在诊断、生成、审核还是决策阶段。

# 6. 诊断 Agent：把答案变成能力缺口

诊断 Agent 的输入包括画像快照、诊断记录、目标知识点和先修图谱。它要识别的不只是“答对或答错”，还包括答题信心、题型维度和知识点关系。例如，同一名学习者可能在理论题上表现良好，却在应用题中无法选择合适的评估指标；输出应当保留这种差异，而不是平均成一个笼统等级。

诊断输出的核心是 skill gap 和不确定性。skill gap 会被下游适配器解释为补先修、增加示例、安排复测或进入迁移任务的理由。诊断 Agent 不得创建已发布资源，也不得覆盖原始诊断记录；这使得它的判断能够被后续事件修正。

# 7. 领域生成 Agent：把证据编排成资源

领域生成 Agent 接收课程版本、知识点、画像控制项和召回的 source_ref。它先选择资源形态，再组织讲义、练习、反馈和检查点的结构。对初学者，结构可能是概念—示例—小题—提示；对项目型学习者，结构可能是任务—输入输出—实验—故障排查；对理论型学习者，结构可能是定义—假设—推导—反例。

生成 Agent 的边界是不能自行批准内容。它只能产生草稿和候选 artifact version，不能把没有来源的陈述标记为 supported，不能修改比赛指标，也不能因为学习者偏好而改变课程事实。资源是否进入工作区由证据审核和状态机共同决定。

# 8. 证据审核 Agent：把“看起来正确”拆开检查

审核 Agent 将资源拆成事实性 claim，并对每条 claim 检查来源、范围、版本和表述强度。它需要区分“来源确实说了这件事”“来源只支持其中一半”“课程正文没有足够信息”三种情况。`unknown` 不等于“模型觉得可能正确”，而是当前材料无法完成判断，因此在严格指标中计为错误候选。

审核结果还决定返工粒度。只有一个 claim 失败时，系统可以保留其他合格内容并对失败片段重新生成；如果关键知识点出现 contradiction，则整条案例失败。这样既不掩盖错误，也避免因为一个局部问题丢失全部可用资源。

# 9. 决策编排 Agent：在多个合理动作中作选择

学习反馈通常不会只指向一个动作。一次低分可能来自先修不足、题目理解错误、环境故障或短期注意力下降。决策编排 Agent 读取学习事件、审核结果、六维匹配报告和当前路径，生成多个候选动作，再按照证据强度、风险、负担和资源成本排序。

决策记录同时保存被选动作和未选动作。例如，系统可能选择“先收集一次延迟复测”，而不是直接降到基础课程，因为当前证据只显示保持性不足，尚不足以证明先修缺口。保留这个比较过程，能让评委理解系统为何没有机械地响应单个错误。

# 10. 状态机、幂等与恢复

任务从 queued 进入 running，再进入 completed 或 failed；中断任务进入 recovery，并读取已完成的前置步骤。幂等键把相同的学习意图绑定到同一任务，若相同键携带了不同课程版本或模型上下文，系统返回冲突而不是静默复用旧结果。

恢复设计的价值在于保护证据链。重新提交不会复制一份没有来源的新资源，已经通过审核的版本不会因为下游决策失败而被删除。失败对象保留错误阶段和可重试范围，评委可以看到系统如何从局部失败恢复，而不是只能看到最终的成功页面。

# 11. 协同过程的可见性

前端 Agent Timeline 只展示学习者能理解的阶段摘要，例如“正在分析先修”“正在生成练习”“正在检查课程来源”“正在安排下一步”。更详细的 trace 只公开对象 ID、版本和状态，不展示私有提示词。这样既能证明阶段交接确实存在，又不会让产品界面变成开发日志。

普通聊天不会自动被描述为完整四阶段协同。只有当任务产生对应的 Agent run、artifact version、审核结果和决策记录时，材料才把它列入协同证据。这一边界保证了文档描述与实际运行记录一致。

# 12. 角色协同的失败案例

一个典型失败是检索得到相似但不属于当前课程的片段。如果没有课程过滤，领域生成 Agent 可能写出流畅答案，审核 Agent 也只能在错误上下文中工作。当前系统在检索前绑定课程和版本，发现候选不满足范围时直接排除；如果剩余证据不足，则返回低置信度状态。

另一个失败是学习者的代码运行环境不可用。决策 Agent 不应把“运行失败”解释成“不会这个知识点”，而应先读取 sandbox 状态，把环境失败与学习证据分开。只有在代码实际执行并通过规定测试后，事件才有资格进入实践掌握度更新。

# 13. 工程创新与可验证性

本项目的多智能体创新主要体现在责任边界和可回放性，而不是角色数量。每个角色的输入、输出、禁止动作和版本都可以在源码和运行记录中找到；角色之间通过任务对象交接，而不是依赖未记录的自然语言上下文。评委可以从一个决策回到它使用的审核结果，再回到资源和课程来源。

这种设计也降低了后续维护成本。替换领域生成模型不会改变诊断和审核接口，调整适配规则不会破坏课程 source_ref，新增一个资源类型只需扩展 artifact schema 和对应的审核规则。系统因此具备在当前两门课程内持续迭代的工程基础。
"""

    personalization_paper_expansion = """
# 5. 个性化不是换标题

个性化学习最容易被误解为给同一篇答案换一个称呼。EduMatrix 采用更严格的判断：如果画像没有改变资源的难度、先修处理、内容长度、脚手架、媒介顺序、任务开放度或反馈节奏，就不能说系统完成了个性化。十维画像的每个维度都要连接到至少一个资源字段或教学动作；暂时没有足够证据接入的维度会标记为未观测，而不是伪造影响。

画像处理采用“登记—诊断—事件—投影”的顺序。登记提供目标、背景和偏好，诊断提供初始知识证据，学习事件提供持续行为证据，适配器把当前状态投影为一次资源请求的控制参数。投影结果不会反向覆盖原始画像，这使得系统可以在新证据到来后重新计算。

# 6. 十维画像的教学含义

知识基础与掌握度决定难度区间和复测优先级；易错点决定反例、辨析题和错因提示；理解与迁移能力决定是否增加变式任务；认知加工方式决定单次内容量和解释拆解；学习策略决定练习、复习和实验的组合。它们共同回答“当前应该教什么”。

元认知决定是否加入信心校准、自评和复盘；动机与目标决定案例使用项目、岗位、考试还是探索语境；情绪与抗挫力决定失败后的提示强度和首题难度；互动偏好决定先展示图示、代码还是推导；学习情境决定时长、设备和任务节奏。它们共同回答“应该怎样让学习者完成”。

# 7. 画像到资源的转换过程

适配器先确定知识点掌握带：低于 0.45 进入 foundation，0.45 到 0.72 进入 scaffolded，达到 0.72 后才考虑 transfer。这个阈值只用于当前资源编排，不是对学习者能力的终身判断。若掌握度证据不足，系统使用保守控制，并把“需要更多证据”作为后续动作。

随后，适配器结合认知负荷、抗挫力和互动偏好计算脚手架和表达顺序。视觉偏好会让图示和流程先出现，代码偏好会让可运行例子先出现，理论偏好会让定义和推导先出现。动机和学习情境再决定案例上下文、任务长度和设备要求。最终生成请求携带的是一组可追踪控制字段，而不是一句泛化的“适合你”。

# 8. 视觉型初学者：从混乱到可操作

视觉型初学者通常不是完全没有兴趣，而是缺少把术语串成流程的框架。系统先通过诊断确认他是否知道样本、特征、标签和预测之间的关系，再选择短段落、图示和即时检查。资源中的每一个概念都配一个可观察的结果，例如改变一个特征后预测如何变化，帮助学习者把抽象定义和操作联系起来。

如果学习者在向量化练习中连续出错，反馈不会简单显示“再试一次”。系统把错误归因到先修概念或操作步骤，插入一个更小的补救任务，并保留原知识点的目标。补救完成后再回到原任务，路径记录这次回退是由哪一个事件触发的。

# 9. 项目实践型学习者：从能运行到能交付

项目实践型学习者重视结果和效率，但容易把脚本运行成功当作方案正确。系统为他安排带数据、指标和故障条件的训练任务，要求说明数据切分、模型选择、指标解释和上线风险。代码练习的完成条件不只包括程序退出成功，还包括隐藏测试、结果范围和解释字段。

当隐藏测试失败时，系统先判断是环境失败、数据问题还是模型判断问题。环境问题不会降低知识掌握度，数据泄漏则会触发数据准备补救，指标选择错误则会安排反例比较。这样，反馈把工程经验转成可以被画像和路径消费的结构化证据。

# 10. 理论研究型学习者：从推导到迁移

理论研究型学习者需要足够的深度，但不意味着应当持续增加公式。系统会把假设、适用条件、复杂度和反例放到资源中心，要求学习者解释一个结论在什么条件下成立，再用小实验验证。若理论回答正确但应用选择错误，画像会把问题标为迁移缺口，而不是把整体掌握度直接降为低水平。

复习任务会选择变式题、边界分析或延迟复测，检验学习者是否能把推导迁移到新数据。只有当多种证据持续支持迁移，系统才会减少基础讲义并增加开放任务。

# 11. 资源类型的差异化生成

讲义、训练任务、分阶测验、思维导图、代码、交互实验和视频脚本共享同一课程证据，但承担不同教学职责。讲义强调可读性和概念顺序，训练任务强调完成条件和故障处理，测验强调证据强度，导图强调关系，代码和实验强调可观察行为。

资源结构也会随画像变化。初学者的讲义包含更多术语解释和检查点，项目型任务包含更多输入输出和参数比较，理论型资源包含更多假设和反例。差异不会改写 source_ref 所支持的事实，只改变事实被组织成学习活动的方式。

# 12. 反馈如何更新画像

系统把测验作答、代码测试、交互实验、费曼复述、复习完成和延迟复测写成不同类型的 learning event。每个事件带证据强度、审核状态和是否允许进入掌握度更新的标记。页面浏览和普通点击只说明接触过资源，不足以提高掌握度。

画像聚合器根据事件序列更新知识点状态和置信度。答对但信心低可能增加元认知复盘，代码通过但复述失败可能保留应用掌握、增加解释任务，延迟复测失败则提高复习优先级。反馈因此改变下一步教学，而不只是显示一个分数。

# 13. 路径与复习的联合编排

路径负责较长的先修和目标关系，复习负责短期保持和间隔安排。一个知识点可以在路径上已经完成，却因为延迟复测失败重新进入复习队列；也可以在复习中表现稳定，但因为下游任务缺少迁移证据而继续保留一个实践节点。两者共享事件事实，但各自保留自己的决策理由。

复习资源不会机械重播原文。系统可以选择一张对照表、一道变式题、一次小实验或一段费曼复述，具体取决于失败类型和画像控制项。这样的编排让“复习”成为重新收集证据的机会。

# 14. 当前个性化能力的边界

三组画像是脱敏重放和当前引擎派生视图，不是外部用户实验。部分维度来自快照推导，部分互动偏好和学习情境仍缺少连续行为证据。材料会把这些字段的来源和置信度写清楚，不能因为输出结构完整就宣称十个维度都已经得到同等强度验证。

当前最可靠的结论是：系统已经把画像字段接入了难度、脚手架、表达和反馈控制，并能在指定数据和环境下复现对象链。画像对真实长期学习效果的影响仍需要更多冻结案例和独立复核。
"""

    knowledge_paper_expansion = """
# 6. 知识库建设的目标

知识库不是把课程文件复制到一个目录，而是为每一次生成提供可回链的证据。系统需要知道某段文字属于哪门课程、哪个版本、哪个章节、哪些知识点，以及它在源文件中的精确位置。只有这样，审核器才能判断一个 claim 是被当前课程支持，还是仅仅与某个相似主题相关。

当前切片保留连续正文、标题、代码和表格上下文。每个 chunk 不超过 1,200 字，长段落被确定性切分，块之间保留字符范围和内容哈希。切片策略优先保证读者在看到一段证据时，仍能理解其上下文，而不是得到一组只有标题和关键词的碎片。

# 7. 课程摄入与版本冻结

摄入从 manifest 开始，解析器读取课程文件并生成章节记录、知识点记录、先修边、chunk 和 source_ref。manifest 的版本和文件哈希会进入每个下游对象。课程更新时，旧版本仍可用于审计，但不会被新版本的资源静默引用。

版本冻结使指标评测具有可重复性。评测数据如果引用了课程正文，必须同时固定课程版本和 source_ref；否则同一个 claim 可能在不同时间指向不同文本，幻觉率和覆盖率就失去可比性。

# 8. 正文切片的实际含义

一个合格 chunk 至少要回答四件事：它来自哪个文件和章节，它覆盖哪些知识点，它在源文件的哪一段，它的内容是否在生成后被改写。当前 JSONL 同时保存 `source_document`、`chapter_id`、`source_span`、`content_sha256` 和 `source_ref_id`，资源引用只保存对象 ID，正文回链再从 source_ref 读取。

这种设计把“引用”从一个网页链接变成了可核查的内部对象。评委可以抽取资源中的一个引用，查询 source_ref，再按照字符范围回到课程文件。即使没有外部网络，仍然能够复核材料内部的一致性。

# 9. Hybrid RAG 的检索步骤

查询进入检索器后，系统先添加领域术语和中英文表达，再根据课程 ID、版本和 owner 做硬过滤。候选排序同时使用嵌入、词法、覆盖率和知识图谱上下文，避免单一算法在混合术语或短查询上失效。命中先修节点时，图谱上下文会提示检索器补充相关基础材料。

候选结果包含得分、命中词、章节和 source_ref。低置信度不是一个最终答案，而是后续生成策略的输入：可以扩大查询、降低回答范围、明确说明材料不足，或请求学习者选择一个课程内目标。检索质量和回答正确性因此被分开评测。

# 10. 生成前后的证据约束

生成前，系统只把通过课程和权限过滤的正文片段放入上下文；生成后，审核器再逐条检查 claim。前置过滤解决“拿错资料”的问题，后置审核解决“把资料说过头”的问题。两者缺一不可：检索正确不保证生成没有夸张，审核严格也不能修复一开始就引用了错误课程。

当来源只支持一个条件性结论时，资源必须保留条件，而不能改写成绝对陈述。当来源之间存在冲突时，审核器把状态标为 contradicted 或 unknown，并要求返工或明确不确定性。严格规则会降低部分回答的流畅度，但提高了评测结果的可解释性。

# 11. 从 claim 到幻觉率

幻觉率的分母是冻结资源中的全部事实性 claim，而不是回答条数或来源条数。一个回答包含十条专业断言，其中两条没有来源，就应当按两条错误候选计算。`unknown` 也不能因为“可能是对的”而从分母删掉，否则结果会被不确定内容系统性美化。

正式复核需要为每条 claim 指定复核状态、来源片段和理由。当前项目采用项目组单人双轮内部复核，第一轮按规则检查，第二轮专门复查 contradiction、unknown 和关键知识点。这个过程可以形成内部严格结果，但不能被称为独立领域专家验证。

# 12. 知识点覆盖的结构化判断

覆盖率不只看资源中是否出现一个知识点名称。一个知识点要被视为正确覆盖，至少需要出现与课程一致的核心内容，达到对应资源的最低深度，并且绑定正确 source_ref。关键知识点使用更高权重，遗漏关键先修时，即使普通知识点覆盖率很高，案例仍可能失败。

覆盖评测从知识点黄金目录生成必需清单，再检查资源内容和引用。这样可以识别“讲了很多外围内容却遗漏关键概念”的情况，也可以把课程图谱中的先修关系纳入解释。

# 13. 许可证与再分发

每个源文件的 manifest 条目记录上游 revision、文件哈希、许可证 SPDX 和许可证文件位置。提交包只纳入授权边界清晰的课程内容和必要的引用信息；无法确认授权的原文不进入最终包。知识库技术本身可以迁移，但课程文本的再分发权不能通过代码自动获得。

# 14. 知识库的当前限制

当前知识库覆盖两门课程，不代表行业全量知识；确定性哈希嵌入用于复现，不代表外部向量模型效果；正文切片证明来源链可用，不等于已经完成三项比赛指标。部分正文来自课程资料的现有版本，若进行正式投稿前发生修改，必须重新生成 chunk、source_ref、资源和指标报告。
"""

    testing_paper_expansion = """
# 8. 测试不是一次性打勾

测试报告的目的不是把所有行标为通过，而是说明系统在哪些条件下可靠、在哪些条件下会拒绝或失败。当前测试分为静态结构、单元行为、集成链路、API 契约、浏览器交互、数据一致性和比赛指标七个层次。每一层回答不同问题：源码是否注册了路由，函数边界是否正确，对象能否串起来，用户是否能完成操作，数据是否能够回链，指标是否有严格分母。

自动测试通过不代表比赛指标通过。例如，画像适配函数的单元测试只能证明阈值逻辑，不能证明真实资源在六个维度上都匹配；RAG 的检索测试只能证明候选排序，不能证明每个生成 claim 都有正确来源。因此报告将接口结果和比赛效果分开记录。

# 9. 测试样本的构成

当前冻结集包含 60 条案例，覆盖两门课程、三组画像和 18 类功能。前 12 条绑定当前数据库演示证据，其他案例保留为待执行或挑战场景。案例字段包含输入目标、课程版本、必需知识点、关键知识点、期望资源、期望难度、期望证据、期望决策和失败原因。

这种样本设计同时覆盖正例和负例。正例检查从诊断到资源和反馈是否能够完成，负例检查课程外提问、低置信度检索、无来源 claim、权限越界、版本冲突和 sandbox 不可用时系统是否拒绝或降级。未执行案例不会被写成通过，仍然保留在分母准备和后续工作清单中。

# 10. 单元与集成测试的边界

单元测试关注画像阈值、匹配区间、RAG 分数、权限函数、版本字段和事件证据等级。集成测试关注诊断—画像—资源—反馈之间的对象衔接，尤其检查一个事件是否能被路径和复习读取，以及一个 artifact 是否能追到 source_ref。

集成链路即使成功，也不意味着外部模型可用。deterministic 模式的价值是让对象流转和失败分支可重复；external_llm 模式仍需要实际 endpoint 和模型配置，结果要重新进行 claim 复核。

# 11. API 与浏览器测试

API 测试覆盖健康检查、认证、课程范围、对象 owner、幂等键、任务状态、SSE 事件、来源查询、测验提交和代码模式。浏览器测试从课程选择开始，依次完成诊断、画像、资源、来源和反馈页面，检查页面错误、控制台错误、HTTP 5xx 和跨课程导航。

浏览器截图只证明截图时的页面状态。为了证明同一条业务链，测试记录还保存对象 ID、trace、时间顺序和服务端状态。页面看起来已经生成资源，不能代替数据库中的 artifact version 和审核结果。

# 12. 幻觉率评测流程

第一步固定资源集合和课程版本，第二步抽取所有事实性 claim，第三步为每个 claim 指定 source_ref，第四步由自动规则做字段和范围预检，第五步由项目组进行两轮人工复核。复核状态只有 supported、contradicted、unsupported 和 unknown，任何无法判断的内容都不得默认算正确。

报告结果时要同时展示分子、分母、错误类型、关键知识点失败数和一条具体失败案例。若使用 deterministic 生成，必须标明这是流程复现结果；若使用外部模型，必须记录模型和运行时间，不能把两种模式的结果混在一个百分比里。

# 13. 适配准确率评测流程

适配评测为每个画像—资源样本建立六维评分表：难度、先修、脚手架、任务复杂度、表达方式和反馈响应。每维 0 表示明显不匹配，1 表示部分匹配，2 表示匹配；总分至少 10/12 且难度、先修不为 0 才算通过。报告需要拆分总体、三组画像、资源类型和最差维度。

评分必须以画像输入和实际资源为准，不能只看生成器的计划字段。项目组单人复核时，第一轮根据规则独立评分，第二轮专门检查是否因为知道期望标签而放宽标准，并保留修改理由。没有外部标注人员时，结论只能称为内部严格评测。

# 14. 知识点覆盖评测流程

覆盖评测先根据课程知识点目录确定必需集合和关键权重，再对每个资源检查内容、正确性、深度和 source_ref。一个知识点即使在标题中出现，如果正文没有解释或引用不对应，也不能计为正确覆盖。先修知识点的遗漏要单独记录，因为它可能让后续核心内容在学习上不可用。

最终结果采用正确覆盖知识点权重总和除以必需知识点权重总和。报告应列出覆盖不足的知识点和失败资源，而不是只保留一个百分比。这样，覆盖率可以指导课程摄入和资源返工。

# 15. 失败案例与当前结果

当前自动回归为 `65 passed, 6 warnings`，前端构建完成，指定两门课程的 Chromium E2E 覆盖 24 个页面，HTTP 5xx、页面错误和控制台错误为 0。11 个旧式 M5 内存夹具因缺少当前课程材料而失败，这个夹具限制已保留，不能被写成产品功能失败或被静默删除。

三项比赛指标尚未正式发布，原因不是没有公式，而是 48 条 challenge 尚未执行，现有资源还需要完成 claim 级、六维适配级和知识点级复核。当前报告因此给出可运行测试结果和指标准备状态两张不同的表，避免把工程回归数字误写成比赛效果数字。

# 16. 评测责任与可复现性

测试数据、运行命令、源码 commit、课程版本、运行模式和复核者都进入报告元数据。项目组单人可以承担内部复核，但需要保留两轮记录、失败案例和修改理由；未来引入外部领域标注时，应在同一冻结集上重新计算，不覆盖旧结果。

可复现的重点不是让所有机器得到完全相同的自然语言，而是让对象边界、课程范围、来源链、状态机和评分规则一致。外部模型存在随机性时，仍应固定模型、参数、时间和证据版本，并把生成差异作为评测记录的一部分。
"""

    deployment_paper_expansion = """
# 7. 部署架构的实际运行关系

评委访问的是浏览器前端，前端通过 API 与 FastAPI 服务通信，后端再访问 SQLite、课程正文和可选模型或沙箱。启动顺序很重要：先确认 Python 依赖和数据库，再启动后端健康检查，最后启动 Vite 前端。这样可以在页面出现之前发现数据库、模型和代码执行模式的问题。

默认部署使用 deterministic 生成、hash embedding 和 disabled sandbox，目标是让课程、诊断、画像、资源和反馈对象能够在没有外部服务的环境下复现。这个默认模式有明确边界：它证明流程和数据契约，不证明真实外部大模型的表达质量或生产吞吐。

# 8. 配置项与安全处理

`.env.example` 只描述配置形状，评委需要在本机生成随机认证密钥；提交材料不包含真实密钥。外部模型的 endpoint、model 和 key 由目标环境注入，健康检查只返回模式和可用性，不返回凭据。课程路径和数据库路径优先使用项目相对位置，避免部署到另一台机器后仍指向开发者目录。

上传和网页来源需要限制文件类型、大小、页数、压缩包展开体积、重定向和内网地址。代码接口先检查语言、长度、运行模式和 owner，Docker 不可用时不回退到宿主高权限执行。日志只保留脱敏摘要、状态、trace 和哈希，不记录 token、密码或完整私有提示词。

# 9. 启动后的验收链

启动后先请求 `/api/health`，确认数据库、课程、模型、检索和 sandbox 状态；再登录并选择一门课程，检查课程 ID 和版本；完成入学诊断后，查看画像快照和掌握度；请求一个带来源的资源，检查 Agent 阶段和 artifact version；最后提交测验或复习事件，确认路径或复习队列发生变化。

每一步都应记录时间、对象 ID 和实际状态。如果页面显示“生成中”，评委可以刷新后端任务状态；如果代码执行返回 503，先查看 sandbox 模式，disabled 下这是预期边界。运行手册把这些检查写出来，是为了让失败也具有可解释性。

# 10. 故障恢复与运维

后端无法连接时，先区分端口未监听、认证失败和课程路径错误；资源生成失败时，沿 task、Agent run 和 artifact version 定位阶段；来源缺失时，检查课程版本、source_ref 和索引是否一致；页面空白时，检查前端构建和 API base URL。每种故障都有对应的最小复现命令。

任务恢复读取已经完成的前置步骤，避免重复写入学习事件和资源版本。课程版本升级需要重建索引并重新审核旧资源的引用。数据库备份和提交包分开管理，最终包不包含运行数据库、WAL/SHM、虚拟环境和 node_modules。

# 11. 评委环境的依赖边界

核心流程只要求 Python 3.11、Node.js 20、npm、SQLite 和项目课程文件。Chromium 只在浏览器 E2E 或 PDF 导出时需要，Docker 只在容器代码执行时需要，外部模型只在 external_llm 模式需要。部署说明把可选服务列为“需单独复核”，避免把环境自动降级误写成同等能力。

# 12. 从本地演示走向部署

当前单机 SQLite 适合评委复现和小规模演示。若进入多人使用，需要把数据库、任务队列、向量索引和对象存储拆分，并增加并发、备份、租户隔离和监控验收。代码执行应优先采用容器或专用沙箱服务，不能因为本地 trusted_local 可运行就直接推断生产安全。
"""

    intro_paper_expansion = """
# 11. 为什么这个作品值得看

EduMatrix 的核心价值不在于把更多内容放进学习页面，而在于把学习过程中最容易断开的几条线连接起来：学习者起点和资源难度之间的线，课程正文和生成答案之间的线，学习反馈和下一步决策之间的线。评委可以从一个学习者的诊断结果出发，看到它如何影响资源，再看到反馈如何改变路径。

系统把“个性化”定义成可观察的字段变化。视觉型初学者得到图示、短回合和高脚手架；项目实践型学习者得到输入输出、故障排查和模型比较；理论研究型学习者得到推导、边界和反例。三组资源共享课程事实，差异来自画像和证据，而不是随意改写专业内容。

# 12. 技术创新一：画像驱动的资源编译

传统学习系统通常在页面上展示画像，资源仍然由固定模板提供。EduMatrix 使用适配器把知识掌握度、易错点、迁移能力、认知加工、学习策略、元认知、动机、抗挫力、互动偏好和学习情境投影成难度、脚手架、内容长度、媒介顺序、任务开放度和反馈方式。

这种“资源编译”让画像的影响可以被检查：输入是什么，控制字段是什么，资源中哪个结构发生了变化。它也保留了事实约束，画像只改变表达和教学动作，不改变 source_ref 所支持的专业结论。

# 13. 技术创新二：带证据的多 Agent 协同

系统没有让一个 Agent 同时担任教师、审核者和路径规划者，而是把责任拆成诊断、领域生成、证据审核和决策编排四个阶段。每个阶段有自己的对象、版本和失败状态，审核结果可以阻止没有来源的资源发布，决策记录可以说明为什么选择补先修或继续收集证据。

这一设计的创新性体现在可回放和可替换。替换生成模型不必重写权限和学习事件，增加资源类型不必改变诊断协议，发生局部错误时可以只返工失败 claim。对评委而言，协同过程不靠动画证明，而靠任务、运行、资源和决策之间的引用证明。

# 14. 技术创新三：课程版本绑定的可信生成

知识库的最小单位不是一个没有上下文的关键词，而是带课程版本、章节、字符范围和哈希的正文 chunk。Hybrid RAG 在课程和权限过滤后召回证据，生成后再拆分 claim 审核。来源不足时，系统选择拒答、降级或请求补充材料，避免以语言流畅度掩盖不确定性。

# 15. 技术创新四：反馈事件驱动的学习决策

测验、代码测试、实验、复述、复习和延迟复测被记录为不同强度的学习事件。事件先写入事实表，再由掌握度、路径和复习模块分别消费。一次点击不会升级掌握度，代码环境失败不会被误判为知识失败，变式任务的结果可以单独改变迁移状态。

这使系统从“一次生成”变成“生成—学习—反馈—再决策”的过程。评委可以看到一个失败事件如何触发补救节点，也可以看到稳定证据如何减少重复讲义并增加迁移挑战。

# 16. 技术创新五：指标与失败一起设计

系统没有把指标留到最后再填数字，而是在数据结构中为 claim、适配维度、知识点权重和失败原因预留位置。幻觉率从 claim 统计，适配准确率从六维评分统计，覆盖率从关键知识点加权统计；unknown、关键知识点 contradiction 和课程外请求都有明确失败规则。

当前三项指标还未正式测量，文档保留这一限制。创新点在于评测对象和证据链已经与产品对象对应，后续运行可以沿同一版本、同一分母和同一复核责任继续完成，而不必重新设计统计口径。
"""

    insert_body_before_appendix("01_作品设计与实现方案.md", main_paper_expansion)
    insert_body_before_appendix("02_作品介绍.md", intro_paper_expansion)
    insert_body_before_appendix("03_多智能体协同决策说明.md", agent_paper_expansion)
    insert_body_before_appendix("04_个性化生成与学习反馈说明.md", personalization_paper_expansion)
    insert_body_before_appendix("05_领域知识库与可信生成说明.md", knowledge_paper_expansion)
    insert_body_before_appendix("06_测试方案与指标报告.md", testing_paper_expansion)
    insert_body_before_appendix("07_系统部署说明.md", deployment_paper_expansion)

    base_main_title, base_main_content = docs["01_作品设计与实现方案.md"]
    if "# 8. 课程内容组织与知识图谱" not in base_main_content:
        docs["01_作品设计与实现方案.md"] = (base_main_title, base_main_content.replace("\n# 附录 E：", body_detail + technical_detail + chapter_extension + "\n# 附录 E：", 1))
    output=[]
    course_table = [["course_id", "version", "title", "知识点", "来源文件"]]
    for course in courses:
        raw = course["raw"]
        course_table.append([raw["course_id"], raw.get("manifest_version"), raw.get("title"), len(raw.get("knowledge_points", [])), len(raw.get("files", []))])
    dimension_table = [["key", "名称", "资源/教学影响"]]
    for key, label, _definition in TEN_DIMENSIONS:
        dimension_table.append([key, label, "已进入 profile_adaptation，或明确标记未接入"])
    test_table = [["类别", "案例数", "状态"]]
    for category in sorted({case["category"] for case in cases}):
        test_table.append([category, sum(case["category"] == category for case in cases), "current_db_evidence / designed_not_run"])
    tables = {
        "01_作品设计与实现方案.md": [("关键课程", course_table), ("十维画像", dimension_table)],
        "06_测试方案与指标报告.md": [("测试分布", test_table)],
    }
    main_tables = [
        ("表 1：课程范围", course_table),
        ("表 2：初始画像字段", [["字段", "含义", "主要来源"], ["background", "学习背景", "入学登记"], ["goal", "学习目标", "入学登记"], ["foundation", "当前基础", "入学登记"], ["difficulty", "主要困难", "入学登记"], ["preference", "学习偏好", "入学登记"]]),
        ("表 3：持续画像维度", dimension_table),
        ("表 4：入学诊断维度", [["dimension", "判断对象", "输出"], ["theory", "概念和原理", "理论掌握"], ["application", "题目和案例", "应用能力"], ["engineering_judgment", "工程边界", "实践判断"]]),
        ("表 5：Agent 角色", [["角色", "输入", "输出", "边界"], ["诊断", "画像/诊断", "skill gap", "不声明胜任"], ["生成", "画像/来源", "资源草稿", "不自发布"], ["审核", "claim/来源", "质量结论", "无证据不批准"], ["决策", "事件/审核", "下一步动作", "不把点击当掌握"]]),
        ("表 6：任务状态", [["状态", "含义", "可执行动作"], ["queued", "等待", "开始"], ["running", "执行中", "心跳/取消"], ["completed", "完成", "读取版本"], ["failed", "失败", "重试或降级"], ["recovery", "恢复", "读取 checkpoint"]]),
        ("表 7：资源类型", [["类型", "用途", "主要字段"], ["handout", "讲义", "outline/examples/miniQuiz"], ["training_task", "实训", "steps/rubric/checkpoints"], ["quiz", "测验", "questions/explanation"], ["mind_map", "关系图", "nodes/relations"], ["code_sandbox", "代码练习", "files/checks/runtime"]]),
        ("表 8：来源对象", [["对象", "身份字段", "用途"], ["source_document", "course/filename/hash", "原始正文"], ["source_ref", "document/location/quote", "引用回跳"], ["chunk", "chunk_id/span/hash", "检索上下文"], ["artifact_version", "version/hash/source_refs", "资源版本"]]),
        ("表 9：学习事件", [["事件", "证据", "反馈"], ["quiz_answered", "作答结果", "掌握度/错题"], ["code_tests_passed", "隐藏测试", "实践证据"], ["feynman_submitted", "复述评分", "迁移状态"], ["review_completed", "复习结果", "复习队列"]]),
        ("表 10：画像到资源", [["画像信号", "资源控制", "示例"], ["掌握度", "难度带", "foundation/transfer"], ["认知负荷", "内容量", "短回合"], ["互动偏好", "媒介排序", "图示/代码"], ["动机", "案例上下文", "项目/考试"]]),
        ("表 11：画像到教学", [["画像信号", "教学动作", "需确认"], ["先修缺口", "插入补救节点", "高风险需确认"], ["抗挫力", "降低首题难度", "不改变事实标准"], ["元认知", "增加自评复盘", "保留原始结果"]]),
        ("表 12：RAG 流程", [["步骤", "输入", "输出"], ["解析", "正文文件", "结构化章节"], ["分块", "章节文本", "chunk"], ["召回", "查询", "候选证据"], ["过滤", "owner/course/version", "可用证据"], ["生成", "证据/画像", "资源草稿"]]),
        ("表 13：Claim 状态", [["状态", "含义", "指标处理"], ["supported", "来源支持", "正确候选"], ["contradicted", "来源冲突", "错误"], ["unsupported", "无来源支持", "错误"], ["unknown", "无法判断", "保守计错"]]),
        ("表 14：适配评分", [["维度", "0 分", "1 分", "2 分"], ["难度", "明显不匹配", "部分匹配", "匹配"], ["先修", "未处理", "部分处理", "处理"], ["脚手架", "缺失", "不完整", "合适"], ["反馈", "忽略", "部分利用", "明确利用"]]),
        ("表 15：覆盖判定", [["条件", "必须满足"], ["内容", "明确提到知识点"], ["正确性", "与来源一致"], ["深度", "达到案例最低要求"], ["证据", "绑定正确 source_ref"], ["关键点", "不能遗漏或错误"]]),
        ("表 16：权限边界", [["边界", "服务端控制"], ["身份", "JWT 当前用户"], ["对象", "owner_public_id"], ["课程", "membership/course scope"], ["来源", "课程可见性"], ["日志", "脱敏摘要"]]),
        ("表 17：部署组件", [["组件", "默认", "验证"], ["Python", "3.11", "import/pytest"], ["Node", "20 LTS", "npm build"], ["LLM", "deterministic", "health"], ["sandbox", "disabled", "status API"], ["DB", "SQLite", "integrity"]]),
        ("表 18：运行验证", [["验证", "结果", "限制"], ["回归测试", "65 passed, 6 warnings", "11 个旧式夹具失败"], ["前端构建", "5453 modules", "大 chunk 警告"], ["核心 E2E", "通过", "指定演示账号"], ["两课程 E2E", "24 页面", "导航取消请求"]]),
        ("表 19：测试案例分层", [["层级", "案例数", "目的"], ["数据契约预检", "60", "字段和引用完整"], ["当前 DB 证据", "12", "可追溯对象"], ["challenge", "18", "负例和边界"], ["未执行", "48", "后续运行"]]),
        ("表 20：指标发布门槛", [["指标", "目标", "当前状态"], ["幻觉率", "<5%", "未正式测量"], ["适配准确率", ">=85%", "未正式测量"], ["知识点覆盖率", ">=90%", "未正式测量"], ["外部复核", "独立责任", "当前不可用"]]),
        ("表 21：材料边界", [["材料", "本轮状态", "后续"], ["文档", "已重建", "继续校对"], ["测试数据", "已重建", "扩展执行"], ["PPT", "未生成", "单独制作"], ["视频", "未接入", "用户提供"], ["报名表", "未接入", "用户提供"], ["最终包", "未生成", "统一组包"]]),
    ]
    tables["01_作品设计与实现方案.md"] = main_tables
    tables["00_材料总览与阅读顺序.md"] = [("材料核对矩阵", [["层次", "主要文件", "评审动作"], ["事实", "AUDIT_FACTS/EVIDENCE_INDEX", "核对版本和证据路径"], ["设计", "01/03/04/05", "理解闭环和角色边界"], ["验证", "06/test_data", "复核样本、公式和失败"], ["复现", "07/08/10", "按命令启动并操作"], ["治理", "09/11/12", "检查隐私、授权和限制"]])]
    tables["02_作品介绍.md"] = [("三类学习者对比", [["画像", "起点", "资源控制", "反馈动作"], ["视觉型初学者", "先修缺口较多", "图示、短段落、高脚手架", "失败后补先修并复测"], ["项目实践型", "概念可用但迁移不足", "训练任务、代码、故障排查", "按测试结果增加变式"], ["理论研究型", "理论强、应用需验证", "推导、边界、反例", "进入迁移挑战"]])]
    tables["07_系统部署说明.md"] = [("部署模式矩阵", [["模式", "默认", "外部依赖", "可声明范围"], ["deterministic", "是", "无外部模型", "流程可复现"], ["external_llm", "否", "endpoint/model/key", "需现场复核"], ["trusted_local", "否", "本机子进程", "研究边界"], ["docker", "否", "Docker daemon", "容器隔离需单独验收"]]), ("启动验收点", [["阶段", "检查", "证据"], ["后端", "/api/health", "HTTP 和组件状态"], ["课程", "manifest/正文", "课程 ID 和版本"], ["画像", "诊断/十维", "profile snapshot"], ["闭环", "事件/路径", "learning_event 和 decision"]])]
    tables["08_评委运行与演示手册.md"] = [("演示段落计时", [["段落", "目标", "建议时长"], ["课程与诊断", "展示范围和起点", "1.5 分钟"], ["画像与适配", "展示十维影响", "2 分钟"], ["Agent 与 RAG", "展示协同和来源", "2.5 分钟"], ["资源与反馈", "展示闭环更新", "2.5 分钟"], ["边界说明", "展示失败和模式", "1.5 分钟"]])]
    tables["09_数据合规与授权说明.md"] = [("数据处理控制", [["对象", "材料处理", "禁止内容"], ["画像/诊断", "脱敏重放或合成", "真实身份和联系方式"], ["课程正文", "保留来源和哈希", "授权不明原文"], ["Agent trace", "公开阶段摘要", "私有提示词和密钥"], ["数据库", "导出最小 JSONL", "运行 DB/WAL/SHM"]])]
    tables["10_源码结构与复现说明.md"] = [("模块复现索引", [["能力", "主要入口", "复核产物"], ["课程", "data/curated、course API", "course_catalog/chunks"], ["画像", "profile_onboarding/summary", "learner_profiles"], ["Agent", "m3_agents/debate/decisions", "trace 和资源"], ["学习反馈", "m5_learning/aggregation", "learning_events"], ["测试", "tests/scripts", "CURRENT_TEST_RUN"]])]
    tables["11_当前实现与赛题要求逐项对应表.md"] = [("状态定义", [["状态", "含义", "可否作为比赛结论"], ["已验证", "有当前命令或对象证据", "仅限对应范围"], ["结构已存在", "源码可定位", "不可单独作为运行结论"], ["未正式测量", "尚未完成严格评分", "不可宣称达标"], ["未接入", "后续材料缺失", "不能写成已提交"]])]
    tables["12_系统限制、风险与未完成能力.md"] = [("风险登记", [["风险", "当前表现", "处置"], ["知识错误", "unknown/unsupported 可能存在", "来源审核和保守计错"], ["画像偏差", "脱敏派生视图", "标注来源和置信度"], ["运行依赖", "外部模型/Docker 可选", "模式矩阵和现场复核"], ["测试缺口", "48 条 challenge 未执行", "隔离运行并补 trace"], ["夹具失败", "11 项旧式 M5", "补课程前置或迁移 fixture"]])]
    tables["13_API与数据字典.md"] = [("核心业务接口", [["业务链", "接口", "关键返回"], ["课程", "GET /api/m1/courses/{course_id}", "课程版本和状态"], ["诊断", "POST /api/diagnostic/sessions/{id}/submit", "作答与能力状态"], ["画像", "GET /api/profile/{student_id}", "十维画像和掌握度"], ["生成", "POST /api/stream/chat", "SSE、资源和阶段状态"], ["来源", "GET /api/m1/source-refs/{source_ref_id}", "引用片段和哈希"], ["反馈", "POST /api/quiz/evaluate", "结果和 learning event"], ["沙箱", "GET /api/code/status", "模式和隔离边界"]]), ("核心对象字段", [["对象", "字段", "用途"], ["DBCourse", "id/version/status", "课程范围"], ["DBProfileSnapshot", "owner/snapshot/trace", "画像快照"], ["DBGenerationTask", "capability/idempotency_key", "任务身份"], ["DBAgentRun", "role/status/input_summary", "Agent 阶段"], ["DBArtifactVersion", "version/content/source_refs", "资源版本"], ["DBLearningEvent", "event_type/evidence_status", "反馈事实"]])]
    tables["14_需求实现测试追踪矩阵.md"] = [("需求追踪摘要", [["能力", "实现", "验证状态"], ["垂直知识库", "两门 canonical course", "当前课程和来源已核对"], ["个性化", "诊断、掌握度、十维适配", "三组脱敏样例"], ["多 Agent", "四类 M3 契约", "结构和部分运行证据"], ["可信生成", "Hybrid RAG、source_ref、claim", "指标待正式测量"], ["反馈闭环", "learning event、路径、复习", "当前事件和页面入口"], ["安全", "JWT、owner、sandbox", "选定矩阵通过"]])]
    tables["15_公开依据与引用清单.md"] = [("依据等级", [["等级", "内容", "能证明什么"], ["A", "命令、HTTP、截图、数据库", "指定运行状态"], ["B", "源码、schema、路由", "结构存在"], ["C", "设计和材料说明", "设计意图"], ["D", "规划、目标、未执行案例", "后续工作"]]), ("当前引用范围", [["范围", "来源", "边界"], ["课程", "两门 canonical manifest", "不代表全行业"], ["源码", "当前工作树模块", "需结合运行证据"], ["测试", "当前命令和报告", "只覆盖选定范围"], ["第三方", "license_records", "授权不明不再分发"]])]
    tables["03_多智能体协同决策说明.md"] = [("Agent 责任矩阵", [["阶段", "输入证据", "输出对象", "失败边界"], ["诊断", "诊断/画像/掌握度", "skill_gap", "不直接声明胜任"], ["生成", "课程 chunk/source_ref", "artifact 草稿", "无证据不发布"], ["审核", "claim/版本/来源", "review 结论", "冲突则返工"], ["决策", "事件/审核/匹配", "decision_record", "高风险需确认"]])]
    tables["04_个性化生成与学习反馈说明.md"] = [("画像控制字段", [["信号", "资源字段", "教学动作"], ["掌握度", "difficulty_band", "补先修/复测"], ["认知加工", "content_length/scaffold", "短回合拆解"], ["互动偏好", "media_order", "图示/代码优先"], ["抗挫力", "first_task/prompt", "失败后降阶"], ["学习情境", "duration/device", "调整任务负担"]])]
    tables["05_领域知识库与可信生成说明.md"] = [("知识库对象链", [["对象", "关键字段", "审计意义"], ["chapter", "course/version/path", "章节范围"], ["knowledge_point", "code/prerequisites", "先修和覆盖"], ["chunk", "id/span/hash", "正文检索"], ["source_ref", "document/quote", "引用回链"], ["artifact_version", "content/source_refs", "生成版本"]])]
    tables["06_测试方案与指标报告.md"].append(("指标复核角色", [["角色", "职责", "当前状态"], ["自动规则", "字段、版本、引用预检", "60/60 契约通过"], ["项目组复核", "claim/适配/覆盖双轮检查", "待正式运行"], ["外部标注", "独立领域判断", "当前不可用"]]))
    # Normalize the main document structure after all prose and appendices
    # have been assembled.  Earlier builders add appendices before the later
    # technical chapters, so position-based slicing can leave 1.x sections
    # stranded between appendices.  Parse every top-level block, collect all
    # numeric subsections, and emit chapters 1-17 followed by appendices.
    main_title, main_content = docs["01_作品设计与实现方案.md"]
    top_level = list(re.finditer(r"^# [^\n]*$", main_content, re.MULTILINE))
    if top_level:
        blocks: list[tuple[str, str]] = []
        for index, heading_match in enumerate(top_level):
            start = heading_match.start()
            end = top_level[index + 1].start() if index + 1 < len(top_level) else len(main_content)
            blocks.append((heading_match.group(0).strip(), main_content[start:end].strip()))

        subsection_blocks: dict[int, list[tuple[int, str]]] = {number: [] for number in range(1, 18)}
        subsection_pattern = re.compile(
            r"^## (\d+)\.(\d+) [^\n]*\n.*?(?=^## |^# |\Z)",
            re.MULTILINE | re.DOTALL,
        )
        for subsection_match in subsection_pattern.finditer(main_content):
            parent = int(subsection_match.group(1))
            ordinal = int(subsection_match.group(2))
            if 1 <= parent <= 17:
                subsection_blocks.setdefault(parent, []).append((ordinal, subsection_match.group(0).strip()))

        chapter_blocks: dict[int, str] = {}
        appendix_blocks: list[str] = []
        opening_blocks: list[str] = []
        chapter_heading_pattern = re.compile(r"^# (\d+)\. [^\n]*$")
        for heading, block in blocks:
            chapter_match = chapter_heading_pattern.match(heading)
            appendix_match = re.match(r"^# 附录 [A-Z]：", heading)
            if chapter_match:
                number = int(chapter_match.group(1))
                if 1 <= number <= 17:
                    # Remove any numeric subsections already nested in this
                    # block before appending the globally collected copies.
                    body = subsection_pattern.sub("", block).strip()
                    chapter_blocks[number] = body
                else:
                    opening_blocks.append(block)
            elif appendix_match:
                # Numeric technical sections may have been appended before a
                # later top-level chapter and therefore live inside an
                # appendix block in the raw assembled text. They are emitted
                # under their numbered parent chapters above, never duplicated
                # inside an appendix.
                appendix_blocks.append(subsection_pattern.sub("", block).strip())
            else:
                opening_blocks.append(block)

        ordered_chapters: list[str] = []
        for number in range(1, 18):
            chapter = chapter_blocks.get(number)
            if chapter:
                ordered_chapters.append(chapter)
                ordered_chapters.extend(
                    subsection
                    for _ordinal, subsection in sorted(subsection_blocks.get(number, []), key=lambda item: item[0])
                )
        if len(chapter_blocks) == 17:
            normalized = "\n\n".join(opening_blocks + ordered_chapters + appendix_blocks)
            docs["01_作品设计与实现方案.md"] = (main_title, normalized)
    for filename,(title,content) in docs.items():
        md=DOCS/filename; md.parent.mkdir(parents=True,exist_ok=True); md.write_text(content.strip()+"\n",encoding="utf-8"); output.append(md)
        figure_map = {
            "01_作品设计与实现方案.md": figures,
            "02_作品介绍.md": figures[0:4],
            "03_多智能体协同决策说明.md": figures[1:5],
            "04_个性化生成与学习反馈说明.md": figures[4:8],
            "05_领域知识库与可信生成说明.md": figures[2:6],
            "06_测试方案与指标报告.md": figures[8:12],
            "07_系统部署说明.md": figures[6:10],
            "08_评委运行与演示手册.md": figures[0:2],
            "09_数据合规与授权说明.md": figures[4:6],
            "10_源码结构与复现说明.md": figures[8:10],
            "11_当前实现与赛题要求逐项对应表.md": figures[0:2],
            "12_系统限制、风险与未完成能力.md": figures[8:10],
            "13_API与数据字典.md": figures[5:9],
            "14_需求实现测试追踪矩阵.md": figures[8:10],
            "15_公开依据与引用清单.md": figures[3:5],
        }
        docx=DOCS/filename.replace(".md",".docx"); docx_from_markdown(title,content,docx,figure_map.get(filename),tables.get(filename)); output.append(docx)
    return output


def main() -> None:
    for path in (DOCS, DATA, FIGURES, EVIDENCE): path.mkdir(parents=True,exist_ok=True)
    courses=course_manifests(); kb=build_knowledge_data(courses); profile_data=extract_profiles_and_resources()
    course_versions={c["raw"]["course_id"]: c["raw"].get("manifest_version", "") for c in courses}
    for profile in profile_data["profiles"]:
        profile["course_version"] = course_versions.get(profile["course_id"], profile.get("course_version", ""))
    figures=draw_figures(); screenshots=collect_current_screenshots(); cases=build_cases(kb,profile_data["profiles"],profile_data)
    doc_files = build_documents(courses, kb, profile_data, cases, figures + screenshots, {"git_commit": git_value("rev-parse", "HEAD"), "python": "Python 3.11.x", "node": "Node.js current"})
    (DATA/"learner_profiles.json").write_text(json.dumps({"data_label":"脱敏重放和当前引擎派生视图","profiles":profile_data["profiles"]},ensure_ascii=False,indent=2),encoding="utf-8")
    fresh_adaptations = extract_profiles_and_resources().get("profile_adaptations", profile_data.get("profile_adaptations", []))
    (DATA/"profile_adaptation_outputs.json").write_text(json.dumps({"data_label":"由当前 app/profile_adaptation.py 对当前快照派生的教学控制","outputs":fresh_adaptations},ensure_ascii=False,indent=2),encoding="utf-8")
    write_jsonl(DATA/"resources.jsonl",profile_data["resources"]); write_jsonl(DATA/"learning_events.jsonl",profile_data["events"]); write_jsonl(DATA/"entrance_diagnostics.jsonl",profile_data["diagnostics"]); write_jsonl(DATA/"db_source_refs.jsonl",profile_data["db_source_refs"]); write_jsonl(DATA/"test_cases.jsonl",cases); write_jsonl(DATA/"hard_cases.jsonl",[x for x in cases if x["difficulty"]=="challenge"])
    canonical_course_versions = {c["raw"]["course_id"]: c["raw"].get("manifest_version", "") for c in courses}
    known_profile_ids = {p["profile_id"] for p in profile_data["profiles"]}
    known_kp_ids = {kp["knowledge_point_id"] for kp in kb["knowledge_points"]}
    known_ref_ids = {ref["source_ref_id"] for ref in kb["refs"]}
    preflight_records = []
    for case in cases:
        checks = {
            "canonical_course": case["course_id"] in canonical_course_versions,
            "course_version_matches_manifest": case.get("course_version") == canonical_course_versions.get(case["course_id"]),
            "profile_present": case["profile_id"] in known_profile_ids,
            "required_kp_ids_present": all(kp in known_kp_ids for kp in case.get("required_knowledge_points", [])),
            "critical_kp_ids_present": all(kp in known_kp_ids for kp in case.get("critical_knowledge_points", [])),
            "expected_refs_present": all(ref in known_ref_ids for ref in case.get("expected_evidence", [])),
            "challenge_reason_present": case["difficulty"] != "challenge" or bool(case.get("failure_reason")),
        }
        preflight_records.append({"case_id": case["case_id"], "preflight_status": "pass" if all(checks.values()) else "fail", "checks": checks, "is_business_execution": False, "note": "contract/data preflight only; does not prove product runtime behavior"})
    write_jsonl(DATA/"case_contract_preflight.jsonl", preflight_records)
    execution_records = []
    for case in cases:
        if case["actual_execution_status"] == "current_db_evidence":
            execution_records.append({"case_id": case["case_id"], "status": "executed_against_current_db_snapshot", "evidence": ["test_data/resources.jsonl", "test_data/learning_events.jsonl", "test_data/entrance_diagnostics.jsonl", "test_data/db_source_refs.jsonl"], "result": "evidence_present; case-specific correctness still requires the declared rubric", "automated_assertions": ["course_id is in canonical two-course set", "expected evidence references exist in exported source records", "profile reference exists", "actual resource/event records are traceable"]})
        else:
            execution_records.append({"case_id": case["case_id"], "status": "not_executed", "evidence": [], "result": None, "automated_assertions": [], "reason": "challenge scenario is frozen for a later run; no actual product output is claimed"})
    write_jsonl(DATA/"case_execution_records.jsonl", execution_records)
    with (DATA/"test_case_index.csv").open("w",encoding="utf-8-sig",newline="") as f:
        writer=csv.DictWriter(f,fieldnames=["case_id","course_id","profile_id","category","difficulty","actual_execution_status"]); writer.writeheader(); writer.writerows({k:x[k] for k in writer.fieldnames} for x in cases)
    metric={"status":"internal_strict_design_not_formally_published","external_domain_annotators":False,"sample_count":60,"profile_count":3,"course_count":2,"challenge_count":18,"hallucination":{"formula":"(contradicted + unsupported + unknown) / all factual claims","unknown_counts_as_error":True,"target":"<5%"},"adaptation":{"dimensions":["difficulty","prerequisite","scaffolding","task_complexity","expression","feedback_response"],"pass_rule":">=10/12 and no critical dimension is 0","target":">=85%"},"coverage":{"weights":{"critical":2,"ordinary":1},"formula":"covered weighted points / required weighted points","target":">=90%"},"note":"No result is claimed until current outputs are scored and internally reviewed; internal review is not independent expert validation."}
    (DATA/"metric_calculation.json").write_text(json.dumps(metric,ensure_ascii=False,indent=2),encoding="utf-8")
    def contains_source_refs(value: Any) -> bool:
        if isinstance(value, dict):
            return any(contains_source_refs(item) for item in value.values()) or any("source" in str(key).lower() and bool(value.get(key)) for key in value)
        if isinstance(value, list):
            return any(contains_source_refs(item) for item in value)
        return False
    structural_metrics = {
        "scope": "current database demo objects and rebuilt course corpus",
        "profiles_complete": {"numerator": sum(bool(p.get("mastery_snapshot", {}).get("concept_mastery")) and len(p.get("ten_dimensions", [])) == 10 for p in profile_data["profiles"]), "denominator": len(profile_data["profiles"])},
        "diagnostic_records_exported": len(profile_data["diagnostics"]),
        "resources_exported": len(profile_data["resources"]),
        "resources_with_nested_source_refs": sum(contains_source_refs(r.get("content")) for r in profile_data["resources"]),
        "learning_events_exported": len(profile_data["events"]),
        "database_source_refs_exported": len(profile_data["db_source_refs"]),
        "course_text_chunks": len(kb["chunks"]),
        "test_cases_current_db_evidence": sum(x["actual_execution_status"] == "current_db_evidence" for x in cases),
        "test_cases_designed_not_run": sum(x["actual_execution_status"] == "designed_not_run" for x in cases),
        "test_case_contract_preflight": {"passed": sum(x["preflight_status"] == "pass" for x in preflight_records), "total": len(preflight_records), "is_runtime_evidence": False},
        "official_metrics": "not_formally_measured",
        "interpretation": "Structural completeness is not a correctness or learning-effectiveness metric.",
    }
    (DATA/"structural_metrics.json").write_text(json.dumps(structural_metrics,ensure_ascii=False,indent=2),encoding="utf-8")
    audit={"generated_at":ts(),"git_commit":git_value("rev-parse","HEAD"),"python":subprocess.run([str(ROOT/'.venv/Scripts/python.exe'),'--version'],capture_output=True,text=True).stdout.strip(),"node":subprocess.run(['node','--version'],capture_output=True,text=True).stdout.strip(),"courses":[{"course_id":c["raw"]["course_id"],"version":c["raw"].get("manifest_version"),"title":c["raw"].get("title"),"knowledge_points":len(c["raw"].get("knowledge_points",[])),"source_files":len(c["raw"].get("files",[]))} for c in courses],"profiles":len(profile_data["profiles"]),"ten_dimensions":len(TEN_DIMENSIONS),"diagnostic_dimensions":list(DIAGNOSTIC_KINDS),"knowledge":{"chapters":len(kb["chapters"]),"knowledge_points":len(kb["knowledge_points"]),"chunks":len(kb["chunks"]),"source_refs":len(kb["refs"]),"db_source_refs":len(profile_data["db_source_refs"])},"resources":len(profile_data["resources"]),"learning_events":len(profile_data["events"]),"diagnostic_records":len(profile_data["diagnostics"]),"test_cases":len(cases),"challenge_cases":sum(x["difficulty"]=="challenge" for x in cases),"runtime_evidence":{"focused_regression":"65 passed, 6 warnings; 11 legacy M5 in-memory fixture failures due missing usable course material","frontend_build":"passed; 5453 modules transformed","no_docker_e2e":"passed; 4 screenshots","two_course_e2e":"passed; 24 pages/screenshots; HTTP 5xx/page/console errors 0; 8 navigation aborts"},"metrics":"not formally measured; no external domain annotators","ppt_generated":False,"video_attached":False,"registration_form_attached":False,"final_zip_generated":False}
    audit_md=f"""# 当前重建审计报告

生成时间：`{audit['generated_at']}`  
Git commit：`{audit['git_commit']}`  
Python：`{audit['python']}`  
Node.js：`{audit['node']}`

## 当前课程

{chr(10).join(f"- `{c['course_id']}` / `{c['version']}`：{c['title']}；{c['knowledge_points']} 个知识点、{c['source_files']} 个来源文件。" for c in audit['courses'])}

## 画像和诊断

- 学习者样例：{audit['profiles']} 组；每组 10 个持续画像维度。
- 入学诊断维度：`{', '.join(audit['diagnostic_dimensions'])}`。
- 三组样例均从当前数据库快照脱敏派生，并保留来源快照 ID、掌握度和画像证据。

## 知识库重建

- 章节：{audit['knowledge']['chapters']}；知识点：{audit['knowledge']['knowledge_points']}；正文分块：{audit['knowledge']['chunks']}；source_ref：{audit['knowledge']['source_refs']}。
- 每个分块包含源文件、课程版本、字符范围、内容哈希和可回链引用。

## 当前运行证据

- 关键回归：`{audit['runtime_evidence']['focused_regression']}`。
- 前端构建：`{audit['runtime_evidence']['frontend_build']}`。
- 无 Docker E2E：`{audit['runtime_evidence']['no_docker_e2e']}`。
- 两课程浏览器 E2E：`{audit['runtime_evidence']['two_course_e2e']}`。

## 测试案例

- 总案例：{audit['test_cases']}；challenge：{audit['challenge_cases']}。
- `current_db_evidence` 表示存在当前数据库可追溯事实；`designed_not_run` 表示冻结场景尚未执行。
- `case_contract_preflight.jsonl` 的数据契约预检为 60/60，通过只证明课程、版本、画像、知识点和 source_ref 字段可对应，不代表 60 条业务场景已经运行通过。

## 限制

- 三项比赛指标当前未正式发布；项目没有外部领域标注人员，内部严格复核不等于独立专家验证。
- 11 个旧式 M5 内存夹具因没有提供可用课程材料而失败，已保留在运行证据中。
- 两门课程之外的跨领域泛化、真实外部模型效果和生产级安全/并发未验证。
- PPT、视频、报名表和最终提交压缩包在后续阶段接入。
"""
    (OUT/"CURRENT_AUDIT_REPORT.md").write_text(audit_md,encoding="utf-8")
    (OUT/"AUDIT_FACTS.json").write_text(json.dumps(audit,ensure_ascii=False,indent=2),encoding="utf-8")
    evidence={"browser_reports":["outputs/e2e_no_docker/report.json","outputs/原系统融合重构执行/evidence/custom_tasks/COURSE-DATA-DEMO-RESEED-03/browser/browser_report.json"],"screenshots_source":"outputs/原系统融合重构执行/evidence/custom_tasks/COURSE-DATA-DEMO-RESEED-03/browser","copied_screenshots":[str(p.relative_to(OUT)).replace('\\\\','/') for p in screenshots],"current_db":"edumatrix.db read-only","source_map":"outputs/原系统融合重构执行/evidence/custom_tasks/TECH-DOC-CODE-MAP-01/TECH-DOC-CODE-MAP-01.md","claim_policy":"code existence, runtime evidence, synthetic/derived data and formal metrics are separate"}
    (OUT/"EVIDENCE_INDEX.json").write_text(json.dumps(evidence,ensure_ascii=False,indent=2),encoding="utf-8")
    claim_boundaries = """# 当前声明边界

- 当前源码、课程 manifest、数据库快照和浏览器证据分别记录，不互相替代。
- 两门课程是本次知识库范围，不代表跨领域泛化。
- 三组画像是脱敏重放和当前引擎派生视图，不是真实用户研究。
- 12 条案例有当前数据库证据，48 条案例尚未执行，不能写成测试通过。
- 三项比赛指标没有外部领域标注人员复核，当前状态为未正式测量。
- deterministic 与 trusted_local 不等于真实外部模型和 Docker 容器隔离。
- 页面截图只证明截图时点的页面状态，不证明指标、生产并发或安全认证。
"""
    (OUT/"CLAIM_BOUNDARIES.md").write_text(claim_boundaries,encoding="utf-8")
    current_test_run = f"""# 当前测试与构建运行记录

记录时间：`{ts()}`  
Git commit：`{audit['git_commit']}`

## 关键回归

```text
.venv\\Scripts\\python.exe -m pytest -q tests/test_m0_course_catalog.py tests/test_m1_course_sources.py tests/test_f3_profile_onboarding.py tests/test_m1_profile_evidence.py tests/test_m3_profiles.py tests/test_m3_agents.py tests/test_m3_debate.py tests/test_m3_matching.py tests/test_m3_decisions.py tests/test_m3_resources.py tests/test_competition_demo_seed.py tests/test_competition_package_runtime.py
```

结果：`65 passed, 6 warnings`。

警告为 FastAPI/Starlette 生命周期、PyPDF2 弃用等提示，不是测试失败。

## 前端构建

```text
cd frontend
npm.cmd run build
```

结果：通过，Vite 转换 5453 个模块；存在大体积 chunk 警告。

## 浏览器证据

- `scripts/e2e_no_docker.py`：通过，健康、登录、工作台、知识库和 sandbox 边界，4 张截图。
- `scripts/e2e_lzz_two_course_demo_evidence.py`：通过，两门课程、24 个页面/截图，HTTP 5xx、页面错误和控制台错误均为 0；8 个 `net::ERR_ABORTED` 是切页取消请求。

## 已知测试夹具限制

`tests/test_m5_learning.py` 和 `tests/test_m5_workspace.py` 中 11 个旧式内存夹具在没有构造当前课程可用材料时返回 `course_unavailable`/`tutor_course_unavailable`。这些失败已保留，不被计入通过数；它们说明夹具需要课程材料前置，不作为产品指标或比赛效果结论。

## 指标状态

幻觉率、画像—资源难度适配准确率和核心知识点覆盖率没有外部领域标注人员复核，当前仅提供冻结测试集、来源、公式和内部评测设计，不发布正式达标数值。
"""
    (OUT/"CURRENT_TEST_RUN.md").write_text(current_test_run,encoding="utf-8")
    manifest={"schema_version":"xh-202630.submission-rebuild.v1","generated_at":audit["generated_at"],"source":"current_source_tree_and_readonly_current_db","git_commit":audit["git_commit"],"documents":sorted(str(p.relative_to(OUT)).replace('\\\\','/') for p in DOCS.rglob('*') if p.is_file()),"data_files":sorted(str(p.relative_to(OUT)).replace('\\\\','/') for p in DATA.rglob('*') if p.is_file()),"figures":sorted(str(p.relative_to(OUT)).replace('\\\\','/') for p in FIGURES.rglob('*') if p.is_file()),"evidence_files":sorted(str(p.relative_to(OUT)).replace('\\\\','/') for p in EVIDENCE.rglob('*') if p.is_file()),"metadata_files":["README.md","CURRENT_AUDIT_REPORT.md","CURRENT_TEST_RUN.md","AUDIT_FACTS.json","EVIDENCE_INDEX.json","CLAIM_BOUNDARIES.md","MATERIAL_MANIFEST.json"],"courses":audit["courses"],"profiles":audit["profiles"],"test_cases":audit["test_cases"],"ppt_generated":False,"video_attached":False,"registration_form_attached":False,"final_zip_generated":False,"pending":["外部领域复核（当前不可用）","PPT","剪辑后视频","审核盖章报名表","最终压缩包元数据"]}
    (OUT/"MATERIAL_MANIFEST.json").write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding="utf-8")
    readme=f"""# XH-202630 当前提交材料重建版\n\n本目录从当前源码、两门课程正文、当前只读演示数据库和当前浏览器证据重建。旧提交包不作为内容来源。\n\n- 文档：{len(manifest['documents'])} 个（Markdown/DOCX）\n- 知识库：{len(kb['chunks'])} 个真实正文分块，{len(kb['refs'])} 个 source_ref\n- 画像：{audit['profiles']} 组，完整十维和当前适配计划\n- 诊断：{audit['diagnostic_records']} 条当前数据库诊断记录\n- 资源：{audit['resources']} 个当前数据库资源对象\n- 学习事件：{audit['learning_events']} 条当前数据库学习事件\n- 测试：{audit['test_cases']} 条，{audit['challenge_cases']} 条 challenge\n- 逐案例：12 条当前数据库证据，48 条未执行挑战场景\n- PPT：未生成\n- 视频/报名表/最终 ZIP：未接入\n\n指标当前标记为未正式测量。结构性完整度文件不等于比赛指标结果。\n"""
    (OUT/"README.md").write_text(readme,encoding="utf-8")
    # Re-export the current adaptation projection after all other files are
    # written so the standalone decision controls remain directly inspectable.
    final_adaptations = extract_profiles_and_resources().get("profile_adaptations", [])
    (DATA/"profile_adaptation_outputs.json").write_text(json.dumps({"data_label":"由当前 app/profile_adaptation.py 对当前快照派生的教学控制","outputs":final_adaptations},ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps({"output":str(OUT),"documents":len(manifest["documents"]),"data_files":len(manifest["data_files"]),"chunks":len(kb["chunks"]),"profiles":audit["profiles"],"cases":audit["test_cases"],"ppt":False},ensure_ascii=False,indent=2))


if __name__ == "__main__":
    main()
