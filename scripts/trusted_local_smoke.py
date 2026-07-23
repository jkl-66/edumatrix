"""Smoke test for the local research/demo code execution mode.

The backend must already be running with EDUMATRIX_SANDBOX_MODE=trusted_local.
This script intentionally records only non-sensitive status and assertion data.
It never writes the temporary account password or JWT to the report.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
BASE_URL = os.getenv("EDUMATRIX_SMOKE_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
OUTPUT_PATH = ROOT / "outputs" / "trusted_local_smoke.json"
PASSWORD = "EduMatrix123!"


def request_json(path: str, method: str = "GET", body=None, headers=None):
    payload = None
    request_headers = {"Accept": "application/json"}
    if headers:
        request_headers.update(headers)
    if body is not None:
        payload = json.dumps(body).encode("utf-8")
        request_headers["Content-Type"] = "application/json"
    request = Request(
        f"{BASE_URL}{path}",
        data=payload,
        headers=request_headers,
        method=method,
    )
    try:
        with urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:300]
        raise RuntimeError(f"HTTP {exc.code} {path}: {detail}") from exc
    except URLError as exc:
        raise RuntimeError(f"Cannot reach {BASE_URL}: {exc.reason}") from exc


def login_temporary_student() -> str:
    username = f"trusted_local_{int(time.time())}"
    request_json(
        "/api/auth/register",
        method="POST",
        body={
            "username": username,
            "password": PASSWORD,
            "display_name": "trusted local smoke student",
        },
    )
    encoded = urlencode({"username": username, "password": PASSWORD}).encode("utf-8")
    request = Request(
        f"{BASE_URL}/api/auth/login",
        data=encoded,
        headers={"Accept": "application/json", "Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))["access_token"]
    except (HTTPError, URLError, KeyError, json.JSONDecodeError) as exc:
        raise RuntimeError("temporary smoke account login failed") from exc


def main() -> int:
    started_at = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    report = {
        "base_url": BASE_URL,
        "started_at": started_at,
        "mode_expected": "trusted_local",
        "checks": {},
    }
    try:
        status = request_json("/api/code/status")
        report["checks"]["status"] = {
            "mode": status.get("mode"),
            "execution_enabled": status.get("execution_enabled"),
            "isolation": status.get("isolation"),
            "security_level": status.get("security_level"),
        }
        assert status.get("mode") == "trusted_local", status
        assert status.get("execution_enabled") is True, status
        assert status.get("isolation") == "trusted_local_child_process", status

        token = login_temporary_student()
        headers = {"Authorization": f"Bearer {token}"}

        safe_result = request_json(
            "/api/code/run",
            method="POST",
            body={"language": "python", "code": "print(6 * 7)"},
            headers=headers,
        )
        safe_output = str(safe_result.get("output", ""))
        assert "42" in safe_output, safe_result
        report["checks"]["safe_execution"] = {
            "passed": True,
            "output_contains_42": True,
            "error_present": bool(safe_result.get("error")),
        }

        blocked_result = request_json(
            "/api/code/run",
            method="POST",
            body={"language": "python", "code": "import os\nos.system('echo unsafe')"},
            headers=headers,
        )
        blocked_output = str(blocked_result.get("output", ""))
        blocked_error = str(blocked_result.get("error", ""))
        assert not blocked_output, blocked_result
        assert blocked_error, blocked_result
        report["checks"]["blocked_os_import"] = {
            "passed": True,
            "output_empty": True,
            "error_present": True,
        }
        report["result"] = "passed"
        return 0
    except Exception as exc:
        report["result"] = "failed"
        report["error"] = f"{type(exc).__name__}: {exc}"[:500]
        return 1
    finally:
        report["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
        OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
        OUTPUT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    raise SystemExit(main())
