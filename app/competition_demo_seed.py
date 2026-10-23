"""Idempotent competition demonstration data built on canonical EduMatrix facts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from typing import Any

from app.auth import get_password_hash
from app.database import (
    DBAssessmentAttempt,
    DBAssessmentQuestion,
    DBAssessmentQuestionVersion,
    DBArtifact,
    DBArtifactVersion,
    DBAuditLog,
    DBChapter,
    DBChapterKnowledgePoint,
    DBCourse,
    DBCourseMembership,
    DBContentReviewCase,
    DBContentReviewDecision,
    DBDecisionRecord,
    DBGenerationTask,
    DBKnowledgePoint,
    DBLearningEvent,
    DBLearningPath,
    DBMarketplaceRecommendationRun,
    DBPathNode,
    DBPlanDraft,
    DBPlanVersion,
    DBProfileSnapshot,
    DBQuizRecord,
    DBReviewPlan,
    DBPublication,
    DBReviewDecision,
    DBSourceDocument,
    DBSourceRef,
    DBStudentProfile,
    DBTeachingAnalyticsReport,
    DBTeachingClass,
    DBTeachingClassMember,
    DBTeachingGroup,
    DBTeachingTask,
    DBUser,
    DBWrongQuestion,
)
from app.m1_lifecycle import record_audit
from app.post_data_demo_seed import (
    ensure_post_data_course,
    ensure_post_data_overlay,
    post_data_demo_issues,
)


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST_PATH = (
    ROOT
    / "outputs"
    / "竞品融合重构执行"
    / "evidence"
    / "R1-01"
    / "demo_object_manifest.json"
)
SOURCE_MANIFEST_PATH = (
    ROOT / "outputs" / "M0_阶段0基线与架构契约" / "datasets" / "course_manifest.json"
)
SOURCE_COURSE_DIR = SOURCE_MANIFEST_PATH.parent.parent / "baseline_course"
SEED_ACTION = "competition_demo.seed.applied"
REPAIR_ACTION = "competition_demo.seed.repaired"
RESET_ACTION = "competition_demo.reset.applied"
TRACE_ID = "trace-competition-demo-v1-seed"
DEMO_ACCOUNT_PASSWORDS = {
    "lzz": "404404aA",
    "teacher": "admin123",
}
DEFAULT_DEMO_PASSWORD = "EduMatrix-Demo-2026"


class CompetitionDemoSeedError(ValueError):
    pass


@dataclass(frozen=True)
class CompetitionDemoSeedResult:
    demo_scope: str
    manifest_version: str
    manifest_sha256: str
    created_count: int
    repaired_count: int
    identity_bindings: dict[str, str]
    object_counts: dict[str, int]
    status: str


@dataclass(frozen=True)
class CompetitionDemoStatus:
    demo_scope: str
    manifest_version: str
    manifest_sha256: str
    status: str
    initialized: bool
    reset_required: bool
    identity_bindings: dict[str, str]
    object_counts: dict[str, int]
    expected_counts: dict[str, int]
    cohort_student_ids: list[str]
    issues: list[str]


@dataclass(frozen=True)
class CompetitionDemoResetResult:
    before_status: str
    after_status: str
    deleted_counts: dict[str, int]
    seed_result: CompetitionDemoSeedResult


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)


def _hash(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _audit_context(row: DBAuditLog) -> dict[str, Any]:
    metadata = dict(row.metadata_json or {})
    context = metadata.get("context")
    return dict(context) if isinstance(context, dict) else metadata


def _file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes().replace(b"\r\n", b"\n").replace(b"\r", b"\n")).hexdigest()


def _source_paragraph(source_text: str, anchor_start: int, anchor: str) -> tuple[int, int, str]:
    start = source_text.rfind("\n\n", 0, anchor_start)
    start = 0 if start < 0 else start + 2
    end = source_text.find("\n\n", anchor_start + len(anchor))
    end = len(source_text) if end < 0 else end
    while end < len(source_text) and len(source_text[start:end].strip()) < 80:
        next_end = source_text.find("\n\n", end + 2)
        end = len(source_text) if next_end < 0 else next_end
    raw = source_text[start:end]
    quote = raw.strip()
    quote_start = start + len(raw) - len(raw.lstrip())
    return quote_start, quote_start + len(quote), quote


def _utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def load_competition_demo_manifest(path: Path | str = DEFAULT_MANIFEST_PATH) -> dict[str, Any]:
    manifest_path = Path(path)
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    required = {
        "schema_version", "manifest_version", "demo_scope", "course", "source_documents",
        "chapters", "knowledge_points", "users", "cohort", "student_summaries",
        "focus_student", "learning_objects", "event_plan", "metric_contract", "reset_contract",
    }
    missing = required - set(data)
    if missing:
        raise CompetitionDemoSeedError(f"competition demo manifest is missing keys: {sorted(missing)}")
    if data["demo_scope"] != "competition-demo-v1":
        raise CompetitionDemoSeedError("unsupported competition demo scope")
    if data["reset_contract"]["reset_scope"] != f"{data['demo_scope']} only":
        raise CompetitionDemoSeedError("competition demo reset scope is not isolated")
    if len(data["chapters"]) != 12 or len(data["knowledge_points"]) != 12:
        raise CompetitionDemoSeedError("competition demo course must contain 12 chapters and 12 knowledge points")
    students = [item for item in data["users"] if item["role"] == "student"]
    if len(students) != 15 or len(data["cohort"]["student_user_ids"]) != 15:
        raise CompetitionDemoSeedError("competition demo cohort must contain exactly 15 students")
    source_manifest = json.loads(SOURCE_MANIFEST_PATH.read_text(encoding="utf-8"))
    if source_manifest["course_id"] != data["course"]["source_course_id"]:
        raise CompetitionDemoSeedError("competition demo source course differs from the frozen course")
    if source_manifest["manifest_version"] != data["course"]["source_manifest_version"]:
        raise CompetitionDemoSeedError("competition demo source version differs from the frozen course")
    expected = {Path(item["path"]).name: item for item in source_manifest["files"]}
    declared = {item["filename"] for item in data["source_documents"]}
    if declared != set(expected):
        raise CompetitionDemoSeedError("competition demo source file set differs from the frozen course")
    for filename, item in expected.items():
        path_obj = SOURCE_COURSE_DIR / filename
        if not path_obj.is_file() or _file_hash(path_obj).upper() != str(item["sha256"]).upper():
            raise CompetitionDemoSeedError(f"frozen course source mismatch: {filename}")
    return data


def _ensure_user(db: Any, spec: dict[str, Any]) -> tuple[DBUser, bool, bool]:
    expected_id = spec["id"]
    username = spec["username"]
    by_id = db.query(DBUser).filter_by(public_id=expected_id).first()
    by_name = db.query(DBUser).filter_by(username=username).first()
    if by_id is not None and by_id.username != username:
        raise CompetitionDemoSeedError(f"demo public ID is owned by another username: {expected_id}")
    if by_name is not None and by_id is not None and by_name.id != by_id.id:
        raise CompetitionDemoSeedError(f"demo username and public ID resolve to different users: {username}")
    if by_name is not None:
        return by_name, False, by_name.public_id != expected_id
    password = DEMO_ACCOUNT_PASSWORDS.get(username, DEFAULT_DEMO_PASSWORD)
    user = DBUser(
        public_id=expected_id,
        username=username,
        hashed_password=get_password_hash(password),
        role=spec["role"],
        display_name=spec["display_name"],
        is_active=True,
    )
    db.add(user)
    db.flush()
    return user, True, False


def _ensure_course(db: Any, manifest: dict[str, Any]) -> tuple[DBCourse, bool]:
    spec = manifest["course"]
    row = db.get(DBCourse, spec["id"])
    manifest_data = {
        "schema_version": manifest["schema_version"],
        "manifest_version": manifest["manifest_version"],
        "demo_scope": manifest["demo_scope"],
        "source_course_id": spec["source_course_id"],
        "source_manifest_version": spec["source_manifest_version"],
        "truthfulness": manifest["truthfulness"],
    }
    expected = {
        "version": manifest["manifest_version"],
        "title": spec["title"],
        "manifest_version": manifest["manifest_version"],
        "manifest_data": manifest_data,
    }
    if row is None:
        row = DBCourse(
            id=spec["id"], version=expected["version"], title=spec["title"],
            subject=spec["subject"], description="冻结 RAG 来源、认知诊断与负责任评测的一体化比赛演示课程。",
            domain_pack="domain-rag-competition-demo-v1", language="zh-CN",
            content_origin="EduMatrix 冻结合成比赛演示课程；正文派生自仓库 M0 原创课程",
            license_text=spec["license_display"], visibility="public", status="published",
            manifest_version=expected["manifest_version"], manifest_data=manifest_data,
        )
        db.add(row)
        db.flush()
        return row, True
    for key, value in expected.items():
        if getattr(row, key) != value:
            raise CompetitionDemoSeedError(f"existing demo course conflicts with frozen manifest field: {key}")
    return row, False


def _ensure_sources(db: Any, manifest: dict[str, Any]) -> int:
    created = 0
    course_id = manifest["course"]["id"]
    source_specs = {item["id"]: item for item in manifest["source_documents"]}
    for source_id, spec in source_specs.items():
        path = SOURCE_COURSE_DIR / spec["filename"]
        content_hash = _file_hash(path)
        row = db.get(DBSourceDocument, source_id)
        expected = {
            "course_id": course_id, "title": spec["title"], "filename": spec["filename"],
            "file_format": "md", "content_hash": content_hash,
        }
        if row is None:
            row = DBSourceDocument(
                id=source_id, **expected, source_sha256=content_hash, processed_sha256=content_hash,
                file_size=path.stat().st_size, source_path=str(path.relative_to(ROOT)).replace("\\", "/"),
                license_text=manifest["course"]["license_display"], parser_version="edumatrix-parser-v1",
                parser_metadata={"demo_scope": manifest["demo_scope"], "source_course_id": manifest["course"]["source_course_id"]},
                processing_status="ready",
            )
            db.add(row)
            created += 1
        else:
            for key, value in expected.items():
                if getattr(row, key) != value:
                    raise CompetitionDemoSeedError(f"existing demo source conflicts with manifest: {source_id}.{key}")
    db.flush()
    return created


def _ensure_course_structure(db: Any, manifest: dict[str, Any]) -> int:
    created = 0
    course_id = manifest["course"]["id"]
    source_files = {item["id"]: item["filename"] for item in manifest["source_documents"]}
    for spec in manifest["knowledge_points"]:
        row = db.get(DBKnowledgePoint, spec["id"])
        expected = {
            "domain_pack": "domain-rag-competition-demo-v1", "code": spec["code"],
            "version": manifest["manifest_version"], "title": spec["title"],
            "prerequisites": list(spec["prerequisite_ids"]),
        }
        if row is None:
            db.add(DBKnowledgePoint(id=spec["id"], **expected, level="core", status="active"))
            created += 1
        else:
            for key, value in expected.items():
                if getattr(row, key) != value:
                    raise CompetitionDemoSeedError(f"existing demo knowledge point conflicts: {spec['id']}.{key}")
    db.flush()
    for spec in manifest["chapters"]:
        source_path = SOURCE_COURSE_DIR / source_files[spec["source_document_id"]]
        source_text = source_path.read_text(encoding="utf-8")
        anchor_start = source_text.find(spec["source_anchor"])
        if anchor_start < 0:
            raise CompetitionDemoSeedError(f"chapter source anchor is missing: {spec['id']}")
        char_start, char_end, source_quote = _source_paragraph(
            source_text, anchor_start, spec["source_anchor"],
        )
        row = db.get(DBChapter, spec["id"])
        expected = {
            "course_id": course_id, "source_document_id": spec["source_document_id"],
            "stable_key": f"competition-demo/{spec['order']:02d}", "title": spec["title"],
            "position": spec["order"], "char_start": char_start, "char_end": char_end,
        }
        if row is None:
            db.add(DBChapter(id=spec["id"], **expected, heading_level=2))
            created += 1
        else:
            for key, value in expected.items():
                if key in {"char_start", "char_end"}:
                    continue
                if getattr(row, key) != value:
                    raise CompetitionDemoSeedError(f"existing demo chapter conflicts: {spec['id']}.{key}")
            if row.char_start != char_start or row.char_end != char_end:
                row.char_start = char_start
                row.char_end = char_end
                created += 1
        relation_id = f"demo-ckp-{spec['order']:02d}"
        relation = db.get(DBChapterKnowledgePoint, relation_id)
        if relation is None:
            db.add(DBChapterKnowledgePoint(
                id=relation_id, chapter_id=spec["id"], knowledge_point_id=spec["knowledge_point_id"],
                relation_type="teaches",
            ))
            created += 1
        ref_id = f"demo-ref-{spec['order']:02d}"
        source_ref = db.get(DBSourceRef, ref_id)
        if source_ref is None:
            db.add(DBSourceRef(
                id=ref_id, source_document_id=spec["source_document_id"], chapter_id=spec["id"],
                parser_version="edumatrix-parser-v1", char_start=char_start, char_end=char_end,
                location_kind="section", location_index=spec["order"], location_label=spec["source_section"],
                location_metadata={"demo_scope": manifest["demo_scope"]},
                content_hash=_file_hash(source_path), quote=source_quote,
            ))
            created += 1
        else:
            expected_ref = {
                "source_document_id": spec["source_document_id"],
                "chapter_id": spec["id"],
                "parser_version": "edumatrix-parser-v1",
                "location_kind": "section",
                "location_index": spec["order"],
                "location_label": spec["source_section"],
                "content_hash": _file_hash(source_path),
            }
            for key, value in expected_ref.items():
                if getattr(source_ref, key) != value:
                    raise CompetitionDemoSeedError(f"existing demo source ref conflicts: {ref_id}.{key}")
            expected_metadata = {"demo_scope": manifest["demo_scope"]}
            if source_ref.location_metadata != expected_metadata:
                raise CompetitionDemoSeedError(f"existing demo source ref conflicts: {ref_id}.location_metadata")
            if (
                source_ref.char_start != char_start
                or source_ref.char_end != char_end
                or source_ref.quote != source_quote
            ):
                source_ref.char_start = char_start
                source_ref.char_end = char_end
                source_ref.quote = source_quote
                created += 1
    db.flush()
    return created


def _ensure_membership(db: Any, *, row_id: str, course_id: str, user_id: str, role: str) -> bool:
    row = db.query(DBCourseMembership).filter_by(course_id=course_id, user_public_id=user_id).first()
    if row is None:
        db.add(DBCourseMembership(id=row_id, course_id=course_id, user_public_id=user_id, role=role, status="active"))
        return True
    if row.role != role or row.status != "active":
        row.role = role
        row.status = "active"
    return False


def _ensure_people_and_class(db: Any, manifest: dict[str, Any]) -> tuple[dict[str, str], int, int]:
    bindings: dict[str, str] = {}
    created = 0
    aliases = 0
    user_specs = {item["id"]: item for item in manifest["users"]}
    for logical_id, spec in user_specs.items():
        user, was_created, was_alias = _ensure_user(db, spec)
        bindings[logical_id] = user.public_id
        created += int(was_created)
        aliases += int(was_alias)
    course_id = manifest["course"]["id"]
    for index, (logical_id, spec) in enumerate(user_specs.items(), start=1):
        created += int(_ensure_membership(
            db, row_id=f"demo-cm-{index:02d}", course_id=course_id,
            user_id=bindings[logical_id], role=spec["role"],
        ))
    db.flush()
    cohort = manifest["cohort"]
    teacher_id = bindings[cohort["teacher_user_id"]]
    classroom = db.get(DBTeachingClass, cohort["class_id"])
    if classroom is None:
        classroom = DBTeachingClass(
            id=cohort["class_id"], course_id=course_id, title=cohort["title"],
            term="2026 比赛演示", owner_public_id=teacher_id, status="active",
        )
        db.add(classroom)
        created += 1
    elif classroom.course_id != course_id or classroom.owner_public_id != teacher_id:
        raise CompetitionDemoSeedError("existing demo teaching class conflicts with manifest scope")
    member_specs = [
        (cohort["teacher_user_id"], "teacher"),
        (cohort["assistant_user_id"], "assistant"),
        *((student_id, "student") for student_id in cohort["student_user_ids"]),
    ]
    for index, (logical_id, role) in enumerate(member_specs, start=1):
        actual_id = bindings[logical_id]
        row = db.query(DBTeachingClassMember).filter_by(class_id=classroom.id, user_public_id=actual_id).first()
        if row is None:
            db.add(DBTeachingClassMember(
                id=f"demo-tcm-{index:02d}", class_id=classroom.id, user_public_id=actual_id,
                role=role, status="active",
            ))
            created += 1
        elif row.role != role:
            raise CompetitionDemoSeedError(f"existing demo class member has another role: {logical_id}")
    db.flush()
    return bindings, created, aliases


def _profile_payload(summary: dict[str, Any], manifest: dict[str, Any]) -> dict[str, Any]:
    focus = manifest["focus_student"]
    is_focus = summary["user_id"] == focus["user_id"]
    return {
        "schema_version": "competition.demo.profile.v1",
        "demo_scope": manifest["demo_scope"],
        "course_id": manifest["course"]["id"],
        "mastery": summary["mastery"],
        "participated": summary["participated"],
        "attention": summary["attention"],
        "mastered_knowledge_point_ids": focus["mastered_knowledge_point_ids"] if is_focus else [],
        "weak_knowledge_point_ids": focus["weak_knowledge_point_ids"] if is_focus else [],
        "misconception": focus["misconception"] if is_focus else None,
        "truthfulness": "frozen_synthetic_demo_data",
    }


def _ensure_profiles(db: Any, manifest: dict[str, Any], bindings: dict[str, str]) -> int:
    created = 0
    summaries = {item["user_id"]: item for item in manifest["student_summaries"]}
    users = {item["id"]: item for item in manifest["users"]}
    focus = manifest["focus_student"]
    for logical_id, summary in summaries.items():
        actual_id = bindings[logical_id]
        profile_id = focus["profile_snapshot_id"] if logical_id == focus["user_id"] else f"demo-profile-{logical_id.removeprefix('usr-demo-')}-v1"
        payload = _profile_payload(summary, manifest)
        content_hash = _hash(payload)
        row = db.get(DBProfileSnapshot, profile_id)
        if row is None:
            db.add(DBProfileSnapshot(
                id=profile_id, owner_public_id=actual_id,
                legacy_student_id=users[logical_id]["username"],
                profile_version="competition.demo.profile.v1", snapshot=payload,
                content_hash=content_hash, trace_id=TRACE_ID,
            ))
            created += 1
        elif row.owner_public_id != actual_id or row.content_hash != content_hash or row.snapshot != payload:
            raise CompetitionDemoSeedError(f"existing demo profile conflicts with manifest: {profile_id}")
        username = users[logical_id]["username"]
        legacy = db.get(DBStudentProfile, username)
        if legacy is None:
            evidence = {
                "source": "performance_signal",
                "source_object_id": profile_id,
                "text": "冻结合成演示画像，依据课程参与、掌握度和薄弱知识点生成。",
                "features": ["mastery", "participation", "weak_knowledge_points"],
                "weight": 1.0,
                "confidence": 0.95,
                "timestamp": "2026-08-06T00:00:00Z",
                "version": "competition.demo.profile-evidence.v1",
                "trace_id": TRACE_ID,
                "demo_scope": manifest["demo_scope"],
                "snapshot_id": profile_id,
            }
            db.add(DBStudentProfile(
                student_id=username, target_course=manifest["course"]["title"],
                weak_points=[item for item in payload["weak_knowledge_point_ids"]],
                concept_mastery={"overall": summary["mastery"]},
                profile_evidence=[evidence],
            ))
            created += 1
    db.flush()
    return created


def _ensure_artifacts(db: Any, manifest: dict[str, Any], owner_id: str) -> int:
    created = 0
    for spec in manifest["learning_objects"]["artifacts"]:
        artifact = db.get(DBArtifact, spec["id"])
        title = {
            "study_note": "混合检索证据精读笔记",
            "interactive_lab": "Recall@K 混合检索调优实验",
            "lesson_guide": "引用约束与拒答学习讲义",
        }[spec["type"]]
        if artifact is None:
            artifact = DBArtifact(
                id=spec["id"], owner_public_id=owner_id, course_id=spec["course_id"],
                artifact_type=spec["type"], title=title, status="approved",
                current_version_id=spec["version_id"],
            )
            db.add(artifact)
            created += 1
        elif artifact.owner_public_id != owner_id or artifact.course_id != spec["course_id"]:
            raise CompetitionDemoSeedError(f"existing demo artifact is out of scope: {spec['id']}")
        content = _canonical({
            "schema_version": "competition.demo.artifact.v1", "demo_scope": manifest["demo_scope"],
            "chapter_id": spec["chapter_id"], "artifact_type": spec["type"], "title": title,
            "status": "frozen_initial_demo_artifact",
        })
        version = db.get(DBArtifactVersion, spec["version_id"])
        if version is None:
            db.add(DBArtifactVersion(
                id=spec["version_id"], artifact_id=spec["id"], version_number=1,
                content=content, content_format="json", content_hash=hashlib.sha256(content.encode("utf-8")).hexdigest(),
                metadata_json={"demo_scope": manifest["demo_scope"], "chapter_id": spec["chapter_id"]},
                created_by_public_id=owner_id,
            ))
            created += 1
        elif version.artifact_id != spec["id"] or version.content != content:
            raise CompetitionDemoSeedError(f"existing demo artifact version conflicts: {spec['version_id']}")
    db.flush()
    return created


def _plan_content(manifest: dict[str, Any], *, historical: bool = False) -> dict[str, Any]:
    if historical:
        return {
            "schema_version": "m5.plan.v1", "goal": "补强向量检索基础并完成一次教师干预",
            "deadline": None, "assumptions": ["冻结合成演示数据"],
            "nodes": [{
                "node_key": "historical-vector-review", "node_type": "chapter",
                "target_object_id": "demo-ch-06", "title": "向量检索基础复习",
                "prerequisites": [], "resource_status": "existing",
                "estimate_min_minutes": 20, "estimate_max_minutes": 30,
                "extension_reason": "", "required": True, "risk_level": "normal",
            }],
        }
    return {
        "schema_version": "m5.plan.v1", "goal": "掌握混合检索调优与可信评测",
        "deadline": None, "assumptions": ["冻结合成演示数据", "每日最多三项任务"],
        "nodes": [
            {"node_key": "read-hybrid", "node_type": "chapter", "target_object_id": "demo-ch-07", "title": "精读混合检索来源", "prerequisites": [], "resource_status": "existing", "estimate_min_minutes": 15, "estimate_max_minutes": 15, "extension_reason": "", "required": True, "risk_level": "normal"},
            {"node_key": "lab-hybrid", "node_type": "interactive", "target_object_id": "demo-artifact-lzz-lab-01", "title": "调优 Recall@K 交互实验", "prerequisites": ["read-hybrid"], "resource_status": "existing", "estimate_min_minutes": 20, "estimate_max_minutes": 20, "extension_reason": "", "required": True, "risk_level": "normal"},
            {"node_key": "quiz-hybrid", "node_type": "assessment", "target_object_id": "demo-assessment-lzz-rag-01-q01-v1", "title": "完成混合检索短测", "prerequisites": ["read-hybrid"], "resource_status": "existing", "estimate_min_minutes": 10, "estimate_max_minutes": 10, "extension_reason": "", "required": True, "risk_level": "normal"},
        ],
    }


def _ensure_plan_path(db: Any, manifest: dict[str, Any], owner_id: str, teacher_id: str) -> int:
    created = 0
    focus = manifest["focus_student"]
    learning = manifest["learning_objects"]
    variants = [
        (focus["active_plan_id"], focus["active_plan_version_id"], focus["active_path_id"], False, owner_id, "active"),
        (learning["historical_intervention"]["plan_id"], "demo-intervention-plan-version-lzz-history-01", learning["historical_intervention"]["path_id"], True, teacher_id, "completed"),
    ]
    for plan_id, version_id, path_id, historical, actor_id, path_status in variants:
        content = _plan_content(manifest, historical=historical)
        content_hash = _hash(content)
        plan = db.get(DBPlanDraft, plan_id)
        if plan is None:
            plan = DBPlanDraft(
                id=plan_id, owner_public_id=owner_id, course_id=manifest["course"]["id"],
                title="历史教师干预" if historical else "RAG 可信评测学习计划",
                status="confirmed", idempotency_key=f"{manifest['demo_scope']}:{plan_id}",
                current_version_id=version_id, confirmed_version_id=version_id,
                confirmed_at=_utcnow(),
            )
            db.add(plan)
            created += 1
        db.flush()
        version = db.get(DBPlanVersion, version_id)
        if version is None:
            db.add(DBPlanVersion(
                id=version_id, plan_draft_id=plan_id, version_number=1,
                profile_snapshot_id=focus["profile_snapshot_id"], content=content,
                content_hash=content_hash, created_by_public_id=actor_id,
            ))
            created += 1
        elif version.plan_draft_id != plan_id or version.content_hash != content_hash:
            raise CompetitionDemoSeedError(f"existing demo plan version conflicts: {version_id}")
        db.flush()
        path = db.get(DBLearningPath, path_id)
        if path is None:
            path = DBLearningPath(
                id=path_id, owner_public_id=owner_id, course_id=manifest["course"]["id"],
                source_plan_version_id=version_id, status=path_status,
                completed_at=_utcnow() if historical else None,
            )
            db.add(path)
            created += 1
        elif path.owner_public_id != owner_id or path.source_plan_version_id != version_id:
            raise CompetitionDemoSeedError(f"existing demo learning path conflicts: {path_id}")
        elif path.status != path_status:
            # Demo-scope paths are owned by this seed. Repair a prior archive or
            # pause so the generated learning journey remains reachable.
            path.status = path_status
            path.completed_at = _utcnow() if historical else None
            path.archived_at = None
            path.paused_at = None
            created += 1
        db.flush()
        node_specs = content["nodes"]
        requested_ids = (
            ["demo-intervention-history-node-01"] if historical else list(focus["today_task_ids"])
        )
        for sequence, (node_id, spec) in enumerate(zip(requested_ids, node_specs), start=1):
            node = db.get(DBPathNode, node_id)
            if node is None:
                db.add(DBPathNode(
                    id=node_id, learning_path_id=path_id, node_key=spec["node_key"], sequence=sequence,
                    node_type=spec["node_type"], target_object_id=spec["target_object_id"],
                    title=spec["title"], status="completed" if historical else ("in_progress" if sequence == 1 else "pending"),
                    prerequisites=spec["prerequisites"], resource_status=spec["resource_status"],
                    estimate_min_minutes=spec["estimate_min_minutes"], estimate_max_minutes=spec["estimate_max_minutes"],
                ))
                created += 1
            elif node.learning_path_id != path_id:
                raise CompetitionDemoSeedError(f"existing demo task belongs to another path: {node_id}")
    db.flush()
    return created


def _ensure_assessment_and_review(db: Any, manifest: dict[str, Any], owner_id: str, username: str) -> int:
    created = 0
    questions = [
        ("demo-kp-06", "向量检索是否总能优于关键词检索？", False, True, [1.15, 0.25, 0.35], [-0.25, 0.15, 0.05], "understand", "theory"),
        ("demo-kp-07", "只增大向量 top-k 是否必然提高有效召回？", False, False, [1.25, 0.35, 0.55], [0.15, 0.25, 0.35], "apply", "application"),
        ("demo-kp-08", "没有可核查证据时系统应继续生成答案吗？", False, False, [1.05, 0.20, 0.45], [0.05, 0.20, 0.25], "evaluate", "engineering_judgment"),
        ("demo-kp-07", "混合检索是否需要重排阶段？", True, True, [1.30, 0.40, 0.60], [0.35, 0.40, 0.45], "apply", "application"),
        ("demo-kp-10", "Recall@K 的分母应在冻结评测集上定义吗？", True, True, [0.95, 0.20, 1.10], [0.45, 0.35, 0.55], "evaluate", "engineering_judgment"),
    ]
    wrong_index = 0
    for index, (kp_id, prompt, answer, correct, alpha, beta, bloom_level, diagnostic_dimension) in enumerate(questions, start=1):
        question_id = f"demo-assessment-lzz-rag-01-q{index:02d}"
        version_id = f"{question_id}-v1"
        question = db.get(DBAssessmentQuestion, question_id)
        if question is None:
            question = DBAssessmentQuestion(
                id=question_id, course_id=manifest["course"]["id"], owner_public_id=owner_id,
                question_type="true_false", origin="textbook", status="approved",
                current_version_id=version_id,
            )
            db.add(question)
            created += 1
        source_ref_id = f"demo-ref-{7 if kp_id == 'demo-kp-07' else 8 if kp_id == 'demo-kp-08' else 6 if kp_id == 'demo-kp-06' else 10:02d}"
        irt_parameters = {"alpha_vector": alpha, "beta_vector": beta, "gamma": 0.5}
        content = {
            "prompt": prompt, "options": ["是", "否"], "answer": answer,
            "kp": kp_id, "bloom_level": bloom_level, "diagnostic_dimension": diagnostic_dimension,
            "irt_parameters": irt_parameters, "source_ref_id": source_ref_id,
        }
        desired_hash = _hash(content)
        desired_scoring_rule = {
            "type": "exact",
            "version": "competition-diagnostic-v1",
            "diagnostic_dimension": diagnostic_dimension,
        }
        desired_misconceptions = ["top-k-absolutism"] if not correct else []

        def version_matches(candidate: DBAssessmentQuestionVersion | None) -> bool:
            return bool(
                candidate
                and candidate.prompt == prompt
                and candidate.options == ["是", "否"]
                and candidate.answer_key == {"value": answer}
                and candidate.scoring_rule == desired_scoring_rule
                and candidate.explanation == "答案来自冻结 RAG 课程来源。"
                and candidate.misconception_tags == desired_misconceptions
                and candidate.primary_knowledge_point_id == kp_id
                and candidate.bloom_level == bloom_level
                and candidate.expert_difficulty == max(beta)
                and candidate.irt_parameters == irt_parameters
                and candidate.source_ref_ids == [source_ref_id]
                and candidate.content_hash == desired_hash
            )

        version = db.get(DBAssessmentQuestionVersion, question.current_version_id or version_id)
        if not version_matches(version):
            version = (
                db.query(DBAssessmentQuestionVersion)
                .filter_by(question_id=question_id, content_hash=desired_hash)
                .order_by(DBAssessmentQuestionVersion.version_number.desc())
                .first()
            )
        if not version_matches(version):
            latest_number = (
                db.query(DBAssessmentQuestionVersion.version_number)
                .filter_by(question_id=question_id)
                .order_by(DBAssessmentQuestionVersion.version_number.desc())
                .limit(1)
                .scalar()
                or 0
            )
            next_number = latest_number + 1
            next_version_id = version_id if next_number == 1 else f"{question_id}-v{next_number}"
            version = DBAssessmentQuestionVersion(
                id=next_version_id, question_id=question_id, version_number=next_number, prompt=prompt,
                options=["是", "否"], answer_key={"value": answer},
                scoring_rule=desired_scoring_rule,
                explanation="答案来自冻结 RAG 课程来源。", misconception_tags=desired_misconceptions,
                primary_knowledge_point_id=kp_id, bloom_level=bloom_level,
                expert_difficulty=max(beta), irt_parameters=irt_parameters, sample_size=0,
                source_ref_ids=[source_ref_id],
                content_hash=desired_hash, created_by_public_id=owner_id,
            )
            db.add(version)
            db.flush()
            created += 1
        if question.current_version_id != version.id:
            question.current_version_id = version.id
            created += 1
        # Attempts reference immutable question versions. Flush the identity and
        # version first so SQLite's immediate FK checks cannot observe a missing
        # parent during the same seed batch.
        db.flush()
        if not correct:
            wrong_index += 1
            quiz_id = f"demo-quiz-record-lzz-{wrong_index:02d}"
            quiz = db.get(DBQuizRecord, quiz_id)
            if quiz is None:
                db.add(DBQuizRecord(
                    id=quiz_id, student_id=username, question=prompt,
                    student_answer="是", correct_answer=answer, accuracy_score=0.0,
                    target_concept=kp_id, feedback="已识别错因并加入复习。",
                    next_action="review", options=["是", "否"],
                ))
                created += 1
            attempt_id = f"demo-assessment-attempt-lzz-{wrong_index:02d}"
            if db.get(DBAssessmentAttempt, attempt_id) is None:
                db.add(DBAssessmentAttempt(
                    id=attempt_id, owner_public_id=owner_id, course_id=manifest["course"]["id"],
                    question_version_id=version_id, idempotency_key=f"{manifest['demo_scope']}:{attempt_id}",
                    mode="diagnostic", answer={"value": True}, score=0.0, correct=False,
                    confidence=0.7, duration_seconds=35, grading_status="graded", feedback_policy="immediate",
                ))
                created += 1
            wrong = db.query(DBWrongQuestion).filter_by(student_id=username, quiz_record_id=quiz_id).first()
            if wrong is None:
                db.add(DBWrongQuestion(
                    student_id=username, quiz_record_id=quiz_id, concept_name=kp_id,
                    wrong_reason_category="confirmed_misconception" if kp_id == "demo-kp-07" else "evidence_boundary",
                    pinned=True, notes=f"logical_id=demo-wrong-lzz-{wrong_index:02d}",
                ))
                created += 1
            review = db.query(DBReviewPlan).filter_by(student_id=username, concept=kp_id).first()
            if review is None:
                db.add(DBReviewPlan(
                    student_id=username, concept=kp_id, interval_days=1, mastery=0.35,
                    review_count=0, easiness_factor=2.5, last_quality=0,
                    similar_quiz_ids=[quiz_id, f"logical:demo-review-lzz-{wrong_index:02d}"], priority=0.5,
                ))
                created += 1
    db.flush()
    return created


def _event_payload(manifest: dict[str, Any], logical_user_id: str, index: int) -> dict[str, Any]:
    return {
        "demo_scope": manifest["demo_scope"], "logical_user_id": logical_user_id,
        "synthetic": True, "sequence": index,
    }


def _ensure_events(db: Any, manifest: dict[str, Any], bindings: dict[str, str]) -> int:
    created = 0
    initial_focus = list(manifest["event_plan"]["initial_event_ids"])
    summaries = {item["user_id"]: item for item in manifest["student_summaries"]}
    for logical_id, summary in summaries.items():
        count = int(summary["activity_event_count"])
        if logical_id == manifest["focus_student"]["user_id"]:
            ids = initial_focus + [f"demo-event-lzz-activity-{index:02d}" for index in range(6, count + 1)]
        else:
            suffix = logical_id.removeprefix("usr-demo-")
            ids = [f"demo-event-{suffix}-activity-{index:02d}" for index in range(1, count + 1)]
        for index, event_id in enumerate(ids, start=1):
            row = db.get(DBLearningEvent, event_id)
            if row is None:
                db.add(DBLearningEvent(
                    id=event_id, owner_public_id=bindings[logical_id],
                    legacy_student_id=next(item["username"] for item in manifest["users"] if item["id"] == logical_id),
                    course_id=manifest["course"]["id"],
                    event_type="resource_opened" if index % 2 else "reading_started",
                    schema_version="competition.demo.learning-event.v1",
                    idempotency_key=f"{manifest['demo_scope']}:{event_id}", source="migration",
                    trace_id=TRACE_ID, object_type="chapter", object_id="demo-ch-07",
                    payload=_event_payload(manifest, logical_id, index),
                    occurred_at=datetime(2026, 8, 1, 8, min(index, 59), 0),
                ))
                created += 1
            elif row.owner_public_id != bindings[logical_id] or row.course_id != manifest["course"]["id"]:
                raise CompetitionDemoSeedError(f"existing demo learning event is out of scope: {event_id}")
    db.flush()
    return created


def _object_counts(db: Any, manifest: dict[str, Any], bindings: dict[str, str]) -> dict[str, int]:
    course_id = manifest["course"]["id"]
    class_id = manifest["cohort"]["class_id"]
    focus_owner = bindings[manifest["focus_student"]["user_id"]]
    return {
        "courses": db.query(DBCourse).filter_by(id=course_id).count(),
        "source_documents": db.query(DBSourceDocument).filter_by(course_id=course_id).count(),
        "chapters": db.query(DBChapter).filter_by(course_id=course_id).count(),
        "course_memberships": db.query(DBCourseMembership).filter_by(course_id=course_id).count(),
        "class_members": db.query(DBTeachingClassMember).filter_by(class_id=class_id).count(),
        "profile_snapshots": db.query(DBProfileSnapshot).filter(DBProfileSnapshot.owner_public_id.in_(list(bindings.values()))).filter_by(profile_version="competition.demo.profile.v1").count(),
        "plans": db.query(DBPlanDraft).filter_by(owner_public_id=focus_owner, course_id=course_id).filter(DBPlanDraft.id.like("demo-%")).count(),
        "paths": db.query(DBLearningPath).filter_by(owner_public_id=focus_owner, course_id=course_id).filter(DBLearningPath.id.like("demo-%")).count(),
        "path_nodes": db.query(DBPathNode).filter(DBPathNode.id.like("demo-%")).count(),
        "artifacts": db.query(DBArtifact).filter_by(owner_public_id=focus_owner, course_id=course_id).filter(DBArtifact.id.like("demo-%")).count(),
        "assessment_questions": db.query(DBAssessmentQuestion).filter_by(owner_public_id=focus_owner, course_id=course_id).filter(DBAssessmentQuestion.id.like("demo-%")).count(),
        "learning_events": db.query(DBLearningEvent).filter_by(course_id=course_id).filter(DBLearningEvent.id.like("demo-event-%")).count(),
    }


def _expected_object_counts(manifest: dict[str, Any]) -> dict[str, int]:
    users = list(manifest["users"])
    students = [item for item in users if item["role"] == "student"]
    learning = manifest["learning_objects"]
    return {
        "courses": 1,
        "source_documents": len(manifest["source_documents"]),
        "chapters": len(manifest["chapters"]),
        "course_memberships": len(users),
        "class_members": len(students) + 2,
        "profile_snapshots": len(students),
        "plans": len(learning["plans"]),
        "paths": len(learning["paths"]),
        "path_nodes": len(learning["tasks"]) + 1,
        "artifacts": len(learning["artifacts"]),
        "assessment_questions": int(learning["assessment"]["question_count"]),
        "learning_events": sum(int(item["activity_event_count"]) for item in manifest["student_summaries"]),
    }


def _resolve_existing_bindings(db: Any, manifest: dict[str, Any]) -> tuple[dict[str, str], list[str]]:
    bindings: dict[str, str] = {}
    issues: list[str] = []
    for spec in manifest["users"]:
        logical_id = spec["id"]
        by_id = db.query(DBUser).filter_by(public_id=logical_id).first()
        by_name = db.query(DBUser).filter_by(username=spec["username"]).first()
        if by_id is not None and by_id.username != spec["username"]:
            issues.append(f"identity_conflict:{logical_id}")
            continue
        if by_id is not None and by_name is not None and by_id.id != by_name.id:
            issues.append(f"identity_split:{logical_id}")
            continue
        user = by_name or by_id
        if user is None:
            issues.append(f"identity_missing:{logical_id}")
            continue
        bindings[logical_id] = user.public_id
        if user.role != spec["role"]:
            issues.append(f"identity_role:{logical_id}")
    return bindings, issues


def _demo_profile_rows(db: Any, manifest: dict[str, Any], bindings: dict[str, str]) -> list[DBProfileSnapshot]:
    owners = list(bindings.values())
    if not owners:
        return []
    rows = db.query(DBProfileSnapshot).filter(DBProfileSnapshot.owner_public_id.in_(owners)).all()
    return [
        row for row in rows
        if row.id.startswith("demo-profile-")
        or (isinstance(row.snapshot, dict) and row.snapshot.get("demo_scope") == manifest["demo_scope"])
    ]


def _demo_event_rows(db: Any, manifest: dict[str, Any], bindings: dict[str, str]) -> list[DBLearningEvent]:
    owners = list(bindings.values())
    query = db.query(DBLearningEvent).filter_by(course_id=manifest["course"]["id"])
    if owners:
        query = query.filter(DBLearningEvent.owner_public_id.in_(owners))
    return [
        row for row in query.all()
        if row.id.startswith("demo-event-")
        or (isinstance(row.payload, dict) and row.payload.get("demo_scope") == manifest["demo_scope"])
    ]


def _initial_state_issues(db: Any, manifest: dict[str, Any], bindings: dict[str, str]) -> list[str]:
    issues: list[str] = []
    focus = manifest["focus_student"]
    learning = manifest["learning_objects"]
    owner_id = bindings.get(focus["user_id"])
    if not owner_id:
        return ["focus_identity_missing"]

    expected_profiles = {
        focus["profile_snapshot_id"] if item["user_id"] == focus["user_id"]
        else f"demo-profile-{item['user_id'].removeprefix('usr-demo-')}-v1": item
        for item in manifest["student_summaries"]
    }
    profile_rows = {row.id: row for row in _demo_profile_rows(db, manifest, bindings)}
    if set(profile_rows) != set(expected_profiles):
        issues.append("profile_snapshot_set")
    for profile_id, summary in expected_profiles.items():
        row = profile_rows.get(profile_id)
        if row is None:
            continue
        expected = _profile_payload(summary, manifest)
        if row.snapshot != expected or row.content_hash != _hash(expected):
            issues.append(f"profile_snapshot:{profile_id}")

    for spec in learning["plans"]:
        row = db.get(DBPlanDraft, spec["id"])
        if row is None or row.owner_public_id != owner_id or row.course_id != spec["course_id"]:
            issues.append(f"plan:{spec['id']}")
    for spec in learning["paths"]:
        row = db.get(DBLearningPath, spec["id"])
        if row is None or row.owner_public_id != owner_id or row.status != spec["status"]:
            issues.append(f"path:{spec['id']}")
    expected_task_status = {item["id"]: item["status"] for item in learning["tasks"]}
    expected_task_status["demo-intervention-history-node-01"] = "completed"
    actual_nodes = db.query(DBPathNode).filter(DBPathNode.id.like("demo-%")).all()
    actual_task_status = {row.id: row.status for row in actual_nodes}
    if actual_task_status != expected_task_status:
        issues.append("path_node_state")

    artifact_ids = {item["id"]: item["version_id"] for item in learning["artifacts"]}
    actual_artifacts = db.query(DBArtifact).filter_by(owner_public_id=owner_id, course_id=manifest["course"]["id"]).filter(DBArtifact.id.like("demo-%")).all()
    if {row.id for row in actual_artifacts} != set(artifact_ids):
        issues.append("artifact_set")
    for row in actual_artifacts:
        if row.status != "approved" or row.current_version_id != artifact_ids[row.id]:
            issues.append(f"artifact_state:{row.id}")

    question_prefix = "demo-assessment-lzz-rag-01-q"
    attempts = db.query(DBAssessmentAttempt).filter_by(owner_public_id=owner_id, course_id=manifest["course"]["id"]).filter(DBAssessmentAttempt.id.like("demo-assessment-attempt-%")).all()
    quizzes = db.query(DBQuizRecord).filter(DBQuizRecord.id.like("demo-quiz-record-%")).count()
    wrong = db.query(DBWrongQuestion).filter(DBWrongQuestion.notes.like("logical_id=demo-wrong-%")).count()
    reviews = [row for row in db.query(DBReviewPlan).filter_by(student_id=next(item["username"] for item in manifest["users"] if item["id"] == focus["user_id"])).all() if any(str(value).startswith("logical:demo-review-") for value in (row.similar_quiz_ids or []))]
    if len(attempts) != 2 or quizzes != 2 or wrong != 2 or len(reviews) != 2:
        issues.append("assessment_review_state")
    if db.query(DBAssessmentQuestion).filter(DBAssessmentQuestion.id.like(f"{question_prefix}%")).count() != int(learning["assessment"]["question_count"]):
        issues.append("assessment_question_set")

    if len(_demo_event_rows(db, manifest, bindings)) != _expected_object_counts(manifest)["learning_events"]:
        issues.append("learning_event_set")
    return sorted(set(issues))


def competition_demo_status(
    db: Any,
    manifest_path: Path | str = DEFAULT_MANIFEST_PATH,
    *,
    include_post_data: bool = True,
) -> CompetitionDemoStatus:
    manifest = load_competition_demo_manifest(manifest_path)
    manifest_sha256 = _hash(manifest)
    course = db.get(DBCourse, manifest["course"]["id"])
    seed_record = db.query(DBAuditLog).filter_by(
        action=SEED_ACTION, object_type="demo_scope", object_id=manifest["demo_scope"],
    ).first()
    if course is None and seed_record is None:
        return CompetitionDemoStatus(
            demo_scope=manifest["demo_scope"], manifest_version=manifest["manifest_version"],
            manifest_sha256=manifest_sha256, status="uninitialized", initialized=False,
            reset_required=False, identity_bindings={}, object_counts={},
            expected_counts=_expected_object_counts(manifest), cohort_student_ids=[], issues=[],
        )

    bindings, issues = _resolve_existing_bindings(db, manifest)
    if seed_record is None:
        issues.append("seed_audit_missing")
    elif _audit_context(seed_record).get("manifest_sha256") != manifest_sha256:
        issues.append("seed_manifest_hash")
    expected_counts = _expected_object_counts(manifest)
    counts = _object_counts(db, manifest, bindings) if len(bindings) == len(manifest["users"]) else {}
    for key, expected in expected_counts.items():
        if counts.get(key) != expected:
            issues.append(f"count:{key}")

    class_id = manifest["cohort"]["class_id"]
    expected_students = [bindings[item] for item in manifest["cohort"]["student_user_ids"] if item in bindings]
    actual_students = [
        row.user_public_id for row in db.query(DBTeachingClassMember)
        .filter_by(class_id=class_id, role="student", status="active").order_by(DBTeachingClassMember.user_public_id).all()
    ]
    if sorted(actual_students) != sorted(expected_students) or len(actual_students) != 15:
        issues.append("cohort_students")
    if len(bindings) == len(manifest["users"]):
        issues.extend(_initial_state_issues(db, manifest, bindings))
        if include_post_data:
            owner = db.query(DBUser).filter_by(
                public_id=bindings[manifest["focus_student"]["user_id"]],
            ).one()
            issues.extend(post_data_demo_issues(db, owner=owner))
    issues = sorted(set(issues))
    return CompetitionDemoStatus(
        demo_scope=manifest["demo_scope"], manifest_version=manifest["manifest_version"],
        manifest_sha256=manifest_sha256, status="ready" if not issues else "degraded",
        initialized=True, reset_required=bool(issues), identity_bindings=bindings,
        object_counts=counts, expected_counts=expected_counts,
        cohort_student_ids=sorted(actual_students), issues=issues,
    )


def competition_demo_students(db: Any, manifest_path: Path | str = DEFAULT_MANIFEST_PATH) -> list[DBUser]:
    manifest = load_competition_demo_manifest(manifest_path)
    bindings, issues = _resolve_existing_bindings(db, manifest)
    if issues:
        raise CompetitionDemoSeedError(f"competition demo identities are incomplete: {issues}")
    expected_ids = {bindings[item] for item in manifest["cohort"]["student_user_ids"]}
    rows = db.query(DBTeachingClassMember).filter_by(
        class_id=manifest["cohort"]["class_id"], role="student", status="active",
    ).all()
    actual_ids = {row.user_public_id for row in rows}
    if actual_ids != expected_ids or len(rows) != 15:
        raise CompetitionDemoSeedError("competition demo teaching scope must contain exactly 15 students")
    return db.query(DBUser).filter(DBUser.public_id.in_(sorted(actual_ids))).order_by(DBUser.username).all()


def _delete_count(query: Any) -> int:
    return int(query.delete(synchronize_session=False) or 0)


def reset_competition_demo(db: Any, manifest_path: Path | str = DEFAULT_MANIFEST_PATH) -> CompetitionDemoResetResult:
    manifest = load_competition_demo_manifest(manifest_path)
    before = competition_demo_status(db, manifest_path)
    core_before = competition_demo_status(db, manifest_path, include_post_data=False)
    if core_before.status == "ready":
        seed_result = seed_competition_demo(db, manifest_path)
        after = competition_demo_status(db, manifest_path)
        if after.status != "ready":
            raise CompetitionDemoSeedError(
                f"competition demo reset did not restore post-data overlay: {after.issues}"
            )
        record_audit(
            db, actor_public_id=before.identity_bindings.get("usr-demo-admin"), action=RESET_ACTION,
            object_type="demo_scope", object_id=manifest["demo_scope"], trace_id=TRACE_ID,
            metadata={
                "before_status": before.status,
                "after_status": after.status,
                "deleted_counts": {},
                "no_change": before.status == "ready",
            },
        )
        db.commit()
        return CompetitionDemoResetResult(before.status, after.status, {}, seed_result)

    deleted: dict[str, int] = {}
    try:
        bindings: dict[str, str] = {}
        for spec in manifest["users"]:
            user, _created, _alias = _ensure_user(db, spec)
            bindings[spec["id"]] = user.public_id
        owner_id = bindings[manifest["focus_student"]["user_id"]]
        course_id = manifest["course"]["id"]
        class_id = manifest["cohort"]["class_id"]

        event_ids = [row.id for row in _demo_event_rows(db, manifest, bindings)]
        if event_ids:
            deleted["learning_events"] = _delete_count(db.query(DBLearningEvent).filter(DBLearningEvent.id.in_(event_ids)))

        username = next(item["username"] for item in manifest["users"] if item["id"] == manifest["focus_student"]["user_id"])
        review_ids = [row.id for row in db.query(DBReviewPlan).filter_by(student_id=username).all() if any(str(value).startswith("logical:demo-review-") for value in (row.similar_quiz_ids or []))]
        if review_ids:
            deleted["review_plans"] = _delete_count(db.query(DBReviewPlan).filter(DBReviewPlan.id.in_(review_ids)))
        deleted["wrong_questions"] = _delete_count(db.query(DBWrongQuestion).filter(DBWrongQuestion.notes.like("logical_id=demo-wrong-%")))
        deleted["quiz_records"] = _delete_count(db.query(DBQuizRecord).filter(DBQuizRecord.id.like("demo-quiz-record-%")))
        deleted["assessment_attempts"] = _delete_count(
            db.query(DBAssessmentAttempt).filter_by(owner_public_id=owner_id, course_id=course_id)
            .filter(DBAssessmentAttempt.id.like("demo-assessment-attempt-%"))
        )
        deleted["assessment_questions"] = _delete_count(
            db.query(DBAssessmentQuestion).filter_by(owner_public_id=owner_id, course_id=course_id)
            .filter(DBAssessmentQuestion.id.like("demo-assessment-lzz-rag-01-q%"))
        )

        artifact_ids = [row.id for row in db.query(DBArtifact).filter_by(owner_public_id=owner_id, course_id=course_id).filter(DBArtifact.id.like("demo-%")).all()]
        version_ids = [row.id for row in db.query(DBArtifactVersion).filter(DBArtifactVersion.artifact_id.in_(artifact_ids)).all()] if artifact_ids else []
        case_ids = [row.id for row in db.query(DBContentReviewCase).filter(DBContentReviewCase.artifact_id.in_(artifact_ids)).all()] if artifact_ids else []
        if case_ids:
            deleted["content_review_decisions"] = _delete_count(db.query(DBContentReviewDecision).filter(DBContentReviewDecision.review_case_id.in_(case_ids)))
            deleted["content_review_cases"] = _delete_count(db.query(DBContentReviewCase).filter(DBContentReviewCase.id.in_(case_ids)))
        if version_ids:
            deleted["publications"] = _delete_count(db.query(DBPublication).filter(DBPublication.artifact_version_id.in_(version_ids)))
            deleted["review_decisions"] = _delete_count(db.query(DBReviewDecision).filter(DBReviewDecision.artifact_version_id.in_(version_ids)))
        if artifact_ids:
            deleted["artifacts"] = _delete_count(db.query(DBArtifact).filter(DBArtifact.id.in_(artifact_ids)))
        deleted["generation_tasks"] = _delete_count(
            db.query(DBGenerationTask).filter_by(owner_public_id=owner_id, course_id=course_id)
            .filter((DBGenerationTask.id.like("demo-%")) | (DBGenerationTask.idempotency_key.like(f"{manifest['demo_scope']}:%")))
        )

        path_ids = [row.id for row in db.query(DBLearningPath).filter_by(owner_public_id=owner_id, course_id=course_id).filter(DBLearningPath.id.like("demo-%")).all()]
        if path_ids:
            deleted["path_nodes"] = _delete_count(db.query(DBPathNode).filter(DBPathNode.learning_path_id.in_(path_ids)))
            deleted["learning_paths"] = _delete_count(db.query(DBLearningPath).filter(DBLearningPath.id.in_(path_ids)))
        plan_ids = [row.id for row in db.query(DBPlanDraft).filter_by(owner_public_id=owner_id, course_id=course_id).filter(DBPlanDraft.id.like("demo-%")).all()]
        if plan_ids:
            deleted["plan_versions"] = _delete_count(db.query(DBPlanVersion).filter(DBPlanVersion.plan_draft_id.in_(plan_ids)))
            deleted["plan_drafts"] = _delete_count(db.query(DBPlanDraft).filter(DBPlanDraft.id.in_(plan_ids)))

        profile_rows = _demo_profile_rows(db, manifest, bindings)
        profile_ids = [row.id for row in profile_rows]
        if profile_ids:
            deleted["decision_records"] = _delete_count(db.query(DBDecisionRecord).filter(DBDecisionRecord.profile_snapshot_id.in_(profile_ids)))
            deleted["marketplace_recommendations"] = _delete_count(db.query(DBMarketplaceRecommendationRun).filter(DBMarketplaceRecommendationRun.profile_snapshot_id.in_(profile_ids)))
            deleted["profile_snapshots"] = _delete_count(db.query(DBProfileSnapshot).filter(DBProfileSnapshot.id.in_(profile_ids)))

        deleted["teaching_analytics"] = _delete_count(db.query(DBTeachingAnalyticsReport).filter_by(class_id=class_id))
        deleted["teaching_tasks"] = _delete_count(db.query(DBTeachingTask).filter_by(class_id=class_id))
        deleted["teaching_groups"] = _delete_count(db.query(DBTeachingGroup).filter_by(class_id=class_id))
        deleted["class_members"] = _delete_count(db.query(DBTeachingClassMember).filter_by(class_id=class_id))
        deleted["course_memberships"] = _delete_count(db.query(DBCourseMembership).filter_by(course_id=course_id))

        # Keep the lzz legacy profile in place. It owns notes, reviews, quiz
        # records and wrong questions from the independent post-data baseline;
        # seed_competition_demo repairs its visible fields after the core reset.

        classroom = db.get(DBTeachingClass, class_id)
        if classroom is not None:
            classroom.title = manifest["cohort"]["title"]
            classroom.term = "2026 比赛演示"
            classroom.owner_public_id = bindings[manifest["cohort"]["teacher_user_id"]]
            classroom.status = "active"
            classroom.lock_version = 1
        db.flush()
        # Bulk deletes bypass the ORM identity map. Detach stale instances so
        # the idempotent seed observes the transactional database state.
        db.expunge_all()

        seed_result = seed_competition_demo(db, manifest_path)
        after = competition_demo_status(db, manifest_path)
        if after.status != "ready":
            raise CompetitionDemoSeedError(f"competition demo reset did not restore initial state: {after.issues}")
        record_audit(
            db, actor_public_id=bindings.get("usr-demo-admin"), action=RESET_ACTION,
            object_type="demo_scope", object_id=manifest["demo_scope"], trace_id=TRACE_ID,
            metadata={"before_status": before.status, "after_status": after.status, "deleted_counts": deleted, "manifest_sha256": after.manifest_sha256},
        )
        db.commit()
        return CompetitionDemoResetResult(before.status, after.status, deleted, seed_result)
    except Exception:
        db.rollback()
        raise


def seed_competition_demo(db: Any, manifest_path: Path | str = DEFAULT_MANIFEST_PATH) -> CompetitionDemoSeedResult:
    manifest = load_competition_demo_manifest(manifest_path)
    manifest_sha256 = _hash(manifest)
    created = 0
    repaired = 0
    try:
        ensure_post_data_course(db)
        _course, was_created = _ensure_course(db, manifest)
        created += int(was_created)
        created += _ensure_sources(db, manifest)
        created += _ensure_course_structure(db, manifest)
        bindings, people_created, alias_count = _ensure_people_and_class(db, manifest)
        created += people_created
        created += _ensure_profiles(db, manifest, bindings)
        owner_id = bindings[manifest["focus_student"]["user_id"]]
        teacher_id = bindings[manifest["cohort"]["teacher_user_id"]]
        created += _ensure_artifacts(db, manifest, owner_id)
        created += _ensure_assessment_and_review(
            db, manifest, owner_id,
            next(item["username"] for item in manifest["users"] if item["id"] == manifest["focus_student"]["user_id"]),
        )
        created += _ensure_plan_path(db, manifest, owner_id, teacher_id)
        created += _ensure_events(db, manifest, bindings)
        created += ensure_post_data_overlay(
            db,
            owner=db.query(DBUser).filter_by(public_id=owner_id).one(),
        )
        object_counts = _object_counts(db, manifest, bindings)
        existing_record = db.query(DBAuditLog).filter_by(
            action=SEED_ACTION, object_type="demo_scope", object_id=manifest["demo_scope"],
        ).first()
        metadata = {
            "manifest_version": manifest["manifest_version"], "manifest_sha256": manifest_sha256,
            "identity_bindings": bindings, "identity_alias_count": alias_count,
            "object_counts": object_counts, "truthfulness": manifest["truthfulness"]["data_kind"],
        }
        if existing_record is None:
            record_audit(
                db, actor_public_id=bindings.get("usr-demo-admin"), action=SEED_ACTION,
                object_type="demo_scope", object_id=manifest["demo_scope"], trace_id=TRACE_ID,
                metadata=metadata,
            )
        else:
            previous_hash = _audit_context(existing_record).get("manifest_sha256")
            if previous_hash != manifest_sha256:
                raise CompetitionDemoSeedError("existing demo seed record belongs to another manifest")
            repaired = created
            if repaired:
                record_audit(
                    db, actor_public_id=bindings.get("usr-demo-admin"), action=REPAIR_ACTION,
                    object_type="demo_scope", object_id=manifest["demo_scope"], trace_id=TRACE_ID,
                    metadata={"manifest_version": manifest["manifest_version"], "manifest_sha256": manifest_sha256, "repaired_count": repaired, "object_counts": object_counts},
                )
        db.commit()
        return CompetitionDemoSeedResult(
            demo_scope=manifest["demo_scope"], manifest_version=manifest["manifest_version"],
            manifest_sha256=manifest_sha256, created_count=created, repaired_count=repaired,
            identity_bindings=bindings, object_counts=object_counts,
            status="created" if created and existing_record is None else "repaired" if repaired else "unchanged",
        )
    except Exception:
        db.rollback()
        raise
