from datetime import datetime, timezone
from types import SimpleNamespace

from app.dashboard_summary import activity_trend, mastery_trend


def _event(occurred_at, *, event_type="quiz_answered", completion_effect="complete", mastery=True):
    return SimpleNamespace(
        occurred_at=occurred_at,
        payload={},
        event_type=event_type,
        completion_effect=completion_effect,
        mastery_eligible=mastery,
        evidence_status="accepted" if mastery else "none",
        id=f"event-{occurred_at.isoformat()}",
    )


def test_activity_trend_uses_display_timezone_and_counts_completed_activity():
    events = [
        _event(datetime(2026, 9, 4, 23, 30)),  # 09-05 in Asia/Shanghai
        _event(datetime(2026, 9, 5, 1, 0)),
    ]
    points = activity_trend(events)
    assert points == [{
        "date": "2026-09-05",
        "event_count": 2,
        "active_minutes": 0.0,
        "label": "09-05",
    }]


def test_mastery_trend_uses_same_display_timezone_as_heatmap():
    event = _event(datetime(2026, 9, 4, 23, 30), mastery=True)
    consumption = SimpleNamespace(
        status="processed",
        result={"steps": {"dashboard": {"summary": {"mastery_average": 0.72}}}},
    )
    points = mastery_trend([(consumption, event)])
    assert points[0]["label"] == "09-05"
    assert points[0]["value"] == 72
