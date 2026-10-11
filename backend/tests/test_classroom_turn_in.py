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

    def upload_file(self, name, content, mime_type):
        self.uploads.append((name, content, mime_type))
        if self.error:
            raise self.error
        return self.result


class FakeExecution:
    def __init__(self, result=None, error=None):
        self.result = result
        self.error = error

    def execute(self):
        if self.error:
            raise self.error
        return self.result


class FakeStudentSubmissions:
    def __init__(self, modify_error=None):
        self.modify_error = modify_error
        self.modify_arguments = None

    def list(self, **kwargs):
        assert kwargs["userId"] == "me"
        return FakeExecution({"studentSubmissions": [{"id": "submission-123"}]})

    def modifyAttachments(self, **kwargs):
        self.modify_arguments = kwargs
        return FakeExecution({"id": "submission-123"}, self.modify_error)


class FakeClassroomService:
    def __init__(self, modify_error=None):
        self.submissions = FakeStudentSubmissions(modify_error)

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
