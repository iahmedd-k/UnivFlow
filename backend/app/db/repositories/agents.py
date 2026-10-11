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
