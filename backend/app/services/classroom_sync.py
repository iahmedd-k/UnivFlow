import json
import hashlib
import time
import random
from datetime import datetime, timedelta, timezone
from typing import Optional, List, Dict, Any
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from sqlalchemy.orm import Session
from app.db.database import get_db
from app.db.repositories import CourseRepository, AssignmentRepository, ClassScheduleRepository, AnnouncementRepository
from app.db.models import (
    BrowserAutomationJob,
    Course,
    Assignment,
    ClassSchedule,
    GoogleCredential,
    SubmissionState,
    Setting,
    AssignmentSolution,
)
from app.core.config import settings
from app.core.logging import logger
from app.core.redis import check_rate_limit as redis_check_rate_limit

CLASSROOM_SYNC_RATE_LIMIT_KEY = "classroom_sync_api"
CLASSROOM_SYNC_RATE_LIMIT = 60  # requests per minute
CLASSROOM_SYNC_RATE_WINDOW = 60  # seconds


class ClassroomSyncService:
    def __init__(self, db: Session, user_id: str = "legacy"):
        self.db = db
        self.user_id = user_id
        self.service = None
        self._new_assignments: Dict[int, Optional[datetime]] = {}
        self._submission_sync_failed: set[str] = set()
        self._load_credentials()

    def _check_rate_limit(self) -> bool:
        """Check rate limit using Redis-backed sliding window"""
        return redis_check_rate_limit(
            f"{CLASSROOM_SYNC_RATE_LIMIT_KEY}:{self.user_id}",
            CLASSROOM_SYNC_RATE_LIMIT,
            CLASSROOM_SYNC_RATE_WINDOW
        )

    def _execute_with_rate_limit(self, func, *args, **kwargs):
        """Execute API call with rate limiting and exponential backoff"""
        max_retries = 3
        base_delay = 2.0
        
        for attempt in range(max_retries):
            if not self._check_rate_limit():
                delay = base_delay * (2 ** attempt) + random.uniform(0, 1)
                logger.warning(f"Rate limit hit, waiting {delay:.1f}s (attempt {attempt + 1}/{max_retries})")
                time.sleep(delay)
                continue
            
            try:
                return func(*args, **kwargs)
            except HttpError as e:
                status = getattr(e.resp, "status", 0)
                if status == 429:  # Rate limited
                    delay = base_delay * (2 ** attempt) + random.uniform(0, 1)
                    logger.warning(f"HTTP 429 rate limited, waiting {delay:.1f}s")
                    time.sleep(delay)
                    continue
                elif status in (500, 502, 503, 504):  # Server errors
                    delay = base_delay * (2 ** attempt) + random.uniform(0, 1)
                    logger.warning(f"HTTP {status} server error, waiting {delay:.1f}s")
                    time.sleep(delay)
                    continue
                raise
            except Exception as e:
                logger.error(f"API call failed: {e}")
                raise
        
        raise RuntimeError(f"Max retries ({max_retries}) exceeded for Classroom API call")

    def _load_credentials(self) -> bool:
        """Load Google credentials from database"""
        cred_row = self.db.query(GoogleCredential).filter(
            GoogleCredential.user_id == self.user_id
        ).first()
        if not cred_row:
            logger.warning("No Google credentials found in database")
            return False

        try:
            creds = Credentials(
                token=cred_row.access_token,
                refresh_token=cred_row.refresh_token,
                token_uri=cred_row.token_uri or "https://oauth2.googleapis.com/token",
                client_id=cred_row.client_id or settings.google_client_id,
                client_secret=cred_row.client_secret or settings.google_client_secret,
                scopes=json.loads(cred_row.scopes) if cred_row.scopes else [],
            )

            if creds.expired and creds.refresh_token:
                from google.auth.transport.requests import Request
                creds.refresh(Request())
                # Update stored token
                cred_row.access_token = creds.token
                cred_row.expiry = creds.expiry
                self.db.commit()

            self.service = build("classroom", "v1", credentials=creds, cache_discovery=False)
            logger.info("Google Classroom service initialized")
            return True

        except Exception as e:
            logger.error(f"Failed to initialize Classroom service: {e}")
            return False

    def _get_drive_service(self):
        """Build a Drive service from stored credentials (for material text extraction)."""
        try:
            from google.oauth2.credentials import Credentials as GCreds
            from googleapiclient.discovery import build as gbuild

            cred_row = self.db.query(GoogleCredential).filter(
                GoogleCredential.user_id == self.user_id
            ).first()
            if not cred_row:
                return None

            creds = GCreds(
                token=cred_row.access_token,
                refresh_token=cred_row.refresh_token,
                token_uri=cred_row.token_uri or "https://oauth2.googleapis.com/token",
                client_id=cred_row.client_id or settings.google_client_id,
                client_secret=cred_row.client_secret or settings.google_client_secret,
                scopes=json.loads(cred_row.scopes) if cred_row.scopes else [],
            )
            if creds.expired and creds.refresh_token:
                from google.auth.transport.requests import Request
                creds.refresh(Request())
                cred_row.access_token = creds.token
                cred_row.expiry = creds.expiry
                self.db.commit()

            return gbuild("drive", "v3", credentials=creds, cache_discovery=False)
        except Exception as e:
            logger.warning(f"Could not initialize Drive service for material extraction: {e}")
            return None

    def _extract_drive_file_text(self, drive_service, file_id: str, mime_type: str) -> str:
        """Extract plain text from a Drive file (Google Doc, PDF, or text)."""
        try:
            import io
            if mime_type == "application/vnd.google-apps.document":
                data = drive_service.files().export_media(fileId=file_id, mimeType="text/plain").execute()
                return data.decode("utf-8", errors="ignore") if isinstance(data, bytes) else str(data)
            if mime_type == "application/vnd.google-apps.presentation":
                data = drive_service.files().export_media(fileId=file_id, mimeType="text/plain").execute()
                return data.decode("utf-8", errors="ignore") if isinstance(data, bytes) else str(data)
            if mime_type == "application/vnd.google-apps.spreadsheet":
                data = drive_service.files().export_media(fileId=file_id, mimeType="text/csv").execute()
                return data.decode("utf-8", errors="ignore") if isinstance(data, bytes) else str(data)
            if mime_type == "application/pdf":
                data = drive_service.files().get_media(fileId=file_id).execute()
                from pypdf import PdfReader
                pdf = PdfReader(io.BytesIO(data if isinstance(data, bytes) else bytes(data)))
                return "\n".join(page.extract_text() or "" for page in pdf.pages)
            if mime_type and (mime_type.startswith("text/") or mime_type in ("application/json", "application/javascript")):
                data = drive_service.files().get_media(fileId=file_id).execute()
                return data.decode("utf-8", errors="ignore") if isinstance(data, bytes) else str(data)
        except Exception as e:
            logger.warning(f"Could not extract text from Drive file {file_id}: {e}")
        return ""


    def _save_semester_start_date(self, dt: datetime):
        """Persist auto-detected semester start date in settings"""
        try:
            setting_key = f"classroom:{self.user_id}:semester_start_date"
            setting = self.db.query(Setting).filter(Setting.key == setting_key).first()
            if not setting:
                setting = Setting(key=setting_key, value=dt.isoformat(), description="Current semester start boundary")
                self.db.add(setting)
            else:
                setting.value = dt.isoformat()
            self.db.commit()
        except Exception:
            self.db.rollback()

    def _get_configured_since_date(self) -> datetime:
        """Get semester start date from database settings or automatically derive from portal calendar."""
        setting_key = f"classroom:{self.user_id}:semester_start_date"
        setting = self.db.query(Setting).filter(Setting.key == setting_key).first()
        if setting and setting.value:
            try:
                # Value can be ISO format YYYY-MM-DD or full timestamp
                val = setting.value.strip().replace('"', '')
                if len(val) == 10:
                    dt = datetime.fromisoformat(f"{val}T00:00:00+00:00")
                else:
                    dt = datetime.fromisoformat(val.replace("Z", "+00:00"))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt
            except Exception as e:
                logger.warning(f"Could not parse stored semester_start_date: {e}")

        # Fallback 1: Derive from portal class schedules
        try:
            from app.db.models import ClassSchedule
            min_date = self.db.query(func.min(ClassSchedule.date)).scalar()
            if min_date:
                if min_date.tzinfo is None:
                    min_date = min_date.replace(tzinfo=timezone.utc)
                derived = min_date.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
                self._save_semester_start_date(derived)
                return derived
        except Exception:
            pass

        # Fallback 2: Default to standard university semester cycle (Fall: Sep 1, Spring: Feb 1)
        now = datetime.now(timezone.utc)
        year = now.year
        if now.month >= 8:
            derived = datetime(year, 9, 1, 0, 0, 0, tzinfo=timezone.utc)
        else:
            derived = datetime(year, 2, 1, 0, 0, 0, tzinfo=timezone.utc)
        self._save_semester_start_date(derived)
        return derived

    def sync_all(self, since_date: Optional[datetime] = None) -> Dict[str, Any]:
        """Sync all Classroom data from the given since_date / semester start onwards"""
        if not self.service:
            return {"error": "Service not initialized"}

        if since_date is None:
            since_date = self._get_configured_since_date()
        elif since_date.tzinfo is None:
            since_date = since_date.replace(tzinfo=timezone.utc)

        results = {
            "courses": 0,
            "assignments": 0,
            "announcements": 0,
            "submission_states": 0,
            "schedules": 0,
            "since_date": since_date.isoformat() if since_date else None,
            "errors": []
        }
        bootstrap_key = f"classroom:{self.user_id}:auto_solve_bootstrapped"
        bootstrap = self.db.query(Setting).filter(Setting.key == bootstrap_key).first()
        is_initial_sync = not (bootstrap and bootstrap.value == "true")

        try:
            courses = self._get_all_courses()
            for course in courses:
                try:
                    course_id = course["id"]
                    
                    # Create the account-owned course before upserting its coursework.
                    db_course = self._sync_course(course, is_active=True)

                    # 1. Sync coursework, materials, and announcements with since_date filter
                    assignments_count = self._sync_coursework(course_id, since_date=since_date)
                    materials_count = self._sync_coursework_materials(course_id, since_date=since_date)
                    announcements_count = self._sync_announcements(course, since_date=since_date)
                    
                    # Determine if course has active activity in current semester
                    c_update_str = course.get("updateTime") or course.get("creationTime")
                    c_update_dt = datetime.fromisoformat(c_update_str.replace("Z", "+00:00")) if c_update_str else None
                    
                    is_active_semester = True
                    if since_date:
                        is_updated_in_semester = c_update_dt and c_update_dt >= since_date
                        has_semester_items = (assignments_count > 0) or (announcements_count > 0) or (materials_count > 0)
                        if not is_updated_in_semester and not has_semester_items:
                            is_active_semester = False

                    # 2. Sync course with appropriate active/archived state
                    db_course = self._sync_course(course, is_active=is_active_semester)
                    
                    if is_active_semester:
                        results["courses"] += 1
                        results["assignments"] += assignments_count
                        results["announcements"] += announcements_count
                        results["course_materials"] = results.get("course_materials", 0) + materials_count
                        results["submission_states"] += self._sync_student_submission_states(course_id)
                        results["schedules"] += self._sync_schedule(course)
                        # Check course-scoped auto turn-in (strictly for this course if enabled)
                        try:
                            from app.classroom.router import check_and_execute_course_auto_turn_in
                            check_and_execute_course_auto_turn_in(self.db, db_course.id, self.user_id)
                        except Exception as auto_turnin_err:
                            logger.debug(f"Course auto turn-in check error for {course_id}: {auto_turnin_err}")
                    else:
                        # Clean up any old assignments attached to this archived course
                        if since_date:
                            self.db.query(Assignment).filter(
                                Assignment.course_id == db_course.id,
                                (Assignment.due_at < since_date) | (Assignment.due_at.is_(None) & (Assignment.created_at < since_date))
                            ).delete(synchronize_session=False)
                            self.db.commit()

                except Exception as e:
                    results["errors"].append(f"Course {course.get('id')}: {e}")

            # Also ensure all database courses older than since_date with no active items are marked ARCHIVED
            if since_date:
                self._cleanup_outdated_db_records(since_date)

            self._enqueue_new_assignments(is_initial_sync)
            if not results["errors"]:
                if bootstrap is None:
                    bootstrap = Setting(
                        key=bootstrap_key,
                        value="true",
                        description="Initial Google Classroom import completed; older work is not auto-queued.",
                    )
                    self.db.add(bootstrap)
                else:
                    bootstrap.value = "true"
                self.db.commit()

            logger.info(f"Classroom sync complete (since {since_date}): {results}")
        except Exception as e:
            logger.error(f"Sync failed: {e}")
            results["errors"].append(str(e))

        return results

    def _enqueue_new_assignments(self, is_initial_sync: bool) -> None:
        enabled_key = f"classroom:{self.user_id}:auto_solve_enabled"
        enabled = self.db.query(Setting).filter(Setting.key == enabled_key).first()
        if is_initial_sync or not enabled or enabled.value != "true":
            return

        now = datetime.now(timezone.utc)
        oldest_eligible_creation = now - timedelta(days=7)
        for assignment_id, created_at in self._new_assignments.items():
            if not created_at or created_at < oldest_eligible_creation:
                continue
            assignment = self.db.query(Assignment).filter(
                Assignment.id == assignment_id,
                Assignment.user_id == self.user_id,
            ).first()
            if (
                not assignment
                or getattr(assignment.state, "value", assignment.state) != "PUBLISHED"
                or assignment.is_quiz
                or (assignment.work_type or "").upper() != "ASSIGNMENT"
                or (assignment.due_at and assignment.due_at < now)
            ):
                continue

            submission_state = getattr(assignment.submission_state, "value", assignment.submission_state)
            if assignment.course.external_id in self._submission_sync_failed:
                continue
            if submission_state not in {"NEW", "CREATED"}:
                continue
            if self.db.query(AssignmentSolution.id).filter(
                AssignmentSolution.assignment_id == assignment.id,
            ).first():
                continue

            job = BrowserAutomationJob(
                user_id=self.user_id,
                assignment_id=assignment.id,
                status="pending",
                queued_at=now,
            )
            try:
                with self.db.begin_nested():
                    self.db.add(job)
                    self.db.flush()
            except IntegrityError:
                continue

        self.db.commit()

    def _cleanup_outdated_db_records(self, since_date: datetime):
        """Mark old semester courses as ARCHIVED and remove obsolete past-semester assignments"""
        try:
            from app.db.models import AssignmentMaterial, AssignmentSolution, Submission
            
            # Find old assignments
            old_assignments = self.db.query(Assignment).filter(
                Assignment.user_id == self.user_id,
                (Assignment.due_at < since_date) |
                (Assignment.due_at.is_(None) & (Assignment.created_at < since_date))
            ).all()
            
            old_ids = [a.id for a in old_assignments]
            if old_ids:
                # Delete dependent records first to satisfy FK constraints
                self.db.query(AssignmentMaterial).filter(AssignmentMaterial.assignment_id.in_(old_ids)).delete(synchronize_session=False)
                self.db.query(AssignmentSolution).filter(AssignmentSolution.assignment_id.in_(old_ids)).delete(synchronize_session=False)
                self.db.query(Submission).filter(Submission.assignment_id.in_(old_ids)).delete(synchronize_session=False)
                self.db.query(BrowserAutomationJob).filter(
                    BrowserAutomationJob.user_id == self.user_id,
                    BrowserAutomationJob.assignment_id.in_(old_ids),
                ).delete(synchronize_session=False)
                
                # Now delete assignments
                self.db.query(Assignment).filter(
                    Assignment.user_id == self.user_id,
                    Assignment.id.in_(old_ids),
                ).delete(synchronize_session=False)

            # Check courses: if course has no active assignments and was created before since_date, mark ARCHIVED
            all_courses = self.db.query(Course).filter(Course.user_id == self.user_id).all()
            for c in all_courses:
                has_active_assignments = self.db.query(Assignment).filter(Assignment.course_id == c.id).count() > 0
                is_recent = c.updated_at and c.updated_at >= since_date
                if not has_active_assignments and not is_recent and c.created_at and c.created_at < since_date:
                    c.course_state = "ARCHIVED"

            self.db.commit()
        except Exception as err:
            logger.warning(f"Error during outdated records cleanup: {err}")
            self.db.rollback()

    def _get_all_courses(self) -> List[Dict]:
        """Fetch active enrolled courses from Classroom API with rate limiting"""
        courses = []
        page_token = None
        last_error = None

        # 1. Primary: Fetch only active courses where current user is enrolled student
        while True:
            try:
                def fetch_student_courses():
                    return self.service.courses().list(
                        pageToken=page_token,
                        pageSize=100,
                        courseStates=["ACTIVE"],
                        studentId="me"
                    ).execute()
                
                response = self._execute_with_rate_limit(fetch_student_courses)

                courses.extend(response.get("courses", []))
                page_token = response.get("nextPageToken")

                if not page_token:
                    break

            except HttpError as e:
                last_error = e
                logger.warning(f"Fetching student courses with studentId=me returned error: {e}")
                break

        # 2. Fallback: If no student courses returned, fetch all active courses
        if not courses:
            page_token = None
            while True:
                try:
                    def fetch_all_courses():
                        return self.service.courses().list(
                            pageToken=page_token,
                            pageSize=100,
                            courseStates=["ACTIVE"]
                        ).execute()
                    
                    response = self._execute_with_rate_limit(fetch_all_courses)

                    courses.extend(response.get("courses", []))
                    page_token = response.get("nextPageToken")

                    if not page_token:
                        break

                except HttpError as e:
                    last_error = e
                    logger.error(f"Error fetching courses: {e}")
                    break

        if not courses and last_error:
            status = getattr(last_error.resp, "status", "unknown")
            raise RuntimeError(
                f"Google Classroom course listing failed (HTTP {status}): {last_error.reason}"
            ) from last_error

        return courses

    def _sync_course(self, course_data: Dict, is_active: bool = True) -> Course:
        """Sync a single course to database"""
        repo = CourseRepository(self.db)

        existing = repo.get_by_external_id(course_data["id"], self.user_id)
        state = "ACTIVE" if is_active and course_data.get("courseState") == "ACTIVE" else "ARCHIVED"
        teacher_name = (existing.teacher_name if existing and existing.teacher_name else self._get_teacher_name(course_data["id"]))
        course_dict = {
            "user_id": self.user_id,
            "external_id": course_data["id"],
            "name": course_data.get("name", ""),
            "section": course_data.get("section", ""),
            "description": course_data.get("description", ""),
            "room": course_data.get("room", ""),
            "teacher_name": teacher_name,
            "course_state": state,
            "alternate_link": course_data.get("alternateLink", ""),
        }

        if existing:
            for key, value in course_dict.items():
                setattr(existing, key, value)
            self.db.commit()
            return existing
        else:
            return repo.create(course_dict)

    def _get_teacher_name(self, course_id: str) -> str:
        """Get teacher name for a course"""
        try:
            def fetch_teachers():
                return self.service.courses().teachers().list(courseId=course_id).execute()
            
            teachers = self._execute_with_rate_limit(fetch_teachers)
            if teachers.get("teachers"):
                teacher = teachers["teachers"][0]
                profile = teacher.get("profile", {})
                return f"{profile.get('name', {}).get('givenName', '')} {profile.get('name', {}).get('familyName', '')}".strip()
        except HttpError:
            pass
        return ""

    def _sync_coursework(self, course_id: str, since_date: Optional[datetime] = None) -> int:
        """Sync coursework (assignments) for a course, skipping items older than since_date"""
        course = self.db.query(Course).filter(
            Course.external_id == course_id,
            Course.user_id == self.user_id,
        ).first()
        if not course:
            return 0

        count = 0
        page_token = None

        while True:
            try:
                def fetch_coursework():
                    return self.service.courses().courseWork().list(
                        courseId=course_id,
                        pageToken=page_token,
                        pageSize=100,
                        orderBy="updateTime desc"
                    ).execute()
                
                response = self._execute_with_rate_limit(fetch_coursework)

                for work in response.get("courseWork", []):
                    # Strict semester date filter
                    if since_date:
                        creation_str = work.get("creationTime")
                        created_dt = datetime.fromisoformat(creation_str.replace("Z", "+00:00")) if creation_str else None

                        # Parse due date
                        due_at = None
                        if work.get("dueDate"):
                            due = work["dueDate"]
                            time = work.get("dueTime", {"hours": 23, "minutes": 59})
                            due_at = datetime(
                                due["year"], due["month"], due["day"],
                                time.get("hours", 23), time.get("minutes", 59),
                                tzinfo=timezone.utc
                            )

                        # Rule 1: If due date is before semester start, it belongs to an old semester. Skip!
                        if due_at and due_at < since_date:
                            continue

                        # Rule 2: If no due date, only accept if created during the current semester.
                        if not due_at and not (created_dt and created_dt >= since_date):
                            continue

                    self._sync_assignment(course.id, work)
                    count += 1

                page_token = response.get("nextPageToken")
                if not page_token:
                    break

            except HttpError as e:
                logger.error(f"Error fetching coursework for {course_id}: {e}")
                status = getattr(e.resp, "status", "unknown")
                raise RuntimeError(
                    f"Google Classroom coursework request failed for course {course_id} "
                    f"(HTTP {status}): {e.reason}"
                ) from e

        return count

    def _sync_assignment(self, course_db_id: int, work: Dict) -> Assignment:
        """Sync a single assignment"""
        repo = AssignmentRepository(self.db)

        external_id = work["id"]
        existing = repo.get_by_external_id(external_id, self.user_id)

        # Parse due date
        due_at = None
        if work.get("dueDate"):
            due = work["dueDate"]
            time = work.get("dueTime", {"hours": 23, "minutes": 59})
            due_at = datetime(
                due["year"], due["month"], due["day"],
                time.get("hours", 23), time.get("minutes", 59),
                tzinfo=timezone.utc
            )

        assignment_dict = {
            "user_id": self.user_id,
            "external_id": external_id,
            "course_id": course_db_id,
            "title": work.get("title", ""),
            "work_type": work.get("workType", "ASSIGNMENT"),
            "is_quiz": bool(work.get("quizSettings", {}).get("isQuiz")),
            "description": work.get("description", ""),
            "due_at": due_at,
            "due_date": due_at,
            "url": work.get("alternateLink", ""),
            "state": work.get("state", "PUBLISHED"),
            "status": "draft",
        }

        if existing:
            for key, value in assignment_dict.items():
                setattr(existing, key, value)
            existing.updated_at = datetime.now(timezone.utc)
            self.db.commit()
            self._sync_materials(existing.id, work.get("materials", []), default_title=work.get("title", ""))
            if not work.get("materials") and work.get("description"):
                from app.db.repositories import AssignmentMaterialRepository
                mat_repo = AssignmentMaterialRepository(self.db)
                if not mat_repo.get_by_assignment(existing.id):
                    mat_repo.create({
                        "user_id": self.user_id,
                        "assignment_id": existing.id,
                        "material_type": "assignment_description",
                        "title": f"{existing.title} (Instructions)",
                        "url": existing.url or "",
                        "drive_file_id": None,
                        "mime_type": "text/plain",
                        "content": work.get("description", "")[:30000],
                    })
            return existing
        else:
            created_value = work.get("creationTime")
            created_at = (
                datetime.fromisoformat(created_value.replace("Z", "+00:00"))
                if created_value else None
            )
            assignment = repo.create(assignment_dict)
            self._new_assignments[assignment.id] = created_at
            self._sync_materials(assignment.id, work.get("materials", []), default_title=work.get("title", ""))
            if not work.get("materials") and work.get("description"):
                from app.db.repositories import AssignmentMaterialRepository
                mat_repo = AssignmentMaterialRepository(self.db)
                mat_repo.create({
                    "user_id": self.user_id,
                    "assignment_id": assignment.id,
                    "material_type": "assignment_description",
                    "title": f"{assignment.title} (Instructions)",
                    "url": assignment.url or "",
                    "drive_file_id": None,
                    "mime_type": "text/plain",
                    "content": work.get("description", "")[:30000],
                })
            try:
                from app.services.alert_service import AlertService
                AlertService(self.db).notify_new_assignment(assignment)
            except Exception as e:
                logger.warning(f"Could not dispatch new assignment notification for {assignment.id}: {e}")
            return assignment

    def _sync_coursework_materials(self, course_id: str, since_date: Optional[datetime] = None) -> int:
        """Sync course documents, slides, handouts, and reading materials from Classroom courseWorkMaterials."""
        course = self.db.query(Course).filter(
            Course.external_id == course_id,
            Course.user_id == self.user_id,
        ).first()
        if not course:
            return 0

        count = 0
        page_token = None

        while True:
            try:
                def fetch_coursework_materials():
                    try:
                        return self.service.courses().courseWorkMaterials().list(
                            courseId=course_id,
                            pageToken=page_token,
                            pageSize=100,
                            courseWorkMaterialStates=["PUBLISHED"],
                        ).execute()
                    except Exception:
                        return self.service.courses().courseWorkMaterials().list(
                            courseId=course_id,
                            pageToken=page_token,
                            pageSize=100,
                        ).execute()

                response = self._execute_with_rate_limit(fetch_coursework_materials)
                items = response.get("courseWorkMaterial", []) or response.get("courseWorkMaterials", [])

                for mat_item in items:
                    self._sync_single_coursework_material(course.id, mat_item)
                    count += 1

                page_token = response.get("nextPageToken")
                if not page_token:
                    break

            except HttpError as e:
                status = getattr(e.resp, "status", None)
                if status in (403, 404):
                    logger.info(f"courseWorkMaterials not accessible for course {course_id} (HTTP {status}): {e.reason}")
                else:
                    logger.warning(f"Error fetching courseWorkMaterials for {course_id}: {e}")
                break
            except Exception as e:
                logger.warning(f"Unexpected error in _sync_coursework_materials for {course_id}: {e}")
                break

        return count

    def _sync_single_coursework_material(self, course_db_id: int, mat_item: Dict) -> Assignment:
        """Sync a single courseWorkMaterial record and its attached files."""
        repo = AssignmentRepository(self.db)
        external_id = f"cwm_{mat_item['id']}"
        existing = repo.get_by_external_id(external_id, self.user_id)

        title = mat_item.get("title") or "Course Material"
        desc = mat_item.get("description", "")
        material_dict = {
            "user_id": self.user_id,
            "external_id": external_id,
            "course_id": course_db_id,
            "title": title,
            "work_type": "MATERIAL",
            "is_quiz": False,
            "description": desc,
            "url": mat_item.get("alternateLink", ""),
            "state": mat_item.get("state", "PUBLISHED"),
            "status": AssignmentStatus.SUBMITTED,
        }

        materials_list = mat_item.get("materials", [])
        if existing:
            for key, value in material_dict.items():
                setattr(existing, key, value)
            existing.updated_at = datetime.now(timezone.utc)
            self.db.commit()
            self._sync_materials(existing.id, materials_list, default_title=title)
            if desc:
                from app.db.repositories import AssignmentMaterialRepository
                mat_repo = AssignmentMaterialRepository(self.db)
                mats = mat_repo.get_by_assignment(existing.id)
                if not mats or not any(m.material_type == "course_material" for m in mats):
                    mat_repo.create({
                        "user_id": self.user_id,
                        "assignment_id": existing.id,
                        "material_type": "course_material",
                        "title": f"{title} (Overview)",
                        "url": mat_item.get("alternateLink", ""),
                        "drive_file_id": None,
                        "mime_type": "text/plain",
                        "content": desc,
                    })
            return existing
        else:
            material_assignment = repo.create(material_dict)
            self._sync_materials(material_assignment.id, materials_list, default_title=title)
            if desc:
                from app.db.repositories import AssignmentMaterialRepository
                mat_repo = AssignmentMaterialRepository(self.db)
                mat_repo.create({
                    "user_id": self.user_id,
                    "assignment_id": material_assignment.id,
                    "material_type": "course_material",
                    "title": f"{title} (Overview)",
                    "url": mat_item.get("alternateLink", ""),
                    "drive_file_id": None,
                    "mime_type": "text/plain",
                    "content": desc,
                })
            return material_assignment

    def _sync_student_submission_states(self, course_id: str) -> int:
        """Update this account's own turned-in/returned state for every course item."""
        course = self.db.query(Course).filter(
            Course.external_id == course_id,
            Course.user_id == self.user_id,
        ).first()
        if not course:
            return 0

        count = 0
        page_token = None
        try:
            while True:
                def fetch_submissions():
                    return self.service.courses().courseWork().studentSubmissions().list(
                        courseId=course_id,
                        courseWorkId="-",
                        userId="me",
                        pageSize=100,
                        pageToken=page_token,
                    ).execute()
                
                response = self._execute_with_rate_limit(fetch_submissions)
                
                for submission in response.get("studentSubmissions", []):
                    assignment = self.db.query(Assignment).filter(
                        Assignment.course_id == course.id,
                        Assignment.external_id == submission.get("courseWorkId"),
                        Assignment.user_id == self.user_id,
                    ).first()
                    state = submission.get("state")
                    if assignment and state and state in SubmissionState.__members__:
                        assignment.submission_state = SubmissionState[state]
                        count += 1
                page_token = response.get("nextPageToken")
                if not page_token:
                    self.db.commit()
                    return count
        except HttpError as error:
            self._submission_sync_failed.add(course_id)
            logger.warning(f"Could not sync own submission states for course {course_id}: {error}")
            self.db.rollback()
            return 0

    def _sync_announcements(self, course_data: Dict, since_date: Optional[datetime] = None) -> int:
        """Sync published Classroom announcements for one course from since_date onwards."""
        repo = AnnouncementRepository(self.db)
        count = 0
        page_token = None
        course_id = course_data["id"]
        local_course = self.db.query(Course).filter(
            Course.external_id == course_id,
            Course.user_id == self.user_id,
        ).first()
        if not local_course:
            return 0
        while True:
            try:
                def fetch_announcements():
                    return self.service.courses().announcements().list(
                        courseId=course_id,
                        pageSize=100,
                        pageToken=page_token,
                        orderBy="updateTime desc",
                    ).execute()
                
                response = self._execute_with_rate_limit(fetch_announcements)
                for post in response.get("announcements", []):
                    published = post.get("creationTime")
                    published_at = datetime.fromisoformat(published.replace("Z", "+00:00")) if published else None
                    updated = post.get("updateTime") or published or ""
                    updated_at = datetime.fromisoformat(updated.replace("Z", "+00:00")) if updated else published_at

                    # Filter out announcements created/updated before semester start
                    if since_date:
                        check_dt = published_at or updated_at
                        if check_dt and check_dt < since_date:
                            continue

                    text = post.get("text", "")
                    external_id = f"classroom:{course_id}:{post['id']}"
                    fingerprint = hashlib.sha256(f"{external_id}:{updated}:{text}".encode("utf-8")).hexdigest()
                    body = text
                    if post.get("alternateLink"):
                        body = f"{text}\n\nOpen in Google Classroom: {post['alternateLink']}"
                    repo.create_or_update({
                        "external_id": external_id,
                        "course_id": local_course.id,
                        "title": (text.strip().splitlines() or ["Google Classroom announcement"])[0][:500],
                        "content": body,
                        "url": post.get("alternateLink"),
                        "source": "Google Classroom",
                        "fingerprint": fingerprint,
                        "published_at": published_at,
                    })

                    # If announcement has attached files/materials or text, index them for study assistant
                    ann_title = (text.strip().splitlines() or ["Announcement"])[0][:500]
                    if post.get("materials"):
                        try:
                            ann_ext_id = f"ann_mat_{post['id']}"
                            repo_assign = AssignmentRepository(self.db)
                            ann_assign = repo_assign.get_by_external_id(ann_ext_id, self.user_id)
                            if not ann_assign:
                                ann_assign = repo_assign.create({
                                    "user_id": self.user_id,
                                    "external_id": ann_ext_id,
                                    "course_id": local_course.id,
                                    "title": ann_title,
                                    "work_type": "ANNOUNCEMENT",
                                    "is_quiz": False,
                                    "description": text,
                                    "url": post.get("alternateLink", ""),
                                    "state": "PUBLISHED",
                                    "status": AssignmentStatus.SUBMITTED,
                                })
                            self._sync_materials(ann_assign.id, post.get("materials", []), default_title=ann_title)
                        except Exception as ann_mat_err:
                            logger.warning(f"Could not sync announcement materials for {post.get('id')}: {ann_mat_err}")
                    elif text and len(text.strip()) > 10:
                        try:
                            ann_ext_id = f"ann_{post['id']}"
                            repo_assign = AssignmentRepository(self.db)
                            ann_assign = repo_assign.get_by_external_id(ann_ext_id, self.user_id)
                            if not ann_assign:
                                ann_assign = repo_assign.create({
                                    "user_id": self.user_id,
                                    "external_id": ann_ext_id,
                                    "course_id": local_course.id,
                                    "title": ann_title,
                                    "work_type": "ANNOUNCEMENT",
                                    "is_quiz": False,
                                    "description": text,
                                    "url": post.get("alternateLink", ""),
                                    "state": "PUBLISHED",
                                    "status": AssignmentStatus.SUBMITTED,
                                })
                                from app.db.repositories import AssignmentMaterialRepository
                                mat_repo = AssignmentMaterialRepository(self.db)
                                mat_repo.create({
                                    "user_id": self.user_id,
                                    "assignment_id": ann_assign.id,
                                    "material_type": "announcement",
                                    "title": ann_title,
                                    "url": post.get("alternateLink", ""),
                                    "drive_file_id": None,
                                    "mime_type": "text/plain",
                                    "content": text[:30000],
                                })
                        except Exception as ann_err:
                            logger.debug(f"Could not index announcement text for {post.get('id')}: {ann_err}")

                    count += 1
                page_token = response.get("nextPageToken")
                if not page_token:
                    return count
            except HttpError as error:
                logger.warning(f"Could not sync announcements for course {course_id}: {error}")
                return count

    def _sync_materials(self, assignment_db_id: int, materials: List[Dict], default_title: str = ""):
        """Sync assignment materials, extracting Drive file text when possible."""
        from app.db.repositories import AssignmentMaterialRepository

        repo = AssignmentMaterialRepository(self.db)

        # Clear existing
        existing = repo.get_by_assignment(assignment_db_id)
        for m in existing:
            self.db.delete(m)

        drive_service = self._get_drive_service()

        for mat in materials:
            drive_file = mat.get("driveFile", {}).get("driveFile", {}) if mat.get("driveFile") else {}
            if mat.get("driveFile") and not drive_file:
                drive_file = mat.get("driveFile") if isinstance(mat.get("driveFile"), dict) else {}

            drive_file_id = drive_file.get("id")
            mime_type = drive_file.get("mimeType")
            content = ""

            # Extract full text from Drive so the study assistant can answer
            # from the document even when Drive isn't connected at chat time.
            if drive_service and drive_file_id and mime_type and (
                mime_type == "application/vnd.google-apps.document"
                or mime_type == "application/vnd.google-apps.presentation"
                or mime_type == "application/vnd.google-apps.spreadsheet"
                or mime_type == "application/pdf"
                or mime_type.startswith("text/")
            ):
                content = self._extract_drive_file_text(drive_service, drive_file_id, mime_type)

            title = (
                drive_file.get("title")
                or (mat.get("youtubeVideo", {}).get("title"))
                or (mat.get("link", {}).get("title"))
                or (mat.get("form", {}).get("title"))
                or default_title
                or "Course Document"
            )
            url = (
                drive_file.get("alternateLink")
                or (mat.get("youtubeVideo", {}).get("alternateLink"))
                or (mat.get("link", {}).get("url"))
                or (mat.get("form", {}).get("formUrl"))
                or ""
            )

            mat_dict = {
                "user_id": self.user_id,
                "assignment_id": assignment_db_id,
                "material_type": (
                    "drive_file" if mat.get("driveFile")
                    else "youtube_video" if mat.get("youtubeVideo")
                    else "link" if mat.get("link")
                    else "form" if mat.get("form")
                    else "other"
                ),
                "title": title,
                "url": url,
                "drive_file_id": drive_file_id,
                "mime_type": mime_type,
                "content": content[:30000] if content else None,
            }
            repo.create(mat_dict)

        self.db.commit()

    def _sync_schedule(self, course_data: Dict) -> int:
        """Sync schedule/timetable from Classroom coursework due dates and course metadata.
        
        Since Classroom API doesn't have a direct timetable endpoint, we derive schedule from:
        1. Coursework due dates/times
        2. Course section/meeting info if available
        3. Calendar events (if Calendar API scope granted)
        """
        course_id = course_data["id"]
        course = self.db.query(Course).filter(
            Course.external_id == course_id,
            Course.user_id == self.user_id,
        ).first()
        if not course:
            return 0

        count = 0
        
        try:
            # Get all coursework for this course to derive schedule from due dates
            def fetch_all_coursework():
                return self.service.courses().courseWork().list(
                    courseId=course_id,
                    pageSize=500,
                    orderBy="updateTime desc"
                ).execute()
            
            response = self._execute_with_rate_limit(fetch_all_coursework)
            coursework = response.get("courseWork", [])
            
            for work in coursework:
                due_at = None
                if work.get("dueDate"):
                    due = work["dueDate"]
                    time = work.get("dueTime", {"hours": 23, "minutes": 59})
                    due_at = datetime(
                        due["year"], due["month"], due["day"],
                        time.get("hours", 23), time.get("minutes", 59),
                        tzinfo=timezone.utc
                    )
                
                if not due_at:
                    continue
                
                # Create schedule entry for the due date
                # Check if already exists
                existing = self.db.query(ClassSchedule).filter(
                    ClassSchedule.course_id == course.id,
                    ClassSchedule.user_id == self.user_id,
                    ClassSchedule.date == due_at.date(),
                    ClassSchedule.start_time == due_at.replace(hour=due_at.hour, minute=due_at.minute, second=0, microsecond=0),
                    ClassSchedule.subject == work.get("title", "Assignment Due")
                ).first()
                
                if not existing:
                    schedule = ClassSchedule(
                        user_id=self.user_id,
                        external_id=f"classroom:{course_id}:{work['id']}",
                        course_id=course.id,
                        subject=work.get("title", "Assignment Due"),
                        date=due_at,
                        start_time=due_at.replace(hour=due_at.hour, minute=due_at.minute, second=0, microsecond=0),
                        end_time=due_at.replace(hour=due_at.hour, minute=due_at.minute, second=0, microsecond=0) + timedelta(hours=1),
                        teacher=course.teacher_name,
                        room=course.room or "Online",
                        status="scheduled"
                    )
                    self.db.add(schedule)
                    count += 1
            
            self.db.commit()
            
        except HttpError as e:
            logger.warning(f"Could not sync schedule for course {course_id}: {e}")
            self.db.rollback()
        except Exception as e:
            logger.error(f"Unexpected error syncing schedule for course {course_id}: {e}")
            self.db.rollback()
        
        return count

    def get_student_submissions(self, course_id: str, assignment_id: str) -> List[Dict]:
        """Get student submissions for an assignment with rate limiting"""
        try:
            def fetch_submissions():
                return self.service.courses().courseWork().studentSubmissions().list(
                    courseId=course_id,
                    courseWorkId=assignment_id,
                    pageSize=100
                ).execute()
            
            submissions = self._execute_with_rate_limit(fetch_submissions)
            return submissions.get("studentSubmissions", [])
        except HttpError as e:
            logger.error(f"Error fetching submissions: {e}")
            return []

    def get_course_students(self, course_id: str) -> List[Dict]:
        """Get students enrolled in a course with rate limiting"""
        students = []
        page_token = None
        while True:
            try:
                def fetch_students():
                    return self.service.courses().students().list(
                        courseId=course_id, pageSize=200, pageToken=page_token
                    ).execute()
                
                response = self._execute_with_rate_limit(fetch_students)
                students.extend(response.get("students", []))
                page_token = response.get("nextPageToken")
                if not page_token:
                    return students
            except HttpError as e:
                logger.error(f"Error fetching students: {e}")
                return students


def get_classroom_service(db: Session = None, user_id: str = "legacy") -> Optional[ClassroomSyncService]:
    """Factory function to get ClassroomSyncService"""
    if db is None:
        db = next(get_db())
    service = ClassroomSyncService(db, user_id=user_id)
    return service if service.service else None
