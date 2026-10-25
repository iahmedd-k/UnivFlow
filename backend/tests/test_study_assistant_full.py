import pytest
from datetime import datetime, timezone
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.main import app
from app.db.database import Base, get_db
from app.db.base import Base as RagBase
from app.auth.clerk_auth import require_current_user
from app.auth.access_gate import require_access_grant
from app.db.models import Course, Assignment, AssignmentMaterial
from app.db.models.enums import AssignmentStatus
from app.models.user import User, UserRole
from app.models.document import Document, DocumentStatus
from app.models.conversation import Conversation
from app.models.message import Message

from sqlalchemy.pool import StaticPool

# In-memory test database
SQLALCHEMY_DATABASE_URL = "sqlite:///:memory:"
engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)



@pytest.fixture
def test_db():
    Base.metadata.create_all(bind=engine)
    RagBase.metadata.create_all(bind=engine)

    db = TestingSessionLocal()
    try:
        # Create user
        user = User(
            id=1,
            first_name="Test",
            last_name="Student",
            email="test_student@example.com",
            password_hash="pw",
            role=UserRole.USER,
            is_active=True,
            is_verified=True,
        )
        db.add(user)
        db.commit()
        yield db
    finally:
        db.close()
        RagBase.metadata.drop_all(bind=engine)
        Base.metadata.drop_all(bind=engine)



@pytest.fixture
def client(test_db):
    def override_get_db():
        try:
            yield test_db
        finally:
            pass

    def override_current_user():
        return {
            "id": "test_clerk_user_123",
            "email": "test_student@example.com",
            "name": "Test Student",
            "role": "student",
        }

    def override_access_grant():
        return True

    app.dependency_overrides[get_db] = override_get_db
    app.dependency_overrides[require_current_user] = override_current_user
    app.dependency_overrides[require_access_grant] = override_access_grant

    with TestClient(app) as test_client:
        yield test_client

    app.dependency_overrides.clear()


def test_knowledge_sources_lists_gcr_coursework_and_slides(test_db, client):
    # 1. Setup course
    course = Course(
        id=1,
        user_id="test_clerk_user_123",
        external_id="c_gcr_101",
        name="Operating Systems",
    )
    test_db.add(course)
    test_db.commit()

    # 2. Setup GCR Instructor Slide Material
    asg_slide = Assignment(
        id=10,
        user_id="test_clerk_user_123",
        external_id="cwm_slide_10",
        course_id=course.id,
        title="Lecture 03 - CPU Scheduling",
        work_type="MATERIAL",
        status=AssignmentStatus.SUBMITTED,
    )
    test_db.add(asg_slide)
    test_db.commit()

    mat_slide = AssignmentMaterial(
        id=101,
        user_id="test_clerk_user_123",
        assignment_id=asg_slide.id,
        material_type="drive_file",
        title="CPU_Scheduling_Slides.pptx",
        drive_file_id="drive_slide_999",
        mime_type="application/vnd.google-apps.presentation",
        file_size=2500000,
        content="Round Robin scheduling allocates a fixed time quantum Q to each process in FIFO order.",
    )
    test_db.add(mat_slide)

    # 3. Setup GCR Coursework Lab Assignment
    asg_lab = Assignment(
        id=20,
        user_id="test_clerk_user_123",
        external_id="asg_lab_20",
        course_id=course.id,
        title="Lab 02 - Process Fork and Exec",
        work_type="ASSIGNMENT",
        description="Implement a miniature command-line shell using fork() and execvp() in C.",
        status=AssignmentStatus.DRAFT,
    )
    test_db.add(asg_lab)

    mat_lab = AssignmentMaterial(
        id=201,
        user_id="test_clerk_user_123",
        assignment_id=asg_lab.id,
        material_type="drive_file",
        title="Lab2_Shell_Manual.pdf",
        drive_file_id="drive_lab_888",
        mime_type="application/pdf",
        file_size=450000,
        content="In this lab, you must handle SIGINT and redirect stdout/stdin using dup2().",
    )
    test_db.add(mat_lab)
    test_db.commit()

    # 4. Fetch documents from /api/v1/rag/documents
    res = client.get("/api/v1/rag/documents")
    assert res.status_code == 200
    body = res.json()
    assert body["success"] is True
    docs = body["data"]

    # Verify both slides and lab assignment are in the knowledge sources list
    filenames = [d["original_filename"] for d in docs]
    assert any("CPU_Scheduling_Slides.pptx" in f for f in filenames)
    assert any("Lab2_Shell_Manual.pdf" in f for f in filenames)

    # Verify status is completed (which shows as 'Indexed' in the UI)
    for doc in docs:
        assert doc["status"] == "completed"
        assert doc["file_size"] > 0


def test_conversations_persistence_and_retrieval(test_db, client):
    # 1. Create a conversation
    create_res = client.post(
        "/api/v1/rag/conversations",
        json={"title": "Midterm Prep Chat", "document_ids": ["mat_101"]},
    )
    assert create_res.status_code == 201
    conv = create_res.json()["data"]
    conv_id = conv["id"]
    assert conv["title"] == "Midterm Prep Chat"
    assert conv["document_ids"] == ["mat_101"]

    # 2. List conversations
    list_res = client.get("/api/v1/rag/conversations")
    assert list_res.status_code == 200
    list_data = list_res.json()["data"]
    assert any(c["id"] == conv_id for c in list_data["conversations"])

    # 3. Get single conversation detail
    detail_res = client.get(f"/api/v1/rag/conversations/{conv_id}")
    assert detail_res.status_code == 200
    detail = detail_res.json()["data"]
    assert detail["id"] == conv_id
    assert isinstance(detail["messages"], list)

    # 4. Update title
    patch_res = client.patch(
        f"/api/v1/rag/conversations/{conv_id}",
        json={"title": "Updated OS Midterm Chat"},
    )
    assert patch_res.status_code == 200
    assert patch_res.json()["data"]["title"] == "Updated OS Midterm Chat"

    # 5. Delete conversation
    del_res = client.delete(f"/api/v1/rag/conversations/{conv_id}")
    assert del_res.status_code == 204


def test_chat_grounded_in_gcr_document(test_db, client):
    # Setup course and material
    course = Course(id=2, user_id="test_clerk_user_123", external_id="c_2", name="Distributed Systems")
    test_db.add(course)
    test_db.commit()

    asg = Assignment(id=30, user_id="test_clerk_user_123", external_id="cwm_30", course_id=course.id, title="Raft Consensus", work_type="MATERIAL")
    test_db.add(asg)
    test_db.commit()

    mat = AssignmentMaterial(
        id=301,
        user_id="test_clerk_user_123",
        assignment_id=asg.id,
        material_type="drive_file",
        title="Raft_Algorithm_Slides.pptx",
        drive_file_id="drive_raft_123",
        mime_type="application/vnd.google-apps.presentation",
        file_size=1200000,
        content="Raft elects a leader using randomized election timers and uses log replication for state machine consensus.",
    )
    test_db.add(mat)
    test_db.commit()

    # Create conversation
    c_res = client.post("/api/v1/rag/conversations", json={"title": "Raft Discussion"})
    conv_id = c_res.json()["data"]["id"]

    # Send chat query scoped to Raft slides
    chat_res = client.post(
        "/api/v1/rag/chat",
        json={
            "query": "How does Raft elect a leader according to the slides?",
            "conversation_id": conv_id,
            "document_ids": ["mat_301"],
        },
    )
    assert chat_res.status_code == 200
    body = chat_res.json()
    assert body["success"] is True
    chat_data = body["data"]

    assert chat_data["answer"] is not None
    assert len(chat_data["answer"]) > 10
    assert chat_data["abstained"] is False
    assert chat_data["confidence"] >= 0.9

    # Verify conversation history persisted both user and assistant messages
    detail_res = client.get(f"/api/v1/rag/conversations/{conv_id}")
    messages = detail_res.json()["data"]["messages"]
    assert len(messages) >= 2
    assert messages[0]["role"] == "user"
    assert "Raft" in messages[0]["content"]
    assert messages[1]["role"] == "assistant"
