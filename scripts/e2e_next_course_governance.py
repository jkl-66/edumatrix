"""Verify class, group, task, and withdrawal governance in Chromium."""

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
from typing import Any

from playwright.sync_api import Page, sync_playwright


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = Path(os.environ.get("EDUMATRIX_E2E_OUTPUT_DIR", ROOT / "outputs" / "NEXT_完全体主动开发" / "evidence" / "NC-GOV-01" / "browser-e2e"))
DB_PATH = Path(os.environ.get("EDUMATRIX_E2E_DB_PATH", ROOT / "outputs" / "_next_course_governance_e2e.db"))
EVIDENCE_DB = OUTPUT / "course_governance_evidence.db"
PORT = 8793
BASE_URL = f"http://127.0.0.1:{PORT}"
PASSWORD = "Next-course-governance-2026!"


def wait_port(open_: bool, timeout: float = 60.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with socket.socket() as sock:
            sock.settimeout(0.25); available = sock.connect_ex(("127.0.0.1", PORT)) == 0
        if available is open_: return
        time.sleep(0.2)
    raise RuntimeError(f"port {PORT} state timeout")


def stop(process: subprocess.Popen[Any] | None) -> None:
    if process is None or process.poll() is not None: return
    subprocess.run(["taskkill","/PID",str(process.pid),"/T","/F"],capture_output=True,text=True,timeout=15)
    try: process.wait(timeout=5)
    except subprocess.TimeoutExpired: pass
    wait_port(False,15)


def shot(page: Page, name: str) -> str:
    path=OUTPUT/f"{name}.png"; page.screenshot(path=str(path),full_page=True); return path.name


def digest(path: Path) -> str: return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    OUTPUT.mkdir(parents=True,exist_ok=True)
    for path in OUTPUT.iterdir():
        if path.is_file(): path.unlink()
    for suffix in ("","-wal","-shm"):
        path=Path(f"{DB_PATH}{suffix}")
        if path.exists(): path.unlink()
    env=os.environ.copy(); env.update({
        "EDUMATRIX_DB_PATH":str(DB_PATH),"EDUMATRIX_AUTH_SECRET_KEY":"next-course-governance-e2e-secret",
        "EDUMATRIX_LLM_PROVIDER":"deterministic","EDUMATRIX_LLM_MODEL":"deterministic","EDUMATRIX_LLM_API_KEY":"",
        "EDUMATRIX_LLM_ENDPOINT":"","EDUMATRIX_MULTIMODAL_LLM_API_KEY":"","EDUMATRIX_MULTIMODAL_LLM_ENDPOINT":"",
        "EDUMATRIX_EMBEDDING_PROVIDER":"hash","EDUMATRIX_RELOAD":"0","EDUMATRIX_SANDBOX_MODE":"disabled",
        "EDUMATRIX_HOST":"127.0.0.1","EDUMATRIX_PORT":str(PORT),"PYTHONUNBUFFERED":"1",
    })
    report:dict[str,Any]={"schema_version":"next.course-governance-e2e.v1","checks":{},"screenshots":[],"started_at":time.strftime("%Y-%m-%dT%H:%M:%S%z")}
    backend=None
    try:
        with (OUTPUT/"backend.log").open("w",encoding="utf-8") as log:
            backend=subprocess.Popen([sys.executable,"run.py"],cwd=ROOT,env=env,stdout=log,stderr=subprocess.STDOUT)
            wait_port(True)
            with sync_playwright() as playwright:
                browser=playwright.chromium.launch(headless=True)
                context=browser.new_context(viewport={"width":1440,"height":1000},locale="zh-CN")
                page=context.new_page()
                try:
                    suffix=str(int(time.time())); teacher_name=f"gov_teacher_{suffix}"; learner_name=f"gov_learner_{suffix}"; outsider_name=f"gov_outsider_{suffix}"
                    identities={}
                    for username,display in ((teacher_name,"治理教师"),(learner_name,"学员 林然"),(outsider_name,"外部用户")):
                        response=page.request.post(f"{BASE_URL}/api/auth/register",data={"username":username,"password":PASSWORD,"display_name":display})
                        assert response.ok; identities[username]=response.json()["user_id"]
                    course_id=f"course-governance-{suffix}"
                    with sqlite3.connect(DB_PATH) as db:
                        db.execute("UPDATE users SET role='teacher' WHERE public_id=?",(identities[teacher_name],))
                        db.execute("INSERT INTO courses(id,version,title,subject,visibility,status,owner_public_id,manifest_version,manifest_data,created_at) VALUES(?,?,?,?,?,?,?,?,?,CURRENT_TIMESTAMP)",
                                   (course_id,"2026.1","AI 工程治理实训","人工智能","private","published",identities[teacher_name],"gov-e2e-1","{}"))
                        db.execute("INSERT INTO course_memberships(id,course_id,user_public_id,role,status,created_at,updated_at) VALUES(?,?,?,?,?,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)",
                                   (f"cm-teacher-{suffix}",course_id,identities[teacher_name],"teacher","active"))
                        db.execute("INSERT INTO course_memberships(id,course_id,user_public_id,role,status,created_at,updated_at) VALUES(?,?,?,?,?,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)",
                                   (f"cm-learner-{suffix}",course_id,identities[learner_name],"student","active")); db.commit()
                    tokens={}
                    for username in identities:
                        login=page.request.post(f"{BASE_URL}/api/auth/login",form={"username":username,"password":PASSWORD}); assert login.ok; tokens[username]=login.json()["access_token"]
                    teacher_h={"Authorization":f"Bearer {tokens[teacher_name]}"}; learner_h={"Authorization":f"Bearer {tokens[learner_name]}"}; outsider_h={"Authorization":f"Bearer {tokens[outsider_name]}"}
                    page.goto(f"{BASE_URL}/login",wait_until="domcontentloaded")
                    page.evaluate("""([token,username])=>{localStorage.setItem('edumatrix_token',token);localStorage.setItem('edumatrix_role','teacher');localStorage.setItem('edumatrix_username',username);localStorage.setItem('edumatrix_student_id',username);localStorage.setItem('edumatrix_display_name','治理教师');localStorage.setItem('edumatrix_onboarded','true')}""",[tokens[teacher_name],teacher_name])
                    page.goto(f"{BASE_URL}/course-governance",wait_until="domcontentloaded",timeout=30000)
                    workspace=page.get_by_test_id("course-governance-workspace"); workspace.wait_for(state="visible",timeout=30000)
                    page.get_by_label("管理课程").select_option(course_id)
                    page.get_by_label("班级名称").fill("2026 秋季 AI 实训班")
                    page.get_by_label("学期").fill("2026 秋")
                    page.get_by_role("button",name="新建班级").click()
                    class_card=page.get_by_test_id("teaching-class").filter(has_text="2026 秋季 AI 实训班"); class_card.wait_for(state="visible",timeout=30000)
                    panel=page.get_by_test_id("class-management-panel")
                    panel.get_by_label("分组名称").fill("项目 A 组"); panel.get_by_label("分组说明").fill("检索实验协作组")
                    panel.get_by_title("添加分组").wait_for(state="visible"); assert panel.get_by_title("添加分组").is_enabled()
                    panel.get_by_title("添加分组").click(); panel.locator(".chips").get_by_text("项目 A 组",exact=True).wait_for(state="visible")
                    panel.get_by_label("候选成员").select_option(identities[learner_name]); panel.get_by_label("成员分组").select_option(label="项目 A 组")
                    panel.get_by_role("button",name="加入").click(); panel.get_by_text("学员 林然",exact=True).wait_for(state="visible")
                    panel.get_by_label("任务名称").fill("完成虚拟实验并提交结果"); panel.get_by_label("任务说明").fill("运行实验、通过隐藏验收并记录反思。")
                    panel.get_by_label("任务范围").select_option(label="项目 A 组"); panel.get_by_label("截止时间").fill("2026-09-30T12:00")
                    panel.get_by_role("button",name="保存任务草稿").click()
                    task=page.get_by_test_id("teaching-task").filter(has_text="完成虚拟实验并提交结果"); task.wait_for(state="visible")
                    task.get_by_role("button",name="发布").click(); page.get_by_test_id("teaching-task").filter(has_text="published").wait_for(state="visible")
                    report["screenshots"].append(shot(page,"01-class-group-published-task"))

                    classes=page.request.get(f"{BASE_URL}/api/v1/course-governance/classes",headers=learner_h,params={"course_id":course_id}); assert classes.ok
                    learner_class=classes.json()["items"][0]
                    assert learner_class["can_manage"] is False and len(learner_class["members"])==1 and len(learner_class["tasks"])==1
                    class_id=learner_class["id"]
                    denied=[
                        page.request.get(f"{BASE_URL}/api/v1/course-governance/classes/{class_id}",headers=outsider_h),
                        page.request.post(f"{BASE_URL}/api/v1/course-governance/classes/{class_id}/groups",headers=learner_h,data={"name":"越权组","description":""}),
                        page.request.post(f"{BASE_URL}/api/v1/course-governance/courses/{course_id}/withdraw",headers=learner_h,data={"reason":"学生不能撤回课程版本","expected_status":"published"}),
                    ]
                    assert [item.status for item in denied]==[403,403,403]; report["checks"]["cross_role"]=[item.status for item in denied]

                    page.reload(wait_until="domcontentloaded",timeout=30000); panel=page.get_by_test_id("class-management-panel"); panel.wait_for(state="visible",timeout=30000)
                    assert "学员 林然" in panel.inner_text() and "published" in panel.inner_text(); report["checks"]["refresh_recovery"]=True
                    page.set_viewport_size({"width":390,"height":844}); page.wait_for_timeout(300)
                    geometry=page.evaluate("""()=>{const box=document.querySelector('[data-testid="course-governance-workspace"]')?.getBoundingClientRect();return{viewport:innerWidth,documentWidth:document.documentElement.scrollWidth,panel:box?{x:box.x,right:box.right,width:box.width}:null}}""")
                    assert geometry["documentWidth"]<=geometry["viewport"]+1 and geometry["panel"] and geometry["panel"]["right"]<=391
                    report["checks"]["mobile_viewport"]=geometry; report["screenshots"].append(shot(page,"02-mobile-course-governance"))
                    page.set_viewport_size({"width":1440,"height":1000})
                    page.once("dialog",lambda dialog:dialog.accept()); page.get_by_role("button",name="撤回课程").click()
                    page.get_by_text("课程已撤回，影响快照已冻结。").wait_for(state="visible",timeout=30000)
                    withdrawal=page.request.post(f"{BASE_URL}/api/v1/course-governance/courses/{course_id}/withdraw",headers=teacher_h,data={"reason":"课程版本停止教学，暂停成员与未归档任务并保留历史证据。","expected_status":"published"}); assert withdrawal.ok
                    impact=withdrawal.json()["impact_snapshot"]
                    assert impact["class_count"]==impact["class_member_count"]==impact["task_count"]==1 and impact["historical_learning_evidence_deleted"]==0
                    assert impact["learner_membership_suspended_count"]==1 and impact["manager_membership_preserved_count"]==1
                    panel=page.get_by_test_id("class-management-panel")
                    assert page.get_by_title("添加分组").is_disabled() and panel.get_by_role("button",name="保存任务草稿").is_disabled()
                    denied_after=page.request.get(f"{BASE_URL}/api/v1/course-governance/classes/{class_id}",headers=learner_h); assert denied_after.status==403
                    report["checks"]["withdrawal_impact"]=impact; report["screenshots"].append(shot(page,"03-course-withdrawn")); report["result"]="passed"
                except Exception:
                    try: report["screenshots"].append(shot(page,"error"))
                    except Exception: pass
                    raise
                finally: context.close(); browser.close()
    except Exception as exc:
        report["result"]="failed"; report["error"]=f"{type(exc).__name__}: {exc}"; raise
    finally:
        report["finished_at"]=time.strftime("%Y-%m-%dT%H:%M:%S%z"); stop(backend)
        if DB_PATH.exists():
            with sqlite3.connect(DB_PATH) as source,sqlite3.connect(EVIDENCE_DB) as target:
                source.backup(target); report["checks"]["sqlite_integrity"]=target.execute("pragma integrity_check").fetchone()[0]
        (OUTPUT/"report.json").write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
        files=[{"file":p.name,"bytes":p.stat().st_size,"sha256":digest(p)} for p in sorted(OUTPUT.iterdir()) if p.is_file() and p.name!="manifest.json" and not p.name.endswith(("-wal","-shm"))]
        (OUTPUT/"manifest.json").write_text(json.dumps({"schema_version":"next.course-governance-manifest.v1","files":files},ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(report,ensure_ascii=False,indent=2)); return 0


if __name__=="__main__": raise SystemExit(main())
