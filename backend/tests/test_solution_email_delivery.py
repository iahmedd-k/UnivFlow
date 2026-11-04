import io
import zipfile
from unittest.mock import MagicMock, patch
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.db.database import Base
from app.db.models import Assignment, Course, AssignmentSolution, Submission
from app.models.user import User
from app.services.email import send_solution_delivery_email


def test_send_solution_delivery_email_includes_google_drive_link():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)
    db = SessionLocal()

    try:
        user = User(
            id=1,
            email="student@uniflow.app",
            first_name="Test",
            last_name="Student",
            password_hash="mock",
            role="USER",
            is_active=True,
        )
        course = Course(id=1, name="CS 101: Computer Science", user_id="user_123", external_id="course_ext_1")
        assignment = Assignment(
            id=10,
            course_id=1,
            user_id="user_123",
            external_id="ext_10",
            title="Lab 4: Data Structures",
        )
        solution = AssignmentSolution(
            id=1,
            assignment_id=10,
            user_id="user_123",
            draft_content="# Task 1\n```python\nprint('hello')\n```",
            validated_content="# Task 1\n```python\nprint('hello')\n```",
        )
        submission = Submission(
            id=1,
            assignment_id=10,
            user_id="user_123",
            google_doc_id="gdoc_test_12345",
        )
        db.add_all([user, course, assignment, solution, submission])
        db.commit()

        with patch("app.services.alert_service.get_user_recipient_email", return_value="student@uniflow.app"), \
             patch("app.services.google_docs.get_google_docs_service", return_value=None), \
             patch("app.services.email.send_email") as mock_send_email:
            mock_send_email.return_value = True

            sent = send_solution_delivery_email(db, assignment_id=10, user_id="user_123")
            assert sent is True
            assert mock_send_email.called

            call_kwargs = mock_send_email.call_args[1]
            html_body = call_kwargs["html_content"]
            assert "https://docs.google.com/document/d/gdoc_test_12345/edit" in html_body
            assert "Solved Report (Google Drive)" in html_body
            assert "Open Solved Report in Google Drive" in html_body

            # Check ZIP attachments
            attachments = call_kwargs["attachments"]
            zip_attachment = next((a for a in attachments if a["filename"].endswith(".zip")), None)
            assert zip_attachment is not None

            # Inspect contents of the generated ZIP
            zf = zipfile.ZipFile(io.BytesIO(zip_attachment["content"]))
            filenames = zf.namelist()
            assert "Google_Drive_Report_Link.url" in filenames
            assert "Google_Drive_Report_Link.txt" in filenames
            
            url_content = zf.read("Google_Drive_Report_Link.url").decode("utf-8")
            assert "https://docs.google.com/document/d/gdoc_test_12345/edit" in url_content
    finally:
        db.close()
