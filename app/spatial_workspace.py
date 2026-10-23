"""Owner-scoped, versioned spatial learning workspace."""
from __future__ import annotations

import hashlib
import json
import re
from copy import deepcopy
from typing import Any

from app.database import DBSpatialLayoutVersion, DBSpatialWorkspace, DBUser

MAX_CARDS = 60
KINDS = {"note", "resource", "task", "question"}
ACTIONS = {"add_card", "move_card", "remove_card", "auto_layout", "undo"}


class SpatialWorkspaceError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message); self.code = code


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _hash(layout: dict) -> str:
    return hashlib.sha256(_canonical(layout).encode("utf-8")).hexdigest()


def _owned(db: Any, workspace_id: str, actor: DBUser) -> DBSpatialWorkspace:
    row = db.get(DBSpatialWorkspace, workspace_id)
    if not row: raise SpatialWorkspaceError("spatial.workspace_unknown", "空间工作区不存在")
    if row.owner_public_id != actor.public_id: raise SpatialWorkspaceError("spatial.workspace_forbidden", "无权访问该空间工作区")
    return row


def _version(db: Any, row: DBSpatialWorkspace) -> DBSpatialLayoutVersion:
    version = db.get(DBSpatialLayoutVersion, row.current_version_id)
    if not version: raise SpatialWorkspaceError("spatial.version_unknown", "当前布局版本不存在")
    return version


def _payload(row: DBSpatialWorkspace, version: DBSpatialLayoutVersion, history: list | None = None) -> dict:
    return {"id": row.id, "title": row.title, "status": row.status, "lock_version": row.lock_version,
            "version_id": version.id, "version_number": version.version_number,
            "layout": version.layout_data, "content_hash": version.content_hash,
            "action_type": version.action_type, "action_summary": version.action_summary,
            "history": history or []}


def list_workspaces(db: Any, actor: DBUser) -> dict:
    rows = db.query(DBSpatialWorkspace).filter_by(owner_public_id=actor.public_id, status="active").order_by(DBSpatialWorkspace.updated_at.desc()).all()
    return {"schema_version": "next.spatial-workspace-list.v1", "items": [_payload(row, _version(db, row)) for row in rows]}


def create_workspace(db: Any, *, actor: DBUser, title: str) -> dict:
    row = DBSpatialWorkspace(owner_public_id=actor.public_id, title=title.strip())
    db.add(row); db.flush()
    layout = {"canvas": {"width": 1200, "height": 760}, "cards": []}
    version = DBSpatialLayoutVersion(workspace_id=row.id, version_number=1, action_type="create",
        action_summary="创建空白空间", layout_data=layout, content_hash=_hash(layout), created_by_public_id=actor.public_id)
    db.add(version); db.flush(); row.current_version_id = version.id; db.flush()
    return _payload(row, version)


def get_workspace(db: Any, *, actor: DBUser, workspace_id: str) -> dict:
    row = _owned(db, workspace_id, actor); version = _version(db, row)
    versions = db.query(DBSpatialLayoutVersion).filter_by(workspace_id=row.id).order_by(DBSpatialLayoutVersion.version_number.desc()).limit(30).all()
    history = [{"id": item.id, "version_number": item.version_number, "action_type": item.action_type,
                "action_summary": item.action_summary, "content_hash": item.content_hash,
                "restored_from_version_id": item.restored_from_version_id} for item in versions]
    return _payload(row, version, history)


def parse_command(command: str) -> tuple[str, dict]:
    text = " ".join(command.strip().split())
    add = re.fullmatch(r"(?:新增|添加)(?:一张)?(?:卡片|便签)[：:]?(.{1,120})", text)
    if add: return "add_card", {"title": add.group(1).strip(), "kind": "note"}
    move = re.fullmatch(r"移动卡片\s+([A-Za-z0-9_-]{1,64})\s+到\s*(-?\d+(?:\.\d+)?)\s*[,，]\s*(-?\d+(?:\.\d+)?)", text)
    if move: return "move_card", {"card_id": move.group(1), "x": float(move.group(2)), "y": float(move.group(3))}
    remove = re.fullmatch(r"删除卡片\s+([A-Za-z0-9_-]{1,64})", text)
    if remove: return "remove_card", {"card_id": remove.group(1)}
    if text in {"自动整理", "整理画布", "自动布局"}: return "auto_layout", {}
    if text in {"撤销", "撤销上一步"}: return "undo", {}
    raise SpatialWorkspaceError("spatial.command_not_allowed", "仅支持新增卡片、移动卡片、删除卡片、自动整理和撤销")


def _validate_position(value: Any, maximum: float, field: str) -> float:
    try: number = float(value)
    except (TypeError, ValueError): raise SpatialWorkspaceError("spatial.position_invalid", f"{field} 坐标无效")
    if number < 0 or number > maximum: raise SpatialWorkspaceError("spatial.position_invalid", f"{field} 坐标超出画布")
    return round(number, 2)


def apply_action(db: Any, *, actor: DBUser, workspace_id: str, action: str, arguments: dict,
                 expected_version: int) -> dict:
    if action not in ACTIONS: raise SpatialWorkspaceError("spatial.action_not_allowed", "动作不在服务端白名单")
    row = _owned(db, workspace_id, actor); current = _version(db, row)
    if row.lock_version != expected_version: raise SpatialWorkspaceError("spatial.version_conflict", "布局已在其他设备更新，请刷新后重试")
    layout = deepcopy(current.layout_data); cards = layout["cards"]; summary = ""; restored = None
    if action == "add_card":
        if len(cards) >= MAX_CARDS: raise SpatialWorkspaceError("spatial.card_limit", "画布卡片已达上限")
        title = str(arguments.get("title", "")).strip()
        kind = str(arguments.get("kind", "note"))
        if not title or len(title) > 120 or kind not in KINDS: raise SpatialWorkspaceError("spatial.card_invalid", "卡片标题或类型无效")
        card_id = f"card-{current.version_number + 1}-{len(cards) + 1}"
        cards.append({"id": card_id, "title": title, "kind": kind,
                      "x": _validate_position(arguments.get("x", 40 + len(cards) % 4 * 250), 980, "x"),
                      "y": _validate_position(arguments.get("y", 40 + len(cards) // 4 * 150), 600, "y"), "w": 220, "h": 112})
        summary = f"新增卡片：{title}"
    elif action == "move_card":
        card = next((item for item in cards if item["id"] == arguments.get("card_id")), None)
        if not card: raise SpatialWorkspaceError("spatial.card_unknown", "目标卡片不存在")
        card["x"] = _validate_position(arguments.get("x"), 980, "x"); card["y"] = _validate_position(arguments.get("y"), 600, "y")
        summary = f"移动卡片：{card['title']}"
    elif action == "remove_card":
        card = next((item for item in cards if item["id"] == arguments.get("card_id")), None)
        if not card: raise SpatialWorkspaceError("spatial.card_unknown", "目标卡片不存在")
        cards.remove(card); summary = f"删除卡片：{card['title']}"
    elif action == "auto_layout":
        for index, card in enumerate(cards): card.update({"x": 40 + index % 4 * 250, "y": 40 + index // 4 * 150})
        summary = "自动整理画布"
    else:
        if current.version_number <= 1: raise SpatialWorkspaceError("spatial.undo_unavailable", "没有可撤销的布局版本")
        target = db.query(DBSpatialLayoutVersion).filter_by(workspace_id=row.id, version_number=current.version_number - 1).one()
        layout = deepcopy(target.layout_data); restored = target.id; summary = f"撤销并恢复 v{target.version_number}"
    next_version = DBSpatialLayoutVersion(workspace_id=row.id, version_number=current.version_number + 1,
        parent_version_id=current.id, restored_from_version_id=restored, action_type=action,
        action_summary=summary, layout_data=layout, content_hash=_hash(layout), created_by_public_id=actor.public_id)
    db.add(next_version); db.flush(); row.current_version_id = next_version.id; row.lock_version += 1; db.flush()
    return get_workspace(db, actor=actor, workspace_id=row.id)
