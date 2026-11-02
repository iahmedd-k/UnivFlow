from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db.database import Base
from app.db.models import ClassSchedule, Course
from app.services.classroom_sync import ClassroomSyncService


def test_classroom_schedule_sync_updates_existing_external_id():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    user_id = "schedule-sync-user"
    course = Course(id=1, external_id="classroom-course", name="Test Course", user_id=user_id)
    due_at = datetime(2026, 10, 26, 18, 59, tzinfo=timezone.utc)
    schedule = ClassSchedule(
        user_id=user_id,
        external_id="classroom:classroom-course:work-1",
        course_id=1,
        subject="Old assignment title",
        date=due_at - timedelta(days=1),
        start_time=due_at - timedelta(days=1),
        end_time=due_at,
        room="Online",
        status="scheduled",
    )
    db.add_all([course, schedule])
    db.commit()
    other_user_course = Course(
        id=2,
        external_id="classroom-course",
        name="Other User Course",
        user_id="other-schedule-sync-user",
    )
    db.add(other_user_course)
    db.add(
        ClassSchedule(
            user_id="other-schedule-sync-user",
            external_id="classroom:classroom-course:work-1",
            course_id=2,
            subject="Other user's assignment",
            date=due_at,
            start_time=due_at,
            end_time=due_at + timedelta(hours=1),
            status="scheduled",
        )
    )
    db.commit()

    service = ClassroomSyncService.__new__(ClassroomSyncService)
    service.db = db
    service.user_id = user_id
    service.service = MagicMock()
    service.service.courses.return_value.courseWork.return_value.list.return_value.execute.return_value = {
        "courseWork": [
            {
                "id": "work-1",
                "title": "Updated assignment title",
                "dueDate": {"year": 2026, "month": 10, "day": 26},
                "dueTime": {"hours": 18, "minutes": 59},
            }
        ]
    }
    service._execute_with_rate_limit = lambda call: call()

    assert service._sync_schedule({"id": "classroom-course"}) == 0
    assert service._sync_schedule({"id": "classroom-course"}) == 0

    saved = db.query(ClassSchedule).filter_by(
        user_id=user_id,
        external_id="classroom:classroom-course:work-1",
    ).one()
    assert db.query(ClassSchedule).filter_by(user_id=user_id).count() == 1
    assert saved.subject == "Updated assignment title"
    assert saved.date.replace(tzinfo=timezone.utc) == due_at
    assert db.query(ClassSchedule).filter_by(external_id=saved.external_id).count() == 2

    db.close()
    engine.dispose()
