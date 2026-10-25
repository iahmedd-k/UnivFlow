"""Normalized user preferences and sync settings helper.
Eliminates ad-hoc string formatting and scattered JSON parsing across routers.
"""

import json
from datetime import datetime, timezone
from typing import Any, Optional, Dict
from sqlalchemy.orm import Session
from app.db.models import Setting
from app.core.logging import logger


def _setting_key(user_id: str, domain: str, key_name: str) -> str:
    return f"{domain}:{user_id}:{key_name}"


def get_user_setting(
    db: Session,
    user_id: str,
    domain: str,
    key_name: str,
    default: Any = None,
) -> Any:
    key = _setting_key(user_id, domain, key_name)
    row = db.query(Setting).filter(Setting.key == key).first()
    if not row or row.value is None:
        return default
    raw = row.value.strip()
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return raw.replace('"', '')


def set_user_setting(
    db: Session,
    user_id: str,
    domain: str,
    key_name: str,
    value: Any,
    description: str = "",
) -> Setting:
    key = _setting_key(user_id, domain, key_name)
    row = db.query(Setting).filter(Setting.key == key).first()
    if not row:
        row = Setting(key=key, description=description or f"{domain} setting {key_name} for {user_id}")
        db.add(row)

    if value is None:
        row.value = None
    elif isinstance(value, (dict, list, bool, int, float)):
        row.value = json.dumps(value)
    else:
        row.value = str(value).strip().replace('"', '')

    db.commit()
    return row


def get_semester_start_date(
    db: Session,
    user_id: str = "default",
    override: Optional[str] = None,
) -> datetime:
    """Return timezone-aware semester start date for coursework cutoff."""
    val = override
    if not val:
        val = get_user_setting(db, user_id, "classroom", "semester_start_date")
    if val:
        try:
            val_str = str(val).strip().replace('"', '')
            if len(val_str) == 10:
                dt = datetime.fromisoformat(f"{val_str}T00:00:00+00:00")
            else:
                dt = datetime.fromisoformat(val_str.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except Exception as e:
            logger.debug(f"Could not parse semester start date '{val}': {e}")

    # Fallback to current semester boundary (Sept 1 for Fall, Feb 1 for Spring)
    now = datetime.now(timezone.utc)
    year = now.year
    if now.month >= 8:
        return datetime(year, 9, 1, 0, 0, 0, tzinfo=timezone.utc)
    return datetime(year, 2, 1, 0, 0, 0, tzinfo=timezone.utc)


def set_semester_start_date(db: Session, user_id: str, start_date: Optional[str]) -> None:
    set_user_setting(
        db,
        user_id,
        "classroom",
        "semester_start_date",
        start_date,
        description=f"Semester start date filter for user {user_id}",
    )


def get_sync_status(db: Session, user_id: str) -> Dict[str, Any]:
    return get_user_setting(db, user_id, "classroom", "sync_status", default={"status": "idle"})


def update_sync_status(db: Session, user_id: str, status_dict: Dict[str, Any]) -> None:
    set_user_setting(
        db,
        user_id,
        "classroom",
        "sync_status",
        status_dict,
        description=f"Most recent Google Classroom sync run for {user_id}",
    )
