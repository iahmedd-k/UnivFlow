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
