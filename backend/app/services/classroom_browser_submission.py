"""Google Classroom UI submission service.

Server-side Chromium for Google Classroom has been retired in favor of the Uniflow
Companion Chrome Extension running inside the student's authentic browser session.
Chromium is reserved strictly for the university student portal and Claude solver.
"""

from typing import Any, Dict, List, Optional
from app.core.logging import logger


class ClassroomBrowserLoginRequired(RuntimeError):
    """The persistent Classroom browser has not been authenticated yet."""


class ClassroomBrowserSubmissionError(RuntimeError):
    """The Classroom UI could not safely complete the requested submission."""


def submit_drive_files(
    user_id: str,
    course_id: str,
    coursework_id: str,
    files: List[Dict[str, str]],
    assignment_url: Optional[str] = None,
    assignment_title: Optional[str] = None,
    expected_email: Optional[str] = None,
    cookies: Optional[List[Dict[str, Any]]] = None,
    user_agent: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Classroom automation is handled natively via the Uniflow Companion Extension
    in the student's authentic Chrome browser session.
    """
    logger.info(
        "submit_drive_files called for user %s, course %s, coursework %s. "
        "Server Chromium is retired; delegating to student's Chrome extension.",
        user_id,
        course_id,
        coursework_id,
    )
    return {
        "turned_in": False,
        "extension_required": True,
        "assignment_url": assignment_url,
        "message": "Classroom UI turn-in is handled natively by the Uniflow Companion Extension.",
    }
