"""Persistent three-profile baseline fixtures for the M3 comparison loop."""

from __future__ import annotations

import hashlib
import json
import secrets
from typing import Any

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
from app.m2_baseline import M2_BASELINE_COURSE_ID
from app.m2_context import assemble_verified_context
from app.m2_contracts import GenerationContext, StrictModel
from app.m3_profiles import M3GoldProfile, load_m3_gold_profiles
from course_catalog import load_m0_course_bundle, upsert_course_bundle


M3_PROFILE_VERSION = "m3.profile.gold.v1"
M3_TARGET_KNOWLEDGE_POINT_CODES = ("KP-11", "KP-12", "KP-13")

_IDENTITIES = {
    "profile-m0-beginner": (
        "usr-m3-gold-beginner-v1",
        "m3-gold-beginner",
        "ps-m3-gold-beginner-v1",
        "trace-m3-gold-beginner-v1",
    ),
    "profile-m0-theory": (
        "usr-m3-gold-theory-v1",
        "m3-gold-theory",
        "ps-m3-gold-theory-v1",
        "trace-m3-gold-theory-v1",
    ),
    "profile-m0-advanced": (
        "usr-m3-gold-advanced-v1",
        "m3-gold-advanced",
        "ps-m3-gold-advanced-v1",
        "trace-m3-gold-advanced-v1",
    ),
}


class M3ProfileBaselineFixture(StrictModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    gold_profile: M3GoldProfile
    trace_id: str
    generation_context: GenerationContext


class M3ProfileBaselineSet(StrictModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    fixtures: tuple[M3ProfileBaselineFixture, ...]


def _canonical_hash(value: Any) -> str:
    raw = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _ensure_user(session: Any, profile: M3GoldProfile) -> tuple[DBUser, str, str]:
    public_id, username, snapshot_id, trace_id = _IDENTITIES[profile.source_profile.profile_id]
    user = session.query(DBUser).filter_by(public_id=public_id).first()
    username_owner = session.query(DBUser).filter_by(username=username).first()
    if username_owner is not None and username_owner.public_id != public_id:
        raise ValueError(f"M3 gold username is already occupied: {username}")
    if user is None:
        user = DBUser(
            public_id=public_id,
            username=username,
            hashed_password=get_password_hash(secrets.token_urlsafe(48)),
            role="student",
            display_name=f"M3 {profile.source_profile.label}",
            is_active=True,
        )
        session.add(user)
        session.flush()
    elif user.username != username:
        raise ValueError(f"M3 gold public ID is already occupied: {public_id}")
    return user, snapshot_id, trace_id


def _teaching_sources(session: Any, target_ids: list[str]) -> tuple[list[str], list[str]]:
    rows = (
        session.query(DBSourceRef, DBChapter, DBChapterKnowledgePoint)
        .join(DBSourceDocument, DBSourceDocument.id == DBSourceRef.source_document_id)
        .join(DBChapter, DBChapter.id == DBSourceRef.chapter_id)
        .join(DBChapterKnowledgePoint, DBChapterKnowledgePoint.chapter_id == DBChapter.id)
        .filter(
            DBSourceDocument.course_id == M2_BASELINE_COURSE_ID,
            DBChapterKnowledgePoint.knowledge_point_id.in_(target_ids),
            DBChapterKnowledgePoint.relation_type == "teaches",
        )
        .order_by(DBChapter.position, DBSourceRef.id)
        .all()
    )
    covered = {relation.knowledge_point_id for _ref, _chapter, relation in rows}
    if covered != set(target_ids):
        raise ValueError("M3 shared target is not fully covered by formal course sources")
    source_ref_ids = list(dict.fromkeys(ref.id for ref, _chapter, _relation in rows))
    chapter_ids = list(dict.fromkeys(chapter.id for _ref, chapter, _relation in rows))
    return source_ref_ids, chapter_ids


def seed_m3_profile_baselines(session: Any) -> M3ProfileBaselineSet:
    """Create or verify the three immutable M3 comparison contexts."""
    upsert_course_bundle(session, load_m0_course_bundle())
    domain = seed_rag_domain_pack(session)
    profile_set = load_m3_gold_profiles()

    points = (
        session.query(DBKnowledgePoint)
        .filter(
            DBKnowledgePoint.domain_pack == "domain-rag-0.1",
            DBKnowledgePoint.version == "kp-rag-0.1",
            DBKnowledgePoint.code.in_(M3_TARGET_KNOWLEDGE_POINT_CODES),
        )
        .all()
    )
    points_by_code = {point.code: point for point in points}
    if set(points_by_code) != set(M3_TARGET_KNOWLEDGE_POINT_CODES):
        raise ValueError("M3 shared target knowledge points are incomplete")
    target_ids = [points_by_code[code].id for code in M3_TARGET_KNOWLEDGE_POINT_CODES]
    source_ref_ids, chapter_ids = _teaching_sources(session, target_ids)

    fixtures = []
    for gold_profile in profile_set.profiles:
        user, snapshot_id, trace_id = _ensure_user(session, gold_profile)
        membership_id = f"cm-{user.public_id.removeprefix('usr-')}"
        membership = session.query(DBCourseMembership).filter_by(
            course_id=M2_BASELINE_COURSE_ID,
            user_public_id=user.public_id,
        ).first()
        if membership is None:
            session.add(
                DBCourseMembership(
                    id=membership_id,
                    course_id=M2_BASELINE_COURSE_ID,
                    user_public_id=user.public_id,
                    role="student",
                    status="active",
                )
            )
        else:
            membership.role = "student"
            membership.status = "active"

        source = gold_profile.source_profile
        snapshot_data = {
            "schema_version": M3_PROFILE_VERSION,
            "source_profile_version": profile_set.source_schema_version,
            "source_profile_sha256": profile_set.source_sha256,
            "source_profile_id": source.profile_id,
            "source_student_id": source.student_id,
            "synthetic_data": True,
            "course_id": M2_BASELINE_COURSE_ID,
            "domain_version_id": str(domain["domain_version_id"]),
            "shared_job_task_id": gold_profile.shared_job_task_id,
            "focus_knowledge_point_ids": target_ids,
            "focus_knowledge_point_codes": list(M3_TARGET_KNOWLEDGE_POINT_CODES),
            "initial_mastery": source.initial_mastery,
            "ability_vector": gold_profile.ability_vector.model_dump(mode="json"),
            "adaptation_strategy": gold_profile.adaptation_strategy.model_dump(mode="json"),
            "evidence": list(source.evidence),
            "planning_constraints": {
                "allowed_chapter_ids": chapter_ids,
                "source_ref_ids": source_ref_ids,
                "available_artifact_types": ["lesson", "lab_guide", "tiered_quiz"],
            },
        }
        content_hash = _canonical_hash(snapshot_data)
        snapshot = session.query(DBProfileSnapshot).filter_by(id=snapshot_id).first()
        if snapshot is None:
            snapshot = DBProfileSnapshot(
                id=snapshot_id,
                owner_public_id=user.public_id,
                profile_version=M3_PROFILE_VERSION,
                snapshot=snapshot_data,
                content_hash=content_hash,
                trace_id=trace_id,
            )
            session.add(snapshot)
        elif (
            snapshot.owner_public_id != user.public_id
            or snapshot.profile_version != M3_PROFILE_VERSION
            or snapshot.snapshot != snapshot_data
            or snapshot.content_hash != content_hash
            or snapshot.trace_id != trace_id
        ):
            raise ValueError(f"M3 gold profile snapshot is immutable: {snapshot_id}")
        session.flush()

        context = assemble_verified_context(
            session,
            owner_public_id=user.public_id,
            course_id=M2_BASELINE_COURSE_ID,
            domain_version_id=str(domain["domain_version_id"]),
            profile_snapshot_id=snapshot.id,
            target_knowledge_point_ids=target_ids,
            source_ref_ids=source_ref_ids,
        )
        fixtures.append(
            M3ProfileBaselineFixture(
                gold_profile=gold_profile,
                trace_id=trace_id,
                generation_context=context,
            )
        )
    session.commit()
    return M3ProfileBaselineSet(fixtures=tuple(fixtures))


def seed_m3_profile_for_owner(
    session: Any,
    *,
    owner_public_id: str,
    source_profile_id: str,
) -> M3ProfileBaselineFixture:
    """Bind a frozen synthetic benchmark archetype to an authenticated owner."""
    owner = session.query(DBUser).filter_by(public_id=owner_public_id, is_active=True).first()
    if owner is None:
        raise ValueError("active M3 profile owner does not exist")
    fixed = seed_m3_profile_baselines(session)
    source_fixture = next(
        (
            fixture
            for fixture in fixed.fixtures
            if fixture.gold_profile.source_profile.profile_id == source_profile_id
        ),
        None,
    )
    if source_fixture is None:
        raise ValueError("unknown M3 gold profile")
    source_context = source_fixture.generation_context
    source_snapshot = session.query(DBProfileSnapshot).filter_by(
        id=source_context.profile_snapshot_id
    ).one()
    identity = hashlib.sha256(
        f"{owner_public_id}\x1f{source_profile_id}\x1f{M3_PROFILE_VERSION}".encode("utf-8")
    ).hexdigest()[:24]
    snapshot_id = f"ps-m3-owner-{identity}"
    trace_id = f"trace-m3-owner-{identity}"
    membership = session.query(DBCourseMembership).filter_by(
        course_id=M2_BASELINE_COURSE_ID,
        user_public_id=owner_public_id,
    ).first()
    if membership is None:
        session.add(
            DBCourseMembership(
                id=f"cm-m3-owner-{identity}",
                course_id=M2_BASELINE_COURSE_ID,
                user_public_id=owner_public_id,
                role="student",
                status="active",
            )
        )
    else:
        membership.status = "active"
    snapshot = session.query(DBProfileSnapshot).filter_by(id=snapshot_id).first()
    if snapshot is None:
        snapshot = DBProfileSnapshot(
            id=snapshot_id,
            owner_public_id=owner_public_id,
            profile_version=M3_PROFILE_VERSION,
            snapshot=source_snapshot.snapshot,
            content_hash=source_snapshot.content_hash,
            trace_id=trace_id,
        )
        session.add(snapshot)
    elif (
        snapshot.owner_public_id != owner_public_id
        or snapshot.profile_version != M3_PROFILE_VERSION
        or snapshot.snapshot != source_snapshot.snapshot
        or snapshot.content_hash != source_snapshot.content_hash
        or snapshot.trace_id != trace_id
    ):
        raise ValueError("owner M3 gold profile snapshot is immutable")
    session.flush()
    context = assemble_verified_context(
        session,
        owner_public_id=owner_public_id,
        course_id=source_context.course_id,
        domain_version_id=source_context.domain_version_id,
        profile_snapshot_id=snapshot.id,
        target_knowledge_point_ids=source_context.target_knowledge_point_ids,
        source_ref_ids=source_context.source_ref_ids,
    )
    session.commit()
    return M3ProfileBaselineFixture(
        gold_profile=source_fixture.gold_profile,
        trace_id=trace_id,
        generation_context=context,
    )
