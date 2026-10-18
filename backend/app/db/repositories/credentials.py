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
from app.core.security import encrypt_token_if_needed

class GoogleCredentialRepository:
    def __init__(self, db: Session):
        self.db = db

    def get(self, user_id: str = "legacy") -> Optional[GoogleCredential]:
        return self.db.query(GoogleCredential).filter(GoogleCredential.user_id == user_id).first()

    def create_or_update(self, user_id: str, credential_data: dict) -> GoogleCredential:
        credential_data = dict(credential_data)
        credential_data["access_token"] = encrypt_token_if_needed(credential_data.get("access_token"))
        credential_data["refresh_token"] = encrypt_token_if_needed(credential_data.get("refresh_token"))
        cred = self.get(user_id)
        if cred:
            for key, value in credential_data.items():
                setattr(cred, key, value)
        else:
            cred = GoogleCredential(user_id=user_id, **credential_data)
            self.db.add(cred)
        self.db.commit()
        self.db.refresh(cred)
        return cred
