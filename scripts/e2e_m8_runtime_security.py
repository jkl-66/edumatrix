"""Run M8 runtime authorization and trusted-local sandbox checks in isolation."""

from __future__ import annotations

import hashlib
import json
import os
import socket
import sqlite3
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = Path(os.environ.get(
    "EDUMATRIX_E2E_OUTPUT_DIR",
    ROOT / "outputs" / "M8_系统硬化与完全体验收" / "evidence" / "runtime-security-20260803",
))
DB_PATH = Path(os.environ.get("EDUMATRIX_E2E_DB_PATH", ROOT / "outputs" / "_m8_runtime_security.db"))
EVIDENCE_DB = OUTPUT / "m8_runtime_security.db"
PORT = int(os.environ.get("EDUMATRIX_E2E_PORT", "8775"))
BASE_URL = f"http://127.0.0.1:{PORT}"


def wait_port(open_: bool, timeout: float = 45.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with socket.socket() as sock:
            sock.settimeout(0.25)
            available = sock.connect_ex(("127.0.0.1", PORT)) == 0
        if available is open_:
            return
        time.sleep(0.2)
    raise RuntimeError("port 8775 state timeout")


def stop(process: subprocess.Popen | None) -> None:
    if process is None or process.poll() is not None:
        return
    subprocess.run(
        ["taskkill", "/PID", str(process.pid), "/T", "/F"],
        capture_output=True,
        text=True,
        timeout=15,
    )
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        pass
    wait_port(False, 15)


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def teacher_token() -> str:
    body = urlencode({"username": "teacher", "password": "admin123"}).encode("utf-8")
    request = Request(
        f"{BASE_URL}/api/auth/login",
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    with urlopen(request, timeout=20) as response:
        return json.loads(response.read().decode("utf-8"))["access_token"]


def deployment_report(token: str) -> dict:
    request = Request(
        f"{BASE_URL}/api/v1/m8/deployment-preflight",
        headers={"Authorization": f"Bearer {token}"},
    )
    with urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def main() -> int:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    for path in OUTPUT.iterdir():
        if path.is_file():
            path.unlink()
    for suffix in ("", "-wal", "-shm"):
        path = Path(f"{DB_PATH}{suffix}")
        if path.exists():
            path.unlink()
    env = os.environ.copy()
    env.update({
        "EDUMATRIX_DB_PATH": str(DB_PATH),
        "EDUMATRIX_AUTH_SECRET_KEY": "m8-runtime-security-isolated-secret-2026",
        "EDUMATRIX_DEMO_MODE": "1",
        "EDUMATRIX_LLM_PROVIDER": "deterministic",
        "EDUMATRIX_LLM_MODEL": "deterministic",
        "EDUMATRIX_LLM_API_KEY": "",
        "EDUMATRIX_LLM_ENDPOINT": "",
        "EDUMATRIX_MULTIMODAL_LLM_API_KEY": "",
        "EDUMATRIX_MULTIMODAL_LLM_ENDPOINT": "",
        "EDUMATRIX_USE_FAISS": "0",
        "EDUMATRIX_SANDBOX_MODE": "trusted_local",
        "EDUMATRIX_RELOAD": "0",
        "EDUMATRIX_HOST": "127.0.0.1",
        "EDUMATRIX_PORT": str(PORT),
        "EDUMATRIX_SECURITY_BASE_URL": BASE_URL,
        "EDUMATRIX_SECURITY_OUTPUT_PATH": str(OUTPUT / "authorization-matrix.json"),
        "EDUMATRIX_SMOKE_BASE_URL": BASE_URL,
        "EDUMATRIX_SMOKE_OUTPUT_PATH": str(OUTPUT / "trusted-local-smoke.json"),
        "PYTHONUNBUFFERED": "1",
    })
    report = {
        "schema_version": "m8.runtime-security-e2e.v1",
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "checks": {},
    }
    backend = None
    try:
        with (OUTPUT / "backend.log").open("w", encoding="utf-8") as backend_log:
            backend = subprocess.Popen(
                [sys.executable, "run.py"], cwd=ROOT, env=env,
                stdout=backend_log, stderr=subprocess.STDOUT,
            )
            wait_port(True)
            for name, script in (
                ("authorization_matrix", "scripts/runtime_security_matrix.py"),
                ("trusted_local_smoke", "scripts/trusted_local_smoke.py"),
            ):
                completed = subprocess.run(
                    [sys.executable, script], cwd=ROOT, env=env,
                    capture_output=True, text=True, timeout=180,
                )
                report["checks"][name] = {
                    "exit_code": completed.returncode,
                    "passed": completed.returncode == 0,
                }
                if completed.returncode != 0:
                    raise RuntimeError(f"{name} failed: {completed.stderr[-500:]}")
            preflight = deployment_report(teacher_token())
            (OUTPUT / "deployment-preflight.json").write_text(
                json.dumps(preflight, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
            report["checks"]["deployment_preflight"] = {
                "status": preflight["status"],
                "generation_mode": preflight["checks"]["generation_runtime"]["mode"],
                "retrieval_backend": preflight["checks"]["retrieval"]["backend"],
                "secret_values_included": preflight["configuration"]["secret_values_included"],
            }
            assert preflight["status"] == "ready"
            assert preflight["checks"]["generation_runtime"]["mode"] == "deterministic_demo"
            assert preflight["configuration"]["secret_values_included"] is False
            report["result"] = "passed"
    except Exception as exc:
        report["result"] = "failed"
        report["error"] = f"{type(exc).__name__}: {exc}"[:1000]
        raise
    finally:
        report["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
        stop(backend)
        if DB_PATH.exists():
            with sqlite3.connect(DB_PATH) as source, sqlite3.connect(EVIDENCE_DB) as target:
                source.backup(target)
                report["checks"]["sqlite_integrity"] = target.execute(
                    "PRAGMA integrity_check"
                ).fetchone()[0]
        (OUTPUT / "report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        files = [
            {"file": path.name, "bytes": path.stat().st_size, "sha256": digest(path)}
            for path in sorted(OUTPUT.iterdir())
            if path.is_file() and path.name != "manifest.json" and not path.name.endswith(("-wal", "-shm"))
        ]
        (OUTPUT / "manifest.json").write_text(
            json.dumps({"schema_version": "m8.runtime-security-manifest.v1", "files": files}, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
