import pytest
from datetime import datetime, timezone
from types import SimpleNamespace
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.main import app
from app.api.endpoints import rag as rag_endpoint
from app.services import gemini as gemini_service
from app.db.database import Base, get_db
from app.db.base import Base as RagBase
from app.auth.clerk_auth import require_current_user
from app.auth.access_gate import require_access_grant
from app.db.models import Course, Assignment, AssignmentMaterial, Setting
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


def test_chat_grounded_in_gcr_document(test_db, client, monkeypatch):
    monkeypatch.setattr(
        rag_endpoint,
        "generate_study_answer",
        lambda **_: "Raft elects a leader using randomized election timers.",
    )

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


def test_chat_scopes_uploaded_retrieval_to_selected_documents(client, monkeypatch):
    class RetrievalServiceStub:
        def __init__(self):
            self.search_options = None

        def search(self, **kwargs):
            self.search_options = kwargs
            return SimpleNamespace(
                results=[
                    SimpleNamespace(
                        chunk_id=8,
                        document_id=42,
                        page_number=3,
                        content="The selected lecture explains the key concept.",
                        score=0.9,
                    )
                ]
            )

    retrieval_stub = RetrievalServiceStub()
    app.dependency_overrides[rag_endpoint.get_retrieval_service] = lambda: retrieval_stub
    monkeypatch.setattr(
        rag_endpoint,
        "generate_study_answer",
        lambda **_: "Answer based on the selected lecture.",
    )

    response = client.post(
        "/api/v1/rag/chat",
        json={
            "query": "Explain the key concept.",
            "document_ids": ["42"],
        },
    )

    assert response.status_code == 200
    assert retrieval_stub.search_options["document_ids"] == [42]
    assert response.json()["data"]["sources"][0]["document_id"] == 42


def test_chat_general_knowledge_mode_skips_document_retrieval(client, monkeypatch):
    class RetrievalServiceStub:
        def search(self, **kwargs):
            pytest.fail("Document retrieval should be skipped in general knowledge mode")

    app.dependency_overrides[rag_endpoint.get_retrieval_service] = lambda: RetrievalServiceStub()
    generated = {}

    def generate_answer(**kwargs):
        generated.update(kwargs)
        return "Here is a general explanation."

    monkeypatch.setattr(rag_endpoint, "generate_study_answer", generate_answer)
    conversation_response = client.post(
        "/api/v1/rag/conversations",
        json={"title": "General chat", "document_ids": ["mat_301", "42"]},
    )
    conversation_id = conversation_response.json()["data"]["id"]

    response = client.post(
        "/api/v1/rag/chat",
        json={
            "query": "Explain this concept generally.",
            "conversation_id": conversation_id,
            "general_knowledge": True,
        },
    )

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["answer"] == "Here is a general explanation."
    assert data["sources"] == []
    assert "general knowledge" in generated["system_prompt"].lower()
    assert "No source documents are attached" in generated["prompt"]
    conversations = client.get("/api/v1/rag/conversations").json()["data"]["conversations"]
    saved_conversation = next(item for item in conversations if item["id"] == conversation_id)
    assert saved_conversation["document_ids"] == []


def test_general_knowledge_fallback_does_not_ask_for_documents(monkeypatch):
    monkeypatch.setattr(gemini_service.settings, "gemini_api_key", "")

    answer = gemini_service.generate_study_answer(
        prompt=(
            "Question: Explain recursion.\n\n"
            "Context:\nNo source documents are attached. Answer the question using your general knowledge."
        ),
        system_prompt="Answer using general knowledge.",
        general_knowledge=True,
    )

    assert "temporarily unavailable" in answer
    assert "upload" not in answer.lower()


def test_rag_account_mapping_is_stable_and_rejects_shared_email(test_db):
    first_identity = {"id": "clerk_user_1", "email": "test_student@example.com"}
    first_user_id, _ = rag_endpoint.resolve_user_context(test_db, first_identity)

    changed_email_user_id, _ = rag_endpoint.resolve_user_context(
        test_db,
        {"id": "clerk_user_1", "email": "changed@example.com"},
    )
    assert changed_email_user_id == first_user_id

    with pytest.raises(HTTPException) as exc_info:
        rag_endpoint.resolve_user_context(
            test_db,
            {"id": "clerk_user_2", "email": "test_student@example.com"},
        )
    assert exc_info.value.status_code == 409
    assert (
        test_db.query(Setting)
        .filter(Setting.key == "rag-account:clerk_user_1")
        .one()
        .value
        == str(first_user_id)
    )


def test_documents_and_status_are_private_to_each_account(test_db, client):
    second_user = User(
        id=2,
        first_name="Second",
        last_name="Student",
        email="second_student@example.com",
        password_hash="pw",
        role=UserRole.USER,
        is_active=True,
        is_verified=True,
    )
    test_db.add(second_user)
    test_db.add_all(
        [
            Document(
                id=101,
                user_id=1,
                original_filename="first-private.pdf",
                storage_key="first-private.pdf",
                storage_url="",
                mime_type="application/pdf",
                file_size=10,
                status=DocumentStatus.COMPLETED,
            ),
            Document(
                id=202,
                user_id=2,
                original_filename="second-private.pdf",
                storage_key="second-private.pdf",
                storage_url="",
                mime_type="application/pdf",
                file_size=10,
                status=DocumentStatus.COMPLETED,
            ),
        ]
    )
    for owner, course_id, assignment_id, material_id, filename in (
        ("test_clerk_user_123", 11, 111, 1111, "first-classroom.pdf"),
        ("test_clerk_user_456", 22, 222, 2222, "second-classroom.pdf"),
    ):
        test_db.add(Course(id=course_id, user_id=owner, external_id=f"course-{course_id}", name=f"Course {course_id}"))
        test_db.add(
            Assignment(
                id=assignment_id,
                user_id=owner,
                external_id=f"assignment-{assignment_id}",
                course_id=course_id,
                title=filename,
                work_type="MATERIAL",
                status=AssignmentStatus.SUBMITTED,
            )
        )
        test_db.add(
            AssignmentMaterial(
                id=material_id,
                user_id=owner,
                assignment_id=assignment_id,
                material_type="drive_file",
                title=filename,
                mime_type="application/pdf",
                file_size=10,
                content=f"Private material for {owner}",
            )
        )
    test_db.commit()

    first_identity = {
        "id": "test_clerk_user_123",
        "email": "test_student@example.com",
        "name": "First Student",
    }
    app.dependency_overrides[require_current_user] = lambda: first_identity
    first_response = client.get("/api/v1/rag/documents")
    assert first_response.status_code == 200
    first_filenames = {item["original_filename"] for item in first_response.json()["data"]}
    assert any("first-private.pdf" in filename for filename in first_filenames)
    assert any("first-classroom.pdf" in filename for filename in first_filenames)
    assert not any("second-private.pdf" in filename for filename in first_filenames)
    assert not any("second-classroom.pdf" in filename for filename in first_filenames)
    assert client.get("/api/v1/rag/documents/202").status_code == 404
    assert client.get("/api/v1/rag/documents/mat_2222").status_code == 404
    assert client.get("/api/v1/rag/documents/202/status").status_code == 404
    assert client.get("/api/v1/rag/documents/mat_2222/status").status_code == 404
    assert client.delete("/api/v1/rag/documents/202").status_code == 404
    assert client.delete("/api/v1/rag/documents/mat_2222").status_code == 404
    assert test_db.query(Document).filter(Document.id == 202).one().user_id == 2

    second_identity = {
        "id": "test_clerk_user_456",
        "email": "second_student@example.com",
        "name": "Second Student",
    }
    app.dependency_overrides[require_current_user] = lambda: second_identity
    second_response = client.get("/api/v1/rag/documents")
    assert second_response.status_code == 200
    second_filenames = {item["original_filename"] for item in second_response.json()["data"]}
    assert any("second-private.pdf" in filename for filename in second_filenames)
    assert any("second-classroom.pdf" in filename for filename in second_filenames)
    assert not any("first-private.pdf" in filename for filename in second_filenames)
    assert not any("first-classroom.pdf" in filename for filename in second_filenames)
