"""Audit the unified FC5 showcase and six journeys at desktop/mobile viewports."""
from __future__ import annotations

import hashlib, json, os, socket, sqlite3, subprocess, sys, time
from pathlib import Path

from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parents[1]
OUTPUT = Path(os.environ.get("EDUMATRIX_E2E_OUTPUT_DIR", ROOT / "outputs" / "FC_比赛功能完全体" / "evidence" / "FC5-08A" / "browser-e2e"))
DB = Path(os.environ.get("EDUMATRIX_E2E_DB_PATH", ROOT / "outputs" / "_fc5_visual_quality_runtime.db"))
PORT = int(os.environ.get("EDUMATRIX_E2E_PORT", "8845"))
BASE = f"http://127.0.0.1:{PORT}"
PASSWORD = "FC5-visual-quality-2026!"
PAGES = (
    ("showcase", "/competition-showcase", "比赛演示中心"),
    ("student", "/judge-journey/student", "学生黄金旅程"),
    ("media", "/judge-journey/media", "多媒体创作旅程"),
    ("teacher", "/judge-journey/teacher", "教师教学旅程"),
    ("enterprise", "/judge-journey/enterprise", "企业培训旅程"),
    ("marketplace", "/judge-journey/marketplace", "生态市场旅程"),
    ("integration", "/judge-journey/integration", "本地集成旅程"),
)


def wait_port(expected: bool, timeout: int = 45) -> None:
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        with socket.socket() as sock:
            opened = sock.connect_ex(("127.0.0.1", PORT)) == 0
        if opened is expected: return
        time.sleep(0.2)
    raise RuntimeError("visual audit port state timeout")


def auth(page, name: str, role: str) -> dict:
    registered = page.request.post(BASE + "/api/auth/register", data={"username": name, "password": PASSWORD, "display_name": "FC5 视觉验收管理员"})
    assert registered.ok, registered.text()
    with sqlite3.connect(DB) as db:
        db.execute("update users set role=? where username=?", (role, name)); db.commit()
    login = page.request.post(BASE + "/api/auth/login", form={"username": name, "password": PASSWORD})
    assert login.ok, login.text()
    return {"username": name, "token": login.json()["access_token"], "headers": {"Authorization": "Bearer " + login.json()["access_token"]}, "role": role}


def browser_state(page, user: dict) -> None:
    page.goto(BASE + "/login", wait_until="domcontentloaded")
    page.evaluate("([t,n,r])=>{localStorage.setItem('edumatrix_token',t);localStorage.setItem('edumatrix_role',r);localStorage.setItem('edumatrix_username',n);localStorage.setItem('edumatrix_display_name','FC5 视觉验收管理员');localStorage.setItem('edumatrix_onboarded','true')}", [user["token"], user["username"], user["role"]])


def visual_metrics(page) -> dict:
    return page.evaluate("""() => {
      const visible = el => {
        const s=getComputedStyle(el),r=el.getBoundingClientRect();
        if(s.display==='none'||s.visibility==='hidden'||Number(s.opacity)<=0||r.width<=1||r.height<=1||r.right<=0||r.bottom<=0||r.left>=innerWidth||r.top>=innerHeight)return false
        const x=Math.max(0,Math.min(innerWidth-1,(Math.max(0,r.left)+Math.min(innerWidth,r.right))/2)),y=Math.max(0,Math.min(innerHeight-1,(Math.max(0,r.top)+Math.min(innerHeight,r.bottom))/2)),hit=document.elementFromPoint(x,y)
        return Boolean(hit&&(hit===el||el.contains(hit)||hit.contains(el)))
      }
      const controls=[...document.querySelectorAll('button,input,select,textarea,a[href]')].filter(visible)
      const collisions=[]
      for(let i=0;i<controls.length;i++) for(let j=i+1;j<controls.length;j++) {
        const a=controls[i],b=controls[j]; if(a.contains(b)||b.contains(a)) continue
        const x=a.getBoundingClientRect(),y=b.getBoundingClientRect(),w=Math.min(x.right,y.right)-Math.max(x.left,y.left),h=Math.min(x.bottom,y.bottom)-Math.max(x.top,y.top)
        if(w>2&&h>2) collisions.push([a.tagName,a.getAttribute('aria-label')||a.textContent.trim().slice(0,30),b.tagName,b.getAttribute('aria-label')||b.textContent.trim().slice(0,30)])
      }
      const clipped=[...document.querySelectorAll('button,label,h1,h2,h3,strong,code')].filter(el=>visible(el)&&(el.scrollWidth>el.clientWidth+2||el.scrollHeight>el.clientHeight+2)).map(el=>({tag:el.tagName,text:el.textContent.trim().slice(0,60),client:[el.clientWidth,el.clientHeight],scroll:[el.scrollWidth,el.scrollHeight]}))
      const bodyText=(document.body.innerText||'').trim()
      return {document_width:document.documentElement.scrollWidth,viewport_width:innerWidth,document_height:document.documentElement.scrollHeight,body_text_length:bodyText.length,controls:controls.length,collisions,clipped}
    }""")


def manifest() -> None:
    files=[{"file":p.name,"bytes":p.stat().st_size,"sha256":hashlib.sha256(p.read_bytes()).hexdigest()} for p in sorted(OUTPUT.iterdir()) if p.is_file() and p.name!="manifest.json" and not p.name.endswith(("-wal","-shm"))]
    (OUTPUT/"manifest.json").write_text(json.dumps({"schema_version":"fc5.visual-quality-e2e-manifest.v1","files":files},ensure_ascii=False,indent=2)+"\n",encoding="utf-8")


def main() -> int:
    OUTPUT.mkdir(parents=True,exist_ok=True)
    for path in OUTPUT.iterdir():
        if path.is_file(): path.unlink()
    for suffix in ("","-wal","-shm"):
        path=Path(str(DB)+suffix)
        if path.exists(): path.unlink()
    env=os.environ.copy();env.update({"EDUMATRIX_DB_PATH":str(DB),"EDUMATRIX_AUTH_SECRET_KEY":"fc5-visual-isolated-secret","EDUMATRIX_LLM_PROVIDER":"deterministic","EDUMATRIX_LLM_MODEL":"deterministic","EDUMATRIX_LLM_API_KEY":"","EDUMATRIX_LLM_ENDPOINT":"","EDUMATRIX_EMBEDDING_PROVIDER":"hash","EDUMATRIX_RELOAD":"0","EDUMATRIX_HOST":"127.0.0.1","EDUMATRIX_PORT":str(PORT),"PYTHON_DOTENV_DISABLED":"1","PYTHONUNBUFFERED":"1"})
    report={"schema_version":"fc5.visual-quality-e2e.v1","scope":"seven-pages-desktop-mobile-overflow-collision-clipping-errors-permissions","fixture_boundary":"Frozen synthetic showcase context; no external network or external certification claim.","checks":{"pages":{}},"screenshots":[],"browser_errors":[],"started_at":time.strftime("%Y-%m-%dT%H:%M:%S%z")}
    process=None
    try:
        with (OUTPUT/"backend.log").open("w",encoding="utf-8") as log:
            process=subprocess.Popen([sys.executable,"run.py"],cwd=ROOT,env=env,stdout=log,stderr=subprocess.STDOUT);wait_port(True)
            with sync_playwright() as pw:
                browser=pw.chromium.launch(channel="chrome",headless=True)
                context=browser.new_context(viewport={"width":1440,"height":1000},locale="zh-CN")
                page=context.new_page();stamp=str(int(time.time()));admin=auth(page,f"fc5_visual_admin_{stamp}","admin");student=auth(page,f"fc5_visual_student_{stamp}","student")
                page.on("pageerror",lambda exc:report["browser_errors"].append({"type":"pageerror","message":str(exc)}))
                page.on("console",lambda msg:report["browser_errors"].append({"type":"console","message":msg.text}) if msg.type=="error" else None)
                initialized=page.request.post(BASE+"/api/v1/competition-showcase/bootstrap",headers=admin["headers"]);assert initialized.ok,initialized.text()
                browser_state(page,admin)
                for viewport,width,height in (("desktop",1440,1000),("mobile",390,844)):
                    page.set_viewport_size({"width":width,"height":height})
                    for key,route,title in PAGES:
                        page.goto(BASE+route,wait_until="networkidle")
                        page.locator(".app-content").get_by_role("heading",name=title,exact=True).wait_for(timeout=20_000)
                        page.wait_for_timeout(250)
                        metrics=visual_metrics(page)
                        assert metrics["document_width"]<=width, f"{viewport}/{key} overflow: {metrics}"
                        assert metrics["body_text_length"]>=80, f"{viewport}/{key} blank: {metrics}"
                        assert not metrics["collisions"], f"{viewport}/{key} collisions: {metrics['collisions']}"
                        assert not metrics["clipped"], f"{viewport}/{key} clipping: {metrics['clipped']}"
                        if viewport == "mobile" and key == "marketplace":
                            summary = page.get_by_test_id("marketplace-listing-summary")
                            assert summary.is_visible()
                            assert "RAG 工程可信训练演示课程" in summary.inner_text()
                        name=f"{viewport}-{key}.png";page.screenshot(path=str(OUTPUT/name),full_page=True);report["screenshots"].append(name)
                        report["checks"]["pages"][f"{viewport}:{key}"]=metrics
                denied=page.request.get(BASE+"/api/v1/competition-showcase",headers=student["headers"]);assert denied.status==403
                unexpected_errors=list(report["browser_errors"])
                page.route("**/api/v1/competition-showcase",lambda route:route.fulfill(status=500,content_type="application/json",body='{"detail":"视觉验收故障状态"}'))
                page.goto(BASE+"/competition-showcase",wait_until="networkidle")
                page.get_by_text("视觉验收故障状态",exact=True).wait_for(timeout=20_000)
                error_metrics=visual_metrics(page);assert error_metrics["document_width"]<=390 and not error_metrics["collisions"]
                page.screenshot(path=str(OUTPUT/"mobile-showcase-error.png"),full_page=True);report["screenshots"].append("mobile-showcase-error.png")
                report["checks"].update({"student_api_status":denied.status,"error_state":error_metrics,"expected_injected_500_console_errors":len(report["browser_errors"])-len(unexpected_errors),"external_network_required":initialized.json()["truthfulness"]["external_network_required"]})
                assert not unexpected_errors,unexpected_errors
                report["result"]="passed";context.close();browser.close()
    finally:
        if process and process.poll() is None:
            subprocess.run(["taskkill","/PID",str(process.pid),"/T","/F"],capture_output=True,text=True,timeout=20);process.wait(timeout=5);wait_port(False,15)
        if DB.exists():
            with sqlite3.connect(DB) as source,sqlite3.connect(OUTPUT/"fc5_visual_quality_evidence.db") as target:
                source.backup(target);report["checks"]["sqlite"]=target.execute("pragma integrity_check").fetchone()[0];report["checks"]["foreign_key_violations"]=len(target.execute("pragma foreign_key_check").fetchall())
        report["finished_at"]=time.strftime("%Y-%m-%dT%H:%M:%S%z");(OUTPUT/"report.json").write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8");manifest()
    print(json.dumps(report,ensure_ascii=False));return 0


if __name__=="__main__":raise SystemExit(main())
