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
    _is_assignment_already_solving,
    _has_display,
    _get_headless_mode,
    is_heavy_ml_assignment,
    classify_assignment_domain,
    dismiss_claude_overlays_and_modals,
    DOMAIN_HEAVY_ML,
    DOMAIN_CODING_LAB,
    DOMAIN_DIAGRAM_DESIGN,
    DOMAIN_QUANTITATIVE_MATH,
    DOMAIN_THEORY_ACADEMIC,
    _is_material_for_different_course,
    _is_claude_asking_for_clarification,
)
from app.services.ai_solution import (
    export_solution_to_google_doc,
    extract_assignment_deliverables,
    extract_colab_notebooks,
    synthesize_colab_notebook_from_markdown,
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


def test_classify_assignment_domain():
    """Verify intelligent assignment classification across academic domains."""
    # 1. Theory / Essay / Humanities
    domain = classify_assignment_domain(
        title="Entrepreneurship Assignment: Business Model Canvas",
        description="Discuss the key value propositions and customer segments for a startup.",
        course_name="Entrepreneurship",
    )
    assert domain == DOMAIN_THEORY_ACADEMIC

    domain = classify_assignment_domain(
        title="Technical Writing Essay",
        description="Explain the ethical considerations of artificial intelligence.",
        course_name="Technical English",
    )
    assert domain == DOMAIN_THEORY_ACADEMIC

    # 2. Coding Lab
    domain = classify_assignment_domain(
        title="Lab 05: Semaphore Synchronization in C",
        description="Implement bounded buffer problem with mutex and semaphores.",
        course_name="Operating Systems Lab",
    )
    assert domain == DOMAIN_CODING_LAB

    domain = classify_assignment_domain(
        title="Task 2: Binary Search Tree",
        description="Write a Python script to insert, search, and delete nodes in a BST.",
        course_name="Data Structures",
    )
    assert domain == DOMAIN_CODING_LAB

    # 3. Heavy Machine Learning
    domain = classify_assignment_domain(
        title="Deep Learning Lab: ResNet18 Training on CIFAR-10",
        description="Train a convolutional neural network with PyTorch on CUDA GPU and evaluate accuracy.",
        course_name="Machine Learning",
    )
    assert domain == DOMAIN_HEAVY_ML

    # 4. Diagram Design
    domain = classify_assignment_domain(
        title="Hospital Management ER Diagram",
        description="Design a complete ER diagram with entities, attributes, and relationships in Draw.io.",
        course_name="Database Systems",
    )
    assert domain == DOMAIN_DIAGRAM_DESIGN

    # 5. Quantitative Math (Calculus / Physics / Linear Algebra)
    domain = classify_assignment_domain(
        title="Calculus II: Optimization and Definite Integrals",
        description="Find the critical points of the function and evaluate its definite integral using substitution.",
        course_name="Calculus II",
    )
    assert domain == DOMAIN_QUANTITATIVE_MATH

    domain = classify_assignment_domain(
        title="Linear Algebra Assignment 3",
        description="Compute the eigenvalues and eigenvectors of the given matrix and prove orthogonality.",
        course_name="Linear Algebra",
    )
    assert domain == DOMAIN_QUANTITATIVE_MATH


def test_dismiss_claude_overlays_and_modals():
    """Verify overlay and modal dismiss logic executes without errors."""
    mock_page = MagicMock()
    mock_btn = MagicMock()
    mock_btn.is_visible.return_value = True
    mock_page.locator().all.return_value = [mock_btn]

    # Should press Escape, click dismiss buttons, and call page.evaluate to hide portal-root overlays
    dismiss_claude_overlays_and_modals(mock_page)

    assert mock_page.keyboard.press.called
    assert mock_btn.click.called
    assert mock_page.evaluate.called


def test_extract_code_deliverables_with_numbered_sections():
    """Verify code deliverables extraction handles diverse heading formats like '# 1. Code' and multiple blocks."""
    markdown = """
# 1. Insertion Sort Implementation
```python
def insertion_sort(arr):
    for i in range(1, len(arr)):
        key = arr[i]
        j = i - 1
        while j >= 0 and key < arr[j]:
            arr[j + 1] = arr[j]
            j -= 1
        arr[j + 1] = key
    return arr
```

```terminal
$ python task1.py
Sorted array: [1, 2, 3, 4, 5]
```

# 2. QuickSort Implementation
```python
def quicksort(arr):
    if len(arr) <= 1:
        return arr
    pivot = arr[len(arr) // 2]
    left = [x for x in arr if x < pivot]
    middle = [x for x in arr if x == pivot]
    right = [x for x in arr if x > pivot]
    return quicksort(left) + middle + quicksort(right)
```

```terminal
$ python task2.py
QuickSort verified: [1, 2, 3, 4, 5]
```
"""
    deliverables = extract_assignment_deliverables(markdown)
    assert len(deliverables["files"]) == 2
    assert deliverables["files"][0]["name"] == "task_1_solution.py"
    assert deliverables["files"][1]["name"] == "task_2_solution.py"
    assert len(deliverables["terminal_outputs"]) == 2


def test_is_material_for_different_course():
    """Verify cross-course material detection avoids sending unrelated course files to Claude."""
    curr_course = Course(id=1, name="Parallel and Distributed Computing")
    other_courses = [
        Course(id=2, name="Professional Practices CS270"),
        Course(id=3, name="Deep Learning CS-444"),
    ]

    # Material matching other courses
    assert _is_material_for_different_course("Professional_Practices_Assignment_01.docx", curr_course, other_courses) is True
    assert _is_material_for_different_course("CS270_Ethics_Case_Study.pdf", curr_course, other_courses) is True
    assert _is_material_for_different_course("Deep_Learning_Lab_3.pdf", curr_course, other_courses) is True
    assert _is_material_for_different_course("CS444_Perceptron_Handout.pdf", curr_course, other_courses) is True

    # Material belonging to current course or generic
    assert _is_material_for_different_course("PDC_Assignment_1_MPI.pdf", curr_course, other_courses) is False
    assert _is_material_for_different_course("Parallel_Computing_Manual.pdf", curr_course, other_courses) is False
    assert _is_material_for_different_course("Lab_Manual_Task1.pdf", curr_course, other_courses) is False


def test_is_claude_asking_for_clarification():
    """Verify autonomous detection when Claude pauses to ask a question instead of solving."""
    # Clarification/hesitation queries from real logs
    hesitant_1 = (
        "Your message combines instructions for three different courses "
        "(Professional Practices, Parallel and Distributed Computing, and Deep Learning), "
        "and I can't tell whether you want all of them done at once or in a particular order.\n"
        "Which one should I start with?"
    )
    hesitant_2 = "Which task would you like me to focus on first? Please let me know how you'd like to proceed."
    hesitant_3 = "Before I begin, please clarify whether you want the implementation in C++ or Python."

    assert _is_claude_asking_for_clarification(hesitant_1) is True
    assert _is_claude_asking_for_clarification(hesitant_2) is True
    assert _is_claude_asking_for_clarification(hesitant_3) is True

    # Real solution responses should NOT be flagged as clarification
    real_solution = """
# Task 1: Matrix Multiplication using MPI
## 1. Problem Statement
Implement parallel matrix multiplication using OpenMPI.
## 2. Source Code
```cpp
#include <mpi.h>
int main(int argc, char** argv) {
    MPI_Init(&argc, &argv);
    return 0;
}
```
## 3. Terminal Output
```terminal
$ mpirun -np 4 ./matmul
Execution time: 0.12s
```
"""
    assert _is_claude_asking_for_clarification(real_solution) is False


def test_extract_colab_notebooks_extended_fences():
    """Verify extract_colab_notebooks supports ```colab-json, ```ipynb, and ```json nbformat 4 blocks."""
    sample_nb = {
        "nbformat": 4,
        "nbformat_minor": 2,
        "metadata": {"accelerator": "GPU"},
        "cells": [
            {"cell_type": "markdown", "metadata": {}, "source": ["# MLP Classifier\n"]},
            {"cell_type": "code", "execution_count": None, "metadata": {}, "outputs": [], "source": ["import torch\n"]}
        ]
    }
    nb_json = json.dumps(sample_nb)

    md_colab_json = f"# Task 1: Train Model\n```colab-json\n{nb_json}\n```"
    md_ipynb = f"# Task 1: Train Model\n```ipynb\n{nb_json}\n```"
    md_json = f"# Task 1: Train Model\n```json\n{nb_json}\n```"

    nbs1 = extract_colab_notebooks(md_colab_json)
    nbs2 = extract_colab_notebooks(md_ipynb)
    nbs3 = extract_colab_notebooks(md_json)

    assert len(nbs1) == 1
    assert len(nbs2) == 1
    assert len(nbs3) == 1
    assert nbs1[0]["language"] == "ipynb"
    assert "import torch" in nbs2[0]["content"]


def test_synthesize_colab_notebook_from_markdown():
    """Verify fallback notebook synthesis when Claude outputs Python code blocks for an ML task."""
    ml_markdown = """
# Task 1: Convolutional Neural Network
## 1. Problem Statement
Build and train a CNN on CIFAR-10.

```python
import torch
import torch.nn as nn

class ConvNet(nn.Module):
    def __init__(self):
        super().__init__()
        self.conv = nn.Conv2d(3, 16, 3)
```
"""
    synthesized = synthesize_colab_notebook_from_markdown(ml_markdown, title="Deep Learning Lab 4")
    assert synthesized is not None
    assert synthesized["name"] == "solution_colab_notebook.ipynb"
    nb = json.loads(synthesized["content"])
    assert nb["nbformat"] == 4
    assert nb["metadata"]["accelerator"] == "GPU"
    assert any("import torch" in "".join(c.get("source", [])) for c in nb["cells"] if c["cell_type"] == "code")


def test_google_docs_inline_markdown_parsing():
    """Verify Google Docs inline markdown tokenizer strips **, // and computes styling spans."""
    from app.services.google_docs import GoogleDocsService

    raw = (
        "// Summary Note: This is an important section.\n"
        "Here is **bold text** and *italic text* with a `variable_x` code token.\n"
        "Option A // Option B\n"
        "Reference URL: https://drive.google.com/open?id=12345"
    )

    clean_text, spans = GoogleDocsService._parse_inline_markdown(raw)

    # 1. No raw markdown characters in clean text
    assert "**" not in clean_text
    assert "`" not in clean_text
    assert clean_text.startswith("• Summary Note:")
    assert "Option A — Option B" in clean_text
    # 2. URL slashes must remain intact
    assert "https://drive.google.com/open?id=12345" in clean_text

    # 3. Spans correctly identify bold and italic
    bold_spans = [s for s in spans if s["style"].get("bold") and not s["style"].get("italic")]
    assert len(bold_spans) == 1
    bold_content = clean_text[bold_spans[0]["start"]:bold_spans[0]["end"]]
    assert bold_content == "bold text"

    italic_spans = [s for s in spans if s["style"].get("italic") and not s["style"].get("bold")]
    assert len(italic_spans) == 1
    italic_content = clean_text[italic_spans[0]["start"]:italic_spans[0]["end"]]
    assert italic_content == "italic text"

    code_spans = [s for s in spans if s["style"].get("weightedFontFamily")]
    assert len(code_spans) == 1
    code_content = clean_text[code_spans[0]["start"]:code_spans[0]["end"]]
    assert code_content == "variable_x"


def test_google_docs_styled_block_cleans_and_updates_spans():
    """Verify append_styled_block sends clean text without ** and adds textStyle updates."""
    from app.services.google_docs import GoogleDocsService

    mock_db = MagicMock()
    service = GoogleDocsService(mock_db)
    service.docs_service = MagicMock()
    service.get_document_end_index = MagicMock(return_value=10)
    service.docs_service.documents().batchUpdate().execute.return_value = {}

    ok = service.append_styled_block(
        document_id="doc_test_123",
        text="## **1. Architectural Framework**\n// Key point: **Scalability** is essential.",
        style_type="NORMAL"
    )

    assert ok is True
    call_args = service.docs_service.documents().batchUpdate.call_args
    reqs = call_args[1]["body"]["requests"]

    # First request must insert clean text without ** or leading //
    insert_text = reqs[0]["insertText"]["text"]
    assert "**" not in insert_text
    assert "• Key point: Scalability is essential." in insert_text

    # Granular updateTextStyle requests must exist for the bold words
    text_style_reqs = [r["updateTextStyle"] for r in reqs if "updateTextStyle" in r]
    assert len(text_style_reqs) >= 2  # base style + bold spans


def test_export_solution_to_google_doc_omits_raw_xml_for_diagrams():
    """Verify export_solution_to_google_doc omits raw <mxfile> code in Google Doc body for theory diagrams."""
    mock_db = MagicMock()
    mock_course = Course(id=1, external_id="course_1", name="Parallel & Distributed Computing", section="VII-A", teacher_name="Dr. Akbar")
    mock_assignment = Assignment(id=20, external_id="assign_20", course_id=1, title="Theory Assignment 1", description="Architectural theory")
    mock_setting = Setting(key="clerk_user_1", value=json.dumps({"name": "Test Student", "student_id": "232530"}))

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

    theory_solution_markdown = """
# Executive Summary
Distributed memory architectures require distinct communication channels.

# Question 1: System Architecture
## 1. In-Depth Theoretical Analysis
Message passing enables independent processes to coordinate without shared state.

```drawio
<mxfile host="app.diagrams.net">
  <diagram name="Architecture">
    <mxGraphModel><root><mxCell id="0"/><mxCell id="1" parent="0"/></root></mxGraphModel>
  </diagram>
</mxfile>
```

# Conclusion
Independent memory scales more effectively than shared bus memory.
"""

    mock_docs_svc = MagicMock()
    mock_docs_svc.create_document.return_value = {"documentId": "doc_theory_456"}
    mock_docs_svc.create_academic_intro_page.return_value = True
    mock_docs_svc.append_styled_block.return_value = True
    mock_docs_svc.insert_image_from_bytes.return_value = True
    mock_docs_svc.drive_service = MagicMock()
    mock_docs_svc.upload_file.return_value = {"id": "drive_xml_123", "webViewLink": "https://drive.google.com/file/d/drive_xml_123/view"}

    # Mock BrowserToolRunner render to return a dummy png
    with patch("app.services.ai_solution.get_google_docs_service", return_value=mock_docs_svc), \
         patch("app.services.browser_tool_runner.BrowserToolRunner.render_drawio_diagram", return_value={"png_bytes": b"fake_png_data"}):
        result = export_solution_to_google_doc(
            db=mock_db,
            assignment=mock_assignment,
            solution_content=theory_solution_markdown,
            user_id="test_user"
        )

    assert result is not None
    assert result["doc_id"] == "doc_theory_456"

    # CRITICAL CHECK: Verify raw XML code was NEVER passed to append_styled_block as CODE
    appended_blocks = [call.args[1] for call in mock_docs_svc.append_styled_block.call_args_list]
    for block_text in appended_blocks:
        assert "<mxfile" not in block_text
        assert "<mxGraphModel" not in block_text

    # Verify diagram image was inserted
    assert mock_docs_svc.insert_image_from_bytes.called is True
    # Verify companion XML file was uploaded to Drive
    assert mock_docs_svc.upload_file.called is True


def test_theory_assignment_diagram_extraction_and_deliverable_packaging():
    """Verify extract_assignment_deliverables captures Draw.io XML and Mermaid diagrams as companion deliverables."""
    theory_md = """
# Task 1: Distributed Architecture
Theoretical discussion of decentralized consensus.

## System Architecture Diagram
```drawio
<mxfile host="app.diagrams.net">
  <diagram name="Consensus">
    <mxGraphModel><root><mxCell id="0"/><mxCell id="1" parent="0"/></root></mxGraphModel>
  </diagram>
</mxfile>
```

## Visual Workflow
```mermaid
graph TD
    Client --> Server
    Server --> Database
```
"""
    deliverables = extract_assignment_deliverables(theory_md)
    files = deliverables.get("files", [])

    assert len(files) >= 1
    # Check that drawio XML file is present
    drawio_files = [f for f in files if f.get("language") in ("drawio", "xml") or f.get("name", "").endswith(".drawio.xml")]
    assert len(drawio_files) >= 1
    assert "<mxfile" in drawio_files[0]["content"]




