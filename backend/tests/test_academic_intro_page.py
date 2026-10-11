import os
import io
import json
from unittest.mock import MagicMock, patch
import pytest
from app.services.google_docs import GoogleDocsService
from app.services.ai_solution import export_solution_to_google_doc
from app.db.models import Course, Assignment, AssignmentSolution, Setting


def test_create_academic_intro_page_builds_expected_blocks():
    """Verify create_academic_intro_page issues appropriate styled blocks and logo requests."""
    mock_db = MagicMock()
    service = GoogleDocsService(mock_db)
    service.docs_service = MagicMock()
    service.drive_service = MagicMock()

    mock_doc_get = {
        "body": {
            "content": [
                {"endIndex": 1},
                {"endIndex": 15, "paragraph": {"elements": [{"textRun": {"content": "Intro\n"}}]}}
            ]
        }
    }
    service.docs_service.documents().get().execute.return_value = mock_doc_get
    service.docs_service.documents().batchUpdate().execute.return_value = {}
    service.drive_service.files().create().execute.return_value = {"id": "test_logo_drive_id"}
    service.drive_service.permissions().create().execute.return_value = {}

    success = service.create_academic_intro_page(
        document_id="doc_123",
        lab_name="Database Management Systems Lab",
        assignment_title="Lab 05: Complex SQL & Relational Schema",
        student_name="Ahmed Khan",
        roll_no="210987",
        section="BSCS-6B",
        teacher_name="Dr. Ali Raza",
        submission_date="March 29, 2026",
        university_name="AIR UNIVERSITY , ISLAMABAD"
    )

    assert success is True
    assert service.docs_service.documents().batchUpdate.call_count >= 5


def test_export_solution_to_google_doc_incorporates_intro_page():
    """Verify export_solution_to_google_doc fetches GCR & profile metadata and applies academic intro page."""
    mock_db = MagicMock()
    mock_course = Course(
        id=1,
        external_id="gcr_course_101",
        name="Artificial Intelligence Lab",
        section="BSCS-6A",
        teacher_name="Prof. Usman Tariq"
    )
    mock_assignment = Assignment(
        id=10,
        external_id="gcr_assign_505",
        course_id=1,
        title="Lab 03: Graph Search & A* Search",
        description="Implement A* search algorithm in Python."
    )
    mock_solution_content = "## Task 1: A* Search Implementation\n```python\nprint('A* Search Output')\n```"
    mock_profile_setting = Setting(
        key="clerk_user_123",
        value=json.dumps({
            "first_name": "Ahmed",
            "last_name": "Dev",
            "email": "220198@students.au.edu.pk",
            "student_id": "220198",
            "university": "AIR UNIVERSITY , ISLAMABAD"
        })
    )

    mock_db.query().filter().first.side_effect = lambda: None

    def query_side_effect(model):
        q = MagicMock()
        if model == Course:
            q.filter.return_value.first.return_value = mock_course
        elif model == Assignment:
            q.filter.return_value.first.return_value = mock_assignment
        elif model == Setting:
            q.filter.return_value.order_by.return_value.first.return_value = mock_profile_setting
        else:
            q.filter.return_value.first.return_value = None
            q.filter.return_value.all.return_value = []
        return q

    mock_db.query.side_effect = query_side_effect

    mock_docs_service = MagicMock()
    mock_docs_service.docs_service = MagicMock()
    mock_docs_service.drive_service = MagicMock()
    mock_docs_service.create_document.return_value = {"documentId": "new_created_doc_id"}
    mock_docs_service.get_document_end_index.return_value = 1
    mock_docs_service.create_academic_intro_page.return_value = True
    mock_docs_service.append_styled_block.return_value = True

    with patch("app.services.ai_solution.get_google_docs_service", return_value=mock_docs_service):
        doc_result = export_solution_to_google_doc(mock_db, assignment=mock_assignment, solution_content=mock_solution_content)

        assert doc_result is not None
        assert doc_result["doc_id"] == "new_created_doc_id"
        assert doc_result["doc_url"] == "https://docs.google.com/document/d/new_created_doc_id/edit"
        mock_docs_service.create_academic_intro_page.assert_called_once()
        _, kwargs = mock_docs_service.create_academic_intro_page.call_args
        assert kwargs["lab_name"] == "Artificial Intelligence Lab"
        assert kwargs["assignment_title"] == "Lab 03: Graph Search & A* Search"
        assert kwargs["student_name"] == "Ahmed Dev"
        assert kwargs["roll_no"] == "220198"
        assert kwargs["section"] == "BSCS-6A"
        assert kwargs["teacher_name"] == "Prof. Usman Tariq"
