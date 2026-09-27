#!/usr/bin/env python3
"""
Database seeding script for Uniflow.
Creates initial admin user, settings, and default configurations.
"""
import os
import sys
from datetime import datetime, timezone

# Add backend to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.db.database import SessionLocal, engine, Base
from app.db.models import Setting, GoogleCredential
from app.core.config import settings as app_settings


def create_tables():
    """Create all database tables"""
    Base.metadata.create_all(bind=engine)
    print("[+] Database tables created")


def seed_settings(db):
    """Seed default settings"""
    default_settings = [
        {
            "key": "semester_start_date",
            "value": "2026-09-01",
            "description": "Semester start date for filtering data (YYYY-MM-DD)"
        },
        {
            "key": "attendance_warning_threshold",
            "value": "75",
            "description": "Attendance percentage threshold for warnings"
        },
        {
            "key": "assignment_check_interval_minutes",
            "value": "30",
            "description": "Interval for checking new assignments"
        },
        {
            "key": "class_reminder_minutes",
            "value": "30",
            "description": "Minutes before class to send reminder"
        },
        {
            "key": "notification_provider",
            "value": "email",
            "description": "Notification provider (email, whatsapp, etc.)"
        },
        {
            "key": "timezone",
            "value": "Asia/Karachi",
            "description": "Default timezone for the application"
        },
    ]

    for s in default_settings:
        existing = db.query(Setting).filter(Setting.key == s["key"]).first()
        if not existing:
            setting = Setting(**s)
            db.add(setting)
            print(f"[+] Created setting: {s['key']}")
        else:
            print(f"[.] Setting exists: {s['key']}")

    db.commit()


def seed_google_credentials(db):
    """Seed Google credentials from environment variables"""
    # Only create if Google OAuth is configured
    if app_settings.google_client_id and app_settings.google_client_secret:
        existing = db.query(GoogleCredential).first()
        if not existing:
            # This is a placeholder - actual credentials come from OAuth flow
            # We just ensure the table is ready
            print("[.] Google credentials table ready (configure via OAuth)")
        else:
            print("[.] Google credentials exist")
    else:
        print("[.] Google OAuth not configured - skipping")


def main():
    print("[SEED] Seeding Uniflow database...")
    print(f"   Environment: {app_settings.environment}")
    print(f"   Database: {app_settings.database_url[:50]}...")

    db = SessionLocal()
    try:
        create_tables()
        seed_settings(db)
        seed_google_credentials(db)
        print("\n[OK] Seeding complete!")
    except Exception as e:
        print(f"\n[ERROR] Seeding failed: {e}")
        db.rollback()
        sys.exit(1)
    finally:
        db.close()


if __name__ == "__main__":
    main()