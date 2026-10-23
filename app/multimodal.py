from __future__ import annotations

import math
from typing import Any


class RegionSelectionError(ValueError):
    pass


def normalized_rect(value: Any) -> dict[str, float]:
    if not isinstance(value, dict):
        raise RegionSelectionError("图片选区坐标无效")
    try:
        rect = {key: float(value[key]) for key in ("x", "y", "width", "height")}
    except (KeyError, TypeError, ValueError) as exc:
        raise RegionSelectionError("图片选区坐标无效") from exc
    if not all(math.isfinite(number) for number in rect.values()):
        raise RegionSelectionError("图片选区坐标无效")
    if rect["x"] < 0 or rect["y"] < 0 or rect["width"] <= 0 or rect["height"] <= 0:
        raise RegionSelectionError("图片选区必须位于页面内")
    if rect["x"] + rect["width"] > 1 or rect["y"] + rect["height"] > 1:
        raise RegionSelectionError("图片选区必须位于页面内")
    if rect["width"] * rect["height"] < 0.0001:
        raise RegionSelectionError("图片选区过小，请重新框选")
    return {key: round(number, 6) for key, number in rect.items()}


def _intersection_ratio(first: dict[str, float], second: dict[str, float]) -> float:
    left = max(first["x"], second["x"])
    top = max(first["y"], second["y"])
    right = min(first["x"] + first["width"], second["x"] + second["width"])
    bottom = min(first["y"] + first["height"], second["y"] + second["height"])
    if right <= left or bottom <= top:
        return 0.0
    return ((right - left) * (bottom - top)) / (second["width"] * second["height"])


def extract_region_text(page: dict[str, Any], rect: dict[str, float]) -> tuple[str, list[str]]:
    text_parts: list[str] = []
    region_ids: list[str] = []
    for region in page.get("regions") or []:
        if not isinstance(region, dict) or (region.get("privacy") or {}).get("sensitive"):
            continue
        try:
            region_rect = normalized_rect(region.get("bbox"))
        except RegionSelectionError:
            continue
        if _intersection_ratio(rect, region_rect) < 0.2:
            continue
        text = str((region.get("content") or {}).get("text") or "").strip()
        if text:
            text_parts.append(text)
        if region.get("region_id"):
            region_ids.append(str(region["region_id"]))
    return "\n".join(dict.fromkeys(text_parts)), list(dict.fromkeys(region_ids))
