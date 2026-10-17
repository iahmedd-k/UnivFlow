import os
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import pytest
from datetime import datetime, timezone
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app
from app.db.database import get_db, Base
from app.auth.clerk_auth import require_current_user
from app.db.models import TimetableEntry, ClassSchedule, Course, Setting
from app.timetable.router import _validate_timetable_candidate


@pytest.fixture(scope="module")
def test_db():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)


def fake_user():
    return {"id": "test_student_user", "email": "student@example.com"}


@pytest.fixture(scope="module")
def client(test_db):
    def override_get_db():
        try:
            yield test_db
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[require_current_user] = fake_user
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


# =========================================================================
# 1. OCR Strict 100% Validation Tests (No dump / rough values)
# =========================================================================

def test_validate_timetable_candidate_valid():
    candidate = {
        "subject": "Parallel & Distributed Computing",
        "weekdays": [0, "1"],
        "start_time": "08:30",
        "end_time": "10:00",
        "teacher": "Dr. Naveed",
        "room": "C-104",
    }
    validated = _validate_timetable_candidate(candidate)
    assert validated is not None
    assert validated["subject"] == "Parallel & Distributed Computing"
    assert validated["weekdays"] == [0, 1]
    assert validated["start_time"] == "08:30"
    assert validated["end_time"] == "10:00"
    assert validated["teacher"] == "Dr. Naveed"
    assert validated["room"] == "C-104"


def test_validate_timetable_candidate_rejects_pure_room():
    assert _validate_timetable_candidate({"subject": "C-101", "weekdays": [0], "start_time": "09:00", "end_time": "10:00"}) is None
    assert _validate_timetable_candidate({"subject": "Lab 02", "weekdays": [0], "start_time": "09:00", "end_time": "10:00"}) is None
    assert _validate_timetable_candidate({"subject": "Auditorium", "weekdays": [0], "start_time": "09:00", "end_time": "10:00"}) is None


def test_validate_timetable_candidate_rejects_header_and_noise():
    assert _validate_timetable_candidate({"subject": "Air University", "weekdays": [0], "start_time": "09:00", "end_time": "10:00"}) is None
    assert _validate_timetable_candidate({"subject": "Department of Computer Science", "weekdays": [0], "start_time": "09:00", "end_time": "10:00"}) is None
    assert _validate_timetable_candidate({"subject": "ascTimetables", "weekdays": [0], "start_time": "09:00", "end_time": "10:00"}) is None
    assert _validate_timetable_candidate({"subject": "Shift-II (Evening)", "weekdays": [0], "start_time": "09:00", "end_time": "10:00"}) is None
    assert _validate_timetable_candidate({"subject": "Break", "weekdays": [0], "start_time": "09:00", "end_time": "10:00"}) is None
    assert _validate_timetable_candidate({"subject": "Monday", "weekdays": [0], "start_time": "09:00", "end_time": "10:00"}) is None


def test_validate_timetable_candidate_rejects_invalid_times():
    # End before or equal to start
    assert _validate_timetable_candidate({"subject": "Calculus", "weekdays": [0], "start_time": "10:00", "end_time": "10:00"}) is None
    assert _validate_timetable_candidate({"subject": "Calculus", "weekdays": [0], "start_time": "12:00", "end_time": "10:00"}) is None
    # Duration < 30 mins
    assert _validate_timetable_candidate({"subject": "Calculus", "weekdays": [0], "start_time": "10:00", "end_time": "10:15"}) is None
    # Duration > 4 hours
    assert _validate_timetable_candidate({"subject": "Calculus", "weekdays": [0], "start_time": "08:00", "end_time": "15:00"}) is None


def test_validate_timetable_candidate_rejects_empty_weekdays():
    assert _validate_timetable_candidate({"subject": "Calculus", "weekdays": [], "start_time": "09:00", "end_time": "10:00"}) is None
    assert _validate_timetable_candidate({"subject": "Calculus", "weekdays": [9], "start_time": "09:00", "end_time": "10:00"}) is None


# =========================================================================
# 2. Timetable Full CRUD Endpoints Tests
# =========================================================================

def test_timetable_crud_endpoints(client, test_db):
    headers = {"Authorization": "Bearer dev_token"}

    # 1. Clear all initially
    res = client.delete("/api/v1/timetable/classes/all", headers=headers)
    assert res.status_code == 200

    # 2. Create single class (POST /classes/single)
    payload_single = {
        "subject": "Linear Algebra",
        "weekdays": [1],
        "start_time": "10:00",
        "end_time": "11:30",
        "teacher": "Dr. Sarah",
        "room": "Hall 3",
        "section": "CS-A",
    }
    create_res = client.post("/api/v1/timetable/classes/single", json=payload_single, headers=headers)
    assert create_res.status_code == 200
    single_data = create_res.json()
    assert single_data["subject"] == "Linear Algebra"
    entry_id = single_data["id"]

    # 3. Read single class (GET /classes/{id})
    get_res = client.get(f"/api/v1/timetable/classes/{entry_id}", headers=headers)
    assert get_res.status_code == 200
    assert get_res.json()["id"] == entry_id

    # 4. Read all classes (GET /classes)
    list_res = client.get("/api/v1/timetable/classes", headers=headers)
    assert list_res.status_code == 200
    assert len(list_res.json()) >= 1

    # 5. Update class (PUT /classes/{id})
    update_payload = {
        "subject": "Advanced Linear Algebra",
        "weekdays": [1],
        "start_time": "10:30",
        "end_time": "12:00",
        "teacher": "Prof. Sarah Khan",
        "room": "Hall 4",
    }
    put_res = client.put(f"/api/v1/timetable/classes/{entry_id}", json=update_payload, headers=headers)
    assert put_res.status_code == 200
    assert put_res.json()["subject"] == "Advanced Linear Algebra"
    assert put_res.json()["start_time"] == "10:30"

    # 6. Delete single class (DELETE /classes/{id})
    del_res = client.delete(f"/api/v1/timetable/classes/{entry_id}", headers=headers)
    assert del_res.status_code == 200
    assert del_res.json()["deleted"] is True

    # Confirm 404 after delete
    get_del = client.get(f"/api/v1/timetable/classes/{entry_id}", headers=headers)
    assert get_del.status_code == 404


def test_timetable_batch_override(client, test_db):
    headers = {"Authorization": "Bearer dev_token"}

    # Seed an old class
    client.post("/api/v1/timetable/classes/single", json={
        "subject": "Old Stale Course",
        "weekdays": [0],
        "start_time": "08:00",
        "end_time": "09:00",
    }, headers=headers)

    # Batch save with default override=True
    new_batch = [
        {
            "subject": "Database Systems",
            "weekdays": [2],
            "start_time": "14:00",
            "end_time": "15:30",
            "teacher": "Dr. Tariq",
            "room": "Lab 1",
        },
        {
            "subject": "Operating Systems",
            "weekdays": [3],
            "start_time": "09:00",
            "end_time": "10:30",
            "teacher": "Dr. Hamza",
            "room": "C-201",
        }
    ]
    batch_res = client.post("/api/v1/timetable/classes?override=true", json=new_batch, headers=headers)
    assert batch_res.status_code == 200

    # Ensure "Old Stale Course" was wiped and only new batch exists
    all_classes = client.get("/api/v1/timetable/classes", headers=headers).json()
    subjects = [c["subject"] for c in all_classes]
    assert "Old Stale Course" not in subjects
    assert "Database Systems" in subjects
    assert "Operating Systems" in subjects


def test_dashboard_clear_timetable(client, test_db):
    headers = {"Authorization": "Bearer dev_token"}

    # Add a class
    client.post("/api/v1/timetable/classes/single", json={
        "subject": "Machine Learning",
        "weekdays": [4],
        "start_time": "11:00",
        "end_time": "12:30",
    }, headers=headers)

    # Call dashboard clear timetable endpoint
    res = client.post("/api/v1/dashboard/clear-timetable", headers=headers)
    assert res.status_code == 200
    assert res.json()["success"] is True

    # Verify classes are empty
    classes = client.get("/api/v1/timetable/classes", headers=headers).json()
    assert len(classes) == 0


# =========================================================================
# 3. Attendance CRUD Tests
# =========================================================================

def test_attendance_crud(client, test_db):
    headers = {"Authorization": "Bearer dev_token"}

    # Ensure course exists
    course = test_db.query(Course).first()
    if not course:
        course = Course(external_id="test-course-att", name="Software Engineering", course_state="ACTIVE", user_id="legacy")
        test_db.add(course)
        test_db.commit()

    # Create attendance record
    att_payload = {
        "course_id": course.id,
        "subject": "Software Engineering",
        "attended": 18,
        "total": 20,
    }
    create_res = client.post("/api/v1/attendance", json=att_payload, headers=headers)
    assert create_res.status_code == 200
    record_id = create_res.json()["id"]
    assert create_res.json()["percentage"] == 90.0

    # Update attendance record
    upd_payload = {
        "attended": 19,
        "total": 21,
    }
    put_res = client.put(f"/api/v1/attendance/{record_id}", json=upd_payload, headers=headers)
    assert put_res.status_code == 200
    assert put_res.json()["attended"] == 19
    assert put_res.json()["total"] == 21

    # Delete attendance record
    del_res = client.delete(f"/api/v1/attendance/{record_id}", headers=headers)
    assert del_res.status_code == 200
    assert del_res.json()["deleted"] is True


# =========================================================================
# 4. University Exams and Quizzes CRUD Tests
# =========================================================================

def test_university_exams_crud_and_quizzes_retired(client, test_db):
    headers = {"Authorization": "Bearer dev_token"}

    # 1. Exam CRUD
    exam_payload = {
        "title": "Midterm Examination",
        "time": "09:00 AM",
        "room": "Auditorium",
        "status": "scheduled",
    }
    create_exam_res = client.post("/api/v1/university/exams", json=exam_payload, headers=headers)
    assert create_exam_res.status_code == 200
    exam_id = create_exam_res.json()["id"]

    get_exam_res = client.get(f"/api/v1/university/exams/{exam_id}", headers=headers)
    assert get_exam_res.status_code == 200

    put_exam_res = client.put(f"/api/v1/university/exams/{exam_id}", json={"room": "Main Hall"}, headers=headers)
    assert put_exam_res.status_code == 200
    assert put_exam_res.json()["room"] == "Main Hall"

    del_exam_res = client.delete(f"/api/v1/university/exams/{exam_id}", headers=headers)
    assert del_exam_res.status_code == 200
    assert del_exam_res.json()["deleted"] is True

    # Quiz routes were intentionally retired with the dashboard quiz feature.
    quiz_payload = {
        "title": "Quiz 1 - Logic Gates",
        "time": "11:00 AM",
        "room": "C-102",
        "status": "scheduled",
    }
    create_quiz_res = client.post("/api/v1/university/quizzes", json=quiz_payload, headers=headers)
    assert create_quiz_res.status_code == 404
    assert client.get("/api/v1/university/quizzes", headers=headers).status_code == 404
    assert client.get("/api/v1/university/quizzes/1", headers=headers).status_code == 404
    assert client.put("/api/v1/university/quizzes/1", json={"title": "Quiz 1 - Advanced Gates"}, headers=headers).status_code == 404
    assert client.delete("/api/v1/university/quizzes/1", headers=headers).status_code == 404
