from types import SimpleNamespace
from unittest.mock import Mock

import httplib2
import pytest
from googleapiclient.errors import HttpError

from app.services.classroom_sync import ClassroomSyncService


class FailingCourseworkRequest:
    def list(self, **kwargs):
        assert kwargs["courseId"] == "course_123"
        return self

    def execute(self):
        response = httplib2.Response({"status": "403"})
        raise HttpError(response, b"Insufficient Permission", uri="https://classroom.googleapis.com/")


class FailingCourseworkService:
    def courses(self):
        return self

    def courseWork(self):
        return FailingCourseworkRequest()


def test_coursework_api_failure_is_reported_to_the_sync_status():
    service = ClassroomSyncService.__new__(ClassroomSyncService)
    service.db = Mock()
    service.db.query.return_value.filter.return_value.first.return_value = SimpleNamespace(id=23)
    service.user_id = "user_123"
    service.service = FailingCourseworkService()

    with pytest.raises(RuntimeError, match="coursework request failed for course course_123 \\(HTTP 403\\)"):
        service._sync_coursework("course_123")
