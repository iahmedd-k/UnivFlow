from .common import *
from .enums import *


class AgentRun(Base):
    __tablename__ = "agent_runs"

    id = Column(Integer, primary_key=True, index=True)
    trigger = Column(SQLEnum(AgentRunTrigger), nullable=False)
    status = Column(SQLEnum(AgentRunStatus), default=AgentRunStatus.RUNNING)
    started_at = Column(DateTime(timezone=True), server_default=func.now())
    finished_at = Column(DateTime(timezone=True), nullable=True)
    duration_seconds = Column(Integer, nullable=True)
    assignments_found = Column(Integer, default=0)
    changes_found = Column(Integer, default=0)
    notifications_sent = Column(Integer, default=0)
    errors = Column(Text, nullable=True)
    error_details = Column(Text, nullable=True)

    events = relationship("AgentEvent", back_populates="run")


class AgentEvent(Base):
    __tablename__ = "agent_events"

    id = Column(Integer, primary_key=True, index=True)
    run_id = Column(Integer, ForeignKey("agent_runs.id"), nullable=False)
    event_type = Column(String(100), nullable=False)
    source = Column(String(50), nullable=False)
    status = Column(String(50), nullable=False)
    message = Column(Text)
    details = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    run = relationship("AgentRun", back_populates="events")
