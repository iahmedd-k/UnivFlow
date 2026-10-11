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
