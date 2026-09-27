import json
import hashlib
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from sqlalchemy.orm import Session
from app.db.database import get_db
from app.db.repositories import CourseRepository, AssignmentRepository, ClassScheduleRepository, AnnouncementRepository
from app.db.models import Course, Assignment, ClassSchedule, GoogleCredential, SubmissionState, Setting
from app.core.logging import logger


class ClassroomSyncService:
    def __init__(self, db: Session):
        self.db = db
        self.service = None
        self._load_credentials()

    def _load_credentials(self) -> bool:
        """Load Google credentials from database"""
        cred_row = self.db.query(GoogleCredential).first()
        if not cred_row:
            logger.warning("No Google credentials found in database")
            return False

        try:
            creds = Credentials(
                token=cred_row.access_token,
                refresh_token=cred_row.refresh_token,
                token_uri=cred_row.token_uri,
                client_id=cred_row.client_id,
                client_secret=cred_row.client_secret,
                scopes=json.loads(cred_row.scopes) if cred_row.scopes else [],
            )

            if creds.expired and creds.refresh_token:
                from google.auth.transport.requests import Request
                creds.refresh(Request())
                # Update stored token
                cred_row.access_token = creds.token
                cred_row.expiry = creds.expiry
                self.db.commit()

            self.service = build("classroom", "v1", credentials=creds)
            logger.info("Google Classroom service initialized")
            return True

        except Exception as e:
            logger.error(f"Failed to initialize Classroom service: {e}")
            return False

    def _get_configured_since_date(self) -> Optional[datetime]:
        """Get semester start date from database settings if configured"""
        setting = self.db.query(Setting).filter(Setting.key == "semester_start_date").first()
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
        return None

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

        try:
            courses = self._get_all_courses()
            for course in courses:
                try:
                    course_id = course["id"]
                    
                    # 1. Sync coursework and announcements with since_date filter
                    assignments_count = self._sync_coursework(course_id, since_date=since_date)
                    announcements_count = self._sync_announcements(course, since_date=since_date)
                    
                    # Determine if course has active activity in current semester
                    c_update_str = course.get("updateTime") or course.get("creationTime")
                    c_update_dt = datetime.fromisoformat(c_update_str.replace("Z", "+00:00")) if c_update_str else None
                    
                    is_active_semester = True
                    if since_date:
                        is_updated_in_semester = c_update_dt and c_update_dt >= since_date
                        has_semester_items = (assignments_count > 0) or (announcements_count > 0)
                        if not is_updated_in_semester and not has_semester_items:
                            is_active_semester = False

                    # 2. Sync course with appropriate active/archived state
                    db_course = self._sync_course(course, is_active=is_active_semester)
                    
                    if is_active_semester:
                        results["courses"] += 1
                        results["assignments"] += assignments_count
                        results["announcements"] += announcements_count
                        results["submission_states"] += self._sync_student_submission_states(course_id)
                        results["schedules"] += self._sync_schedule(course)
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

            logger.info(f"Classroom sync complete (since {since_date}): {results}")
        except Exception as e:
            logger.error(f"Sync failed: {e}")
            results["errors"].append(str(e))

        return results

    def _cleanup_outdated_db_records(self, since_date: datetime):
        """Mark old semester courses as ARCHIVED and remove obsolete past-semester assignments"""
        try:
            from app.db.models import AssignmentMaterial, AssignmentSolution, Submission
            
            # Find old assignments
            old_assignments = self.db.query(Assignment).filter(
                (Assignment.due_at < since_date) |
                (Assignment.due_at.is_(None) & (Assignment.created_at < since_date))
            ).all()
            
            old_ids = [a.id for a in old_assignments]
            if old_ids:
                # Delete dependent records first to satisfy FK constraints
                self.db.query(AssignmentMaterial).filter(AssignmentMaterial.assignment_id.in_(old_ids)).delete(synchronize_session=False)
                self.db.query(AssignmentSolution).filter(AssignmentSolution.assignment_id.in_(old_ids)).delete(synchronize_session=False)
                self.db.query(Submission).filter(Submission.assignment_id.in_(old_ids)).delete(synchronize_session=False)
                
                # Now delete assignments
                self.db.query(Assignment).filter(Assignment.id.in_(old_ids)).delete(synchronize_session=False)

            # Check courses: if course has no active assignments and was created before since_date, mark ARCHIVED
            all_courses = self.db.query(Course).all()
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
        """Fetch active enrolled courses from Classroom API"""
        courses = []
        page_token = None

        # 1. Primary: Fetch only active courses where current user is enrolled student
        while True:
            try:
                response = self.service.courses().list(
                    pageToken=page_token,
                    pageSize=100,
                    courseStates=["ACTIVE"],
                    studentId="me"
                ).execute()

                courses.extend(response.get("courses", []))
                page_token = response.get("nextPageToken")

                if not page_token:
                    break

            except HttpError as e:
                logger.warning(f"Fetching student courses with studentId=me returned error: {e}")
                break

        # 2. Fallback: If no student courses returned, fetch all active courses
        if not courses:
            page_token = None
            while True:
                try:
                    response = self.service.courses().list(
                        pageToken=page_token,
                        pageSize=100,
                        courseStates=["ACTIVE"]
                    ).execute()

                    courses.extend(response.get("courses", []))
                    page_token = response.get("nextPageToken")

                    if not page_token:
                        break

                except HttpError as e:
                    logger.error(f"Error fetching courses: {e}")
                    break

        return courses

    def _sync_course(self, course_data: Dict, is_active: bool = True) -> Course:
        """Sync a single course to database"""
        repo = CourseRepository(self.db)

        existing = repo.get_by_external_id(course_data["id"])
        state = "ACTIVE" if is_active and course_data.get("courseState") == "ACTIVE" else "ARCHIVED"
        course_dict = {
            "external_id": course_data["id"],
            "name": course_data.get("name", ""),
            "section": course_data.get("section", ""),
            "description": course_data.get("description", ""),
            "room": course_data.get("room", ""),
            "teacher_name": self._get_teacher_name(course_data["id"]),
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
            teachers = self.service.courses().teachers().list(courseId=course_id).execute()
            if teachers.get("teachers"):
                teacher = teachers["teachers"][0]
                profile = teacher.get("profile", {})
                return f"{profile.get('name', {}).get('givenName', '')} {profile.get('name', {}).get('familyName', '')}".strip()
        except HttpError:
            pass
        return ""

    def _sync_coursework(self, course_id: str, since_date: Optional[datetime] = None) -> int:
        """Sync coursework (assignments) for a course, skipping items older than since_date"""
        course = self.db.query(Course).filter(Course.external_id == course_id).first()
        if not course:
            return 0

        count = 0
        page_token = None

        while True:
            try:
                response = self.service.courses().courseWork().list(
                    courseId=course_id,
                    pageToken=page_token,
                    pageSize=100,
                    orderBy="updateTime desc"
                ).execute()

                for work in response.get("courseWork", []):
                    # Check date filter
                    if since_date:
                        # Extract timestamps
                        creation_str = work.get("creationTime")
                        update_str = work.get("updateTime")
                        created_dt = datetime.fromisoformat(creation_str.replace("Z", "+00:00")) if creation_str else None
                        updated_dt = datetime.fromisoformat(update_str.replace("Z", "+00:00")) if update_str else None

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

                        # If the assignment is past due before the semester start, and created before semester start, skip it
                        is_current_or_future_due = due_at and due_at >= since_date
                        is_created_recently = created_dt and created_dt >= since_date
                        is_updated_recently = updated_dt and updated_dt >= since_date

                        if not (is_current_or_future_due or is_created_recently or is_updated_recently):
                            continue

                    self._sync_assignment(course.id, work)
                    count += 1

                page_token = response.get("nextPageToken")
                if not page_token:
                    break

            except HttpError as e:
                logger.error(f"Error fetching coursework for {course_id}: {e}")
                break

        return count

    def _sync_assignment(self, course_db_id: int, work: Dict) -> Assignment:
        """Sync a single assignment"""
        repo = AssignmentRepository(self.db)

        external_id = work["id"]
        existing = repo.get_by_external_id(external_id)

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
            self._sync_materials(existing.id, work.get("materials", []))
            return existing
        else:
            assignment = repo.create(assignment_dict)
            self._sync_materials(assignment.id, work.get("materials", []))
        return assignment

    def _sync_student_submission_states(self, course_id: str) -> int:
        """Update this account's own turned-in/returned state for every course item."""
        course = self.db.query(Course).filter(Course.external_id == course_id).first()
        if not course:
            return 0

        count = 0
        page_token = None
        try:
            while True:
                response = self.service.courses().courseWork().studentSubmissions().list(
                    courseId=course_id,
                    courseWorkId="-",
                    userId="me",
                    pageSize=100,
                    pageToken=page_token,
                ).execute()
                for submission in response.get("studentSubmissions", []):
                    assignment = self.db.query(Assignment).filter(
                        Assignment.course_id == course.id,
                        Assignment.external_id == submission.get("courseWorkId"),
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
            logger.warning(f"Could not sync own submission states for course {course_id}: {error}")
            self.db.rollback()
            return 0

    def _sync_announcements(self, course_data: Dict, since_date: Optional[datetime] = None) -> int:
        """Sync published Classroom announcements for one course from since_date onwards."""
        repo = AnnouncementRepository(self.db)
        count = 0
        page_token = None
        course_id = course_data["id"]
        local_course = self.db.query(Course).filter(Course.external_id == course_id).first()
        if not local_course:
            return 0
        while True:
            try:
                response = self.service.courses().announcements().list(
                    courseId=course_id,
                    pageSize=100,
                    pageToken=page_token,
                    orderBy="updateTime desc",
                ).execute()
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
                    count += 1
                page_token = response.get("nextPageToken")
                if not page_token:
                    return count
            except HttpError as error:
                logger.warning(f"Could not sync announcements for course {course_id}: {error}")
                return count

    def _sync_materials(self, assignment_db_id: int, materials: List[Dict]):
        """Sync assignment materials"""
        from app.db.repositories import AssignmentMaterialRepository

        repo = AssignmentMaterialRepository(self.db)

        # Clear existing
        existing = repo.get_by_assignment(assignment_db_id)
        for m in existing:
            self.db.delete(m)

        for mat in materials:
            mat_dict = {
                "assignment_id": assignment_db_id,
                "material_type": mat.get("driveFile") and "drive_file" or mat.get("link") and "link" or mat.get("form") and "form" or "other",
                "title": mat.get("driveFile", {}).get("driveFile", {}).get("title") or mat.get("link", {}).get("title") or mat.get("form", {}).get("title") or "",
                "url": mat.get("driveFile", {}).get("driveFile", {}).get("alternateLink") or mat.get("link", {}).get("url") or mat.get("form", {}).get("formUrl") or "",
                "drive_file_id": mat.get("driveFile", {}).get("driveFile", {}).get("id"),
                "mime_type": mat.get("driveFile", {}).get("driveFile", {}).get("mimeType"),
            }
            repo.create(mat_dict)

        self.db.commit()

    def _sync_schedule(self, course_data: Dict) -> int:
        return 0

    def get_student_submissions(self, course_id: str, assignment_id: str) -> List[Dict]:
        """Get student submissions for an assignment"""
        try:
            submissions = self.service.courses().courseWork().studentSubmissions().list(
                courseId=course_id,
                courseWorkId=assignment_id,
                pageSize=100
            ).execute()
            return submissions.get("studentSubmissions", [])
        except HttpError as e:
            logger.error(f"Error fetching submissions: {e}")
            return []

    def get_course_students(self, course_id: str) -> List[Dict]:
        """Get students enrolled in a course"""
        students = []
        page_token = None
        while True:
            response = self.service.courses().students().list(
                courseId=course_id, pageSize=200, pageToken=page_token
            ).execute()
            students.extend(response.get("students", []))
            page_token = response.get("nextPageToken")
            if not page_token:
                return students


def get_classroom_service(db: Session = None) -> Optional[ClassroomSyncService]:
    """Factory function to get ClassroomSyncService"""
    if db is None:
        db = next(get_db())
    service = ClassroomSyncService(db)
    return service if service.service else None
