"""Runtime A/B/teacher authorization matrix for the competition build.

This script talks to a running local backend and verifies that an authenticated
student cannot substitute another student's ID across the main read/write
surfaces. It intentionally does not call external LLM or web-search providers.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Any

import httpx


ROOT = Path(__file__).resolve().parents[1]
BASE_URL = "http://127.0.0.1:8000"
OUTPUT = ROOT / "outputs" / "runtime_security_matrix.json"


def login(client: httpx.Client, username: str, password: str) -> tuple[str, dict[str, Any]]:
    response = client.post(
        "/api/auth/login",
        data={"username": username, "password": password},
    )
    response.raise_for_status()
    body = response.json()
    return body["access_token"], body


def register(client: httpx.Client, username: str) -> None:
    response = client.post(
        "/api/auth/register",
        json={
            "username": username,
            "password": "EduMatrix123!",
            "display_name": f"矩阵测试 {username}",
        },
    )
    response.raise_for_status()


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    timestamp = int(time.time())
    student_a = f"matrix_a_{timestamp}"
    student_b = f"matrix_b_{timestamp}"
    report: dict[str, Any] = {
        "base_url": BASE_URL,
        "started_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "accounts": {"student_a": student_a, "student_b": student_b},
        "checks": [],
    }

    with httpx.Client(base_url=BASE_URL, timeout=40.0) as client:
        register(client, student_a)
        register(client, student_b)
        token_a, _ = login(client, student_a, "EduMatrix123!")
        token_b, _ = login(client, student_b, "EduMatrix123!")
        headers_a = {"Authorization": f"Bearer {token_a}"}
        headers_b = {"Authorization": f"Bearer {token_b}"}

        def check(name: str, method: str, path: str, expected: set[int], *, headers=None, json_body=None) -> None:
            response = client.request(method, path, headers=headers, json=json_body)
            try:
                body: Any = response.json()
            except Exception:
                body = response.text[:300]
            if isinstance(body, dict):
                body = {
                    key: body[key]
                    for key in ("detail", "status", "student_id", "message", "received")
                    if key in body
                }
            elif isinstance(body, list):
                body = {"type": "list", "length": len(body)}
            elif isinstance(body, str):
                body = body[:300]
            item = {
                "name": name,
                "method": method,
                "path": path,
                "status": response.status_code,
                "expected": sorted(expected),
                "passed": response.status_code in expected,
                "body": body,
            }
            report["checks"].append(item)

        # Baseline authentication and own-scope checks.
        check("unauthenticated profile is rejected", "GET", f"/api/profile/{student_a}", {401})
        check("student A can read own profile", "GET", f"/api/profile/{student_a}", {200}, headers=headers_a)
        check("student B can read own profile", "GET", f"/api/profile/{student_b}", {200}, headers=headers_b)
        check("student A can use default alias for own scope", "GET", "/api/profile/default", {200}, headers=headers_a)

        # Cross-user path/query reads.
        cross_gets = [
            ("profile", f"/api/profile/{student_b}"),
            ("profile analysis", f"/api/profile/{student_b}/analysis"),
            ("learning path", f"/api/profile/{student_b}/learning-path"),
            ("goal recommendations", f"/api/profile/{student_b}/goal-recommendations"),
            ("profile narrative", f"/api/profile/{student_b}/narrative"),
            ("recommendations", f"/api/profile/{student_b}/recommendations"),
            ("knowledge list", f"/api/knowledge/list?student_id={student_b}"),
            ("knowledge document", f"/api/knowledge/not-a-real-document?student_id={student_b}"),
            ("quiz history", f"/api/quiz/history/{student_b}"),
            ("wrong questions", f"/api/quiz/wrong-questions/{student_b}"),
            ("wrong concepts", f"/api/quiz/wrong-concepts/{student_b}"),
            ("checkin streak", f"/api/quiz/checkin/streak/{student_b}"),
            ("checkin history", f"/api/quiz/checkin/history/{student_b}"),
            ("flashcard due", f"/api/flashcard/due?student_id={student_b}"),
            ("behavior scope is not a read route", f"/api/sessions/{student_b}"),
            ("conversation history", f"/api/history/{student_b}"),
            ("progress", f"/api/progress/{student_b}"),
            ("review plans", f"/api/review/{student_b}"),
            ("code history", f"/api/code/history/{student_b}"),
            ("profile PDF", f"/api/v1/profile/export?student_id={student_b}"),
        ]
        for label, path in cross_gets:
            check(f"A cannot read B: {label}", "GET", path, {403}, headers=headers_a)

        # Cross-user body/path mutations. Authorization must happen before
        # expensive parsing, LLM calls, network access, or resource lookup.
        cross_posts = [
            ("process", "/api/process", {"student_id": student_b, "message": "测试"}),
            ("stream explain", "/api/stream/explain", {"student_id": student_b, "message": "测试"}),
            ("stream chat", "/api/stream/chat", {"student_id": student_b, "message": "测试"}),
            ("profile update", f"/api/profile/{student_b}/update", {"major": "越权测试"}),
            ("profile update legacy", f"/api/profile/{student_b}", {"major": "越权测试"}),
            ("knowledge web source", "/api/knowledge/add-web-source", {"student_id": student_b, "url": "https://example.com"}),
            ("knowledge web download", "/api/knowledge/download-web-file", {"student_id": student_b, "url": "https://example.com/a.pdf"}),
            ("notes create", f"/api/notes/{student_b}", {"content": "越权测试"}),
            ("notes reflection", "/api/notes/append-reflection", {"student_id": student_b, "concept": "测试", "quiz_record_id": "missing", "wrong_reason": "测试"}),
            ("notes update", "/api/notes/update/not-a-real-note", {"student_id": student_b, "content": "越权测试"}),
            ("quiz generate", "/api/quiz/generate", {"student_id": student_b, "target_concept": "逻辑回归"}),
            ("quiz evaluate", "/api/quiz/evaluate", {"student_id": student_b, "quiz_id": "missing", "answer": "A"}),
            ("quiz adapt", "/api/quiz/adapt", {"student_id": student_b, "target_concept": "逻辑回归"}),
            ("quiz similar", "/api/quiz/similar", {"student_id": student_b, "source_quiz_id": "missing"}),
            ("flashcard generate", "/api/flashcard/generate", {"student_id": student_b, "concept": "逻辑回归"}),
            ("flashcard review", "/api/flashcard/review", {"student_id": student_b, "concept": "逻辑回归", "quality": 4}),
            ("behavior logs", "/api/behavior/logs", {"student_id": student_b, "actual_stay_seconds": 10}),
            ("quiz checkin", f"/api/quiz/checkin/{student_b}", {"tz_offset": 8}),
            ("code run", "/api/code/run", {"student_id": student_b, "code": "print(1)", "language": "python"}),
        ]
        for label, path, payload in cross_posts:
            check(f"A cannot mutate B: {label}", "POST", path, {403}, headers=headers_a, json_body=payload)

        # Teacher boundary: a student cannot enter teacher endpoints, while
        # the seeded teacher account can enter them.
        check("student A cannot access teacher dashboard", "GET", "/api/teacher", {403}, headers=headers_a)
        check("student B cannot access teacher reviews", "GET", "/api/teacher/reviews", {403}, headers=headers_b)
        try:
            teacher_token, teacher = login(client, "teacher", "admin123")
            teacher_headers = {"Authorization": f"Bearer {teacher_token}"}
            check("teacher can access teacher dashboard", "GET", "/api/teacher", {200}, headers=teacher_headers)
            check("teacher can access teacher reviews", "GET", "/api/teacher/reviews", {200}, headers=teacher_headers)
            report["teacher"] = {"available": True, "username": teacher.get("username", "teacher")}
        except Exception as exc:
            report["teacher"] = {"available": False, "reason": str(exc)}

    failed = [item for item in report["checks"] if not item["passed"]]
    report["summary"] = {
        "total": len(report["checks"]),
        "passed": len(report["checks"]) - len(failed),
        "failed": len(failed),
        "failed_names": [item["name"] for item in failed],
    }
    report["result"] = "passed" if not failed else "failed"
    report["finished_at"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    OUTPUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"result": report["result"], "summary": report["summary"]}, ensure_ascii=False, indent=2))
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
