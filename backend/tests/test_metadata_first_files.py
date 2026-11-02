import asyncio
import io
from pathlib import Path
from unittest.mock import Mock

import pytest
from fastapi import BackgroundTasks, UploadFile
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.endpoints import rag as rag_new
from app.core.config import settings
from app.db.database import Base
from app.db.models import Assignment, AssignmentMaterial, Course
from app.db.models.enums import AssignmentStatus
from app.models.document import DocumentStatus
from app.services.classroom_sync import ClassroomSyncService


@pytest.fixture
def db_session():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine)
    db = session_factory()
    try:
        yield db
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)
        engine.dispose()


def _create_drive_material(db, material_id=101, drive_file_id="drive-file-1"):
    course = Course(
        user_id="clerk_user_1",
        external_id=f"course-{material_id}",
        name="Operating Systems",
    )
    db.add(course)
    db.flush()
    assignment = Assignment(
        user_id="clerk_user_1",
        external_id=f"assignment-{material_id}",
        course_id=course.id,
        title="Lecture Notes",
        work_type="MATERIAL",
        status=AssignmentStatus.SUBMITTED,
    )
    db.add(assignment)
    db.flush()
    material = AssignmentMaterial(
        id=material_id,
        user_id="clerk_user_1",
        assignment_id=assignment.id,
        material_type="drive_file",
        title="Lecture Notes.pdf",
        url=f"https://drive.google.com/file/d/{drive_file_id}/view",
        drive_file_id=drive_file_id,
        mime_type="application/pdf",
    )
    db.add(material)
    db.commit()
    return material


def test_classroom_sync_stores_metadata_and_cleans_legacy_file_cache(db_session, monkeypatch):
    material = _create_drive_material(db_session)
    material.storage_key = "legacy/classroom/cache.pdf"
    material.content = "stale cached text"
    material.drive_checksum = "old-checksum"
    db_session.commit()
    s3 = Mock()
    monkeypatch.setattr("app.db.s3_client.get_s3_client", lambda: s3)

    class Request:
        def execute(self):
            return {
                "id": material.drive_file_id,
                "name": material.title,
                "mimeType": "application/pdf",
                "modifiedTime": "2026-10-30T12:00:00Z",
                "md5Checksum": "current-checksum",
                "size": "1234",
            }

    class Files:
        def get(self, **kwargs):
            assert kwargs["fileId"] == material.drive_file_id
            return Request()

    service = ClassroomSyncService.__new__(ClassroomSyncService)
    service.db = db_session
    service.user_id = "clerk_user_1"
    service.scope_missing_for_materials = False
    service._get_drive_service = lambda: type("Drive", (), {"files": lambda self: Files()})()
    service._download_drive_file_bytes = Mock(side_effect=AssertionError("sync must not fetch file bytes"))
    service._extract_drive_file_text = Mock(side_effect=AssertionError("sync must not extract file text"))

    service._sync_materials(
        material.assignment_id,
        [
            {
                "driveFile": {
                    "driveFile": {
                        "id": material.drive_file_id,
                        "title": material.title,
                        "mimeType": "application/pdf",
                        "alternateLink": material.url,
                    }
                }
            }
        ],
    )

    db_session.refresh(material)
    assert material.title == "Lecture Notes.pdf"
    assert material.drive_checksum == "current-checksum"
    assert material.file_size == 1234
    assert material.content is None
    assert material.storage_key is None
    service._download_drive_file_bytes.assert_not_called()
    service._extract_drive_file_text.assert_not_called()
    s3.delete_object.assert_called_once_with(
        Bucket="uniflow-files",
        Key="legacy/classroom/cache.pdf",
    )


def test_ai_fetches_drive_content_on_demand_and_reuses_version_cache(db_session, monkeypatch):
    material = _create_drive_material(db_session)
    download = Mock(return_value=(b"pdf bytes", "application/pdf"))
    extract = Mock(return_value="Cached lecture text for AI.")

    class Request:
        def execute(self):
            return {
                "id": material.drive_file_id,
                "name": material.title,
                "mimeType": "application/pdf",
                "modifiedTime": "2026-10-30T12:00:00Z",
                "size": "1234",
            }

    class Files:
        def get(self, **kwargs):
            return Request()

    drive = type("Drive", (), {"files": lambda self: Files()})()
    classroom_service = type(
        "ClassroomService",
        (),
        {
            "_get_drive_service": lambda self: drive,
            "_download_drive_file_bytes": download,
            "_extract_drive_file_text": extract,
        },
    )()

    class Lock:
        def acquire(self):
            return True

        def release(self):
            pass

    monkeypatch.setattr(
        "app.services.classroom_sync.get_classroom_service",
        lambda db, user_id: classroom_service,
    )
    monkeypatch.setattr("app.core.redis.get_user_lock", lambda *args, **kwargs: Lock())

    rag_new._cache_classroom_materials_for_ai(
        db_session,
        [f"mat_{material.id}"],
        "clerk_user_1",
    )
    db_session.refresh(material)
    assert material.content == "Cached lecture text for AI."
    assert material.storage_key is None
    download.assert_called_once()

    rag_new._cache_classroom_materials_for_ai(
        db_session,
        [f"mat_{material.id}"],
        "clerk_user_1",
    )
    download.assert_called_once()


@pytest.mark.asyncio
async def test_user_upload_returns_processing_metadata_before_background_indexing(tmp_path, monkeypatch):
    from app.models.document import Document

    monkeypatch.setattr(settings, "local_temp_dir", str(tmp_path))
    monkeypatch.setattr(
        rag_new,
        "resolve_user_context",
        lambda db, current_user: (7, "clerk_user_1"),
    )

    class UploadService:
        def __init__(self):
            self.process_background = Mock()
            self.temp_path = None

        def upload_async(self, **kwargs):
            self.temp_path = kwargs["file_path"]
            return (
                Document(
                    id=42,
                    user_id=7,
                    original_filename="notes.pdf",
                    storage_key="user/notes.pdf",
                    storage_url="https://storage.example/notes.pdf",
                    mime_type="application/pdf",
                    file_size=8,
                    status=DocumentStatus.PROCESSING,
                ),
                self.temp_path,
            )

        def process_document_background(self, document_id, temp_path):
            self.process_background(document_id, temp_path)

    upload_service = UploadService()
    background_tasks = BackgroundTasks()
    response = await rag_new.upload_document(
        background_tasks=background_tasks,
        file=UploadFile(filename="notes.pdf", file=io.BytesIO(b"pdf data")),
        current_user={"id": "clerk_user_1"},
        db=object(),
        document_service=upload_service,
    )

    assert response.data.status == DocumentStatus.PROCESSING
    upload_service.process_background.assert_not_called()
    await background_tasks()
    upload_service.process_background.assert_called_once_with(42, str(upload_service.temp_path))
    Path(upload_service.temp_path).unlink(missing_ok=True)
