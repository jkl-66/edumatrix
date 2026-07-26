"""Reproducible baseline learner and weak-skill fixture for the M2 golden loop."""

from __future__ import annotations

import hashlib
import json
import secrets
from typing import Any, Literal

from pydantic import ConfigDict

from app.auth import get_password_hash
from app.database import (
    DBChapter,
    DBChapterKnowledgePoint,
    DBCourseMembership,
    DBKnowledgePoint,
    DBProfileSnapshot,
    DBSourceDocument,
    DBSourceRef,
    DBUser,
)
from app.m1_evidence import seed_rag_domain_pack
from app.m2_contracts import GenerationContext, StrictModel
from course_catalog import load_m0_course_bundle, upsert_course_bundle


M2_BASELINE_ID = "m2-golden-rag-v1"
M2_BASELINE_OWNER_PUBLIC_ID = "usr-m2-golden-learner-v1"
M2_BASELINE_USERNAME = "m2-golden-learner"
M2_BASELINE_COURSE_ID = "course-rag-engineering-m0"
M2_BASELINE_PROFILE_SNAPSHOT_ID = "ps-m2-golden-rag-v1"
M2_BASELINE_PROFILE_VERSION = "m2.profile.baseline.v1"
M2_BASELINE_TRACE_ID = "trace-m2-golden-rag-v1"
M2_TARGET_KNOWLEDGE_POINT_CODE = "KP-16"


class M2BaselineFixture(StrictModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, frozen=True)

    baseline_id: Literal["m2-golden-rag-v1"] = M2_BASELINE_ID
    trace_id: str
    generation_context: GenerationContext
    target_knowledge_point_code: str
    target_knowledge_point_title: str
    prerequisite_codes: list[str]
    allowed_chapter_ids: list[str]
    estimated_effort_range_minutes: tuple[int, int]
    required_artifact_types: tuple[Literal["lesson", "lab_guide", "tiered_quiz"], ...]


def _canonical_hash(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _baseline_user(session: Any) -> DBUser:
    user = session.query(DBUser).filter_by(public_id=M2_BASELINE_OWNER_PUBLIC_ID).first()
    username_owner = session.query(DBUser).filter_by(username=M2_BASELINE_USERNAME).first()
    if username_owner is not None and username_owner.public_id != M2_BASELINE_OWNER_PUBLIC_ID:
        raise ValueError("M2 baseline username is already owned by another user")
    if user is None:
        user = DBUser(
            public_id=M2_BASELINE_OWNER_PUBLIC_ID,
            username=M2_BASELINE_USERNAME,
            hashed_password=get_password_hash(secrets.token_urlsafe(48)),
            role="student",
            display_name="M2 基准学习者",
            is_active=True,
        )
        session.add(user)
        session.flush()
    elif user.username != M2_BASELINE_USERNAME:
        raise ValueError("M2 baseline public ID is already owned by another username")
    return user


def seed_m2_baseline(session: Any) -> M2BaselineFixture:
    """Create or verify the immutable M2 baseline on an empty or existing database."""
    upsert_course_bundle(session, load_m0_course_bundle())
    domain = seed_rag_domain_pack(session)
    user = _baseline_user(session)

    membership = session.query(DBCourseMembership).filter_by(
        course_id=M2_BASELINE_COURSE_ID,
        user_public_id=user.public_id,
    ).first()
    if membership is None:
        membership = DBCourseMembership(
            id="cm-m2-golden-rag-v1",
            course_id=M2_BASELINE_COURSE_ID,
            user_public_id=user.public_id,
            role="student",
            status="active",
        )
        session.add(membership)
    else:
        membership.role = "student"
        membership.status = "active"

    target = session.query(DBKnowledgePoint).filter_by(
        domain_pack="domain-rag-0.1",
        version="kp-rag-0.1",
        code=M2_TARGET_KNOWLEDGE_POINT_CODE,
    ).one()
    source_rows = (
        session.query(DBSourceRef, DBChapter)
        .join(DBSourceDocument, DBSourceDocument.id == DBSourceRef.source_document_id)
        .join(DBChapter, DBChapter.id == DBSourceRef.chapter_id)
        .join(DBChapterKnowledgePoint, DBChapterKnowledgePoint.chapter_id == DBChapter.id)
        .filter(
            DBSourceDocument.course_id == M2_BASELINE_COURSE_ID,
            DBChapterKnowledgePoint.knowledge_point_id == target.id,
            DBChapterKnowledgePoint.relation_type == "teaches",
        )
        .order_by(DBChapter.position, DBSourceRef.id)
        .all()
    )
    if not source_rows:
        raise ValueError("M2 target knowledge point has no course-readable source reference")

    source_ref_ids = [source_ref.id for source_ref, _chapter in source_rows]
    allowed_chapter_ids = [chapter.id for _source_ref, chapter in source_rows]
    snapshot_data = {
        "schema_version": M2_BASELINE_PROFILE_VERSION,
        "baseline_id": M2_BASELINE_ID,
        "course_id": M2_BASELINE_COURSE_ID,
        "domain_version_id": str(domain["domain_version_id"]),
        "weak_knowledge_point_ids": [target.id],
        "target_knowledge_point": {
            "id": target.id,
            "code": target.code,
            "title": target.title,
            "mastery": 0.35,
            "prerequisite_codes": list(target.prerequisites or []),
        },
        "profile_probe": {
            "knowledge_base": "foundation",
            "cognitive_style": "visual_and_code",
            "preferred_language": "zh-CN",
            "confidence": 0.8,
        },
        "planning_constraints": {
            "allowed_chapter_ids": allowed_chapter_ids,
            "source_ref_ids": source_ref_ids,
            "available_artifact_types": ["lesson", "lab_guide", "tiered_quiz"],
            "estimated_effort_range_minutes": [45, 75],
        },
    }
    content_hash = _canonical_hash(snapshot_data)
    snapshot = session.query(DBProfileSnapshot).filter_by(id=M2_BASELINE_PROFILE_SNAPSHOT_ID).first()
    if snapshot is None:
        snapshot = DBProfileSnapshot(
            id=M2_BASELINE_PROFILE_SNAPSHOT_ID,
            owner_public_id=user.public_id,
            profile_version=M2_BASELINE_PROFILE_VERSION,
            snapshot=snapshot_data,
            content_hash=content_hash,
            trace_id=M2_BASELINE_TRACE_ID,
        )
        session.add(snapshot)
    elif (
        snapshot.owner_public_id != user.public_id
        or snapshot.profile_version != M2_BASELINE_PROFILE_VERSION
        or snapshot.content_hash != content_hash
        or snapshot.snapshot != snapshot_data
        or snapshot.trace_id != M2_BASELINE_TRACE_ID
    ):
        raise ValueError("M2 baseline profile snapshot is immutable and does not match the frozen fixture")
    session.commit()

    context = GenerationContext(
        owner_public_id=user.public_id,
        course_id=M2_BASELINE_COURSE_ID,
        domain_version_id=str(domain["domain_version_id"]),
        profile_snapshot_id=snapshot.id,
        target_knowledge_point_ids=[target.id],
        source_ref_ids=source_ref_ids,
    )
    return M2BaselineFixture(
        trace_id=M2_BASELINE_TRACE_ID,
        generation_context=context,
        target_knowledge_point_code=target.code,
        target_knowledge_point_title=target.title,
        prerequisite_codes=list(target.prerequisites or []),
        allowed_chapter_ids=allowed_chapter_ids,
        estimated_effort_range_minutes=(45, 75),
        required_artifact_types=("lesson", "lab_guide", "tiered_quiz"),
    )
