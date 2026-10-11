import math
import re
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.core.config import settings
from app.core.logging import logger
from app.db.models import (
    AttendanceRecord,
    ClassSchedule,
    Course,
    Notification,
    NotificationStatus,
    Setting,
    TimetableEntry,
)
from app.db.models.assignments import Assignment, Submission
from app.db.models.enums import CourseworkState, SubmissionState
from app.services.email import send_email


def normalize_subject_name(name: str) -> str:
    """Normalize course name by stripping course codes, section tags, and trailing numbers."""
    if not name:
        return ""
    # Strip prefixes like 'F-26-' or 'CS-101-'
    cleaned = re.sub(r"^[A-Z0-9]+-[0-9]+-", "", name, flags=re.IGNORECASE)
    # Strip trailing numbers like '-1971', '-768'
    cleaned = re.sub(r"-[0-9]+$", "", cleaned)
    # Normalize whitespace
    return re.sub(r"\s+", " ", cleaned).strip().lower()


def is_lab_subject(name: str) -> bool:
    """Check if subject is a practical/lab class."""
    return bool(re.search(r"\blab\b", name or "", re.IGNORECASE))


def match_attendance_to_timetable(
    tt_subject: str, attendance_records: List[AttendanceRecord]
) -> Optional[AttendanceRecord]:
    """Find the best matching AttendanceRecord for a given timetable entry."""
    norm_tt = normalize_subject_name(tt_subject)
    tt_is_lab = is_lab_subject(tt_subject)

    best_match = None
    for att in attendance_records:
        norm_att = normalize_subject_name(att.subject)
        att_is_lab = is_lab_subject(att.subject)

        # Enforce lab-to-lab or theory-to-theory consistency
        if tt_is_lab != att_is_lab:
            continue

        # Check containment in either direction
        if norm_tt == norm_att or norm_tt in norm_att or norm_att in norm_tt:
            return att

    # Fallback to loose match if no strict lab match found
    if not best_match:
        for att in attendance_records:
            norm_att = normalize_subject_name(att.subject)
            if norm_tt in norm_att or norm_att in norm_tt:
                return att

    return None


def calculate_attendance_recovery(attended: int, total: int, threshold: float = 75.0) -> int:
    """
    Calculate the exact number of consecutive upcoming classes a student must attend 
    without absence to restore their overall attendance to the minimum required threshold.
    """
    if total <= 0:
        return 0
    t = threshold / 100.0
    if (total * t) <= attended:
        return 0
    # Formula: (attended + x) / (total + x) >= t  ==>  x >= (t*total - attended) / (1 - t)
    needed = math.ceil((t * total - attended) / (1.0 - t))
    return max(1, needed)


def calculate_safe_bunks(attended: int, total: int, threshold: float = 75.0) -> int:
    """
    Calculate the maximum number of upcoming classes a student can safely miss
    without dropping below the minimum required attendance threshold.
    Formula: attended / (total + y) >= t  ==>  y <= (attended / t) - total
    """
    if total <= 0 or attended <= 0:
        return 0
    t = threshold / 100.0
    if t <= 0 or t >= 1.0:
        return 0
    current_pct = (attended / total) * 100.0
    if current_pct < threshold:
        return 0
    max_total = attended / t
    safe_absences = math.floor(max_total - total)
    return max(0, safe_absences)


def get_user_recipient_email(db: Session, user_id: str = "dev_student_user") -> str:
    """Resolve the most accurate notification recipient email for a student."""
    # 1. Custom user setting
    s = db.query(Setting).filter(Setting.key == f"notification_email_{user_id}").first()
    if s and s.value and s.value.strip():
        return s.value.strip()

    # 2. University portal login email
    portal_email = db.query(Setting).filter(
        Setting.key == f"portal:{user_id}:university_portal_login_email"
    ).first()
    if portal_email and portal_email.value and portal_email.value.strip():
        return portal_email.value.strip()

    # 3. Google connected university email
    g_email = db.query(Setting).filter(Setting.key == "google_connected_email").first()
    if g_email and g_email.value and g_email.value.strip():
        return g_email.value.strip()

    # 4. Registered user table email
    try:
        from app.db.models.common import User
        user = db.query(User).filter(User.id == user_id).first()
        if user and user.email and user.email.strip():
            return user.email.strip()
    except Exception:
        pass

    # 5. Fallback configured default
    return "ahmedkhnaofficials@gmail.com"


# ---------------------------------------------------------------------------
# Clean, Executive Email Templates (No cheap emojis, institutional typography)
# ---------------------------------------------------------------------------

def build_attendance_warning_email(
    course_name: str,
    percentage: float,
    attended: int,
    total: int,
    class_time: str,
    room: Optional[str] = None,
    teacher: Optional[str] = None,
    threshold: float = 75.0,
) -> Tuple[str, str]:
    """Generate institutional HTML and plain-text email for low attendance advisory on scheduled class days."""
    subject = f"[Uniflow] Academic Advisory: Low Attendance in {course_name} ({percentage:.1f}%)"
    room_str = room if (room and room.strip() and room.lower() != "none") else "Main Campus (Consult Portal)"
    teacher_str = teacher if (teacher and teacher.strip() and teacher.lower() != "none") else "Department Faculty"
    recovery_classes = calculate_attendance_recovery(attended, total, threshold)

    recovery_note = ""
    if recovery_classes > 0:
        recovery_note = (
            f"<strong>Attendance Recovery Plan:</strong> Based on current records, you must attend the next "
            f"<strong>{recovery_classes} consecutive sessions</strong> without absence to restore your attendance "
            f"above the {threshold:.0f}% examination threshold."
        )
    else:
        recovery_note = (
            f"Attending today's scheduled session is critical to avoid slipping below the institutional threshold of {threshold:.0f}%."
        )

    html = f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <style>
    body {{
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
      background-color: #f8fafc;
      color: #0f172a;
      margin: 0;
      padding: 24px 12px;
      line-height: 1.5;
    }}
    .email-container {{
      max-width: 580px;
      margin: 0 auto;
      background: #ffffff;
      border-radius: 8px;
      overflow: hidden;
      border: 1px solid #e2e8f0;
      box-shadow: 0 1px 3px rgba(0,0,0,0.05);
    }}
    .header-bar {{
      background: #0f172a;
      padding: 22px 28px;
      border-bottom: 2px solid #e2e8f0;
    }}
    .brand-title {{
      font-size: 11px;
      font-weight: 700;
      letter-spacing: 0.12em;
      text-transform: uppercase;
      color: #94a3b8;
      margin-bottom: 4px;
    }}
    .header-title {{
      color: #ffffff;
      font-size: 19px;
      font-weight: 700;
      margin: 0;
      letter-spacing: -0.01em;
    }}
    .content-body {{
      padding: 28px;
    }}
    .status-badge {{
      display: inline-block;
      padding: 4px 10px;
      border-radius: 4px;
      font-size: 11px;
      font-weight: 700;
      letter-spacing: 0.05em;
      text-transform: uppercase;
      background: #fef2f2;
      color: #991b1b;
      border: 1px solid #fecaca;
      margin-bottom: 18px;
    }}
    .intro-paragraph {{
      font-size: 14px;
      color: #334155;
      margin: 0 0 20px 0;
    }}
    .metric-grid {{
      display: table;
      width: 100%;
      margin: 20px 0;
      background: #f8fafc;
      border: 1px solid #e2e8f0;
      border-radius: 6px;
    }}
    .metric-cell {{
      display: table-cell;
      width: 50%;
      padding: 16px;
      text-align: center;
      vertical-align: middle;
    }}
    .metric-cell:first-child {{
      border-right: 1px solid #e2e8f0;
    }}
    .metric-value {{
      font-size: 24px;
      font-weight: 700;
      color: #991b1b;
    }}
    .metric-label {{
      font-size: 11px;
      font-weight: 600;
      text-transform: uppercase;
      letter-spacing: 0.05em;
      color: #64748b;
      margin-top: 4px;
    }}
    .details-table {{
      width: 100%;
      border-collapse: collapse;
      margin: 20px 0;
      font-size: 13px;
    }}
    .details-table td {{
      padding: 10px 12px;
      border-bottom: 1px solid #f1f5f9;
      color: #1e293b;
    }}
    .details-table td.label-col {{
      width: 32%;
      font-weight: 600;
      color: #64748b;
      background: #fafafa;
    }}
    .action-notice {{
      background: #fffbeb;
      border: 1px solid #fef3c7;
      border-radius: 6px;
      padding: 14px 16px;
      font-size: 13px;
      color: #92400e;
      margin-top: 22px;
    }}
    .footer-bar {{
      background: #f8fafc;
      padding: 18px 28px;
      font-size: 11px;
      color: #64748b;
      text-align: center;
      border-top: 1px solid #e2e8f0;
      line-height: 1.6;
    }}
  </style>
</head>
<body>
  <div class="email-container">
    <div class="header-bar">
      <div class="brand-title">Uniflow Academic Suite · Air University</div>
      <h1 class="header-title">Academic Advisory: Low Attendance Warning</h1>
    </div>
    <div class="content-body">
      <div class="status-badge">ATTENDANCE DEFICIT · BELOW {threshold:.0f}%</div>
      <p class="intro-paragraph">
        A lecture session for <strong>{course_name}</strong> is scheduled today at <strong>{class_time}</strong>. 
        Your current cumulative attendance is below the university's examination eligibility requirement.
      </p>

      <div class="metric-grid">
        <div class="metric-cell">
          <div class="metric-value">{percentage:.1f}%</div>
          <div class="metric-label">Current Attendance</div>
        </div>
        <div class="metric-cell">
          <div class="metric-value">{attended} / {total}</div>
          <div class="metric-label">Classes Attended</div>
        </div>
      </div>

      <table class="details-table">
        <tr>
          <td class="label-col">Course Name</td>
          <td><strong>{course_name}</strong></td>
        </tr>
        <tr>
          <td class="label-col">Session Time</td>
          <td>{class_time}</td>
        </tr>
        <tr>
          <td class="label-col">Classroom / Venue</td>
          <td>{room_str}</td>
        </tr>
        <tr>
          <td class="label-col">Instructor</td>
          <td>{teacher_str}</td>
        </tr>
      </table>

      <div class="action-notice">
        {recovery_note}
      </div>
    </div>
    <div class="footer-bar">
      Air University Student Academic Alert Service.<br>
      Automated notice generated based on the official University Student Portal records.
    </div>
  </div>
</body>
</html>"""

    text = f"""[Uniflow Academic Advisory] LOW ATTENDANCE WARNING

Course: {course_name}
Current Attendance: {percentage:.1f}% ({attended}/{total} classes attended)
Minimum Required: {threshold:.0f}%

Class Scheduled Today:
- Time: {class_time}
- Location: {room_str}
- Instructor: {teacher_str}

ACTION REQUIRED:
{recovery_note.replace('<strong>', '').replace('</strong>', '')}

---
Sent by Uniflow Academic Suite for Air University students.
"""
    return html.strip(), text.strip()


def build_timetable_reminder_email(
    course_name: str,
    start_time: str,
    end_time: str,
    room: Optional[str] = None,
    teacher: Optional[str] = None,
    minutes_left: int = 10,
    session_type: str = "Lecture",
) -> Tuple[str, str]:
    """Generate institutional HTML and plain-text email for 10-minute prior class reminder."""
    subject = f"[Uniflow] Upcoming Class: {course_name} at {start_time}"
    room_str = room if (room and room.strip() and room.lower() != "none") else "Venue to be confirmed via Portal"
    teacher_str = teacher if (teacher and teacher.strip() and teacher.lower() != "none") else "Department Faculty"

    html = f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <style>
    body {{
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
      background-color: #f8fafc;
      color: #0f172a;
      margin: 0;
      padding: 24px 12px;
      line-height: 1.5;
    }}
    .email-container {{
      max-width: 580px;
      margin: 0 auto;
      background: #ffffff;
      border-radius: 8px;
      overflow: hidden;
      border: 1px solid #e2e8f0;
      box-shadow: 0 1px 3px rgba(0,0,0,0.05);
    }}
    .header-bar {{
      background: #0f172a;
      padding: 22px 28px;
      border-bottom: 2px solid #e2e8f0;
    }}
    .brand-title {{
      font-size: 11px;
      font-weight: 700;
      letter-spacing: 0.12em;
      text-transform: uppercase;
      color: #94a3b8;
      margin-bottom: 4px;
    }}
    .header-title {{
      color: #ffffff;
      font-size: 19px;
      font-weight: 700;
      margin: 0;
      letter-spacing: -0.01em;
    }}
    .content-body {{
      padding: 28px;
    }}
    .status-badge {{
      display: inline-block;
      padding: 4px 10px;
      border-radius: 4px;
      font-size: 11px;
      font-weight: 700;
      letter-spacing: 0.05em;
      text-transform: uppercase;
      background: #eef2ff;
      color: #3730a3;
      border: 1px solid #c7d2fe;
      margin-bottom: 18px;
    }}
    .details-table {{
      width: 100%;
      border-collapse: collapse;
      margin: 16px 0;
      font-size: 13px;
    }}
    .details-table td {{
      padding: 10px 12px;
      border-bottom: 1px solid #f1f5f9;
      color: #1e293b;
    }}
    .details-table td.label-col {{
      width: 32%;
      font-weight: 600;
      color: #64748b;
      background: #fafafa;
    }}
    .preparation-box {{
      background: #f8fafc;
      border: 1px solid #e2e8f0;
      border-radius: 6px;
      padding: 14px 16px;
      font-size: 13px;
      color: #334155;
      margin-top: 20px;
    }}
    .preparation-box strong {{
      color: #0f172a;
    }}
    .footer-bar {{
      background: #f8fafc;
      padding: 18px 28px;
      font-size: 11px;
      color: #64748b;
      text-align: center;
      border-top: 1px solid #e2e8f0;
      line-height: 1.6;
    }}
  </style>
</head>
<body>
  <div class="email-container">
    <div class="header-bar">
      <div class="brand-title">Uniflow Academic Suite · Air University</div>
      <h1 class="header-title">Upcoming Class Reminder</h1>
    </div>
    <div class="content-body">
      <div class="status-badge">SCHEDULE NOTICE · STARTING IN ~{minutes_left} MINUTES</div>

      <table class="details-table">
        <tr>
          <td class="label-col">Course</td>
          <td><strong>{course_name}</strong></td>
        </tr>
        <tr>
          <td class="label-col">Time Window</td>
          <td><strong>{start_time} - {end_time}</strong></td>
        </tr>
        <tr>
          <td class="label-col">Classroom / Venue</td>
          <td>{room_str}</td>
        </tr>
        <tr>
          <td class="label-col">Instructor</td>
          <td>{teacher_str}</td>
        </tr>
        <tr>
          <td class="label-col">Session Type</td>
          <td>{session_type}</td>
        </tr>
      </table>

      <div class="preparation-box">
        <strong>Preparation Notice:</strong> Please proceed to {room_str} now to ensure on-time arrival. 
        Verify that you have your course notes, student ID, and any relevant lab materials ready.
      </div>
    </div>
    <div class="footer-bar">
      Air University Student Weekly Schedule Tracker.<br>
      Automated 10-minute prior notice sent by Uniflow.
    </div>
  </div>
</body>
</html>"""

    text = f"""[Uniflow Schedule Notice] CLASS STARTING IN ~{minutes_left} MINUTES

Course: {course_name}
Time: {start_time} - {end_time}
Classroom / Venue: {room_str}
Instructor: {teacher_str}
Session Type: {session_type}

Please proceed to {room_str} now to ensure on-time arrival.

---
Sent by Uniflow Academic Suite for Air University students.
"""
    return html.strip(), text.strip()


def build_assignment_deadline_email(
    assignment_title: str,
    course_name: str,
    due_datetime_str: str,
    time_remaining_str: str,
    classroom_url: Optional[str] = None,
    is_quiz: bool = False,
) -> Tuple[str, str]:
    """Generate institutional HTML and plain-text email for Google Classroom coursework deadline reminders."""
    work_type_label = "Quiz / Examination" if is_quiz else "Assignment / Lab Report"
    subject = f"[Uniflow] Deadline Notice: {assignment_title} ({course_name})"
    action_url = classroom_url or "https://classroom.google.com"

    html = f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <style>
    body {{
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
      background-color: #f8fafc;
      color: #0f172a;
      margin: 0;
      padding: 24px 12px;
      line-height: 1.5;
    }}
    .email-container {{
      max-width: 580px;
      margin: 0 auto;
      background: #ffffff;
      border-radius: 8px;
      overflow: hidden;
      border: 1px solid #e2e8f0;
      box-shadow: 0 1px 3px rgba(0,0,0,0.05);
    }}
    .header-bar {{
      background: #0f172a;
      padding: 22px 28px;
      border-bottom: 2px solid #e2e8f0;
    }}
    .brand-title {{
      font-size: 11px;
      font-weight: 700;
      letter-spacing: 0.12em;
      text-transform: uppercase;
      color: #94a3b8;
      margin-bottom: 4px;
    }}
    .header-title {{
      color: #ffffff;
      font-size: 19px;
      font-weight: 700;
      margin: 0;
      letter-spacing: -0.01em;
    }}
    .content-body {{
      padding: 28px;
    }}
    .status-badge {{
      display: inline-block;
      padding: 4px 10px;
      border-radius: 4px;
      font-size: 11px;
      font-weight: 700;
      letter-spacing: 0.05em;
      text-transform: uppercase;
      background: #fffbeb;
      color: #92400e;
      border: 1px solid #fde68a;
      margin-bottom: 18px;
    }}
    .details-table {{
      width: 100%;
      border-collapse: collapse;
      margin: 16px 0;
      font-size: 13px;
    }}
    .details-table td {{
      padding: 10px 12px;
      border-bottom: 1px solid #f1f5f9;
      color: #1e293b;
    }}
    .details-table td.label-col {{
      width: 32%;
      font-weight: 600;
      color: #64748b;
      background: #fafafa;
    }}
    .btn-container {{
      text-align: center;
      margin: 24px 0 12px 0;
    }}
    .btn-primary {{
      display: inline-block;
      background: #0f172a;
      color: #ffffff !important;
      text-decoration: none;
      padding: 11px 22px;
      border-radius: 6px;
      font-size: 13px;
      font-weight: 600;
      letter-spacing: 0.02em;
    }}
    .footer-bar {{
      background: #f8fafc;
      padding: 18px 28px;
      font-size: 11px;
      color: #64748b;
      text-align: center;
      border-top: 1px solid #e2e8f0;
      line-height: 1.6;
    }}
  </style>
</head>
<body>
  <div class="email-container">
    <div class="header-bar">
      <div class="brand-title">Uniflow Academic Suite · Google Classroom Sync</div>
      <h1 class="header-title">Coursework Deadline Reminder</h1>
    </div>
    <div class="content-body">
      <div class="status-badge">DEADLINE NOTICE · DUE IN {time_remaining_str.upper()}</div>

      <table class="details-table">
        <tr>
          <td class="label-col">Task Title</td>
          <td><strong>{assignment_title}</strong></td>
        </tr>
        <tr>
          <td class="label-col">Course</td>
          <td>{course_name}</td>
        </tr>
        <tr>
          <td class="label-col">Work Type</td>
          <td>{work_type_label}</td>
        </tr>
        <tr>
          <td class="label-col">Submission Deadline</td>
          <td><strong>{due_datetime_str}</strong></td>
        </tr>
        <tr>
          <td class="label-col">Status</td>
          <td><span style="color: #92400e; font-weight: 600;">Pending Submission</span></td>
        </tr>
      </table>

      <div class="btn-container">
        <a href="{action_url}" target="_blank" class="btn-primary">View in Google Classroom</a>
      </div>
    </div>
    <div class="footer-bar">
      Air University Student Google Classroom Integration.<br>
      To submit, turn in your completed files via Google Classroom or the Uniflow Assignment Portal.
    </div>
  </div>
</body>
</html>"""

    text = f"""[Uniflow Deadline Notice] COURSEWORK DUE IN {time_remaining_str.upper()}

Task Title: {assignment_title}
Course: {course_name}
Type: {work_type_label}
Deadline: {due_datetime_str}
Status: Pending Submission

Direct Submission Link: {action_url}

---
Sent by Uniflow Academic Suite for Air University students.
"""
    return html.strip(), text.strip()


# ---------------------------------------------------------------------------
# Core Alert Service with Comprehensive Student Edge Cases
# ---------------------------------------------------------------------------

class AlertService:
    """Core service for generating, deduplicating, and delivering academic and schedule notifications."""

    def __init__(self, db: Session):
        self.db = db

    def generate_daily_attendance_warnings(
        self,
        user_id: str = "dev_student_user",
        target_date: Optional[date] = None,
        threshold: float = 75.0,
        send_immediately: bool = True,
    ) -> List[Dict]:
        """
        Check all classes scheduled today; if attendance in any class is below threshold, 
        dispatch an institutional academic advisory.
        
        Edge cases handled:
        - Total held classes = 0: Skipped (no classes held yet, e.g. start of semester).
        - Multiple timetable slots of same subject in one day: Deduplicated to 1 warning.
        - Strict Lab vs Theory matching: Prevents mixing Lab records with Theory.
        - Mathematical recovery calculation: Shows exact number of consecutive classes required.
        - Idempotency: Exactly one warning per course per day.
        """
        if not target_date:
            tz = ZoneInfo(settings.timezone)
            target_date = datetime.now(tz).date()

        weekday_int = target_date.weekday()
        recipient = get_user_recipient_email(self.db, user_id)

        # 1. Get today's classes from TimetableEntry
        scheduled_today = (
            self.db.query(TimetableEntry)
            .filter(TimetableEntry.weekday == weekday_int)
            .order_by(TimetableEntry.start_time)
            .all()
        )

        if not scheduled_today:
            return []

        # 2. Get student's attendance records
        att_records = self.db.query(AttendanceRecord).all()
        if not att_records:
            return []

        generated_alerts = []
        seen_courses_today = set()

        for entry in scheduled_today:
            match = match_attendance_to_timetable(entry.subject, att_records)
            if not match:
                continue

            # EDGE CASE 1: No held classes recorded yet
            total_held = match.total or 0
            attended_count = match.attended or 0
            if total_held <= 0:
                continue

            # Check if attendance is below threshold
            pct = match.percentage if match.percentage is not None else (attended_count / total_held * 100.0)
            if pct >= threshold:
                continue

            # EDGE CASE 2: Deduplicate multiple slots of same course on same day
            norm_name = normalize_subject_name(entry.subject)
            if norm_name in seen_courses_today:
                continue
            seen_courses_today.add(norm_name)

            # EDGE CASE 3: Idempotency key per user, record, and date
            idempotency_key = f"att-warn:{user_id}:{match.id}:{target_date.isoformat()}"
            existing = (
                self.db.query(Notification)
                .filter(Notification.idempotency_key == idempotency_key)
                .first()
            )
            if existing:
                continue

            recovery_needed = calculate_attendance_recovery(attended_count, total_held, threshold)
            subject_title = f"[Uniflow] Academic Advisory: Low Attendance in {entry.subject} ({pct:.1f}%)"
            payload_summary = (
                f"Course: {entry.subject}\n"
                f"Current Attendance: {pct:.1f}% ({attended_count}/{total_held} classes attended)\n"
                f"Minimum Required: {threshold:.0f}%\n"
                f"Consecutive Classes Needed to Recover: {recovery_needed}\n"
                f"Scheduled Time: {entry.start_time} - {entry.end_time} in {entry.room or 'Main Campus'}\n"
                f"Instructor: {entry.teacher or 'Department Faculty'}"
            )

            html_content, text_content = build_attendance_warning_email(
                course_name=entry.subject,
                percentage=pct,
                attended=attended_count,
                total=total_held,
                class_time=f"{entry.start_time} - {entry.end_time}",
                room=entry.room,
                teacher=entry.teacher,
                threshold=threshold,
            )

            notification = Notification(
                notification_type="attendance_warning",
                recipient=recipient,
                subject=subject_title,
                payload=payload_summary,
                external_id=f"att-{match.id}",
                idempotency_key=idempotency_key,
                status=NotificationStatus.PENDING,
            )
            self.db.add(notification)
            self.db.commit()
            self.db.refresh(notification)

            if send_immediately:
                success = send_email(
                    to_email=recipient,
                    subject=subject_title,
                    html_content=html_content,
                    text_content=text_content,
                    from_name="Uniflow",
                    categories=["academic-advisory", "attendance-warning"],
                    custom_args={"notification_id": str(notification.id), "user_id": user_id},
                )
                if success:
                    notification.status = NotificationStatus.SENT
                    notification.sent_at = func.now()
                else:
                    notification.status = NotificationStatus.FAILED
                    notification.error = "Delivery failed via SendGrid and SMTP fallback"
                self.db.commit()

            generated_alerts.append({
                "notification_id": notification.id,
                "type": "attendance_warning",
                "course": entry.subject,
                "percentage": pct,
                "attended": attended_count,
                "total": total_held,
                "recovery_needed": recovery_needed,
                "time": entry.start_time,
                "room": entry.room,
                "recipient": recipient,
                "status": notification.status.value,
            })

        return generated_alerts

    def generate_upcoming_class_reminders(
        self,
        user_id: str = "dev_student_user",
        target_dt: Optional[datetime] = None,
        lookahead_minutes: int = 10,
        window_tolerance: int = 3,
        send_immediately: bool = True,
    ) -> List[Dict]:
        """
        Find classes starting in ~10 minutes and dispatch a timetable reminder.
        
        Edge cases handled:
        - Multi-slot continuous lab blocks (e.g. 3-hour lab broken into three 50-minute entries): 
          Only alerts once at the start of the entire block, not in the middle of consecutive slots.
        - Missing room or teacher: Gracefully formats institutional fallbacks.
        - Idempotency key per user, slot, and date.
        """
        tz = ZoneInfo(settings.timezone)
        if not target_dt:
            target_dt = datetime.now(tz)
        elif target_dt.tzinfo is None:
            target_dt = target_dt.replace(tzinfo=tz)

        today = target_dt.date()
        weekday_int = today.weekday()
        recipient = get_user_recipient_email(self.db, user_id)

        # 1. Get today's classes
        classes_today = (
            self.db.query(TimetableEntry)
            .filter(TimetableEntry.weekday == weekday_int)
            .order_by(TimetableEntry.start_time)
            .all()
        )

        if not classes_today:
            return []

        generated_reminders = []

        for i, entry in enumerate(classes_today):
            if not entry.start_time:
                continue

            try:
                # Parse start time (formats: "08:30" or "08:30:00")
                parts = entry.start_time.strip().split(":")
                start_h = int(parts[0])
                start_m = int(parts[1])
                class_start = target_dt.replace(hour=start_h, minute=start_m, second=0, microsecond=0)
            except (ValueError, IndexError):
                continue

            diff_seconds = (class_start - target_dt).total_seconds()
            target_seconds = lookahead_minutes * 60
            tolerance_seconds = window_tolerance * 60

            # Match within window
            if abs(diff_seconds - target_seconds) <= tolerance_seconds:
                # EDGE CASE: Multi-hour / continuous lab session
                # If the previous entry ended right when this entry starts for the same subject,
                # this is an ongoing session continuation — skip alerting mid-class!
                if i > 0:
                    prev_entry = classes_today[i - 1]
                    norm_curr = normalize_subject_name(entry.subject)
                    norm_prev = normalize_subject_name(prev_entry.subject)
                    if norm_curr == norm_prev and prev_entry.end_time == entry.start_time:
                        continue

                idempotency_key = f"tt-remind:{user_id}:{entry.id}:{today.isoformat()}"
                existing = (
                    self.db.query(Notification)
                    .filter(Notification.idempotency_key == idempotency_key)
                    .first()
                )
                if existing:
                    continue

                mins_display = max(1, int(round(diff_seconds / 60.0)))
                session_type = "Laboratory Practical" if is_lab_subject(entry.subject) else "Lecture"
                subject_title = f"[Uniflow] Upcoming Class: {entry.subject} at {entry.start_time}"
                payload_summary = (
                    f"Course: {entry.subject}\n"
                    f"Session Type: {session_type}\n"
                    f"Time: {entry.start_time} - {entry.end_time} (Starting in ~{mins_display} mins)\n"
                    f"Venue: {entry.room or 'Main Campus (Consult Portal)'}\n"
                    f"Instructor: {entry.teacher or 'Department Faculty'}"
                )

                html_content, text_content = build_timetable_reminder_email(
                    course_name=entry.subject,
                    start_time=entry.start_time,
                    end_time=entry.end_time,
                    room=entry.room,
                    teacher=entry.teacher,
                    minutes_left=mins_display,
                    session_type=session_type,
                )

                notification = Notification(
                    notification_type="timetable_reminder",
                    recipient=recipient,
                    subject=subject_title,
                    payload=payload_summary,
                    external_id=f"tt-{entry.id}",
                    idempotency_key=idempotency_key,
                    status=NotificationStatus.PENDING,
                )
                self.db.add(notification)
                self.db.commit()
                self.db.refresh(notification)

                if send_immediately:
                    success = send_email(
                        to_email=recipient,
                        subject=subject_title,
                        html_content=html_content,
                        text_content=text_content,
                        from_name="Uniflow",
                        categories=["class-schedule", "timetable-reminder"],
                        custom_args={"notification_id": str(notification.id), "user_id": user_id},
                    )
                    if success:
                        notification.status = NotificationStatus.SENT
                        notification.sent_at = func.now()
                    else:
                        notification.status = NotificationStatus.FAILED
                        notification.error = "Delivery failed via SendGrid and SMTP fallback"
                    self.db.commit()

                generated_reminders.append({
                    "notification_id": notification.id,
                    "type": "timetable_reminder",
                    "course": entry.subject,
                    "session_type": session_type,
                    "time": entry.start_time,
                    "room": entry.room,
                    "minutes_left": mins_display,
                    "recipient": recipient,
                    "status": notification.status.value,
                })

        return generated_reminders

    def generate_upcoming_assignment_reminders(
        self,
        user_id: str = "dev_student_user",
        target_dt: Optional[datetime] = None,
        lookahead_hours: int = 24,
        send_immediately: bool = True,
    ) -> List[Dict]:
        """
        Scan synced Google Classroom (GCR) coursework and alert students about upcoming deadlines.
        
        Edge cases handled:
        - Already turned in or returned: Skipped completely (students hate alerts for submitted work).
        - No due date: Skipped (professors posting study material).
        - Already past due date: Skipped (no retroactive spam).
        - Quizzes vs Homework: Distinct institutional labeling.
        - Two alert milestones: 24-hour advance notice and 3-hour urgent notice.
        - Idempotency per assignment and alert milestone.
        """
        tz = ZoneInfo(settings.timezone)
        if not target_dt:
            target_dt = datetime.now(tz)
        elif target_dt.tzinfo is None:
            target_dt = target_dt.replace(tzinfo=tz)

        recipient = get_user_recipient_email(self.db, user_id)

        # 1. Query active assignments
        assignments = (
            self.db.query(Assignment)
            .filter(Assignment.state == CourseworkState.PUBLISHED)
            .all()
        )

        if not assignments:
            return []

        generated_alerts = []

        for assignment in assignments:
            # EDGE CASE 1: Already submitted / turned in
            if assignment.submission_state in [SubmissionState.TURNED_IN, SubmissionState.RETURNED]:
                continue
            if assignment.submission and assignment.submission.submitted_at is not None:
                continue

            # EDGE CASE 2: No due date
            due = assignment.due_at or assignment.due_date
            if not due:
                continue

            # Ensure due has timezone info
            if due.tzinfo is None:
                due = due.replace(tzinfo=tz)

            time_left = (due - target_dt).total_seconds()

            # EDGE CASE 3: Already past deadline
            if time_left <= 0:
                continue

            # Determine milestone window
            hours_left = time_left / 3600.0
            milestone = None
            if hours_left <= 3.5:
                milestone = "3h"
                time_str = f"{max(1, int(round(hours_left * 60)))} minutes" if hours_left < 1 else f"{round(hours_left, 1)} hours"
            elif hours_left <= (lookahead_hours + 1.0):
                milestone = "24h"
                time_str = f"~{int(round(hours_left))} hours"
            else:
                continue

            # EDGE CASE 4: Idempotency per milestone
            idempotency_key = f"gcr-due-{milestone}:{user_id}:{assignment.id}"
            existing = (
                self.db.query(Notification)
                .filter(Notification.idempotency_key == idempotency_key)
                .first()
            )
            if existing:
                continue

            course_name = assignment.course.name if assignment.course else "University Course"
            is_quiz = assignment.is_quiz or (assignment.work_type and "quiz" in assignment.work_type.lower())
            work_label = "Quiz" if is_quiz else "Assignment"
            due_formatted = due.strftime("%A, %d %b %Y at %I:%M %p")
            subject_title = f"[Uniflow] Deadline Notice: {assignment.title} ({course_name})"
            payload_summary = (
                f"Course: {course_name}\n"
                f"Task: {assignment.title} ({work_label})\n"
                f"Due: {due_formatted} (In {time_str})\n"
                f"Google Classroom Link: {assignment.url or 'https://classroom.google.com'}"
            )

            html_content, text_content = build_assignment_deadline_email(
                assignment_title=assignment.title,
                course_name=course_name,
                due_datetime_str=due_formatted,
                time_remaining_str=time_str,
                classroom_url=assignment.url,
                is_quiz=is_quiz,
            )

            notification = Notification(
                notification_type="assignment_deadline",
                recipient=recipient,
                subject=subject_title,
                payload=payload_summary,
                external_id=f"gcr-{assignment.id}",
                idempotency_key=idempotency_key,
                status=NotificationStatus.PENDING,
            )
            self.db.add(notification)
            self.db.commit()
            self.db.refresh(notification)

            if send_immediately:
                success = send_email(
                    to_email=recipient,
                    subject=subject_title,
                    html_content=html_content,
                    text_content=text_content,
                    from_name="Uniflow",
                    categories=["gcr-deadline", "assignment-reminder"],
                    custom_args={"notification_id": str(notification.id), "user_id": user_id},
                )
                if success:
                    notification.status = NotificationStatus.SENT
                    notification.sent_at = func.now()
                else:
                    notification.status = NotificationStatus.FAILED
                    notification.error = "Delivery failed via SendGrid and SMTP fallback"
                self.db.commit()

            generated_alerts.append({
                "notification_id": notification.id,
                "type": "assignment_deadline",
                "title": assignment.title,
                "course": course_name,
                "is_quiz": is_quiz,
                "due": due_formatted,
                "time_remaining": time_str,
                "recipient": recipient,
                "status": notification.status.value,
            })

        return generated_alerts
