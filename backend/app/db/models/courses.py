from .common import *
from .enums import *


class Course(Base):
    __tablename__ = "courses"

    id = Column(Integer, primary_key=True, index=True)
    external_id = Column(String(255), unique=True, nullable=False, index=True)
    name = Column(String(500), nullable=False)
    section = Column(String(100))
    description = Column(Text)
    room = Column(String(100))
    teacher_name = Column(String(255))
    course_state = Column(String(50))
    alternate_link = Column(String(500))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())

    assignments = relationship("Assignment", back_populates="course")
    schedules = relationship("ClassSchedule", back_populates="course")
    attendance_records = relationship("AttendanceRecord", back_populates="course")
