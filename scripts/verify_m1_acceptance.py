"""Generate a reproducible, non-secret M1 acceptance evidence report."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = ROOT / "outputs" / "M1_最小统一数据底座" / "03_M1自动验收报告.json"
FOCUSED_TESTS = (
    "tests/test_m1_stage_acceptance.py",
    "tests/test_m1_internal_inspection.py",
    "tests/test_m1_profile_evidence.py",
)


def _request_json(url: str, timeout: int = 60) -> dict[str, Any]:
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def _safe_health(payload: dict[str, Any]) -> dict[str, Any]:
    allowed = (
        "status", "version", "service", "llm_provider", "llm_model",
        "llm_api_key_configured", "embedding_provider", "concurrent_llm",
        "rate_limit_rpm",
    )
    return {key: payload.get(key) for key in allowed if key in payload}


def _run(command: list[str]) -> dict[str, Any]:
    completed = subprocess.run(
        command,
        cwd=ROOT,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    output = completed.stdout.strip()
    return {
        "status": "pass" if completed.returncode == 0 else "fail",
        "exit_code": completed.returncode,
        "command": command,
        "output_tail": output[-4000:],
    }


def _git_state() -> dict[str, Any]:
    revision = _run(["git", "rev-parse", "HEAD"])
    status = _run(["git", "status", "--porcelain"])
    return {
        "revision": revision["output_tail"].splitlines()[-1] if revision["status"] == "pass" else None,
        "worktree_dirty": bool(status["output_tail"].strip()),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--test-llm", action="store_true", help="Run the project's one-line real LLM connectivity check")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    report: dict[str, Any] = {
        "schema": "edumatrix-m1-acceptance-v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "base_url": args.base_url,
        "python": sys.version.split()[0],
        "git": _git_state(),
        "checks": {},
        "manual_acceptance": {
            "status": "not_required",
            "reason": "M1 原人工清单条件均有精确、可复现的等价自动证据，按总方案规则不重复执行。",
            "checklist": "04_M1人工业务验收清单.md",
        },
    }

    try:
        health = _safe_health(_request_json(f"{args.base_url.rstrip('/')}/api/health", timeout=10))
        report["checks"]["backend_health"] = {
            "status": "pass" if health.get("status") == "ok" else "fail",
            "payload": health,
        }
    except (OSError, ValueError, urllib.error.URLError) as exc:
        report["checks"]["backend_health"] = {"status": "fail", "error": str(exc)}

    if args.test_llm:
        try:
            payload = _request_json(f"{args.base_url.rstrip('/')}/api/llm/test", timeout=60)
            report["checks"]["llm_connectivity"] = {
                "status": "pass" if payload.get("status") == "ok" else "fail",
                "provider_type": payload.get("llm_type"),
                "model": payload.get("model"),
                "message": payload.get("message"),
            }
        except (OSError, ValueError, urllib.error.URLError) as exc:
            report["checks"]["llm_connectivity"] = {"status": "fail", "error": str(exc)}
    else:
        report["checks"]["llm_connectivity"] = {"status": "not_run"}

    report["checks"]["stage_acceptance_tests"] = _run([
        sys.executable, "-m", "pytest", "-q", *FOCUSED_TESTS,
    ])
    automated = [item["status"] for item in report["checks"].values()]
    report["automated_status"] = "pass" if automated and all(item == "pass" for item in automated) else "fail"

    output = args.output if args.output.is_absolute() else ROOT / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "automated_status": report["automated_status"],
        "manual_acceptance": report["manual_acceptance"]["status"],
        "output": str(output),
    }, ensure_ascii=False))
    return 0 if report["automated_status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
