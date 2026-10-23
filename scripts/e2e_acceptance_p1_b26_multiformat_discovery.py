"""FB-26 isolated browser journey for multi-format discovery and retry states."""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import Page, Route, sync_playwright

import e2e_f6_t03_code_sandbox as base
import e2e_f7_t03_graph_admission as f7


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT / ".agents" / "input" / "acceptance-feedback" / "evidence" / "P1-B26"


def _candidate(status: str = "pending_review", *, failed: bool = False) -> dict[str, object]:
    pipeline = {
        "download": {"status": "failed" if failed else "not_started", "code": "download_timeout" if failed else "", "message": "原站下载超时，候选已保留，可重新下载。" if failed else "尚未下载"},
        "parse": {"status": "blocked" if failed else "not_started", "code": "", "message": "等待下载重试" if failed else "尚未解析"},
        "citation": {"status": "blocked", "code": "", "message": "等待解析和来源核验"},
        "admission": {"status": "candidate" if not failed else "pending", "code": "", "message": "尚未准入"},
        "overall_status": "failed" if failed else "candidate",
        "retryable": True,
        "failure": {"status": "failed", "code": "download_timeout", "message": "原站下载超时，候选已保留，可重新下载。"} if failed else None,
    }
    return {
        "id": "b26-html-candidate",
        "query": "机器学习课程资料",
        "title": "开放课程 HTML 图片与多格式资料",
        "url": "https://open.example.org/course/index.html",
        "sourceDomain": "open.example.org",
        "authorOrOrganization": "开放课程组织",
        "fileFormat": "html",
        "formatLabel": "HTML 网页",
        "formatConfidence": "high",
        "formatDetection": "url_extension",
        "snippet": "正文、流程图、PDF、PPTX、DOCX 和视频课程入口。",
        "licenseStatus": "open_permissive" if status == "imported" else "unknown",
        "licenseText": "CC BY 4.0" if status == "imported" else "",
        "usageHint": "允许个人学习引用并保留署名" if status == "imported" else "请核对许可",
        "parsingImpact": {
            "summary": "可提取公开正文和图片地址/alt/位置；图片需授权后 OCR；视频字幕或转写可用时才进入引用。",
            "text": "best_effort",
            "images": "metadata_and_authorized_ocr",
            "video": "when_authorized",
            "pipeline": pipeline,
        },
        "processingPipeline": pipeline,
        "processingStatus": "admitted" if status == "imported" else ("failed" if failed else "candidate"),
        "citationStatus": "ready" if status == "imported" else "blocked",
        "retryable": status != "imported",
        "failure": pipeline["failure"],
        "trustLevel": "source_declared" if status == "imported" else "unverified",
        "reviewStatus": status,
        "importedVersion": "b26-source-v1" if status == "imported" else None,
        "importResult": {"source_document_id": "b26-source-doc", "status": "ready"} if status == "imported" else {},
        "canAdmit": status in {"pending_review", "license_required"} and status != "imported",
        "blockers": [] if status == "imported" else ["许可未确认", "用途说明缺失"],
        "authorityScope": "personal_course_source" if status == "imported" else "candidate_only",
        "authoritative": False,
        "resourceGenerationEligible": status == "imported",
        "createdAt": "2026-08-26T00:00:00+08:00",
        "updatedAt": "2026-08-26T00:00:00+08:00",
    }


def install_api_fixtures(page: Page, report: dict[str, object]) -> dict[str, object]:
    state = {"candidate": None, "admit_attempts": 0, "search_requests": 0}

    def handler(route: Route) -> None:
        request = route.request
        parsed = urlparse(request.url)
        path = parsed.path
        if path.endswith("/discovery/search") and request.method == "GET":
            state["search_requests"] += 1
            payload = {
                "schemaVersion": "edumatrix.web-source-discovery.v1",
                "status": "ready",
                "query": "机器学习课程资料",
                "items": [
                    {
                        "id": "b26-html-result",
                        "title": "开放课程 HTML 图片与多格式资料",
                        "url": "https://open.example.org/course/index.html",
                        "snippet": "正文、流程图、PDF、PPTX、DOCX 和视频课程入口。",
                        "sourceDomain": "open.example.org",
                        "authorOrOrganization": "开放课程组织",
                        "fileFormat": "html",
                        "formatLabel": "HTML 网页",
                        "formatConfidence": "high",
                        "formatDetection": "url_extension",
                        "licenseStatus": "unknown",
                        "usageHint": "请核对许可",
                        "parsingImpact": {
                            "summary": "可提取公开正文和图片地址/alt/位置；图片需授权后 OCR。",
                            "text": "best_effort",
                            "images": "metadata_and_authorized_ocr",
                            "video": "when_authorized",
                        },
                        "trustLevel": "unverified",
                        "reviewStatus": "not_saved",
                        "canAdmit": False,
                        "authoritative": False,
                    },
                    {
                        "id": "b26-pdf-result",
                        "title": "课程 PDF 讲义",
                        "url": "https://open.example.org/course/lesson.pdf",
                        "snippet": "正文、表格、公式和页面图片。",
                        "sourceDomain": "open.example.org",
                        "authorOrOrganization": "开放课程组织",
                        "fileFormat": "pdf",
                        "formatLabel": "PDF",
                        "formatConfidence": "high",
                        "formatDetection": "url_extension",
                        "licenseStatus": "unknown",
                        "usageHint": "请核对许可",
                        "parsingImpact": {"summary": "正文、页面图片和 OCR；复杂表格需复核。", "text": True, "images": "best_effort", "ocr": "best_effort"},
                        "trustLevel": "unverified",
                        "reviewStatus": "not_saved",
                        "canAdmit": False,
                        "authoritative": False,
                    },
                    {
                        "id": "b26-video-result",
                        "title": "课程视频（字幕可用时引用）",
                        "url": "https://open.example.org/course/lesson.mp4",
                        "snippet": "视频元数据；没有字幕时不作为完整正文。",
                        "sourceDomain": "open.example.org",
                        "authorOrOrganization": "开放课程组织",
                        "fileFormat": "mp4",
                        "formatLabel": "MP4 视频",
                        "formatConfidence": "high",
                        "formatDetection": "url_extension",
                        "licenseStatus": "unknown",
                        "usageHint": "请核对许可",
                        "parsingImpact": {"summary": "元数据可用，字幕/转写需授权或真实取得。", "metadata": True, "transcript": "when_authorized", "keyframes": "metadata_only"},
                        "trustLevel": "unverified",
                        "reviewStatus": "not_saved",
                        "canAdmit": False,
                        "authoritative": False,
                    },
                ],
                "filteredResultCount": 0,
                "authorityBoundary": "联网搜索结果只进入候选区；未经许可核验不得进入课程、图谱、RAG 或资源生成。",
            }
            route.fulfill(status=200, content_type="application/json", body=json.dumps(payload, ensure_ascii=False))
            return
        if path.endswith("/discovery/candidates") and request.method == "GET":
            items = [state["candidate"]] if state["candidate"] else []
            route.fulfill(status=200, content_type="application/json", body=json.dumps({"schemaVersion": "edumatrix.web-source-candidates.v1", "items": items}, ensure_ascii=False))
            return
        if path.endswith("/discovery/candidates") and request.method == "POST":
            state["candidate"] = _candidate()
            route.fulfill(status=200, content_type="application/json", body=json.dumps({"created": True, "candidate": state["candidate"]}, ensure_ascii=False))
            return
        if path.endswith("/admit") and request.method == "POST":
            state["admit_attempts"] += 1
            if state["admit_attempts"] == 1:
                state["candidate"] = _candidate("pending_review", failed=True)
                route.fulfill(status=503, content_type="application/json", body=json.dumps({"detail": {"message": "原站下载超时，候选已保留，可重新下载。"}}, ensure_ascii=False))
            else:
                state["candidate"] = _candidate("imported")
                route.fulfill(status=200, content_type="application/json", body=json.dumps({"created": True, "candidate": state["candidate"], "document": {"source_document_id": "b26-source-doc"}}, ensure_ascii=False))
            return
        if path.endswith("/withdraw") and request.method == "POST":
            state["candidate"] = _candidate("withdrawn")
            state["candidate"]["processingStatus"] = "candidate"
            route.fulfill(status=200, content_type="application/json", body=json.dumps({"candidate": state["candidate"]}, ensure_ascii=False))
            return
        route.continue_()

    page.route("**/api/knowledge/discovery/**", handler)
    page.route("**/api/knowledge/courses", lambda route: route.fulfill(
        status=200,
        content_type="application/json",
        body=json.dumps({"shelf": [{"id": "b26-course", "title": "FB-26 课程", "can_manage": True}]}, ensure_ascii=False),
    ))
    report["fixture_state"] = state
    return state


def diagnostics(page: Page, report: dict[str, object]) -> None:
    def response(response) -> None:
        if response.status >= 400:
            if response.status == 503 and response.url.endswith("/admit"):
                report["expected_failures"].append(response.url)
            else:
                report["http_errors"].append({"status": response.status, "url": response.url})

    page.on("response", response)
    page.on("requestfailed", lambda request: report["failed_requests"].append({"url": request.url, "failure": request.failure}))
    page.on("pageerror", lambda error: report["page_errors"].append(str(error)))
    page.on("console", lambda message: report["console_errors"].append(message.text) if message.type == "error" and "503" not in message.text else None)


def visual(page: Page, report: dict[str, object], key: str) -> None:
    result = f7.visual_contract(page, ".discovery-workspace", "discovery")
    report["visual"][key] = result
    assert result["missingRoot"] is False, result
    assert result["pageOverflow"] is False, result
    assert result["overlap"] is False, result
    assert result["smallText"] == [], result
    assert result["clippedText"] == [], result
    assert result["decorativeBackgrounds"] == [], result
    assert result["forbiddenThemeHits"] == [], result


def run() -> dict[str, object]:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    base.OUTPUT_DIR = OUTPUT_DIR
    base.PORT_START = 9031
    db_path = OUTPUT_DIR / "p1_b26.sqlite3"
    port = base.free_port()
    env = base.runtime_env(db_path, port)
    env["EDUMATRIX_AUTH_SECRET_KEY"] = "p1-b26-isolated-secret"
    env["EDUMATRIX_SANDBOX_MODE"] = "disabled"
    f7.OUTPUT_DIR = OUTPUT_DIR
    f7.seed_fixture(env)
    process: subprocess.Popen | None = None
    report: dict[str, object] = {
        "schema_version": "acceptance-feedback.p1-b26.browser.v1",
        "status": "running",
        "viewports": [[1440, 900], [1366, 768]],
        "screenshots": [],
        "visual": {},
        "expected_failures": [],
        "http_errors": [],
        "failed_requests": [],
        "page_errors": [],
        "console_errors": [],
    }
    try:
        process = base.start_service(env, port)
        base_url = f"http://127.0.0.1:{port}"
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            for width, height in ((1440, 900), (1366, 768)):
                context = browser.new_context(viewport={"width": width, "height": height}, locale="zh-CN")
                page = context.new_page()
                diagnostics(page, report)
                state = install_api_fixtures(page, report)
                base.login(page, base_url)
                page.goto(f"{base_url}/knowledge/discover", wait_until="networkidle", timeout=60_000)
                page.get_by_test_id("knowledge-discovery-workspace").wait_for(state="visible")
                page.get_by_test_id("discovery-search-input").fill("机器学习课程资料")
                page.get_by_test_id("discovery-search-submit").click()
                page.get_by_text("开放课程 HTML 图片与多格式资料", exact=True).first.wait_for(state="visible")
                preview = page.get_by_test_id("discovery-source-preview")
                assert "图片地址/说明，授权后 OCR" in page.locator("body").inner_text()
                assert "PDF" in page.locator(".source-list").inner_text()
                assert "MP4" in page.locator(".source-list").inner_text()
                result_row = page.locator(".source-row").filter(has_text="开放课程 HTML 图片与多格式资料")
                result_row.get_by_role("button").first.click()
                result_row.get_by_role("button", name="保存为候选", exact=True).click()
                page.get_by_role("tab", name="我的候选 1", exact=True).wait_for(state="visible")
                page.get_by_label("许可状态").select_option("open_permissive")
                page.get_by_label("许可原文或名称").fill("CC BY 4.0")
                page.get_by_label("允许用途").fill("允许个人学习引用并保留署名")
                form_before_failure = {
                    "course": page.get_by_test_id("candidate-course-select").input_value(),
                    "license": page.get_by_test_id("candidate-license-select").input_value(),
                    "license_text": page.get_by_label("许可原文或名称").input_value(),
                    "usage": page.get_by_label("允许用途").input_value(),
                }
                admit = page.get_by_test_id("candidate-admit")
                admit.click()
                page.get_by_text("操作没有完成", exact=True).wait_for(state="visible")
                assert "原站下载超时" in preview.inner_text()
                retry = page.get_by_role("button", name="重新下载并解析", exact=True)
                if retry.count() == 0:
                    report["retry_debug"] = {
                        "preview": preview.inner_text(),
                        "body": page.locator("body").inner_text(),
                        "candidate_admit_disabled": admit.is_disabled(),
                        "form_before_failure": form_before_failure,
                        "form_after_failure": {
                            "course": page.get_by_test_id("candidate-course-select").input_value(),
                            "license": page.get_by_test_id("candidate-license-select").input_value(),
                            "license_text": page.get_by_label("许可原文或名称").input_value(),
                            "usage": page.get_by_label("允许用途").input_value(),
                        },
                    }
                    page.screenshot(path=OUTPUT_DIR / f"{width}x{height}-retry-debug.png", full_page=True)
                    raise AssertionError(report["retry_debug"])
                retry.click()
                page.get_by_text("资料已从原站下载、解析并加入目标课程。", exact=True).wait_for(state="visible")
                assert "已准入且可引用" in preview.inner_text()
                assert "可引用状态" in preview.inner_text()
                assert "[object Object]" not in preview.inner_text()
                page.screenshot(path=OUTPUT_DIR / f"{width}x{height}-multiformat-retry.png", full_page=True)
                report["screenshots"].append(f"{width}x{height}-multiformat-retry.png")
                visual(page, report, f"{width}x{height}")
                context.close()
            browser.close()
        assert len(report["expected_failures"]) == 2, report["expected_failures"]
        assert not report["http_errors"], report["http_errors"]
        assert not report["failed_requests"], report["failed_requests"]
        assert not report["page_errors"], report["page_errors"]
        assert not report["console_errors"], report["console_errors"]
        report["status"] = "passed"
        return report
    finally:
        base.stop_service(process, port)
        report["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
        (OUTPUT_DIR / "browser-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=False, indent=2))
