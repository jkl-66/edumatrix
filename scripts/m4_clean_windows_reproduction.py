"""Reproduce the runnable competition archive in a fresh Windows directory."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
from urllib.request import urlopen
import zipfile


ROOT = Path(__file__).resolve().parents[1]
ARCHIVE = ROOT / "outputs" / "00015352作品.zip"
RUNTIME = ROOT / "outputs" / "package_smoke_runtime_v2"
EVIDENCE = (
    ROOT / "outputs" / "M4_量化评测与可靠性交付" / "evidence"
    / "clean-windows-reproduction-20260802"
)
PORT = 8765
DEFAULT_VENV = Path("D:/EM4V")


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def run(command: list[str], *, cwd: Path, env: dict[str, str] | None = None, timeout: int = 1800) -> dict[str, object]:
    started = time.monotonic()
    result = subprocess.run(
        command, cwd=cwd, env=env, capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=timeout,
    )
    record = {
        "command": [Path(command[0]).name, *command[1:]],
        "returncode": result.returncode,
        "duration_seconds": round(time.monotonic() - started, 3),
        "stdout_tail": result.stdout[-4000:],
        "stderr_tail": result.stderr[-4000:],
    }
    if result.returncode:
        raise RuntimeError(json.dumps(record, ensure_ascii=False))
    return record


def safe_extract(archive: Path, target: Path) -> int:
    target_resolved = target.resolve()
    with zipfile.ZipFile(archive) as package:
        if package.testzip() is not None:
            raise ValueError("runnable archive CRC verification failed")
        for item in package.infolist():
            destination = (target / item.filename).resolve()
            if target_resolved != destination and target_resolved not in destination.parents:
                raise ValueError(f"archive path escapes target: {item.filename}")
        package.extractall(target)
        return len(package.infolist())


def wait_for_health(process: subprocess.Popen[str], timeout: float = 90.0) -> dict[str, object]:
    deadline = time.monotonic() + timeout
    last_error = ""
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"backend exited before health check: {process.returncode}")
        try:
            with urlopen(f"http://127.0.0.1:{PORT}/api/health", timeout=3) as response:
                payload = json.loads(response.read().decode("utf-8"))
                if response.status == 200 and payload.get("status") == "ok":
                    return payload
        except Exception as exc:
            last_error = f"{type(exc).__name__}: {exc}"
        time.sleep(0.5)
    raise RuntimeError(f"backend health timeout: {last_error}")


def terminate_process_tree(process: subprocess.Popen[str]) -> None:
    if process.poll() is not None:
        return
    subprocess.run(
        ["taskkill", "/PID", str(process.pid), "/T", "/F"],
        capture_output=True, text=True, timeout=30,
    )


def assemble_manifest(output: Path, report: dict[str, object]) -> dict[str, object]:
    report_path = output / "report.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    files: dict[str, dict[str, object]] = {}
    for path in sorted(output.rglob("*")):
        if path.is_file() and path.name != "manifest.json":
            relative = path.relative_to(output).as_posix()
            files[relative] = {"bytes": path.stat().st_size, "sha256": sha256(path)}
    manifest = {
        "schema_version": "m4.clean-windows-reproduction-manifest.v1",
        "files": files,
    }
    (output / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
    )
    return manifest


def verify(output: Path) -> dict[str, object]:
    manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    actual = {
        path.relative_to(output).as_posix()
        for path in output.rglob("*") if path.is_file() and path.name != "manifest.json"
    }
    if actual != set(manifest["files"]):
        raise ValueError("clean reproduction evidence has missing or unexpected files")
    for relative, expected in manifest["files"].items():
        path = output / relative
        if path.stat().st_size != expected["bytes"] or sha256(path) != expected["sha256"]:
            raise ValueError(f"clean reproduction evidence changed: {relative}")
    report = json.loads((output / "report.json").read_text(encoding="utf-8"))
    if report.get("result") != "passed" or report.get("independent_third_party_machine") is not False:
        raise ValueError("clean reproduction result or independence boundary changed")
    return report


def reproduce(runtime: Path, output: Path, venv: Path, *, reuse_venv: bool = False) -> dict[str, object]:
    if runtime.exists() or output.exists() or (venv.exists() and not reuse_venv):
        raise FileExistsError("refusing to overwrite clean reproduction runtime, venv, or evidence")
    if reuse_venv and not (venv / "Scripts" / "python.exe").is_file():
        raise FileNotFoundError("reused clean reproduction venv is incomplete")
    runtime.mkdir(parents=True)
    output.mkdir(parents=True)
    report: dict[str, object] = {
        "schema_version": "m4.clean-windows-reproduction.v1",
        "started_at": datetime.now(timezone.utc).isoformat(),
        "result": "running",
        "platform": sys.platform,
        "independent_third_party_machine": False,
        "environment_definition": "fresh extraction plus new Python 3.11 venv on the same Windows host",
        "archive": {"file": ARCHIVE.name, "bytes": ARCHIVE.stat().st_size, "sha256": sha256(ARCHIVE)},
        "steps": {},
    }
    backend: subprocess.Popen[str] | None = None
    backend_log = output / "backend.log"
    try:
        report["steps"]["extract"] = {"entries": safe_extract(ARCHIVE, runtime)}
        forbidden = [
            str(path.relative_to(runtime)) for path in runtime.rglob("*")
            if path.is_file() and (
                path.name == ".env" or ".venv" in path.parts or "node_modules" in path.parts
                or path.name.endswith((".db-wal", ".db-shm"))
            )
        ]
        if forbidden:
            raise ValueError(f"archive extracted forbidden runtime files: {forbidden[:10]}")
        python = venv / "Scripts" / "python.exe"
        if reuse_venv:
            report["steps"]["create_venv"] = {"reused_from_same_clean_reproduction_attempt": True}
            report["steps"]["install_locked_dependencies"] = {
                "reused_from_same_clean_reproduction_attempt": True,
                "evidence": "clean-windows-reproduction-preflight-env-discovery/report.json",
            }
        else:
            report["steps"]["create_venv"] = run(
                [sys.executable, "-m", "venv", str(venv)], cwd=runtime, timeout=180,
            )
            report["steps"]["install_locked_dependencies"] = run(
                [str(python), "-m", "pip", "install", "-r", "requirements-lock.txt"],
                cwd=runtime, timeout=3600,
            )
        report["steps"]["pip_check"] = run(
            [str(python), "-m", "pip", "check"], cwd=runtime, timeout=180,
        )
        env = os.environ.copy()
        env["EDUMATRIX_VENV_PATH"] = str(venv)
        report["steps"]["runtime_preflight"] = run(
            [str(python), "scripts/runtime_preflight.py"], cwd=runtime, env=env, timeout=180,
        )
        report["steps"]["playwright_chromium"] = run(
            [str(python), "-m", "playwright", "install", "chromium"],
            cwd=runtime, env=env, timeout=900,
        )

        env.update({
            "EDUMATRIX_ENV": "development",
            "EDUMATRIX_RELOAD": "0",
            "EDUMATRIX_SANDBOX_MODE": "disabled",
            "EDUMATRIX_LLM_PROVIDER": "deterministic",
            "EDUMATRIX_LLM_MODEL": "deterministic",
            "EDUMATRIX_EMBEDDING_PROVIDER": "hash",
            "EDUMATRIX_USE_FAISS": "0",
            "EDUMATRIX_PORT": str(PORT),
            "EDUMATRIX_HOST": "127.0.0.1",
            "EDUMATRIX_E2E_BASE_URL": f"http://127.0.0.1:{PORT}",
            "EDUMATRIX_E2E_OUTPUT_DIR": str(output / "browser-e2e"),
            "EDUMATRIX_E2E_SANDBOX_MODE": "disabled",
        })
        log_handle = backend_log.open("w", encoding="utf-8")
        backend = subprocess.Popen(
            [str(python), "run.py"], cwd=runtime, env=env,
            stdout=log_handle, stderr=subprocess.STDOUT, text=True,
        )
        health = wait_for_health(backend)
        report["steps"]["backend_health"] = {
            "status": health.get("status"),
            "port": PORT,
            "process_started": True,
        }
        report["steps"]["browser_golden_journey"] = run(
            [str(python), "scripts/e2e_no_docker.py"], cwd=runtime, env=env, timeout=600,
        )
        e2e_report = json.loads((output / "browser-e2e" / "report.json").read_text(encoding="utf-8"))
        if e2e_report.get("result") != "passed":
            raise RuntimeError("browser golden journey did not pass")
        report["golden_journey"] = {
            "result": "passed",
            "mode": e2e_report.get("mode"),
            "checks": e2e_report.get("checks"),
            "screenshot_count": len(e2e_report.get("screenshots", [])),
        }
        terminate_process_tree(backend)
        backend = None
        log_handle.close()

        trusted_log = output / "trusted-local-backend.log"
        trusted_env = env.copy()
        trusted_env.update({
            "EDUMATRIX_SANDBOX_MODE": "trusted_local",
            "EDUMATRIX_SMOKE_BASE_URL": f"http://127.0.0.1:{PORT}",
            "EDUMATRIX_SMOKE_OUTPUT_PATH": str(output / "trusted-local-smoke.json"),
        })
        log_handle = trusted_log.open("w", encoding="utf-8")
        backend = subprocess.Popen(
            [str(python), "run.py"], cwd=runtime, env=trusted_env,
            stdout=log_handle, stderr=subprocess.STDOUT, text=True,
        )
        trusted_health = wait_for_health(backend)
        report["steps"]["trusted_local_backend_health"] = {
            "status": trusted_health.get("status"),
            "process_started": True,
        }
        report["steps"]["trusted_local_code_execution"] = run(
            [str(python), "scripts/trusted_local_smoke.py"],
            cwd=runtime, env=trusted_env, timeout=180,
        )
        trusted_report = json.loads(
            (output / "trusted-local-smoke.json").read_text(encoding="utf-8")
        )
        if trusted_report.get("result") != "passed":
            raise RuntimeError("trusted-local code execution smoke did not pass")
        report["trusted_local_code_execution"] = {
            "result": "passed",
            "status": trusted_report["checks"]["status"],
            "safe_execution": trusted_report["checks"]["safe_execution"],
            "blocked_os_import": trusted_report["checks"]["blocked_os_import"],
        }
        report["result"] = "passed"
    except Exception as exc:
        report["result"] = "failed"
        report["error"] = f"{type(exc).__name__}: {exc}"[-8000:]
        raise
    finally:
        if backend is not None:
            terminate_process_tree(backend)
        try:
            log_handle.close()
        except (NameError, OSError):
            pass
        report["finished_at"] = datetime.now(timezone.utc).isoformat()
        assemble_manifest(output, report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("run", "verify"))
    parser.add_argument("--runtime", type=Path, default=RUNTIME)
    parser.add_argument("--output", type=Path, default=EVIDENCE)
    parser.add_argument("--venv", type=Path, default=DEFAULT_VENV)
    parser.add_argument("--reuse-venv", action="store_true")
    args = parser.parse_args()
    result = reproduce(
        args.runtime.resolve(), args.output.resolve(), args.venv.resolve(), reuse_venv=args.reuse_venv,
    ) if args.command == "run" else verify(args.output.resolve())
    print(json.dumps({
        "result": result["result"],
        "output": str(args.output.resolve()),
        "independent_third_party_machine": result["independent_third_party_machine"],
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
