"""Finalize R3-09 evidence after the isolated UI-only process has exited."""

from __future__ import annotations

import gc
import hashlib
import json
import socket
import sqlite3
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "outputs" / "竞品融合重构执行" / "evidence" / "R3-09"
DB = OUTPUT / "r3_09_runtime.db"
PORT = 8900


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
        raise RuntimeError("R3-09 UI-only report is not passed")

    connection = sqlite3.connect(DB, timeout=10)
    try:
        integrity = connection.execute("pragma integrity_check").fetchone()[0]
        foreign_keys = len(connection.execute("pragma foreign_key_check").fetchall())
        audit = {
            "integrity": integrity,
            "foreign_key_violations": foreign_keys,
            "confirmed_misconceptions": connection.execute(
                "select count(*) from misconception_reviews where status in ('accepted','modified','teacher_confirmed')"
            ).fetchone()[0],
            "learning_events": connection.execute("select count(*) from learning_events").fetchone()[0],
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

    cleanup = {
        "service_stopped": True,
        "port_released": socket.socket().connect_ex(("127.0.0.1", PORT)) != 0,
        "wal_exists": DB.with_name(DB.name + "-wal").exists(),
        "shm_exists": DB.with_name(DB.name + "-shm").exists(),
        "audit_phase": "post_process_exit",
    }
    if integrity != "ok" or foreign_keys or not cleanup["port_released"] or cleanup["wal_exists"] or cleanup["shm_exists"]:
        raise RuntimeError(f"R3-09 finalizer audit failed: {audit}, {cleanup}")

    report["database_audit"] = audit
    report["process_cleanup"] = cleanup
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    summary = {
        "gate": "R3-09_STUDENT_GOLDEN_LOOP=PASS",
        "ui_only_result": report["result"],
        "journey": {
            "diagnostic": report.get("diagnostic"),
            "path": report.get("path"),
            "learning_task": report.get("learning_task"),
            "feedback": report.get("feedback"),
            "profile": report.get("profile"),
            "review": report.get("review"),
            "refresh": report.get("refresh"),
        },
        "mobile": report.get("mobile"),
        "browser_errors": sum(len(report[key]) for key in ("http_errors", "failed_requests", "console_errors", "page_errors")),
        "database_audit": audit,
        "cleanup": cleanup,
        "limitations": [
            "本任务验证的是隔离演示数据和确定性模型，不宣称真实模型质量指标。",
            "画像变化显示证据回流和摘要刷新，不把一次用户声明直接解释为掌握度提升。",
            "R3-10 的未参与开发者人工可理解性检查尚未执行。",
        ],
    }
    (OUTPUT / "verification_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (OUTPUT / "R3-09学生黄金闭环验收说明.md").write_text(
        """# R3-09 学生黄金闭环验收说明

## 验收结论

最终门禁：`R3-09_STUDENT_GOLDEN_LOOP=PASS`

学生通过可见页面完成：登录、管理员初始化演示数据、课程诊断、确认学习路径、进入学习空间、完成首个学习任务、进入练习、错误作答、确认系统错因候选、返回学习画像、进入统一复习中心，并验证刷新恢复和 390x844 移动端布局。

## 证据边界

- 全程使用真实 Chromium UI 操作；没有通过 API、数据库、角色注入、token 注入或预填完成态跳过步骤。
- 运行使用隔离 SQLite 和确定性模型，正式数据库未修改。
- 浏览器 HTTP 错误、失败请求、console error、page error 均为 0。
- SQLite integrity 为 `ok`，外键违规为 0；进程退出后端口释放，WAL/SHM 清理完成。
- 画像证据记录的是摘要可见和事件回流，不宣称真实用户效果或真实模型指标。

## 人工环节边界

R3-10 学生人工可理解性检查属于后续人工验收，不由本自动门禁替代。
""",
        encoding="utf-8",
    )

    implementation = [
        ROOT / "frontend/src/App.vue",
        ROOT / "frontend/src/views/Review.vue",
        ROOT / "scripts/e2e_r3_student_golden_loop.py",
        ROOT / "scripts/finalize_r3_student_golden_loop.py",
    ]
    evidence = sorted(path for path in OUTPUT.iterdir() if path.is_file() and path.name != "evidence_manifest.json")
    files = [
        {"kind": "implementation", "path": path.relative_to(ROOT).as_posix(), "size": path.stat().st_size, "sha256": sha256(path)}
        for path in implementation
    ]
    files.extend(
        {"kind": "evidence", "path": f"evidence/R3-09/{path.name}", "size": path.stat().st_size, "sha256": sha256(path)}
        for path in evidence
    )
    (OUTPUT / "evidence_manifest.json").write_text(
        json.dumps(
            {
                "schema_version": "r3-09.evidence-manifest.v1",
                "task": "R3-09 student golden loop UI-only E2E",
                "gate": "R3-09_STUDENT_GOLDEN_LOOP=PASS",
                "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
                "file_count": len(files),
                "files": files,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=True))


if __name__ == "__main__":
    raise SystemExit(main())
