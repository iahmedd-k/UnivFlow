from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List, Optional
from datetime import datetime

from app.db.database import get_db
from app.db.repositories import DailyReportRepository, AnnouncementRepository
from app.db.models import DailyReport, Announcement
from app.auth.clerk_auth import get_current_user_optional
from app.auth.ownership import require_user_id, user_owner_ids

router = APIRouter(prefix="/documents", tags=["Documents"])


@router.get("/daily-reports", response_model=List[dict])
def get_daily_reports(
    limit: int = 30,
    db: Session = Depends(get_db),
    clerk_user: Optional[dict] = Depends(get_current_user_optional),
):
    user_id = require_user_id(clerk_user)
    owners = user_owner_ids(user_id)
    reports = (
        db.query(DailyReport)
        .filter(DailyReport.user_id.in_(owners))
        .order_by(DailyReport.report_date.desc())
        .limit(limit)
        .all()
    )
    return [
        {
            "id": r.id,
            "report_date": r.report_date,
            "google_document_id": r.google_document_id,
            "google_drive_file_id": r.google_drive_file_id,
            "content": r.content,
            "status": r.status,
            "created_at": r.created_at,
        }
        for r in reports
    ]


@router.get("/daily-reports/{report_id}", response_model=dict)
def get_daily_report(
    report_id: int,
    db: Session = Depends(get_db),
    clerk_user: Optional[dict] = Depends(get_current_user_optional),
):
    user_id = require_user_id(clerk_user)
    report = (
        db.query(DailyReport)
        .filter(DailyReport.id == report_id, DailyReport.user_id.in_(user_owner_ids(user_id)))
        .first()
    )
    if not report:
        raise HTTPException(status_code=404, detail="Daily report not found")
    return {
        "id": report.id,
        "report_date": report.report_date,
        "google_document_id": report.google_document_id,
        "google_drive_file_id": report.google_drive_file_id,
        "content": report.content,
        "status": report.status,
        "created_at": report.created_at,
    }


@router.get("/daily-reports/by-date", response_model=dict)
def get_daily_report_by_date(
    date: datetime,
    db: Session = Depends(get_db),
    clerk_user: Optional[dict] = Depends(get_current_user_optional),
):
    user_id = require_user_id(clerk_user)
    report = (
        db.query(DailyReport)
        .filter(DailyReport.report_date == date, DailyReport.user_id.in_(user_owner_ids(user_id)))
        .first()
    )
    if not report:
        raise HTTPException(status_code=404, detail="Daily report not found for this date")
    return {
        "id": report.id,
        "report_date": report.report_date,
        "google_document_id": report.google_document_id,
        "google_drive_file_id": report.google_drive_file_id,
        "content": report.content,
        "status": report.status,
        "created_at": report.created_at,
    }


@router.get("/announcements", response_model=List[dict])
def get_announcements(
    limit: int = 50,
    db: Session = Depends(get_db),
    clerk_user: Optional[dict] = Depends(get_current_user_optional),
):
    user_id = require_user_id(clerk_user)
    announcements = (
        db.query(Announcement)
        .filter(Announcement.user_id.in_(user_owner_ids(user_id)))
        .order_by(Announcement.published_at.desc().nullslast())
        .limit(limit)
        .all()
    )
    return [
        {
            "id": a.id,
            "external_id": a.external_id,
            "title": a.title,
            "content": a.content,
            "source": a.source,
            "fingerprint": a.fingerprint,
            "published_at": a.published_at,
            "created_at": a.created_at,
        }
        for a in announcements
    ]


@router.get("/announcements/{announcement_id}", response_model=dict)
def get_announcement(
    announcement_id: int,
    db: Session = Depends(get_db),
    clerk_user: Optional[dict] = Depends(get_current_user_optional),
):
    user_id = require_user_id(clerk_user)
    announcement = (
        db.query(Announcement)
        .filter(Announcement.id == announcement_id, Announcement.user_id.in_(user_owner_ids(user_id)))
        .first()
    )
    if not announcement:
        raise HTTPException(status_code=404, detail="Announcement not found")
    return {
        "id": announcement.id,
        "external_id": announcement.external_id,
        "title": announcement.title,
        "content": announcement.content,
        "source": announcement.source,
        "fingerprint": announcement.fingerprint,
        "published_at": announcement.published_at,
        "created_at": announcement.created_at,
    }