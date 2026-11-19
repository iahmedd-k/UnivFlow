"""Personal life planner records, scoped to an individual user."""

from .common import *


class PlannerTask(Base):
    __tablename__ = "planner_tasks"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(String(255), nullable=False, index=True)
    title = Column(String(500), nullable=False)
    description = Column(Text)
    category = Column(String(80), nullable=False, default="Personal")
    priority = Column(String(20), nullable=False, default="Medium")
    status = Column(String(20), nullable=False, default="open")
    due_at = Column(DateTime(timezone=True), index=True)
    estimated_minutes = Column(Integer, nullable=False, default=0)
    goal_id = Column(Integer, ForeignKey("planner_goals.id"), nullable=True, index=True)
    recurrence = Column(String(30), nullable=False, default="none")
    reminder_offsets = Column(Text, nullable=True)  # JSON list of minutes before due time
    completed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


class PlannerGoal(Base):
    __tablename__ = "planner_goals"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(String(255), nullable=False, index=True)
    title = Column(String(500), nullable=False)
    description = Column(Text)
    category = Column(String(80), nullable=False, default="Personal")
    priority = Column(String(20), nullable=False, default="Medium")
    status = Column(String(20), nullable=False, default="active")
    target_value = Column(Float, nullable=True)
    current_value = Column(Float, nullable=False, default=0)
    unit = Column(String(80), nullable=True)
    start_at = Column(DateTime(timezone=True), nullable=True)
    target_at = Column(DateTime(timezone=True), nullable=True, index=True)
    check_in_frequency = Column(String(30), nullable=False, default="weekly")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


class PlannerExpense(Base):
    __tablename__ = "planner_expenses"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(String(255), nullable=False, index=True)
    title = Column(String(500), nullable=False)
    category = Column(String(80), nullable=False, default="Personal")
    amount = Column(Float, nullable=False)
    spent_at = Column(DateTime(timezone=True), nullable=False, index=True)
    payment_method = Column(String(80), nullable=True)
    notes = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class PlannerBill(Base):
    __tablename__ = "planner_bills"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(String(255), nullable=False, index=True)
    title = Column(String(500), nullable=False)
    category = Column(String(80), nullable=False, default="Bills")
    amount = Column(Float, nullable=False)
    amount_paid = Column(Float, nullable=False, default=0)
    due_at = Column(DateTime(timezone=True), nullable=True, index=True)
    status = Column(String(20), nullable=False, default="pending")
    recurrence = Column(String(30), nullable=False, default="none")
    reminder_offsets = Column(Text, nullable=True)
    notes = Column(Text)
    paid_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())


class PlannerProfile(Base):
    __tablename__ = "planner_profiles"
    __table_args__ = (UniqueConstraint("user_id", name="uq_planner_profiles_user"),)

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(String(255), nullable=False, index=True)
    monthly_budget = Column(Float, nullable=False, default=0)
    currency = Column(String(8), nullable=False, default="PKR")
    timezone = Column(String(64), nullable=True)
    daily_digest_enabled = Column(Boolean, nullable=False, default=True)
    weekly_review_enabled = Column(Boolean, nullable=False, default=True)
    quiet_hours_start = Column(String(5), nullable=True)
    quiet_hours_end = Column(String(5), nullable=True)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())
