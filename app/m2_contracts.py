"""Strict capability and artifact contracts for the M2 golden loop."""

from __future__ import annotations

from enum import Enum
from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class M2ArtifactType(str, Enum):
    LESSON = "lesson"
    LAB_GUIDE = "lab_guide"
    TIERED_QUIZ = "tiered_quiz"


class M2Capability(str, Enum):
    LESSON = "lesson.generate_verified"
    LAB_GUIDE = "lab_guide.generate_verified"
    TIERED_QUIZ = "tiered_quiz.generate_verified"


class GenerationContext(StrictModel):
    owner_public_id: str = Field(min_length=8, max_length=64)
    course_id: str = Field(min_length=3, max_length=64)
    domain_version_id: str = Field(min_length=3, max_length=64)
    profile_snapshot_id: str = Field(min_length=3, max_length=64)
    target_knowledge_point_ids: list[str] = Field(min_length=1)
    source_ref_ids: list[str] = Field(min_length=1)
    language: str = Field(default="zh-CN", min_length=2, max_length=16)
    quality_mode: Literal["verified"] = "verified"

    @model_validator(mode="after")
    def unique_references(self) -> "GenerationContext":
        if len(set(self.target_knowledge_point_ids)) != len(self.target_knowledge_point_ids):
            raise ValueError("target_knowledge_point_ids must be unique")
        if len(set(self.source_ref_ids)) != len(self.source_ref_ids):
            raise ValueError("source_ref_ids must be unique")
        return self


class LessonSection(StrictModel):
    heading: str = Field(min_length=1, max_length=160)
    body_markdown: str = Field(min_length=1)
    knowledge_point_ids: list[str] = Field(min_length=1)
    source_ref_ids: list[str] = Field(min_length=1)


class LessonArtifact(StrictModel):
    artifact_type: Literal["lesson"] = "lesson"
    schema_version: Literal["m2.lesson.v1"] = "m2.lesson.v1"
    title: str = Field(min_length=1, max_length=256)
    objective: str = Field(min_length=1)
    prerequisites: list[str] = Field(default_factory=list)
    sections: list[LessonSection] = Field(min_length=1)
    retrieval_questions: list[str] = Field(default_factory=list)
    summary: str = Field(min_length=1)


class LabStep(StrictModel):
    step_number: int = Field(ge=1)
    title: str = Field(min_length=1, max_length=160)
    instruction: str = Field(min_length=1)
    command_or_action: str = Field(default="")
    expected_result: str = Field(min_length=1)
    rollback: str = Field(min_length=1)
    risk_level: Literal["low", "medium", "high"] = "low"
    source_ref_ids: list[str] = Field(min_length=1)


class FailureBranch(StrictModel):
    symptom: str = Field(min_length=1)
    likely_cause: str = Field(min_length=1)
    recovery_steps: list[str] = Field(min_length=1)


class LabGuideArtifact(StrictModel):
    artifact_type: Literal["lab_guide"] = "lab_guide"
    schema_version: Literal["m2.lab_guide.v1"] = "m2.lab_guide.v1"
    title: str = Field(min_length=1, max_length=256)
    objective: str = Field(min_length=1)
    environment: list[str] = Field(min_length=1)
    safety_boundary: str = Field(min_length=1)
    steps: list[LabStep] = Field(min_length=1)
    acceptance_criteria: list[str] = Field(min_length=1)
    failure_branches: list[FailureBranch] = Field(min_length=1)

    @model_validator(mode="after")
    def ordered_steps(self) -> "LabGuideArtifact":
        expected = list(range(1, len(self.steps) + 1))
        if [step.step_number for step in self.steps] != expected:
            raise ValueError("lab steps must be consecutive and start at 1")
        return self


class TieredQuestion(StrictModel):
    id: str = Field(min_length=1, max_length=64)
    prompt: str = Field(min_length=1)
    knowledge_point_ids: list[str] = Field(min_length=1)
    bloom_level: Literal["remember", "understand", "apply", "analyze", "evaluate", "create"]
    difficulty_basis: str = Field(min_length=1)
    scoring_rule: str = Field(min_length=1)
    answer_key: str = Field(min_length=1)
    explanation: str = Field(min_length=1)
    source_ref_ids: list[str] = Field(min_length=1)

    def learner_payload(self) -> dict[str, Any]:
        return self.model_dump(exclude={"answer_key", "explanation"})


class QuizTier(StrictModel):
    level: Literal["foundation", "application", "advanced"]
    questions: list[TieredQuestion] = Field(min_length=1)


class TieredQuizArtifact(StrictModel):
    artifact_type: Literal["tiered_quiz"] = "tiered_quiz"
    schema_version: Literal["m2.tiered_quiz.v1"] = "m2.tiered_quiz.v1"
    title: str = Field(min_length=1, max_length=256)
    instructions: str = Field(min_length=1)
    tiers: list[QuizTier] = Field(min_length=3, max_length=3)
    pass_rules: dict[str, str] = Field(min_length=3)

    @model_validator(mode="after")
    def exactly_three_tiers(self) -> "TieredQuizArtifact":
        levels = [tier.level for tier in self.tiers]
        expected = ["foundation", "application", "advanced"]
        if levels != expected:
            raise ValueError(f"quiz tiers must be ordered as {expected}")
        if set(self.pass_rules) != set(expected):
            raise ValueError("pass_rules must cover all three tiers")
        question_ids = [question.id for tier in self.tiers for question in tier.questions]
        if len(question_ids) != len(set(question_ids)):
            raise ValueError("question ids must be unique across tiers")
        return self

    def learner_payload(self) -> dict[str, Any]:
        payload = self.model_dump()
        payload["tiers"] = [{
            "level": tier.level,
            "questions": [question.learner_payload() for question in tier.questions],
        } for tier in self.tiers]
        return payload


M2Artifact = Annotated[
    Union[LessonArtifact, LabGuideArtifact, TieredQuizArtifact],
    Field(discriminator="artifact_type"),
]
M2_ARTIFACT_ADAPTER = TypeAdapter(M2Artifact)


CAPABILITY_ARTIFACT_TYPES: dict[M2Capability, M2ArtifactType] = {
    M2Capability.LESSON: M2ArtifactType.LESSON,
    M2Capability.LAB_GUIDE: M2ArtifactType.LAB_GUIDE,
    M2Capability.TIERED_QUIZ: M2ArtifactType.TIERED_QUIZ,
}


def validate_m2_artifact(capability: M2Capability | str, payload: Any) -> M2Artifact:
    capability_value = M2Capability(capability)
    artifact = M2_ARTIFACT_ADAPTER.validate_python(payload)
    expected = CAPABILITY_ARTIFACT_TYPES[capability_value].value
    if artifact.artifact_type != expected:
        raise ValueError(f"capability {capability_value.value} requires artifact_type={expected}")
    return artifact
