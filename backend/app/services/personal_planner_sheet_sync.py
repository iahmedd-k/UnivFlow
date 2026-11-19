"""Import a public Google Sheet into a user's personal planner.

The source is deliberately restricted to the Google Sheets export endpoint.  This
lets a user share a view-only sheet without giving the application access to
their Google account, and prevents this import feature from fetching arbitrary
URLs.
"""

import json
import re
from datetime import datetime, timezone
from io import BytesIO
from urllib.parse import urlparse

import openpyxl
import requests

from app.db.models import PlannerBill, PlannerExpense, PlannerGoal, PlannerTask, Setting

SOURCE_SETTING = "planner:{user_id}:public_sheet_source"
MAP_SETTING = "planner:{user_id}:public_sheet_row_map"
MAX_EXPORT_BYTES = 20 * 1024 * 1024


def sheet_export_url(value: str) -> str:
    """Return the official XLSX export URL for a public Google Sheets URL."""
    parsed = urlparse((value or "").strip())
    if parsed.scheme != "https" or parsed.hostname != "docs.google.com":
        raise ValueError("Use a public https://docs.google.com/spreadsheets/d/... link.")
    match = re.match(r"^/spreadsheets/d/([A-Za-z0-9_-]+)(?:/|$)", parsed.path)
    if not match:
        raise ValueError("That does not look like a Google Sheets document link.")
    return f"https://docs.google.com/spreadsheets/d/{match.group(1)}/export?format=xlsx"


def _setting(db, key: str, default):
    row = db.query(Setting).filter(Setting.key == key).first()
    if not row or not row.value:
        return default
    try:
        return json.loads(row.value)
    except (TypeError, ValueError):
        return default


def _save_setting(db, key: str, value: dict):
    row = db.query(Setting).filter(Setting.key == key).first()
    if not row:
        row = Setting(key=key)
        db.add(row)
    row.value = json.dumps(value)


def get_sheet_source(db, user_id: str) -> dict:
    return _setting(db, SOURCE_SETTING.format(user_id=user_id), {})


def save_sheet_source(db, user_id: str, url: str) -> dict:
    export_url = sheet_export_url(url)
    source = get_sheet_source(db, user_id)
    source.update({"url": url.strip(), "export_url": export_url, "last_error": ""})
    _save_setting(db, SOURCE_SETTING.format(user_id=user_id), source)
    db.commit()
    return source


def _download_workbook(export_url: str):
    response = requests.get(export_url, timeout=(5, 30), stream=True)
    response.raise_for_status()
    host = (urlparse(response.url).hostname or "").lower()
    if host != "docs.google.com":
        raise ValueError("Google Sheets redirected the export to an unexpected location.")
    payload = bytearray()
    for chunk in response.iter_content(65536):
        payload.extend(chunk)
        if len(payload) > MAX_EXPORT_BYTES:
            raise ValueError("The sheet export is too large (maximum 20 MB).")
    return openpyxl.load_workbook(BytesIO(payload), data_only=True, read_only=True)


def _rows(workbook, sheet_name: str):
    if sheet_name not in workbook.sheetnames:
        return []
    sheet = workbook[sheet_name]
    header = None
    for index, row in enumerate(sheet.iter_rows(values_only=True), start=1):
        values = list(row)
        if header is None:
            if any(str(value or "").strip() for value in values):
                # The supplied planner format uses the first real header row.
                known = {str(value or "").strip().lower() for value in values}
                if {"task", "goal", "item", "date"} & known:
                    header = [str(value or "").strip().lower() for value in values]
            continue
        if not any(value is not None and str(value).strip() for value in values):
            continue
        yield index, {header[i]: values[i] if i < len(values) else None for i in range(len(header))}


def _text(value) -> str:
    return str(value or "").strip()


def _number(value, default=0.0) -> float:
    try:
        return float(value or default)
    except (TypeError, ValueError):
        return default


def _date(value):
    if isinstance(value, datetime):
        return value.replace(tzinfo=value.tzinfo or timezone.utc)
    return None


def _priority(value):
    value = _text(value).lower()
    return {"high": "High", "medium": "Medium", "low": "Low"}.get(value, "Medium")


def _task_status(value):
    return "completed" if _text(value).lower() in {"done", "complete", "completed"} else "open"


def _goal_status(value):
    value = _text(value).lower()
    if value in {"done", "complete", "completed"}:
        return "completed"
    if value in {"paused", "on hold"}:
        return "paused"
    if value in {"abandoned", "cancelled", "canceled"}:
        return "abandoned"
    return "active"


def _bill_status(value):
    value = _text(value).lower()
    return "paid" if value in {"paid", "done", "complete", "completed"} else "partial" if value == "partial" else "pending"


def _record(mapping, section, key, model, db, user_id, **extra_init):
    record_id = mapping.get(section, {}).get(key)
    if record_id:
        item = db.query(model).filter(model.id == record_id, model.user_id == user_id).first()
        if item:
            return item
    # Every planner model requires a title; set harmless temporary values so we
    # can obtain an id before the caller fills in the imported fields.
    kwargs = {"user_id": user_id, "title": "Imported item"}
    if model is PlannerBill:
        kwargs["amount"] = 0.0
    elif model is PlannerExpense:
        kwargs["amount"] = 0.0
        kwargs["spent_at"] = datetime.now(timezone.utc)
    kwargs.update(extra_init)
    item = model(**kwargs)
    db.add(item)
    db.flush()
    mapping.setdefault(section, {})[key] = item.id
    return item


def sync_sheet(db, user_id: str, source: dict | None = None) -> dict:
    """Upsert imported rows. Manually created planner items are never deleted."""
    source = source or get_sheet_source(db, user_id)
    if not source.get("export_url"):
        raise ValueError("Connect a public Google Sheet first.")
    workbook = _download_workbook(source["export_url"])
    mapping = _setting(db, MAP_SETTING.format(user_id=user_id), {})
    counts = {"goals": 0, "tasks": 0, "bills": 0, "expenses": 0}
    goals_by_name = {}

    for row_number, row in _rows(workbook, "Goals"):
        title = _text(row.get("goal"))
        if not title:
            continue
        item = _record(mapping, "goals", f"Goals:{row_number}", PlannerGoal, db, user_id)
        item.title, item.description = title, _text(row.get("why it matters") or row.get("notes"))
        item.priority, item.status, item.target_at = _priority(row.get("priority")), _goal_status(row.get("status")), _date(row.get("target date"))
        item.category, item.check_in_frequency = "Personal", "weekly"
        goals_by_name[title.casefold()] = item
        counts["goals"] += 1

    for row_number, row in _rows(workbook, "Tasks"):
        title = _text(row.get("task"))
        if not title:
            continue
        item = _record(mapping, "tasks", f"Tasks:{row_number}", PlannerTask, db, user_id)
        item.title, item.description = title, _text(row.get("notes"))
        item.priority, item.status, item.due_at = _priority(row.get("priority")), _task_status(row.get("status")), _date(row.get("due date"))
        item.estimated_minutes = round(_number(row.get("est. time (hrs)")) * 60)
        item.category, item.recurrence, item.reminder_offsets = "Personal", "none", "[1440]"
        goal = goals_by_name.get(_text(row.get("goal")).casefold())
        item.goal_id = goal.id if goal else None
        item.completed_at = datetime.now(timezone.utc) if item.status == "completed" else None
        counts["tasks"] += 1

    for row_number, row in _rows(workbook, "Budget"):
        title = _text(row.get("item"))
        if not title:
            continue
        item = _record(mapping, "bills", f"Budget:{row_number}", PlannerBill, db, user_id)
        item.title, item.category, item.notes = title, _text(row.get("category")) or "Bills", _text(row.get("notes"))
        item.amount, item.amount_paid, item.due_at = _number(row.get("amount (pkr)")), _number(row.get("amount paid (pkr)")), _date(row.get("due date"))
        item.status, item.recurrence, item.reminder_offsets = _bill_status(row.get("status")), "monthly" if "recurr" in _text(row.get("type")).lower() else "none", "[1440]"
        item.paid_at = _date(row.get("payment date")) if item.status == "paid" else None
        counts["bills"] += 1

    for row_number, row in _rows(workbook, "Daily Plan"):
        amount, spent_at = _number(row.get("daily expenses pkr")), _date(row.get("date"))
        if amount <= 0 or not spent_at:
            continue
        item = _record(mapping, "expenses", f"Daily Plan:{row_number}", PlannerExpense, db, user_id)
        item.title, item.category, item.amount, item.spent_at = f"Daily expense · {spent_at.date().isoformat()}", "Daily living", amount, spent_at
        item.payment_method, item.notes = "", _text(row.get("notes/wins"))
        counts["expenses"] += 1

    source.update({"last_synced_at": datetime.now(timezone.utc).isoformat(), "last_error": ""})
    _save_setting(db, SOURCE_SETTING.format(user_id=user_id), source)
    _save_setting(db, MAP_SETTING.format(user_id=user_id), mapping)
    db.commit()
    workbook.close()
    return counts
