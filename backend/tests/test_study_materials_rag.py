import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.db.database import Base
from app.db.models import Course, Assignment, AssignmentMaterial
from app.db.models.enums import AssignmentStatus
from app.api.rag import _classify_material, _classify_file_type, _read_materials, get_classroom_materials


# SQLite in-memory test setup
SQLALCHEMY_DATABASE_URL = "sqlite:///:memory:"
engine = create_engine(SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False})
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@pytest.fixture
def db_session():
    Base.metadata.create_all(bind=engine)
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()
        Base.metadata.drop_all(bind=engine)


def test_classify_material_types():
    # 1. Slide / Lecture material
    cat, label, icon = _classify_material("Lecture 1 - Operating Systems.pptx", "OS Intro", "MATERIAL", "application/vnd.google-apps.presentation", "drive_file")
    assert cat == "material"
    assert "Slides" in label

    # 2. Lab assignment
    cat, label, icon = _classify_material("Lab 03 - Paging and Virtual Memory.pdf", "Lab 03", "ASSIGNMENT", "application/pdf", "drive_file")
    assert cat == "assignment"
    assert "Labs" in label

    # 3. Announcement
    cat, label, icon = _classify_material("", "Important Exam Notice", "ANNOUNCEMENT", "", "announcement")
    assert cat == "announcement"
    assert "Announcements" in label


def test_classify_file_types():
    assert _classify_file_type("application/pdf", "handout.pdf", "material") == "pdf"
    assert _classify_file_type("application/vnd.google-apps.presentation", "slides", "material") == "slide"
    assert _classify_file_type("text/x-python", "solution.py", "assignment") == "code"
    assert _classify_file_type("", "syllabus.docx", "material") == "doc"
    assert _classify_file_type("", "grades.xlsx", "material") == "sheet"
    assert _classify_file_type("", "Exam Announcement", "announcement") == "announcement"


def test_get_classroom_materials_with_category_filtering(db_session):
    # Setup test course
    course = Course(
        id=1,
        user_id="dev_student_user",
        external_id="c_101",
        name="Operating Systems",
    )
    db_session.add(course)
    db_session.commit()

    # 1. Slide material
    asg_mat = Assignment(
        id=1,
        user_id="dev_student_user",
        external_id="cwm_1",
        course_id=course.id,
        title="Lecture 02 - CPU Scheduling Slides",
        work_type="MATERIAL",
        status=AssignmentStatus.SUBMITTED,
    )
    db_session.add(asg_mat)
    db_session.commit()

    mat_item = AssignmentMaterial(
        id=1,
        user_id="dev_student_user",
        assignment_id=asg_mat.id,
        material_type="drive_file",
        title="CPU_Scheduling_Slides.pdf",
        drive_file_id="drive_slide_123",
        mime_type="application/pdf",
        content="CPU scheduling algorithms include FCFS, SJF, and Round Robin.",
    )
    db_session.add(mat_item)

    # 2. Lab assignment
    asg_lab = Assignment(
        id=2,
        user_id="dev_student_user",
        external_id="asg_2",
        course_id=course.id,
        title="Lab 02 - Process Fork and Exec",
        work_type="ASSIGNMENT",
        status=AssignmentStatus.SUBMITTED,
    )
    db_session.add(asg_lab)
    db_session.commit()

    lab_item = AssignmentMaterial(
        id=2,
        user_id="dev_student_user",
        assignment_id=asg_lab.id,
        material_type="drive_file",
        title="Lab2_Manual.pdf",
        drive_file_id="drive_lab_456",
        mime_type="application/pdf",
        content="In this lab, you will implement fork() and pipe() in C.",
    )
    db_session.add(lab_item)

    # 3. Announcement
    asg_ann = Assignment(
        id=3,
        user_id="dev_student_user",
        external_id="ann_mat_3",
        course_id=course.id,
        title="Midterm Exam Guidelines",
        work_type="ANNOUNCEMENT",
        status=AssignmentStatus.SUBMITTED,
    )
    db_session.add(asg_ann)
    db_session.commit()

    ann_item = AssignmentMaterial(
        id=3,
        user_id="dev_student_user",
        assignment_id=asg_ann.id,
        material_type="announcement",
        title="Midterm Exam Guidelines",
        drive_file_id=None,
        mime_type="text/plain",
        content="Midterm exam will cover Chapters 1 to 4. Calculators allowed.",
    )
    db_session.add(ann_item)
    db_session.commit()

    # Query all materials
    all_data = get_classroom_materials(limit=50, course_id=None, category="all", query=None, current_user=None, db=db_session)
    assert len(all_data) >= 3

    # Filter by category="material" (slides)
    mat_data = get_classroom_materials(limit=50, course_id=None, category="material", query=None, current_user=None, db=db_session)
    assert any(m["title"] == "CPU_Scheduling_Slides.pdf" for m in mat_data)
    assert not any(m["title"] == "Lab2_Manual.pdf" for m in mat_data)

    # Filter by category="assignment" (labs)
    lab_data = get_classroom_materials(limit=50, course_id=None, category="assignment", query=None, current_user=None, db=db_session)
    assert any(m["title"] == "Lab2_Manual.pdf" for m in lab_data)
    assert not any(m["title"] == "CPU_Scheduling_Slides.pdf" for m in lab_data)

    # Filter by category="announcement"
    ann_data = get_classroom_materials(limit=50, course_id=None, category="announcement", query=None, current_user=None, db=db_session)
    assert any("Midterm Exam" in m["title"] for m in ann_data)


def test_read_materials_fallback_assignment_description(db_session):
    course = Course(id=10, user_id="dev_student_user", external_id="c_10", name="Databases")
    db_session.add(course)
    db_session.commit()

    asg = Assignment(
        id=99,
        user_id="dev_student_user",
        external_id="asg_99",
        course_id=course.id,
        title="SQL Subqueries Task",
        description="Write nested SQL queries to find top-earning employees.",
    )
    db_session.add(asg)
    db_session.commit()

    results = _read_materials(db_session, ["asg_99"])
    assert len(results) == 1
    assert "top-earning employees" in results[0]["content"]
    assert results[0]["title"] == "SQL Subqueries Task"
