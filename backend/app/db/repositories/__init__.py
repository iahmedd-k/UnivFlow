from sqlalchemy.orm import Session
from typing import Optional, List
from app.db.models import (
    GoogleCredential, AgentRun, AgentEvent, Course, Assignment,
    AssignmentMaterial, AssignmentSolution, Submission, ClassSchedule,
    AttendanceRecord, Exam, Quiz, Announcement, ChangeEvent,
    Notification, DailyReport, Setting
)
from datetime import datetime


class GoogleCredentialRepository:
    def __init__(self, db: Session):
        self.db = db

    def get(self) -> Optional[GoogleCredential]:
        return self.db.query(GoogleCredential).first()

    def create_or_update(self, credential_data: dict) -> GoogleCredential:
        cred = self.get()
        if cred:
            for key, value in credential_data.items():
                setattr(cred, key, value)
        else:
            cred = GoogleCredential(**credential_data)
            self.db.add(cred)
        self.db.commit()
        self.db.refresh(cred)
        return cred


class AgentRunRepository:
    def __init__(self, db: Session):
        self.db = db

    def create(self, trigger: str) -> AgentRun:
        run = AgentRun(trigger=trigger)
        self.db.add(run)
        self.db.commit()
        self.db.refresh(run)
        return run

    def update(self, run_id: int, **kwargs) -> Optional[AgentRun]:
        run = self.db.query(AgentRun).filter(AgentRun.id == run_id).first()
        if run:
            for key, value in kwargs.items():
                setattr(run, key, value)
            self.db.commit()
            self.db.refresh(run)
        return run

    def get_recent(self, limit: int = 10) -> List[AgentRun]:
        return self.db.query(AgentRun).order_by(AgentRun.started_at.desc()).limit(limit).all()


class AgentEventRepository:
    def __init__(self, db: Session):
        self.db = db

    def create(self, run_id: int, event_type: str, source: str, status: str, message: str = None, details: str = None) -> AgentEvent:
        event = AgentEvent(
            run_id=run_id,
            event_type=event_type,
            source=source,
            status=status,
            message=message,
            details=details
        )
        self.db.add(event)
        self.db.commit()
        self.db.refresh(event)
        return event

    def get_by_run(self, run_id: int) -> List[AgentEvent]:
        return self.db.query(AgentEvent).filter(AgentEvent.run_id == run_id).all()


class CourseRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_by_external_id(self, external_id: str) -> Optional[Course]:
        return self.db.query(Course).filter(Course.external_id == external_id).first()

    def create_or_update(self, course_data: dict) -> Course:
        course = self.get_by_external_id(course_data["external_id"])
        if course:
            for key, value in course_data.items():
                setattr(course, key, value)
        else:
            course = Course(**course_data)
            self.db.add(course)
        self.db.commit()
        self.db.refresh(course)
        return course

    def get_all(self) -> List[Course]:
        return self.db.query(Course).all()


class AssignmentRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_by_external_id(self, external_id: str) -> Optional[Assignment]:
        return self.db.query(Assignment).filter(Assignment.external_id == external_id).first()

    def get_by_id(self, assignment_id: int) -> Optional[Assignment]:
        return self.db.query(Assignment).filter(Assignment.id == assignment_id).first()

    def create_or_update(self, assignment_data: dict) -> Assignment:
        assignment = self.get_by_external_id(assignment_data["external_id"])
        if assignment:
            for key, value in assignment_data.items():
                setattr(assignment, key, value)
        else:
            assignment = Assignment(**assignment_data)
            self.db.add(assignment)
        self.db.commit()
        self.db.refresh(assignment)
        return assignment

    def get_pending_review(self) -> List[Assignment]:
        return self.db.query(Assignment).filter(Assignment.status == "ready_for_review").all()

    def get_by_status(self, status: str) -> List[Assignment]:
        return self.db.query(Assignment).filter(Assignment.status == status).all()

    def get_all(self) -> List[Assignment]:
        return self.db.query(Assignment).order_by(Assignment.due_at.asc().nullslast()).all()


class AssignmentMaterialRepository:
    def __init__(self, db: Session):
        self.db = db

    def create(self, material_data: dict) -> AssignmentMaterial:
        material = AssignmentMaterial(**material_data)
        self.db.add(material)
        self.db.commit()
        self.db.refresh(material)
        return material

    def get_by_assignment(self, assignment_id: int) -> List[AssignmentMaterial]:
        return self.db.query(AssignmentMaterial).filter(AssignmentMaterial.assignment_id == assignment_id).all()

    def delete_by_assignment(self, assignment_id: int):
        self.db.query(AssignmentMaterial).filter(AssignmentMaterial.assignment_id == assignment_id).delete()
        self.db.commit()


class AssignmentSolutionRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_by_assignment(self, assignment_id: int) -> Optional[AssignmentSolution]:
        return self.db.query(AssignmentSolution).filter(AssignmentSolution.assignment_id == assignment_id).first()

    def create_or_update(self, solution_data: dict) -> AssignmentSolution:
        solution = self.get_by_assignment(solution_data["assignment_id"])
        if solution:
            for key, value in solution_data.items():
                setattr(solution, key, value)
        else:
            solution = AssignmentSolution(**solution_data)
            self.db.add(solution)
        self.db.commit()
        self.db.refresh(solution)
        return solution


class SubmissionRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_by_assignment(self, assignment_id: int) -> Optional[Submission]:
        return self.db.query(Submission).filter(Submission.assignment_id == assignment_id).first()

    def create_or_update(self, submission_data: dict) -> Submission:
        submission = self.get_by_assignment(submission_data["assignment_id"])
        if submission:
            for key, value in submission_data.items():
                setattr(submission, key, value)
        else:
            submission = Submission(**submission_data)
            self.db.add(submission)
        self.db.commit()
        self.db.refresh(submission)
        return submission


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


class ChangeEventRepository:
    def __init__(self, db: Session):
        self.db = db

    def create(self, change_data: dict) -> ChangeEvent:
        change = ChangeEvent(**change_data)
        self.db.add(change)
        self.db.commit()
        self.db.refresh(change)
        return change

    def get_unnotified(self) -> List[ChangeEvent]:
        return self.db.query(ChangeEvent).filter(ChangeEvent.notified == False).all()

    def mark_notified(self, change_id: int):
        change = self.db.query(ChangeEvent).filter(ChangeEvent.id == change_id).first()
        if change:
            change.notified = True
            self.db.commit()


class NotificationRepository:
    def __init__(self, db: Session):
        self.db = db

    def create(self, notification_data: dict) -> Notification:
        notification = Notification(**notification_data)
        self.db.add(notification)
        self.db.commit()
        self.db.refresh(notification)
        return notification

    def get_by_idempotency_key(self, key: str) -> Optional[Notification]:
        return self.db.query(Notification).filter(Notification.idempotency_key == key).first()

    def update_status(self, notification_id: int, status: str, error: str = None, external_id: str = None):
        notification = self.db.query(Notification).filter(Notification.id == notification_id).first()
        if notification:
            notification.status = status
            if error:
                notification.error = error
            if external_id:
                notification.external_id = external_id
            if status == "sent":
                notification.sent_at = datetime.now()
            self.db.commit()

    def get_pending(self) -> List[Notification]:
        return self.db.query(Notification).filter(Notification.status == "pending").all()


class DailyReportRepository:
    def __init__(self, db: Session):
        self.db = db

    def get_by_date(self, report_date: datetime) -> Optional[DailyReport]:
        return self.db.query(DailyReport).filter(DailyReport.report_date == report_date).first()

    def create(self, report_data: dict) -> DailyReport:
        report = DailyReport(**report_data)
        self.db.add(report)
        self.db.commit()
        self.db.refresh(report)
        return report

    def get_recent(self, limit: int = 30) -> List[DailyReport]:
        return self.db.query(DailyReport).order_by(DailyReport.report_date.desc()).limit(limit).all()


class SettingRepository:
    def __init__(self, db: Session):
        self.db = db

    def get(self, key: str) -> Optional[Setting]:
        return self.db.query(Setting).filter(Setting.key == key).first()

    def set(self, key: str, value: str, description: str = None) -> Setting:
        setting = self.get(key)
        if setting:
            setting.value = value
        else:
            setting = Setting(key=key, value=value, description=description)
            self.db.add(setting)
        self.db.commit()
        self.db.refresh(setting)
        return setting

    def get_all(self) -> List[Setting]:
        return self.db.query(Setting).all()