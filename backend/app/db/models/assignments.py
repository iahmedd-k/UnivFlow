from .common import *
from .enums import *


class Assignment(Base):
    __tablename__ = "assignments"

    id = Column(Integer, primary_key=True, index=True)
    external_id = Column(String(255), unique=True, nullable=False, index=True)
    course_id = Column(Integer, ForeignKey("courses.id"), nullable=False)
    title = Column(String(500), nullable=False)
    work_type = Column(String(50), nullable=True)
    is_quiz = Column(Boolean, default=False, nullable=False)
    description = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
    due_at = Column(DateTime(timezone=True), nullable=True)
    due_date = Column(DateTime(timezone=True), nullable=True)
    url = Column(String(500))
    state = Column(SQLEnum(CourseworkState), default=CourseworkState.PUBLISHED)
    submission_state = Column(SQLEnum(SubmissionState), nullable=True)
    status = Column(SQLEnum(AssignmentStatus), default=AssignmentStatus.DRAFT)
    last_synced_at = Column(DateTime(timezone=True), server_default=func.now())

    course = relationship("Course", back_populates="assignments")
    materials = relationship("AssignmentMaterial", back_populates="assignment")
    solution = relationship("AssignmentSolution", back_populates="assignment", uselist=False)
    submission = relationship("Submission", back_populates="assignment", uselist=False)


class AssignmentMaterial(Base):
    __tablename__ = "assignment_materials"

    id = Column(Integer, primary_key=True, index=True)
    assignment_id = Column(Integer, ForeignKey("assignments.id"), nullable=False)
    material_type = Column(String(50), nullable=False)
    title = Column(String(500))
    url = Column(String(500))
    drive_file_id = Column(String(255))
    mime_type = Column(String(100))
    content = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    assignment = relationship("Assignment", back_populates="materials")


class AssignmentTemplate(Base):
    __tablename__ = "assignment_templates"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    description = Column(Text)
    google_doc_id = Column(String(255), nullable=False)
    google_drive_file_id = Column(String(255))
    mime_type = Column(String(100))
    is_default = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


class AssignmentSolution(Base):
    __tablename__ = "assignment_solutions"

    id = Column(Integer, primary_key=True, index=True)
    assignment_id = Column(Integer, ForeignKey("assignments.id"), unique=True, nullable=False)
    draft_content = Column(Text)
    validated_content = Column(Text)
    validation_errors = Column(Text)
    retry_count = Column(Integer, default=0)
    ai_provider = Column(String(50))
    generated_at = Column(DateTime(timezone=True), server_default=func.now())
    validated_at = Column(DateTime(timezone=True), nullable=True)

    assignment = relationship("Assignment", back_populates="solution")


class Submission(Base):
    __tablename__ = "submissions"

    id = Column(Integer, primary_key=True, index=True)
    assignment_id = Column(Integer, ForeignKey("assignments.id"), unique=True, nullable=False)
    google_doc_id = Column(String(255))
    google_drive_file_id = Column(String(255))
    classroom_attachment_id = Column(String(255))
    attached_at = Column(DateTime(timezone=True), nullable=True)
    submitted_at = Column(DateTime(timezone=True), nullable=True)
    submission_state = Column(SQLEnum(SubmissionState), nullable=True)
    approved_by_user = Column(Boolean, default=False)
    approved_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    assignment = relationship("Assignment", back_populates="submission")
