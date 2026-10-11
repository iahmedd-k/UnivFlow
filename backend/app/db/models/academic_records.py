from .common import *
from .enums import *


class Exam(Base):
    __tablename__ = "exams"

    id = Column(Integer, primary_key=True, index=True)
    external_id = Column(String(255), unique=True, nullable=False, index=True)
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

    id = Column(Integer, primary_key=True, index=True)
    external_id = Column(String(255), unique=True, nullable=False, index=True)
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

    id = Column(Integer, primary_key=True, index=True)
    external_id = Column(String(255), unique=True, nullable=False, index=True)
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

    id = Column(Integer, primary_key=True, index=True)
    event_type = Column(SQLEnum(ChangeEventType), nullable=False)
    external_id = Column(String(255), index=True)
    subject = Column(String(255))
    old_value = Column(Text)
    new_value = Column(Text)
    date = Column(DateTime(timezone=True))
    notified = Column(Boolean, default=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
