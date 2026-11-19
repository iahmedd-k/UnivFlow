from datetime import datetime, timezone
import openpyxl
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.endpoints.planner import (
    BillInput,
    ExpenseInput,
    GoalInput,
    TaskInput,
    create_bill,
    create_expense,
    create_goal,
    create_task,
    overview,
)
from app.db.database import Base
import app.db.models  # noqa: F401
from app.services import personal_planner_sheet_sync as sheet_sync


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(engine)


def test_personal_planner_is_user_scoped_and_summarizes_records(db_session):
    owner = {"id": "planner-owner"}
    other = {"id": "planner-other"}
    goal = create_goal(GoalInput(title="Save for a laptop", target_value=100000, unit="PKR"), db=db_session, user=owner)
    create_task(TaskInput(title="Transfer savings", due_at=datetime.now(timezone.utc), goal_id=goal["id"]), db=db_session, user=owner)
    create_expense(ExpenseInput(title="Groceries", amount=1200, spent_at=datetime.now(timezone.utc)), db=db_session, user=owner)
    create_bill(BillInput(title="Internet bill", amount=2500, due_at=datetime.now(timezone.utc)), db=db_session, user=owner)
    create_task(TaskInput(title="Private task", due_at=datetime.now(timezone.utc)), db=db_session, user=other)

    result = overview(db=db_session, user=owner)

    assert [task["title"] for task in result["tasks"]] == ["Transfer savings"]
    assert result["goals"][0]["title"] == "Save for a laptop"
    assert result["summary"]["month_spend"] == 1200
    assert result["summary"]["pending_bills"] == 2500


def test_public_sheet_sync_imports_weekly_planner_tabs_without_touching_manual_data(db_session, monkeypatch):
    workbook = openpyxl.Workbook()
    goals = workbook.active; goals.title = "Goals"
    goals.append(["Goal", "Why It Matters", "Target Date", "Priority", "Status"])
    goals.append(["Save for travel", "Take a trip", datetime(2027, 1, 1), "High", "In Progress"])
    tasks = workbook.create_sheet("Tasks")
    tasks.append(["#", "Task", "Goal", "Due Date", "Priority", "Status", "Est. Time (hrs)", "Notes"])
    tasks.append([1, "Research flights", "Save for travel", datetime(2026, 12, 1), "Medium", "Open", 2, "Compare prices"])
    budget = workbook.create_sheet("Budget")
    budget.append(["Item", "Category", "Type", "Amount (PKR)", "Amount Paid (PKR)", "Status", "Due Date", "Payment Date", "Notes"])
    budget.append(["Phone bill", "Utilities", "Recurring", 1500, 0, "Pending", datetime(2026, 12, 2), None, "Monthly"])
    daily = workbook.create_sheet("Daily Plan")
    daily.append(["Date", "Daily Expenses PKR", "Notes/Wins"])
    daily.append([datetime(2026, 11, 19), 500, "Groceries"])

    monkeypatch.setattr(sheet_sync, "_download_workbook", lambda _: workbook)
    sheet_sync.save_sheet_source(db_session, "planner-owner", "https://docs.google.com/spreadsheets/d/test_sheet_id/edit")
    assert sheet_sync.sync_sheet(db_session, "planner-owner") == {"goals": 1, "tasks": 1, "bills": 1, "expenses": 1}
    create_task(TaskInput(title="Manual task"), db=db_session, user={"id": "planner-owner"})
    # A repeat sync updates the same imported rows rather than duplicating them.
    sheet_sync.sync_sheet(db_session, "planner-owner")
    result = overview(db=db_session, user={"id": "planner-owner"})
    assert {task["title"] for task in result["tasks"]} == {"Research flights", "Manual task"}
    assert result["goals"][0]["title"] == "Save for travel"
    assert result["bills"][0]["title"] == "Phone bill"
    assert result["expenses"][0]["amount"] == 500
