"""Structured M2 generation adapter and formal artifact persistence."""

from __future__ import annotations

import json
from typing import Any

from app.database import (
    DBArtifact,
    DBArtifactVersion,
    DBCourseDocument,
    DBGenerationTask,
    DBProfileSnapshot,
    DBSourceDocument,
    DBSourceRef,
    DBTaskEvent,
    DBTaskStep,
)
from app.m1_repository import add_artifact_version, create_artifact_with_version
from app.m2_context import assemble_verified_context
from app.m2_contracts import (
    GenerationContext,
    LabGuideArtifact,
    LessonArtifact,
    M2Artifact,
    M2Capability,
    TieredQuizArtifact,
    validate_m2_artifact,
)
from app.m2_tasks import M2_GOLDEN_CAPABILITY, complete_task_step


CAPABILITY_SEQUENCE = {
    M2Capability.LESSON: 1,
    M2Capability.LAB_GUIDE: 2,
    M2Capability.TIERED_QUIZ: 3,
}
CAPABILITY_ROLE = {
    M2Capability.LESSON: "理论教授",
    M2Capability.LAB_GUIDE: "极客助教",
    M2Capability.TIERED_QUIZ: "考官智能体",
}
CAPABILITY_MODEL = {
    M2Capability.LESSON: LessonArtifact,
    M2Capability.LAB_GUIDE: LabGuideArtifact,
    M2Capability.TIERED_QUIZ: TieredQuizArtifact,
}


class M2ArtifactGenerationError(ValueError):
    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(message)


def _fail(code: str, message: str) -> None:
    raise M2ArtifactGenerationError(code, message)


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _source_material(session: Any, context: GenerationContext) -> list[dict[str, str]]:
    rows = (
        session.query(DBSourceRef, DBSourceDocument, DBCourseDocument)
        .join(DBSourceDocument, DBSourceDocument.id == DBSourceRef.source_document_id)
        .join(DBCourseDocument, DBCourseDocument.id == DBSourceDocument.legacy_document_id)
        .filter(DBSourceRef.id.in_(context.source_ref_ids))
        .all()
    )
    by_id = {}
    for source_ref, source, course_document in rows:
        start = max(0, int(source_ref.char_start or 0))
        end = int(source_ref.char_end or len(course_document.content or ""))
        excerpt = (course_document.content or "")[start:end].strip()
        by_id[source_ref.id] = {
            "source_ref_id": source_ref.id,
            "title": source.title,
            "content_hash": source_ref.content_hash,
            "excerpt": excerpt[:6000],
        }
    if set(by_id) != set(context.source_ref_ids):
        _fail("source_material_missing", "verified source content is unavailable")
    return [by_id[source_id] for source_id in context.source_ref_ids]


def validate_artifact_scope(artifact: M2Artifact, context: GenerationContext) -> None:
    source_ids: list[str] = []
    knowledge_ids: list[str] = []
    if isinstance(artifact, LessonArtifact):
        for section in artifact.sections:
            source_ids.extend(section.source_ref_ids)
            knowledge_ids.extend(section.knowledge_point_ids)
    elif isinstance(artifact, LabGuideArtifact):
        for step in artifact.steps:
            source_ids.extend(step.source_ref_ids)
    elif isinstance(artifact, TieredQuizArtifact):
        for tier in artifact.tiers:
            for question in tier.questions:
                source_ids.extend(question.source_ref_ids)
                knowledge_ids.extend(question.knowledge_point_ids)
    if not set(source_ids).issubset(set(context.source_ref_ids)):
        _fail("artifact_source_out_of_scope", "artifact cites a source outside the verified context")
    if knowledge_ids and not set(knowledge_ids).issubset(set(context.target_knowledge_point_ids)):
        _fail("artifact_knowledge_out_of_scope", "artifact targets a knowledge point outside the verified context")
    if knowledge_ids and not set(context.target_knowledge_point_ids).issubset(set(knowledge_ids)):
        _fail("artifact_target_incomplete", "artifact does not cover every verified target knowledge point")


class M2StructuredArtifactGenerator:
    def __init__(self, llm: Any):
        self.llm = llm

    async def generate(
        self,
        session: Any,
        *,
        capability: M2Capability | str,
        context: GenerationContext,
    ) -> M2Artifact:
        capability_value = M2Capability(capability)
        verified = assemble_verified_context(
            session,
            **context.model_dump(exclude={"quality_mode"}),
        )
        snapshot = session.query(DBProfileSnapshot).filter_by(
            id=verified.profile_snapshot_id
        ).one()
        model = CAPABILITY_MODEL[capability_value]
        schema = model.model_json_schema()
        system_prompt = (
            f"你是 EduMatrix 的{CAPABILITY_ROLE[capability_value]}。"
            "只输出一个符合给定 JSON Schema 的原始 JSON 对象，不要输出 Markdown 代码围栏或解释。"
            "只能引用提供的 source_ref_id 和 target_knowledge_point_id。"
            "不得虚构运行结果、掌握结论或来源。"
            f"JSON Schema: {_canonical_json(schema)}"
        )
        profile_summary = {
            "profile_probe": (snapshot.snapshot or {}).get("profile_probe", {}),
            "target_knowledge_point": (snapshot.snapshot or {}).get("target_knowledge_point", {}),
        }
        user_prompt = _canonical_json(
            {
                "capability": capability_value.value,
                "context": verified.model_dump(mode="json"),
                "profile_summary": profile_summary,
                "sources": _source_material(session, verified),
            }
        )
        raw = await self.llm.generate(
            system_prompt,
            user_prompt,
            role=CAPABILITY_ROLE[capability_value],
        )
        try:
            payload = json.loads(raw)
        except (TypeError, json.JSONDecodeError) as exc:
            raise M2ArtifactGenerationError(
                "invalid_generator_json", "generator did not return a raw JSON object"
            ) from exc
        try:
            artifact = validate_m2_artifact(capability_value, payload)
        except (ValueError, TypeError) as exc:
            raise M2ArtifactGenerationError(
                "artifact_schema_invalid", "generator output failed the M2 artifact contract"
            ) from exc
        validate_artifact_scope(artifact, verified)
        return artifact


def persist_generated_artifact(
    session: Any,
    *,
    task_id: str,
    context: GenerationContext,
    capability: M2Capability | str,
    artifact: M2Artifact | dict[str, Any],
) -> tuple[DBArtifact, DBArtifactVersion, bool]:
    capability_value = M2Capability(capability)
    verified = assemble_verified_context(
        session,
        **context.model_dump(exclude={"quality_mode"}),
    )
    validated = validate_m2_artifact(capability_value, artifact)
    validate_artifact_scope(validated, verified)
    task = session.query(DBGenerationTask).filter_by(id=task_id).first()
    if (
        task is None
        or task.owner_public_id != verified.owner_public_id
        or task.course_id != verified.course_id
        or task.capability != M2_GOLDEN_CAPABILITY
    ):
        _fail("task_context_mismatch", "artifact task does not match the verified context")
    context_event = session.query(DBTaskEvent).filter_by(
        task_id=task.id, event_type="m2.context.verified"
    ).first()
    if context_event is None or (context_event.payload or {}).get("context") != verified.model_dump(mode="json"):
        _fail("task_context_mismatch", "task does not persist the verified artifact context")
    sequence = CAPABILITY_SEQUENCE[capability_value]
    latest_step = (
        session.query(DBTaskStep)
        .filter_by(task_id=task.id, sequence=sequence)
        .order_by(DBTaskStep.attempt.desc())
        .first()
    )
    if latest_step is None or latest_step.tool_name != capability_value.value:
        _fail("task_step_mismatch", "artifact capability does not match the persistent task step")

    content = _canonical_json(validated.model_dump(mode="json"))
    metadata = {
        "schema_version": validated.schema_version,
        "quality_mode": verified.quality_mode,
        "profile_snapshot_id": verified.profile_snapshot_id,
        "domain_version_id": verified.domain_version_id,
        "target_knowledge_point_ids": verified.target_knowledge_point_ids,
        "source_ref_ids": verified.source_ref_ids,
        "trace_id": task.trace_id,
        "sensitive_fields": (
            ["tiers.questions.answer_key", "tiers.questions.explanation"]
            if isinstance(validated, TieredQuizArtifact)
            else []
        ),
    }
    existing = session.query(DBArtifact).filter_by(
        creating_task_id=task.id,
        artifact_type=validated.artifact_type,
    ).first()
    if existing is not None:
        version = session.query(DBArtifactVersion).filter_by(id=existing.current_version_id).one()
        version_created = False
        if version.content != content:
            if latest_step.attempt <= 1 or latest_step.status != "running":
                _fail("artifact_replay_conflict", "task already has different content for this artifact type")
            version = add_artifact_version(
                session,
                artifact=existing,
                content=content,
                content_format="json",
                created_by_public_id=verified.owner_public_id,
                created_task_id=task.id,
                metadata=metadata,
            )
            version_created = True
        complete_task_step(
            session,
            task_id=task.id,
            owner_public_id=verified.owner_public_id,
            sequence=sequence,
            output_artifact_version_id=version.id,
        )
        return existing, version, version_created
    created, version = create_artifact_with_version(
        session,
        owner_public_id=verified.owner_public_id,
        artifact_type=validated.artifact_type,
        title=validated.title,
        content=content,
        content_format="json",
        course_id=verified.course_id,
        creating_task_id=task.id,
        metadata=metadata,
    )
    complete_task_step(
        session,
        task_id=task.id,
        owner_public_id=verified.owner_public_id,
        sequence=sequence,
        output_artifact_version_id=version.id,
    )
    session.flush()
    return created, version, True
