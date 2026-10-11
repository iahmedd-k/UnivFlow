import os
import json
from unittest.mock import MagicMock, patch, PropertyMock
import pytest
from app.db.models import Assignment, AssignmentSolution, AssignmentMaterial, Course, Setting, AssignmentStatus
from app.services.claude_browser_solver import (
    find_system_browser,
    is_cdp_port_live,
    get_student_metadata,
    prepare_assignment_materials,
    build_academic_cover_markdown,
    open_claude_browser_window,
    solve_assignment_via_claude_browser,
    CLAUDE_CDP_PORT,
    USER_CDP_PORT,
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


def test_is_cdp_port_live_when_closed():
    """Verify is_cdp_port_live returns False when port is not listening."""
    # Use a random inactive local port
    assert is_cdp_port_live(59999, timeout=0.1) is False


def test_open_claude_browser_window_when_already_active():
    """Verify open_claude_browser_window detects already running Chrome instance."""
    with patch("app.services.claude_browser_solver.get_active_cdp_port", return_value=CLAUDE_CDP_PORT):
        res = open_claude_browser_window()
        assert res["status"] == "ready"
        assert res["port"] == CLAUDE_CDP_PORT
        assert "already active" in res["message"]


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

    with patch("app.services.claude_browser_solver.get_active_cdp_port", return_value=21735), \
         patch("playwright.sync_api.sync_playwright") as mock_pw_ctx:
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

    with patch("app.services.claude_browser_solver.get_active_cdp_port", return_value=21735), \
         patch("playwright.sync_api.sync_playwright") as mock_pw_ctx, \
         patch("app.services.claude_browser_solver.export_solution_to_google_doc", return_value={"doc_url": "https://docs.google.com/document/d/test123", "doc_id": "test123"}):
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
