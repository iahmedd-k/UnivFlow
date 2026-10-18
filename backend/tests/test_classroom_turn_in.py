from io import BytesIO

import pytest
from fastapi import HTTPException
from starlette.datastructures import Headers, UploadFile

from app.classroom.router import _attach_submission_files, _upload_submission_files


class FakeDriveDocsService:
    def __init__(self, result=None, error=None):
        self.result = result
        self.error = error
        self.uploads = []
        self.removed_public_shares = []

    def upload_file(self, name, content, mime_type):
        self.uploads.append((name, content, mime_type))
        if self.error:
            raise self.error
        return self.result

    def remove_public_sharing(self, file_id):
        self.removed_public_shares.append(file_id)
        return True


class FakeExecution:
    def __init__(self, result=None, error=None):
        self.result = result
        self.error = error

    def execute(self):
        if self.error:
            raise self.error
        return self.result


class FakeStudentSubmissions:
    def __init__(self, modify_error=None, turn_in_error=None, initial_state="NEW", initial_attachments=None):
        self.modify_error = modify_error
        self.turn_in_error = turn_in_error
        self.state = initial_state
        self.attachments = initial_attachments or []
        self.modify_arguments = None
        self.turn_in_arguments = None
        self.reclaim_arguments = None

    def list(self, **kwargs):
        assert kwargs["userId"] == "me"
        return FakeExecution({
            "studentSubmissions": [{
                "id": "submission-123",
                "state": self.state,
                "assignmentSubmission": {
                    "attachments": self.attachments,
                },
            }]
        })

    def modifyAttachments(self, **kwargs):
        self.modify_arguments = kwargs
        return FakeExecution({"id": "submission-123"}, self.modify_error)

    def turnIn(self, **kwargs):
        self.turn_in_arguments = kwargs
        if not self.turn_in_error:
            self.state = "TURNED_IN"
        return FakeExecution({}, self.turn_in_error)

    def reclaim(self, **kwargs):
        self.reclaim_arguments = kwargs
        self.state = "RECLAIMED_BY_STUDENT"
        return FakeExecution({"state": "RECLAIMED_BY_STUDENT"})


class FakeClassroomService:
    def __init__(self, modify_error=None, turn_in_error=None, initial_state="NEW", initial_attachments=None):
        self.submissions = FakeStudentSubmissions(modify_error, turn_in_error, initial_state, initial_attachments)
        self.service = self

    def courses(self):
        return self

    def courseWork(self):
        return self

    def studentSubmissions(self):
        return self.submissions


def make_upload(filename="report.pdf"):
    return UploadFile(
        filename=filename,
        file=BytesIO(b"assignment file bytes"),
        headers=Headers({"content-type": "application/pdf"}),
    )


@pytest.mark.asyncio
async def test_upload_submission_files_returns_google_drive_ids():
    docs_service = FakeDriveDocsService({"id": "drive-file-123"})

    file_ids = await _upload_submission_files(docs_service, [make_upload()])

    assert file_ids == ["drive-file-123"]
    assert docs_service.uploads == [
        ("report.pdf", b"assignment file bytes", "application/pdf")
    ]


@pytest.mark.asyncio
async def test_upload_submission_files_fails_if_drive_returns_no_file_id():
    docs_service = FakeDriveDocsService(None)

    with pytest.raises(HTTPException) as error:
        await _upload_submission_files(docs_service, [make_upload()])

    assert error.value.status_code == 502
    assert "did not return a file ID" in error.value.detail


def test_attach_submission_files_uses_student_submission_and_requested_ids():
    classroom = FakeClassroomService()

    submission_id = _attach_submission_files(
        classroom, "course-1", "assignment-1", ["cover-doc", "drive-file-123"]
    )

    assert submission_id == "submission-123"
    assert classroom.submissions.modify_arguments["id"] == "submission-123"
    assert classroom.submissions.modify_arguments["body"] == {
        "addAttachments": [
            {"driveFile": {"id": "cover-doc"}},
            {"driveFile": {"id": "drive-file-123"}},
        ]
    }


def test_attach_submission_files_reports_classroom_attachment_failure():
    classroom = FakeClassroomService(modify_error=RuntimeError("Classroom unavailable"))

    with pytest.raises(HTTPException) as error:
        _attach_submission_files(classroom, "course-1", "assignment-1", ["drive-file-123"])

    assert error.value.status_code == 502
    assert error.value.detail == "Failed to attach files to Google Classroom"


def test_execute_quick_turn_in_attaches_doc_and_zip(monkeypatch):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from app.db.database import Base
    from app.db.models import Course, Assignment, AssignmentSolution, Submission, SubmissionState
    from app.classroom.router import execute_quick_turn_in
    import json

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    db = Session()

    course = Course(id=1, external_id="course-ext-1", name="Parallel Computing", user_id="test_user")
    assignment = Assignment(id=1, external_id="asgn-ext-1", course_id=1, title="Lab 1 - OpenMP", user_id="test_user")
    solution = AssignmentSolution(
        id=1,
        assignment_id=1,
        validated_content="```python\n# File: task_1.py\nprint('Hello OpenMP')\n```"
    )
    db.add_all([course, assignment, solution])
    db.commit()

    fake_classroom = FakeClassroomService()
    fake_docs = FakeDriveDocsService(result={"id": "zip-file-drive-id"})
    fake_docs.share_file = lambda *args, **kwargs: None

    import sys
    classroom_mod = sys.modules["app.classroom.router"]
    monkeypatch.setattr(classroom_mod, "get_classroom_service", lambda _db, user_id: fake_classroom)
    monkeypatch.setattr(classroom_mod, "get_google_docs_service", lambda _db, user_id: fake_docs)
    monkeypatch.setattr(
        "app.services.ai_solution.export_solution_to_google_doc",
        # Match the real exporter response shape; quick-turn-in must consume doc_id.
        lambda _db, _asgn, _content, user_id: {"doc_id": "doc-drive-id-123", "doc_url": "https://docs.google.com/..."}
    )

    res = execute_quick_turn_in(db, assignment.id, "test_user")

    assert res["success"] is True
    assert res["google_doc_id"] == "doc-drive-id-123"
    assert res["zip_file_id"] == "zip-file-drive-id"
    assert "Deliverables.zip" in res["zip_filename"]
    assert fake_docs.removed_public_shares == ["doc-drive-id-123", "zip-file-drive-id"]

    # Verify both Google Doc and ZIP were attached
    assert fake_classroom.submissions.modify_arguments["id"] == "submission-123"
    attached = fake_classroom.submissions.modify_arguments["body"]["addAttachments"]
    assert len(attached) == 2
    assert attached[0]["driveFile"]["id"] == "doc-drive-id-123"
    assert attached[1]["driveFile"]["id"] == "zip-file-drive-id"

    # Verify turnIn was executed with required empty JSON body
    assert fake_classroom.submissions.turn_in_arguments["id"] == "submission-123"
    assert fake_classroom.submissions.turn_in_arguments["body"] == {}

    # Verify assignment submission state updated
    db.refresh(assignment)
    assert assignment.submission_state == SubmissionState.TURNED_IN


def test_attach_submission_files_does_not_unsubmit_already_turned_in_work():
    classroom = FakeClassroomService(initial_state="TURNED_IN")

    submission_id, state = _attach_submission_files(
        classroom, "course-1", "assignment-1", ["doc-1"], return_state=True
    )

    assert submission_id == "submission-123"
    assert state == "TURNED_IN"
    assert classroom.submissions.reclaim_arguments is None
    assert classroom.submissions.modify_arguments["id"] == "submission-123"
    assert classroom.submissions.modify_arguments["body"] == {
        "addAttachments": [{"driveFile": {"id": "doc-1"}}]
    }


def test_attach_submission_files_skips_already_attached_files():
    classroom = FakeClassroomService(
        initial_attachments=[{"driveFile": {"id": "doc-1"}}]
    )

    submission_id = _attach_submission_files(
        classroom, "course-1", "assignment-1", ["doc-1"]
    )

    assert submission_id == "submission-123"
    # modifyAttachments was not called because doc-1 was already attached!
    assert classroom.submissions.modify_arguments is None


def test_execute_quick_turn_in_handles_closed_submissions_safely(monkeypatch):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from app.db.database import Base
    from app.db.models import Course, Assignment, AssignmentSolution, Submission, SubmissionState, AssignmentStatus
    from app.classroom.router import execute_quick_turn_in

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    db = Session()

    course = Course(id=1, external_id="course-ext-1", name="Parallel Computing", user_id="test_user")
    assignment = Assignment(id=1, external_id="asgn-ext-1", course_id=1, title="Lab 1 - OpenMP", user_id="test_user")
    solution = AssignmentSolution(
        id=1,
        assignment_id=1,
        validated_content="```python\n# File: task_1.py\nprint('Hello OpenMP')\n```"
    )
    db.add_all([course, assignment, solution])
    db.commit()

    # turnIn raises error indicating submissions are closed
    fake_classroom = FakeClassroomService(turn_in_error=RuntimeError("Submissions are closed for this coursework."))
    fake_docs = FakeDriveDocsService(result={"id": "zip-file-drive-id"})

    import sys
    classroom_mod = sys.modules["app.classroom.router"]
    monkeypatch.setattr(classroom_mod, "get_classroom_service", lambda _db, user_id: fake_classroom)
    monkeypatch.setattr(classroom_mod, "get_google_docs_service", lambda _db, user_id: fake_docs)
    monkeypatch.setattr(
        "app.services.ai_solution.export_solution_to_google_doc",
        lambda _db, _asgn, _content, user_id: {"doc_id": "doc-drive-id-123", "doc_url": "https://docs.google.com/..."}
    )

    res = execute_quick_turn_in(db, assignment.id, "test_user")

    # Deliverables were safely attached to Google Classroom even though turnIn was closed
    assert res["success"] is True
    assert res["turned_in"] is False
    assert "safely attached to coursework" in res["message"]
    assert fake_classroom.submissions.modify_arguments is not None
    attached = fake_classroom.submissions.modify_arguments["body"]["addAttachments"]
    assert len(attached) == 2


def test_check_and_execute_course_auto_turn_in_strictly_scopes_to_course(monkeypatch):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from datetime import datetime, timezone, timedelta
    from app.db.database import Base
    from app.db.models import Course, Assignment, AssignmentSolution, Setting, Submission, SubmissionState
    from app.classroom.router import check_and_execute_course_auto_turn_in
    import json
    import sys

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    db = Session()

    user_id = "test_user_scoped"
    course1 = Course(id=10, external_id="c1", name="Course 1", user_id=user_id)
    course2 = Course(id=20, external_id="c2", name="Course 2", user_id=user_id)

    now = datetime.now(timezone.utc)
    # Assignment in course 1: due in 35 mins (within 60 min window)
    asgn1 = Assignment(
        id=101, external_id="a1", course_id=10, title="Course 1 Lab",
        due_at=now + timedelta(minutes=35), user_id=user_id,
        submission_state=SubmissionState.CREATED
    )
    # Assignment in course 2: also due in 35 mins
    asgn2 = Assignment(
        id=201, external_id="a2", course_id=20, title="Course 2 Assignment",
        due_at=now + timedelta(minutes=35), user_id=user_id,
        submission_state=SubmissionState.CREATED
    )

    sol1 = AssignmentSolution(id=1, assignment_id=101, validated_content="Code 1")
    sol2 = AssignmentSolution(id=2, assignment_id=201, validated_content="Code 2")
    # An earlier attempt attached files but did not turn in; auto-turn-in must retry it.
    prior_failed_attempt = Submission(
        id=1, assignment_id=101, user_id=user_id,
        submitted_at=now - timedelta(minutes=1),
        submission_state=SubmissionState.CREATED,
        google_doc_id="doc-101", google_drive_file_id="zip-101",
        classroom_attachment_id="submission-101",
    )

    # Auto turn-in enabled ONLY for course 10
    setting_c1 = Setting(
        key=f"auto_turnin_course_{user_id}_10",
        value=json.dumps({"enabled": True, "minutes_before": 60})
    )
    db.add_all([course1, course2, asgn1, asgn2, sol1, sol2, prior_failed_attempt, setting_c1])
    db.commit()

    turn_in_calls = []
    classroom_mod = sys.modules["app.classroom.router"]
    monkeypatch.setattr(
        classroom_mod,
        "execute_quick_turn_in",
        lambda _db, a_id, u_id: turn_in_calls.append(a_id) or {"success": True, "assignment_id": a_id}
    )

    results = check_and_execute_course_auto_turn_in(db, course_id=10, user_id=user_id)

    # STRICT CHECK: Only Course 1 assignment was turned in!
    assert len(results) == 1
    assert turn_in_calls == [101]
    assert 201 not in turn_in_calls


def test_auto_turn_in_completed_solution_requires_opt_in_validated_content_and_open_submission(monkeypatch):
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from app.db.database import Base
    from app.db.models import Course, Assignment, AssignmentSolution, Setting, Submission, SubmissionState
    from app.classroom.router import auto_turn_in_completed_solution
    import json
    import sys

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    user_id = "test_user_ready_submit"
    course = Course(id=30, external_id="course-ready", name="Ready Course", user_id=user_id)
    assignment = Assignment(id=301, external_id="assignment-ready", course_id=30, title="Lab", user_id=user_id)
    solution = AssignmentSolution(id=301, assignment_id=301, user_id=user_id, draft_content="Draft only")
    setting = Setting(
        key=f"auto_turnin_course_{user_id}_30",
        value=json.dumps({"submit_when_ready": False}),
    )
    db.add_all([course, assignment, solution, setting])
    db.commit()

    calls = []
    monkeypatch.setattr(
        sys.modules["app.classroom.router"],
        "execute_quick_turn_in",
        lambda _db, assignment_id, _user_id: calls.append(assignment_id) or {"success": True},
    )

    assert auto_turn_in_completed_solution(db, assignment.id, user_id) is None
    assert calls == []

    setting.value = json.dumps({"submit_when_ready": True})
    db.commit()
    assert auto_turn_in_completed_solution(db, assignment.id, user_id) is None
    assert calls == []

    solution.validated_content = "Validated report"
    db.commit()
    assert auto_turn_in_completed_solution(db, assignment.id, user_id) == {"success": True}
    assert calls == [assignment.id]

    submission = Submission(
        assignment_id=assignment.id,
        user_id=user_id,
        submission_state=SubmissionState.TURNED_IN,
    )
    db.add(submission)
    db.commit()
    assert auto_turn_in_completed_solution(db, assignment.id, user_id) is None
    assert calls == [assignment.id]
    db.close()
