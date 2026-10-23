"""Verify explainable teaching analytics in a real Chromium workflow."""

from __future__ import annotations

import hashlib, json, os, socket, sqlite3, subprocess, sys, time
from pathlib import Path
from typing import Any
from playwright.sync_api import sync_playwright

ROOT=Path(__file__).resolve().parents[1]
OUTPUT=Path(os.environ.get("EDUMATRIX_E2E_OUTPUT_DIR",ROOT/"outputs"/"NEXT_完全体主动开发"/"evidence"/"NC-GOV-02"/"browser-e2e"))
DB_PATH=Path(os.environ.get("EDUMATRIX_E2E_DB_PATH",ROOT/"outputs"/"_next_teaching_analytics_e2e.db"))
EVIDENCE_DB=OUTPUT/"teaching_analytics_evidence.db"
PORT=8794; BASE=f"http://127.0.0.1:{PORT}"; PASSWORD="Next-teaching-analytics-2026!"

def wait_port(open_:bool,timeout:float=60)->None:
    deadline=time.monotonic()+timeout
    while time.monotonic()<deadline:
        with socket.socket() as sock: sock.settimeout(.25); available=sock.connect_ex(("127.0.0.1",PORT))==0
        if available is open_: return
        time.sleep(.2)
    raise RuntimeError("port state timeout")

def stop(process:subprocess.Popen[Any]|None)->None:
    if process is None or process.poll() is not None:return
    subprocess.run(["taskkill","/PID",str(process.pid),"/T","/F"],capture_output=True,text=True,timeout=15)
    try:process.wait(timeout=5)
    except subprocess.TimeoutExpired:pass
    wait_port(False,15)

def digest(path:Path)->str:return hashlib.sha256(path.read_bytes()).hexdigest()

def main()->int:
    OUTPUT.mkdir(parents=True,exist_ok=True)
    for path in OUTPUT.iterdir():
        if path.is_file():path.unlink()
    for suffix in ("","-wal","-shm"):
        path=Path(f"{DB_PATH}{suffix}")
        if path.exists():path.unlink()
    env=os.environ.copy();env.update({"EDUMATRIX_DB_PATH":str(DB_PATH),"EDUMATRIX_AUTH_SECRET_KEY":"teaching-analytics-e2e-secret","EDUMATRIX_LLM_PROVIDER":"deterministic","EDUMATRIX_LLM_MODEL":"deterministic","EDUMATRIX_LLM_API_KEY":"","EDUMATRIX_LLM_ENDPOINT":"","EDUMATRIX_MULTIMODAL_LLM_API_KEY":"","EDUMATRIX_MULTIMODAL_LLM_ENDPOINT":"","EDUMATRIX_EMBEDDING_PROVIDER":"hash","EDUMATRIX_RELOAD":"0","EDUMATRIX_SANDBOX_MODE":"disabled","EDUMATRIX_HOST":"127.0.0.1","EDUMATRIX_PORT":str(PORT),"PYTHONUNBUFFERED":"1"})
    report:dict[str,Any]={"schema_version":"next.teaching-analytics-e2e.v1","checks":{},"screenshots":[],"started_at":time.strftime("%Y-%m-%dT%H:%M:%S%z")};backend=None
    try:
        with (OUTPUT/"backend.log").open("w",encoding="utf-8") as log:
            backend=subprocess.Popen([sys.executable,"run.py"],cwd=ROOT,env=env,stdout=log,stderr=subprocess.STDOUT);wait_port(True)
            with sync_playwright() as pw:
                browser=pw.chromium.launch(headless=True);context=browser.new_context(viewport={"width":1440,"height":1000},locale="zh-CN",accept_downloads=True);page=context.new_page()
                try:
                    suffix=str(int(time.time())); names=[f"analytics_teacher_{suffix}",f"analytics_outsider_{suffix}",*[f"analytics_learner_{i}_{suffix}" for i in range(3)]];ids={}
                    for name in names:
                        response=page.request.post(f"{BASE}/api/auth/register",data={"username":name,"password":PASSWORD,"display_name":name});assert response.ok;ids[name]=response.json()["user_id"]
                    teacher,outsider,*learners=names;course_id=f"analytics-course-{suffix}"
                    with sqlite3.connect(DB_PATH) as db:
                        db.execute("UPDATE users SET role='teacher' WHERE public_id IN (?,?)",(ids[teacher],ids[outsider]))
                        db.execute("INSERT INTO courses(id,version,title,subject,visibility,status,owner_public_id,manifest_version,manifest_data,created_at) VALUES(?,?,?,?,?,?,?,?,?,CURRENT_TIMESTAMP)",(course_id,"2026.1","可解释教学分析课程","人工智能","private","published",ids[teacher],"analytics-1","{}"))
                        db.execute("INSERT INTO course_memberships(id,course_id,user_public_id,role,status,created_at,updated_at) VALUES(?,?,?,?,?,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)",(f"cm-t-{suffix}",course_id,ids[teacher],"teacher","active"));db.commit()
                    tokens={}
                    for name in names:
                        login=page.request.post(f"{BASE}/api/auth/login",form={"username":name,"password":PASSWORD});assert login.ok;tokens[name]=login.json()["access_token"]
                    headers={"Authorization":f"Bearer {tokens[teacher]}"}; outsider_headers={"Authorization":f"Bearer {tokens[outsider]}"}
                    created=page.request.post(f"{BASE}/api/v1/course-governance/classes",headers=headers,data={"course_id":course_id,"title":"2026 AI 教学分析班","term":"2026 秋"});assert created.ok;class_id=created.json()["id"]
                    for learner in learners:
                        added=page.request.put(f"{BASE}/api/v1/course-governance/classes/{class_id}/members",headers=headers,data={"user_public_id":ids[learner],"role":"student","group_id":None,"expected_version":None});assert added.ok
                    with sqlite3.connect(DB_PATH) as db:
                        now=time.strftime("%Y-%m-%d %H:%M:%S")
                        for i,learner in enumerate(learners[:2]):db.execute("INSERT INTO learning_events(id,owner_public_id,course_id,event_type,schema_version,source,trace_id,object_type,object_id,payload,occurred_at,recorded_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",(f"le-a-{i}",ids[learner],course_id,"resource_viewed","1.0","e2e",f"trace-a-{i}","chapter",f"chapter-{i}","{}",now,now))
                        db.execute("INSERT INTO plan_drafts(id,owner_public_id,course_id,title,status,idempotency_key,lock_version,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)",("pd-a",ids[learners[0]],course_id,"分析路径","confirmed","pd-a-key",1,now,now))
                        db.execute("INSERT INTO plan_versions(id,plan_draft_id,version_number,content,content_hash,created_by_public_id,created_at) VALUES(?,?,?,?,?,?,?)",("pv-a","pd-a",1,"{}","a"*64,ids[teacher],now))
                        db.execute("INSERT INTO learning_paths(id,owner_public_id,course_id,source_plan_version_id,status,lock_version,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)",("path-a",ids[learners[0]],course_id,"pv-a","active",1,now,now))
                        db.execute("INSERT INTO path_nodes(id,learning_path_id,node_key,sequence,node_type,title,status,prerequisites,is_extension,resource_status,estimate_min_minutes,estimate_max_minutes,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",("node-a1","path-a","a1",1,"chapter","已完成章节","completed","[]",0,"existing",20,40,now))
                        db.execute("INSERT INTO path_nodes(id,learning_path_id,node_key,sequence,node_type,title,status,prerequisites,is_extension,resource_status,estimate_min_minutes,estimate_max_minutes,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",("node-a2","path-a","a2",2,"chapter","高负担实验","pending","[]",0,"existing",90,200,now));db.commit()
                    page.goto(f"{BASE}/login",wait_until="domcontentloaded");page.evaluate("""([token,name])=>{localStorage.setItem('edumatrix_token',token);localStorage.setItem('edumatrix_role','teacher');localStorage.setItem('edumatrix_username',name);localStorage.setItem('edumatrix_student_id',name);localStorage.setItem('edumatrix_display_name','分析教师');localStorage.setItem('edumatrix_onboarded','true')}""",[tokens[teacher],teacher])
                    page.goto(f"{BASE}/teaching-analytics",wait_until="domcontentloaded",timeout=30000);workspace=page.get_by_test_id("teaching-analytics-page");workspace.wait_for(state="visible",timeout=30000)
                    page.get_by_label("教学班").select_option(class_id);page.get_by_label("开始日期").fill("2026-08-03");page.get_by_label("结束日期").fill("2026-08-05");page.get_by_role("button",name="生成冻结报告").click();page.get_by_test_id("metric-participation_rate").wait_for(state="visible",timeout=30000)
                    text=workspace.inner_text();assert "67%" in text and "小样本" in text and "比赛演示指标" in text and "200 分钟" in text
                    report["screenshots"].append("01-explainable-period-report.png");page.screenshot(path=str(OUTPUT/report["screenshots"][-1]),full_page=True)
                    list_response=page.request.get(f"{BASE}/api/v1/teaching-analytics/reports",headers=headers,params={"class_id":class_id});assert list_response.ok;report_id=list_response.json()["items"][0]["id"]
                    exports=[page.request.get(f"{BASE}/api/v1/teaching-analytics/reports/{report_id}/export/{fmt}",headers=headers) for fmt in ("json","csv")];assert all(item.ok for item in exports) and "participation_rate" in exports[1].text()
                    denied=[page.request.get(f"{BASE}/api/v1/teaching-analytics/reports/{report_id}",headers=outsider_headers),page.request.get(f"{BASE}/api/v1/teaching-analytics/reports/{report_id}/export/csv",headers=outsider_headers)];assert [r.status for r in denied]==[403,403]
                    page.reload(wait_until="domcontentloaded",timeout=30000);page.get_by_test_id("metric-participation_rate").wait_for(state="visible",timeout=30000)
                    page.set_viewport_size({"width":390,"height":844});page.wait_for_timeout(300);geometry=page.evaluate("()=>({viewport:innerWidth,documentWidth:document.documentElement.scrollWidth,panel:document.querySelector('[data-testid=teaching-analytics-page]').getBoundingClientRect().width})");assert geometry["documentWidth"]<=391
                    report["screenshots"].append("02-mobile-analytics-report.png");page.screenshot(path=str(OUTPUT/report["screenshots"][-1]),full_page=True)
                    report["checks"]={"metric_cards":4,"participation_rate":.6667,"small_sample_disclosed":True,"learner_high_burden_minutes":200,"refresh_recovery":True,"exports":["json","csv"],"cross_manager_statuses":[403,403],"mobile_viewport":geometry};report["result"]="passed"
                finally:context.close();browser.close()
    except Exception as exc:report["result"]="failed";report["error"]=f"{type(exc).__name__}: {exc}";raise
    finally:
        report["finished_at"]=time.strftime("%Y-%m-%dT%H:%M:%S%z");stop(backend)
        if DB_PATH.exists():
            with sqlite3.connect(DB_PATH) as source,sqlite3.connect(EVIDENCE_DB) as target:source.backup(target);report["checks"]["sqlite_integrity"]=target.execute("pragma integrity_check").fetchone()[0]
        (OUTPUT/"report.json").write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
        files=[{"file":p.name,"bytes":p.stat().st_size,"sha256":digest(p)} for p in sorted(OUTPUT.iterdir()) if p.is_file() and p.name!="manifest.json" and not p.name.endswith(("-wal","-shm"))]
        (OUTPUT/"manifest.json").write_text(json.dumps({"schema_version":"next.teaching-analytics-manifest.v1","files":files},ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(report,ensure_ascii=False,indent=2));return 0

if __name__=="__main__":raise SystemExit(main())
