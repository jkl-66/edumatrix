"""Fail-fast checks for the one-click launcher.

The launcher invokes this script with the project .venv interpreter.  The
check prevents a system-Python backend from starting without required runtime
packages.
"""

from __future__ import annotations

import os
import sys
from importlib import import_module
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EXPECTED_PREFIX = Path(os.getenv("EDUMATRIX_VENV_PATH", str(ROOT / ".venv"))).resolve()
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def check_optional_media() -> None:
    for label, module_name in (
        ("whisper.cpp", "app.offline_speech"),
        ("FFmpeg", "app.video_rendering"),
    ):
        try:
            runtime = import_module(module_name).runtime_status()
            if runtime.get("available"):
                version = runtime.get("version") or runtime.get("ffmpeg_version") or "installed"
                print(f"  {label:<12}: {version}")
            else:
                print(f"[WARN] Optional {label} runtime unavailable: {runtime.get('failure_code', 'unknown')}")
        except Exception as exc:
            print(f"[WARN] Optional {label} runtime check failed: {exc}")


def main() -> int:
    executable = Path(sys.executable).resolve()
    print(f"  Python executable: {executable}")
    print(f"  Project root:      {ROOT}")

    if EXPECTED_PREFIX not in executable.parents:
        print("[ERROR] Launcher is not using the project .venv interpreter.")
        print(f"        Expected under: {EXPECTED_PREFIX}")
        return 1

    required = {
        "fastapi": "fastapi",
        "uvicorn": "uvicorn",
        "matplotlib": "matplotlib",
        "pandas": "pandas",
        "sklearn": "sklearn",
    }
    for label, module_name in required.items():
        try:
            module = import_module(module_name)
            version = getattr(module, "__version__", "installed")
            print(f"  {label:<12}: {version}")
        except Exception as exc:
            print(f"[ERROR] Missing or broken dependency {label}: {exc}")
            return 1

    # Speech and automatic video rendering are optional capabilities; their
    # absence must not prevent the learning application from starting.
    check_optional_media()

    if os.getenv("EDUMATRIX_RELOAD") not in {None, "", "0"}:
        print("[WARN] EDUMATRIX_RELOAD is enabled; one-click mode expects reload disabled.")

    print("  Runtime preflight: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
