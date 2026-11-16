from types import SimpleNamespace
from unittest.mock import MagicMock

import app.api.endpoints.portal as portal


def test_sync_without_attendance_records_is_partial(monkeypatch):
    db = MagicMock()
    db.bind = None
    report = {
        "tables": [["Course", "Grade"], ["Calculus", "A"]],
        "text": "Course Grade Calculus A",
        "title": "Grades",
    }

    monkeypatch.setattr(portal, "SessionLocal", lambda: db)
    monkeypatch.setattr(portal, "is_redis_configured", lambda: False)
    monkeypatch.setattr(
        portal,
        "_portal_setting",
        lambda _db, _uid, key: SimpleNamespace(value="https://portal.example")
        if key == "university_portal_url"
        else None,
    )
    monkeypatch.setattr(portal, "_profile_dir", lambda _uid: portal.Path("."))
    monkeypatch.setattr(
        portal,
        "_scrape_report_thread",
        lambda *_args: {
            "status": "success",
            "reports": [
                {"current_url": "https://portal.example/grades", "report": report}
            ],
        },
    )
    monkeypatch.setattr(
        portal, "_ingest_report_data", lambda *_args, **_kwargs: ([], [], {"cgpa": 3.5})
    )
    monkeypatch.setattr(portal, "_set_portal_setting", lambda *_args: None)

    result = portal._sync_portal_for_user("test-user")

    assert result["status"] == "partial"
    assert result["attendance"] == []
    assert "no attendance records were found" in result["message"].lower()
    assert "left unchanged" in result["message"].lower()
