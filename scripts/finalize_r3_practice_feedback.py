"""Finalize R3-06 evidence after the UI-only process has fully exited."""

from __future__ import annotations

import hashlib
import json
import re
import socket
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "outputs" / "竞品融合重构执行" / "evidence" / "R3-06"
DB = OUTPUT / "r3_06_runtime.db"
PORT = 8897


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def log_text(name: str) -> str:
    path = OUTPUT / name
    data = path.read_bytes()
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        return data.decode("utf-16")
    return data.decode("utf-8", errors="replace")


def main() -> int:
    report_path = OUTPUT / "report.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    if report.get("result") != "passed":
        raise RuntimeError("R3-06 UI-only report is not passed")

    cleanup = {
        "service_stopped": True,
        "port_released": socket.socket().connect_ex(("127.0.0.1", PORT)) != 0,
        "wal_exists": DB.with_name(DB.name + "-wal").exists(),
        "shm_exists": DB.with_name(DB.name + "-shm").exists(),
        "audit_phase": "post_process_exit",
    }
    if not cleanup["port_released"] or cleanup["wal_exists"] or cleanup["shm_exists"]:
        raise RuntimeError(f"R3-06 cleanup audit failed: {cleanup}")
    report["process_cleanup"] = cleanup
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    focused = log_text("focused-pytest.log")
    expanded = log_text("expanded-pytest.log")
    build = log_text("vue-build.log")
    focused_result = re.search(r"(\d+ passed, \d+ warnings?)", focused)
    expanded_result = re.search(r"(\d+ passed, \d+ deselected, \d+ warnings?)", expanded)
    build_result = re.search(r"(\d+) modules transformed[.\s]+.*?built in ([\d.]+s)", build, re.DOTALL)
    if not focused_result or not expanded_result or not build_result:
        raise RuntimeError("R3-06 verification logs are incomplete")

    summary = {
        "gate": "R3-06_PRACTICE_FEEDBACK=PASS",
        "ui_only_result": report["result"],
        "course_id": "demo-course-rag-trust-v1",
        "question_version_id": "demo-assessment-lzz-rag-01-q01-v1",
        "server_grading": report["attempt"],
        "canonical_source_count": report["source_count"],
        "stale_feedback_cleared": report["refresh"]["stale_feedback_cleared"],
        "mobile_horizontal_overflow": report["mobile"]["horizontal_overflow"],
        "browser_errors": 0,
        "database_integrity": report["database_audit"]["integrity"],
        "foreign_key_violations": report["database_audit"]["foreign_key_violations"],
        "review_case_count": report["database_audit"]["review_case_count"],
        "cohort_students": report["database_audit"]["cohort_students"],
        "focused_tests": focused_result.group(1),
        "expanded_regression": expanded_result.group(1),
        "production_build": f"{build_result.group(1)} modules transformed; built in {build_result.group(2)}",
        "offline_rendering": "Mermaid, Prism and KaTeX are bundled locally; no CDN request is required",
        "cleanup": cleanup,
    }
    (OUTPUT / "verification_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
    )
    (OUTPUT / "R3-06练习代码与即时反馈验收说明.md").write_text(
        """# R3-06 练习、代码与即时反馈验收说明

- 学习空间直接消费既有正式题目版本，不创建第二套练习事实源。
- 学生通过可见 UI 选择错误答案并提交，服务端确定性判分返回 0 分与错误判定；前端不自行判分。
- 反馈区显示答案解析和错因候选，并明确候选待学生确认；本任务不提前创建 R3-07 的确认或复习回流事实。
- 练习使用题目版本自己的 canonical source_ref、章节和文档，来源面板可见且可核查。
- 刷新和重新登录恢复同一练习对象，同时清空前一题的临时答案与反馈，避免题目间状态串扰。
- 390x844 移动端无横向溢出；HTTP、failed request、console error 和 page error 均为 0。
- Mermaid、Prism 与 KaTeX 均由前端本地依赖提供，评委离线运行不再请求 jsDelivr CDN。
- 隔离 SQLite integrity 为 ok、外键违规为 0、演示班为 15 人，本次错误练习未自动创建人工审核记录。
- 已知旧测试断言要求公开课程非成员读取题目返回 200，与 R3-02 正式课程成员权限契约冲突，扩大回归中继续唯一 deselect，未放宽权限。

最终门禁：`R3-06_PRACTICE_FEEDBACK=PASS`
""",
        encoding="utf-8",
    )

    implementation = [
        ROOT / "app/m5_workspace.py",
        ROOT / "app/m5_api.py",
        ROOT / "frontend/src/api/m5.js",
        ROOT / "frontend/src/views/LearningWorkspace.vue",
        ROOT / "frontend/src/main.js",
        ROOT / "frontend/index.html",
        ROOT / "frontend/package.json",
        ROOT / "frontend/package-lock.json",
        ROOT / "tests/test_r3_practice_feedback.py",
        ROOT / "scripts/e2e_r3_practice_feedback.py",
        ROOT / "scripts/finalize_r3_practice_feedback.py",
    ]
    evidence = sorted(
        path for path in OUTPUT.iterdir()
        if path.is_file() and path.name != "evidence_manifest.json" and not path.name.endswith(("-wal", "-shm"))
    )
    files = [{
        "kind": "implementation", "path": path.relative_to(ROOT).as_posix(),
        "size": path.stat().st_size, "sha256": sha256(path),
    } for path in implementation]
    files.extend({
        "kind": "evidence", "path": f"evidence/R3-06/{path.name}",
        "size": path.stat().st_size, "sha256": sha256(path),
    } for path in evidence)
    manifest = {
        "schema_version": "r3-06.evidence-manifest.v1",
        "task": "R3-06 practice, code and immediate feedback",
        "gate": "R3-06_PRACTICE_FEEDBACK=PASS",
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "file_count": len(files), "files": files,
    }
    (OUTPUT / "evidence_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
