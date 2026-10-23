"""Real Chromium smoke evidence for the two-course lzz demo seed."""
from __future__ import annotations
import json, re
from pathlib import Path
from playwright.sync_api import sync_playwright

BASE="http://127.0.0.1:8000"
OUT=Path("outputs/原系统融合重构执行/evidence/custom_tasks/COURSE-DATA-DEMO-RESEED-03/browser")
OUT.mkdir(parents=True,exist_ok=True)
COURSES=["course-machine-learning-foundations-v1","course-ai-deep-learning-agents-v1"]

def run():
    report={"status":"passed","screenshots":[],"pages":[],"http_errors":[],"failed_requests":[],"page_errors":[],"console_errors":[]}
    with sync_playwright() as p:
        browser=p.chromium.launch(headless=True)
        for width,height in [(1920,1080),(2560,1600)]:
            context=browser.new_context(viewport={"width":width,"height":height},locale="zh-CN")
            page=context.new_page()
            page.on("response",lambda r: report["http_errors"].append({"url":r.url,"status":r.status}) if r.status>=500 else None)
            page.on("requestfailed",lambda r: report["failed_requests"].append({"url":r.url,"error":r.failure}))
            page.on("pageerror",lambda e: report["page_errors"].append(str(e)))
            page.on("console",lambda m: report["console_errors"].append(m.text) if m.type=="error" else None)
            page.goto(f"{BASE}/login",wait_until="domcontentloaded")
            page.get_by_test_id("login-username").fill("lzz"); page.get_by_test_id("login-password").fill("404404aA"); page.get_by_test_id("login-submit").click(); page.wait_for_timeout(800)
            for cid in COURSES:
                routes=[
                    ("home",f"/workspace?course_id={cid}"),
                    ("path",f"/workspace/path?course_id={cid}&path_id=lzzdemo03-{'ml' if cid==COURSES[0] else 'ai'}-path"),
                    ("resources",f"/workspace/resources?course_id={cid}"),
                    ("assessment",f"/workspace/assessment?course_id={cid}"),
                    ("profile",f"/profile/learning?course_id={cid}"),
                    ("chat",f"/chat?course_id={cid}"),
                ]
                for name,path in routes:
                    page.goto(BASE+path,wait_until="domcontentloaded",timeout=60000); page.wait_for_timeout(700)
                    body=page.locator("body").inner_text()
                    if len(body.strip())<40: report["status"]="failed"
                    shot=f"{width}x{height}-{('ml' if cid==COURSES[0] else 'ai')}-{name}.png"; page.screenshot(path=str(OUT/shot),full_page=True); report["screenshots"].append(shot)
                    report["pages"].append({"viewport":[width,height],"course_id":cid,"route":path,"body_chars":len(body),"title":page.title()})
            context.close()
        browser.close()
    (OUT/"browser_report.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
    print(json.dumps({"status":report["status"],"screenshots":len(report["screenshots"]),"http_errors":len(report["http_errors"]),"failed_requests":len(report["failed_requests"]),"page_errors":len(report["page_errors"]),"console_errors":len(report["console_errors"])},ensure_ascii=False))

if __name__=="__main__": run()
