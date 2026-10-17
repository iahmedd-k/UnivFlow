from datetime import datetime, timedelta, timezone
import json
import pytest
from fastapi.testclient import TestClient

from app.main import app as fastapi_app
from app.db.database import get_db, Base
from app.auth.clerk_auth import require_current_user
from app.db.models import Assignment, AssignmentSolution, Setting, AssignmentStatus, Course
import app.db.models  # noqa: F401

client = TestClient(fastapi_app)


from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

SQLALCHEMY_DATABASE_URL = "sqlite:///:memory:"
engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False})
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@pytest.fixture
def db_session():
    Base.metadata.create_all(bind=engine)
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)


def fake_user():
    return {"id": "test_student_user", "email": "student@example.com"}


def test_stale_and_draft_assignments_not_in_active_crew_runs(db_session):
    def override_get_db():
        yield db_session

    fastapi_app.dependency_overrides[get_db] = override_get_db
    fastapi_app.dependency_overrides[require_current_user] = fake_user

    try:
        # Create course
        course = Course(name="Distributed Systems", user_id="test_student_user", external_id="ext_course_101")
        db_session.add(course)
        db_session.commit()

        # 1. Old assignment in DRAFT with an unvalidated solution from days ago
        draft_assign = Assignment(
            title="Lab Task 1 Old",
            course_id=course.id,
            user_id="test_student_user",
            external_id="ext_assign_1",
            status=AssignmentStatus.DRAFT,
        )
        db_session.add(draft_assign)
        db_session.commit()

        old_sol = AssignmentSolution(
            assignment_id=draft_assign.id,
            ai_provider="claude_browser",
            generated_at=datetime.now(timezone.utc) - timedelta(days=2),
            validated_content=None,
            validation_errors=None,
        )
        db_session.add(old_sol)
        db_session.commit()

        # 2. Assignment in GENERATING but stale (> 25 mins ago)
        stale_generating = Assignment(
            title="Stale Generating Assignment",
            course_id=course.id,
            user_id="test_student_user",
            external_id="ext_assign_2",
            status=AssignmentStatus.GENERATING,
        )
        db_session.add(stale_generating)
        db_session.commit()

        stale_sol = AssignmentSolution(
            assignment_id=stale_generating.id,
            ai_provider="claude_browser",
            generated_at=datetime.now(timezone.utc) - timedelta(minutes=30),
            validated_content=None,
            validation_errors=None,
        )
        db_session.add(stale_sol)
        db_session.commit()

        # 3. Freshly generating assignment (within last 5 minutes)
        fresh_generating = Assignment(
            title="Active Fresh Assignment",
            course_id=course.id,
            user_id="test_student_user",
            external_id="ext_assign_3",
            status=AssignmentStatus.GENERATING,
        )
        db_session.add(fresh_generating)
        db_session.commit()

        fresh_sol = AssignmentSolution(
            assignment_id=fresh_generating.id,
            ai_provider="claude_browser",
            generated_at=datetime.now(timezone.utc) - timedelta(minutes=2),
            validated_content=None,
            validation_errors=None,
        )
        db_session.add(fresh_sol)

        progress_setting = Setting(
            key=f"assignment_crew_progress_{fresh_generating.id}",
            value=json.dumps({
                "current_step": 2,
                "total_steps": 5,
                "step_title": "Synthesizing Solution",
                "detail": "Working on lab tasks",
                "updated_at": datetime.now(timezone.utc).isoformat(),
            })
        )
        db_session.add(progress_setting)
        db_session.commit()

        # Fetch overview directly
        from app.dashboard.router import get_dashboard_overview, dismiss_active_crew_run
        data = get_dashboard_overview(since=None, db=db_session, user=fake_user())

        active_runs = data.get("ai_agent_hub", {}).get("active_crew_runs", [])
        active_ids = [r["assignment_id"] for r in active_runs]

        # Draft assignment with old solution must NOT be in active runs
        assert draft_assign.id not in active_ids

        # Stale generating assignment must be auto-recovered and NOT in active runs
        assert stale_generating.id not in active_ids

        # Refresh stale_generating from DB to verify auto-recovery to DRAFT
        db_session.refresh(stale_generating)
        assert stale_generating.status == AssignmentStatus.DRAFT

        # Fresh generating assignment MUST be in active runs
        assert fresh_generating.id in active_ids

        # Test dismiss endpoint on fresh run
        dismiss_resp = dismiss_active_crew_run(assignment_id=fresh_generating.id, db=db_session, user=fake_user())
        assert dismiss_resp["success"] is True

        db_session.refresh(fresh_generating)
        assert fresh_generating.status == AssignmentStatus.DRAFT

        # Overview should now have 0 active runs
        data_after = get_dashboard_overview(since=None, db=db_session, user=fake_user())
        active_ids_after = [r["assignment_id"] for r in data_after.get("ai_agent_hub", {}).get("active_crew_runs", [])]
        assert fresh_generating.id not in active_ids_after

    finally:
        fastapi_app.dependency_overrides.pop(require_current_user, None)
        fastapi_app.dependency_overrides.pop(get_db, None)
