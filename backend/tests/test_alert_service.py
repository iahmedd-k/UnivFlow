import pytest
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from unittest.mock import patch

from app.db.models.common import Base
from app.db.models.courses import Course
from app.db.models.schedules import AttendanceRecord, TimetableEntry
from app.db.models.assignments import Assignment, Submission
from app.db.models.enums import CourseworkState, SubmissionState
from app.db.models.notifications import Notification, NotificationStatus
from app.services.alert_service import (
    AlertService,
    normalize_subject_name,
    is_lab_subject,
    match_attendance_to_timetable,
    calculate_attendance_recovery,
    build_attendance_warning_email,
    build_timetable_reminder_email,
    build_assignment_deadline_email,
)


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


def test_calculate_attendance_recovery():
    # 15/24 = 62.5%. To reach 75%, need 12 consecutive classes: (15+12)/(24+12) = 27/36 = 75.0%
    assert calculate_attendance_recovery(15, 24, 75.0) == 12
    # Already above threshold (18/20 = 90%)
    assert calculate_attendance_recovery(18, 20, 75.0) == 0
    # Zero held classes
    assert calculate_attendance_recovery(0, 0, 75.0) == 0


def test_normalize_subject_name():
    assert normalize_subject_name("F-26-Computer Organization and Assembly Language-1971") == "computer organization and assembly language"
    assert normalize_subject_name("F-26-Deep Learning Lab-773") == "deep learning lab"
    assert normalize_subject_name("Software Design and Architecture") == "software design and architecture"


def test_is_lab_subject():
    assert is_lab_subject("Deep Learning Lab") is True
    assert is_lab_subject("Parallel and Distributed Computing") is False
    assert is_lab_subject("F-26-COAL Lab-1972") is True


def test_match_attendance_to_timetable(db_session):
    course1 = Course(id=1, external_id="c1", name="COAL")
    course2 = Course(id=2, external_id="c2", name="COAL Lab")
    db_session.add_all([course1, course2])
    db_session.commit()

    att_theory = AttendanceRecord(id=1, external_id="a1", course_id=1, subject="F-26-Computer Organization and Assembly Language-1971", percentage=54.5, attended=55, total=100)
    att_lab = AttendanceRecord(id=2, external_id="a2", course_id=2, subject="F-26-Computer Organization and Assembly Language Lab-1972", percentage=60.0, attended=60, total=100)
    db_session.add_all([att_theory, att_lab])
    db_session.commit()

    records = [att_theory, att_lab]
    matched_th = match_attendance_to_timetable("Computer Organization and Assembly Language", records)
    assert matched_th is not None
    assert matched_th.id == 1

    matched_lab = match_attendance_to_timetable("Computer Organization and Assembly Language Lab", records)
    assert matched_lab is not None
    assert matched_lab.id == 2


@patch("app.services.alert_service.send_email", return_value=True)
def test_attendance_warning_generation(mock_send, db_session):
    course = Course(id=1, external_id="c1", name="Professional Practices")
    db_session.add(course)
    db_session.commit()

    att = AttendanceRecord(
        id=1, external_id="a1", course_id=1,
        subject="F-26-Professional Practices-765",
        percentage=63.64, attended=14, total=22
    )
    db_session.add(att)

    tt = TimetableEntry(
        id=1, external_id="tt1", subject="Professional Practices",
        weekday=1, start_time="14:00", end_time="14:50", room="Main Campus", teacher="Mr. Qadeer Yasin"
    )
    db_session.add(tt)
    db_session.commit()

    service = AlertService(db_session)
    target_tuesday = date(2026, 10, 13)
    alerts = service.generate_daily_attendance_warnings(
        user_id="dev_student_user",
        target_date=target_tuesday,
        threshold=75.0,
        send_immediately=True
    )

    assert len(alerts) == 1
    assert alerts[0]["course"] == "Professional Practices"
    assert alerts[0]["percentage"] == 63.64
    assert alerts[0]["recovery_needed"] > 0
    assert alerts[0]["status"] == "sent"
    mock_send.assert_called_once()


@patch("app.services.alert_service.send_email", return_value=True)
def test_attendance_edge_case_zero_total_classes(mock_send, db_session):
    # Edge case: Course has 0 held classes recorded (start of term)
    course = Course(id=1, external_id="c1", name="Artificial Intelligence")
    db_session.add(course)

    att = AttendanceRecord(
        id=1, external_id="a1", course_id=1,
        subject="F-26-Artificial Intelligence-100",
        percentage=0.0, attended=0, total=0
    )
    db_session.add(att)

    tt = TimetableEntry(
        id=1, external_id="tt1", subject="Artificial Intelligence",
        weekday=1, start_time="10:00", end_time="10:50", room="Lab 1"
    )
    db_session.add(tt)
    db_session.commit()

    service = AlertService(db_session)
    alerts = service.generate_daily_attendance_warnings(
        user_id="dev_student_user",
        target_date=date(2026, 10, 13),
        threshold=75.0,
        send_immediately=True
    )
    # Zero held classes should NOT trigger an alert
    assert len(alerts) == 0
    mock_send.assert_not_called()


@patch("app.services.alert_service.send_email", return_value=True)
def test_attendance_edge_case_multi_slot_deduplication(mock_send, db_session):
    # Edge case: Student has 2 slots of same subject on same day
    course = Course(id=1, external_id="c1", name="Database Systems")
    db_session.add(course)

    att = AttendanceRecord(
        id=1, external_id="a1", course_id=1,
        subject="F-26-Database Systems-200",
        percentage=50.0, attended=5, total=10
    )
    db_session.add(att)

    tt1 = TimetableEntry(
        id=1, external_id="tt1", subject="Database Systems",
        weekday=2, start_time="09:00", end_time="09:50", room="Room 101"
    )
    tt2 = TimetableEntry(
        id=2, external_id="tt2", subject="Database Systems",
        weekday=2, start_time="10:00", end_time="10:50", room="Room 101"
    )
    db_session.add_all([tt1, tt2])
    db_session.commit()

    service = AlertService(db_session)
    alerts = service.generate_daily_attendance_warnings(
        user_id="dev_student_user",
        target_date=date(2026, 10, 14), # Wednesday
        threshold=75.0,
        send_immediately=True
    )
    # Only 1 warning generated, not 2
    assert len(alerts) == 1
    mock_send.assert_called_once()


@patch("app.services.alert_service.send_email", return_value=True)
def test_timetable_10min_reminder(mock_send, db_session):
    tt = TimetableEntry(
        id=1, external_id="tt1", subject="Deep Learning",
        weekday=0, start_time="17:00", end_time="17:50", room="Hall B", teacher="Mr. Mohabbat Ali"
    )
    db_session.add(tt)
    db_session.commit()

    service = AlertService(db_session)
    simulated_now = datetime(2026, 10, 12, 16, 50, 0, tzinfo=ZoneInfo("Asia/Karachi"))

    reminders = service.generate_upcoming_class_reminders(
        user_id="dev_student_user",
        target_dt=simulated_now,
        lookahead_minutes=10,
        window_tolerance=2,
        send_immediately=True
    )

    assert len(reminders) == 1
    assert reminders[0]["course"] == "Deep Learning"
    assert reminders[0]["minutes_left"] == 10
    assert reminders[0]["status"] == "sent"
    mock_send.assert_called_once()


@patch("app.services.alert_service.send_email", return_value=True)
def test_timetable_edge_case_multi_slot_lab_continuation(mock_send, db_session):
    # Edge case: 2 consecutive slots of the same lab:
    # Slot 1: 08:30 - 09:20
    # Slot 2: 09:20 - 10:10 (continuation)
    tt1 = TimetableEntry(
        id=1, external_id="tt1", subject="COAL Lab",
        weekday=0, start_time="08:30", end_time="09:20", room="Lab 3"
    )
    tt2 = TimetableEntry(
        id=2, external_id="tt2", subject="COAL Lab",
        weekday=0, start_time="09:20", end_time="10:10", room="Lab 3"
    )
    db_session.add_all([tt1, tt2])
    db_session.commit()

    service = AlertService(db_session)
    # At 09:10 (10 mins before slot 2 starts, but slot 1 is actively ongoing):
    simulated_now = datetime(2026, 10, 12, 9, 10, 0, tzinfo=ZoneInfo("Asia/Karachi"))

    reminders = service.generate_upcoming_class_reminders(
        user_id="dev_student_user",
        target_dt=simulated_now,
        lookahead_minutes=10,
        window_tolerance=2,
        send_immediately=True
    )
    # Should skip alerting mid-session for the continuation slot
    assert len(reminders) == 0
    mock_send.assert_not_called()


@patch("app.services.alert_service.send_email", return_value=True)
def test_assignment_deadline_edge_cases(mock_send, db_session):
    course = Course(id=1, external_id="c1", name="Software Engineering")
    db_session.add(course)
    db_session.commit()

    now_pkt = datetime(2026, 10, 12, 10, 0, 0, tzinfo=ZoneInfo("Asia/Karachi"))

    # 1. Active unsubmitted assignment due in 18 hours (should alert)
    a1 = Assignment(
        id=1, external_id="a1", course_id=1,
        title="SRS Document Lab 3",
        work_type="ASSIGNMENT",
        state=CourseworkState.PUBLISHED,
        submission_state=SubmissionState.CREATED,
        due_at=now_pkt + timedelta(hours=18),
        url="https://classroom.google.com/c/1/a/1"
    )

    # 2. Assignment ALREADY TURNED IN (edge case: should NOT alert)
    a2 = Assignment(
        id=2, external_id="a2", course_id=1,
        title="SRS Draft",
        work_type="ASSIGNMENT",
        state=CourseworkState.PUBLISHED,
        submission_state=SubmissionState.TURNED_IN,
        due_at=now_pkt + timedelta(hours=5),
    )

    # 3. Assignment with NO DUE DATE (edge case: should NOT alert)
    a3 = Assignment(
        id=3, external_id="a3", course_id=1,
        title="Optional Reading",
        work_type="MATERIAL",
        state=CourseworkState.PUBLISHED,
        due_at=None,
    )

    db_session.add_all([a1, a2, a3])
    db_session.commit()

    service = AlertService(db_session)
    alerts = service.generate_upcoming_assignment_reminders(
        user_id="dev_student_user",
        target_dt=now_pkt,
        lookahead_hours=24,
        send_immediately=True
    )

    assert len(alerts) == 1
    assert alerts[0]["title"] == "SRS Document Lab 3"
    assert alerts[0]["status"] == "sent"
    mock_send.assert_called_once()


def test_email_builders_clean_typography():
    html_att, text_att = build_attendance_warning_email(
        course_name="Computer Organization and Assembly Language",
        percentage=54.55,
        attended=12,
        total=22,
        class_time="12:00 - 12:50",
        room="Main Campus",
        teacher="Mr. Ali Arshad",
        threshold=75.0,
    )
    # Check institutional branding
    assert "Uniflow Academic Suite" in html_att
    assert "Academic Advisory" in html_att
    assert "54.5%" in html_att
    assert "Mr. Ali Arshad" in html_att
    # Zero cheap tacky emojis in text
    assert "⚠️" not in text_att
    assert "🔔" not in text_att
    assert "[Uniflow Academic Advisory]" in text_att

    html_tt, text_tt = build_timetable_reminder_email(
        course_name="Software Design and Architecture",
        start_time="15:00",
        end_time="15:50",
        room="Room 304",
        teacher="Dr. Bilal Ahmad",
        minutes_left=10,
    )
    assert "Room 304" in html_tt
    assert "Dr. Bilal Ahmad" in html_tt
    assert "⏱️" not in text_tt
    assert "📍" not in text_tt
    assert "[Uniflow Schedule Notice]" in text_tt

    html_gcr, text_gcr = build_assignment_deadline_email(
        assignment_title="Lab 4: Binary Search Trees",
        course_name="Data Structures",
        due_datetime_str="Tuesday, 13 Oct 2026 at 11:59 PM",
        time_remaining_str="~14 hours",
        classroom_url="https://classroom.google.com/test",
        is_quiz=False,
    )
    assert "Lab 4: Binary Search Trees" in html_gcr
    assert "Data Structures" in html_gcr
    assert "View in Google Classroom" in html_gcr
    assert "[Uniflow Deadline Notice]" in text_gcr
