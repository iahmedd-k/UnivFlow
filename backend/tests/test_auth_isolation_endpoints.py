import pytest
from unittest.mock import patch
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app
from app.db.database import get_db, Base
from app.db.models import (
    Course, TimetableEntry, ClassSchedule, AttendanceRecord,
    Exam, DailyReport, Announcement, PortalSyncJob, Setting
)
from app.auth.clerk_auth import require_current_user, get_current_user_optional
from app.auth.access_gate import _key as access_setting_key
from app.core.config import settings


@pytest.fixture
def test_db():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture
def client(test_db):
    def override_get_db():
        try:
            yield test_db
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    with patch("app.main.init_db"), patch("app.main.init_supabase"), patch("app.main.init_s3"), patch("app.main.start_scheduler"):
        with TestClient(app) as test_client:
            yield test_client
    app.dependency_overrides.clear()


def test_production_unauthenticated_requests_return_401(client, monkeypatch):
    """Ensure that in production, endpoints reject unauthenticated requests with 401."""
    monkeypatch.setattr(settings, "environment", "production")

    # Documents endpoint
    resp = client.get("/api/v1/documents/daily-reports")
    assert resp.status_code == 401

    # Timetable endpoint
    resp = client.get("/api/v1/timetable/classes")
    assert resp.status_code == 401

    # Attendance endpoint
    resp = client.get("/api/v1/attendance")
    assert resp.status_code == 401

    # University exams endpoint
    resp = client.get("/api/v1/university/exams")
    assert resp.status_code == 401

    # Dashboard overview
    resp = client.get("/api/v1/dashboard/overview")
    assert resp.status_code == 401


def test_user_data_isolation_between_two_users(test_db, client, monkeypatch):
    """Verify that User B cannot see User A's timetable, exams, reports, announcements, or sync jobs."""
    monkeypatch.setattr(settings, "environment", "production")

    user_a = {"id": "user_alice", "email": "alice@test.com", "name": "Alice"}
    user_b = {"id": "user_bob", "email": "bob@test.com", "name": "Bob"}
    test_db.add(Setting(
        key=access_setting_key("grant", user_b["id"]),
        value='{"granted_at":"test-approved"}',
    ))

    # Seed User A's data
    course_a = Course(user_id="user_alice", external_id="course_a", name="Alice Course 101")
    test_db.add(course_a)
    test_db.flush()

    tt_a = TimetableEntry(
        user_id="user_alice",
        external_id="portal-tt:alice-1",
        subject="Alice CS101",
        weekday=0,
        start_time="09:00",
        end_time="10:00",
    )
    test_db.add(tt_a)

    exam_a = Exam(
        user_id="user_alice",
        external_id="exam_alice_1",
        course_id=course_a.id,
        title="Alice Final Exam",
    )
    test_db.add(exam_a)

    from datetime import datetime, timezone

    report_a = DailyReport(
        user_id="user_alice",
        report_date=datetime.now(timezone.utc),
        content="# Alice Private Report",
    )
    test_db.add(report_a)

    job_a = PortalSyncJob(
        user_id="user_alice",
        job_id="job_alice_123",
        status="completed",
        result='{"status": "success", "summary": {"cgpa": 3.9}}'
    )
    test_db.add(job_a)

    test_db.commit()

    # Authenticate as User B
    app.dependency_overrides[require_current_user] = lambda: user_b
    app.dependency_overrides[get_current_user_optional] = lambda: user_b

    # 1. Timetable: User B should see 0 classes
    tt_resp = client.get("/api/v1/timetable/classes")
    assert tt_resp.status_code == 200
    assert len(tt_resp.json()) == 0

    # 2. Daily reports: User B should see 0 reports
    rep_resp = client.get("/api/v1/documents/daily-reports")
    assert rep_resp.status_code == 200
    assert len(rep_resp.json()) == 0

    # 3. Specific report of User A: User B must get 404
    rep_one = client.get(f"/api/v1/documents/daily-reports/{report_a.id}")
    assert rep_one.status_code == 404

    # 4. University exams: User B should see 0 exams
    exam_resp = client.get("/api/v1/university/exams")
    assert exam_resp.status_code == 200
    assert len(exam_resp.json()) == 0

    # 5. Portal sync job of User A: User B must get 404
    job_resp = client.get(f"/api/v1/portal/sync/{job_a.job_id}")
    assert job_resp.status_code == 404

    # 6. Auto-approval config: User B cannot access User A's config
    auto_resp = client.get(f"/api/v1/assignments/auto-approval/config?user_id=11111111-1111-1111-1111-111111111111")
    assert auto_resp.status_code == 403


def test_timetable_wipe_does_not_affect_other_users(test_db, client, monkeypatch):
    """Ensure that wiping or overriding timetable entries does not delete other users' entries."""
    monkeypatch.setattr(settings, "environment", "production")

    user_a = {"id": "user_alice", "email": "alice@test.com", "name": "Alice"}
    user_b = {"id": "user_bob", "email": "bob@test.com", "name": "Bob"}

    # Seed User A's timetable
    tt_a = TimetableEntry(
        user_id="user_alice",
        external_id="portal-tt:alice-keep",
        subject="Alice Discrete Math",
        weekday=1,
        start_time="11:00",
        end_time="12:00",
    )
    test_db.add(tt_a)
    test_db.add(Setting(
        key=access_setting_key("grant", "user_bob"),
        value='{"granted_at":"test-approved"}',
    ))
    test_db.commit()

    # User B overrides all their timetable classes
    app.dependency_overrides[require_current_user] = lambda: user_b
    app.dependency_overrides[get_current_user_optional] = lambda: user_b

    # User B saves classes with override=true
    resp = client.post("/api/v1/timetable/classes?override=true", json=[{
        "subject": "Bob Physics",
        "weekdays": [2],
        "start_time": "14:00",
        "end_time": "15:00",
    }])
    assert resp.status_code == 200

    # User A's entry must still exist intact!
    entry = test_db.query(TimetableEntry).filter(TimetableEntry.external_id == "portal-tt:alice-keep").first()
    assert entry is not None
    assert entry.user_id == "user_alice"
