from .common import *
from .enums import *


class ClassSchedule(Base):
    __tablename__ = "class_schedules"

    id = Column(Integer, primary_key=True, index=True)
    external_id = Column(String(255), unique=True, nullable=False, index=True)
    course_id = Column(Integer, ForeignKey("courses.id"), nullable=False)
    subject = Column(String(255))
    date = Column(DateTime(timezone=True), nullable=False)
    start_time = Column(DateTime(timezone=True), nullable=False)
    end_time = Column(DateTime(timezone=True), nullable=False)
    teacher = Column(String(255))
    room = Column(String(100))
    status = Column(String(50), default="scheduled")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    course = relationship("Course", back_populates="schedules")


class TimetableEntry(Base):
    __tablename__ = "timetable_entries"

    id = Column(Integer, primary_key=True, index=True)
    external_id = Column(String(64), unique=True, nullable=False, index=True)
    subject = Column(String(255), nullable=False)
    weekday = Column(Integer, nullable=False)
    start_time = Column(String(10), nullable=False)
    end_time = Column(String(10), nullable=False)
    teacher = Column(String(255))
    room = Column(String(100))
    semester_name = Column(String(120))
    semester_start = Column(DateTime(timezone=True))
    semester_end = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


class AttendanceRecord(Base):
    __tablename__ = "attendance_records"

    id = Column(Integer, primary_key=True, index=True)
    external_id = Column(String(255), unique=True, nullable=False, index=True)
    course_id = Column(Integer, ForeignKey("courses.id"), nullable=False)
    subject = Column(String(255))
    attended = Column(Integer, default=0)
    total = Column(Integer, default=0)
    percentage = Column(Float, default=0.0)
    last_updated = Column(DateTime(timezone=True), server_default=func.now())
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    course = relationship("Course", back_populates="attendance_records")
