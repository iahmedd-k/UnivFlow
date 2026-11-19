"""Server-backed personal life planner API."""

import json
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.auth.clerk_auth import require_current_user
from app.db.database import get_db
from app.db.models import PlannerBill, PlannerExpense, PlannerGoal, PlannerProfile, PlannerTask
from app.services.personal_planner_sheet_sync import get_sheet_source, save_sheet_source, sync_sheet

router = APIRouter(prefix="/planner", tags=["Personal planner"])


def _user_id(user: dict) -> str:
    return str((user or {}).get("id") or "dev_student_user")


def _utc(value: Optional[datetime]) -> Optional[datetime]:
    if not value:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _serialize_task(item: PlannerTask) -> dict:
    return {"id": item.id, "title": item.title, "description": item.description or "", "category": item.category,
            "priority": item.priority, "status": item.status, "due_at": item.due_at, "estimated_minutes": item.estimated_minutes,
            "goal_id": item.goal_id, "recurrence": item.recurrence, "reminder_offsets": json.loads(item.reminder_offsets or "[]"),
            "completed_at": item.completed_at}


def _serialize_goal(item: PlannerGoal) -> dict:
    return {"id": item.id, "title": item.title, "description": item.description or "", "category": item.category,
            "priority": item.priority, "status": item.status, "target_value": item.target_value, "current_value": item.current_value,
            "unit": item.unit or "", "start_at": item.start_at, "target_at": item.target_at, "check_in_frequency": item.check_in_frequency}


def _serialize_expense(item: PlannerExpense) -> dict:
    return {"id": item.id, "title": item.title, "category": item.category, "amount": item.amount, "spent_at": item.spent_at,
            "payment_method": item.payment_method or "", "notes": item.notes or ""}


def _serialize_bill(item: PlannerBill) -> dict:
    return {"id": item.id, "title": item.title, "category": item.category, "amount": item.amount, "amount_paid": item.amount_paid,
            "remaining": max(0, item.amount - item.amount_paid), "due_at": item.due_at, "status": item.status,
            "recurrence": item.recurrence, "reminder_offsets": json.loads(item.reminder_offsets or "[]"), "notes": item.notes or "", "paid_at": item.paid_at}


class TaskInput(BaseModel):
    title: str = Field(min_length=1, max_length=500)
    description: str = ""
    category: str = "Personal"
    priority: str = "Medium"
    status: str = "open"
    due_at: Optional[datetime] = None
    estimated_minutes: int = Field(default=0, ge=0, le=10080)
    goal_id: Optional[int] = None
    recurrence: str = "none"
    reminder_offsets: list[int] = []


class GoalInput(BaseModel):
    title: str = Field(min_length=1, max_length=500)
    description: str = ""
    category: str = "Personal"
    priority: str = "Medium"
    status: str = "active"
    target_value: Optional[float] = Field(default=None, ge=0)
    current_value: float = Field(default=0, ge=0)
    unit: str = ""
    start_at: Optional[datetime] = None
    target_at: Optional[datetime] = None
    check_in_frequency: str = "weekly"


class ExpenseInput(BaseModel):
    title: str = Field(min_length=1, max_length=500)
    category: str = "Personal"
    amount: float = Field(gt=0)
    spent_at: datetime
    payment_method: str = ""
    notes: str = ""


class BillInput(BaseModel):
    title: str = Field(min_length=1, max_length=500)
    category: str = "Bills"
    amount: float = Field(gt=0)
    amount_paid: float = Field(default=0, ge=0)
    due_at: Optional[datetime] = None
    status: str = "pending"
    recurrence: str = "none"
    reminder_offsets: list[int] = []
    notes: str = ""


class ProfileInput(BaseModel):
    monthly_budget: float = Field(default=0, ge=0)
    currency: str = "PKR"
    timezone: str = ""
    daily_digest_enabled: bool = True
    weekly_review_enabled: bool = True
    quiet_hours_start: str = ""
    quiet_hours_end: str = ""


class SheetSourceInput(BaseModel):
    url: str = Field(min_length=20, max_length=2000)


@router.get("/overview")
def overview(db: Session = Depends(get_db), user: dict = Depends(require_current_user)):
    uid = _user_id(user)
    now = datetime.now(timezone.utc)
    end = now + timedelta(days=7)
    tasks = db.query(PlannerTask).filter(PlannerTask.user_id == uid).order_by(PlannerTask.due_at.asc().nullslast()).all()
    goals = db.query(PlannerGoal).filter(PlannerGoal.user_id == uid).order_by(PlannerGoal.target_at.asc().nullslast()).all()
    expenses = db.query(PlannerExpense).filter(PlannerExpense.user_id == uid).order_by(PlannerExpense.spent_at.desc()).limit(100).all()
    bills = db.query(PlannerBill).filter(PlannerBill.user_id == uid).order_by(PlannerBill.due_at.asc().nullslast()).all()
    profile = db.query(PlannerProfile).filter(PlannerProfile.user_id == uid).first() or PlannerProfile(user_id=uid)
    if not profile.id:
        db.add(profile); db.commit(); db.refresh(profile)
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    month_spend = sum(item.amount for item in expenses if _utc(item.spent_at) and _utc(item.spent_at) >= month_start)
    overdue = [item for item in tasks if item.status != "completed" and item.due_at and _utc(item.due_at) < now]
    due_soon = [item for item in tasks if item.status != "completed" and item.due_at and now <= _utc(item.due_at) <= end]
    return {"tasks": [_serialize_task(x) for x in tasks], "goals": [_serialize_goal(x) for x in goals],
            "expenses": [_serialize_expense(x) for x in expenses], "bills": [_serialize_bill(x) for x in bills],
            "profile": {"monthly_budget": profile.monthly_budget, "currency": profile.currency, "timezone": profile.timezone or "", "daily_digest_enabled": profile.daily_digest_enabled, "weekly_review_enabled": profile.weekly_review_enabled, "quiet_hours_start": profile.quiet_hours_start or "", "quiet_hours_end": profile.quiet_hours_end or ""},
            "sheet_source": get_sheet_source(db, uid),
            "summary": {"month_spend": month_spend, "overdue_tasks": len(overdue), "upcoming_tasks": len(due_soon), "pending_bills": sum(max(0, x.amount - x.amount_paid) for x in bills if x.status != "paid")}}


@router.get("/sheet-source")
def sheet_source(db: Session = Depends(get_db), user: dict = Depends(require_current_user)):
    return get_sheet_source(db, _user_id(user))


@router.put("/sheet-source")
def configure_sheet_source(payload: SheetSourceInput, db: Session = Depends(get_db), user: dict = Depends(require_current_user)):
    try:
        return save_sheet_source(db, _user_id(user), payload.url)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error))


@router.post("/sheet-source/sync")
def sync_sheet_source(db: Session = Depends(get_db), user: dict = Depends(require_current_user)):
    uid = _user_id(user)
    try:
        return {"ok": True, "counts": sync_sheet(db, uid), "sheet_source": get_sheet_source(db, uid)}
    except Exception as error:
        db.rollback()
        source = get_sheet_source(db, uid)
        source["last_error"] = str(error)
        # Preserve the original source configuration even if its data is inaccessible.
        from app.services.personal_planner_sheet_sync import _save_setting
        _save_setting(db, f"planner:{uid}:public_sheet_source", source)
        db.commit()
        raise HTTPException(status_code=422, detail=f"Could not sync this Google Sheet: {error}")


def _owned_or_404(db: Session, model, record_id: int, uid: str):
    item = db.query(model).filter(model.id == record_id, model.user_id == uid).first()
    if not item: raise HTTPException(status_code=404, detail="Planner item not found")
    return item


@router.post("/tasks")
def create_task(payload: TaskInput, db: Session = Depends(get_db), user: dict = Depends(require_current_user)):
    uid = _user_id(user)
    if payload.goal_id: _owned_or_404(db, PlannerGoal, payload.goal_id, uid)
    item = PlannerTask(user_id=uid, **payload.model_dump(exclude={"reminder_offsets", "due_at"}), due_at=_utc(payload.due_at), reminder_offsets=json.dumps(sorted(set(payload.reminder_offsets))))
    db.add(item); db.commit(); db.refresh(item); return _serialize_task(item)


@router.patch("/tasks/{task_id}")
def update_task(task_id: int, payload: TaskInput, db: Session = Depends(get_db), user: dict = Depends(require_current_user)):
    uid = _user_id(user)
    if payload.goal_id:
        _owned_or_404(db, PlannerGoal, payload.goal_id, uid)
    item = _owned_or_404(db, PlannerTask, task_id, uid)
    for key, value in payload.model_dump(exclude={"reminder_offsets"}).items(): setattr(item, key, _utc(value) if key == "due_at" else value)
    item.reminder_offsets = json.dumps(sorted(set(payload.reminder_offsets)))
    item.completed_at = datetime.now(timezone.utc) if payload.status == "completed" else None
    db.commit(); db.refresh(item); return _serialize_task(item)


@router.delete("/tasks/{task_id}")
def delete_task(task_id: int, db: Session = Depends(get_db), user: dict = Depends(require_current_user)):
    db.delete(_owned_or_404(db, PlannerTask, task_id, _user_id(user))); db.commit(); return {"ok": True}


@router.post("/goals")
def create_goal(payload: GoalInput, db: Session = Depends(get_db), user: dict = Depends(require_current_user)):
    item = PlannerGoal(user_id=_user_id(user), **payload.model_dump()); db.add(item); db.commit(); db.refresh(item); return _serialize_goal(item)


@router.patch("/goals/{goal_id}")
def update_goal(goal_id: int, payload: GoalInput, db: Session = Depends(get_db), user: dict = Depends(require_current_user)):
    item = _owned_or_404(db, PlannerGoal, goal_id, _user_id(user))
    for key, value in payload.model_dump().items(): setattr(item, key, value)
    db.commit(); db.refresh(item); return _serialize_goal(item)


@router.post("/expenses")
def create_expense(payload: ExpenseInput, db: Session = Depends(get_db), user: dict = Depends(require_current_user)):
    item = PlannerExpense(user_id=_user_id(user), **payload.model_dump(exclude={"spent_at"}), spent_at=_utc(payload.spent_at)); db.add(item); db.commit(); db.refresh(item); return _serialize_expense(item)


@router.delete("/expenses/{expense_id}")
def delete_expense(expense_id: int, db: Session = Depends(get_db), user: dict = Depends(require_current_user)):
    db.delete(_owned_or_404(db, PlannerExpense, expense_id, _user_id(user))); db.commit(); return {"ok": True}


@router.post("/bills")
def create_bill(payload: BillInput, db: Session = Depends(get_db), user: dict = Depends(require_current_user)):
    item = PlannerBill(user_id=_user_id(user), **payload.model_dump(exclude={"reminder_offsets", "due_at"}), due_at=_utc(payload.due_at), reminder_offsets=json.dumps(sorted(set(payload.reminder_offsets))))
    db.add(item); db.commit(); db.refresh(item); return _serialize_bill(item)


@router.patch("/bills/{bill_id}")
def update_bill(bill_id: int, payload: BillInput, db: Session = Depends(get_db), user: dict = Depends(require_current_user)):
    item = _owned_or_404(db, PlannerBill, bill_id, _user_id(user))
    for key, value in payload.model_dump(exclude={"reminder_offsets"}).items(): setattr(item, key, _utc(value) if key == "due_at" else value)
    item.reminder_offsets = json.dumps(sorted(set(payload.reminder_offsets)))
    item.paid_at = datetime.now(timezone.utc) if payload.status == "paid" else None
    db.commit(); db.refresh(item); return _serialize_bill(item)


@router.patch("/profile")
def update_profile(payload: ProfileInput, db: Session = Depends(get_db), user: dict = Depends(require_current_user)):
    uid = _user_id(user); item = db.query(PlannerProfile).filter(PlannerProfile.user_id == uid).first() or PlannerProfile(user_id=uid)
    for key, value in payload.model_dump().items(): setattr(item, key, value or None if key in {"timezone", "quiet_hours_start", "quiet_hours_end"} else value)
    db.add(item); db.commit(); return {"ok": True}
