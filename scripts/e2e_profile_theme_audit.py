"""Read-only visual audit of the three student profile surfaces."""
from __future__ import annotations

import json, os, shutil, socket, sqlite3, subprocess, sys, time
from pathlib import Path
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
OUT = ROOT / "outputs" / "原系统融合重构执行" / "evidence" / "custom_tasks" / "PROFILE-PAGE-THEME-AUDIT-01" / "browser"
DB = OUT.parent / "profile_theme_runtime.db"
PORT = 8976
BASE = f"http://127.0.0.1:{PORT}"
COURSE_ID = "demo-course-rag-trust-v1"

def clean():
    OUT.mkdir(parents=True, exist_ok=True)
    for p in OUT.iterdir():
        if p.is_file() or p.is_symlink(): p.unlink()
        else: shutil.rmtree(p)
    for suffix in ("", "-wal", "-shm"):
        p = Path(str(DB) + suffix)
        if p.exists(): p.unlink()

def seed():
    os.environ.update({"EDUMATRIX_DB_PATH": str(DB), "EDUMATRIX_AUTH_SECRET_KEY": "profile-theme-audit-secret",
        "EDUMATRIX_LLM_PROVIDER": "deterministic", "EDUMATRIX_LLM_MODEL": "deterministic",
        "EDUMATRIX_LLM_API_KEY": "", "EDUMATRIX_LLM_ENDPOINT": "", "EDUMATRIX_EMBEDDING_PROVIDER": "hash",
        "EDUMATRIX_RELOAD": "0", "EDUMATRIX_HOST": "127.0.0.1", "EDUMATRIX_PORT": str(PORT),
        "PYTHON_DOTENV_DISABLED": "1", "PYTHONUNBUFFERED": "1", "EDUMATRIX_SANDBOX_MODE": "disabled"})
    from app.database import init_db, SessionLocal
    from app.competition_demo_seed import seed_competition_demo
    init_db(); db = SessionLocal()
    try: seed_competition_demo(db)
    finally: db.close()

def login(page):
    r = page.request.post(f"{BASE}/api/auth/login", form={"username":"lzz", "password":"404404aA"})
    if not r.ok: raise RuntimeError(f"login {r.status}: {r.text()}")
    return r.json()

def install(page, payload):
    state = json.dumps(payload, ensure_ascii=False)
    page.add_init_script(f"""(() => {{ const s={state}; localStorage.setItem('edumatrix_token',s.access_token); localStorage.setItem('edumatrix_username','lzz'); localStorage.setItem('edumatrix_display_name',s.display_name||'lzz'); localStorage.setItem('edumatrix_role','student'); localStorage.setItem('edumatrix_student_id',s.student_id||'lzz'); localStorage.setItem('edumatrix_onboarded','true'); localStorage.setItem('edumatrix_course_id','{COURSE_ID}'); }})()""")

def metrics(page):
    return page.evaluate("""() => {
      const pick = (s) => { const e=document.querySelector(s); if(!e) return null; const c=getComputedStyle(e); return {selector:s, color:c.color, background:c.backgroundColor, border:c.borderColor, fontSize:c.fontSize}; };
      const body=getComputedStyle(document.body); const root=document.documentElement;
      const visible = [...document.querySelectorAll('button,a,input,select,textarea,h1,h2,h3,p,span')].filter(e => { const r=e.getBoundingClientRect(), c=getComputedStyle(e); return r.width>1&&r.height>1&&c.visibility!=='hidden'&&c.display!=='none'; });
      const overflow = root.scrollWidth > innerWidth + 1;
      const clipped = visible.filter(e => { const r=e.getBoundingClientRect(); return r.right>innerWidth+1 || r.left < -1; }).slice(0,10).map(e=>({tag:e.tagName,text:(e.innerText||'').trim().slice(0,50)}));
      return {viewport:[innerWidth,innerHeight], body:{color:body.color,background:body.backgroundColor,font:body.fontFamily}, overflow, clipped, bodyText:(document.body.innerText||'').trim().length, colors:[pick('.profile-page'),pick('.profile-state'),pick('.identity-band'),pick('.content-panel'),pick('.profile-map-section'),pick('.profile-map-canvas'),pick('.profile-update-page'),pick('.conversation-panel'),pick('.round-review'),pick('.complete-message'),pick('.button--primary'),pick('.profile-primary-action')]};
    }""")

def main():
    clean(); seed(); report={"result":"running","viewports":{},"screenshots":[]}; proc=None
    try:
        env=os.environ.copy(); log=(OUT.parent/"backend.log").open("w",encoding="utf-8")
        proc=subprocess.Popen([sys.executable,"run.py"],cwd=ROOT,env=env,stdout=log,stderr=subprocess.STDOUT)
        deadline=time.monotonic()+50
        import urllib.request
        while time.monotonic()<deadline:
            try:
                with urllib.request.urlopen(f"{BASE}/api/health",timeout=2) as r:
                    if r.status==200: break
            except Exception: time.sleep(.25)
        else: raise RuntimeError("health timeout")
        with sync_playwright() as pw:
            browser=pw.chromium.launch(headless=True); setup=browser.new_page(); payload=login(setup); setup.close()
            for viewport in ((1920,1080),(2560,1600)):
                ctx=browser.new_context(viewport={"width":viewport[0],"height":viewport[1]},locale="zh-CN"); page=ctx.new_page(); install(page,payload)
                errors=[]; http=[]; expected_aborts=[]
                page.on("pageerror",lambda e:errors.append({"type":"pageerror","message":str(e)}))
                page.on("console",lambda m:errors.append({"type":"console","message":m.text}) if m.type=="error" else None)
                page.on("requestfailed",lambda r: expected_aborts.append({"url":r.url,"message":str(r.failure)}) if "ERR_ABORTED" in str(r.failure) else errors.append({"type":"requestfailed","url":r.url,"message":str(r.failure)}))
                page.on("response",lambda r:http.append({"url":r.url,"status":r.status}) if r.status>=400 else None)
                vp=f"{viewport[0]}x{viewport[1]}"; report["viewports"][vp]={"pages":{},"errors":errors,"http_errors":http,"expected_request_aborts":expected_aborts}
                for key,url in (("dashboard",f"/profile?course_id={COURSE_ID}"),("learning",f"/profile/learning?course_id={COURSE_ID}"),("update",f"/profile/update?course_id={COURSE_ID}")):
                    page.goto(BASE+url,wait_until="domcontentloaded",timeout=45_000)
                    page.wait_for_timeout(5000 if key == "learning" else 2200)
                    name=f"{vp}-{key}.png"; page.screenshot(path=str(OUT/name),full_page=True); report["screenshots"].append(name)
                    report["viewports"][vp]["pages"][key]={"url":page.url,"metrics":metrics(page),"text":page.locator("body").inner_text()[:1000]}
                    if key == "learning":
                        scrolled = page.evaluate("""() => { const xs=[...document.querySelectorAll('*')].filter(e=>e.scrollHeight>e.clientHeight+80 && ['auto','scroll'].includes(getComputedStyle(e).overflowY)).sort((a,b)=>b.scrollHeight-a.scrollHeight); const t=xs[0]; if(t){t.scrollTop=Math.min(900,t.scrollHeight-t.clientHeight)} return t ? {className:String(t.className||''),scrollTop:t.scrollTop,scrollHeight:t.scrollHeight,clientHeight:t.clientHeight} : null }""")
                        detail_name=f"{vp}-learning-detail.png"; page.screenshot(path=str(OUT/detail_name),full_page=False); report["screenshots"].append(detail_name)
                        report["viewports"][vp]["pages"]["learning_detail"]={"scroll":scrolled,"metrics":metrics(page)}
                ctx.close();
            browser.close()
        with sqlite3.connect(DB) as db:
            report["database_integrity"]=db.execute("PRAGMA integrity_check").fetchone()[0]
            report["foreign_key_violations"]=len(db.execute("PRAGMA foreign_key_check").fetchall())
        report["result"]="passed" if not any(v["errors"] or v["http_errors"] for v in report["viewports"].values()) else "failed"
    except Exception as exc:
        report["result"]="failed"; report["error"]=repr(exc)
    finally:
        if proc: proc.terminate(); proc.wait(timeout=10)
        (OUT.parent/"browser_report.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps(report,ensure_ascii=False,indent=2)); return 0 if report["result"]=="passed" else 1

if __name__ == "__main__": raise SystemExit(main())
