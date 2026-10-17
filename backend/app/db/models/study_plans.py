"""Persistent study plans and their day-by-day sessions."""

from .common import *


class StudyPlan(Base):
    __tablename__ = "study_plans"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(String(255), nullable=False, index=True)
    title = Column(String(500), nullable=False)
    exam_title = Column(String(300), nullable=True)
    exam_date = Column(DateTime(timezone=True), nullable=True)
    syllabus = Column(Text, nullable=True)
    # Syllabus topics extracted by the planner (JSON array of {title, difficulty, weight})
    topics = Column(Text, nullable=True)  # JSON
    # Plan preferences (JSON): hours_per_day, session_minutes, plan_mode, start_date, end_date
    preferences = Column(Text, nullable=True)  # JSON
    # Coverage percentage / completion stats (JSON)
    stats = Column(Text, nullable=True)  # JSON
    # Human-readable plan summary (markdown)
    summary = Column(Text, nullable=True)
    status = Column(String(30), nullable=False, default="active")  # active | completed | archived
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    sessions = relationship("StudyPlanSession", back_populates="plan", cascade="all, delete-orphan")


class StudyPlanSession(Base):
    __tablename__ = "study_plan_sessions"

    id = Column(Integer, primary_key=True, index=True)
    plan_id = Column(Integer, ForeignKey("study_plans.id"), nullable=False, index=True)
    # Calendar date for this session (YYYY-MM-DD stored as date at midnight UTC)
    session_date = Column(DateTime(timezone=True), nullable=False, index=True)
    # 'learn' | 'review' | 'final_review'
    session_type = Column(String(20), nullable=False)
    topic = Column(String(500), nullable=False)
    duration_minutes = Column(Integer, nullable=False, default=0)
    order_index = Column(Integer, nullable=False, default=0)  # ordering within the day
    # 'pending' | 'done' | 'partial' | 'missed'
    status = Column(String(20), nullable=False, default="pending")
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    plan = relationship("StudyPlan", back_populates="sessions")
