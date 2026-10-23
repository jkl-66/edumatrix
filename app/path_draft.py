"""Textbook-anchored plan drafts built on the canonical M5 plan lifecycle."""

from __future__ import annotations

import asyncio
import json
from concurrent.futures import ThreadPoolExecutor
from collections import defaultdict
from typing import Any

from app.authorization import active_course_role
from app.database import (
    DBChapter,
    DBChapterKnowledgePoint,
    DBCourse,
    DBKnowledgePoint,
    DBLearningPath,
    DBModelCall,
    DBPlanDraft,
    DBPlanVersion,
    DBProfileSnapshot,
    DBSourceDocument,
    DBSourceRef,
    DBUser,
)
from app.m2_contracts import StrictModel
from app.m5_capabilities import Capability, M5CapabilityError, OutputConstraints
from app.m5_gateway import execute_registered_structured_call
from app.m5_learning import (
    PlanNodeSpec,
    PlanSpec,
    _validate_plan_targets,
    create_plan_draft,
    plan_version_diff,
    propose_plan_revision,
)
from pydantic import Field


class PathDraftError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _fail(code: str, message: str) -> None:
    raise PathDraftError(code, message)


class PathDraftModelOutput(StrictModel):
    """The only model-authored portion of a diagnostic path draft."""

    plan: PlanSpec
    personalization_summary: str = Field(min_length=8, max_length=1600)


def _require_path_model(llm: Any) -> None:
    model = str(getattr(llm, "model", "")).strip()
    thinking = str(getattr(llm, "thinking_mode", "")).strip().lower()
    reasoning = str(getattr(llm, "reasoning_effort", "")).strip().lower()
    backend_name = llm.__class__.__name__.lower()
    if (
        model != "deepseek-v4-flash"
        or thinking != "enabled"
        or reasoning != "max"
        or "deterministic" in backend_name
        or "fallback" in backend_name
        or bool(getattr(llm, "allow_fallback", False))
    ):
        _fail(
            "path_draft_model_policy_invalid",
            "学习路径定制必须使用 deepseek-v4-flash、thinking enabled、reasoning max，且不允许回退模型。",
        )


def _build_path_model():
    """Build the governed production backend at the boundary that owns the call."""
    from config import CONFIG
    from llm_client import build_async_llm

    return build_async_llm(
        CONFIG,
        model="deepseek-v4-flash",
        thinking_mode="enabled",
        reasoning_effort="max",
        # Complex graph planning with reasoning enabled can consume most of
        # an 8k completion before emitting the public JSON object. Keep the
        # configured production budget for this governed call.
        max_tokens=CONFIG.llm_max_tokens,
        allow_fallback=False,
    )


def _run_model_sync(coro_factory):
    """Run the async gateway from both thread-backed endpoints and direct callers."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro_factory())
    with ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(lambda: asyncio.run(coro_factory())).result()


def _authorize(session: Any, *, current_user: DBUser, course: DBCourse) -> None:
    from course_catalog import course_is_selectable
    if not course_is_selectable(session, course):
        _fail("course_unavailable", "课程已停止发布或没有可用学习资料")
    role = active_course_role(
        session, course_id=course.id, user_public_id=current_user.public_id,
    )
    if current_user.role != "admin" and course.owner_public_id != current_user.public_id and role is None:
        _fail("course_forbidden", "当前账号不是该课程成员")


def _latest_profile(
    session: Any, *, owner_public_id: str, course_id: str, profile_snapshot_id: str | None = None,
) -> DBProfileSnapshot | None:
    if profile_snapshot_id:
        row = session.get(DBProfileSnapshot, profile_snapshot_id)
        if row is None or row.owner_public_id != owner_public_id:
            return None
        return row if (row.snapshot or {}).get("course_id") in {None, course_id} else None
    rows = session.query(DBProfileSnapshot).filter_by(owner_public_id=owner_public_id).order_by(
        DBProfileSnapshot.created_at.desc(), DBProfileSnapshot.id.desc(),
    ).all()
    return next(
        (row for row in rows if (row.snapshot or {}).get("course_id") in {None, course_id}),
        None,
    )


def _course_facts(session: Any, *, course_id: str) -> dict[str, Any]:
    chapters = session.query(DBChapter).filter_by(course_id=course_id).order_by(
        DBChapter.position, DBChapter.id,
    ).all()
    chapter_ids = [item.id for item in chapters]
    links = session.query(DBChapterKnowledgePoint).filter(
        DBChapterKnowledgePoint.chapter_id.in_(chapter_ids or ["-"]),
    ).all()
    kp_ids = sorted({item.knowledge_point_id for item in links})
    knowledge = {
        item.id: item for item in session.query(DBKnowledgePoint).filter(
            DBKnowledgePoint.id.in_(kp_ids or ["-"]),
        ).all()
    }
    chapter_by_kp: dict[str, DBChapter] = {}
    kp_by_chapter: dict[str, list[DBKnowledgePoint]] = defaultdict(list)
    chapter_by_id = {item.id: item for item in chapters}
    for link in links:
        chapter = chapter_by_id.get(link.chapter_id)
        kp = knowledge.get(link.knowledge_point_id)
        if chapter is None or kp is None:
            continue
        chapter_by_kp.setdefault(kp.id, chapter)
        kp_by_chapter[chapter.id].append(kp)
    sources = {
        item.id: item for item in session.query(DBSourceDocument).filter_by(course_id=course_id).all()
    }
    refs = session.query(DBSourceRef).filter(
        DBSourceRef.chapter_id.in_(chapter_ids or ["-"]),
    ).order_by(DBSourceRef.created_at, DBSourceRef.id).all()
    ref_by_chapter = {item.chapter_id: item for item in refs if item.chapter_id}
    return {
        "chapters": chapters,
        "chapter_by_kp": chapter_by_kp,
        "kp_by_chapter": kp_by_chapter,
        "knowledge": knowledge,
        "sources": sources,
        "ref_by_chapter": ref_by_chapter,
    }


def _path_model_context(
    facts: dict[str, Any], *, course: DBCourse, profile: DBProfileSnapshot,
    snapshot: dict[str, Any], time_budget_minutes: int,
) -> dict[str, Any]:
    """Build the smallest serializable, course-scoped input for the path model."""
    mastery = snapshot.get("mastery_by_knowledge_point") or {}
    chapters = []
    for chapter in facts["chapters"]:
        chapters.append({
            "id": chapter.id,
            "title": chapter.title,
            "position": chapter.position,
            "source_document_id": chapter.source_document_id,
            "knowledge_points": [
                {
                    "id": kp.id,
                    "title": kp.title,
                    "prerequisites": [str(item) for item in (kp.prerequisites or [])],
                    "mastery": mastery.get(kp.id, {}),
                }
                for kp in facts["kp_by_chapter"].get(chapter.id, [])
            ],
        })
    sources = [
        {
            "id": source.id,
            "title": source.title,
            "filename": source.filename,
            "license": source.license_text,
            "content_hash": source.content_hash,
        }
        for source in facts["sources"].values()
    ]
    raw_diagnostic = snapshot.get("diagnostic_evidence") or {}
    compact_feedback = []
    for item in (raw_diagnostic.get("grading_feedback") or [])[:32]:
        grading = item.get("grading") or {}
        advice = grading.get("improvementAdvice") or []
        compact_feedback.append({
            "knowledge_point_id": item.get("knowledge_point_id"),
            "score": grading.get("score"),
            "correct": grading.get("correct"),
            "feedback": str(grading.get("feedback") or "")[:240],
            "improvement_advice": [str(value)[:160] for value in advice[:2]],
        })
    diagnostic_evidence = {
        "source_ref_ids": list(raw_diagnostic.get("source_ref_ids") or []),
        "attempt_count": len(raw_diagnostic.get("attempt_ids") or []),
        "grading_feedback": compact_feedback,
    }
    return {
        "course": {"id": course.id, "title": course.title, "version": course.version},
        "profile_snapshot_id": profile.id,
        "initial_learning_evidence": {
            "mastery_by_knowledge_point": mastery,
            "mastered_knowledge_point_ids": [str(item) for item in snapshot.get("mastered_knowledge_point_ids") or []],
            "weak_knowledge_point_ids": [str(item) for item in snapshot.get("weak_knowledge_point_ids") or []],
            "unknown_knowledge_point_ids": [str(item) for item in snapshot.get("unknown_knowledge_point_ids") or []],
            "diagnostic_evidence": diagnostic_evidence,
        },
        "learning_goal": snapshot.get("learning_goal") or snapshot.get("goal") or "完成当前课程的可验证学习目标",
        "learning_preferences": snapshot.get("learning_preferences") or snapshot.get("preferences") or {},
        "time_budget_minutes": time_budget_minutes,
        "course_graph": {"chapters": chapters, "sources": sources},
    }


def _validate_model_plan_output(
    payload: dict[str, Any], *, facts: dict[str, Any], owner_public_id: str,
    course_id: str, session: Any, require_full_coverage: bool = False,
    required_chapter_ids: set[str] | None = None,
) -> PathDraftModelOutput:
    payload = _coerce_model_payload(payload, facts=facts)
    try:
        output = PathDraftModelOutput.model_validate(payload)
    except Exception as exc:
        _fail("path_draft_model_output_invalid", "模型返回的路径草稿不符合正式结构，请重试。")
        raise AssertionError from exc
    allowed_chapters = {item.id for item in facts["chapters"]}
    for node in output.plan.nodes:
        if node.node_type == "chapter" and node.target_object_id not in allowed_chapters:
            _fail("path_draft_model_scope_invalid", "模型草稿包含不属于当前课程的章节。")
    try:
        _validate_plan_targets(
            session, owner_public_id=owner_public_id, course_id=course_id,
            spec=output.plan,
        )
    except PathDraftError:
        raise
    except Exception as exc:
        _fail("path_draft_model_targets_invalid", "模型草稿的课程或资源授权校验失败，请重试。")
        raise AssertionError from exc
    covered_chapters = {str(node.target_object_id) for node in output.plan.nodes if node.node_type == "chapter"}
    if require_full_coverage:
        missing_chapters = [chapter.id for chapter in facts["chapters"] if chapter.id not in covered_chapters]
        if missing_chapters:
            _fail("path_draft_model_scope_invalid", "模型草稿没有覆盖当前课程的全部章节。")
    if required_chapter_ids and not required_chapter_ids.issubset(covered_chapters):
        _fail("path_draft_model_scope_invalid", "模型批次没有覆盖分配的章节。")
    return output


def _coerce_model_payload(payload: dict[str, Any], *, facts: dict[str, Any]) -> dict[str, Any]:
    """Normalize a legacy model envelope before the strict PlanSpec boundary.

    Older providers have returned the same model-authored plan with names such as
    ``plan_schema``, knowledge-point node keys, ordinal difficulties and resource
    availability objects.  Those fields can be mapped to the current course graph;
    an unmappable node or prerequisite is a real model-output failure and must not
    be handed to Pydantic (or replaced with a deterministic path).
    """
    if not isinstance(payload, dict):
        _fail("path_draft_model_output_invalid", "模型返回的路径草稿不是对象。")
    wrapper = dict(payload)
    raw_plan = wrapper.get("plan", wrapper)
    if not isinstance(raw_plan, dict):
        _fail("path_draft_model_output_invalid", "模型返回的路径计划不是对象。")
    plan = dict(raw_plan)
    if plan.get("schema_version") != "m5.plan.v1":
        plan["schema_version"] = plan.get("plan_schema") or plan.get("schema") or "m5.plan.v1"

    chapters = {item.id: item for item in facts["chapters"]}
    knowledge = facts["knowledge"]
    chapter_by_kp = facts["chapter_by_kp"]
    chapter_ids = set(chapters)
    valid_node_types = {"chapter", "artifact", "assessment", "interactive", "review", "extension"}

    def resolve_chapter(node: dict[str, Any]) -> tuple[str, DBChapter]:
        candidates: list[str] = []
        for key in (
            "target_object_id", "knowledge_point_id", "target_knowledge_point_id",
            "chapter_id", "target_id", "id", "node_key",
        ):
            value = node.get(key)
            if isinstance(value, dict):
                value = value.get("id") or value.get("key") or value.get("knowledge_point_id")
            if value is not None and str(value).strip():
                candidates.append(str(value).strip())
        for candidate in candidates:
            if candidate in chapters:
                return candidate, chapters[candidate]
            if candidate in chapter_by_kp:
                chapter = chapter_by_kp[candidate]
                return candidate, chapter
        # Some older outputs use a display key (for example learn-kp-04) rather
        # than the canonical knowledge-point id.  Only accept an unambiguous
        # suffix match from the current course graph.
        suffix_matches: dict[str, DBChapter] = {}
        for candidate in candidates:
            suffix = candidate.rsplit("-", 1)[-1].lower()
            matches = [
                (kp_id, chapter)
                for kp_id, chapter in chapter_by_kp.items()
                if kp_id.rsplit("-", 1)[-1].lower() == suffix
            ]
            if len(matches) == 1:
                return matches[0]
            suffix_matches.update(matches)
        if len(suffix_matches) == 1:
            return next(iter(suffix_matches.items()))
        _fail("path_draft_model_scope_invalid", "模型草稿包含无法映射到当前课程图谱的节点。")
        raise AssertionError

    def normalize_status(node: dict[str, Any], chapter: DBChapter) -> str:
        value = node.get("resource_status")
        if isinstance(value, dict):
            value = value.get("status") or value.get("availability") or value.get("state")
        value = str(value or "").strip().lower()
        if value in {"existing", "available", "ready", "published", "source_available"}:
            return "existing"
        if value in {"to_generate", "generate", "missing", "pending", "not_available"}:
            return "to_generate"
        if value in {"external", "external_dependency", "dependency"}:
            return "external_dependency"
        # ``weak``/``not_learned`` are mastery labels emitted by an older path
        # prompt.  Resource availability remains a course fact, not a mastery
        # conclusion, so use the chapter's admitted source when present.
        if value in {"", "unknown", "not_learned", "weak", "incomplete"}:
            return "existing" if chapter.source_document_id in facts["sources"] else "to_generate"
        _fail("path_draft_model_output_invalid", "模型草稿包含无法识别的资源状态。")
        raise AssertionError

    def normalize_difficulty(value: Any) -> float | None:
        if value is None or value == "":
            return None
        if isinstance(value, str):
            text = value.strip().lower()
            value = {
                "easy": 0.3, "basic": 0.3, "beginner": 0.25,
                "medium": 0.5, "intermediate": 0.55,
                "hard": 0.75, "advanced": 0.8,
            }.get(text)
            if value is None:
                _fail("path_draft_model_output_invalid", "模型草稿包含无法识别的难度。")
        try:
            number = float(value)
        except (TypeError, ValueError):
            _fail("path_draft_model_output_invalid", "模型草稿包含无法识别的难度。")
            raise AssertionError
        # Legacy prompts used 1..5 ordinal difficulty while the current contract
        # uses [0, 1].  Preserve model intent without letting an ordinal through.
        if number > 1:
            number = {2.0: 0.3, 3.0: 0.55, 4.0: 0.75, 5.0: 0.9}.get(number, -1)
        if not 0 <= number <= 1:
            _fail("path_draft_model_output_invalid", "模型草稿的难度超出有效范围。")
        return round(number, 3)

    def normalize_minutes(node: dict[str, Any]) -> tuple[int, int]:
        minimum = node.get("estimate_min_minutes")
        maximum = node.get("estimate_max_minutes")
        estimate = node.get("estimate_minutes") or node.get("estimated_minutes")
        estimate = estimate or node.get("estimated_time_minutes") or node.get("duration_minutes")
        if isinstance(estimate, dict):
            minimum = minimum or estimate.get("min") or estimate.get("minimum")
            maximum = maximum or estimate.get("max") or estimate.get("maximum")
        minimum = minimum or estimate or 15
        maximum = maximum or estimate or minimum
        try:
            minimum, maximum = int(minimum), int(maximum)
        except (TypeError, ValueError):
            _fail("path_draft_model_output_invalid", "模型草稿包含无法识别的学习时长。")
            raise AssertionError
        if minimum < 1 or maximum < minimum:
            _fail("path_draft_model_output_invalid", "模型草稿的学习时长无效。")
        return minimum, maximum

    normalized_nodes: list[dict[str, Any]] = []
    aliases: dict[str, str] = {}
    selected_chapter_ids: set[str] = set()
    for raw in plan.get("nodes") or []:
        if not isinstance(raw, dict):
            _fail("path_draft_model_output_invalid", "模型草稿包含无效的路径节点。")
        node = dict(raw)
        target, chapter = resolve_chapter(node)
        node_key = str(node.get("node_key") or f"model-{chapter.id}").strip()
        if not node_key:
            _fail("path_draft_model_output_invalid", "模型草稿节点缺少唯一标识。")
        node_type = str(node.get("node_type") or "chapter").strip().lower()
        if node_type not in valid_node_types or target not in chapter_ids:
            node_type = "chapter"
        minimum, maximum = normalize_minutes(node)
        normalized = {
            "node_key": node_key,
            "node_type": node_type,
            "target_object_id": chapter.id,
            "title": str(node.get("title") or chapter.title),
            "prerequisites": list(node.get("prerequisites") or []),
            "resource_status": normalize_status(node, chapter),
            "estimate_min_minutes": minimum,
            "estimate_max_minutes": maximum,
            "difficulty": normalize_difficulty(node.get("difficulty")),
            "rationale": str(node.get("rationale") or node.get("reason") or "模型依据本次初始学情安排该步骤。"),
        }
        aliases[node_key] = node_key
        aliases[target] = node_key
        aliases[chapter.id] = node_key
        selected_chapter_ids.add(chapter.id)
        for kp_id, mapped_chapter in chapter_by_kp.items():
            if mapped_chapter.id == chapter.id:
                aliases[kp_id] = node_key
                point = knowledge.get(kp_id)
                if point is not None:
                    if point.code:
                        aliases[str(point.code)] = node_key
                    if point.title:
                        aliases[str(point.title)] = node_key
        normalized_nodes.append(normalized)

    if not normalized_nodes:
        _fail("path_draft_model_output_invalid", "模型草稿没有可用的路径节点。")
    selected_aliases = dict(aliases)

    def course_chapter_for_alias(value: str) -> DBChapter | None:
        if value in chapters:
            return chapters[value]
        if value in chapter_by_kp:
            return chapter_by_kp[value]
        suffix = value.rsplit("-", 1)[-1].lower()
        matches = [
            chapter for kp_id, chapter in chapter_by_kp.items()
            if kp_id.rsplit("-", 1)[-1].lower() == suffix
        ]
        return matches[0] if len({item.id for item in matches}) == 1 else None

    seen: set[str] = set()
    for node in normalized_nodes:
        prerequisites: list[str] = []
        for prerequisite in node["prerequisites"]:
            if isinstance(prerequisite, dict):
                prerequisite = prerequisite.get("node_key") or prerequisite.get("target_object_id") or prerequisite.get("knowledge_point_id")
            key = str(prerequisite or "").strip()
            mapped = selected_aliases.get(key)
            if mapped is None:
                suffix = key.rsplit("-", 1)[-1].lower()
                suffix_values = {
                    value for alias, value in selected_aliases.items()
                    if alias.rsplit("-", 1)[-1].lower() == suffix
                }
                mapped = next(iter(suffix_values)) if len(suffix_values) == 1 else None
            if mapped is None:
                prerequisite_chapter = course_chapter_for_alias(key)
                # A mastered/external prerequisite is a course fact, not a node
                # that must be repeated in this learner's path.  It remains in
                # the model rationale and graph input but is omitted from the
                # PlanSpec edge set.  Unknown aliases are still rejected.
                if prerequisite_chapter is not None and prerequisite_chapter.id not in selected_chapter_ids:
                    continue
            if mapped is None or mapped not in seen:
                _fail("path_draft_model_topology_invalid", "模型草稿包含无法验证或顺序错误的先修关系。")
            if mapped not in prerequisites:
                prerequisites.append(mapped)
        node["prerequisites"] = prerequisites
        seen.add(node["node_key"])

    plan = {
        key: plan[key] for key in ("schema_version", "goal", "deadline", "assumptions") if key in plan
    }
    plan.setdefault("schema_version", "m5.plan.v1")
    plan.setdefault("goal", "完成当前课程的可验证学习目标")
    plan.setdefault("assumptions", [])
    plan["nodes"] = normalized_nodes
    return {
        "plan": plan,
        "personalization_summary": str(
            wrapper.get("personalization_summary")
            or plan.get("personalization_summary")
            or "模型依据当前初始学情生成了定制学习路径。"
        ),
    }


async def _generate_model_path(
    session: Any, *, llm: Any, user: DBUser, course: DBCourse,
    profile: DBProfileSnapshot, snapshot: dict[str, Any], facts: dict[str, Any],
    time_budget_minutes: int, idempotency_key: str | None, full_coverage: bool = False,
) -> tuple[PathDraftModelOutput, dict[str, Any]]:
    _require_path_model(llm)
    if full_coverage and len(facts["chapters"]) > 6:
        return await _generate_model_path_in_batches(
            session, llm=llm, user=user, course=course, profile=profile,
            snapshot=snapshot, facts=facts, time_budget_minutes=time_budget_minutes,
            idempotency_key=idempotency_key,
        )
    context = _path_model_context(
        facts, course=course, profile=profile, snapshot=snapshot,
        time_budget_minutes=time_budget_minutes,
    )
    system_prompt = (
        "你是 EduMatrix 的个性化学习路径规划专家。只能输出符合 JSON Schema 的原始 JSON 对象，不要 Markdown。"
        "必须根据输入的初始诊断证据、学习目标、偏好、时间预算、当前课程图谱和授权来源生成真实定制路径；"
        "不得复制固定章节模板，不得臆造课程外节点，不得把 unknown 证据当作已掌握。"
        "输出的 plan 必须是 m5.plan.v1，节点顺序必须满足先修关系；每个节点的 rationale 必须说明本次画像为何需要它。"
        "最终 content 必须是包含 plan.nodes 的结果对象，不要返回 JSON Schema 定义、字段说明或 schema 片段。"
    )
    prompt_payload = {
        "task": "diagnostic_personalized_learning_path",
        "idempotency_key": idempotency_key,
        "context": context,
        "output_requirements": {
            "plan_schema": "m5.plan.v1",
            "minimum_nodes": 1,
            "maximum_nodes": 6,
            "must_include": ["goal", "assumptions", "nodes", "node_key", "prerequisites", "resource_status", "estimate_min_minutes", "estimate_max_minutes", "difficulty", "rationale"],
            "shape_example": {
                "plan": {"schema_version": "m5.plan.v1", "goal": "根据当前证据安排学习", "assumptions": [], "nodes": [{"node_key": "chapter-1", "node_type": "chapter", "target_object_id": "使用输入图谱中的章节 id", "title": "使用输入图谱中的章节标题", "prerequisites": [], "resource_status": "existing", "estimate_min_minutes": 20, "estimate_max_minutes": 30, "difficulty": 0.45, "rationale": "说明该节点与当前诊断证据的关系"}]},
                "personalization_summary": "说明路径如何结合当前诊断证据调整"
            },
            "do_not_include": ["api_key", "prompt", "reasoning_content", "private_agent_log"],
        },
    }
    result = None
    for attempt in range(2):
        request_payload = dict(prompt_payload)
        if attempt:
            request_payload["retry_instruction"] = (
                "上一次返回未通过结构校验。请重新生成，严格只输出一个原始 JSON 对象，"
                "不要 Markdown、解释文字或代码围栏；所有节点和先修关系必须来自输入课程图谱。"
            )
        user_prompt = json.dumps(
            request_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        try:
            result = await execute_registered_structured_call(
                session,
                backend=llm,
                capability=Capability.PLAN,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                role="诊断结果个性化路径规划",
                operation="p1_b11_personalized_learning_path",
                response_model=PathDraftModelOutput,
                owner_public_id=user.public_id,
                course_id=course.id,
                output_constraints=OutputConstraints(
                    language="zh-CN", format="json", max_length=20000,
                    source_scope=tuple(sorted(facts["sources"])),
                    safety_boundary="仅可使用当前课程和授权来源；不发布未确认草稿。",
                ),
                response_validator=lambda value: _validate_model_plan_output(
                    value, facts=facts, owner_public_id=user.public_id,
                    course_id=course.id, session=session,
                    require_full_coverage=False,
                ),
            )
            break
        except M5CapabilityError as exc:
            if exc.code == "structured_output_invalid" and attempt == 0:
                continue
            _fail("path_draft_model_failed", "真实模型未能完成学习路径定制，请稍后重试。")
            raise AssertionError from exc
        except PathDraftError:
            raise
        except Exception as exc:
            _fail("path_draft_model_failed", "学习路径定制暂时失败，请稍后重试。")
            raise AssertionError from exc
    if result is None:
        _fail("path_draft_model_failed", "真实模型未能完成学习路径定制，请稍后重试。")
    if result.fallback_used or result.model != "deepseek-v4-flash":
        _fail("path_draft_model_policy_invalid", "路径定制未使用受治理的 deepseek-v4-flash 模型。")
    output = _validate_model_plan_output(
        result.structured_output or {}, facts=facts, owner_public_id=user.public_id,
        course_id=course.id, session=session,
    )
    return output, {
        "status": "completed",
        "call_id": result.call_id,
        "model": result.model,
        "prompt_version": result.prompt_version,
        "personalization_summary": output.personalization_summary,
    }


async def _generate_model_path_in_batches(
    session: Any, *, llm: Any, user: DBUser, course: DBCourse,
    profile: DBProfileSnapshot, snapshot: dict[str, Any], facts: dict[str, Any],
    time_budget_minutes: int, idempotency_key: str | None,
) -> tuple[PathDraftModelOutput, dict[str, Any]]:
    """Generate a full-course path through bounded model batches, then merge."""
    chapters = list(facts["chapters"])
    all_nodes: list[PlanNodeSpec] = []
    summaries: list[str] = []
    call_ids: list[str] = []
    batch_size = 4
    previous_batch_tail: str | None = None
    for batch_index in range(0, len(chapters), batch_size):
        batch = chapters[batch_index:batch_index + batch_size]
        batch_ids = {item.id for item in batch}
        batch_facts = {
            **facts,
            "chapters": batch,
            "kp_by_chapter": {key: value for key, value in facts["kp_by_chapter"].items() if key in batch_ids},
            "chapter_by_kp": {key: value for key, value in facts["chapter_by_kp"].items() if value.id in batch_ids},
        }
        context = _path_model_context(
            batch_facts, course=course, profile=profile, snapshot=snapshot,
            time_budget_minutes=time_budget_minutes,
        )
        system_prompt = (
            "你是 EduMatrix 的个性化学习路径规划专家。只能输出一个原始 JSON 对象，不要 Markdown 或 JSON Schema。"
            "当前是完整课程路径的一个章节批次；必须为分配给你的每个章节各生成一个 chapter 节点，不能遗漏、重复或臆造章节。"
            "节点顺序遵循输入章节顺序，rationale 结合当前诊断证据；已掌握章节保留但可降低难度和时长。"
        )
        payload = {
            "task": "diagnostic_personalized_learning_path_batch",
            "batch_index": batch_index // batch_size + 1,
            "batch_chapter_ids": [item.id for item in batch],
            "context": context,
            "output_requirements": {
                "plan_schema": "m5.plan.v1",
                "minimum_nodes": len(batch),
                "maximum_nodes": len(batch),
                "must_include_every_batch_chapter": True,
                "must_include": ["goal", "assumptions", "nodes", "node_key", "prerequisites", "resource_status", "estimate_min_minutes", "estimate_max_minutes", "difficulty", "rationale"],
                "do_not_include": ["api_key", "prompt", "reasoning_content", "private_agent_log"],
            },
        }
        result = None
        for attempt in range(2):
            request_payload = dict(payload)
            if attempt:
                request_payload["retry_instruction"] = "上一批输出未通过校验。请只输出分配章节的实际 plan.nodes JSON，不要输出 Schema 定义。"
            try:
                result = await execute_registered_structured_call(
                    session, backend=llm, capability=Capability.PLAN,
                    system_prompt=system_prompt,
                    user_prompt=json.dumps(request_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
                    role="诊断结果个性化路径规划",
                    operation="p1_b11_personalized_learning_path_batch",
                    response_model=PathDraftModelOutput,
                    owner_public_id=user.public_id, course_id=course.id,
                    output_constraints=OutputConstraints(language="zh-CN", format="json", max_length=14000, source_scope=tuple(sorted(facts["sources"])), safety_boundary="仅可使用当前课程和授权来源；不发布未确认草稿。"),
                    response_validator=lambda value, ids=batch_ids: _validate_model_plan_output(
                        value, facts=facts, owner_public_id=user.public_id,
                        course_id=course.id, session=session,
                        required_chapter_ids=ids,
                    ),
                )
                break
            except M5CapabilityError as exc:
                if exc.code == "structured_output_invalid" and attempt == 0:
                    continue
                _fail("path_draft_model_failed", "真实模型未能完成完整课程路径的分批定制，请稍后重试。")
        if result is None:
            _fail("path_draft_model_failed", "真实模型未能完成完整课程路径的分批定制，请稍后重试。")
        parsed = _validate_model_plan_output(
            result.structured_output or {}, facts=facts, owner_public_id=user.public_id,
            course_id=course.id, session=session, required_chapter_ids=batch_ids,
        )
        batch_nodes = list(parsed.plan.nodes)
        if previous_batch_tail and batch_nodes:
            first = batch_nodes[0]
            if previous_batch_tail not in first.prerequisites:
                batch_nodes[0] = first.model_copy(update={
                    "prerequisites": (*first.prerequisites, previous_batch_tail),
                })
        all_nodes.extend(batch_nodes)
        if batch_nodes:
            previous_batch_tail = batch_nodes[-1].node_key
        summaries.append(parsed.personalization_summary)
        call_ids.append(result.call_id)
    merged = PlanSpec(
        schema_version="m5.plan.v1",
        goal="覆盖当前课程全部章节，并按初始诊断证据安排先后顺序",
        assumptions=("完整课程章节均已纳入路径。", f"本轮时间预算为 {time_budget_minutes} 分钟。"),
        nodes=tuple(all_nodes),
    )
    final = PathDraftModelOutput(
        plan=merged,
        personalization_summary="；".join(summary for summary in summaries if summary)[:1600],
    )
    _validate_model_plan_output(
        final.model_dump(mode="json"), facts=facts, owner_public_id=user.public_id,
        course_id=course.id, session=session, require_full_coverage=True,
    )
    return final, {"status": "completed", "call_id": call_ids[-1], "call_ids": call_ids, "model": "deepseek-v4-flash", "prompt_version": "p1_b11_personalized_learning_path_batch:1.0", "personalization_summary": final.personalization_summary}


def _latest_path_generation(
    session: Any, *, owner_public_id: str, course_id: str,
) -> dict[str, Any] | None:
    row = session.query(DBModelCall).filter_by(
        owner_public_id=owner_public_id, course_id=course_id,
        capability=Capability.PLAN.value,
    ).order_by(DBModelCall.created_at.desc(), DBModelCall.id.desc()).first()
    if row is None:
        return None
    return {
        "status": row.status,
        "call_id": row.id,
        "provider": row.provider,
        "model": row.model,
        "error_code": row.error_code or None,
        "prompt_version": row.prompt_version,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def _prerequisite_closure(knowledge: dict[str, DBKnowledgePoint], targets: list[str]) -> set[str]:
    selected: set[str] = set()

    def visit(kp_id: str) -> None:
        if kp_id in selected or kp_id not in knowledge:
            return
        for prerequisite in knowledge[kp_id].prerequisites or []:
            visit(str(prerequisite))
        selected.add(kp_id)

    for target in targets:
        visit(target)
    return selected


def _draft_spec(
    facts: dict[str, Any], *, snapshot: dict[str, Any], time_budget_minutes: int,
) -> tuple[PlanSpec, dict[str, str]]:
    weak_ids = [str(item) for item in snapshot.get("weak_knowledge_point_ids") or []]
    mastered_ids = {str(item) for item in snapshot.get("mastered_knowledge_point_ids") or []}
    available_weak = [item for item in weak_ids if item in facts["chapter_by_kp"]]
    if not available_weak:
        available_weak = [
            kp.id for chapter in facts["chapters"]
            for kp in facts["kp_by_chapter"].get(chapter.id, [])
            if kp.id not in mastered_ids
        ][:1]
    selected_kps = _prerequisite_closure(facts["knowledge"], available_weak)
    selected_kps -= mastered_ids
    selected_chapter_ids = {
        facts["chapter_by_kp"][kp_id].id for kp_id in selected_kps
        if kp_id in facts["chapter_by_kp"]
    }
    ordered = [item for item in facts["chapters"] if item.id in selected_chapter_ids]
    if ordered:
        last_position = max(item.position for item in ordered)
        successor = next((item for item in facts["chapters"] if item.position > last_position), None)
        if successor is not None:
            ordered.append(successor)
    ordered = ordered[:6]
    if not ordered:
        _fail("path_draft_evidence_missing", "课程缺少可用于路径草稿的章节与画像证据")

    minutes = max(10, min(30, time_budget_minutes // len(ordered)))
    key_by_chapter = {item.id: f"textbook-{item.id}" for item in ordered}
    selected_ids = set(key_by_chapter)
    reasons: dict[str, str] = {}
    nodes = []
    target_difficulty = float(snapshot.get("difficulty_target") or 0.48)
    for index, chapter in enumerate(ordered):
        chapter_kps = facts["kp_by_chapter"].get(chapter.id, [])
        kp = chapter_kps[0] if chapter_kps else None
        prerequisite_keys = []
        if kp is not None:
            for prerequisite in kp.prerequisites or []:
                prerequisite_chapter = facts["chapter_by_kp"].get(str(prerequisite))
                if prerequisite_chapter and prerequisite_chapter.id in selected_ids:
                    prerequisite_keys.append(key_by_chapter[prerequisite_chapter.id])
        if kp and kp.id in available_weak:
            reason = "画像薄弱点：优先补齐当前课程证据不足或答题暴露的知识点。"
        elif kp and kp.id in selected_kps:
            reason = "薄弱点先修：先补齐教材中的前置知识，再进入目标章节。"
        else:
            reason = "巩固后衔接：完成薄弱点后进入相邻教材章节，验证迁移能力。"
        reasons[key_by_chapter[chapter.id]] = reason
        nodes.append(PlanNodeSpec(
            node_key=key_by_chapter[chapter.id],
            node_type="chapter",
            target_object_id=chapter.id,
            title=chapter.title,
            prerequisites=tuple(prerequisite_keys),
            resource_status="existing",
            estimate_min_minutes=minutes,
            estimate_max_minutes=minutes,
            difficulty=round(max(0.2, min(0.85, target_difficulty + index * 0.04)), 3),
            rationale=reason,
        ))
    assumptions = (
        "只使用当前课程的真实章节、canonical 来源和已记录画像证据。",
        "薄弱点与先修关系只影响草稿排序，不等同课程总评或专家结论。",
        f"本轮可用时间预算为 {time_budget_minutes} 分钟。",
    )
    return PlanSpec(
        goal="补齐当前薄弱知识点，并沿教材先修关系进入下一可验证章节",
        assumptions=assumptions,
        nodes=tuple(nodes),
    ), reasons


def _find_plan(session: Any, *, owner_public_id: str, course_id: str) -> DBPlanDraft | None:
    plans = session.query(DBPlanDraft).filter_by(
        owner_public_id=owner_public_id, course_id=course_id,
    ).filter(DBPlanDraft.archived_at.is_(None)).order_by(
        DBPlanDraft.updated_at.desc(), DBPlanDraft.id.desc(),
    ).all()
    pending = next((item for item in plans if item.status == "replan_pending"), None)
    if pending is not None:
        return pending
    active_path = session.query(DBLearningPath).filter(
        DBLearningPath.owner_public_id == owner_public_id,
        DBLearningPath.course_id == course_id,
        DBLearningPath.status.in_(("active", "paused")),
    ).order_by(DBLearningPath.updated_at.desc(), DBLearningPath.id.desc()).first()
    if active_path is not None:
        source_version = session.get(DBPlanVersion, active_path.source_plan_version_id)
        active_plan = session.get(DBPlanDraft, source_version.plan_draft_id) if source_version else None
        if active_plan is not None and active_plan.archived_at is None:
            return active_plan
    return plans[0] if plans else None


def generate_textbook_path_draft(
    session: Any, *, current_user: DBUser, course_id: str, time_budget_minutes: int,
    profile_snapshot_id: str | None = None, idempotency_key: str | None = None,
    llm: Any | None = None, full_coverage: bool = False,
) -> tuple[DBPlanDraft, bool]:
    course = session.query(DBCourse).filter_by(id=course_id).first()
    if course is None:
        _fail("course_not_found", "课程不存在")
    _authorize(session, current_user=current_user, course=course)
    profile = _latest_profile(
        session, owner_public_id=current_user.public_id, course_id=course_id,
        profile_snapshot_id=profile_snapshot_id,
    )
    if profile is None:
        _fail("path_draft_profile_missing", "尚无可用于路径草稿的课程画像")
    facts = _course_facts(session, course_id=course_id)
    snapshot = dict(profile.snapshot or {})
    plan = (
        session.query(DBPlanDraft).filter_by(
            owner_public_id=current_user.public_id,
            idempotency_key=idempotency_key,
        ).first()
        if idempotency_key else
        _find_plan(session, owner_public_id=current_user.public_id, course_id=course_id)
    )
    call_summary = {
        "profile_snapshot_id": profile.id,
        "time_budget_minutes": int(time_budget_minutes),
        "idempotency_key": idempotency_key,
    }
    if plan is not None and plan.status in {"draft", "replan_pending", "confirmed"}:
        current = session.get(DBPlanVersion, plan.current_version_id)
        matching_call = next(
            (
                item for item in session.query(DBModelCall).filter_by(
                    owner_public_id=current_user.public_id,
                    course_id=course_id,
                    capability=Capability.PLAN.value,
                    prompt_version="p1_b11_personalized_learning_path:1.0",
                    status="completed",
                ).order_by(DBModelCall.created_at.desc(), DBModelCall.id.desc()).all()
                if (item.input_summary or {}).get("profile_snapshot_id") == profile.id
                and (item.input_summary or {}).get("time_budget_minutes") == int(time_budget_minutes)
                and (not idempotency_key or (item.input_summary or {}).get("idempotency_key") == idempotency_key)
            ),
            None,
        )
        if current is not None and current.profile_snapshot_id == profile.id and matching_call is not None:
            return plan, False
    backend = llm or _build_path_model()
    try:
        generated, generation_meta = _run_model_sync(lambda: _generate_model_path(
            session,
            llm=backend,
            user=current_user,
            course=course,
            profile=profile,
            snapshot=snapshot,
            facts=facts,
            time_budget_minutes=time_budget_minutes,
            idempotency_key=idempotency_key,
            full_coverage=full_coverage,
        ))
    except PathDraftError:
        raise
    spec = generated.plan
    payload = spec.model_dump(mode="json")
    model_call = session.get(DBModelCall, generation_meta.get("call_id"))
    if model_call is not None and (
        model_call.owner_public_id != current_user.public_id
        or model_call.course_id != course_id
        or model_call.status != "completed"
    ):
        model_call = None
    if model_call is None:
        _fail("path_draft_model_audit_missing", "路径模型调用没有留下可追溯审计记录，请重试。")
    model_call.input_summary = {**(model_call.input_summary or {}), **call_summary}
    if plan is None:
        plan, _, created = create_plan_draft(
            session,
            owner_public_id=current_user.public_id,
            course_id=course_id,
            title=f"{course.title} · 诊断定制路径",
            idempotency_key=idempotency_key or f"r3-04:{current_user.public_id}:{course_id}",
            spec=spec,
            profile_snapshot_id=profile.id,
        )
        return plan, created
    propose_plan_revision(
        session,
        plan=plan,
        owner_public_id=current_user.public_id,
        expected_lock_version=plan.lock_version,
        spec=spec,
        profile_snapshot_id=profile.id,
    )
    return plan, True


def _node_projection(
    facts: dict[str, Any], *, node: dict[str, Any], reasons: dict[str, str], weak_ids: set[str],
) -> dict[str, Any]:
    chapter = next((item for item in facts["chapters"] if item.id == node.get("target_object_id")), None)
    if chapter is None:
        return {**node, "chapter": None, "source": None, "knowledge_points": [], "reason": "保留既有非教材任务。"}
    source = facts["sources"].get(chapter.source_document_id)
    source_ref = facts["ref_by_chapter"].get(chapter.id)
    kps = facts["kp_by_chapter"].get(chapter.id, [])
    reason = node.get("rationale") or reasons.get(str(node.get("node_key")), "沿既有正式路径顺序安排。")
    if node.get("prerequisites"):
        reason = f"{reason}（先修关系已校验：{', '.join(str(item) for item in node['prerequisites'])}）"
    return {
        **node,
        "chapter": {"id": chapter.id, "title": chapter.title, "position": chapter.position},
        "source": {
            "document_id": source.id if source else chapter.source_document_id,
            "title": source.title if source else "课程教材",
            "filename": source.filename if source else "",
            "license": source.license_text if source else "",
            "content_hash": source.content_hash if source else "",
            "source_ref_id": source_ref.id if source_ref else None,
            "route": f"/knowledge?course_id={chapter.course_id}&chapter_id={chapter.id}",
        },
        "knowledge_points": [
            {"id": kp.id, "title": kp.title, "is_weak": kp.id in weak_ids}
            for kp in kps
        ],
        "reason": reason,
    }


def textbook_path_draft_payload(
    session: Any, *, current_user: DBUser, course_id: str, profile_snapshot_id: str | None = None,
) -> dict[str, Any]:
    course = session.query(DBCourse).filter_by(id=course_id).first()
    if course is None:
        _fail("course_not_found", "课程不存在")
    _authorize(session, current_user=current_user, course=course)
    profile = _latest_profile(
        session, owner_public_id=current_user.public_id, course_id=course_id,
        profile_snapshot_id=profile_snapshot_id,
    )
    snapshot = dict(profile.snapshot or {}) if profile else {}
    weak_ids = {str(item) for item in snapshot.get("weak_knowledge_point_ids") or []}
    facts = _course_facts(session, course_id=course_id)
    if profile_snapshot_id:
        plan = (
            session.query(DBPlanDraft)
            .join(DBPlanVersion, DBPlanVersion.plan_draft_id == DBPlanDraft.id)
            .filter(
                DBPlanDraft.owner_public_id == current_user.public_id,
                DBPlanDraft.course_id == course_id,
                DBPlanDraft.archived_at.is_(None),
                DBPlanVersion.profile_snapshot_id == profile_snapshot_id,
                DBPlanVersion.id == DBPlanDraft.current_version_id,
            )
            .order_by(DBPlanDraft.updated_at.desc(), DBPlanDraft.id.desc())
            .first()
        )
    else:
        plan = _find_plan(session, owner_public_id=current_user.public_id, course_id=course_id)
    if plan is None:
        return {
            "schema_version": "r3.diagnostic-personalized-path-draft.v2",
            "course": {"id": course.id, "title": course.title, "version": course.version},
            "state": "not_generated",
            "plan": None,
            "nodes": [],
            "diff": None,
            "generation": _latest_path_generation(
                session, owner_public_id=current_user.public_id, course_id=course_id,
            ) or {"status": "not_started", "model": None},
            "boundary": "完成诊断并取得当前课程画像后，路径才会由真实模型定制；用户确认前仅为草稿。",
        }
    current = session.get(DBPlanVersion, plan.current_version_id)
    confirmed = session.get(DBPlanVersion, plan.confirmed_version_id) if plan.confirmed_version_id else None
    # Persisted demo paths may predate the strict m5.plan.v1 schema. Normalize
    # the legacy envelope at this read boundary so a valid course cannot be
    # blocked by textbook-path-draft validation.
    normalized_content = _coerce_model_payload(current.content, facts=facts)
    spec = PlanSpec.model_validate(normalized_content["plan"])
    _, reasons = _draft_spec(facts, snapshot=snapshot, time_budget_minutes=sum(
        int(item.estimate_max_minutes) for item in spec.nodes
    )) if current.profile_snapshot_id == (profile.id if profile else None) else (spec, {})
    diff = plan_version_diff(confirmed, current) if confirmed and confirmed.id != current.id else None
    title_by_key = {item.node_key: item.title for item in spec.nodes}
    diff_payload = None if diff is None else {
        **diff,
        "added_titles": [title_by_key.get(item, item) for item in diff["added"]],
        "removed_count": len(diff["removed"]),
        "moved_count": len(diff["moved"]),
        "changed_count": len(diff["changed"]),
        "summary": f"新增 {len(diff['added'])} 项，移除 {len(diff['removed'])} 项，调整顺序 {len(diff['moved'])} 项，修改 {len(diff['changed'])} 项。",
    }
    generation = _latest_path_generation(
        session, owner_public_id=current_user.public_id, course_id=course_id,
    )
    return {
        "schema_version": "r3.diagnostic-personalized-path-draft.v2",
        "course": {"id": course.id, "title": course.title, "version": course.version},
        "state": "draft_ready" if plan.status in {"draft", "replan_pending"} else "confirmed",
        "plan": {
            "id": plan.id,
            "title": plan.title,
            "status": plan.status,
            "lock_version": plan.lock_version,
            "current_version_id": plan.current_version_id,
            "confirmed_version_id": plan.confirmed_version_id,
            "version_number": current.version_number,
            "profile_snapshot_id": current.profile_snapshot_id,
            "goal": spec.goal,
            "assumptions": list(spec.assumptions),
            "total_minutes": sum(int(item.estimate_max_minutes) for item in spec.nodes),
        },
        "nodes": [
            _node_projection(
                facts, node=item.model_dump(mode="json"), reasons=reasons, weak_ids=weak_ids,
            )
            for item in spec.nodes
        ],
        "diff": diff_payload,
        "evidence": {
            "profile_snapshot_id": profile.id if profile else None,
            "weak_knowledge_point_ids": sorted(weak_ids),
            "chapter_count": len(facts["chapters"]),
            "canonical_source_count": len(facts["sources"]),
        },
        "generation": generation or {
            "status": "legacy",
            "model": None,
            "message": "这是已有路径版本，未记录新的模型定制调用。",
        },
        "boundary": "路径由当前初始学情、目标、偏好、时间和课程图谱定制；用户确认前仅为草稿。模型失败不会用模板冒充成功，旧正式路径仍可读取。",
    }
