from datetime import datetime, timezone

from fastapi.testclient import TestClient

from app.crud import review_plan_to_dict
from app.database import DBReviewPlan
from app.main import app
from tests.api_test_helpers import auth_headers


def test_review_dates_preserve_utc_in_browser_payload():
    plan = DBReviewPlan(student_id="time-test", concept="数组", course_id="array-course", next_review_at=datetime(2026, 10, 28, 16, 30), created_at=datetime(2026, 10, 27, 16, 30))
    result = review_plan_to_dict(plan)
    assert result["next_review_at"] == "2026-10-28T16:30:00Z"
    assert result["course_id"] == "array-course"
    assert datetime.fromisoformat(result["created_at"].replace("Z", "+00:00")).tzinfo == timezone.utc


def test_manual_review_rejects_invalid_inputs_and_repeat_keeps_one_plan():
    username = "manual-review-input-check"
    with TestClient(app) as client:
        headers = auth_headers(client, username)
        endpoint = f"/api/review/{username}"
        for bad in [
            {"concept": " "}, {"concept": "数组", "mastery": 2},
            {"concept": "数组", "interval_days": -1},
            {"concept": "数组", "interval_days": 1.5},
            {"concept": "数组", "mastery": "无效输入"},
        ]:
            assert client.post(endpoint, headers=headers, json=bad).status_code == 422
        payload = {"concept": "数组", "mastery": 0.5, "interval_days": 1}
        first = client.post(endpoint, headers=headers, json=payload)
        second = client.post(endpoint, headers=headers, json=payload)
        assert first.status_code == second.status_code == 200
        assert first.json()["id"] == second.json()["id"]
        assert first.json()["next_review_at"].endswith("Z")
        assert first.json()["review_count"] == 0


def test_manual_plans_preserve_selected_course_and_do_not_merge_same_named_topics():
    username = "manual-review-course-check"
    with TestClient(app) as client:
        headers = auth_headers(client, username)
        endpoint = f"/api/review/{username}"
        course_a = "course-machine-learning-foundations-v1"
        course_b = "course-ai-deep-learning-agents-v1"
        payload = {"concept": "边界条件", "mastery": .4, "interval_days": 2, "course_id": course_a}
        first = client.post(endpoint, headers=headers, json=payload)
        assert first.status_code == 200
        repeated = client.post(endpoint, headers=headers, json=payload)
        second = client.post(endpoint, headers=headers, json={**payload, "course_id": course_b})
        assert repeated.json()["id"] == first.json()["id"] != second.json()["id"]
        plans = client.get(endpoint, headers=headers).json()["due_reviews"]
        assert {p["course_id"] for p in plans} == {course_a, course_b}
        assert client.post(endpoint, headers=headers, json={**payload, "course_id": "unknown"}).status_code == 404
