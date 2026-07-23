from pathlib import Path
import multiprocessing
import sys
from concurrent.futures import ProcessPoolExecutor


ROOT = Path(__file__).resolve().parents[1]


def _worker_executable():
    return sys.executable


def test_one_click_launcher_uses_project_venv_and_preflight():
    launcher = (ROOT / "start.bat").read_text(encoding="utf-8")
    assert "%PROJECT_ROOT%.venv\\Scripts\\python.exe" in launcher
    assert "runtime_preflight.py" in launcher
    assert "run.py" in launcher
    assert "EDUMATRIX_RELOAD=0" in launcher
    assert 'EDUMATRIX_SANDBOX_MODE=trusted_local' in launcher
    assert "Existing EduMatrix Vite service detected" in launcher
    assert "Port 5173 is occupied by a non-EduMatrix process" in launcher


def test_runtime_preflight_requires_project_venv():
    preflight = (ROOT / "scripts" / "runtime_preflight.py").read_text(encoding="utf-8")
    assert "sys.executable" in preflight
    assert "EXPECTED_PREFIX" in preflight
    assert "matplotlib" in preflight
    assert "pandas" in preflight
    assert "sklearn" in preflight


def test_code_execution_uses_backend_interpreter():
    source = (ROOT / "code_exec_api.py").read_text(encoding="utf-8")
    assert 'requested_mode == "trusted_local"' in source
    assert 'in {"production", "prod"}' in source
    assert 'requested_mode = "disabled"' in source
    assert "asyncio.create_subprocess_exec(" in source
    assert "sys.executable" in source
    assert "[sys.executable, \"-c\", exec_command]" in source
    assert '"python_executable": sys.executable' in source
    assert '"multiprocessing_executable": multiprocessing_spawn.get_executable()' in source


def test_algorithm_worker_pool_uses_backend_interpreter():
    source = (ROOT / "bkt_engine.py").read_text(encoding="utf-8")
    assert "multiprocessing.set_executable(sys.executable)" in source
    assert 'mp_context=multiprocessing.get_context("spawn")' in source


def test_windows_spawn_worker_inherits_project_interpreter():
    multiprocessing.set_executable(sys.executable)
    context = multiprocessing.get_context("spawn")
    with ProcessPoolExecutor(max_workers=1, mp_context=context) as executor:
        worker_executable = Path(executor.submit(_worker_executable).result(timeout=30)).resolve()
    assert ROOT / ".venv" in worker_executable.parents
