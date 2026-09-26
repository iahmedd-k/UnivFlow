from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from typing import List
from datetime import datetime, timedelta

from app.db.database import get_db
from app.db.repositories import (
    CourseRepository,
    AssignmentRepository,
    ClassScheduleRepository,
    AttendanceRecordRepository,
    ExamRepository,
    QuizRepository,
    AgentRunRepository,
)
from app.db.models import (
    Course,
    Assignment,
    ClassSchedule,
    AttendanceRecord,
    Exam,
    Quiz,
    AssignmentStatus,
)

router = APIRouter(prefix="/dashboard", tags=["Dashboard"])


@router.get("/overview", response_model=dict)
def get_dashboard_overview(db: Session = Depends(get_db)):
    course_repo = CourseRepository(db)
    assignment_repo = AssignmentRepository(db)
    schedule_repo = ClassScheduleRepository(db)
    attendance_repo = AttendanceRecordRepository(db)
    exam_repo = ExamRepository(db)
    quiz_repo = QuizRepository(db)
    agent_repo = AgentRunRepository(db)

    courses = course_repo.get_all()
    all_assignments = assignment_repo.get_all()
    upcoming_schedules = schedule_repo.get_upcoming(7)
    attendance_records = attendance_repo.get_all()
    upcoming_exams = exam_repo.get_upcoming(30)
    upcoming_quizzes = quiz_repo.get_upcoming(30)
    recent_agent_runs = agent_repo.get_recent(5)

    pending_assignments = [a for a in all_assignments if a.status in [AssignmentStatus.PENDING, AssignmentStatus.READY_FOR_REVIEW]]
    overdue_assignments = [a for a in all_assignments if a.due_at and a.due_at < datetime.now() and a.status not in [AssignmentStatus.SUBMITTED, AssignmentStatus.APPROVED]]
    completed_assignments = [a for a in all_assignments if a.status in [AssignmentStatus.SUBMITTED, AssignmentStatus.APPROVED]]

    avg_attendance = sum(r.percentage for r in attendance_records) / len(attendance_records) if attendance_records else 0

    return {
        "courses_count": len(courses),
        "assignments": {
            "total": len(all_assignments),
            "pending": len(pending_assignments),
            "overdue": len(overdue_assignments),
            "completed": len(completed_assignments),
        },
        "upcoming_classes": len(upcoming_schedules),
        "upcoming_exams": len(upcoming_exams),
        "upcoming_quizzes": len(upcoming_quizzes),
        "average_attendance": round(avg_attendance, 2),
        "recent_agent_runs": [
            {
                "id": r.id,
                "trigger": r.trigger.value,
                "status": r.status.value,
                "started_at": r.started_at,
                "finished_at": r.finished_at,
                "assignments_found": r.assignments_found,
                "changes_found": r.changes_found,
                "notifications_sent": r.notifications_sent,
            }
            for r in recent_agent_runs
        ],
    }


@router.get("/upcoming", response_model=dict)
def get_upcoming_items(
    days: int = 7,
    db: Session = Depends(get_db)
):
    schedule_repo = ClassScheduleRepository(db)
    assignment_repo = AssignmentRepository(db)
    exam_repo = ExamRepository(db)
    quiz_repo = QuizRepository(db)

    schedules = schedule_repo.get_upcoming(days)
    all_assignments = assignment_repo.get_all()
    upcoming_assignments = [
        a for a in all_assignments
        if a.due_at and a.due_at <= datetime.now() + timedelta(days=days)
        and a.status not in [AssignmentStatus.SUBMITTED, AssignmentStatus.APPROVED]
    ]
    exams = exam_repo.get_upcoming(days)
    quizzes = quiz_repo.get_upcoming(days)

    return {
        "classes": [
            {
                "id": s.id,
                "subject": s.subject,
                "date": s.date,
                "start_time": s.start_time,
                "end_time": s.end_time,
                "teacher": s.teacher,
                "room": s.room,
            }
            for s in schedules
        ],
        "assignments": [
            {
                "id": a.id,
                "title": a.title,
                "due_at": a.due_at,
                "course_id": a.course_id,
                "status": a.status.value if a.status else None,
            }
            for a in upcoming_assignments
        ],
        "exams": [
            {
                "id": e.id,
                "title": e.title,
                "date": e.date,
                "time": e.time,
                "room": e.room,
            }
            for e in exams
        ],
        "quizzes": [
            {
                "id": q.id,
                "title": q.title,
                "date": q.date,
                "time": q.time,
                "room": q.room,
            }
            for q in quizzes
        ],
    }


@router.get("/attendance-summary", response_model=dict)
def get_attendance_summary(db: Session = Depends(get_db)):
    attendance_repo = AttendanceRecordRepository(db)
    course_repo = CourseRepository(db)

    records = attendance_repo.get_all()
    courses = course_repo.get_all()

    summary = []
    for record in records:
        course = next((c for c in courses if c.id == record.course_id), None)
        summary.append({
            "course_id": record.course_id,
            "course_name": course.name if course else "Unknown",
            "subject": record.subject,
            "attended": record.attended,
            "total": record.total,
            "percentage": record.percentage,
        })

    overall = sum(r.percentage for r in records) / len(records) if records else 0

    return {
        "overall_attendance": round(overall, 2),
        "per_course": summary,
    }


@router.get("/assignments-by-status", response_model=dict)
def get_assignments_by_status(db: Session = Depends(get_db)):
    assignment_repo = AssignmentRepository(db)
    all_assignments = assignment_repo.get_all()

    by_status = {}
    for status in AssignmentStatus:
        by_status[status.value] = len([a for a in all_assignments if a.status == status])

    return {
        "by_status": by_status,
        "total": len(all_assignments),
    }