import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.dashboard.router import get_attendance_summary
from app.db.models.common import Base
from app.db.models.courses import Course
from app.db.models.schedules import AttendanceRecord, TimetableEntry
from app.portal.router import _attendance_rows


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()
    engine.dispose()


def test_attendance_parser_uses_class_counts_not_hour_columns():
    table = [
        ["Sr.NO", "Subject Name", "Total", "Total Hrs", "ATTS", "ABS", "ATT Hrs", "ABS Hrs", "Attendance %"],
        ["1", "Course A", "11", "32", "6", "5", "18", "14", "54.55"],
        ["2", "Course B", "9", "27", "0", "9", "0", "27", "0"],
    ]

    rows = _attendance_rows([table])

    assert rows == [
        {"subject": "Course A", "attended": 6, "total": 11, "percentage": 54.55},
        {"subject": "Course B", "attended": 0, "total": 9, "percentage": 0.0},
    ]


def test_percentage_only_attendance_does_not_invent_class_counts():
    rows = _attendance_rows([[["Course", "Attendance %"], ["Course C", "82.5"]]])

    assert rows == [
        {"subject": "Course C", "attended": None, "total": None, "percentage": 82.5}
    ]


def test_attendance_summary_uses_cumulative_counts_and_weekly_schedule(db_session):
    course = Course(
        id=1,
        user_id="test-user",
        external_id="attendance-course",
        name="F-26-Computer Organization and Assembly Language-1971",
    )
    db_session.add(course)
    db_session.add(
        AttendanceRecord(
            user_id="test-user",
            external_id="attendance-record",
            course_id=course.id,
            subject=course.name,
            attended=6,
            total=11,
            percentage=54.55,
        )
    )
    db_session.add_all([
        TimetableEntry(
            user_id="test-user",
            external_id="timetable-monday",
            subject="Computer Organization and Assembly Language",
            weekday=0,
            start_time="09:00",
            end_time="10:00",
        ),
        TimetableEntry(
            user_id="test-user",
            external_id="timetable-wednesday",
            subject="Computer Organization and Assembly Language",
            weekday=2,
            start_time="09:00",
            end_time="10:00",
        ),
    ])
    db_session.commit()

    response = get_attendance_summary(db_session, user={"id": "test-user"})

    assert response["overall_attendance"] == 54.55
    assert response["counted_attended"] == 6
    assert response["counted_held"] == 11
    assert response["per_course"][0]["classes_per_week"] == 2
    assert response["per_course"][0]["registration_date"] is None
    assert response["per_course"][0]["planned_since_registration"] is None


def test_attendance_summary_matches_full_portal_attendance_table(db_session):
    rows = [
        ("F-26-Computer Organization and Assembly Language-1971", 6, 11, 54.55),
        ("F-26-Deep Learning Lab-773", 4, 5, 80.0),
        ("F-26-Software Design and Architecture Lab-769", 6, 6, 100.0),
        ("F-26-Deep Learning-772", 9, 11, 81.82),
        ("F-26-Computer Organization and Assembly Language Lab-1972", 3, 5, 60.0),
        ("F-26-Parallel and Distributed Computing Lab-763", 5, 5, 100.0),
        ("F-26-Parallel and Distributed Computing-762", 8, 11, 72.73),
        ("F-26-Professional Practices-765", 7, 11, 63.64),
        ("F-26-Entrepreneurship-767", 8, 10, 80.0),
        ("F-26-Software Design and Architecture-768", 6, 9, 66.67),
    ]
    portal_table = [[
        "Sr.NO", "Subject Name", "Total", "Total Hrs", "ATTS", "ABS",
        "ATT Hrs", "ABS Hrs", "Attendance %",
    ]]
    for index, (subject, attended, total, percentage) in enumerate(rows, start=1):
        absent = total - attended
        portal_table.append([
            str(index),
            subject,
            str(total),
            str(total * 3),
            str(attended),
            str(absent),
            str(attended * 3),
            str(absent * 3),
            str(percentage),
        ])

    parsed_rows = _attendance_rows([portal_table])
    assert len(parsed_rows) == 10
    assert [
        (row["subject"], row["attended"], row["total"], row["percentage"])
        for row in parsed_rows
    ] == [(subject, attended, total, percentage) for subject, attended, total, percentage in rows]

    for index, parsed in enumerate(parsed_rows, start=1):
        subject = parsed["subject"]
        course = Course(id=index, user_id="test-user", external_id=f"portal-course-{index}", name=subject)
        db_session.add(course)
        db_session.add(
            AttendanceRecord(
                user_id="test-user",
                external_id=f"portal-attendance-{index}",
                course_id=index,
                subject=subject,
                attended=parsed["attended"],
                total=parsed["total"],
                percentage=parsed["percentage"],
            )
        )
    db_session.commit()

    response = get_attendance_summary(db_session, user={"id": "test-user"})
    by_subject = {row["subject"]: row for row in response["per_course"]}

    assert response["counted_attended"] == 62
    assert response["counted_held"] == 84
    assert response["overall_attendance"] == 73.81
    assert len(response["per_course"]) == 10
    for subject, attended, total, percentage in rows:
        assert by_subject[subject]["attended"] == attended
        assert by_subject[subject]["total"] == total
        assert by_subject[subject]["absent"] == total - attended
        assert by_subject[subject]["percentage"] == percentage


def test_percentage_only_record_is_not_counted_as_a_class_total(db_session):
    course = Course(id=1, user_id="test-user", external_id="percentage-course", name="Course D")
    db_session.add(course)
    db_session.add(
        AttendanceRecord(
            user_id="test-user",
            external_id="percentage-record",
            course_id=course.id,
            subject=course.name,
            attended=None,
            total=None,
            percentage=82.5,
        )
    )
    db_session.commit()

    response = get_attendance_summary(db_session, user={"id": "test-user"})
    row = response["per_course"][0]

    assert row["percentage"] == 82.5
    assert row["attended"] is None
    assert row["held"] is None
    assert row["absent"] is None
    assert response["overall_attendance"] is None
    assert response["counted_held"] == 0


def test_legacy_portal_placeholder_total_is_not_reported_as_verified_counts(db_session):
    course = Course(id=1, user_id="test-user", external_id="portal-attendance-course", name="Course E")
    db_session.add(course)
    db_session.add(
        AttendanceRecord(
            user_id="test-user",
            external_id="portal-attendance:legacy-course",
            course_id=course.id,
            subject=course.name,
            attended=55,
            total=100,
            percentage=54.55,
        )
    )
    db_session.commit()

    response = get_attendance_summary(db_session, user={"id": "test-user"})
    row = response["per_course"][0]

    assert row["percentage"] == 54.55
    assert row["attended"] is None
    assert row["held"] is None
    assert row["absent"] is None
    assert response["overall_attendance"] is None
    assert response["counted_attended"] == 0
    assert response["counted_held"] == 0
