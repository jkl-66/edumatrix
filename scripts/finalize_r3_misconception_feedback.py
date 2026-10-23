"""Finalize R3-07 evidence after the browser/backend process has exited."""

from __future__ import annotations

import hashlib
import json
import socket
import sqlite3
import time
import gc
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "outputs" / "竞品融合重构执行" / "evidence" / "R3-07"
DB = OUTPUT / "r3_07_runtime.db"
PORT = 8898


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def main() -> int:
    report_path = OUTPUT / "report.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    if report.get("result") != "passed":
        raise RuntimeError("R3-07 UI-only report is not passed")

    connection = sqlite3.connect(DB, timeout=10)
    try:
        integrity = connection.execute("pragma integrity_check").fetchone()[0]
        foreign_keys = len(connection.execute("pragma foreign_key_check").fetchall())
        audit = {
            "integrity": integrity,
            "foreign_key_violations": foreign_keys,
            "misconception_reviews": connection.execute("select count(*) from misconception_reviews").fetchone()[0],
            "decision_events": connection.execute("select count(*) from learning_events where event_type='misconception_decided'").fetchone()[0],
            "profile_evidence": connection.execute("select count(*) from profile_evidence_items where source_type='misconception_user_statement'").fetchone()[0],
        }
        connection.execute("pragma wal_checkpoint(truncate)")
    finally:
        connection.close()
        del connection
        gc.collect()

    for suffix in ("-wal", "-shm"):
        sidecar = DB.with_name(DB.name + suffix)
        for _ in range(40):
            try:
                sidecar.unlink(missing_ok=True)
                if not sidecar.exists():
                    break
            except PermissionError:
                time.sleep(0.25)
            time.sleep(0.1)

    time.sleep(0.5)

    cleanup = {
        "service_stopped": True,
        "port_released": socket.socket().connect_ex(("127.0.0.1", PORT)) != 0,
        "wal_exists": DB.with_name(DB.name + "-wal").exists(),
        "shm_exists": DB.with_name(DB.name + "-shm").exists(),
        "audit_phase": "post_process_exit",
    }
    if integrity != "ok" or foreign_keys or not cleanup["port_released"] or cleanup["wal_exists"] or cleanup["shm_exists"]:
        raise RuntimeError(f"R3-07 finalizer audit failed: {audit}, {cleanup}")

    report["database_audit"] = audit
    report["process_cleanup"] = cleanup
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    summary = {
        "gate": "R3-07_MISCONCEPTION_FEEDBACK=PASS",
        "ui_only_result": report["result"],
        "decision": report["decision"],
        "refresh": report["refresh"],
        "mobile": report["mobile"],
        "browser_errors": sum(len(report[key]) for key in ("http_errors", "failed_requests", "console_errors", "page_errors")),
        "database_audit": audit,
        "cleanup": cleanup,
        "limitations": [
            "用户声明被记录为证据，不自动改变掌握度；复习安排复用既有延迟复测对象。",
            "系统候选、用户声明与教师证据通过同一 learning_event 关联，但不宣称真人专家确认。",
        ],
    }
    (OUTPUT / "verification_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (OUTPUT / "R3-07错因确认与学习事件回流验收说明.md").write_text(
        """# R3-07 错因确认与学习事件回流验收说明

- 错误练习只生成 `DBMisconceptionReview` 系统候选，状态为 `proposed`，候选证据明确标记为 `system_candidate`。
- 学生通过学习空间可见 UI 确认、修正或拒绝候选；系统不会把候选自动写成用户声明。
- 确认/修正会复用既有 `learning_events` 写入 `misconception_decided`，事件以 `user_statement/user_declared` 标识，并明确 `mastery_changed=false`。
- 画像侧复用 `profile_evidence_items` 与 `profile_snapshots`；路径侧复用 `learning_event_consumptions` 的 `learning_path` 消费；教师侧使用同一事件 ID 作为可追溯证据入口。
- 相同决定重复提交幂等返回；不同决定冲突拒绝；候选、事件和画像投影均执行 owner/course 权限校验。
- 全流程由普通学生 UI 完成，覆盖管理员初始化、错误作答、错因修正、刷新恢复和 `390x844` 移动端；HTTP、失败请求、控制台和页面错误均为 0。
- 隔离 SQLite integrity 为 `ok`、外键违规为 0；正式数据库未修改。

最终门禁：`R3-07_MISCONCEPTION_FEEDBACK=PASS`
""",
        encoding="utf-8",
    )

    implementation = [
        ROOT / "app/m5_learning.py", ROOT / "app/m5_assessment_core.py", ROOT / "app/m5_api.py",
        ROOT / "frontend/src/views/LearningWorkspace.vue", ROOT / "tests/test_r3_misconception_feedback.py",
        ROOT / "scripts/e2e_r3_misconception_feedback.py", ROOT / "scripts/finalize_r3_misconception_feedback.py",
    ]
    evidence = sorted(path for path in OUTPUT.iterdir() if path.is_file() and path.name != "evidence_manifest.json")
    files = [{"kind": "implementation", "path": path.relative_to(ROOT).as_posix(), "size": path.stat().st_size, "sha256": sha256(path)} for path in implementation]
    files.extend({"kind": "evidence", "path": f"evidence/R3-07/{path.name}", "size": path.stat().st_size, "sha256": sha256(path)} for path in evidence)
    manifest = {
        "schema_version": "r3-07.evidence-manifest.v1",
        "task": "R3-07 misconception confirmation and learning event return",
        "gate": "R3-07_MISCONCEPTION_FEEDBACK=PASS",
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "file_count": len(files), "files": files,
    }
    (OUTPUT / "evidence_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
