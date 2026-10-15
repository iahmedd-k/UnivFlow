from .common import *
from .enums import *


class PortalSyncJob(Base):
    __tablename__ = "portal_sync_jobs"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(String(255), nullable=False, index=True)
    job_id = Column(String(64), nullable=False, unique=True, index=True)
    status = Column(String(32), nullable=False, default="queued")  # queued, running, completed, failed, cancelled
    sync_type = Column(String(32), nullable=False, default="full")  # full, attendance, timetable, grades
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    started_at = Column(DateTime(timezone=True), nullable=True)
    finished_at = Column(DateTime(timezone=True), nullable=True)
    error = Column(Text, nullable=True)
    result = Column(Text, nullable=True)  # JSON serialized result
    retry_count = Column(Integer, default=0)
    max_retries = Column(Integer, default=3)
    next_retry_at = Column(DateTime(timezone=True), nullable=True)