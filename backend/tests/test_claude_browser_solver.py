import os
import json
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch, PropertyMock
from pathlib import Path
from types import SimpleNamespace
import pytest
from app.db.models import Assignment, AssignmentSolution, AssignmentMaterial, BrowserAutomationJob, Course, Setting, AssignmentStatus
from app.services.claude_browser_solver import (
    find_system_browser,
    is_cdp_port_live,
    get_student_metadata,
    prepare_assignment_materials,
    build_academic_cover_markdown,
    open_claude_browser_window,
    solve_assignment_via_claude_browser,
    USER_CDP_PORT,
    connect_to_chrome,
    is_heavy_ml_assignment,
    _is_assignment_already_solving,
    _has_display,
    _get_headless_mode,
)
from app.services.ai_solution import (
    export_solution_to_google_doc,
    extract_assignment_deliverables,
    extract_colab_notebooks,
)


def test_find_system_browser():
    """Verify find_system_browser returns a valid executable path or command name."""
    browser_bin = find_system_browser()
    assert isinstance(browser_bin, str)
    assert len(browser_bin) > 0
    assert any(name in browser_bin.lower() for name in ("chrome", "edge", "chromium"))


def test_build_academic_cover_markdown():
    """Verify academic cover markdown produces clean Air University deliverable header."""
    meta = {
        "university": "AIR UNIVERSITY, ISLAMABAD",
        "department": "Department of Computer Science & Information Technology",
        "course_name": "Operating Systems Lab",
        "student_name": "Ahmed Khan",
        "roll_no": "232530",
        "section": "BSCSev-F-23-A-925",
        "instructor": "Dr. Farhan",
        "date": "October 11, 2026",
    }
    cover = build_academic_cover_markdown(meta, "Lab Task 05: Semaphore Synchronization")
    assert "# AIR UNIVERSITY, ISLAMABAD" in cover
    assert "Operating Systems Lab" in cover
    assert "Ahmed Khan" in cover
    assert "232530" in cover
    assert "BSCSev-F-23-A-925" in cover
    assert "Lab Task 05: Semaphore Synchronization" in cover


def test_get_student_metadata_with_clerk_profile():
    """Verify get_student_metadata extracts student info from DB Settings."""
    mock_db = MagicMock()
    mock_setting = Setting(
        key="clerk_user_user_123",
        value=json.dumps({
            "first_name": "Ahmed",
            "last_name": "Khan",
            "email": "232530@students.au.edu.pk",
            "student_id": "232530"
        })
    )
    mock_db.query().filter().order_by().first.return_value = mock_setting
    mock_course = Course(
        id=1,
        name="Computer Networks",
        teacher_name="Engr. Bilal",
        section="BSCS-5A"
    )

    meta = get_student_metadata(mock_db, mock_course)
    assert meta["student_name"] == "Ahmed Khan"
    assert meta["roll_no"] == "232530"
    assert meta["course_name"] == "Computer Networks"
    assert meta["instructor"] == "Engr. Bilal"
    assert meta["section"] == "BSCS-5A"
    assert "AIR UNIVERSITY" in meta["university"]


def test_get_student_metadata_does_not_reuse_another_students_identity():
    mock_db = MagicMock()
    mock_db.query.return_value.filter.return_value.first.return_value = None

    meta = get_student_metadata(mock_db, None, user_id="user_without_profile")

    assert meta["student_name"] == "Student"
    assert meta["roll_no"] == ""
    assert meta["student_email"] == ""
    assert meta["section"] == "Not provided"


def test_is_cdp_port_live_when_closed():
    """Verify is_cdp_port_live returns False when port is not listening."""
    # Use a random inactive local port
    assert is_cdp_port_live(59999, timeout=0.1) is False


def test_connect_to_chrome_retries_transient_cdp_timeout():
    chromium = MagicMock()
    browser = MagicMock()
    chromium.connect_over_cdp.side_effect = [
        TimeoutError("DevTools handshake timed out"),
        browser,
    ]

    with patch("app.services.claude_browser_solver.time.sleep") as sleep:
        result = connect_to_chrome(chromium, USER_CDP_PORT)

    assert result is browser
    assert chromium.connect_over_cdp.call_count == 2
    chromium.connect_over_cdp.assert_called_with(
        "http://127.0.0.1:9222",
        timeout=20000,
    )
    sleep.assert_called_once_with(1)


def test_open_claude_browser_window_when_already_active():
    """Verify open_claude_browser_window detects already running Chrome instance."""
    with patch("app.services.claude_browser_solver.get_active_cdp_port", return_value=USER_CDP_PORT):
        res = open_claude_browser_window()
        assert res["status"] == "ready"
        assert res["port"] == USER_CDP_PORT
        assert "already active" in res["message"]


def test_open_claude_browser_window_uses_persistent_isolated_profile():
    with patch("app.services.claude_browser_solver.get_active_cdp_port", return_value=None), \
         patch("app.services.claude_browser_solver.find_system_browser", return_value="chrome.exe"), \
         patch("app.services.claude_browser_solver.subprocess.Popen") as mock_popen, \
         patch("app.services.claude_browser_solver.is_cdp_port_live", return_value=True):
        res = open_claude_browser_window()

    command = mock_popen.call_args.args[0]
    assert res["status"] == "launched"
    assert res["port"] == USER_CDP_PORT
    assert any(arg.startswith("--user-data-dir=") for arg in command)
    assert not any(arg.startswith("--profile-directory=") for arg in command)
    assert not any("taskkill" in arg.lower() for arg in command)


def test_prepare_assignment_materials_only_returns_explicit_assignment_attachments(tmp_path):
    local_material = SimpleNamespace(
        id=1,
        material_type="local_upload",
        title="Lab Sheet.pdf",
        drive_file_id=None,
        mime_type="application/pdf",
    )
    drive_material = SimpleNamespace(
        id=2,
        material_type="drive_file",
        title="rubric.docx",
        drive_file_id="drive-2",
        mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )
    db = MagicMock()
    db.query.return_value.filter.return_value.all.return_value = [local_material, drive_material]
    local_file = tmp_path / "assignment_44_Lab_Sheet.pdf"
    local_file.write_bytes(b"attached local PDF")
    (tmp_path / "assignment_44_unrelated_old_download.pdf").write_bytes(b"unrelated cached PDF")

    drive_service = MagicMock()
    drive_service.download_file.return_value = b"attached Drive document"

    with patch("app.services.claude_browser_solver.CLAUDE_MATERIALS_DIR", tmp_path), \
         patch("app.services.claude_browser_solver.get_google_docs_service", return_value=drive_service):
        paths = prepare_assignment_materials(db, Assignment(id=44, title="Lab 4"))

    assert paths == [
        str(local_file.resolve()),
        str((tmp_path / "assignment_44_material_2_rubric.docx").resolve()),
    ]
    assert Path(paths[1]).read_bytes() == b"attached Drive document"
    drive_service.download_file.assert_called_once_with("drive-2")


def test_heavy_ml_assignment_uses_colab_deliverable_extraction():
    notebook = {
        "cells": [{"cell_type": "code", "metadata": {}, "source": ["print('train')"], "outputs": [], "execution_count": None}],
        "metadata": {"kernelspec": {"display_name": "Python 3", "language": "python", "name": "python3"}},
        "nbformat": 4,
        "nbformat_minor": 5,
    }
    markdown = (
        "# Task 2 — Train a CNN\n"
        "Use GPU for deep learning model training.\n\n"
        "```colab-json\n"
        f"{json.dumps(notebook)}\n"
        "```\n"
    )

    assert is_heavy_ml_assignment(markdown)
    deliverables = extract_assignment_deliverables(markdown)
    assert len(deliverables["files"]) == 1
    assert deliverables["files"][0]["name"] == "task_2_colab.ipynb"
    assert json.loads(deliverables["files"][0]["content"]) == notebook
    assert extract_colab_notebooks("# Task 3 — broken\n```colab-json\nnot json\n```") == []


def test_google_report_includes_supplied_terminal_output():
    assignment = Assignment(id=44, title="Lab report", course_id=5)
    course = Course(id=5, name="Distributed Computing")
    db = MagicMock()

    def mock_query(model):
        query = MagicMock()
        query.filter.return_value.first.return_value = course if model == Course else None
        if model == Setting:
            query.filter.return_value.order_by.return_value.first.return_value = None
        return query

    db.query.side_effect = mock_query
    docs_service = MagicMock()
    docs_service.create_document.return_value = {"documentId": "doc-1"}
    docs_service.drive_service = MagicMock()
    docs_service.upload_file.return_value = {
        "id": "notebook-1",
        "webViewLink": "https://drive.google.com/file/d/notebook-1/view",
    }
    notebook = {
        "cells": [{"cell_type": "code", "metadata": {}, "source": ["print('train')"], "outputs": [], "execution_count": None}],
        "metadata": {},
        "nbformat": 4,
        "nbformat_minor": 5,
    }
    markdown = (
        "# AIR UNIVERSITY, ISLAMABAD\n"
        "Student cover page content\n"
        "---\n\n"
        "# Task 1 — Semaphore test\n"
        "Analyze bounded concurrency.\n\n"
        "```java\nclass Main { public static void main(String[] args) { System.out.println(\"done\"); } }\n"
        "```\n"
    )
    execution_results = [{
        "task": "1",
        "filename": "task_1_solution.java",
        "status": "passed",
        "success": True,
        "exit_code": 0,
        "tool": "Java",
        "terminal_output": "$ java Main\ndone\n[Process completed with exit code 0]",
    }]

    with patch("app.services.ai_solution.get_google_docs_service", return_value=docs_service):
        result = export_solution_to_google_doc(
            db,
            assignment,
            markdown,
            execution_results=execution_results,
            notebook_deliverables=[{
                "task": "2",
                "name": "task_2_colab.ipynb",
                "content": json.dumps(notebook),
            }],
        )

    assert result["doc_url"] == "https://docs.google.com/document/d/doc-1/edit"
    assert any("Task 1: Semaphore test" in call.args[1] for call in docs_service.append_styled_block.call_args_list)
    assert any("done" in call.args[1] for call in docs_service.append_styled_block.call_args_list)
    assert not any("Student cover page content" in call.args[1] for call in docs_service.append_styled_block.call_args_list)
    assert any("https://drive.google.com/file/d/notebook-1/view" in call.args[1] for call in docs_service.append_styled_block.call_args_list)
    docs_service.upload_file.assert_called_once_with(
        name="task_2_colab.ipynb",
        content=json.dumps(notebook).encode("utf-8"),
        mime_type="application/x-ipynb+json",
    )
    docs_service.create_academic_intro_page.assert_called_once()


def test_solve_assignment_via_claude_browser_not_found():
    """Verify solve_assignment_via_claude_browser returns error if assignment does not exist."""
    mock_db = MagicMock()
    mock_db.query().filter().first.return_value = None

    res = solve_assignment_via_claude_browser(mock_db, assignment_id=99999)
    assert res["status"] == "error"
    assert "not found" in res["error"]


def test_solve_assignment_via_claude_browser_needs_login():
    """Verify solver detects when Claude page requires user login."""
    mock_db = MagicMock()
    mock_assignment = Assignment(id=1, title="Lab 1", course_id=10)
    mock_course = Course(id=10, name="OOP")
    
    # Configure mock query behavior
    def mock_query(model):
        q = MagicMock()
        if model == Assignment:
            q.filter().first.return_value = mock_assignment
        elif model == Course:
            q.filter().first.return_value = mock_course
        elif model == Setting:
            q.filter().order_by().first.return_value = None
        elif model == AssignmentMaterial:
            q.filter().all.return_value = []
        return q
    mock_db.query.side_effect = mock_query

    mock_page = MagicMock()
    mock_page.url = "https://claude.ai/login"

    mock_context = MagicMock()
    mock_context.pages = [mock_page]

    mock_browser = MagicMock()
    mock_browser.contexts = [mock_context]

    mock_pw_instance = MagicMock()
    mock_pw_instance.chromium.connect_over_cdp.return_value = mock_browser

    with patch("app.services.browser_sessions.BrowserSessionClient.cdp_endpoint", return_value="http://127.0.0.1:9222"), \
         patch("playwright.sync_api.sync_playwright") as mock_pw_ctx, \
         patch("app.services.claude_browser_solver._handle_claude_login_and_oauth", return_value=False):
        mock_pw_ctx.return_value.__enter__.return_value = mock_pw_instance
        res = solve_assignment_via_claude_browser(mock_db, assignment_id=1)
        assert res["status"] == "needs_login"
        assert "not signed in" in res["error"]


def test_solve_assignment_via_claude_browser_successful_solve():
    """Verify end-to-end Claude solving flow with prompt input, response extraction, and DB persistence."""
    mock_db = MagicMock()
    mock_assignment = Assignment(id=2, title="Database Normalization", course_id=5, status=AssignmentStatus.DRAFT)
    mock_course = Course(id=5, name="DBMS", teacher_name="Dr. Ali", section="BSCS-4B")
    mock_solution = AssignmentSolution(assignment_id=2)

    def mock_query(model):
        q = MagicMock()
        if model == Assignment:
            q.filter().first.return_value = mock_assignment
        elif model == Course:
            q.filter().first.return_value = mock_course
        elif model == Setting:
            q.filter().order_by().first.return_value = None
        elif model == AssignmentMaterial:
            q.filter().all.return_value = []
        elif model == AssignmentSolution:
            q.filter().first.return_value = mock_solution
        return q
    mock_db.query.side_effect = mock_query

    generated_claude_output = (
        "## Task 1: 3NF Normalization\n"
        "### 1. Problem Statement\nDecompose the unnormalized Student-Course relation into 3NF.\n\n"
        "### 2. Source Code / Visual Diagram Implementation\n"
        "```sql\nCREATE TABLE Students (StudentID INT PRIMARY KEY, Name VARCHAR(100));\n```\n\n"
        "### 3. Expected Output & Verification\n"
        "The relation satisfies 1NF, 2NF, and 3NF with zero transitive dependencies."
    )

    mock_page = MagicMock()
    mock_page.url = "https://claude.ai/new"
    # Provide a mock copy button
    mock_copy_btn = MagicMock()
    mock_page.locator().all.return_value = [mock_copy_btn]
    # Stop button locator count returns 0 (finished)
    mock_page.locator().count.return_value = 0
    mock_page.locator().first.is_visible.return_value = False
    # Clipboard returns the generated text
    mock_page.evaluate.return_value = generated_claude_output

    mock_context = MagicMock()
    mock_context.pages = [mock_page]

    mock_browser = MagicMock()
    mock_browser.contexts = [mock_context]

    mock_pw_instance = MagicMock()
    mock_pw_instance.chromium.connect_over_cdp.return_value = mock_browser

    with patch("app.services.browser_sessions.BrowserSessionClient.cdp_endpoint", return_value="http://127.0.0.1:9222"), \
         patch("playwright.sync_api.sync_playwright") as mock_pw_ctx, \
         patch("app.services.claude_browser_solver.export_solution_to_google_doc", return_value={"doc_url": "https://docs.google.com/document/d/test123", "doc_id": "test123"}), \
         patch("app.services.claude_browser_solver._handle_claude_login_and_oauth", return_value=True):
        mock_pw_ctx.return_value.__enter__.return_value = mock_pw_instance

        res = solve_assignment_via_claude_browser(mock_db, assignment_id=2, max_wait_seconds=5)

        assert res["status"] == "completed"
        assert res["assignment_id"] == 2
        assert res["google_doc_url"] == "https://docs.google.com/document/d/test123"
        assert mock_assignment.status == AssignmentStatus.READY_FOR_REVIEW
        assert mock_solution.ai_provider == "claude_browser"
        assert "# AIR UNIVERSITY, ISLAMABAD" in mock_solution.validated_content
        assert "3NF Normalization" in mock_solution.validated_content
        assert mock_db.commit.called


def test_is_assignment_already_solving_when_generating_recently():
    """Verify solver refuses to start when assignment is already being solved."""
    mock_db = MagicMock()
    mock_assignment = Assignment(id=3, title="Lab 3", status=AssignmentStatus.GENERATING)
    mock_solution = AssignmentSolution(
        assignment_id=3,
        generated_at=datetime.now(timezone.utc) - timedelta(minutes=5),
    )

    def mock_query(model):
        q = MagicMock()
        if model == Assignment:
            q.filter().first.return_value = mock_assignment
        elif model == AssignmentSolution:
            q.filter().first.return_value = mock_solution
        elif model == BrowserAutomationJob:
            q.filter().first.return_value = None
        return q

    mock_db.query.side_effect = mock_query
    assert _is_assignment_already_solving(mock_db, 3, "user_123") is True


def test_is_assignment_already_solving_when_stale():
    """Verify solver is allowed to start when prior generation is stale."""
    mock_db = MagicMock()
    mock_assignment = Assignment(id=4, title="Lab 4", status=AssignmentStatus.GENERATING)
    mock_solution = AssignmentSolution(
        assignment_id=4,
        generated_at=datetime.now(timezone.utc) - timedelta(minutes=30),
    )

    def mock_query(model):
        q = MagicMock()
        if model == Assignment:
            q.filter().first.return_value = mock_assignment
        elif model == AssignmentSolution:
            q.filter().first.return_value = mock_solution
        elif model == BrowserAutomationJob:
            q.filter().first.return_value = None
        return q

    mock_db.query.side_effect = mock_query
    assert _is_assignment_already_solving(mock_db, 4, "user_123") is False


def test_solve_assignment_via_claude_browser_already_running():
    """Verify solver returns already_running when a solve is in progress."""
    mock_db = MagicMock()
    mock_assignment = Assignment(id=5, title="Lab 5", status=AssignmentStatus.GENERATING)
    mock_solution = AssignmentSolution(
        assignment_id=5,
        generated_at=datetime.now(timezone.utc) - timedelta(minutes=2),
    )

    def mock_query(model):
        q = MagicMock()
        if model == Assignment:
            q.filter().first.return_value = mock_assignment
        elif model == AssignmentSolution:
            q.filter().first.return_value = mock_solution
        elif model == BrowserAutomationJob:
            q.filter().first.return_value = None
        return q

    mock_db.query.side_effect = mock_query
    res = solve_assignment_via_claude_browser(mock_db, assignment_id=5, user_id="user_123")
    assert res["status"] == "already_running"


def test_solve_assignment_via_claude_browser_completed_with_google_docs_warning():
    """Verify a generated solution is saved as COMPLETED with warning when Google Docs export fails."""
    mock_db = MagicMock()
    mock_assignment = Assignment(id=6, title="Export Fails", course_id=5, status=AssignmentStatus.DRAFT)
    mock_course = Course(id=5, name="DBMS", teacher_name="Dr. Ali", section="BSCS-4B")
    mock_solution = AssignmentSolution(assignment_id=6)

    def mock_query(model):
        q = MagicMock()
        if model == Assignment:
            q.filter().first.return_value = mock_assignment
        elif model == Course:
            q.filter().first.return_value = mock_course
        elif model == Setting:
            q.filter().order_by().first.return_value = None
        elif model == AssignmentMaterial:
            q.filter().all.return_value = []
        elif model == AssignmentSolution:
            q.filter().first.return_value = mock_solution
        return q

    mock_db.query.side_effect = mock_query

    generated_claude_output = (
        "## Task 1: Sample Assignment\n\n"
        "This is a sample solution generated by Claude for testing the draft-on-export-failure path.\n\n"
        "### 1. Problem Statement\n"
        "Solve the sample problem.\n\n"
        "### 2. Solution\n"
        "The answer is forty-two.\n"
    )

    mock_page = MagicMock()
    mock_page.url = "https://claude.ai/new"
    mock_copy_btn = MagicMock()
    mock_page.locator().all.return_value = [mock_copy_btn]
    mock_page.locator().count.return_value = 0
    mock_page.locator().first.is_visible.return_value = False
    mock_page.evaluate.return_value = generated_claude_output

    mock_context = MagicMock()
    mock_context.pages = [mock_page]

    mock_browser = MagicMock()
    mock_browser.contexts = [mock_context]

    mock_pw_instance = MagicMock()
    mock_pw_instance.chromium.connect_over_cdp.return_value = mock_browser

    with patch("app.services.browser_sessions.BrowserSessionClient.cdp_endpoint", return_value="http://127.0.0.1:9222"), \
         patch("playwright.sync_api.sync_playwright") as mock_pw_ctx, \
         patch("app.services.claude_browser_solver.export_solution_to_google_doc", return_value=None), \
         patch("app.services.claude_browser_solver._handle_claude_login_and_oauth", return_value=True):
        mock_pw_ctx.return_value.__enter__.return_value = mock_pw_instance

        res = solve_assignment_via_claude_browser(mock_db, assignment_id=6, max_wait_seconds=5)

        assert res["status"] == "completed"
        assert "warning" in res
        assert "Google Docs" in res["warning"]
        assert mock_assignment.status == AssignmentStatus.READY_FOR_REVIEW
        assert mock_solution.draft_content is not None
        assert mock_solution.validated_content is not None
        assert "Google Docs" in mock_solution.validation_errors
        assert mock_db.commit.called


def test_has_display_and_get_headless_mode():
    """Verify headless mode enforces True when running in headless/container environments."""
    # When on Linux with no DISPLAY or WAYLAND_DISPLAY
    with patch("os.name", "posix"), patch.dict(os.environ, {}, clear=True):
        assert _has_display() is False
        assert _get_headless_mode() is True

    # When on Linux with DISPLAY set and X11 socket exists
    with patch("os.name", "posix"), patch.dict(os.environ, {"DISPLAY": ":0"}), patch("pathlib.Path.exists", return_value=True):
        assert _has_display() is True

    # When on Linux with DISPLAY set but X11 socket missing (e.g. docker container without Xvfb)
    with patch("os.name", "posix"), patch.dict(os.environ, {"DISPLAY": ":0"}), patch("pathlib.Path.exists", return_value=False):
        assert _has_display() is False
        assert _get_headless_mode() is True

