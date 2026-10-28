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
            q.filter.return_value.first.return_value = mock_profile_setting
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


def test_insert_table_builds_expected_api_requests():
    """Verify insert_table creates table and populates cells in reverse order with headers."""
    mock_db = MagicMock()
    service = GoogleDocsService(mock_db)
    mock_docs_api = MagicMock()
    service.docs_service = MagicMock()
    service.docs_service.documents.return_value = mock_docs_api

    mock_doc = {
        "body": {
            "content": [
                {"endIndex": 1},
                {
                    "endIndex": 50,
                    "table": {
                        "tableRows": [
                            {
                                "tableCells": [
                                    {"content": [{"startIndex": 10}]},
                                    {"content": [{"startIndex": 15}]},
                                ]
                            },
                            {
                                "tableCells": [
                                    {"content": [{"startIndex": 20}]},
                                    {"content": [{"startIndex": 25}]},
                                ]
                            }
                        ]
                    }
                }
            ]
        }
    }
    mock_docs_api.get.return_value.execute.return_value = mock_doc
    mock_docs_api.batchUpdate.return_value.execute.return_value = {}

    success = service.insert_table(
        document_id="doc_tbl_1",
        headers=["Concept", "Definition"],
        rows=[["Morals", "Personal beliefs"]]
    )

    assert success is True
    calls = mock_docs_api.batchUpdate.call_args_list
    assert len(calls) >= 2
    first_reqs = calls[0].kwargs.get("body", {}).get("requests", [])
    assert any("insertTable" in r for r in first_reqs)


def test_export_solution_to_google_doc_renders_markdown_tables():
    """Verify markdown pipe tables are intercepted and passed to insert_table instead of plain text."""
    mock_db = MagicMock()
    mock_course = Course(id=1, external_id="course_1", name="Professional Practices", section="BSCS 7-A", teacher_name="Dr. Akbar")
    mock_assignment = Assignment(id=1, external_id="assign_1", course_id=1, title="Assignment 1", description="Ethics")
    mock_setting = Setting(key="clerk_user_1", value=json.dumps({"name": "Ahmed", "student_id": "232530"}))

    def query_side_effect(model):
        q = MagicMock()
        if model == Course:
            q.filter.return_value.first.return_value = mock_course
        elif model == Assignment:
            q.filter.return_value.first.return_value = mock_assignment
        elif model == Setting:
            q.filter.return_value.first.return_value = mock_setting
        else:
            q.filter.return_value.first.return_value = None
            q.filter.return_value.all.return_value = []
        return q

    mock_db.query.side_effect = query_side_effect

    mock_docs_service = MagicMock()
    mock_docs_service.create_document.return_value = {"documentId": "doc_table_test"}
    mock_docs_service.create_academic_intro_page.return_value = True
    mock_docs_service.append_styled_block.return_value = True
    mock_docs_service.insert_table.return_value = True

    markdown_with_table = """
# Question 1: Ethics, Morals and Laws
Theoretical analysis.

| Concept | Meaning | Source |
|---|---|---|
| Morals | Personal beliefs | Individual |
| Ethics | Group standards | Society |

---

# Conclusion
Final thoughts.
"""

    with patch("app.services.ai_solution.get_google_docs_service", return_value=mock_docs_service):
        res = export_solution_to_google_doc(mock_db, assignment=mock_assignment, solution_content=markdown_with_table)

    assert res is not None
    # Verify insert_table was called with the parsed headers and rows
    mock_docs_service.insert_table.assert_called_once()
    _, kwargs = mock_docs_service.insert_table.call_args
    assert kwargs["headers"] == ["Concept", "Meaning", "Source"]
    assert len(kwargs["rows"]) == 2
    assert kwargs["rows"][0] == ["Morals", "Personal beliefs", "Individual"]
    assert kwargs["rows"][1] == ["Ethics", "Group standards", "Society"]

    # Verify raw table pipes and horizontal rule '---' were never sent to append_styled_block
    for call in mock_docs_service.append_styled_block.call_args_list:
        text_arg = call.args[1]
        assert "|---|" not in text_arg
        assert text_arg.strip() != "---"


def test_export_solution_to_google_doc_omits_execution_verification_and_environment_metadata():
    """Verify Google Doc export permanently omits 'Status: Executed (Verified)...' and '& Execution Verification'."""
    from app.services.ai_solution import strip_disclaimers

    # 1. Test strip_disclaimers removes them from markdown
    legacy_text = (
        "## 2. Program Output & Execution Verification\n"
        "Status: Executed (Verified) | Exit Code: 0 | Environment: Ahmed Khan@air-desktop\n"
        "Output content here"
    )
    cleaned = strip_disclaimers(legacy_text)
    assert "& Execution Verification" not in cleaned
    assert "Status: Executed" not in cleaned
    assert "@air-desktop" not in cleaned

    # 2. Test export_solution_to_google_doc does not insert them into Google Doc blocks
    mock_db = MagicMock()
    mock_assignment = Assignment(id=5, title="Lab 04: Threads", course_id=101)
    mock_course = Course(id=101, name="Operating Systems")

    def query_side_effect(model):
        q = MagicMock()
        if model == Course:
            q.filter.return_value.first.return_value = mock_course
        elif model == Assignment:
            q.filter.return_value.first.return_value = mock_assignment
        else:
            q.filter.return_value.first.return_value = None
            q.filter.return_value.all.return_value = []
        return q

    mock_db.query.side_effect = query_side_effect

    mock_docs_service = MagicMock()
    mock_docs_service.create_document.return_value = {"documentId": "doc_no_exec_verif"}
    mock_docs_service.create_academic_intro_page.return_value = True
    mock_docs_service.append_styled_block.return_value = True

    execution_results = [{
        "task": 1,
        "name": "thread_test.c",
        "exit_code": 0,
        "stdout": "Thread 1 completed",
        "stderr": "",
        "screenshot_data_uri": "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="
    }]

    solution_markdown = (
        "### Task 1: Thread Test\n"
        "Question: Implement pthread join.\n\n"
        "```c\n"
        "#include <stdio.h>\n"
        "int main() { return 0; }\n"
        "```\n"
    )

    with patch("app.services.ai_solution.get_google_docs_service", return_value=mock_docs_service):
        res = export_solution_to_google_doc(
            mock_db,
            assignment=mock_assignment,
            solution_content=solution_markdown,
            execution_results=execution_results
        )

    assert res is not None
    appended_texts = [call.args[1] for call in mock_docs_service.append_styled_block.call_args_list]

    # Verify heading is '2. Program Output' and not '2. Program Output & Execution Verification'
    assert any("2. Program Output\n" in text for text in appended_texts)
    assert not any("Execution Verification" in text for text in appended_texts)
    assert not any("Status: Executed (Verified)" in text for text in appended_texts)
    assert not any("@air-desktop" in text for text in appended_texts)


