#!/usr/bin/env python3
"""Synchronize the long-form live status surfaces after F10-T03 closes."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def replace_line_once(path: Path, prefix: str, replacement: str) -> None:
    """Replace one live status line without depending on wrapped long prose."""
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    matches = [index for index, line in enumerate(lines) if line.startswith(prefix)]
    if not matches:
        completed = [index for index, line in enumerate(lines) if line.startswith(replacement)]
        if len(completed) == 1:
            return
    if len(matches) != 1:
        raise RuntimeError(f"expected one stale status line in {path}, found {len(matches)}")
    newline = "\n" if lines[matches[0]].endswith("\n") else ""
    lines[matches[0]] = replacement + newline
    path.write_text("".join(lines), encoding="utf-8")


def replace_text_once(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count == 0 and text.count(new) == 1:
        return
    if count != 1:
        raise RuntimeError(f"expected one stale status token in {path}, found {count}")
    path.write_text(text.replace(old, new), encoding="utf-8")


def main() -> None:
    status_path = ROOT / "outputs" / "原系统融合重构执行" / "00_唯一执行状态.md"
    replace_text_once(status_path, "F10-T03-EVIDENCE-VERIFIED", "F10-T03-CLOSED")
    replace_line_once(
        status_path,
        "- 当前官方 checkpoint 以 `evidence/context_recovery/current_checkpoint.json` 的实时准据。",
        "- 当前官方 checkpoint 以 `evidence/context_recovery/current_checkpoint.json` 的实时 `phase/task/state/snapshot_sequence` 为唯一准据。当前任务是 `F10 / F10-T03 / CLOSED`，由 F10-T03 逐原子账本约束；本任务无主责原子，27 条相关原子已完成逐条兼容证据核验并通过最终关闭迁移。F10-T01、F10-T02 的关闭快照与逐原子证据继续保持不变，不得重做。F10-T03 不修改前端、正式数据库、Git 或现有压缩包。",
    )
    replace_line_once(
        status_path,
        "`F10 / F10-T02 / CLOSED`",
        "当前 checkpoint 为 `F10 / F10-T03 / CLOSED`，关闭快照为 `0469_F10-T03_CLOSED_20260819T063809+0800.json`。F10-T03 的 27 条相关原子均为 `COMPATIBILITY_VERIFIED`，官方恢复加载器、隔离评委窄烟测、29 条聚焦回归、运行前置检查、动态规格交叉校验和保护哈希均已通过。F10-T01/T02 的既有关闭证据继续保留；本目标不加载下一任务、不修改前端、正式数据库、Git 或交付压缩包。",
    )
    replace_line_once(
        ROOT / "outputs" / "原系统融合重构执行" / "11_上下文恢复与实施索引.md",
        "- F9-T01 至 F9-T04、F9 阶段联合验收与 F10-T01、F10-T02 已 `CLOSED / PASS`；",
        "- F9-T01 至 F9-T04、F9 阶段联合验收与 F10-T01、F10-T02、F10-T03 已 `CLOSED / PASS`；当前目标在 F10-T03 关闭后停止，不加载其他任务。不得做移动端、企业治理、专家认证、真实企业集成、视频生成、比赛 PPT、比赛打包或目标外最终交付。",
    )
    replace_line_once(
        ROOT / "outputs" / "原系统融合重构执行" / "11_上下文恢复与实施索引.md",
        "当前 checkpoint 为 `F10 / F10-T02 / CLOSED`，",
        "当前 checkpoint 为 `F10 / F10-T03 / CLOSED`，快照为 `0469_F10-T03_CLOSED_20260819T063809+0800.json`。F10-T03 的 27 条相关原子均为 `COMPATIBILITY_VERIFIED`；最终上下文清单、评委窄烟测、29 条聚焦回归、运行前置检查、20 项规格交叉校验、正式数据库和三个 ZIP 保护哈希均通过。当前目标停止；不得加载其他任务或把本任务误写成产品 UI 重构。",
    )
    print("F10-T03 status surfaces synchronized")


if __name__ == "__main__":
    main()
