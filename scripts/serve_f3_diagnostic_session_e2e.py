"""Run the F3-T04 browser fixture on an isolated database and port."""

from __future__ import annotations

import os
import shutil
import sys
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
OUTPUT_DIR = ROOT / "outputs" / "原系统融合重构执行" / "evidence" / "f3_t04_diagnostic_session"
DB_PATH = OUTPUT_DIR / "f3_t04_runtime.db"
PORT = int(os.getenv("EDUMATRIX_F3_T04_PORT", "8895"))


def prepare_output() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for item in OUTPUT_DIR.iterdir():
        if item.is_file() or item.is_symlink():
            item.unlink()
        elif item.is_dir():
            shutil.rmtree(item)


def main() -> None:
    prepare_output()
    os.environ.update({
        "EDUMATRIX_DB_PATH": str(DB_PATH),
        "EDUMATRIX_AUTH_SECRET_KEY": "f3-t04-isolated-secret",
        "EDUMATRIX_LLM_PROVIDER": "deterministic",
        "EDUMATRIX_LLM_MODEL": "deterministic",
        "EDUMATRIX_LLM_API_KEY": "",
        "EDUMATRIX_LLM_ENDPOINT": "",
        "EDUMATRIX_EMBEDDING_PROVIDER": "hash",
        "EDUMATRIX_RELOAD": "0",
        "EDUMATRIX_HOST": "127.0.0.1",
        "EDUMATRIX_PORT": str(PORT),
        "PYTHON_DOTENV_DISABLED": "1",
        "PYTHONUNBUFFERED": "1",
        "EDUMATRIX_SANDBOX_MODE": "disabled",
    })

    with (OUTPUT_DIR / "backend.log").open("w", encoding="utf-8") as log:
        with redirect_stdout(log), redirect_stderr(log):
            from app.competition_demo_seed import seed_competition_demo
            from app.database import SessionLocal, init_db

            init_db()
            session = SessionLocal()
            try:
                seed_competition_demo(session)
            finally:
                session.close()

            import uvicorn

            uvicorn.run(
                "app.main:app",
                host="127.0.0.1",
                port=PORT,
                reload=False,
                log_config=None,
                access_log=False,
                use_colors=False,
            )


if __name__ == "__main__":
    main()
