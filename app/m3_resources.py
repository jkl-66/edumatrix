"""Profile-bound resource generation and persistence for the M3 comparison."""

from __future__ import annotations

import json
from typing import Annotated, Any, Literal, Union

from pydantic import ConfigDict, Field, TypeAdapter

from app.database import DBAgentRun, DBArtifact, DBArtifactVersion, DBGenerationTask, DBProfileSnapshot
from app.m1_repository import add_artifact_relation, create_artifact_with_version
from app.m2_artifacts import _source_material, validate_artifact_scope
from app.m2_context import assemble_verified_context
from app.m2_contracts import (
    GenerationContext,
    LabGuideArtifact,
    LessonArtifact,
    StrictModel,
    TieredQuizArtifact,
)
from app.m3_agents import (
    M3_COLLABORATION_CAPABILITY,
    M3AgentRole,
    complete_m3_agent_run,
    task_events,
)
from app.m3_profiles import M3GoldProfile, load_m3_gold_profiles


M3_RESOURCE_SET_TYPE = "m3_personalized_resource_set"


class M3ResourceError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _fail(code: str, message: str) -> None:
    raise M3ResourceError(code, message)


class PersonalizationEvidence(StrictModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    profile_snapshot_id: str
    difficulty_band: str
    scaffolding: Literal["high", "medium", "low"]
    terminology_density: Literal["low", "medium", "high"]
    step_granularity: Literal["short", "controlled", "open"]
    hint_policy: Literal["progressive", "on_failure", "minimal"]
    task_openness: Literal["guided", "bounded", "open"]
    quiz_emphasis: Literal["recognition_application", "application_debugging", "diagnosis_decision"]
    rationale_refs: tuple[str, ...] = Field(min_length=3)
    fact_standard: Literal["unchanged"] = "unchanged"
    safety_standard: Literal["unchanged"] = "unchanged"


class M3LessonArtifact(LessonArtifact):
    schema_version: Literal["m3.lesson.v1"] = "m3.lesson.v1"
    personalization: PersonalizationEvidence


class M3LabGuideArtifact(LabGuideArtifact):
    schema_version: Literal["m3.lab_guide.v1"] = "m3.lab_guide.v1"
    personalization: PersonalizationEvidence


class M3TieredQuizArtifact(TieredQuizArtifact):
    schema_version: Literal["m3.tiered_quiz.v1"] = "m3.tiered_quiz.v1"
    personalization: PersonalizationEvidence


M3PersonalizedArtifact = Annotated[
    Union[M3LessonArtifact, M3LabGuideArtifact, M3TieredQuizArtifact],
    Field(discriminator="artifact_type"),
]
M3_ARTIFACT_ADAPTER = TypeAdapter(M3PersonalizedArtifact)


class M3PersonalizedResourceBundle(StrictModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: Literal["m3.personalized_resource_bundle.v1"] = "m3.personalized_resource_bundle.v1"
    lesson: M3LessonArtifact
    lab_guide: M3LabGuideArtifact
    tiered_quiz: M3TieredQuizArtifact


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _gold_profile(snapshot: DBProfileSnapshot) -> M3GoldProfile:
    source_profile_id = (snapshot.snapshot or {}).get("source_profile_id")
    profile = next(
        (
            item
            for item in load_m3_gold_profiles().profiles
            if item.source_profile.profile_id == source_profile_id
        ),
        None,
    )
    if profile is None:
        _fail("profile_not_m3_gold", "snapshot is not one of the frozen M3 gold profiles")
    return profile


def expected_personalization(profile: M3GoldProfile, snapshot_id: str) -> PersonalizationEvidence:
    strategy = profile.adaptation_strategy
    return PersonalizationEvidence(
        profile_snapshot_id=snapshot_id,
        difficulty_band=strategy.difficulty_band,
        scaffolding=strategy.scaffolding,
        terminology_density=strategy.terminology_density,
        step_granularity=strategy.step_granularity,
        hint_policy=strategy.hint_policy,
        task_openness=strategy.task_openness,
        quiz_emphasis=strategy.quiz_emphasis,
        rationale_refs=strategy.rationale,
    )


def validate_m3_resource_bundle(
    bundle: M3PersonalizedResourceBundle | dict[str, Any],
    *,
    context: GenerationContext,
    profile: M3GoldProfile,
) -> M3PersonalizedResourceBundle:
    try:
        validated = M3PersonalizedResourceBundle.model_validate(bundle)
    except ValueError as exc:
        raise M3ResourceError("m3_resource_schema_invalid", str(exc)) from exc
    expected = expected_personalization(profile, context.profile_snapshot_id)
    artifacts = (validated.lesson, validated.lab_guide, validated.tiered_quiz)
    if any(artifact.personalization != expected for artifact in artifacts):
        _fail("personalization_evidence_mismatch", "resource personalization does not match the frozen profile strategy")
    for artifact in artifacts:
        validate_artifact_scope(artifact, context)

    if expected.scaffolding == "high" and len(validated.lab_guide.steps) < 4:
        _fail("personalization_structure_mismatch", "high scaffolding requires at least four short lab steps")
    if expected.task_openness == "open" and not any(
        question.bloom_level in {"evaluate", "create"}
        for tier in validated.tiered_quiz.tiers
        for question in tier.questions
    ):
        _fail("personalization_structure_mismatch", "open advanced work requires an evaluate/create question")
    if expected.quiz_emphasis == "recognition_application" and not any(
        question.bloom_level in {"remember", "understand"}
        for question in validated.tiered_quiz.tiers[0].questions
    ):
        _fail("personalization_structure_mismatch", "beginner foundation tier must include recognition or understanding")
    return validated


class M3PersonalizedResourceGenerator:
    def __init__(self, llm: Any):
        self.llm = llm

    async def generate(
        self,
        session: Any,
        *,
        context: GenerationContext,
    ) -> M3PersonalizedResourceBundle:
        verified = assemble_verified_context(session, **context.model_dump(exclude={"quality_mode"}))
        snapshot = session.query(DBProfileSnapshot).filter_by(id=verified.profile_snapshot_id).one()
        profile = _gold_profile(snapshot)
        expected = expected_personalization(profile, snapshot.id)
        system_prompt = (
            "你是 EduMatrix M3 领域生成角色。只输出符合 JSON Schema 的原始 JSON 对象，不要 Markdown 围栏。"
            "三类资源必须应用给定 personalization，不得改变事实、安全、隔离和岗位验收标准。"
            "只能引用提供的 target_knowledge_point_id 与 source_ref_id，不得声称学习者已经掌握。"
            f"JSON Schema: {_canonical_json(M3PersonalizedResourceBundle.model_json_schema())}"
        )
        user_prompt = _canonical_json(
            {
                "context": verified.model_dump(mode="json"),
                "profile": {
                    "source_profile_id": profile.source_profile.profile_id,
                    "ability_vector": profile.ability_vector.model_dump(mode="json"),
                    "personalization": expected.model_dump(mode="json"),
                },
                "sources": _source_material(session, verified),
            }
        )
        raw = await self.llm.generate(system_prompt, user_prompt, role="M3领域生成")
        try:
            payload = json.loads(raw)
        except (TypeError, json.JSONDecodeError) as exc:
            raise M3ResourceError("invalid_generator_json", "M3 generator did not return raw JSON") from exc
        return validate_m3_resource_bundle(payload, context=verified, profile=profile)


def persist_m3_resource_bundle(
    session: Any,
    *,
    task_id: str,
    context: GenerationContext,
    bundle: M3PersonalizedResourceBundle | dict[str, Any],
) -> tuple[DBArtifact, DBArtifactVersion, list[DBArtifact], bool]:
    verified = assemble_verified_context(session, **context.model_dump(exclude={"quality_mode"}))
    snapshot = session.query(DBProfileSnapshot).filter_by(id=verified.profile_snapshot_id).one()
    profile = _gold_profile(snapshot)
    validated = validate_m3_resource_bundle(bundle, context=verified, profile=profile)
    task = session.query(DBGenerationTask).filter_by(id=task_id).first()
    context_event = next((event for event in task_events(session, task_id) if event.event_type == "m3.context.verified"), None)
    if (
        task is None
        or task.capability != M3_COLLABORATION_CAPABILITY
        or task.owner_public_id != verified.owner_public_id
        or task.course_id != verified.course_id
        or context_event is None
        or (context_event.payload or {}).get("context") != verified.model_dump(mode="json")
    ):
        _fail("task_context_mismatch", "M3 resource task does not match verified context")
    run = session.query(DBAgentRun).filter_by(task_id=task.id, role=M3AgentRole.DOMAIN_GENERATION.value).first()
    if run is None or run.status not in {"running", "completed"}:
        _fail("domain_generation_not_running", "domain generation role must be running")

    expected_contents = {
        artifact.artifact_type: _canonical_json(artifact.model_dump(mode="json"))
        for artifact in (validated.lesson, validated.lab_guide, validated.tiered_quiz)
    }
    existing_rows = session.query(DBArtifact).filter_by(creating_task_id=task.id).all()
    existing = {row.artifact_type: row for row in existing_rows}
    if existing:
        required = {"lesson", "lab_guide", "tiered_quiz", M3_RESOURCE_SET_TYPE}
        if set(existing) != required:
            _fail("partial_resource_set", "M3 task has a partial resource set")
        resources = [existing[kind] for kind in ("lesson", "lab_guide", "tiered_quiz")]
        for resource in resources:
            version = session.query(DBArtifactVersion).filter_by(id=resource.current_version_id).one()
            if version.content != expected_contents[resource.artifact_type]:
                _fail("resource_replay_conflict", "M3 task already contains different resource content")
        manifest = existing[M3_RESOURCE_SET_TYPE]
        manifest_version = session.query(DBArtifactVersion).filter_by(id=manifest.current_version_id).one()
        return manifest, manifest_version, resources, False

    resources = []
    resource_versions = []
    personalization = expected_personalization(profile, snapshot.id)
    for artifact in (validated.lesson, validated.lab_guide, validated.tiered_quiz):
        resource, version = create_artifact_with_version(
            session,
            owner_public_id=verified.owner_public_id,
            artifact_type=artifact.artifact_type,
            title=artifact.title,
            content=expected_contents[artifact.artifact_type],
            content_format="json",
            course_id=verified.course_id,
            creating_task_id=task.id,
            metadata={
                "schema_version": artifact.schema_version,
                "profile_snapshot_id": snapshot.id,
                "domain_version_id": verified.domain_version_id,
                "target_knowledge_point_ids": verified.target_knowledge_point_ids,
                "source_ref_ids": verified.source_ref_ids,
                "trace_id": task.trace_id,
                "personalization": personalization.model_dump(mode="json"),
                "fact_standard": "unchanged",
                "safety_standard": "unchanged",
                "sensitive_fields": ["tiers.questions.answer_key", "tiers.questions.explanation"] if artifact.artifact_type == "tiered_quiz" else [],
            },
        )
        resources.append(resource)
        resource_versions.append(version)

    manifest_content = _canonical_json(
        {
            "schema_version": "m3.personalized_resource_set.v1",
            "task_id": task.id,
            "trace_id": task.trace_id,
            "profile_snapshot_id": snapshot.id,
            "source_profile_id": profile.source_profile.profile_id,
            "resource_version_ids": [version.id for version in resource_versions],
            "personalization": personalization.model_dump(mode="json"),
        }
    )
    manifest, manifest_version = create_artifact_with_version(
        session,
        owner_public_id=verified.owner_public_id,
        artifact_type=M3_RESOURCE_SET_TYPE,
        title=f"M3 个性化资源集 - {profile.source_profile.label}",
        content=manifest_content,
        content_format="json",
        course_id=verified.course_id,
        creating_task_id=task.id,
        metadata={
            "profile_snapshot_id": snapshot.id,
            "trace_id": task.trace_id,
            "contains_artifact_ids": [resource.id for resource in resources],
        },
    )
    for resource in resources:
        add_artifact_relation(
            session,
            source_artifact_id=manifest.id,
            target_artifact_id=resource.id,
            relation_type="contains",
            created_by_public_id=verified.owner_public_id,
        )
    if run.status == "running":
        complete_m3_agent_run(
            session,
            task_id=task.id,
            owner_public_id=verified.owner_public_id,
            role=M3AgentRole.DOMAIN_GENERATION,
            output_artifact_version_id=manifest_version.id,
        )
    session.flush()
    return manifest, manifest_version, resources, True
