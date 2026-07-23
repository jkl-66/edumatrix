"""Fail-fast checks for the one-click launcher.

The launcher invokes this script with the project .venv interpreter.  The
check prevents a system-Python backend from starting without required runtime
packages.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EXPECTED_PREFIX = (ROOT / ".venv").resolve()


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
            module = __import__(module_name)
            version = getattr(module, "__version__", "installed")
            print(f"  {label:<12}: {version}")
        except Exception as exc:
            print(f"[ERROR] Missing or broken dependency {label}: {exc}")
            return 1

    if os.getenv("EDUMATRIX_RELOAD") not in {None, "", "0"}:
        print("[WARN] EDUMATRIX_RELOAD is enabled; one-click mode expects reload disabled.")

    print("  Runtime preflight: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
