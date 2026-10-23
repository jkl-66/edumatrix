"""Run the FC5 marketplace judge journey against isolated FastAPI/SQLite/Chrome."""
from __future__ import annotations

import hashlib, json, os, socket, sqlite3, subprocess, sys, time
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT=Path(__file__).resolve().parents[1]
OUTPUT=Path(os.environ.get("EDUMATRIX_E2E_OUTPUT_DIR",ROOT/"outputs"/"FC_比赛功能完全体"/"evidence"/"FC5-05A"/"browser-e2e"))
DB=Path(os.environ.get("EDUMATRIX_E2E_DB_PATH",ROOT/"outputs"/"_fc5_marketplace_journey_runtime.db"))
PORT=int(os.environ.get("EDUMATRIX_E2E_PORT","8842"));BASE=f"http://127.0.0.1:{PORT}";PASSWORD="FC5-marketplace-journey-2026!"

def wait_port(expected,timeout=45):
 end=time.monotonic()+timeout
 while time.monotonic()<end:
  with socket.socket() as sock:opened=sock.connect_ex(("127.0.0.1",PORT))==0
  if opened is expected:return
  time.sleep(.2)
 raise RuntimeError("marketplace journey port state timeout")

def auth(page,name,role):
 response=page.request.post(BASE+"/api/auth/register",data={"username":name,"password":PASSWORD,"display_name":name});assert response.ok,response.text()
 with sqlite3.connect(DB) as db:db.execute("update users set role=? where username=?",(role,name));db.commit()
 login=page.request.post(BASE+"/api/auth/login",form={"username":name,"password":PASSWORD});assert login.ok,login.text()
 return {"username":name,"public_id":response.json()["user_id"],"token":login.json()["access_token"],"headers":{"Authorization":"Bearer "+login.json()["access_token"]},"role":role}

def browser_state(page,user):
 page.goto(BASE+"/login",wait_until="domcontentloaded")
 page.evaluate("([t,n,r])=>{localStorage.setItem('edumatrix_token',t);localStorage.setItem('edumatrix_role',r);localStorage.setItem('edumatrix_username',n);localStorage.setItem('edumatrix_display_name','FC5 市场旅程管理员');localStorage.setItem('edumatrix_onboarded','true')}",[user["token"],user["username"],user["role"]])

def insert_course(owner,stamp):
 course=f"fc5-market-course-{stamp}";content="可信训练需要版本、来源、许可与真实学习证据共同支撑。";digest=hashlib.sha256(content.encode()).hexdigest()
 with sqlite3.connect(DB) as db:
  db.execute("insert into courses(id,version,title,subject,description,content_origin,license_text,visibility,status,owner_public_id,manifest_version,manifest_data,created_at) values(?,?,?,?,?,?,?,?,?,?,?,?,CURRENT_TIMESTAMP)",(course,"1.0","AI 可信训练市场旅程","人工智能","冻结合成课程 v1","https://example.invalid/fc5-market","CC BY 4.0","private","published",owner,"fc5-market-v1",json.dumps({"learning_objectives":["可信训练","证据治理"]},ensure_ascii=False)))
  db.execute("insert into course_memberships(id,course_id,user_public_id,role,status,created_at,updated_at) values(?,?,?,?,?,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)",(f"cm-{stamp}",course,owner,"teacher","active"))
  db.execute("insert into course_documents(id,course_id,chapter_order,filename,file_type,file_size,title,content,tags,chunk_count,content_hash,source_path,license_text,status,created_at) values(?,?,?,?,?,?,?,?,?,?,?,?,?,?,CURRENT_TIMESTAMP)",(f"doc-{stamp}",course,1,"trust.md","md",len(content.encode()),"可信训练",content,"[]",1,digest,"trust.md","CC BY 4.0","published"))
  db.execute("insert into source_documents(id,course_id,title,filename,file_format,content_hash,source_sha256,processed_sha256,file_size,source_url,source_path,license_text,parser_version,parser_metadata,parse_warnings,processing_error_code,processing_status,created_at,updated_at) values(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)",(f"src-{stamp}",course,"可信训练来源","trust.md","md",digest,"b"*64,"c"*64,128,"https://example.invalid/source","trust.md","CC BY 4.0","fc5-market","{}","[]","","ready"));db.commit()
 return course

def submit(page,user,course,title):
 response=page.request.post(BASE+"/api/v1/marketplace/listings",headers=user["headers"],data={"course_id":course,"title":title,"summary":"来源与许可可追溯的冻结合成 AI 课程","category":"人工智能","tags":["AI","可信训练"]});assert response.ok,response.text();return response.json()

def decision(page,admin,row,action,reason,impact=None):
 body={"action":action,"reason":reason,"expected_version":row["lock_version"]}
 if impact:body["impact_kind"]=impact
 response=page.request.post(BASE+f"/api/v1/marketplace/listings/{row['id']}/decisions",headers=admin["headers"],data=body);assert response.ok,response.text();return response.json()

def publish(page,admin,row,impact=None):return decision(page,admin,decision(page,admin,row,"approve","冻结来源与许可字段审核通过"),"publish","批准进入比赛演示公共市场",impact)

def shot(page,name,report):
 page.screenshot(path=str(OUTPUT/name),full_page=True);report["screenshots"].append(name)

def manifest():
 files=[{"file":p.name,"bytes":p.stat().st_size,"sha256":hashlib.sha256(p.read_bytes()).hexdigest()} for p in sorted(OUTPUT.iterdir()) if p.is_file() and p.name!="manifest.json" and not p.name.endswith(("-wal","-shm"))]
 (OUTPUT/"manifest.json").write_text(json.dumps({"schema_version":"fc5.marketplace-judge-journey-e2e-manifest.v1","files":files},ensure_ascii=False,indent=2)+"\n",encoding="utf-8")

def main():
 OUTPUT.mkdir(parents=True,exist_ok=True)
 for p in OUTPUT.iterdir():
  if p.is_file():p.unlink()
 for suffix in ("","-wal","-shm"):
  p=Path(str(DB)+suffix)
  if p.exists():p.unlink()
 env=os.environ.copy();env.update({"EDUMATRIX_DB_PATH":str(DB),"EDUMATRIX_AUTH_SECRET_KEY":"fc5-marketplace-isolated-secret","EDUMATRIX_LLM_PROVIDER":"deterministic","EDUMATRIX_LLM_MODEL":"deterministic","EDUMATRIX_LLM_API_KEY":"","EDUMATRIX_LLM_ENDPOINT":"","EDUMATRIX_EMBEDDING_PROVIDER":"hash","EDUMATRIX_RELOAD":"0","EDUMATRIX_HOST":"127.0.0.1","EDUMATRIX_PORT":str(PORT),"PYTHON_DOTENV_DISABLED":"1","PYTHONUNBUFFERED":"1"})
 report={"schema_version":"fc5.marketplace-judge-journey-e2e.v1","scope":"submission-review-search-engagement-acquisition-fork-update-withdrawal","fixture_boundary":"Frozen synthetic course and demonstration accounts; no payment, legal review, third-party certification or real enterprise claim.","checks":{},"screenshots":[],"started_at":time.strftime("%Y-%m-%dT%H:%M:%S%z")};process=None
 try:
  with (OUTPUT/"backend.log").open("w",encoding="utf-8") as log:
   process=subprocess.Popen([sys.executable,"run.py"],cwd=ROOT,env=env,stdout=log,stderr=subprocess.STDOUT);wait_port(True)
   with sync_playwright() as pw:
    browser=pw.chromium.launch(channel="chrome",headless=True);context=browser.new_context(viewport={"width":1440,"height":1000},locale="zh-CN");page=context.new_page();stamp=str(int(time.time()))
    admin=auth(page,f"fc5_market_admin_{stamp}","admin");publisher=auth(page,f"fc5_market_publisher_{stamp}","teacher");learner=auth(page,f"fc5_market_learner_{stamp}","student");outsider=auth(page,f"fc5_market_outsider_{stamp}","teacher")
    course=insert_course(publisher["public_id"],stamp);v1=submit(page,publisher,course,"AI 可信训练市场旅程 v1")
    browser_state(page,admin);page.goto(BASE+"/judge-journey/marketplace",wait_until="networkidle");root=page.get_by_test_id("marketplace-judge-journey");root.get_by_text("尚未开始生态市场旅程",exact=True).wait_for(timeout=20000)
    root.get_by_label("已提交市场条目").select_option(v1["id"]);root.get_by_label("指定体验账号").select_option(learner["public_id"]);shot(page,"01-empty-frozen-boundary.png",report)
    root.get_by_role("button",name="新建市场旅程").click();root.get_by_text("1 / 8",exact=True).wait_for();workspace=page.request.get(BASE+"/api/v1/competition-journeys/marketplace",headers=admin["headers"]).json();run=workspace["runs"][0];shot(page,"02-submission-one-of-eight.png",report)
    for step in run["steps"]:
     response=page.request.post(BASE+f"/api/v1/competition-journeys/marketplace/runs/{run['id']}/visits",headers=admin["headers"],data={"step_key":step["key"],"route":step["route"]});assert response.ok,response.text()
    visited=page.request.get(BASE+f"/api/v1/competition-journeys/marketplace/runs/{run['id']}",headers=admin["headers"]).json();assert visited["progress"]["completed"]==1 and len(visited["visits"])==8
    v1=publish(page,admin,v1);proof=page.request.post(BASE+f"/api/v1/competition-journeys/marketplace/runs/{run['id']}/search-verification",headers=admin["headers"]);assert proof.ok,proof.text()
    page.reload(wait_until="networkidle");root=page.get_by_test_id("marketplace-judge-journey");root.get_by_text("3 / 8",exact=True).wait_for();shot(page,"03-review-search-three-of-eight.png",report)
    favorite=page.request.put(BASE+f"/api/v1/marketplace/listings/{v1['id']}/favorite",headers=learner["headers"],data={"active":True});assert favorite.ok
    acquisition=page.request.post(BASE+f"/api/v1/marketplace/listings/{v1['id']}/acquisitions",headers=learner["headers"]);assert acquisition.ok,acquisition.text();acquisition=acquisition.json()
    review=page.request.put(BASE+f"/api/v1/marketplace/listings/{v1['id']}/review",headers=learner["headers"],data={"rating":5,"body":"已导入课程并检查冻结来源。"});assert review.ok,review.text()
    before_usage=page.request.get(BASE+f"/api/v1/competition-journeys/marketplace/runs/{run['id']}",headers=admin["headers"]).json();assert before_usage["progress"]["completed"]==4
    with sqlite3.connect(DB) as db:db.execute("insert into learning_events(id,owner_public_id,course_id,event_type,schema_version,source,trace_id,object_type,object_id,payload,occurred_at,recorded_at) values(?,?,?,?,?,?,?,?,?,?,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)",(f"le-{stamp}",learner["public_id"],acquisition["derived_course_id"],"course.resource.completed","1.0","browser-e2e",f"trace-{stamp}","course",acquisition["derived_course_id"],"{}"));db.commit()
    fork=page.request.post(BASE+f"/api/v1/marketplace/listings/{v1['id']}/forks",headers=learner["headers"],data={"modification_summary":"建立比赛演示独立版本线"});assert fork.ok,fork.text();fork=fork.json()
    page.reload(wait_until="networkidle");root=page.get_by_test_id("marketplace-judge-journey");root.get_by_text("6 / 8",exact=True).wait_for();shot(page,"04-use-acquisition-fork-six-of-eight.png",report)
    with sqlite3.connect(DB) as db:db.execute("update courses set version='2.0',title='AI 可信训练市场旅程上游 v2',description='上游重要修复',manifest_version='fc5-market-v2' where id=?",(course,));db.commit()
    v2=publish(page,admin,submit(page,publisher,course,"AI 可信训练市场旅程 v2"),"severe_fix")
    page.reload(wait_until="networkidle");root=page.get_by_test_id("marketplace-judge-journey");root.get_by_text("7 / 8",exact=True).wait_for();shot(page,"05-update-notification-seven-of-eight.png",report)
    v1=decision(page,admin,v1,"withdraw","旧版正式撤回并保留体验学员本地副本")
    page.reload(wait_until="networkidle");root=page.get_by_test_id("marketplace-judge-journey");root.get_by_text("8 / 8",exact=True).wait_for();root.get_by_text("八步市场闭环完成",exact=True).wait_for();shot(page,"06-complete-eight-of-eight.png",report)
    page.reload(wait_until="networkidle");root.get_by_text("8 / 8",exact=True).wait_for()
    denied=page.request.get(BASE+"/api/v1/competition-journeys/marketplace",headers=outsider["headers"]);assert denied.status==403
    page.set_viewport_size({"width":390,"height":844});page.wait_for_timeout(500);width=page.evaluate("document.documentElement.scrollWidth");assert width<=390;shot(page,"07-mobile-complete.png",report)
    final=page.request.get(BASE+f"/api/v1/competition-journeys/marketplace/runs/{run['id']}",headers=admin["headers"]).json();assert final["status"]=="completed" and final["progress"]["completed"]==8
    report["checks"].update({"run_id":run["id"],"listing_v1":v1["id"],"listing_v2":v2["id"],"initial_progress":1,"visit_only_progress":visited["progress"]["completed"],"before_usage_progress":before_usage["progress"]["completed"],"final_progress":final["progress"]["completed"],"visits":len(final["visits"]),"acquisition_id":acquisition["id"],"fork_id":fork["id"],"outsider_workspace_status":denied.status,"mobile_width":width});report["result"]="passed";context.close();browser.close()
 finally:
  if process and process.poll() is None:
   subprocess.run(["taskkill","/PID",str(process.pid),"/T","/F"],capture_output=True,text=True,timeout=20);process.wait(timeout=5);wait_port(False,15)
  if DB.exists():
   with sqlite3.connect(DB) as source,sqlite3.connect(OUTPUT/"fc5_marketplace_journey_evidence.db") as target:
    source.backup(target);report["checks"]["sqlite"]=target.execute("pragma integrity_check").fetchone()[0];report["checks"]["foreign_key_violations"]=len(target.execute("pragma foreign_key_check").fetchall());report["checks"]["migration_059_060"]=target.execute("select count(*) from schema_migrations where version in ('20260805_059','20260805_060')").fetchone()[0];report["checks"]["search_proofs"]=target.execute("select count(*) from marketplace_journey_search_verifications").fetchone()[0];report["checks"]["impact_notices"]=target.execute("select count(*) from marketplace_impact_notifications").fetchone()[0]
  report["finished_at"]=time.strftime("%Y-%m-%dT%H:%M:%S%z");(OUTPUT/"report.json").write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8");manifest()
 print(json.dumps(report,ensure_ascii=False));return 0

if __name__=="__main__":raise SystemExit(main())
