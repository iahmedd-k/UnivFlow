from .common import *
from .enums import *


class Exam(Base):
    __tablename__ = "exams"
    __table_args__ = (UniqueConstraint("user_id", "external_id", name="uq_exams_user_external_id"),)

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(String(255), nullable=False, default="legacy", index=True)
    external_id = Column(String(255), nullable=False, index=True)
    course_id = Column(Integer, ForeignKey("courses.id"), nullable=True)
    title = Column(String(500))
    date = Column(DateTime(timezone=True))
    time = Column(String(50))
    room = Column(String(100))
    status = Column(String(50))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


class Quiz(Base):
    __tablename__ = "quizzes"
    __table_args__ = (UniqueConstraint("user_id", "external_id", name="uq_quizzes_user_external_id"),)

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(String(255), nullable=False, default="legacy", index=True)
    external_id = Column(String(255), nullable=False, index=True)
    course_id = Column(Integer, ForeignKey("courses.id"), nullable=True)
    title = Column(String(500))
    date = Column(DateTime(timezone=True))
    time = Column(String(50))
    room = Column(String(100))
    status = Column(String(50))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


class Announcement(Base):
    __tablename__ = "announcements"
    __table_args__ = (UniqueConstraint("user_id", "external_id", name="uq_announcements_user_external_id"),)

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(String(255), nullable=False, default="legacy", index=True)
    external_id = Column(String(255), nullable=False, index=True)
    course_id = Column(Integer, nullable=True)
    title = Column(String(500))
    content = Column(Text)
    url = Column(String(1000))
    source = Column(String(50))
    fingerprint = Column(String(64), nullable=False, index=True)
    published_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class ChangeEvent(Base):
    __tablename__ = "change_events"
    __table_args__ = (UniqueConstraint("user_id", "external_id", name="uq_change_events_user_external_id"),)

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(String(255), nullable=False, default="legacy", index=True)
    external_id = Column(String(255), index=True)
    subject = Column(String(255))
    old_value = Column(Text)
    new_value = Column(Text)
    date = Column(DateTime(timezone=True))
    notified = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
