"""Shared public schemas for the unified EduMatrix learning context."""

from __future__ import annotations

from typing import Literal

from pydantic import ConfigDict, Field, model_validator

from app.m2_contracts import StrictModel


class ContextRef(StrictModel):
    """Stable identifiers carried across course-scoped routes and API calls."""

    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        populate_by_name=True,
    )

    user_id: str | None = Field(default=None, alias="userId", max_length=64)
    course_id: str | None = Field(default=None, alias="courseId", max_length=128)
    chapter_id: str | None = Field(default=None, alias="chapterId", max_length=64)
    knowledge_point_id: str | None = Field(
        default=None, alias="knowledgePointId", max_length=64
    )
    path_id: str | None = Field(default=None, alias="pathId", max_length=64)
    task_id: str | None = Field(default=None, alias="taskId", max_length=64)
    resource_id: str | None = Field(default=None, alias="resourceId", max_length=64)
    source_ref_id: str | None = Field(default=None, alias="sourceRefId", max_length=64)
    attempt_id: str | None = Field(default=None, alias="attemptId", max_length=64)
    version: str | None = Field(default=None, max_length=128)

    @model_validator(mode="after")
    def require_course_for_scoped_objects(self) -> "ContextRef":
        scoped = (
            self.chapter_id,
            self.knowledge_point_id,
            self.path_id,
            self.task_id,
            self.resource_id,
            self.source_ref_id,
            self.attempt_id,
        )
        if any(scoped) and not self.course_id:
            raise ValueError("courseId is required when a course-scoped object is present")
        return self


class ContextResolveRequest(StrictModel):
    context: ContextRef


class ContextObjectSummary(StrictModel):
    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        populate_by_name=True,
    )

    object_type: str = Field(alias="objectType")
    id: str
    title: str
    course_id: str | None = Field(default=None, alias="courseId")
    owner_user_id: str | None = Field(default=None, alias="ownerUserId")
    version: str | None = None
    status: str | None = None


class ContextResolution(StrictModel):
    model_config = ConfigDict(
        extra="forbid",
        str_strip_whitespace=True,
        populate_by_name=True,
    )

    schema_version: Literal["edumatrix.context-resolution.v1"] = (
        "edumatrix.context-resolution.v1"
    )
    context: ContextRef
    course: ContextObjectSummary
    chapter: ContextObjectSummary | None = None
    knowledge_point: ContextObjectSummary | None = Field(
        default=None, alias="knowledgePoint"
    )
    task: ContextObjectSummary | None = None
    resource: ContextObjectSummary | None = None
    source_ref: ContextObjectSummary | None = Field(default=None, alias="sourceRef")
    attempt: ContextObjectSummary | None = None
    fallback: Literal["none", "legacy_course_picker"] = "none"
