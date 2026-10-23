"""Profile-bound resource generation and persistence for the M3 comparison."""

from __future__ import annotations

import json
from typing import Annotated, Any, Literal, Union

from pydantic import ConfigDict, Field, TypeAdapter

from app.database import DBAgentRun, DBArtifact, DBArtifactVersion, DBGenerationTask, DBProfileSnapshot
from app.m5_capabilities import Capability, M5CapabilityError, OutputConstraints
from app.m5_gateway import execute_registered_structured_call
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
from llm_client import describe_structured_output, parse_json_object


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
        _validate_personalization_structure(artifact, expected)

    return validated


def _validate_personalization_structure(
    artifact: M3PersonalizedArtifact,
    expected: PersonalizationEvidence,
) -> None:
    if artifact.artifact_type == "lesson":
        if expected.quiz_emphasis == "application_debugging" and not artifact.retrieval_questions:
            _fail(
                "personalization_structure_mismatch",
                "application_debugging requires at least one lesson retrieval question for a concrete debugging check",
            )
        return

    if artifact.artifact_type == "lab_guide":
        if expected.scaffolding == "high":
            if len(artifact.steps) < 4:
                _fail(
                    "personalization_structure_mismatch",
                    "high scaffolding requires at least four short lab steps",
                )
            if any(not step.command_or_action.strip() for step in artifact.steps):
                _fail(
                    "personalization_structure_mismatch",
                    "high scaffolding requires a concrete runnable command_or_action for every lab step",
                )
        return

    if expected.task_openness == "open" and not any(
        question.bloom_level in {"evaluate", "create"}
        for tier in artifact.tiers
        for question in tier.questions
    ):
        _fail("personalization_structure_mismatch", "open advanced work requires an evaluate/create question")
    if expected.quiz_emphasis == "recognition_application" and not any(
        question.bloom_level in {"remember", "understand"}
        for question in artifact.tiers[0].questions
    ):
        _fail("personalization_structure_mismatch", "beginner foundation tier must include recognition or understanding")


class M3PersonalizedResourceGenerator:
    def __init__(self, llm: Any):
        self.llm = llm

    async def generate(
        self,
        session: Any,
        *,
        context: GenerationContext,
        task_id: str | None = None,
    ) -> M3PersonalizedResourceBundle:
        verified = assemble_verified_context(session, **context.model_dump(exclude={"quality_mode"}))
        snapshot = session.query(DBProfileSnapshot).filter_by(id=verified.profile_snapshot_id).one()
        profile = _gold_profile(snapshot)
        expected = expected_personalization(profile, snapshot.id)
        task = session.query(DBGenerationTask).filter_by(id=task_id).first() if task_id else None
        trace_id = task.trace_id if task is not None else None
        system_prompt = (
            "你是 EduMatrix M3 领域生成角色。只输出符合 JSON Schema 的原始 JSON 对象，不要 Markdown 围栏。"
            "三类资源必须应用给定 personalization，不得改变事实、安全、隔离和岗位验收标准。"
            "只能引用提供的 target_knowledge_point_id 与 source_ref_id，不得声称学习者已经掌握。"
            "个性化必须落实到正文而非只复制 metadata：high scaffolding 的 lab_guide 至少四个短步骤，"
            "每一步 command_or_action 都要给可直接照做的命令、代码模板或具体操作；"
            "application_debugging 的 lesson.retrieval_questions 至少包含一个可实际检查的应用或调试问题。"
            "tiered_quiz.tiers 必须按 foundation、application、advanced 恰好三层且各层至少一个题目；"
            "tiered_quiz.pass_rules 必须是恰好包含 foundation、application、advanced 三个键的对象。"
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
        validation_error: M3ResourceError | None = None
        for attempt in range(2):
            prompt = user_prompt
            if validation_error is not None:
                repair_instruction = "Regenerate the complete object. Do not omit or rename required fields."
                if "pass_rules must cover all three tiers" in str(validation_error):
                    repair_instruction = (
                        "Regenerate the complete object. Set tiered_quiz.pass_rules to an object with exactly "
                        "these three keys: foundation, application, advanced; each value must be a string."
                    )
                prompt = _canonical_json(
                    {
                        "original_request": json.loads(user_prompt),
                        "validation_feedback": {
                            "code": validation_error.code,
                            "message": str(validation_error),
                            "instruction": repair_instruction,
                        },
                    }
                )
            try:
                result = await execute_registered_structured_call(
                    session,
                    backend=self.llm,
                    capability=Capability.REPORT,
                    system_prompt=system_prompt,
                    user_prompt=prompt,
                    role="M3领域生成",
                    operation=f"m3_resource_bundle_attempt_{attempt + 1}",
                    response_model=M3PersonalizedResourceBundle,
                    response_validator=lambda payload: validate_m3_resource_bundle(payload, context=verified, profile=profile),
                    owner_public_id=context.owner_public_id,
                    course_id=context.course_id,
                    task_id=task_id,
                    trace_id=trace_id,
                )
                return M3PersonalizedResourceBundle.model_validate(result.structured_output)
            except M5CapabilityError as exc:
                diagnostics = json.dumps({"gateway_error": exc.code}, sort_keys=True)
                cause = exc.__cause__
                validation_error = M3ResourceError(
                    "invalid_generator_json" if not isinstance(cause, M3ResourceError) else cause.code,
                    str(cause) if isinstance(cause, M3ResourceError)
                    else f"M3 generator failed strict output validation; shape={diagnostics}",
                )
                if exc.code == "structured_output_invalid" and not isinstance(exc.__cause__, M3ResourceError):
                    break
                if attempt == 1:
                    break

        # Some providers are reliable for small JSON objects but truncate a
        # complete three-resource bundle. Generate each contract separately,
        # then apply the same aggregate validation before persistence.
        artifacts: dict[str, Any] = {}
        split_models = (
            ("lesson", M3LessonArtifact),
            ("lab_guide", M3LabGuideArtifact),
            ("tiered_quiz", M3TieredQuizArtifact),
        )
        base_request = json.loads(user_prompt)
        for artifact_type, model in split_models:
            split_system = (
                f"你是 EduMatrix M3 领域生成角色。只输出一个 {artifact_type} JSON 对象，不要 Markdown 围栏或解释。"
                "必须原样应用提供的 personalization；只能引用提供的 target_knowledge_point_id 和 source_ref_id。"
                "不得改变事实、安全、隔离和岗位验收标准，不得声称学习者已经掌握。"
                + (
                    "若 personalization.scaffolding=high，至少生成四个短步骤，且每一步 command_or_action "
                    "都必须是学习者可直接照做的命令、代码模板或具体操作。"
                    if artifact_type == "lab_guide"
                    else ""
                )
                + (
                    "若 personalization.quiz_emphasis=application_debugging，retrieval_questions 至少包含一个"
                    "可实际检查的应用或调试问题。"
                    if artifact_type == "lesson"
                    else ""
                )
                + (
                    "tiers 必须按 foundation、application、advanced 恰好三层，pass_rules 必须恰好包含这三个键。"
                    if artifact_type == "tiered_quiz"
                    else ""
                )
                + f" JSON Schema: {_canonical_json(model.model_json_schema())}"
            )
            split_error: str | None = None
            for split_attempt in range(2):
                split_request = {
                    **base_request,
                    "artifact_type": artifact_type,
                }
                if split_error is not None:
                    split_request["validation_feedback"] = {
                        "message": split_error,
                        "instruction": "Regenerate the complete object and satisfy every required field exactly.",
                    }
                try:
                    def validate_split(payload):
                        artifact = model.model_validate(payload)
                        if artifact.personalization != expected:
                            _fail("personalization_evidence_mismatch", "resource personalization does not match the frozen profile strategy")
                        validate_artifact_scope(artifact, verified)
                        _validate_personalization_structure(artifact, expected)
                        return artifact

                    result = await execute_registered_structured_call(
                        session,
                        backend=self.llm,
                        capability={
                            "lesson": Capability.LECTURE,
                            "lab_guide": Capability.PRACTICAL_GUIDE,
                            "tiered_quiz": Capability.TIERED_QUIZ,
                        }[artifact_type],
                        system_prompt=split_system,
                        user_prompt=_canonical_json(split_request),
                        role=f"M3领域生成:{artifact_type}",
                        operation=f"m3_{artifact_type}_attempt_{split_attempt + 1}",
                        response_model=model,
                        response_validator=validate_split,
                        owner_public_id=context.owner_public_id,
                        course_id=context.course_id,
                        task_id=task_id,
                        trace_id=trace_id,
                        output_constraints=OutputConstraints(
                            format="json",
                            environment=("verified_course_context",) if artifact_type == "lab_guide" else (),
                            safety_boundary="Verified course and profile scope is immutable." if artifact_type == "lab_guide" else "",
                        ),
                    )
                    artifact = model.model_validate(result.structured_output)
                    artifacts[artifact_type] = artifact
                    break
                except (TypeError, ValueError, json.JSONDecodeError, M3ResourceError, M5CapabilityError) as exc:
                    split_error = str(exc)
                    if split_attempt == 1:
                        raise M3ResourceError(
                            "m3_split_resource_invalid",
                            f"split generation failed for {artifact_type}: {split_error}",
                        ) from exc
        return validate_m3_resource_bundle(
            M3PersonalizedResourceBundle(**artifacts),
            context=verified,
            profile=profile,
        )


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
    run = (
        session.query(DBAgentRun)
        .filter_by(task_id=task.id, role=M3AgentRole.DOMAIN_GENERATION.value)
        .order_by(DBAgentRun.created_at.desc(), DBAgentRun.id.desc())
        .first()
    )
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
            candidate_summary=(
                "Generated lesson, training guide and tiered quiz candidates with "
                f"difficulty {personalization.difficulty_band} and {personalization.scaffolding} scaffolding."
            ),
            validation=f"Generated resources cite {len(verified.source_ref_ids)} verified source references.",
            decision_summary="Forward the three personalized candidates to evidence review.",
        )
    session.flush()
    return manifest, manifest_version, resources, True
