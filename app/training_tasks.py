"""Structured training-task content used by the F5 resource workspace."""

from __future__ import annotations

import json
from typing import Any, Literal

from pydantic import Field, model_validator

from app.m2_contracts import LabGuideArtifact, StrictModel
from app.m5_capabilities import M5CapabilityError


class TrainingTaskStep(StrictModel):
    id: str = Field(min_length=1, max_length=96)
    title: str = Field(min_length=1, max_length=160)
    instruction: str = Field(min_length=1, max_length=8_000)
    expectedResult: str = Field(min_length=1, max_length=4_000)
    errorGuidance: str = Field(min_length=1, max_length=4_000)
    sourceRefIds: list[str] = Field(default_factory=list, max_length=40)


class TrainingTaskCheckpoint(StrictModel):
    id: str = Field(min_length=1, max_length=96)
    afterStepId: str = Field(min_length=1, max_length=96)
    title: str = Field(min_length=1, max_length=160)
    verification: str = Field(min_length=1, max_length=4_000)
    passCondition: str = Field(min_length=1, max_length=4_000)


class TrainingTaskDeliverable(StrictModel):
    id: str = Field(min_length=1, max_length=96)
    title: str = Field(min_length=1, max_length=160)
    description: str = Field(min_length=1, max_length=4_000)
    format: str = Field(min_length=1, max_length=80)


class TrainingTaskRubricItem(StrictModel):
    id: str = Field(min_length=1, max_length=96)
    criterion: str = Field(min_length=1, max_length=240)
    evidence: str = Field(min_length=1, max_length=4_000)
    points: int = Field(ge=1, le=100)


class TrainingTaskContent(StrictModel):
    schemaVersion: Literal["f5.training-task.v1"] = "f5.training-task.v1"
    title: str = Field(min_length=1, max_length=256)
    objective: str = Field(min_length=1, max_length=4_000)
    difficulty: str = Field(min_length=1, max_length=64)
    estimatedMinutes: int = Field(ge=1, le=960)
    prerequisites: list[str] = Field(min_length=1, max_length=20)
    environment: list[str] = Field(min_length=1, max_length=20)
    data: list[str] = Field(min_length=1, max_length=20)
    steps: list[TrainingTaskStep] = Field(min_length=1, max_length=40)
    checkpoints: list[TrainingTaskCheckpoint] = Field(min_length=1, max_length=40)
    deliverables: list[TrainingTaskDeliverable] = Field(min_length=1, max_length=20)
    rubric: list[TrainingTaskRubricItem] = Field(min_length=1, max_length=20)
    sourceRefs: list[str] = Field(min_length=1, max_length=80)
    linkedSandboxId: str | None = Field(default=None, max_length=64)
    linkedModelId: str | None = Field(default=None, max_length=64)
    semanticContext: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def valid_execution_contract(self) -> "TrainingTaskContent":
        step_ids = [step.id for step in self.steps]
        checkpoint_ids = [item.id for item in self.checkpoints]
        deliverable_ids = [item.id for item in self.deliverables]
        rubric_ids = [item.id for item in self.rubric]
        all_ids = step_ids + checkpoint_ids + deliverable_ids + rubric_ids
        if len(all_ids) != len(set(all_ids)):
            raise ValueError("training-task section ids must be unique")
        if any(item.afterStepId not in step_ids for item in self.checkpoints):
            raise ValueError("training-task checkpoints must reference an existing step")
        if sum(item.points for item in self.rubric) != 100:
            raise ValueError("training-task rubric points must total 100")
        if len(self.sourceRefs) != len(set(self.sourceRefs)):
            raise ValueError("training-task source references must be unique")
        if any(len(step.sourceRefIds) != len(set(step.sourceRefIds)) for step in self.steps):
            raise ValueError("training-task step source references must be unique")
        return self


def parse_training_task_content(content: str) -> TrainingTaskContent:
    try:
        payload = json.loads(content)
    except json.JSONDecodeError as exc:
        raise M5CapabilityError(
            "training_task_content_invalid", "structured training-task content must be valid JSON"
        ) from exc
    if not isinstance(payload, dict):
        raise M5CapabilityError(
            "training_task_content_invalid", "structured training-task content must be a JSON object"
        )
    try:
        return TrainingTaskContent.model_validate(payload)
    except ValueError as exc:
        raise M5CapabilityError(
            "training_task_content_incomplete", "structured training-task is missing required execution sections"
        ) from exc


def legacy_lab_guide(content: str) -> dict[str, Any] | None:
    try:
        payload = json.loads(content)
        guide = LabGuideArtifact.model_validate(payload)
    except (json.JSONDecodeError, TypeError, ValueError):
        return None
    return {
        "title": guide.title,
        "objective": guide.objective,
        "environment": guide.environment,
        "safety_boundary": guide.safety_boundary,
        "steps": [
            {
                "id": f"legacy-step-{step.step_number}",
                "title": step.title,
                "instruction": step.instruction,
                "expectedResult": step.expected_result,
                "errorGuidance": step.rollback,
                "sourceRefIds": step.source_ref_ids,
            }
            for step in guide.steps
        ],
        "acceptance_criteria": guide.acceptance_criteria,
        "failure_branches": [branch.model_dump() for branch in guide.failure_branches],
    }
