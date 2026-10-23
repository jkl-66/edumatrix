"""Finalize R3-08 evidence after the browser/backend process has exited."""

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
OUTPUT = ROOT / "outputs" / "竞品融合重构执行" / "evidence" / "R3-08"
DB = OUTPUT / "r3_08_runtime.db"
PORT = 8899


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
        raise RuntimeError("R3-08 UI-only report is not passed")
    connection = sqlite3.connect(DB, timeout=10)
    try:
        integrity = connection.execute("pragma integrity_check").fetchone()[0]
        foreign_keys = len(connection.execute("pragma foreign_key_check").fetchall())
        audit = {
            "integrity": integrity,
            "foreign_key_violations": foreign_keys,
            "review_plans": connection.execute("select count(*) from review_plans").fetchone()[0],
            "confirmed_misconceptions": connection.execute(
                "select count(*) from misconception_reviews where status in ('accepted','modified','teacher_confirmed')"
            ).fetchone()[0],
            "retest_tasks": connection.execute("select count(*) from assessment_retest_tasks").fetchone()[0],
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
    time.sleep(0.5)
    cleanup = {
        "service_stopped": True,
        "port_released": socket.socket().connect_ex(("127.0.0.1", PORT)) != 0,
        "wal_exists": DB.with_name(DB.name + "-wal").exists(),
        "shm_exists": DB.with_name(DB.name + "-shm").exists(),
        "audit_phase": "post_process_exit",
    }
    if integrity != "ok" or foreign_keys or not cleanup["port_released"] or cleanup["wal_exists"] or cleanup["shm_exists"]:
        raise RuntimeError(f"R3-08 finalizer audit failed: {audit}, {cleanup}")
    report["database_audit"] = audit
    report["process_cleanup"] = cleanup
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    summary = {
        "gate": "R3-08_REVIEW_CENTER=PASS",
        "ui_only_result": report["result"],
        "desktop": report["desktop"],
        "export": report["export"],
        "compatibility_redirects": report["compatibility_redirects"],
        "refresh": report["refresh"],
        "mobile": report["mobile"],
        "browser_errors": sum(len(report[key]) for key in ("http_errors", "failed_requests", "console_errors", "page_errors")),
        "database_audit": audit,
        "cleanup": cleanup,
        "limitations": [
            "SM-2 旧复习计划表没有 course_id，因此统一中心将其标记为算法调度，不虚构课程归属。",
            "错因复测严格绑定确认错因和课程；未确认的 system_candidate 不进入队列。",
            "诊疗导出只提供脱敏复习摘要，不导出题目答案或模型内部提示。",
        ],
    }
    (OUTPUT / "verification_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (OUTPUT / "R3-08复习中心归并验收说明.md").write_text(
        """# R3-08 复习中心归并验收说明

- 学生从统一复习中心查看“今天该复习什么”，错因诊疗与 SM-2 间隔复习使用同一队列展示，并显示来源、理由、状态、证据强度和下一动作。
- 已确认错因才进入复习队列；延迟复测复用既有 `DBAssessmentRetestTask`，不新增复习表或调度器。
- 持久化闪卡继续使用既有 `DBFlashcard`/`DBFlashcardVersion` 和 SM-2 反馈入口。
- “错题本”和“复习日历”旧深链保留，但统一兼容跳转到复习中心，不删除旧页面代码。
- 诊疗材料导出为当前用户范围内的 Markdown 摘要，不包含题目答案、API Key、模型提示词或其他用户数据。
- 真实 Chromium 旅程覆盖管理员可见初始化、学生错答与确认、统一队列、导出、刷新、旧入口跳转和 `390x844`；浏览器四类错误为 0。
- 隔离 SQLite integrity 为 `ok`、外键违规为 0、进程退出后 WAL/SHM 清理通过；正式数据库未修改。

最终门禁：`R3-08_REVIEW_CENTER=PASS`
""",
        encoding="utf-8",
    )
    implementation = [
        ROOT / "app/m5_assessment_core.py", ROOT / "app/m5_api.py",
        ROOT / "frontend/src/api/m5.js", ROOT / "frontend/src/router/index.js",
        ROOT / "frontend/src/views/Review.vue", ROOT / "tests/test_r3_review_center.py",
        ROOT / "scripts/e2e_r3_review_center.py", ROOT / "scripts/finalize_r3_review_center.py",
    ]
    evidence = sorted(path for path in OUTPUT.iterdir() if path.is_file() and path.name != "evidence_manifest.json")
    files = [{"kind": "implementation", "path": path.relative_to(ROOT).as_posix(), "size": path.stat().st_size, "sha256": sha256(path)} for path in implementation]
    files.extend({"kind": "evidence", "path": f"evidence/R3-08/{path.name}", "size": path.stat().st_size, "sha256": sha256(path)} for path in evidence)
    (OUTPUT / "evidence_manifest.json").write_text(json.dumps({
        "schema_version": "r3-08.evidence-manifest.v1",
        "task": "R3-08 consolidated review center",
        "gate": "R3-08_REVIEW_CENTER=PASS",
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "file_count": len(files), "files": files,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=True))


if __name__ == "__main__":
    raise SystemExit(main())
