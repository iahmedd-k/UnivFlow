from sqlalchemy import func
from sqlalchemy.orm import Session
from typing import Optional, List
from datetime import datetime
from app.db.models import (
    GoogleCredential, AgentRun, AgentEvent, Course, Assignment,
    AssignmentMaterial, AssignmentTemplate, AssignmentSolution, Submission, ClassSchedule,
    AttendanceRecord, Exam, Quiz, Announcement, ChangeEvent,
    Notification, DailyReport, Setting
)

class ClassScheduleRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_by_external_id(self, external_id: str) -> Optional[ClassSchedule]:
        return self.db.query(ClassSchedule).filter(ClassSchedule.external_id == external_id).first()

    def create_or_update(self, schedule_data: dict) -> ClassSchedule:
        schedule = self.get_by_external_id(schedule_data["external_id"])
        if schedule:
            for key, value in schedule_data.items():
                setattr(schedule, key, value)
        else:
            schedule = ClassSchedule(**schedule_data)
            self.db.add(schedule)
        self.db.commit()
        self.db.refresh(schedule)
        return schedule

    def get_upcoming(self, days: int = 7) -> List[ClassSchedule]:
        from datetime import datetime, timedelta
        now = datetime.now()
        future = now + timedelta(days=days)
        return self.db.query(ClassSchedule).filter(
            ClassSchedule.date >= now,
            ClassSchedule.date <= future
        ).order_by(ClassSchedule.date, ClassSchedule.start_time).all()

    def get_today(self) -> List[ClassSchedule]:
        from datetime import datetime
        today = datetime.now().date()
        return self.db.query(ClassSchedule).filter(
            func.date(ClassSchedule.date) == today
        ).order_by(ClassSchedule.start_time).all()


class AttendanceRecordRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_by_external_id(self, external_id: str) -> Optional[AttendanceRecord]:
        return self.db.query(AttendanceRecord).filter(AttendanceRecord.external_id == external_id).first()

    def create_or_update(self, record_data: dict) -> AttendanceRecord:
        record = self.get_by_external_id(record_data["external_id"])
        if record:
            for key, value in record_data.items():
                setattr(record, key, value)
        else:
            record = AttendanceRecord(**record_data)
            self.db.add(record)
        self.db.commit()
        self.db.refresh(record)
        return record

    def get_all(self) -> List[AttendanceRecord]:
        return self.db.query(AttendanceRecord).all()

    def get_by_course(self, course_id: int) -> Optional[AttendanceRecord]:
        return self.db.query(AttendanceRecord).filter(AttendanceRecord.course_id == course_id).first()


class ExamRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_by_external_id(self, external_id: str) -> Optional[Exam]:
        return self.db.query(Exam).filter(Exam.external_id == external_id).first()

    def create_or_update(self, exam_data: dict) -> Exam:
        exam = self.get_by_external_id(exam_data["external_id"])
        if exam:
            for key, value in exam_data.items():
                setattr(exam, key, value)
        else:
            exam = Exam(**exam_data)
            self.db.add(exam)
        self.db.commit()
        self.db.refresh(exam)
        return exam

    def get_upcoming(self, days: int = 30) -> List[Exam]:
        from datetime import datetime, timedelta
        now = datetime.now()
        future = now + timedelta(days=days)
        return self.db.query(Exam).filter(
            Exam.date >= now,
            Exam.date <= future
        ).order_by(Exam.date).all()


class QuizRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_by_external_id(self, external_id: str) -> Optional[Quiz]:
        return self.db.query(Quiz).filter(Quiz.external_id == external_id).first()

    def create_or_update(self, quiz_data: dict) -> Quiz:
        quiz = self.get_by_external_id(quiz_data["external_id"])
        if quiz:
            for key, value in quiz_data.items():
                setattr(quiz, key, value)
        else:
            quiz = Quiz(**quiz_data)
            self.db.add(quiz)
        self.db.commit()
        self.db.refresh(quiz)
        return quiz

    def get_upcoming(self, days: int = 30) -> List[Quiz]:
        from datetime import datetime, timedelta
        now = datetime.now()
        future = now + timedelta(days=days)
        return self.db.query(Quiz).filter(
            Quiz.date >= now,
            Quiz.date <= future
        ).order_by(Quiz.date).all()


class AnnouncementRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_by_external_id(self, external_id: str) -> Optional[Announcement]:
        return self.db.query(Announcement).filter(Announcement.external_id == external_id).first()

    def get_by_fingerprint(self, fingerprint: str) -> Optional[Announcement]:
        return self.db.query(Announcement).filter(Announcement.fingerprint == fingerprint).first()

    def create_or_update(self, announcement_data: dict) -> Announcement:
        announcement = self.get_by_external_id(announcement_data["external_id"])
        if announcement:
            for key, value in announcement_data.items():
                setattr(announcement, key, value)
        else:
            announcement = Announcement(**announcement_data)
            self.db.add(announcement)
        self.db.commit()
        self.db.refresh(announcement)
        return announcement
