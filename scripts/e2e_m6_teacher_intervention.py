"""Verify the M6 evidence-led teacher intervention journey."""

from __future__ import annotations

import hashlib, json, os, socket, sqlite3, subprocess, sys, time
from pathlib import Path
from typing import Any
from playwright.sync_api import Page, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0, str(ROOT))
OUTPUT = ROOT / "outputs" / "M6_教学治理与企业培训" / "evidence" / "teacher-intervention-e2e-20260803"
DB_PATH = ROOT / "outputs" / "_m6_teacher_intervention_e2e_runtime.db"
EVIDENCE_DB = OUTPUT / "m6_teacher_intervention_evidence.db"
BASE_URL = "http://127.0.0.1:8773"
ADMIN_USERNAME = "m6_teacher_admin"
PASSWORD = "M6-teacher-e2e-2026!"

def wait_port(open_: bool, timeout: float = 45.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with socket.socket() as sock:
            sock.settimeout(.25); available = sock.connect_ex(("127.0.0.1", 8773)) == 0
        if available is open_: return
        time.sleep(.2)
    raise RuntimeError("port 8773 state timeout")

def stop(process):
    if process is None or process.poll() is not None: return
    subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], capture_output=True, text=True, timeout=15)
    try: process.wait(timeout=5)
    except subprocess.TimeoutExpired: pass
    wait_port(False, 15)

def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""): value.update(block)
    return value.hexdigest()

def shot(page: Page, name: str) -> str:
    path = OUTPUT / f"{name}.png"; page.screenshot(path=str(path), full_page=True); return path.name

def manifest():
    files = [{"file": p.name, "bytes": p.stat().st_size, "sha256": digest(p)} for p in sorted(OUTPUT.iterdir()) if p.is_file() and p.name != "manifest.json" and not p.name.endswith(("-wal", "-shm"))]
    (OUTPUT / "manifest.json").write_text(json.dumps({"schema_version":"m6.teacher-intervention-e2e-manifest.v1","files":files}, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")

def login(page: Page, username: str, password: str):
    response = page.request.post(f"{BASE_URL}/api/auth/login", form={"username":username,"password":password})
    assert response.ok, response.text(); return response.json()

def main() -> int:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    for p in OUTPUT.iterdir():
        if p.is_file(): p.unlink()
    for suffix in ("", "-wal", "-shm"):
        p = Path(f"{DB_PATH}{suffix}")
        if p.exists(): p.unlink()
    env = os.environ.copy(); env.update({
        "EDUMATRIX_DB_PATH":str(DB_PATH), "EDUMATRIX_AUTH_SECRET_KEY":"m6-teacher-isolated-secret-2026",
        "EDUMATRIX_LLM_PROVIDER":"deterministic", "EDUMATRIX_LLM_MODEL":"deterministic",
        "EDUMATRIX_LLM_API_KEY":"", "EDUMATRIX_LLM_ENDPOINT":"", "EDUMATRIX_RELOAD":"0",
        "EDUMATRIX_HOST":"127.0.0.1", "EDUMATRIX_PORT":"8773", "PYTHONUNBUFFERED":"1",
    }); os.environ.update(env)
    from app.auth import get_password_hash
    from app.database import DBUser, SessionLocal, init_db
    init_db()
    with SessionLocal() as session:
        session.add(DBUser(username=ADMIN_USERNAME, hashed_password=get_password_hash(PASSWORD), role="admin", display_name="教学治理管理员")); session.commit()
    report: dict[str, Any] = {"scope":"profile risk to teacher plan, learner evidence, teacher confirmation, path completion, mobile UI", "started_at":time.strftime("%Y-%m-%dT%H:%M:%S%z"), "checks":{}, "screenshots":[]}
    backend = None
    try:
        with (OUTPUT / "backend.log").open("w", encoding="utf-8") as log:
            backend = subprocess.Popen([sys.executable,"run.py"], cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT); wait_port(True)
            with sync_playwright() as pw:
                browser = pw.chromium.launch(headless=True); context = browser.new_context(viewport={"width":1440,"height":1000}, locale="zh-CN"); page = context.new_page()
                try:
                    admin = login(page, ADMIN_USERNAME, PASSWORD); headers={"Authorization":f"Bearer {admin['access_token']}"}
                    bootstrap = page.request.post(f"{BASE_URL}/api/v1/m6/demo/bootstrap", headers=headers).json()
                    page.goto(f"{BASE_URL}/login", wait_until="networkidle")
                    page.evaluate("""([t,u])=>{localStorage.setItem('edumatrix_token',t);localStorage.setItem('edumatrix_role','admin');localStorage.setItem('edumatrix_username',u);localStorage.setItem('edumatrix_display_name','教学治理管理员');localStorage.setItem('edumatrix_onboarded','true')}""", [admin["access_token"],ADMIN_USERNAME])
                    page.goto(f"{BASE_URL}/teacher/interventions", wait_until="networkidle")
                    page.get_by_text("混合检索与重排", exact=False).first.wait_for(state="visible", timeout=20_000)
                    report["screenshots"].append(shot(page,"01-profile-risk"))
                    page.get_by_role("button", name="发布干预任务").click()
                    page.get_by_text("已进入正式路径", exact=True).wait_for(state="visible", timeout=20_000)
                    page.get_by_text("等待学员提交", exact=True).wait_for(state="visible")
                    report["screenshots"].append(shot(page,"02-versioned-intervention-published"))
                    overview = page.request.get(f"{BASE_URL}/api/v1/m6/teacher/interventions?course_id=course-rag-engineering-m0", headers=headers).json()
                    intervention = overview["interventions"][0]
                    learner = login(page, f"m6_demo_{ADMIN_USERNAME}"[:64], "EduMatrix-M6-Demo")
                    evidence = page.request.post(f"{BASE_URL}/api/v1/m6/teacher/interventions/{intervention['path_id']}/learner-evidence", headers={"Authorization":f"Bearer {learner['access_token']}"}, data={"active_seconds":1200})
                    assert evidence.ok, evidence.text()
                    page.reload(wait_until="networkidle")
                    page.get_by_text("已提交学习证据", exact=True).wait_for(state="visible", timeout=20_000)
                    page.get_by_role("button", name="确认干预完成").wait_for(state="visible")
                    report["screenshots"].append(shot(page,"03-learner-evidence-awaits-review"))
                    page.get_by_role("button", name="确认干预完成").click()
                    page.get_by_text("教师已确认", exact=True).wait_for(state="visible", timeout=20_000)
                    page.get_by_text("已完成", exact=True).wait_for(state="visible")
                    report["screenshots"].append(shot(page,"04-teacher-confirmed-effect"))
                    final = page.request.get(f"{BASE_URL}/api/v1/m6/teacher/interventions?course_id=course-rag-engineering-m0", headers=headers).json()["interventions"][0]
                    assert final["node_status"] == "completed" and final["teacher_confirmed"] is True
                    report["checks"]["formal_chain"]={"learner_public_id":bootstrap["learner_public_id"],"plan_id":final["plan_id"],"path_id":final["path_id"],"learner_event_id":final["learner_event_id"],"node_status":final["node_status"],"teacher_confirmed":final["teacher_confirmed"]}
                    page.set_viewport_size({"width":390,"height":844}); page.reload(wait_until="networkidle"); page.get_by_text("教师已确认", exact=True).wait_for(state="visible", timeout=20_000)
                    report["screenshots"].append(shot(page,"05-mobile-completed")); report["checks"]["mobile_viewport"]={"width":390,"height":844,"completed_visible":True}; report["result"]="passed"
                finally: context.close(); browser.close()
    except Exception as exc:
        report["result"]="failed"; report["error"]=f"{type(exc).__name__}: {exc}"; raise
    finally:
        report["finished_at"]=time.strftime("%Y-%m-%dT%H:%M:%S%z"); stop(backend)
        if DB_PATH.exists():
            with sqlite3.connect(DB_PATH) as source, sqlite3.connect(EVIDENCE_DB) as dest:
                source.backup(dest); report["checks"]["sqlite_integrity"]=dest.execute("PRAGMA integrity_check").fetchone()[0]
        (OUTPUT/"report.json").write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8"); manifest()
    print(json.dumps(report,ensure_ascii=False,indent=2)); return 0

if __name__ == "__main__": raise SystemExit(main())
