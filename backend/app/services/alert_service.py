import math
import re
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo
from sqlalchemy.orm import Session
from sqlalchemy import func

from app.core.config import settings
from app.auth.ownership import user_owner_ids
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


def get_user_recipient_email(db: Session, user_id: str = "") -> str:
    """
    Resolve the most accurate notification recipient email for a student.
    Strictly prioritizes the email address the student saved in Dashboard -> Settings.
    """
    if not user_id:
        return ""

    setting = db.query(Setting).filter(Setting.key == f"notification_email_{user_id}").first()
    if setting and setting.value and setting.value.strip() and "@" in setting.value:
        return setting.value.strip()
    if user_id == "dev_student_user" and not settings.is_production:
        local_default = db.query(Setting).filter(Setting.key == "notification_email_default").first()
        if local_default and local_default.value and "@" in local_default.value:
            return local_default.value.strip()
        # Local fixtures and a fresh development database may not have an email
        # configured. Keep alert generation deterministic without borrowing an
        # address belonging to a real account.
        return "dev-student@localhost.invalid"

    # Only use profile or integration emails associated with this exact user.
    clerk_s = db.query(Setting).filter(Setting.key == f"clerk_user_{user_id}").first()
    if clerk_s and clerk_s.value:
        try:
            data = json.loads(clerk_s.value)
            email = data.get("email") or data.get("emailAddress") or ""
            if email and "@" in email:
                return email.strip()
        except Exception:
            pass

    portal_email = db.query(Setting).filter(
        Setting.key == f"portal:{user_id}:university_portal_login_email"
    ).first()
    if portal_email and portal_email.value and portal_email.value.strip() and "@" in portal_email.value:
        return portal_email.value.strip()

    g_email = db.query(Setting).filter(Setting.key == f"google_connected_email_{user_id}").first()
    if g_email and g_email.value and g_email.value.strip() and "@" in g_email.value:
        return g_email.value.strip()

    return ""


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


def build_daily_morning_digest_email(
    student_name: str,
    date_str: str,
    classes_today: List[Dict],
    urgent_warnings: List[Dict],
    upcoming_tasks: List[Dict],
) -> Tuple[str, str]:
    """
    Generate an executive HTML and plain-text email for the daily morning academic briefing.
    Delivers today's complete schedule, attendance status for each course, safe bunk / recovery metrics,
    and approaching coursework deadlines.
    """
    subject = f"[Uniflow] Morning Briefing: Today's Classes & Attendance ({date_str})"
    classes_count = len(classes_today)
    advisories_count = len(urgent_warnings)
    tasks_count = len(upcoming_tasks)

    # Build classes rows
    if classes_today:
        class_rows_html = ""
        for item in classes_today:
            course = item.get("course", "")
            time_str = item.get("time", "")
            room = item.get("room") or "Main Campus"
            teacher = item.get("teacher") or "Department Faculty"
            pct = item.get("percentage")
            attended = item.get("attended", 0)
            total = item.get("total", 0)
            recovery = item.get("recovery_needed", 0)
            safe_bunks = item.get("safe_bunks", 0)

            if pct is not None and total > 0:
                if pct < 75.0:
                    att_badge = f'<span style="display:inline-block; padding:2px 8px; border-radius:4px; font-size:11px; font-weight:700; background:#fef2f2; color:#991b1b; border:1px solid #fecaca;">{pct:.1f}% ({attended}/{total}) · Need {recovery} to reach 75%</span>'
                else:
                    bunk_text = f" · {safe_bunks} safe bunk{'s' if safe_bunks != 1 else ''}" if safe_bunks > 0 else " · On borderline"
                    att_badge = f'<span style="display:inline-block; padding:2px 8px; border-radius:4px; font-size:11px; font-weight:700; background:#f0fdf4; color:#166534; border:1px solid #bbf7d0;">{pct:.1f}% ({attended}/{total}){bunk_text}</span>'
            else:
                att_badge = '<span style="color:#64748b; font-size:12px;">No portal records</span>'

            class_rows_html += f"""
            <tr>
              <td style="padding:12px 14px; border-bottom:1px solid #f1f5f9; vertical-align:top; width:30%;">
                <div style="font-weight:700; color:#0f172a; font-size:13px;">{time_str}</div>
                <div style="font-size:11px; color:#64748b; margin-top:2px;">{room}</div>
              </td>
              <td style="padding:12px 14px; border-bottom:1px solid #f1f5f9; vertical-align:top;">
                <div style="font-weight:600; color:#1e293b; font-size:13px;">{course}</div>
                <div style="font-size:11px; color:#64748b; margin-top:2px;">{teacher}</div>
                <div style="margin-top:6px;">{att_badge}</div>
              </td>
            </tr>
            """
    else:
        class_rows_html = """
        <tr>
          <td colspan="2" style="padding:24px; text-align:center; color:#64748b; font-size:13px; font-style:italic;">
            No university classes scheduled for today. Enjoy your day!
          </td>
        </tr>
        """

    # Build advisories section
    advisories_html = ""
    if urgent_warnings:
        advisory_items_html = ""
        for adv in urgent_warnings:
            c = adv.get("course", "")
            p = adv.get("percentage", 0.0)
            rec = adv.get("recovery_needed", 0)
            advisory_items_html += f"""
            <li style="margin-bottom:8px; font-size:13px; color:#991b1b;">
              <strong>{c}</strong>: Currently at <strong>{p:.1f}%</strong>. You must attend today's session and the next <strong>{rec} consecutive classes</strong> to restore examination eligibility.
            </li>
            """
        advisories_html = f"""
        <div style="margin:20px 0; background:#fef2f2; border:1px solid #fecaca; border-radius:6px; padding:16px;">
          <div style="font-size:11px; font-weight:700; text-transform:uppercase; letter-spacing:0.08em; color:#991b1b; margin-bottom:8px;">
            Academic Advisory: Attendance Below Minimum Threshold (75%)
          </div>
          <ul style="margin:0; padding-left:18px;">
            {advisory_items_html}
          </ul>
        </div>
        """

    # Build upcoming tasks section
    tasks_html = ""
    if upcoming_tasks:
        task_rows_html = ""
        for t in upcoming_tasks:
            title = t.get("title", "")
            cname = t.get("course", "")
            due_str = t.get("due", "")
            url = t.get("url") or "https://classroom.google.com"
            task_rows_html += f"""
            <tr>
              <td style="padding:10px 14px; border-bottom:1px solid #f1f5f9; font-size:13px; color:#1e293b;">
                <strong>{title}</strong>
                <div style="font-size:11px; color:#64748b;">{cname} · Due: {due_str}</div>
              </td>
              <td style="padding:10px 14px; border-bottom:1px solid #f1f5f9; text-align:right;">
                <a href="{url}" target="_blank" style="font-size:11px; font-weight:600; color:#4f46e5; text-decoration:none;">Open</a>
              </td>
            </tr>
            """
        tasks_html = f"""
        <div style="margin:24px 0 16px 0;">
          <div style="font-size:11px; font-weight:700; text-transform:uppercase; letter-spacing:0.08em; color:#64748b; margin-bottom:10px;">
            Pending Coursework &amp; Deadlines
          </div>
          <table style="width:100%; border-collapse:collapse; background:#ffffff; border:1px solid #e2e8f0; border-radius:6px;">
            {task_rows_html}
          </table>
        </div>
        """

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
      max-width: 600px;
      margin: 0 auto;
      background: #ffffff;
      border-radius: 8px;
      overflow: hidden;
      border: 1px solid #e2e8f0;
      box-shadow: 0 1px 3px rgba(0,0,0,0.05);
    }}
    .header-bar {{
      background: #0f172a;
      padding: 24px 28px;
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
      font-size: 20px;
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
    .stats-table {{
      width: 100%;
      border-collapse: collapse;
      margin: 16px 0 24px 0;
      background: #f8fafc;
      border: 1px solid #e2e8f0;
      border-radius: 6px;
    }}
    .stats-cell {{
      width: 33.33%;
      padding: 14px;
      text-align: center;
      border-right: 1px solid #e2e8f0;
    }}
    .stats-cell:last-child {{
      border-right: none;
    }}
    .stats-val {{
      font-size: 20px;
      font-weight: 700;
      color: #0f172a;
    }}
    .stats-label {{
      font-size: 10px;
      font-weight: 600;
      text-transform: uppercase;
      letter-spacing: 0.05em;
      color: #64748b;
      margin-top: 2px;
    }}
    .schedule-table {{
      width: 100%;
      border-collapse: collapse;
      margin-top: 10px;
      border: 1px solid #e2e8f0;
      border-radius: 6px;
      background: #ffffff;
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
      <div class="brand-title">Uniflow Academic Suite · Daily Briefing</div>
      <h1 class="header-title">Daily Schedule &amp; Attendance Digest</h1>
    </div>
    <div class="content-body">
      <div class="status-badge">DAILY DIGEST · {date_str.upper()}</div>
      
      <p style="margin:0 0 16px 0; font-size:14px; color:#334155;">
        Good morning! Here is your personalized daily academic overview for <strong>{date_str}</strong>.
      </p>

      <table class="stats-table">
        <tr>
          <td class="stats-cell">
            <div class="stats-val">{classes_count}</div>
            <div class="stats-label">Classes Today</div>
          </td>
          <td class="stats-cell">
            <div class="stats-val" style="color: {'#dc2626' if advisories_count > 0 else '#16a34a'};">{advisories_count}</div>
            <div class="stats-label">Advisories (&lt;75%)</div>
          </td>
          <td class="stats-cell">
            <div class="stats-val">{tasks_count}</div>
            <div class="stats-label">Active Tasks</div>
          </td>
        </tr>
      </table>

      {advisories_html}

      <div style="font-size:11px; font-weight:700; text-transform:uppercase; letter-spacing:0.08em; color:#64748b; margin-bottom:8px;">
        Today's Class Schedule &amp; Course Attendance
      </div>
      <table class="schedule-table">
        {class_rows_html}
      </table>

      {tasks_html}

      <div style="margin-top:24px; text-align:center;">
        <a href="http://localhost:3000/dashboard" target="_blank" style="display:inline-block; background:#0f172a; color:#ffffff !important; text-decoration:none; padding:10px 22px; border-radius:6px; font-size:12px; font-weight:600;">Open Uniflow Dashboard</a>
      </div>
    </div>
    <div class="footer-bar">
      Daily Morning Digest dispatched strictly once per day by Uniflow Academic Suite.<br>
      Air University Student Intelligence &amp; Schedule Synchronization.
    </div>
  </div>
</body>
</html>"""

    text_lines = [
        f"[Uniflow Morning Briefing] {date_str}",
        "",
        f"Classes Today: {classes_count} | Attendance Advisories: {advisories_count} | Active Tasks: {tasks_count}",
        "",
        "--- TODAY'S CLASS SCHEDULE ---",
    ]
    if classes_today:
        for item in classes_today:
            c = item.get("course", "")
            t = item.get("time", "")
            r = item.get("room") or "Main Campus"
            p = item.get("percentage")
            att = item.get("attended", 0)
            tot = item.get("total", 0)
            rec = item.get("recovery_needed", 0)
            sb = item.get("safe_bunks", 0)
            att_info = f"{p:.1f}% ({att}/{tot})" if p is not None and tot > 0 else "No data"
            if p is not None and tot > 0 and p < 75.0:
                att_info += f" [CRITICAL: Need {rec} classes to recover]"
            elif sb > 0:
                att_info += f" [{sb} safe bunks]"
            text_lines.append(f"• {t}: {c} in {r} | Attendance: {att_info}")
    else:
        text_lines.append("No classes scheduled for today.")

    if urgent_warnings:
        text_lines.extend(["", "--- ACADEMIC ADVISORIES (<75%) ---"])
        for adv in urgent_warnings:
            text_lines.append(f"• {adv.get('course')}: {adv.get('percentage'):.1f}% (Need {adv.get('recovery_needed')} consecutive classes)")

    if upcoming_tasks:
        text_lines.extend(["", "--- UPCOMING DEADLINES ---"])
        for t in upcoming_tasks:
            text_lines.append(f"• {t.get('title')} ({t.get('course')}) - Due: {t.get('due')}")

    text_lines.extend(["", "---", "Sent by Uniflow Academic Suite for Air University students."])
    text = "\n".join(text_lines)

    return html.strip(), text.strip()


def build_new_assignment_email(
    assignment_title: str,
    course_name: str,
    due_datetime_str: str,
    classroom_url: Optional[str] = None,
    description: Optional[str] = None,
    is_quiz: bool = False,
) -> Tuple[str, str]:
    """Generate institutional HTML and plain-text email for newly posted Google Classroom coursework."""
    work_type_label = "Quiz / Exam" if is_quiz else "Assignment"
    subject = f"[Uniflow] New Task: {assignment_title} ({course_name})"
    action_url = classroom_url or "https://classroom.google.com"
    desc_snippet = (description[:250] + "...") if description and len(description) > 250 else (description or "No additional instructions provided.")

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
      background: #eff6ff;
      color: #1d4ed8;
      border: 1px solid #bfdbfe;
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
      <h1 class="header-title">New Coursework Posted</h1>
    </div>
    <div class="content-body">
      <div class="status-badge">NEW {work_type_label.upper()} · {course_name.upper()}</div>

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
          <td class="label-col">Submission Due</td>
          <td><strong>{due_datetime_str}</strong></td>
        </tr>
        <tr>
          <td class="label-col">Instructions</td>
          <td style="color:#475569; font-size:12px; line-height:1.5;">{desc_snippet}</td>
        </tr>
      </table>

      <div class="btn-container">
        <a href="{action_url}" target="_blank" class="btn-primary">View in Google Classroom</a>
      </div>
    </div>
    <div class="footer-bar">
      Dispatched strictly once upon new coursework arrival by Uniflow Academic Suite.<br>
      Air University Student Google Classroom Sync.
    </div>
  </div>
</body>
</html>"""

    text = f"""[Uniflow New Coursework] {assignment_title} ({course_name})

Course: {course_name}
Task: {assignment_title}
Type: {work_type_label}
Due Date: {due_datetime_str}

Instructions:
{desc_snippet}

Direct Classroom Link: {action_url}

---
Sent by Uniflow Academic Suite for Air University students.
"""
    return html.strip(), text.strip()


def build_daily_class_list_email(
    student_name: str,
    date_str: str,
    classes_today: List[Dict],
) -> Tuple[str, str]:
    """
    Generate a simple HTML and plain-text email for the daily class list.
    Contains only the schedule of classes for the day.
    """
    classes_count = len(classes_today)
    day_of_week = date_str.split(",")[0] if "," in date_str else date_str

    # Build classes rows
    if classes_today:
        class_rows_html = ""
        for item in classes_today:
            course = item.get("course", "")
            time_str = item.get("time", "")
            room = item.get("room") or "Main Campus"
            teacher = item.get("teacher") or "Department Faculty"

            class_rows_html += f"""
            <tr>
              <td style="padding:12px 14px; border-bottom:1px solid #f1f5f9; vertical-align:top; width:30%;">
                <div style="font-weight:700; color:#0f172a; font-size:13px;">{time_str}</div>
                <div style="font-size:11px; color:#64748b; margin-top:2px;">{room}</div>
              </td>
              <td style="padding:12px 14px; border-bottom:1px solid #f1f5f9; vertical-align:top;">
                <div style="font-weight:600; color:#1e293b; font-size:13px;">{course}</div>
                <div style="font-size:11px; color:#64748b; margin-top:2px;">{teacher}</div>
              </td>
            </tr>
            """
    else:
        class_rows_html = """
        <tr>
          <td colspan="2" style="padding:24px; text-align:center; color:#64748b; font-size:13px; font-style:italic;">
            No university classes scheduled for today. Enjoy your day!
          </td>
        </tr>
        """

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
      max-width: 600px;
      margin: 0 auto;
      background: #ffffff;
      border-radius: 8px;
      overflow: hidden;
      border: 1px solid #e2e8f0;
      box-shadow: 0 1px 3px rgba(0,0,0,0.05);
    }}
    .header-bar {{
      background: linear-gradient(135deg, #3b82f6 0%, #1d4ed8 100%);
      padding: 24px 28px;
      border-bottom: 2px solid #e2e8f0;
    }}
    .brand-title {{
      font-size: 11px;
      font-weight: 700;
      letter-spacing: 0.12em;
      text-transform: uppercase;
      color: #bfdbfe;
      margin-bottom: 4px;
    }}
    .header-title {{
      color: #ffffff;
      font-size: 20px;
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
      background: #eff6ff;
      color: #1d4ed8;
      border: 1px solid #bfdbfe;
      margin-bottom: 18px;
    }}
    .schedule-table {{
      width: 100%;
      border-collapse: collapse;
      margin-top: 10px;
      border: 1px solid #e2e8f0;
      border-radius: 6px;
      background: #ffffff;
    }}
    .schedule-table th {{
      background: #f8fafc;
      padding: 12px 14px;
      text-align: left;
      font-weight: 600;
      color: #475569;
      font-size: 12px;
      border-bottom: 2px solid #e2e8f0;
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
      <div class="brand-title">Uniflow Academic Suite · Daily Schedule</div>
      <h1 class="header-title">Today's Class Schedule</h1>
    </div>
    <div class="content-body">
      <div class="status-badge">DAILY SCHEDULE · {date_str.upper()}</div>
      
      <p style="margin:0 0 16px 0; font-size:14px; color:#334155;">
        Good morning, <strong>{student_name}</strong>! Here is your class schedule for <strong>{day_of_week}</strong>, <strong>{date_str}</strong>.
      </p>

      <table class="schedule-table">
        <thead>
          <tr>
            <th style="width:30%;">Time & Room</th>
            <th>Course & Instructor</th>
          </tr>
        </thead>
        <tbody>
          {class_rows_html}
        </tbody>
      </table>

      <div style="margin-top:20px; padding:12px; background:#f0fdf4; border:1px solid #bbf7d0; border-radius:6px; font-size:12px; color:#166534;">
        <strong>{classes_count} class{'es' if classes_count != 1 else ''} scheduled today.</strong>
      </div>
    </div>
    <div class="footer-bar">
      Dispatched daily at 07:00 AM by Uniflow Academic Suite.<br>
      Air University Student Schedule Notifications.
    </div>
  </div>
</body>
</html>"""

    # Plain text version
    text_lines = [
        f"[Uniflow] Today's Class Schedule ({date_str})",
        "",
        f"Good morning, {student_name}! Here is your class schedule for {day_of_week}, {date_str}.",
        "",
        "─" * 50,
    ]

    if classes_today:
        for item in classes_today:
            course = item.get("course", "")
            time_str = item.get("time", "")
            room = item.get("room") or "Main Campus"
            teacher = item.get("teacher") or "Department Faculty"
            text_lines.extend([
                f"• {course}",
                f"  Time: {time_str}",
                f"  Room: {room}",
                f"  Instructor: {teacher}",
                "",
            ])
    else:
        text_lines.append("No university classes scheduled for today. Enjoy your day!")
        text_lines.append("")

    text_lines.extend([
        "─" * 50,
        f"Total: {classes_count} class{'es' if classes_count != 1 else ''} scheduled today.",
        "",
        "---",
        "Sent by Uniflow Academic Suite for Air University students."
    ])
    text = "\n".join(text_lines)

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
        if not recipient:
            return []

        # 1. Get today's classes from TimetableEntry
        scheduled_today = (
            self.db.query(TimetableEntry)
            .filter(TimetableEntry.user_id.in_(user_owner_ids(user_id)), TimetableEntry.weekday == weekday_int)
            .order_by(TimetableEntry.start_time)
            .all()
        )

        if not scheduled_today:
            return []

        # 2. Get student's attendance records
        att_records = self.db.query(AttendanceRecord).filter(AttendanceRecord.user_id.in_(user_owner_ids(user_id))).all()
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
                .filter(Notification.user_id.in_(user_owner_ids(user_id)), Notification.idempotency_key == idempotency_key)
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
                user_id=user_id,
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

    def generate_daily_morning_digest(
        self,
        user_id: str = "dev_student_user",
        target_date: Optional[date] = None,
        threshold: float = 75.0,
        send_immediately: bool = True,
    ) -> Optional[Dict]:
        """
        Deliver a comprehensive Morning Academic Briefing strictly ONCE per day in the morning.
        Includes:
        - Today's complete schedule (classes, times, rooms, teachers)
        - Attendance metrics for each scheduled course (percentage, attended/total, safe bunks or recovery)
        - Academic advisories for courses under threshold (<75%)
        - Google Classroom tasks due within 48 hours
        
        Enforces idempotency: key 'daily-morning-digest:{user_id}:{today.isoformat()}'
        """
        tz = ZoneInfo(settings.timezone)
        if not target_date:
            target_date = datetime.now(tz).date()

        idempotency_key = f"daily-morning-digest:{user_id}:{target_date.isoformat()}"
        existing = (
            self.db.query(Notification)
            .filter(Notification.user_id.in_(user_owner_ids(user_id)), Notification.idempotency_key == idempotency_key)
            .first()
        )
        if existing:
            logger.info(f"Daily morning digest already dispatched today for {user_id} ({target_date})")
            return None

        recipient = get_user_recipient_email(self.db, user_id)
        if not recipient:
            return None
        weekday_int = target_date.weekday()

        # 1. Fetch today's classes
        scheduled_today = (
            self.db.query(TimetableEntry)
            .filter(TimetableEntry.user_id.in_(user_owner_ids(user_id)), TimetableEntry.weekday == weekday_int)
            .order_by(TimetableEntry.start_time)
            .all()
        )

        # 2. Correlate with student attendance records
        att_records = self.db.query(AttendanceRecord).filter(AttendanceRecord.user_id.in_(user_owner_ids(user_id))).all()
        classes_data = []
        urgent_warnings = []
        seen_courses = set()

        for entry in scheduled_today:
            match = match_attendance_to_timetable(entry.subject, att_records) if att_records else None
            pct = None
            attended = 0
            total = 0
            recovery = 0
            safe_bunks = 0

            if match and (match.total or 0) > 0:
                total = match.total
                attended = match.attended or 0
                pct = match.percentage if match.percentage is not None else (attended / total * 100.0)
                recovery = calculate_attendance_recovery(attended, total, threshold)
                safe_bunks = calculate_safe_bunks(attended, total, threshold)

                norm_name = normalize_subject_name(entry.subject)
                if pct < threshold and norm_name not in seen_courses:
                    seen_courses.add(norm_name)
                    urgent_warnings.append({
                        "course": entry.subject,
                        "percentage": pct,
                        "attended": attended,
                        "total": total,
                        "recovery_needed": recovery,
                    })

            classes_data.append({
                "course": entry.subject,
                "time": f"{entry.start_time} - {entry.end_time}",
                "room": entry.room,
                "teacher": entry.teacher,
                "percentage": pct,
                "attended": attended,
                "total": total,
                "recovery_needed": recovery,
                "safe_bunks": safe_bunks,
            })

        # 3. Upcoming GCR assignments due in next 48 hours
        upcoming_tasks = []
        now_dt = datetime.now(tz)
        assignments = (
            self.db.query(Assignment)
            .filter(Assignment.user_id.in_(user_owner_ids(user_id)), Assignment.state == CourseworkState.PUBLISHED)
            .all()
        )
        for a in assignments:
            if a.submission_state in [SubmissionState.TURNED_IN, SubmissionState.RETURNED]:
                continue
            due = a.due_at or a.due_date
            if not due:
                continue
            if due.tzinfo is None:
                due = due.replace(tzinfo=tz)
            time_diff = (due - now_dt).total_seconds()
            if 0 < time_diff <= (48 * 3600):
                cname = a.course.name if a.course else "Course"
                upcoming_tasks.append({
                    "id": a.id,
                    "title": a.title,
                    "course": cname,
                    "due": due.strftime("%A, %d %b at %I:%M %p"),
                    "url": a.url or "https://classroom.google.com",
                })

        date_formatted = target_date.strftime("%A, %d %B %Y")
        html_content, text_content = build_daily_morning_digest_email(
            student_name="Student",
            date_str=date_formatted,
            classes_today=classes_data,
            urgent_warnings=urgent_warnings,
            upcoming_tasks=upcoming_tasks,
        )

        subject = f"[Uniflow] Morning Briefing: Today's Classes & Attendance ({date_formatted})"
        notification = Notification(
            user_id=user_id,
            notification_type="daily_morning_digest",
            recipient=recipient,
            subject=subject,
            payload=text_content,
            external_id=f"digest-{target_date.isoformat()}",
            idempotency_key=idempotency_key,
            status=NotificationStatus.PENDING,
        )
        self.db.add(notification)
        self.db.commit()
        self.db.refresh(notification)

        if send_immediately:
            success = send_email(
                to_email=recipient,
                subject=subject,
                html_content=html_content,
                text_content=text_content,
                from_name="Uniflow",
                categories=["morning-briefing", "daily-digest"],
                custom_args={"notification_id": str(notification.id), "user_id": user_id},
            )
            if success:
                notification.status = NotificationStatus.SENT
                notification.sent_at = func.now()
            else:
                notification.status = NotificationStatus.FAILED
                notification.error = "Delivery failed via SendGrid and SMTP fallback"
            self.db.commit()

        return {
            "notification_id": notification.id,
            "type": "daily_morning_digest",
            "date": target_date.isoformat(),
            "classes_count": len(classes_data),
            "urgent_warnings": len(urgent_warnings),
            "upcoming_tasks": len(upcoming_tasks),
            "recipient": recipient,
            "status": notification.status.value,
        }

    def generate_daily_class_list_email(
        self,
        user_id: str = "dev_student_user",
        target_date: Optional[date] = None,
        send_immediately: bool = True,
    ) -> Optional[Dict]:
        """
        Send a simple daily morning email containing just the list of all classes for the day.
        Unlike the full digest, this only includes the class schedule without attendance metrics or tasks.
        
        Enforces idempotency: key 'daily-class-list:{user_id}:{today.isoformat()}'
        """
        tz = ZoneInfo(settings.timezone)
        if not target_date:
            target_date = datetime.now(tz).date()

        idempotency_key = f"daily-class-list:{user_id}:{target_date.isoformat()}"
        existing = (
            self.db.query(Notification)
            .filter(Notification.user_id.in_(user_owner_ids(user_id)), Notification.idempotency_key == idempotency_key)
            .first()
        )
        if existing:
            logger.info(f"Daily class list email already dispatched today for {user_id} ({target_date})")
            return None

        recipient = get_user_recipient_email(self.db, user_id)
        if not recipient:
            logger.warning(f"No notification email configured for user {user_id}")
            return None

        weekday_int = target_date.weekday()

        # Fetch today's classes
        scheduled_today = (
            self.db.query(TimetableEntry)
            .filter(TimetableEntry.user_id.in_(user_owner_ids(user_id)), TimetableEntry.weekday == weekday_int)
            .order_by(TimetableEntry.start_time)
            .all()
        )

        classes_data = []
        for entry in scheduled_today:
            classes_data.append({
                "course": entry.subject,
                "time": f"{entry.start_time} - {entry.end_time}",
                "room": entry.room or "Main Campus",
                "teacher": entry.teacher or "Department Faculty",
            })

        date_formatted = target_date.strftime("%A, %d %B %Y")
        html_content, text_content = build_daily_class_list_email(
            student_name="Student",
            date_str=date_formatted,
            classes_today=classes_data,
        )

        subject = f"[Uniflow] Today's Class Schedule ({date_formatted})"
        notification = Notification(
            user_id=user_id,
            notification_type="daily_class_list",
            recipient=recipient,
            subject=subject,
            payload=text_content,
            external_id=f"class-list-{target_date.isoformat()}",
            idempotency_key=idempotency_key,
            status=NotificationStatus.PENDING,
        )
        self.db.add(notification)
        self.db.commit()
        self.db.refresh(notification)

        if send_immediately:
            success = send_email(
                to_email=recipient,
                subject=subject,
                html_content=html_content,
                text_content=text_content,
                from_name="Uniflow",
                categories=["class-schedule", "daily-class-list"],
                custom_args={"notification_id": str(notification.id), "user_id": user_id},
            )
            if success:
                notification.status = NotificationStatus.SENT
                notification.sent_at = func.now()
            else:
                notification.status = NotificationStatus.FAILED
                notification.error = "Delivery failed via SendGrid and SMTP fallback"
            self.db.commit()

        return {
            "notification_id": notification.id,
            "type": "daily_class_list",
            "date": target_date.isoformat(),
            "classes_count": len(classes_data),
            "recipient": recipient,
            "status": notification.status.value,
        }

    def generate_upcoming_class_reminders(
        self,
        user_id: str = "dev_student_user",
        target_dt: Optional[datetime] = None,
        lookahead_minutes: Optional[int] = None,
        window_tolerance: Optional[int] = None,
        send_immediately: bool = True,
    ) -> List[Dict]:
        """
        Scan classes starting today and dispatch:
        - By default: 20-minute prior notice (17-24m window) AND 5-minute urgent notice (3-7m window)
        - If custom lookahead_minutes provided: alerts within lookahead_minutes +/- tolerance
        
        Edge cases:
        - Multi-slot continuous lab blocks: Only alert before block start, not mid-lab!
        - Deduplication per milestone, slot, and day.
        """
        tz = ZoneInfo(settings.timezone)
        if not target_dt:
            target_dt = datetime.now(tz)
        elif target_dt.tzinfo is None:
            target_dt = target_dt.replace(tzinfo=tz)

        today = target_dt.date()
        weekday_int = today.weekday()

        # Active hours constraint: 7:00 AM (07:00) to 10:00 PM (22:00) only.
        # Allow 06:35 AM onwards to catch 20m reminders for 07:00 AM morning classes.
        cur_hour = target_dt.hour
        cur_min = target_dt.minute
        if cur_hour < 6 or (cur_hour == 6 and cur_min < 35) or cur_hour > 22 or (cur_hour == 22 and cur_min > 5):
            return []

        recipient = get_user_recipient_email(self.db, user_id)
        if not recipient:
            return []

        # 1. Get today's classes
        classes_today = (
            self.db.query(TimetableEntry)
            .filter(TimetableEntry.user_id.in_(user_owner_ids(user_id)), TimetableEntry.weekday == weekday_int)
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
                parts = entry.start_time.strip().split(":")
                start_h = int(parts[0])
                start_m = int(parts[1])
                class_start = target_dt.replace(hour=start_h, minute=start_m, second=0, microsecond=0)
            except (ValueError, IndexError):
                continue

            diff_seconds = (class_start - target_dt).total_seconds()

            # Determine milestone window
            milestone = None
            minutes_label = 0
            if lookahead_minutes is not None:
                tol_sec = (window_tolerance if window_tolerance is not None else 3) * 60
                if abs(diff_seconds - (lookahead_minutes * 60)) <= tol_sec:
                    milestone = f"{lookahead_minutes}m"
                    minutes_label = max(1, int(round(diff_seconds / 60.0)))
                else:
                    continue
            else:
                # Default hourly schedule check (e.g. running once an hour at :40 past the hour)
                # Matches classes starting in ~20 minutes (window 12 to 28 minutes)
                if (12 * 60) <= diff_seconds <= (28 * 60):
                    milestone = "20m"
                    minutes_label = max(1, int(round(diff_seconds / 60.0)))
                elif (3 * 60) <= diff_seconds <= (7 * 60):
                    milestone = "5m"
                    minutes_label = max(1, int(round(diff_seconds / 60.0)))
                else:
                    continue

            # EDGE CASE: Multi-hour / continuous lab session
            if i > 0:
                prev_entry = classes_today[i - 1]
                norm_curr = normalize_subject_name(entry.subject)
                norm_prev = normalize_subject_name(prev_entry.subject)
                if norm_curr == norm_prev and prev_entry.end_time == entry.start_time:
                    continue

            idempotency_key = f"tt-remind-{milestone}:{user_id}:{entry.id}:{today.isoformat()}"
            existing = (
                self.db.query(Notification)
                .filter(Notification.user_id.in_(user_owner_ids(user_id)), Notification.idempotency_key == idempotency_key)
                .first()
            )
            if existing:
                continue

            session_type = "Laboratory Practical" if is_lab_subject(entry.subject) else "Lecture"
            subject_title = (
                f"[Uniflow] Starting Shortly (5m): {entry.subject} at {entry.start_time}"
                if milestone == "5m"
                else f"[Uniflow] Class in 20 Minutes: {entry.subject} at {entry.start_time}"
            )
            payload_summary = (
                f"Course: {entry.subject}\n"
                f"Session Type: {session_type}\n"
                f"Time: {entry.start_time} - {entry.end_time} (Starting in ~{minutes_label} mins)\n"
                f"Venue: {entry.room or 'Main Campus (Consult Portal)'}\n"
                f"Instructor: {entry.teacher or 'Department Faculty'}"
            )

            html_content, text_content = build_timetable_reminder_email(
                course_name=entry.subject,
                start_time=entry.start_time,
                end_time=entry.end_time,
                room=entry.room,
                teacher=entry.teacher,
                minutes_left=minutes_label,
                session_type=session_type,
            )

            notification = Notification(
                user_id=user_id,
                notification_type=f"timetable_reminder_{milestone}",
                recipient=recipient,
                subject=subject_title,
                payload=payload_summary,
                external_id=f"tt-{entry.id}-{milestone}",
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
                    categories=["class-schedule", f"timetable-reminder-{milestone}"],
                    custom_args={"notification_id": str(notification.id), "user_id": user_id, "milestone": milestone},
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
                "type": f"timetable_reminder_{milestone}",
                "milestone": milestone,
                "course": entry.subject,
                "session_type": session_type,
                "time": entry.start_time,
                "room": entry.room,
                "minutes_left": minutes_label,
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
        Scan synced Google Classroom (GCR) coursework and alert students about approaching deadlines.
        Strictly sends at most ONCE PER DAY per assignment with NO REPETITIONS.
        """
        tz = ZoneInfo(settings.timezone)
        if not target_dt:
            target_dt = datetime.now(tz)
        elif target_dt.tzinfo is None:
            target_dt = target_dt.replace(tzinfo=tz)

        today = target_dt.date()
        recipient = get_user_recipient_email(self.db, user_id)
        if not recipient:
            return []

        assignments = (
            self.db.query(Assignment)
            .filter(Assignment.user_id.in_(user_owner_ids(user_id)), Assignment.state == CourseworkState.PUBLISHED)
            .all()
        )
        if not assignments:
            return []

        generated_alerts = []

        for assignment in assignments:
            # Skip if already submitted / returned
            if assignment.submission_state in [SubmissionState.TURNED_IN, SubmissionState.RETURNED]:
                continue
            if assignment.submission and assignment.submission.submitted_at is not None:
                continue

            due = assignment.due_at or assignment.due_date
            if not due:
                continue
            if due.tzinfo is None:
                due = due.replace(tzinfo=tz)

            time_left = (due - target_dt).total_seconds()
            if time_left <= 0:
                continue  # already past

            hours_left = time_left / 3600.0
            if hours_left > lookahead_hours:
                continue  # not due within lookahead

            # Idempotency key per assignment and DATE: strictly once per day!
            idempotency_key = f"gcr-deadline:{user_id}:{assignment.id}:{today.isoformat()}"
            existing = (
                self.db.query(Notification)
                .filter(Notification.user_id.in_(user_owner_ids(user_id)), Notification.idempotency_key == idempotency_key)
                .first()
            )
            if existing:
                continue

            time_str = f"{max(1, int(round(hours_left * 60)))} minutes" if hours_left < 1 else f"{round(hours_left, 1)} hours"
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
                user_id=user_id,
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

    def notify_new_assignment(
        self,
        assignment: Assignment,
        user_id: str = "dev_student_user",
        send_immediately: bool = True,
    ) -> Optional[Dict]:
        """
        Send exactly ONE email notification when a new Google Classroom task arrives.
        Strictly deduplicated with key 'gcr-new-task:{user_id}:{assignment.id}'.
        """
        idempotency_key = f"gcr-new-task:{user_id}:{assignment.id}"
        existing = (
            self.db.query(Notification)
            .filter(Notification.user_id.in_(user_owner_ids(user_id)), Notification.idempotency_key == idempotency_key)
            .first()
        )
        if existing:
            return None

        recipient = get_user_recipient_email(self.db, user_id)
        if not recipient or assignment.user_id not in user_owner_ids(user_id):
            return None
        course_name = assignment.course.name if assignment.course else "University Course"
        is_quiz = assignment.is_quiz or (assignment.work_type and "quiz" in assignment.work_type.lower())
        due = assignment.due_at or assignment.due_date
        due_formatted = due.strftime("%A, %d %b %Y at %I:%M %p") if due else "No due date specified"

        subject = f"[Uniflow] New Task: {assignment.title} ({course_name})"
        html_content, text_content = build_new_assignment_email(
            assignment_title=assignment.title,
            course_name=course_name,
            due_datetime_str=due_formatted,
            classroom_url=assignment.url,
            description=assignment.description,
            is_quiz=is_quiz,
        )

        notification = Notification(
            user_id=user_id,
            notification_type="new_assignment",
            recipient=recipient,
            subject=subject,
            payload=text_content,
            external_id=f"gcr-new-{assignment.id}",
            idempotency_key=idempotency_key,
            status=NotificationStatus.PENDING,
        )
        self.db.add(notification)
        self.db.commit()
        self.db.refresh(notification)

        if send_immediately:
            success = send_email(
                to_email=recipient,
                subject=subject,
                html_content=html_content,
                text_content=text_content,
                from_name="Uniflow",
                categories=["new-task", "google-classroom"],
                custom_args={"notification_id": str(notification.id), "user_id": user_id, "assignment_id": str(assignment.id)},
            )
            if success:
                notification.status = NotificationStatus.SENT
                notification.sent_at = func.now()
            else:
                notification.status = NotificationStatus.FAILED
                notification.error = "Delivery failed via SendGrid and SMTP fallback"
            self.db.commit()

        return {
            "notification_id": notification.id,
            "type": "new_assignment",
            "title": assignment.title,
            "course": course_name,
            "recipient": recipient,
            "status": notification.status.value,
        }
