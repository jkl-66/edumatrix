"""Deterministic, server-computed teaching animation projects and versions."""

from __future__ import annotations

import hashlib
import json
import math
from typing import Any

from app.authorization import ObjectAccess, active_course_role, can_access_object
from app.database import DBCourse, DBTeachingAnimation, DBTeachingAnimationVersion, DBUser


TEMPLATE_ID = "gradient-descent-2d-v1"
PARAMETER_SPECS = {
    "initial_x": {"label": "初始位置 x0", "minimum": -10.0, "maximum": 10.0, "step": 0.1, "default": 8.0},
    "target_x": {"label": "目标位置 x*", "minimum": -5.0, "maximum": 5.0, "step": 0.1, "default": 1.0},
    "learning_rate": {"label": "学习率", "minimum": 0.01, "maximum": 1.0, "step": 0.01, "default": 0.15},
    "curvature": {"label": "曲率", "minimum": 0.1, "maximum": 3.0, "step": 0.1, "default": 1.0},
    "step_count": {"label": "迭代步数", "minimum": 3, "maximum": 80, "step": 1, "default": 24},
}
FORMULA = {
    "loss": "L(x) = curvature * (x - target_x)^2",
    "gradient": "gradient = 2 * curvature * (x - target_x)",
    "update": "x_next = x - learning_rate * gradient",
    "stability": "0 < learning_rate * 2 * curvature < 2",
    "engine_version": "edumatrix-deterministic-gradient-v1",
}


class TeachingAnimationError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


def _fail(code: str, message: str) -> None:
    raise TeachingAnimationError(code, message)


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _template() -> dict[str, Any]:
    return {
        "id": TEMPLATE_ID,
        "title": "二维梯度下降损失曲线",
        "description": "用确定性逐帧计算展示学习率、曲率和初始位置如何影响优化轨迹。",
        "parameters": PARAMETER_SPECS,
        "formula": FORMULA,
        "rendering": "Canvas 曲线与轨迹；Canvas 不可用时使用逐帧数据表",
        "data_boundary": "所有帧由服务端冻结公式计算，不调用外部模型，不包含随机结果。",
    }


def list_templates() -> dict[str, Any]:
    return {"items": [_template()], "count": 1}


def _number(parameters: dict[str, Any], key: str) -> float:
    raw = parameters.get(key, PARAMETER_SPECS[key]["default"])
    if isinstance(raw, bool):
        _fail("teaching_animation.parameter_invalid", f"参数 {key} 必须是数值")
    try:
        value = float(raw)
    except (TypeError, ValueError):
        _fail("teaching_animation.parameter_invalid", f"参数 {key} 必须是数值")
    if not math.isfinite(value):
        _fail("teaching_animation.parameter_invalid", f"参数 {key} 必须是有限数值")
    spec = PARAMETER_SPECS[key]
    if value < spec["minimum"] or value > spec["maximum"]:
        _fail(
            "teaching_animation.parameter_out_of_range",
            f"参数 {key} 必须在 {spec['minimum']} 到 {spec['maximum']} 之间",
        )
    return value


def normalize_parameters(parameters: dict[str, Any] | None) -> dict[str, Any]:
    source = parameters or {}
    unknown = sorted(set(source) - set(PARAMETER_SPECS))
    if unknown:
        _fail("teaching_animation.parameter_unknown", f"不支持的参数：{', '.join(unknown)}")
    result: dict[str, Any] = {
        "initial_x": round(_number(source, "initial_x"), 10),
        "target_x": round(_number(source, "target_x"), 10),
        "learning_rate": round(_number(source, "learning_rate"), 10),
        "curvature": round(_number(source, "curvature"), 10),
    }
    step_raw = source.get("step_count", PARAMETER_SPECS["step_count"]["default"])
    if isinstance(step_raw, bool):
        _fail("teaching_animation.parameter_invalid", "参数 step_count 必须是整数")
    try:
        step_float = float(step_raw)
    except (TypeError, ValueError):
        _fail("teaching_animation.parameter_invalid", "参数 step_count 必须是整数")
    if not step_float.is_integer():
        _fail("teaching_animation.parameter_invalid", "参数 step_count 必须是整数")
    step_count = int(step_float)
    spec = PARAMETER_SPECS["step_count"]
    if step_count < spec["minimum"] or step_count > spec["maximum"]:
        _fail("teaching_animation.parameter_out_of_range", "参数 step_count 必须在 3 到 80 之间")
    result["step_count"] = step_count
    stability_factor = result["learning_rate"] * 2.0 * result["curvature"]
    if not 0.0 < stability_factor < 2.0:
        _fail(
            "teaching_animation.unstable_parameters",
            "学习率与曲率组合不满足稳定条件：0 < learning_rate * 2 * curvature < 2",
        )
    return result


def compute_frames(parameters: dict[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    params = normalize_parameters(parameters)
    x = params["initial_x"]
    target = params["target_x"]
    curvature = params["curvature"]
    learning_rate = params["learning_rate"]
    frames: list[dict[str, Any]] = []
    for step in range(params["step_count"] + 1):
        loss = curvature * ((x - target) ** 2)
        gradient = 2.0 * curvature * (x - target)
        distance = abs(x - target)
        frames.append({
            "index": step,
            "x": round(x, 10),
            "loss": round(loss, 10),
            "gradient": round(gradient, 10),
            "distance_to_target": round(distance, 10),
            "state": "converged" if distance <= 0.001 else "optimizing",
        })
        x = x - learning_rate * gradient
    quality = {
        "deterministic": True,
        "randomness": False,
        "stability_factor": round(learning_rate * 2.0 * curvature, 10),
        "stable": True,
        "converged": frames[-1]["state"] == "converged",
        "initial_loss": frames[0]["loss"],
        "final_loss": frames[-1]["loss"],
        "loss_reduction": round(frames[0]["loss"] - frames[-1]["loss"], 10),
        "frame_count": len(frames),
    }
    return frames, quality


def _course(db: Any, actor: DBUser, course_id: str | None) -> DBCourse | None:
    if not course_id:
        return None
    row = db.get(DBCourse, course_id)
    if row is None:
        _fail("teaching_animation.course_unknown", "课程不存在")
    from course_catalog import course_is_selectable
    if not course_is_selectable(db, row):
        _fail("teaching_animation.course_unavailable", "课程已停止发布或没有可用学习资料")
    role = active_course_role(db, course_id=row.id, user_public_id=actor.public_id)
    allowed = can_access_object(
        actor,
        ObjectAccess("course", row.id, owner_public_id=row.owner_public_id, course_id=row.id, visibility=row.visibility),
        action="read",
        course_role=role,
    )
    if not allowed:
        _fail("teaching_animation.course_forbidden", "无权将动画关联到该课程")
    return row


def _owned(db: Any, actor: DBUser, animation_id: str) -> DBTeachingAnimation:
    row = db.get(DBTeachingAnimation, animation_id)
    if row is None:
        _fail("teaching_animation.unknown", "教学动画项目不存在")
    if row.owner_public_id != actor.public_id:
        _fail("teaching_animation.forbidden", "无权访问该教学动画项目")
    return row


def _version_payload(row: DBTeachingAnimationVersion) -> dict[str, Any]:
    return {
        "id": row.id,
        "version_number": row.version_number,
        "parameters": row.parameters,
        "frames": row.frame_data,
        "formula": row.formula_snapshot,
        "quality": row.quality_snapshot,
        "content_hash": row.content_hash,
        "created_at": row.created_at,
    }


def _project_payload(db: Any, row: DBTeachingAnimation, *, include_versions: bool = True) -> dict[str, Any]:
    current = db.get(DBTeachingAnimationVersion, row.current_version_id) if row.current_version_id else None
    versions = (
        db.query(DBTeachingAnimationVersion)
        .filter_by(animation_id=row.id)
        .order_by(DBTeachingAnimationVersion.version_number.desc())
        .all()
    ) if include_versions else []
    max_frame = max(0, len(current.frame_data) - 1) if current else 0
    current_frame = min(row.current_frame, max_frame)
    return {
        "id": row.id,
        "title": row.title,
        "template_id": row.template_id,
        "course_id": row.course_id,
        "current_version_id": row.current_version_id,
        "current_frame": current_frame,
        "playback_status": row.playback_status,
        "lock_version": row.lock_version,
        "max_frame": max_frame,
        "current_version": _version_payload(current) if current else None,
        "versions": [_version_payload(item) for item in versions],
        "created_at": row.created_at,
        "updated_at": row.updated_at,
        "boundary": "项目和播放位置属于当前用户；帧序列是服务端确定性计算形成的不可变版本。",
    }


def list_projects(db: Any, *, actor: DBUser) -> dict[str, Any]:
    rows = (
        db.query(DBTeachingAnimation)
        .filter_by(owner_public_id=actor.public_id)
        .order_by(DBTeachingAnimation.updated_at.desc(), DBTeachingAnimation.id.asc())
        .all()
    )
    return {"items": [_project_payload(db, row, include_versions=False) for row in rows], "count": len(rows)}


def create_project(
    db: Any, *, actor: DBUser, title: str, template_id: str,
    parameters: dict[str, Any] | None, course_id: str | None,
) -> dict[str, Any]:
    if template_id != TEMPLATE_ID:
        _fail("teaching_animation.template_unknown", "教学动画模板不存在")
    clean_title = " ".join(title.split())[:256]
    if not clean_title:
        _fail("teaching_animation.title_required", "项目标题不能为空")
    _course(db, actor, course_id)
    row = DBTeachingAnimation(
        owner_public_id=actor.public_id,
        course_id=course_id,
        title=clean_title,
        template_id=template_id,
    )
    db.add(row)
    db.flush()
    result = create_version(db, actor=actor, animation_id=row.id, parameters=parameters, expected_lock_version=1)
    result["created"] = True
    return result


def create_version(
    db: Any, *, actor: DBUser, animation_id: str,
    parameters: dict[str, Any] | None, expected_lock_version: int,
) -> dict[str, Any]:
    row = _owned(db, actor, animation_id)
    if row.lock_version != expected_lock_version:
        _fail("teaching_animation.conflict", "项目已在其他页面更新，请刷新后重试")
    params = normalize_parameters(parameters)
    identity = {"template_id": row.template_id, "parameters": params, "formula": FORMULA}
    content_hash = hashlib.sha256(_canonical(identity).encode("utf-8")).hexdigest()
    existing = db.query(DBTeachingAnimationVersion).filter_by(animation_id=row.id, content_hash=content_hash).one_or_none()
    if existing is not None:
        return {**_project_payload(db, row), "version_created": False}
    frames, quality = compute_frames(params)
    number = db.query(DBTeachingAnimationVersion).filter_by(animation_id=row.id).count() + 1
    version = DBTeachingAnimationVersion(
        animation_id=row.id,
        version_number=number,
        parameters=params,
        frame_data=frames,
        formula_snapshot=FORMULA,
        quality_snapshot=quality,
        content_hash=content_hash,
        created_by_public_id=actor.public_id,
    )
    db.add(version)
    db.flush()
    row.current_version_id = version.id
    row.current_frame = 0
    row.playback_status = "paused"
    row.lock_version += 1
    db.flush()
    return {**_project_payload(db, row), "version_created": True}


def get_project(db: Any, *, actor: DBUser, animation_id: str) -> dict[str, Any]:
    return _project_payload(db, _owned(db, actor, animation_id))


def update_playback(
    db: Any, *, actor: DBUser, animation_id: str, current_frame: int,
    playback_status: str, expected_lock_version: int,
) -> dict[str, Any]:
    row = _owned(db, actor, animation_id)
    if row.lock_version != expected_lock_version:
        _fail("teaching_animation.conflict", "播放位置已在其他页面更新，请刷新后重试")
    if playback_status not in {"playing", "paused"}:
        _fail("teaching_animation.playback_invalid", "播放状态只能是 playing 或 paused")
    version = db.get(DBTeachingAnimationVersion, row.current_version_id)
    if version is None:
        _fail("teaching_animation.version_missing", "动画项目没有可播放版本")
    max_frame = len(version.frame_data) - 1
    if current_frame < 0 or current_frame > max_frame:
        _fail("teaching_animation.frame_out_of_range", f"当前帧必须在 0 到 {max_frame} 之间")
    row.current_frame = current_frame
    row.playback_status = "paused" if current_frame == max_frame else playback_status
    row.lock_version += 1
    db.flush()
    return _project_payload(db, row)
