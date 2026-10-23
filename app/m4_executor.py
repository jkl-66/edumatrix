"""Real structured-model executor for the frozen M4 blind benchmark."""

from __future__ import annotations

import json
import os
import re
from typing import Any, Literal

from pydantic import ConfigDict, Field

from app.database import DBCourseDocument, DBSourceDocument, DBSourceRef
from app.m2_contracts import StrictModel
from app.m3_profiles import load_m3_gold_profiles
from app.m4_evaluation import load_frozen_benchmark
from app.m4_runs import BlindCaseOutput
from app.m5_capabilities import Capability, M5CapabilityError
from app.m5_gateway import execute_registered_structured_call
from llm_client import parse_json_object


_FORBIDDEN_OUTBOUND_KEYS = {
    "gold", "gold_data", "failure_branch", "api_key", "apikey",
    "authorization", "access_token", "refresh_token", "password", "secret",
}
_EMAIL_PATTERN = re.compile(r"(?i)(?<![\w.+-])[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
_CN_MOBILE_PATTERN = re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")
_BEARER_PATTERN = re.compile(r"(?i)\bbearer\s+[a-z0-9._~+/-]{8,}=*")


def _configured_secret_values() -> tuple[str, ...]:
    values = []
    for name, value in os.environ.items():
        upper = name.upper()
        if value and len(value) >= 8 and any(marker in upper for marker in ("KEY", "TOKEN", "SECRET", "PASSWORD")):
            values.append(value)
    return tuple(values)


def audit_m4_outbound_payload(payload: Any) -> None:
    """Fail closed before M4 data reaches the configured external endpoint."""
    secrets = _configured_secret_values()

    def visit(value: Any, path: str) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                normalized = str(key).strip().lower()
                if normalized in _FORBIDDEN_OUTBOUND_KEYS:
                    raise ValueError(f"M4 outbound payload contains forbidden key at {path}.{key}")
                visit(child, f"{path}.{key}")
            return
        if isinstance(value, (list, tuple)):
            for index, child in enumerate(value):
                visit(child, f"{path}[{index}]")
            return
        if not isinstance(value, str):
            return
        if any(secret in value for secret in secrets):
            raise ValueError(f"M4 outbound payload contains a configured secret at {path}")
        if _EMAIL_PATTERN.search(value) or _CN_MOBILE_PATTERN.search(value) or _BEARER_PATTERN.search(value):
            raise ValueError(f"M4 outbound payload contains identity or credential data at {path}")

    visit(payload, "payload")


class M4AtomicClaim(StrictModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    claim_id: str = Field(min_length=1, max_length=64)
    text: str = Field(min_length=1, max_length=2000)
    source_ref_ids: tuple[str, ...]
    confidence: float = Field(ge=0.0, le=1.0)


class M4ProfileAdaptationEvidence(StrictModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    profile_id: str
    applied: bool
    difficulty_band: str
    scaffolding: Literal["high", "medium", "low"]
    explanation: str = Field(min_length=1, max_length=2000)


class M4StructuredCaseResponse(StrictModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    case_id: str
    status: Literal["completed", "legal_refusal"]
    response_text: str = Field(min_length=1, max_length=20000)
    claims: tuple[M4AtomicClaim, ...] = Field(min_length=1, max_length=12)
    adaptation: M4ProfileAdaptationEvidence
    uncertainty: str = Field(default="", max_length=2000)


def load_m4_source_material(session: Any) -> tuple[dict[str, str], ...]:
    rows = (
        session.query(DBSourceRef, DBSourceDocument, DBCourseDocument)
        .join(DBSourceDocument, DBSourceDocument.id == DBSourceRef.source_document_id)
        .join(DBCourseDocument, DBCourseDocument.id == DBSourceDocument.legacy_document_id)
        .filter(DBSourceDocument.course_id == "course-rag-engineering-m0")
        .order_by(DBCourseDocument.chapter_order, DBSourceRef.id)
        .all()
    )
    material = []
    for source_ref, source, document in rows:
        start = max(0, int(source_ref.char_start or 0))
        end = int(source_ref.char_end or len(document.content or ""))
        material.append({
            "source_ref_id": source_ref.id,
            "title": source.title,
            "excerpt": (document.content or "")[start:end].strip()[:6000],
        })
    if not material:
        raise ValueError("M4 frozen course source material is unavailable")
    return tuple(material)


def _profile_context(profile_id: str) -> dict[str, Any]:
    profile = next(
        (item for item in load_m3_gold_profiles().profiles if item.source_profile.profile_id == profile_id),
        None,
    )
    if profile is None:
        raise ValueError(f"unknown frozen M4 profile: {profile_id}")
    strategy = profile.adaptation_strategy
    return {
        "profile_id": profile_id,
        "archetype": profile.archetype,
        "goal": profile.source_profile.goal,
        "constraints": profile.source_profile.constraints,
        "strategy": {
            "difficulty_band": strategy.difficulty_band,
            "scaffolding": strategy.scaffolding,
            "terminology_density": strategy.terminology_density,
            "step_granularity": strategy.step_granularity,
            "hint_policy": strategy.hint_policy,
            "task_openness": strategy.task_openness,
            "quiz_emphasis": strategy.quiz_emphasis,
        },
    }


class M4RealModelExecutor:
    def __init__(self, llm: Any, *, sources: tuple[dict[str, str], ...], session: Any, trace_id: str):
        self.llm = llm
        self.sources = sources
        self.session = session
        self.trace_id = trace_id
        self.allowed_source_ids = {item["source_ref_id"] for item in sources}
        self.benchmark = load_frozen_benchmark()

    def _original_request(self, blind_case: dict[str, object]) -> dict[str, Any]:
        profile_id = str(blind_case.get("profile_id", ""))
        return {
            "blind_case": blind_case,
            "profile": _profile_context(profile_id),
            "course_sources": self.sources,
            "required_schema": M4StructuredCaseResponse.model_json_schema(),
        }

    def preflight(self, blind_cases: tuple[dict[str, object], ...]) -> None:
        for blind_case in blind_cases:
            audit_m4_outbound_payload(self._original_request(blind_case))

    async def execute(self, blind_case: dict[str, object]) -> BlindCaseOutput:
        case_id = str(blind_case.get("case_id", ""))
        profile_id = str(blind_case.get("profile_id", ""))
        original_request = self._original_request(blind_case)
        system_prompt = (
            "Return JSON only and satisfy required_schema exactly. You are the EduMatrix frozen M4 blind-case executor. "
            "Answer only from course_sources and the stated system safety boundary. Never infer or request hidden gold labels. "
            "Every factual claim must cite only provided source_ref_ids. Preserve owner, course and version isolation; do not "
            "claim an operation was executed when the case only asks for an explanation. Use legal_refusal only when the requested "
            "action itself must be refused; otherwise explain the required secure behavior with status completed. Apply the frozen "
            "profile strategy to depth and scaffolding without weakening factual or safety standards."
        )
        validation_error: Exception | None = None
        for _attempt in range(2):
            request: dict[str, Any] = original_request
            if validation_error is not None:
                request = {
                    "original_request": original_request,
                    "validation_feedback": {
                        "message": str(validation_error),
                        "instruction": "Regenerate the complete object and use only allowed source_ref_ids and enum values.",
                    },
                }
            audit_m4_outbound_payload(request)
            try:
                def validate_response(value):
                    response = M4StructuredCaseResponse.model_validate(value)
                    if response.case_id != case_id:
                        raise ValueError("model returned another case_id")
                    cited = {ref for claim in response.claims for ref in claim.source_ref_ids}
                    if not cited.issubset(self.allowed_source_ids):
                        raise ValueError("model cited a source outside the frozen course scope")
                    if response.adaptation.profile_id != profile_id:
                        raise ValueError("model returned another profile_id")
                    return response

                result = await execute_registered_structured_call(
                    self.session,
                    backend=self.llm,
                    capability=Capability.REPORT,
                    system_prompt=system_prompt,
                    user_prompt=json.dumps(request, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
                    role="m4_blind_case_executor",
                    operation=f"m4_blind_case_{case_id}_attempt_{_attempt + 1}",
                    response_model=M4StructuredCaseResponse,
                    response_validator=validate_response,
                    course_id="course-rag-engineering-m0",
                    trace_id=self.trace_id,
                )
                response = M4StructuredCaseResponse.model_validate(result.structured_output)
                return BlindCaseOutput(
                    case_id=case_id,
                    status=response.status,
                    response_text=response.response_text,
                    citation_count=sum(len(claim.source_ref_ids) for claim in response.claims),
                    locatable_citation_count=sum(len(claim.source_ref_ids) for claim in response.claims),
                    evidence={
                        "schema_version": "m4.structured-case-evidence.v1",
                        "evaluation_context": {
                            "domain_id": self.benchmark.domain_id,
                            "course_id": self.benchmark.course_id,
                            "profile_snapshot": {
                                "profile_id": profile_id,
                                "version": self.benchmark.profile_version,
                                "id": f"{self.benchmark.profile_version}:{profile_id}",
                            },
                            "source_snapshot": {
                                "course_manifest_sha256": self.benchmark.course_manifest_sha256,
                                "knowledge_point_version": self.benchmark.knowledge_point_version,
                                "case_version": self.benchmark.case_version,
                            },
                        },
                        "claims": [item.model_dump(mode="json") for item in response.claims],
                        "adaptation": response.adaptation.model_dump(mode="json"),
                        "uncertainty": response.uncertainty,
                        "source_scope": sorted(self.allowed_source_ids),
                    },
                )
            except (TypeError, ValueError, json.JSONDecodeError, M5CapabilityError) as exc:
                validation_error = exc
        raise ValueError(f"M4 structured executor failed strict repair: {validation_error}")
