"""Submit frozen resource scenarios through learner APIs, then only observe.

This runner never edits a draft, supplies recovery feedback, or calls recover,
retry, complete, or review-decision endpoints. Existing job IDs are reused.
"""
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import argparse
import hashlib
import json
import time
import requests

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "scratch/automatic-generation-r207"


def run(case_id, base, observe_seconds, revision=""):
    manifest = json.loads((OUT / "inputs.json").read_text(encoding="utf-8"))
    credentials = json.loads((OUT / "credentials.local.json").read_text(encoding="utf-8"))
    supplementary = OUT / 'capability-inputs-r208e.json'
    additional = json.loads(supplementary.read_text(encoding='utf8'))['cases'] if supplementary.exists() else []
    case = next(item for item in [*manifest["cases"], *additional] if item["id"] == case_id)
    if case["entry"] != "resource_center":
        raise ValueError("This runner submits only resource-center scenarios; use each other scenario's real entry.")
    run_name = case_id + ("-" + revision if revision else "")
    folder = OUT / "runs" / run_name
    folder.mkdir(parents=True, exist_ok=True)
    session = requests.Session()
    login = session.post(base + "/api/auth/login", data=credentials[case["persona"]], timeout=30)
    login.raise_for_status()
    session.headers["Authorization"] = "Bearer " + login.json()["access_token"]
    trace = folder / "submission.json"
    if trace.exists():
        saved = json.loads(trace.read_text(encoding="utf-8"))
    else:
        profile = manifest["personas"][case["persona"]]
        title = case.get('title', manifest['title'])
        instruction = case.get('instruction', manifest["common_instruction"]) + (
            "\n按所选资源类型分工完成本学习目标；每类只承担适合它的学习动作。视频用于定位相关概念；"
            "交互实验使用实际注册模板的输入与输出；代码练习完成给定数据计算。不同活动明确其各自数据。"
        )
        request = {"course_id": manifest["course_id"], "knowledge_point_id": case.get('knowledge_point_id', manifest["knowledge_point_id"]),
            "profile_snapshot_id": profile["profile_snapshot_id"], "idempotency_key": "r207-" + run_name,
            "scope": "single" if len(case["types"]) == 1 else "bundle", "learning_goal": title,
            "user_instruction": instruction,
            "items": [{"type": kind, "title": title, "source_ref_ids": case.get('source_ref_ids', [item["id"] for item in manifest["sources"]])}
                      for kind in case["types"]]}
        (folder / "request.json").write_text(json.dumps(request, ensure_ascii=False, indent=2), encoding="utf-8")
        started = time.time()
        result = session.post(base + "/api/v1/resource-bundles/generation-jobs", json=request, timeout=60)
        result.raise_for_status()
        saved = {"job_id": result.json()["job_id"], "started_at": started, "case": case_id,
                 "request_hash": hashlib.sha256(json.dumps(request, ensure_ascii=False, sort_keys=True).encode()).hexdigest()}
        trace.write_text(json.dumps(saved, indent=2), encoding="utf-8")
    end = time.monotonic() + observe_seconds
    previous = None
    while True:
        try:
            response = session.get(base + "/api/v1/resource-bundles/generation-jobs/" + saved["job_id"], timeout=30)
            response.raise_for_status()
        except requests.RequestException as exc:
            with (folder / "observation-errors.jsonl").open("a", encoding="utf-8") as stream:
                stream.write(json.dumps({"at": time.time(), "error": str(exc)}) + "\n")
            if time.monotonic() >= end:
                return
            time.sleep(5)
            continue
        result = response.json()
        (folder / "latest.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        status = (result["automation"]["state"], result["status"], result["automation"]["attempts"])
        if status != previous:
            print(json.dumps({"case": case_id, "job_id": saved["job_id"], "state": status,
                              "elapsed_seconds": round(time.time()-saved["started_at"], 1)}), flush=True)
            previous = status
        if status[0] in {"completed", "cancelled", "waiting_configuration", "needs_attention"} or time.monotonic() >= end:
            return
        time.sleep(5)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("cases", nargs="+")
    parser.add_argument("--base", default="http://127.0.0.1:8944")
    parser.add_argument("--observe-seconds", type=int, default=45)
    parser.add_argument("--revision", default="", help="Fresh run after a product change; preserves the original run.")
    args = parser.parse_args()
    with ThreadPoolExecutor(max_workers=2) as pool:
        for result in pool.map(lambda case: run(case, args.base, args.observe_seconds, args.revision), args.cases):
            pass
