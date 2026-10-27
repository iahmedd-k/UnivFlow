import math
import re
import json
from html import escape
from datetime import date, datetime, timedelta, timezone
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
    PortalSyncJob,
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
        if getattr(settings, "notification_email", None) and "@" in settings.notification_email:
            return settings.notification_email.strip()
        if getattr(settings, "smtp_username", None) and "@" in settings.smtp_username:
            return settings.smtp_username.strip()
        if getattr(settings, "smtp_user", None) and "@" in settings.smtp_user:
            return settings.smtp_user.strip()
        # Local fixtures, test suites, and fresh development environments may not have an email
        # configured. Keep alert generation deterministic.
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

    if getattr(settings, "notification_email", None) and "@" in settings.notification_email:
        return settings.notification_email.strip()
    if getattr(settings, "smtp_username", None) and "@" in settings.smtp_username:
        return settings.smtp_username.strip()
    if getattr(settings, "smtp_user", None) and "@" in settings.smtp_user:
        return settings.smtp_user.strip()

    return ""


# ---------------------------------------------------------------------------
# Executive Professional Email System (Institutional Design & Clean Typography)
# ---------------------------------------------------------------------------

def _render_uniflow_email_shell(
    preheader: str,
    brand_title: str,
    header_title: str,
    status_badge_html: str,
    body_html: str,
    footer_lines: List[str],
    accent_gradient: str = "linear-gradient(90deg, #4f46e5 0%, #6366f1 50%, #818cf8 100%)",
) -> str:
    """Render a bulletproof, modern executive transactional email with high-end typography and mobile responsiveness."""
    footer_content = "<br>".join(
        line for line in footer_lines
        if not re.search(r"(?:google classroom integration|\bgcr\b|sync|synchroniz)", line, re.IGNORECASE)
    )
    return f"""<!DOCTYPE html>
<html lang="en" xmlns="http://www.w3.org/1999/xhtml">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <meta http-equiv="X-UA-Compatible" content="IE=edge">
  <meta name="x-apple-disable-message-reformatting">
  <title>{escape(header_title)}</title>
  <style>
    html, body {{
      margin: 0 !important;
      padding: 0 !important;
      height: 100% !important;
      width: 100% !important;
      -webkit-text-size-adjust: 100%;
      -ms-text-size-adjust: 100%;
    }}
    table, td {{
      mso-table-lspace: 0pt !important;
      mso-table-rspace: 0pt !important;
      border-collapse: separate;
    }}
    body {{
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
      background-color: #f1f5f9;
      color: #0f172a;
      margin: 0;
      padding: 32px 12px;
      -webkit-font-smoothing: antialiased;
      -moz-osx-font-smoothing: grayscale;
      line-height: 1.6;
    }}
    .email-wrapper {{
      width: 100%;
      background-color: #f1f5f9;
      padding: 0;
      margin: 0;
    }}
    .email-container {{
      max-width: 600px;
      margin: 0 auto;
      background: #ffffff;
      border-radius: 14px;
      overflow: hidden;
      border: 1px solid #e2e8f0;
      box-shadow: 0 4px 12px rgba(15, 23, 42, 0.05), 0 1px 3px rgba(15, 23, 42, 0.08);
    }}
    .accent-bar {{
      height: 4px;
      background: {accent_gradient};
      line-height: 4px;
      font-size: 0;
    }}
    .header-bar {{
      background: #090d16;
      padding: 26px 32px;
      border-bottom: 1px solid #1e293b;
    }}
    .brand-title {{
      font-size: 11px;
      font-weight: 700;
      letter-spacing: 0.14em;
      text-transform: uppercase;
      color: #94a3b8;
      margin-bottom: 6px;
    }}
    .header-title {{
      color: #ffffff;
      font-size: 21px;
      font-weight: 700;
      margin: 0;
      letter-spacing: -0.02em;
      line-height: 1.3;
    }}
    .content-body {{
      padding: 32px;
      background: #ffffff;
    }}
    .status-badge {{
      display: inline-block;
      padding: 5px 12px;
      border-radius: 9999px;
      font-size: 11px;
      font-weight: 700;
      letter-spacing: 0.06em;
      text-transform: uppercase;
      margin-bottom: 20px;
    }}
    .metric-grid {{
      display: table;
      width: 100%;
      margin: 22px 0;
      background: #f8fafc;
      border: 1px solid #e2e8f0;
      border-radius: 10px;
      overflow: hidden;
    }}
    .metric-cell {{
      display: table-cell;
      width: 50%;
      padding: 18px 16px;
      text-align: center;
      vertical-align: middle;
    }}
    .metric-cell:first-child {{
      border-right: 1px solid #e2e8f0;
    }}
    .metric-value {{
      font-size: 26px;
      font-weight: 800;
      letter-spacing: -0.02em;
      line-height: 1.1;
    }}
    .metric-label {{
      font-size: 11px;
      font-weight: 600;
      text-transform: uppercase;
      letter-spacing: 0.06em;
      color: #64748b;
      margin-top: 6px;
    }}
    .details-table {{
      width: 100%;
      border-collapse: separate;
      border-spacing: 0;
      margin: 20px 0;
      font-size: 13px;
      border: 1px solid #e2e8f0;
      border-radius: 10px;
      overflow: hidden;
    }}
    .details-table tr:last-child td {{
      border-bottom: none;
    }}
    .details-table td {{
      padding: 12px 16px;
      border-bottom: 1px solid #f1f5f9;
      color: #0f172a;
      vertical-align: middle;
    }}
    .details-table td.label-col {{
      width: 32%;
      font-weight: 600;
      color: #475569;
      background: #f8fafc;
      border-right: 1px solid #f1f5f9;
    }}
    .action-notice {{
      background: #fef2f2;
      border: 1px solid #fecaca;
      border-left: 4px solid #ef4444;
      border-radius: 8px;
      padding: 16px 18px;
      font-size: 13px;
      color: #991b1b;
      margin-top: 24px;
      line-height: 1.6;
    }}
    .preparation-box {{
      background: #f8fafc;
      border: 1px solid #e2e8f0;
      border-left: 4px solid #6366f1;
      border-radius: 8px;
      padding: 16px 18px;
      font-size: 13px;
      color: #334155;
      margin-top: 22px;
      line-height: 1.6;
    }}
    .btn-table {{
      margin: 26px auto 10px auto;
    }}
    .btn-primary {{
      display: inline-block;
      background: #0f172a;
      color: #ffffff !important;
      text-decoration: none;
      padding: 12px 26px;
      border-radius: 8px;
      font-size: 13px;
      font-weight: 600;
      letter-spacing: 0.02em;
    }}
    .footer-bar {{
      background: #f8fafc;
      padding: 22px 32px;
      font-size: 11px;
      color: #64748b;
      text-align: center;
      border-top: 1px solid #e2e8f0;
      line-height: 1.65;
    }}
    @media only screen and (max-width: 620px) {{
      .email-container {{
        width: 100% !important;
        border-radius: 8px !important;
      }}
      .content-body {{
        padding: 20px 16px !important;
      }}
      .header-bar {{
        padding: 20px 18px !important;
      }}
      .metric-cell {{
        display: block !important;
        width: 100% !important;
        box-sizing: border-box !important;
        border-right: none !important;
        border-bottom: 1px solid #e2e8f0 !important;
      }}
      .metric-cell:last-child {{
        border-bottom: none !important;
      }}
    }}
  </style>
</head>
<body>
  <div style="display:none;font-size:1px;color:#ffffff;line-height:1px;max-height:0px;max-width:0px;opacity:0;overflow:hidden;mso-hide:all;">
    {escape(preheader)}
    &#847; &zwnj; &nbsp; &#8199; &shy; &#847; &zwnj; &nbsp; &#8199; &shy; &#847; &zwnj; &nbsp; &#8199; &shy; &#847; &zwnj; &nbsp; &#8199; &shy;
  </div>
  <table role="presentation" class="email-wrapper" width="100%" border="0" cellspacing="0" cellpadding="0">
    <tr>
      <td align="center">
        <div class="email-container">
          <div class="accent-bar"></div>
          <div class="header-bar">
            <div class="brand-title">{escape(brand_title)}</div>
            <h1 class="header-title">{escape(header_title)}</h1>
          </div>
          <div class="content-body">
            {status_badge_html}
            {body_html}
          </div>
          <div class="footer-bar">
            {footer_content}
          </div>
        </div>
      </td>
    </tr>
  </table>
</body>
</html>"""


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
    room_str = room if (room and room.strip() and room.lower() not in ("none", "-", "venue to be confirmed via portal")) else "Room to be announced"
    teacher_str = teacher if (teacher and teacher.strip() and teacher.lower() != "none") else "Department Faculty"
    recovery_classes = calculate_attendance_recovery(attended, total, threshold)

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

    preheader = f"Academic Advisory: Your attendance in {course_name} is currently at {percentage:.1f}%, below the required {threshold:.0f}% threshold. Class today in Room {room_str}."
    status_badge_html = f'<div class="status-badge" style="background:#fef2f2; color:#991b1b; border:1px solid #fecaca;">ATTENDANCE DEFICIT · BELOW {threshold:.0f}%</div>'

    body_html = f"""
      <p style="font-size:14px; color:#334155; margin:0 0 20px 0; line-height:1.6;">
        A lecture session for <strong>{escape(course_name)}</strong> is scheduled today at <strong>{escape(class_time)}</strong> in <strong>Room {escape(room_str)}</strong>.
        Your current cumulative attendance is below the university's examination eligibility requirement.
      </p>

      <div class="metric-grid">
        <div class="metric-cell">
          <div class="metric-value" style="color:#dc2626;">{percentage:.1f}%</div>
          <div class="metric-label">Current Attendance</div>
        </div>
        <div class="metric-cell">
          <div class="metric-value" style="color:#0f172a;">{attended} / {total}</div>
          <div class="metric-label">Classes Attended</div>
        </div>
      </div>

      <table class="details-table" role="presentation">
        <tr>
          <td class="label-col">Course Name</td>
          <td><strong>{escape(course_name)}</strong></td>
        </tr>
        <tr>
          <td class="label-col">Session Time</td>
          <td><strong>{escape(class_time)}</strong></td>
        </tr>
        <tr>
          <td class="label-col">Room / Classroom</td>
          <td><strong style="color:#0f172a; font-size:13px; background:#f1f5f9; padding:2px 8px; border-radius:4px; border:1px solid #cbd5e1;">Room {escape(room_str)}</strong></td>
        </tr>
        <tr>
          <td class="label-col">Instructor</td>
          <td>{escape(teacher_str)}</td>
        </tr>
        <tr>
          <td class="label-col">Policy Requirement</td>
          <td>Minimum {threshold:.0f}% cumulative attendance for final examination clearance</td>
        </tr>
      </table>

      <div class="action-notice">
        {recovery_note}
      </div>
    """

    footer_lines = [
        "Uniflow Academic Suite · Air University Student Academic Alert Service.",
        "Automated notice generated based on the official University Student Portal records.",
    ]

    html = _render_uniflow_email_shell(
        preheader=preheader,
        brand_title="Uniflow Academic Suite · Air University",
        header_title="Academic Advisory: Low Attendance Warning",
        status_badge_html=status_badge_html,
        body_html=body_html,
        footer_lines=footer_lines,
        accent_gradient="linear-gradient(90deg, #dc2626 0%, #ef4444 50%, #f87171 100%)",
    )

    clean_recovery_note = recovery_note.replace("<strong>", "").replace("</strong>", "")
    text = f"""Low Attendance Advisory: {course_name}

Course: {course_name}
Current Attendance: {percentage:.1f}% ({attended}/{total} classes attended)
Minimum Required: {threshold:.0f}%

Class Scheduled Today:
- Time: {class_time}
- Room: {room_str}
- Instructor: {teacher_str}

ACTION REQUIRED:
{clean_recovery_note}

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
    room_str = room if (room and room.strip() and room.lower() not in ("none", "-", "venue to be confirmed via portal")) else "Room to be announced"
    teacher_str = teacher if (teacher and teacher.strip() and teacher.lower() != "none") else "Department Faculty"

    preheader = f"Class Reminder: {course_name} starts in ~{minutes_left} minutes ({start_time} - {end_time}) in Room {room_str}."
    status_badge_html = f'<div class="status-badge" style="background:#eef2ff; color:#3730a3; border:1px solid #c7d2fe;">SCHEDULE NOTICE · STARTING IN ~{minutes_left} MINUTES</div>'

    body_html = f"""
      <table class="details-table" role="presentation">
        <tr>
          <td class="label-col">Course</td>
          <td><strong>{escape(course_name)}</strong></td>
        </tr>
        <tr>
          <td class="label-col">Time Window</td>
          <td><strong>{escape(start_time)} - {escape(end_time)}</strong></td>
        </tr>
        <tr>
          <td class="label-col">Room / Classroom</td>
          <td><strong style="color:#0f172a; font-size:14px; background:#f1f5f9; padding:2px 8px; border-radius:4px; border:1px solid #cbd5e1;">Room {escape(room_str)}</strong></td>
        </tr>
        <tr>
          <td class="label-col">Instructor</td>
          <td>{escape(teacher_str)}</td>
        </tr>
        <tr>
          <td class="label-col">Session Type</td>
          <td>{escape(session_type)}</td>
        </tr>
      </table>

      <div class="preparation-box">
        <strong>Preparation Notice:</strong> Please proceed to <strong>Room {escape(room_str)}</strong> now to ensure on-time arrival.
        Verify that you have your course notes, student ID, and any relevant lab materials ready.
      </div>
    """

    footer_lines = [
        "Uniflow Academic Suite · Air University Student Weekly Schedule Tracker.",
        f"Automated {minutes_left}-minute prior notice dispatched by Uniflow.",
    ]

    html = _render_uniflow_email_shell(
        preheader=preheader,
        brand_title="Uniflow Academic Suite · Air University",
        header_title="Upcoming Class Reminder",
        status_badge_html=status_badge_html,
        body_html=body_html,
        footer_lines=footer_lines,
        accent_gradient="linear-gradient(90deg, #4338ca 0%, #6366f1 50%, #818cf8 100%)",
    )

    text = f"""Class Starts in ~{minutes_left} Minutes: {course_name}

Course: {course_name}
Time: {start_time} - {end_time}
Room: {room_str}
Instructor: {teacher_str}
Session Type: {session_type}

Please proceed to Room {room_str} now to ensure on-time arrival.

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
    action_url = classroom_url or "https://classroom.google.com"

    preheader = f"Deadline Notice: {assignment_title} for {course_name} is due in {time_remaining_str} ({due_datetime_str})."
    status_badge_html = f'<div class="status-badge" style="background:#fffbeb; color:#92400e; border:1px solid #fde68a;">DEADLINE NOTICE · DUE IN {escape(time_remaining_str.upper())}</div>'

    body_html = f"""
      <table class="details-table" role="presentation">
        <tr>
          <td class="label-col">Task Title</td>
          <td><strong>{escape(assignment_title)}</strong></td>
        </tr>
        <tr>
          <td class="label-col">Course</td>
          <td>{escape(course_name)}</td>
        </tr>
        <tr>
          <td class="label-col">Work Type</td>
          <td>{escape(work_type_label)}</td>
        </tr>
        <tr>
          <td class="label-col">Submission Deadline</td>
          <td><strong>{escape(due_datetime_str)}</strong></td>
        </tr>
        <tr>
          <td class="label-col">Current Status</td>
          <td><span style="display:inline-block; padding:2px 8px; border-radius:4px; font-size:11px; font-weight:700; background:#fffbeb; color:#92400e; border:1px solid #fde68a;">Pending Submission</span></td>
        </tr>
      </table>

      <table class="btn-table" role="presentation" border="0" cellspacing="0" cellpadding="0">
        <tr>
          <td align="center" style="border-radius:8px; background:#0f172a;">
            <a href="{escape(action_url, quote=True)}" target="_blank" class="btn-primary">View in Google Classroom</a>
          </td>
        </tr>
      </table>
    """

    footer_lines = [
        "Uniflow Academic Suite · Coursework Notifications.",
        "To submit, turn in your completed files via Google Classroom or the Uniflow Assignment Portal.",
    ]

    html = _render_uniflow_email_shell(
        preheader=preheader,
        brand_title="Uniflow Academic Suite · Coursework Notifications",
        header_title="Coursework Deadline Reminder",
        status_badge_html=status_badge_html,
        body_html=body_html,
        footer_lines=footer_lines,
        accent_gradient="linear-gradient(90deg, #d97706 0%, #f59e0b 50%, #fbbf24 100%)",
    )

    text = f"""Coursework Deadline Reminder: {assignment_title}

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
    sync_warnings: Optional[List[Dict]] = None,
) -> Tuple[str, str]:
    """
    Generate an executive HTML and plain-text email for the daily morning academic briefing.
    Delivers today's complete schedule with room numbers, attendance status for each course,
    safe bunk / recovery metrics, and approaching coursework deadlines.
    """
    classes_count = len(classes_today)
    advisories_count = len(urgent_warnings)
    tasks_count = len(upcoming_tasks)

    # Build classes rows with room numbers highlighted
    if classes_today:
        class_rows_html = ""
        for item in classes_today:
            course = escape(str(item.get("course", "")))
            time_str = escape(str(item.get("time", "")))
            raw_room = str(item.get("room") or "").strip()
            room = escape(raw_room) if raw_room and raw_room.lower() not in ("none", "-", "main campus") else "Room to be announced"
            teacher = escape(str(item.get("teacher") or "Department Faculty"))
            pct = item.get("percentage")
            attended = item.get("attended", 0)
            total = item.get("total", 0)
            recovery = item.get("recovery_needed", 0)
            safe_bunks = item.get("safe_bunks", 0)

            if pct is not None and total > 0:
                if pct < 75.0:
                    att_badge = f'<span style="display:inline-block; padding:3px 9px; border-radius:4px; font-size:11px; font-weight:700; background:#fef2f2; color:#991b1b; border:1px solid #fecaca;">{pct:.1f}% ({attended}/{total}) · Need {recovery} to reach 75%</span>'
                else:
                    bunk_text = f" · {safe_bunks} safe bunk{'s' if safe_bunks != 1 else ''}" if safe_bunks > 0 else " · On borderline"
                    att_badge = f'<span style="display:inline-block; padding:3px 9px; border-radius:4px; font-size:11px; font-weight:700; background:#f0fdf4; color:#166534; border:1px solid #bbf7d0;">{pct:.1f}% ({attended}/{total}){bunk_text}</span>'
            else:
                att_badge = '<span style="display:inline-block; padding:3px 8px; border-radius:4px; font-size:11px; font-weight:600; background:#f1f5f9; color:#64748b; border:1px solid #e2e8f0;">No portal records</span>'

            class_rows_html += f"""
            <tr>
              <td style="padding:14px 16px; border-bottom:1px solid #f1f5f9; vertical-align:top; width:34%; background:#fafafa;">
                <div style="font-weight:700; color:#0f172a; font-size:13px;">{time_str}</div>
                <div style="margin-top:5px;"><span style="display:inline-block; font-size:11px; font-weight:700; color:#0f172a; background:#e2e8f0; padding:2px 8px; border-radius:4px; border:1px solid #cbd5e1;">Room {room}</span></div>
              </td>
              <td style="padding:14px 16px; border-bottom:1px solid #f1f5f9; vertical-align:top;">
                <div style="font-weight:600; color:#1e293b; font-size:13px;">{course}</div>
                <div style="font-size:11px; color:#64748b; margin-top:2px;">{teacher}</div>
                <div style="margin-top:6px;">{att_badge}</div>
              </td>
            </tr>
            """
    else:
        class_rows_html = """
        <tr>
          <td colspan="2" style="padding:28px 20px; text-align:center; color:#64748b; font-size:13px; font-style:italic;">
            No university classes scheduled for today. Have a productive day!
          </td>
        </tr>
        """

    # Build advisories section
    advisories_html = ""
    if urgent_warnings:
        advisory_items_html = ""
        for adv in urgent_warnings:
            c = escape(str(adv.get("course", "")))
            p = adv.get("percentage", 0.0)
            rec = adv.get("recovery_needed", 0)
            advisory_items_html += f"""
            <li style="margin-bottom:8px; font-size:13px; color:#991b1b; line-height:1.5;">
              <strong>{c}</strong>: Cumulative attendance at <strong>{p:.1f}%</strong>. You must attend today's session and the next <strong>{rec} consecutive classes</strong> to restore examination eligibility.
            </li>
            """
        advisories_html = f"""
        <div style="margin:22px 0; background:#fef2f2; border:1px solid #fecaca; border-left:4px solid #ef4444; border-radius:8px; padding:18px;">
          <div style="font-size:11px; font-weight:700; text-transform:uppercase; letter-spacing:0.08em; color:#991b1b; margin-bottom:10px;">
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
            title = escape(str(t.get("title", "")))
            cname = escape(str(t.get("course", "")))
            due_str = escape(str(t.get("due", "")))
            candidate_url = str(t.get("url") or "")
            url = candidate_url if candidate_url.startswith("https://classroom.google.com/") else "https://classroom.google.com/"
            task_rows_html += f"""
            <tr>
              <td style="padding:12px 16px; border-bottom:1px solid #f1f5f9; font-size:13px; color:#1e293b;">
                <strong>{title}</strong>
                <div style="font-size:11px; color:#64748b; margin-top:2px;">{cname} · Due: {due_str}</div>
              </td>
              <td style="padding:12px 16px; border-bottom:1px solid #f1f5f9; text-align:right;">
                <a href="{escape(url, quote=True)}" target="_blank" style="font-size:12px; font-weight:700; color:#4f46e5; text-decoration:none; padding:4px 10px; background:#eef2ff; border-radius:6px;">Open &rarr;</a>
              </td>
            </tr>
            """
        tasks_html = f"""
        <div style="margin:26px 0 16px 0;">
          <div style="font-size:11px; font-weight:700; text-transform:uppercase; letter-spacing:0.08em; color:#64748b; margin-bottom:10px;">
            Pending Coursework &amp; Deadlines
          </div>
          <table style="width:100%; border-collapse:separate; border-spacing:0; background:#ffffff; border:1px solid #e2e8f0; border-radius:8px; overflow:hidden;" role="presentation">
            {task_rows_html}
          </table>
        </div>
        """

    dashboard_url = escape(settings.frontend_url.rstrip("/") + "/dashboard", quote=True)
    preheader = f"Morning Academic Briefing for {date_str}: {classes_count} classes scheduled (with rooms), {advisories_count} attendance warnings, {tasks_count} active tasks."
    status_badge_html = f'<div class="status-badge" style="background:#eef2ff; color:#3730a3; border:1px solid #c7d2fe;">DAILY BRIEFING · {escape(date_str.upper())}</div>'

    body_html = f"""
      <p style="margin:0 0 18px 0; font-size:14px; color:#334155; line-height:1.6;">
        Good morning, <strong>{escape(student_name)}</strong>! Here is your personalized daily academic overview for <strong>{escape(date_str)}</strong>.
      </p>

      <table style="width:100%; border-collapse:separate; border-spacing:0; margin:18px 0 24px 0; background:#f8fafc; border:1px solid #e2e8f0; border-radius:10px; overflow:hidden;" role="presentation">
        <tr>
          <td style="width:33.33%; padding:16px 12px; text-align:center; border-right:1px solid #e2e8f0;">
            <div style="font-size:22px; font-weight:800; color:#0f172a; line-height:1.1;">{classes_count}</div>
            <div style="font-size:10px; font-weight:600; text-transform:uppercase; letter-spacing:0.06em; color:#64748b; margin-top:4px;">Classes Today</div>
          </td>
          <td style="width:33.33%; padding:16px 12px; text-align:center; border-right:1px solid #e2e8f0;">
            <div style="font-size:22px; font-weight:800; color:{'#dc2626' if advisories_count > 0 else '#16a34a'}; line-height:1.1;">{advisories_count}</div>
            <div style="font-size:10px; font-weight:600; text-transform:uppercase; letter-spacing:0.06em; color:#64748b; margin-top:4px;">Advisories (&lt;75%)</div>
          </td>
          <td style="width:33.33%; padding:16px 12px; text-align:center;">
            <div style="font-size:22px; font-weight:800; color:#0f172a; line-height:1.1;">{tasks_count}</div>
            <div style="font-size:10px; font-weight:600; text-transform:uppercase; letter-spacing:0.06em; color:#64748b; margin-top:4px;">Active Tasks</div>
          </td>
        </tr>
      </table>

      {advisories_html}

      <div style="font-size:11px; font-weight:700; text-transform:uppercase; letter-spacing:0.08em; color:#64748b; margin:24px 0 10px 0;">
        Today's Class Schedule (with Classroom Locations)
      </div>
      <table style="width:100%; border-collapse:separate; border-spacing:0; border:1px solid #e2e8f0; border-radius:8px; overflow:hidden; background:#ffffff;" role="presentation">
        {class_rows_html}
      </table>

      {tasks_html}

      <table class="btn-table" role="presentation" border="0" cellspacing="0" cellpadding="0">
        <tr>
          <td align="center" style="border-radius:8px; background:#0f172a;">
            <a href="{dashboard_url}" target="_blank" class="btn-primary">Open Uniflow Dashboard</a>
          </td>
        </tr>
      </table>
    """

    footer_lines = [
        "Daily Morning Digest dispatched strictly once per day by Uniflow Academic Suite.",
        "Air University Student Intelligence &amp; Schedule Synchronization.",
    ]

    html = _render_uniflow_email_shell(
        preheader=preheader,
        brand_title="Uniflow Academic Suite · Daily Briefing",
        header_title="Daily Schedule & Attendance Digest",
        status_badge_html=status_badge_html,
        body_html=body_html,
        footer_lines=footer_lines,
        accent_gradient="linear-gradient(90deg, #2563eb 0%, #4f46e5 50%, #7c3aed 100%)",
    )

    text_lines = [
        f"Daily Academic Briefing: {date_str}",
        "",
        f"Classes Today: {classes_count} | Attendance Advisories: {advisories_count} | Active Tasks: {tasks_count}",
        "",
        "--- TODAY'S CLASS SCHEDULE (WITH ROOMS) ---",
    ]
    if classes_today:
        for item in classes_today:
            c = item.get("course", "")
            t = item.get("time", "")
            r = item.get("room") or "Room to be announced"
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
            text_lines.append(f"• {t}: {c} | Room: {r} | Attendance: {att_info}")
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
    action_url = classroom_url or "https://classroom.google.com"
    desc_snippet = (description[:250] + "...") if description and len(description) > 250 else (description or "No additional instructions provided.")

    preheader = f"New Coursework: {assignment_title} has been posted for {course_name}. Due: {due_datetime_str}."
    status_badge_html = f'<div class="status-badge" style="background:#eff6ff; color:#1d4ed8; border:1px solid #bfdbfe;">NEW {escape(work_type_label.upper())} · {escape(course_name.upper())}</div>'

    body_html = f"""
      <table class="details-table" role="presentation">
        <tr>
          <td class="label-col">Task Title</td>
          <td><strong>{escape(assignment_title)}</strong></td>
        </tr>
        <tr>
          <td class="label-col">Course</td>
          <td>{escape(course_name)}</td>
        </tr>
        <tr>
          <td class="label-col">Work Type</td>
          <td>{escape(work_type_label)}</td>
        </tr>
        <tr>
          <td class="label-col">Submission Due</td>
          <td><strong>{escape(due_datetime_str)}</strong></td>
        </tr>
        <tr>
          <td class="label-col">Instructions</td>
          <td style="color:#475569; font-size:13px; line-height:1.6;">{escape(desc_snippet)}</td>
        </tr>
      </table>

      <table class="btn-table" role="presentation" border="0" cellspacing="0" cellpadding="0">
        <tr>
          <td align="center" style="border-radius:8px; background:#0f172a;">
            <a href="{escape(action_url, quote=True)}" target="_blank" class="btn-primary">View in Google Classroom</a>
          </td>
        </tr>
      </table>
    """

    footer_lines = [
        "Dispatched strictly once upon new coursework arrival by Uniflow Academic Suite.",
        "Air University Student Coursework Notifications.",
    ]

    html = _render_uniflow_email_shell(
        preheader=preheader,
        brand_title="Uniflow Academic Suite · Coursework Notifications",
        header_title="New Coursework Posted",
        status_badge_html=status_badge_html,
        body_html=body_html,
        footer_lines=footer_lines,
        accent_gradient="linear-gradient(90deg, #0284c7 0%, #2563eb 50%, #4f46e5 100%)",
    )

    text = f"""New Coursework: {assignment_title} ({course_name})

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
    Generate an executive HTML and plain-text email for the daily 7:00 AM class schedule list.
    Lists all classes of the day with their scheduled time window, room number, and instructor.
    """
    classes_count = len(classes_today)
    day_of_week = date_str.split(",")[0] if "," in date_str else date_str

    if classes_today:
        class_rows_html = ""
        for item in classes_today:
            course = escape(str(item.get("course", "")))
            time_str = escape(str(item.get("time", "")))
            raw_room = str(item.get("room") or "").strip()
            room = escape(raw_room) if raw_room and raw_room.lower() not in ("none", "-", "main campus") else "Room to be announced"
            teacher = escape(str(item.get("teacher") or "Department Faculty"))

            class_rows_html += f"""
            <tr>
              <td style="padding:14px 16px; border-bottom:1px solid #f1f5f9; vertical-align:top; width:34%; background:#fafafa;">
                <div style="font-weight:700; color:#0f172a; font-size:13px;">{time_str}</div>
                <div style="margin-top:5px;"><span style="display:inline-block; font-size:11px; font-weight:700; color:#0f172a; background:#e2e8f0; padding:2px 8px; border-radius:4px; border:1px solid #cbd5e1;">Room {room}</span></div>
              </td>
              <td style="padding:14px 16px; border-bottom:1px solid #f1f5f9; vertical-align:top;">
                <div style="font-weight:600; color:#1e293b; font-size:13px;">{course}</div>
                <div style="font-size:11px; color:#64748b; margin-top:3px;">Instructor: {teacher}</div>
              </td>
            </tr>
            """
    else:
        class_rows_html = """
        <tr>
          <td colspan="2" style="padding:28px 20px; text-align:center; color:#64748b; font-size:13px; font-style:italic;">
            No university classes scheduled for today. Enjoy your day!
          </td>
        </tr>
        """

    preheader = f"Daily Class Schedule for {day_of_week}, {date_str}: {classes_count} class{'es' if classes_count != 1 else ''} scheduled with room numbers."
    status_badge_html = f'<div class="status-badge" style="background:#eff6ff; color:#1d4ed8; border:1px solid #bfdbfe;">DAILY SCHEDULE · {escape(date_str.upper())}</div>'

    body_html = f"""
      <p style="margin:0 0 18px 0; font-size:14px; color:#334155; line-height:1.6;">
        Good morning, <strong>{escape(student_name)}</strong>! Here is your official daily class schedule for <strong>{escape(day_of_week)}</strong>, <strong>{escape(date_str)}</strong>.
      </p>

      <table class="details-table" style="margin-top:14px;" role="presentation">
        <thead>
          <tr>
            <th style="width:34%; background:#f8fafc; padding:12px 16px; text-align:left; font-size:11px; font-weight:700; text-transform:uppercase; letter-spacing:0.06em; color:#475569; border-bottom:1px solid #e2e8f0;">Time &amp; Room</th>
            <th style="background:#f8fafc; padding:12px 16px; text-align:left; font-size:11px; font-weight:700; text-transform:uppercase; letter-spacing:0.06em; color:#475569; border-bottom:1px solid #e2e8f0;">Course &amp; Instructor</th>
          </tr>
        </thead>
        <tbody>
          {class_rows_html}
        </tbody>
      </table>

      <div style="margin-top:22px; padding:14px 18px; background:#f0fdf4; border:1px solid #bbf7d0; border-left:4px solid #16a34a; border-radius:8px; font-size:13px; color:#166534;">
        <strong>Schedule Summary:</strong> {classes_count} class{'es' if classes_count != 1 else ''} scheduled today. Please arrive at your respective rooms on time.
      </div>
    """

    footer_lines = [
        "Dispatched daily at 07:00 AM by Uniflow Academic Suite.",
        "Air University Student Schedule Notifications.",
    ]

    html = _render_uniflow_email_shell(
        preheader=preheader,
        brand_title="Uniflow Academic Suite · Daily Schedule",
        header_title="Today's Class Schedule & Room Numbers",
        status_badge_html=status_badge_html,
        body_html=body_html,
        footer_lines=footer_lines,
        accent_gradient="linear-gradient(90deg, #0d9488 0%, #0284c7 50%, #2563eb 100%)",
    )

    text_lines = [
        f"Today's Class Schedule: {date_str}",
        "",
        f"Good morning, {student_name}! Here is your class schedule for {day_of_week}, {date_str}.",
        "",
        "─" * 50,
    ]

    if classes_today:
        for item in classes_today:
            course = item.get("course", "")
            time_str = item.get("time", "")
            raw_room = str(item.get("room") or "").strip()
            r = raw_room if raw_room and raw_room.lower() not in ("none", "-", "main campus") else "Room to be announced"
            teacher = item.get("teacher") or "Department Faculty"
            text_lines.extend([
                f"• {course}",
                f"  Time: {time_str}",
                f"  Room: {r}",
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
        timezone_name: Optional[str] = None,
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
            room_suffix = f" • Room {entry.room}" if (entry.room and entry.room.strip() and entry.room.lower() not in ("none", "-")) else ""
            subject_title = f"[Uniflow] Academic Advisory: Low Attendance in {entry.subject} ({pct:.1f}%){room_suffix}"
            payload_summary = (
                f"Course: {entry.subject}\n"
                f"Current Attendance: {pct:.1f}% ({attended_count}/{total_held} classes attended)\n"
                f"Minimum Required: {threshold:.0f}%\n"
                f"Consecutive Classes Needed to Recover: {recovery_needed}\n"
                f"Scheduled Time: {entry.start_time} - {entry.end_time} in {entry.room or 'Room to be announced'}\n"
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
        timezone_name: Optional[str] = None,
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
        tz = ZoneInfo(timezone_name or settings.timezone)
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

        profile_row = self.db.query(Setting).filter(Setting.key == f"student_profile_{user_id}").first()
        if not profile_row:
            profile_row = self.db.query(Setting).filter(Setting.key == f"clerk_user_{user_id}").first()
        student_name = "Student"
        if profile_row and profile_row.value:
            try:
                prof_data = json.loads(profile_row.value)
                student_name = prof_data.get("name") or prof_data.get("student_name") or "Student"
            except Exception:
                pass

        date_formatted = target_date.strftime("%A, %d %B %Y")
        html_content, text_content = build_daily_morning_digest_email(
            student_name=student_name,
            date_str=date_formatted,
            classes_today=classes_data,
            urgent_warnings=urgent_warnings,
            upcoming_tasks=upcoming_tasks,
        )

        subject = f"[Uniflow] Daily Academic Briefing: Today's Classes & Attendance ({date_formatted})"
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

        profile_row = self.db.query(Setting).filter(Setting.key == f"student_profile_{user_id}").first()
        if not profile_row:
            profile_row = self.db.query(Setting).filter(Setting.key == f"clerk_user_{user_id}").first()
        student_name = "Student"
        if profile_row and profile_row.value:
            try:
                prof_data = json.loads(profile_row.value)
                student_name = prof_data.get("name") or prof_data.get("student_name") or "Student"
            except Exception:
                pass

        classes_data = []
        for entry in scheduled_today:
            classes_data.append({
                "course": entry.subject,
                "time": f"{entry.start_time} - {entry.end_time}",
                "room": entry.room or "Room to be announced",
                "teacher": entry.teacher or "Department Faculty",
            })

        date_formatted = target_date.strftime("%A, %d %B %Y")
        html_content, text_content = build_daily_class_list_email(
            student_name=student_name,
            date_str=date_formatted,
            classes_today=classes_data,
        )

        subject = f"[Uniflow] Daily Class Schedule — {date_formatted} (All Classes & Rooms)"
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
            room_suffix = f" • Room {entry.room}" if (entry.room and entry.room.strip() and entry.room.lower() not in ("none", "-")) else ""
            subject_title = (
                f"[Uniflow] Urgent Class Reminder: {entry.subject} at {entry.start_time}{room_suffix} (Starts in ~5m)"
                if milestone == "5m"
                else f"[Uniflow] Upcoming Class Reminder: {entry.subject} at {entry.start_time}{room_suffix}"
            )
            payload_summary = (
                f"Course: {entry.subject}\n"
                f"Session Type: {session_type}\n"
                f"Time: {entry.start_time} - {entry.end_time} (Starting in ~{minutes_label} mins)\n"
                f"Room: {entry.room or 'Room to be announced'}\n"
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
            subject_title = f"[Uniflow] Coursework Deadline Reminder: {assignment.title} ({course_name})"
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

        subject = f"[Uniflow] New Coursework Assigned: {assignment.title} ({course_name})"
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
