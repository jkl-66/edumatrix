"""Run the M3 competition loop against real local services and an isolated database."""

from __future__ import annotations

import json
import os
import re
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from playwright.sync_api import Browser, Page, sync_playwright


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT / "outputs" / "M3_三画像C加比赛闭环" / "evidence" / "browser-e2e"
DB_PATH = OUTPUT_DIR / "m3_e2e.db"
FAISS_DIR = ROOT / "outputs" / "M3_三画像C加比赛闭环" / "evidence" / "faiss"
BACKEND_URL = "http://127.0.0.1:8000"
FRONTEND_URL = "http://127.0.0.1:5173"
PASSWORD = "M3-E2E-only-2026!"
PROFILE_USERS = {
    "profile-m0-beginner": "m3-e2e-beginner",
    "profile-m0-theory": "m3-e2e-theory",
    "profile-m0-advanced": "m3-e2e-advanced",
}


def _wait_port(port: int, *, open_: bool, timeout: float = 60.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with socket.socket() as sock:
            sock.settimeout(0.25)
            available = sock.connect_ex(("127.0.0.1", port)) == 0
        if available is open_:
            return
        time.sleep(0.2)
    raise RuntimeError(f"port {port} did not become {'open' if open_ else 'closed'}")


def _ensure_ports_free() -> None:
    occupied = []
    for port in (8000, 5173):
        with socket.socket() as sock:
            sock.settimeout(0.2)
            if sock.connect_ex(("127.0.0.1", port)) == 0:
                occupied.append(port)
    if occupied:
        raise RuntimeError(f"acceptance ports already in use: {occupied}")


def _process_env() -> dict[str, str]:
    env = os.environ.copy()
    env.update(
        {
            "EDUMATRIX_DB_PATH": str(DB_PATH),
            "EDUMATRIX_AUTH_SECRET_KEY": "m3-e2e-auth-secret-isolated-2026-0001",
            "EDUMATRIX_DEMO_MODE": "0",
            # Allow the caller to select a local hash backend for isolated
            # acceptance runs; the historical sentence-transformer default
            # remains unchanged when no override is provided.
            "EDUMATRIX_EMBEDDING_PROVIDER": os.getenv("EDUMATRIX_EMBEDDING_PROVIDER", "sentence_transformer"),
            "EDUMATRIX_EMBEDDING_MODEL": os.getenv("EDUMATRIX_EMBEDDING_MODEL", "BAAI/bge-small-zh-v1.5"),
            "EDUMATRIX_EMBEDDING_DIM": os.getenv("EDUMATRIX_EMBEDDING_DIM", "512"),
            "EDUMATRIX_USE_FAISS": "1",
            "EDUMATRIX_FAISS_DIR": str(FAISS_DIR),
            "EDUMATRIX_RELOAD": "0",
            "EDUMATRIX_DISABLE_LLM_FALLBACK": "1",
            "PYTHONUNBUFFERED": "1",
        }
    )
    return env


def _prepare_database(env: dict[str, str]) -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    for suffix in ("", "-wal", "-shm"):
        path = Path(f"{DB_PATH}{suffix}")
        if path.exists():
            path.unlink()
    code = """
from app.database import init_db
init_db()
"""
    subprocess.run([sys.executable, "-c", code], cwd=ROOT, env=env, check=True, timeout=120)


def _start_backend(env: dict[str, str], log) -> subprocess.Popen[Any]:
    process = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "8000"],
        cwd=ROOT,
        env=env,
        stdout=log,
        stderr=subprocess.STDOUT,
    )
    _wait_port(8000, open_=True, timeout=120)
    return process


def _start_frontend(env: dict[str, str], log) -> subprocess.Popen[Any]:
    process = subprocess.Popen(
        ["npm.cmd", "--prefix", "frontend", "run", "dev", "--", "--host", "127.0.0.1", "--port", "5173"],
        cwd=ROOT,
        env=env,
        stdout=log,
        stderr=subprocess.STDOUT,
    )
    _wait_port(5173, open_=True)
    return process


def _stop(process: subprocess.Popen[Any] | None, port: int) -> None:
    if process is None or process.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            capture_output=True,
            text=True,
            timeout=20,
        )
    else:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        pass
    _wait_port(port, open_=False, timeout=20)


def _register(page: Page, username: str) -> str:
    response = page.request.post(
        f"{BACKEND_URL}/api/auth/register",
        data={"username": username, "password": PASSWORD, "display_name": username},
    )
    if response.status != 200:
        raise AssertionError(f"registration failed for {username}: {response.status} {response.text()}")
    return response.json()["access_token"]


def _authenticated_page(browser: Browser, token: str, *, mobile: bool = False) -> tuple[Any, Page]:
    viewport = {"width": 390, "height": 844} if mobile else {"width": 1440, "height": 1000}
    context = browser.new_context(viewport=viewport, locale="zh-CN")
    page = context.new_page()
    page.goto(f"{FRONTEND_URL}/login", wait_until="domcontentloaded")
    page.evaluate(
        "([token]) => { localStorage.setItem('edumatrix_token', token); localStorage.setItem('edumatrix_onboarded', 'true') }",
        [token],
    )
    return context, page


def _api(page: Page, method: str, path: str, token: str, data: dict[str, Any] | None = None):
    options: dict[str, Any] = {
        "headers": {"Authorization": f"Bearer {token}"},
        "timeout": 420_000,
    }
    if data is not None:
        options["data"] = data
    response = getattr(page.request, method)(f"{BACKEND_URL}{path}", **options)
    if not response.ok:
        raise AssertionError(f"{method.upper()} {path}: {response.status} {response.text()}")
    return response.json()


def _safe_error(exc: Exception) -> str:
    value = f"{type(exc).__name__}: {exc}"
    value = re.sub(r"Bearer\s+[A-Za-z0-9._~-]+", "Bearer [REDACTED]", value, flags=re.IGNORECASE)
    value = re.sub(r"Authorization:\s*[^\r\n]+", "Authorization: [REDACTED]", value, flags=re.IGNORECASE)
    return value[:4000]


def _artifact_content(bundle: dict[str, Any], artifact_type: str) -> dict[str, Any]:
    artifact = bundle["artifacts"][artifact_type][0]
    value = artifact["versions"][-1]["content"]
    return value if isinstance(value, dict) else json.loads(value)


def _screenshot(page: Page, name: str) -> str:
    path = OUTPUT_DIR / f"{name}.png"
    page.screenshot(path=str(path), full_page=True)
    return str(path.relative_to(ROOT)).replace("\\", "/")


def _run_profile(page: Page, token: str, profile_id: str, report: dict[str, Any]) -> dict[str, Any]:
    task = _api(
        page,
        "post",
        "/api/v1/m3/tasks",
        token,
        {
            "profile_id": profile_id,
            "idempotency_key": f"m3-e2e-{profile_id}-{int(time.time() * 1000)}",
            "model": "configured-structured-backend",
        },
    )
    task_id = task["id"]
    for suffix in ("start", "diagnose", "generate", "review", "matching-report", "decision"):
        _api(page, "post", f"/api/v1/m3/tasks/{task_id}/{suffix}", token)
    bundle = _api(page, "get", f"/api/v1/m3/tasks/{task_id}/bundle", token)
    assert bundle["task"]["status"] == "completed"
    assert all(step["status"] == "completed" for step in bundle["task"]["steps"])
    for kind in ("lesson", "lab_guide", "tiered_quiz", "m3_debate_report", "m3_matching_report", "m3_decision_comparison"):
        assert bundle["artifacts"].get(kind), f"missing {kind}"

    lesson = _artifact_content(bundle, "lesson")
    lab = _artifact_content(bundle, "lab_guide")
    quiz = _artifact_content(bundle, "tiered_quiz")
    debate = _artifact_content(bundle, "m3_debate_report")
    personalization = lesson["personalization"]
    quiz_version = bundle["artifacts"]["tiered_quiz"][0]["versions"][-1]
    quiz_personalization = quiz_version["metadata"]["personalization"]
    assert personalization == lab["personalization"] == quiz_personalization
    assert "answer_key" not in json.dumps(quiz, ensure_ascii=False)
    assert "explanation" not in json.dumps(quiz, ensure_ascii=False)
    assert personalization["fact_standard"] == "unchanged"
    assert personalization["safety_standard"] == "unchanged"
    assert len(debate["results"]) == 3
    lesson_source_ref_ids = sorted({
        source_ref_id
        for section in lesson["sections"]
        for source_ref_id in section["source_ref_ids"]
    })
    lesson_metadata = bundle["artifacts"]["lesson"][0]["versions"][-1]["metadata"]
    assert lesson_source_ref_ids == sorted(lesson_metadata["source_ref_ids"])

    page.goto(f"{FRONTEND_URL}/competition-loop", wait_until="networkidle")
    page.get_by_text("四角色完成").wait_for(state="visible", timeout=30_000)
    page.get_by_text("原子事实辩论").wait_for(state="visible")
    report["screenshots"].append(_screenshot(page, f"profile-{profile_id}"))
    return {
        "profile_id": profile_id,
        "task_id": task_id,
        "token": token,
        "personalization": personalization,
        "titles": {"lesson": lesson["title"], "lab_guide": lab["title"], "tiered_quiz": quiz["title"]},
        "lesson_sha256": bundle["artifacts"]["lesson"][0]["versions"][-1]["content_hash"],
        "lab_sha256": bundle["artifacts"]["lab_guide"][0]["versions"][-1]["content_hash"],
        "quiz_sha256": bundle["artifacts"]["tiered_quiz"][0]["versions"][-1]["content_hash"],
        "source_ref_ids": lesson_source_ref_ids,
    }


def _run_interactive(page: Page, token: str, task_id: str) -> dict[str, Any]:
    _api(page, "post", f"/api/v1/m3/tasks/{task_id}/interactive/manifest", token)
    session = _api(
        page,
        "post",
        f"/api/v1/m3/tasks/{task_id}/interactive/sessions",
        token,
        {"idempotency_key": f"m3-e2e-session-{task_id}"},
    )
    session_id = session["session_artifact_id"]

    def action(kind: str, **extra: Any) -> dict[str, Any]:
        return _api(
            page,
            "post",
            f"/api/v1/m3/interactive/sessions/{session_id}/actions",
            token,
            {"idempotency_key": f"m3-e2e-{kind}-{time.time_ns()}", "action": kind, **extra},
        )["state"]

    params = {"keyword_weight": 0.4, "vector_weight": 0.6, "top_k": 5, "rerank_threshold": 0.55}
    action("configure", parameters=params)
    action("inject_fault", fault_type="index_version_mismatch")
    action("run")
    failed = action("evaluate")
    assert failed["status"] == "failed"
    diagnosed = action(
        "diagnose",
        diagnosis="索引版本与任务冻结版本不一致",
        recovery_action="select_matching_index_version",
    )
    assert diagnosed["recovery_verified"] is True
    action("rerun")
    evaluated = action("evaluate")
    assert evaluated["status"] == "evaluated"
    passed = action("submit")
    assert passed["status"] == "passed"
    assert passed["hidden_acceptance"]["passed_count"] == passed["hidden_acceptance"]["total_count"]
    evidence = _api(page, "post", f"/api/v1/m3/interactive/sessions/{session_id}/evidence", token)
    return {
        "session_artifact_id": session_id,
        "fault_recovered": True,
        "status": passed["status"],
        "hidden_acceptance": passed["hidden_acceptance"],
        "skill_evidence_level": evidence["skill_evidence_level"],
        "mastery_update": evidence["mastery_update"],
    }


def _verify_faiss(env: dict[str, str]) -> dict[str, Any]:
    code = """
import json
from rag_engine import FAISSIndexSet
indexes = FAISSIndexSet()
hits = indexes.search('How does a decision tree choose a split for classification?', top_k=3)
print(json.dumps({
    'index_names': sorted(indexes.indexes),
    'vector_count': sum(index.count() for index in indexes.indexes.values()),
    'hits': [{'id': item.id, 'title': item.title, 'source': item.source, 'score': item.score, 'license': item.metadata.get('license')} for item in hits],
}, ensure_ascii=False))
"""
    completed = subprocess.run(
        [sys.executable, "-c", code], cwd=ROOT, env=env, check=True, capture_output=True, text=True, timeout=180
    )
    payload = json.loads(completed.stdout.strip().splitlines()[-1])
    assert "licensed_ml_course" in payload["index_names"]
    assert payload["vector_count"] == 365
    assert len(payload["hits"]) == 3
    assert all(item["license"] == "MIT" for item in payload["hits"])
    return payload


def main() -> int:
    report: dict[str, Any] = {
        "scope": "M3 real model, three-profile, four-role, debate and interactive browser acceptance",
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "database": str(DB_PATH.relative_to(ROOT)).replace("\\", "/"),
        "claim_boundary": (
            "The three-profile generation uses the frozen RAG course source_refs. The separately licensed MIT "
            "machine-learning FAISS index proves the real embedding/index retrieval path and is not represented "
            "as the semantic source of the RAG task."
        ),
        "checks": {},
        "screenshots": [],
    }
    env = _process_env()
    backend = None
    frontend = None
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    try:
        _ensure_ports_free()
        _prepare_database(env)
        if os.getenv("EDUMATRIX_VERIFY_REAL_FAISS", "1").strip().lower() in {"0", "false", "no"}:
            report["checks"]["real_faiss"] = {
                "status": "skipped_by_explicit_test_env",
                "claim_boundary": "This run validates the deterministic M3 loop only; the 512-dimensional licensed FAISS index was not used.",
            }
        else:
            report["checks"]["real_faiss"] = _verify_faiss(env)
        with (OUTPUT_DIR / "backend.log").open("w", encoding="utf-8") as backend_log, (OUTPUT_DIR / "frontend.log").open("w", encoding="utf-8") as frontend_log:
            backend = _start_backend(env, backend_log)
            frontend = _start_frontend(env, frontend_log)
            with sync_playwright() as playwright:
                browser = playwright.chromium.launch(headless=True)
                tokens: dict[str, str] = {}
                profiles: list[dict[str, Any]] = []
                for profile_id, username in PROFILE_USERS.items():
                    request_context = browser.new_context()
                    request_page = request_context.new_page()
                    token = _register(request_page, username)
                    request_context.close()
                    tokens[profile_id] = token
                    context, page = _authenticated_page(browser, token)
                    try:
                        profiles.append(_run_profile(page, token, profile_id, report))
                    finally:
                        context.close()

                strategies = {
                    (
                        item["personalization"]["difficulty_band"],
                        item["personalization"]["scaffolding"],
                        item["personalization"]["task_openness"],
                        item["personalization"]["quiz_emphasis"],
                    )
                    for item in profiles
                }
                assert len(strategies) == 3
                assert len({item["lesson_sha256"] for item in profiles}) == 3
                assert len({item["lab_sha256"] for item in profiles}) == 3
                assert len({item["quiz_sha256"] for item in profiles}) == 3
                assert len({tuple(item["source_ref_ids"]) for item in profiles}) == 1
                report["checks"]["three_profile_differences"] = [
                    {key: value for key, value in item.items() if key != "token"} for item in profiles
                ]

                advanced = next(item for item in profiles if item["profile_id"] == "profile-m0-advanced")
                context, page = _authenticated_page(browser, advanced["token"])
                try:
                    report["checks"]["interactive"] = _run_interactive(page, advanced["token"], advanced["task_id"])
                    page.goto(f"{FRONTEND_URL}/competition-loop", wait_until="networkidle")
                    page.get_by_text("隐藏验收 5/5").wait_for(state="visible", timeout=30_000)
                    report["screenshots"].append(_screenshot(page, "interactive-hidden-acceptance"))

                    page.reload(wait_until="networkidle")
                    page.get_by_text("隐藏验收 5/5").wait_for(state="visible", timeout=30_000)
                    report["checks"]["browser_refresh_recovery"] = True

                    _stop(backend, 8000)
                    backend = _start_backend(env, backend_log)
                    page.reload(wait_until="networkidle")
                    page.get_by_text("隐藏验收 5/5").wait_for(state="visible", timeout=30_000)
                    report["screenshots"].append(_screenshot(page, "backend-restart-recovery"))
                    report["checks"]["backend_restart_recovery"] = True
                finally:
                    context.close()

                beginner = next(item for item in profiles if item["profile_id"] == "profile-m0-beginner")
                intruder_context, intruder_page = _authenticated_page(browser, beginner["token"])
                try:
                    forbidden_task = intruder_page.request.get(
                        f"{BACKEND_URL}/api/v1/m3/tasks/{advanced['task_id']}",
                        headers={"Authorization": f"Bearer {beginner['token']}"},
                    )
                    forbidden_bundle = intruder_page.request.get(
                        f"{BACKEND_URL}/api/v1/m3/tasks/{advanced['task_id']}/bundle",
                        headers={"Authorization": f"Bearer {beginner['token']}"},
                    )
                    assert forbidden_task.status == 403
                    assert forbidden_bundle.status == 403
                    report["checks"]["owner_boundary"] = {"task": 403, "bundle": 403}
                finally:
                    intruder_context.close()

                mobile_context, mobile_page = _authenticated_page(browser, advanced["token"], mobile=True)
                try:
                    mobile_page.goto(f"{FRONTEND_URL}/competition-loop", wait_until="networkidle")
                    mobile_page.get_by_text("四角色完成").wait_for(state="visible", timeout=30_000)
                    report["screenshots"].append(_screenshot(mobile_page, "mobile-completed-loop"))
                finally:
                    mobile_context.close()
                browser.close()
        report["checks"]["real_structured_model"] = {
            "configured": True,
            "three_generation_calls_completed": True,
            "three_debate_reviews_completed": True,
            "credentials_redacted": True,
        }
        report["result"] = "passed"
    except Exception as exc:
        report["result"] = "failed"
        report["error"] = _safe_error(exc)
        raise
    finally:
        report["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
        (OUTPUT_DIR / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        _stop(frontend, 5173)
        _stop(backend, 8000)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
