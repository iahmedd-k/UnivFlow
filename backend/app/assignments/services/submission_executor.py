import logging
from abc import ABC, abstractmethod
from typing import Optional, List, Dict, Any
from datetime import datetime
from dataclasses import dataclass

from app.assignments.schemas.assignment import (
    SolutionPackage, GoogleDocInfo, SubmissionReceipt, 
    SubmissionFormat, AssignmentRecord
)

logger = logging.getLogger(__name__)


@dataclass
class SubmissionTarget:
    platform: str  # GCR, CANVAS, BLACKBOARD, MOODLE, CUSTOM
    course_id: str
    assignment_id: str
    credentials: Dict[str, Any]
    config: Dict[str, Any]


class BaseSubmissionExecutor(ABC):
    @abstractmethod
    async def submit(
        self,
        target: SubmissionTarget,
        solution: SolutionPackage,
        google_doc: Optional[GoogleDocInfo],
        student_info: Dict[str, Any]
    ) -> SubmissionReceipt:
        pass
    
    @abstractmethod
    async def verify_submission(
        self,
        target: SubmissionTarget,
        receipt: SubmissionReceipt
    ) -> bool:
        pass


class GCROAuthCredentials:
    """Google Classroom OAuth credentials handler."""
    
    def __init__(self, credentials_dict: Dict[str, Any]):
        self.credentials_dict = credentials_dict
        self._service = None
    
    def get_service(self):
        if self._service is None:
            from googleapiclient.discovery import build
            from google.oauth2.credentials import Credentials
            
            creds = Credentials.from_authorized_user_info(self.credentials_dict)
            self._service = build("classroom", "v1", credentials=creds)
        return self._service


class GCRSubmissionExecutor(BaseSubmissionExecutor):
    """Google Classroom submission executor."""
    
    def __init__(self):
        self._service = None
    
    def _get_service(self, credentials: Dict[str, Any]):
        if self._service is None:
            from googleapiclient.discovery import build
            from google.oauth2.credentials import Credentials
            
            creds = Credentials.from_authorized_user_info(credentials)
            self._service = build("classroom", "v1", credentials=creds)
        return self._service
    
    async def submit(
        self,
        target: SubmissionTarget,
        solution: SolutionPackage,
        google_doc: Optional[GoogleDocInfo],
        student_info: Dict[str, Any]
    ) -> SubmissionReceipt:
        """Submit to Google Classroom."""
        service = self._get_service(target.credentials)
        
        course_id = target.course_id
        assignment_id = target.assignment_id
        
        # 1. Get or create student submission
        submission = self._get_or_create_submission(service, course_id, assignment_id, student_info)
        submission_id = submission.get("id")
        
        if not submission_id:
            raise Exception("Could not create/access student submission")
        
        # 2. Attach files
        attachments = []
        
        # Attach Google Doc if available
        if google_doc:
            attachments.append({
                "driveFile": {
                    "id": google_doc.drive_file_id,
                    "title": google_doc.title,
                    "alternateLink": google_doc.url
                }
            })
        
        # Attach additional files
        for file in solution.files:
            # For additional files, we need to upload to Drive first
            drive_file_id = await self._upload_to_drive(
                target.credentials, file, student_info
            )
            if drive_file_id:
                attachments.append({
                    "driveFile": {
                        "id": drive_file_id,
                        "title": file.name,
                        "alternateLink": f"https://drive.google.com/file/d/{drive_file_id}/view"
                    }
                })
        
        # 3. Add attachments to submission
        if attachments:
            service.courses().courseWork().studentSubmissions().modifyAttachments(
                courseId=course_id,
                courseWorkId=assignment_id,
                id=submission_id,
                body={"addAttachments": attachments}
            ).execute()
        
        # 4. Turn in the submission
        turn_in_result = service.courses().courseWork().studentSubmissions().turnIn(
            courseId=course_id,
            courseWorkId=assignment_id,
            id=submission_id
        ).execute()
        
        return SubmissionReceipt(
            confirmation_id=turn_in_result.get("id", submission_id),
            submitted_at=datetime.utcnow(),
            method="GCR_API",
            portal_submission_id=submission_id,
            raw_response=turn_in_result
        )
    
    def _get_or_create_submission(
        self, 
        service, 
        course_id: str, 
        assignment_id: str, 
        student_info: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Get existing submission or create new one."""
        user_id = student_info.get("google_user_id", "me")
        
        try:
            # List student submissions
            submissions = service.courses().courseWork().studentSubmissions().list(
                courseId=course_id,
                courseWorkId=assignment_id,
                userId=user_id
            ).execute()
            
            student_submissions = submissions.get("studentSubmissions", [])
            if student_submissions:
                return student_submissions[0]
        except Exception as e:
            logger.warning(f"Could not list submissions: {e}")
        
        # Create new submission
        try:
            submission = service.courses().courseWork().studentSubmissions().create(
                courseId=course_id,
                courseWorkId=assignment_id,
                body={"userId": user_id}
            ).execute()
            return submission
        except Exception as e:
            logger.error(f"Failed to create submission: {e}")
            raise
    
    async def _upload_to_drive(
        self, 
        credentials: Dict[str, Any], 
        file: Any,
        student_info: Dict[str, Any]
    ) -> Optional[str]:
        """Upload file to Google Drive and return file ID."""
        try:
            from googleapiclient.discovery import build
            from googleapiclient.http import MediaIoBaseUpload
            from google.oauth2.credentials import Credentials
            import io
            
            creds = Credentials.from_authorized_user_info(credentials)
            drive_service = build("drive", "v3", credentials=creds)
            
            # Prepare file metadata
            file_metadata = {
                "name": file.name,
                "parents": [student_info.get("drive_folder_id", "root")]
            }
            
            # Prepare media
            content = file.content
            if file.encoding == "base64":
                import base64
                content = base64.b64decode(content)
            
            media = MediaIoBaseUpload(
                io.BytesIO(content),
                mimetype=file.mime_type,
                resumable=True
            )
            
            # Upload
            uploaded = drive_service.files().create(
                body=file_metadata,
                media_body=media,
                fields="id"
            ).execute()
            
            return uploaded.get("id")
        except Exception as e:
            logger.error(f"Failed to upload file to Drive: {e}")
            return None
    
    async def verify_submission(
        self,
        target: SubmissionTarget,
        receipt: SubmissionReceipt
    ) -> bool:
        """Verify submission was successful."""
        try:
            service = self._get_service(target.credentials)
            submission = service.courses().courseWork().studentSubmissions().get(
                courseId=target.course_id,
                courseWorkId=target.assignment_id,
                id=receipt.portal_submission_id
            ).execute()
            
            state = submission.get("state", "")
            return state in ["TURNED_IN", "RETURNED"]
        except Exception as e:
            logger.error(f"Verification failed: {e}")
            return False


class PlaywrightSubmissionExecutor(BaseSubmissionExecutor):
    """Generic Playwright-based submission for LMS portals."""
    
    def __init__(self, browser_manager=None):
        self.browser_manager = browser_manager
    
    async def submit(
        self,
        target: SubmissionTarget,
        solution: SolutionPackage,
        google_doc: Optional[GoogleDocInfo],
        student_info: Dict[str, Any]
    ) -> SubmissionReceipt:
        """Submit via browser automation."""
        # This would use Playwright to navigate the LMS
        # Implementation depends on specific portal
        raise NotImplementedError("Playwright executor needs portal-specific implementation")
    
    async def verify_submission(
        self,
        target: SubmissionTarget,
        receipt: SubmissionReceipt
    ) -> bool:
        raise NotImplementedError


class SubmissionExecutorFactory:
    """Factory for creating submission executors."""
    
    def __init__(self):
        self._executors = {
            "GCR": GCRSubmissionExecutor(),
            "GOOGLE_CLASSROOM": GCRSubmissionExecutor(),
            "PLAYWRIGHT": PlaywrightSubmissionExecutor(),
        }
    
    def register(self, platform: str, executor: BaseSubmissionExecutor):
        self._executors[platform.upper()] = executor
    
    def get_executor(self, platform: str) -> Optional[BaseSubmissionExecutor]:
        return self._executors.get(platform.upper())
    
    async def submit(
        self,
        platform: str,
        target: SubmissionTarget,
        solution: SolutionPackage,
        google_doc: Optional[GoogleDocInfo],
        student_info: Dict[str, Any]
    ) -> SubmissionReceipt:
        executor = self.get_executor(platform)
        if not executor:
            raise ValueError(f"No executor for platform: {platform}")
        return await executor.submit(target, solution, google_doc, student_info)


class SubmissionService:
    """High-level submission orchestration service."""
    
    def __init__(self, executor_factory: SubmissionExecutorFactory):
        self.factory = executor_factory
    
    async def submit_assignment(
        self,
        assignment: AssignmentRecord,
        solution: SolutionPackage,
        google_doc: Optional[GoogleDocInfo],
        student_credentials: Dict[str, Any],
        student_info: Dict[str, Any]
    ) -> SubmissionReceipt:
        """
        Submit assignment to the appropriate platform.
        """
        # Determine submission target
        platform = assignment.submission_target or "GCR"
        
        target = SubmissionTarget(
            platform=platform,
            course_id=assignment.course_code,  # May need mapping
            assignment_id=assignment.external_id,
            credentials=student_credentials,
            config={}
        )
        
        # Execute submission
        receipt = await self.factory.submit(
            platform, target, solution, google_doc, student_info
        )
        
        # Verify
        executor = self.factory.get_executor(platform)
        if executor:
            verified = await executor.verify_submission(target, receipt)
            if not verified:
                logger.warning("Submission verification failed")
        
        return receipt
    
    async def schedule_submission(
        self,
        assignment: AssignmentRecord,
        solution: SolutionPackage,
        google_doc: Optional[GoogleDocInfo],
        student_credentials: Dict[str, Any],
        student_info: Dict[str, Any],
        submit_at: datetime
    ) -> str:
        """Schedule submission for later (e.g., before deadline)."""
        # In production, use Celery/Redis or similar task queue
        # This is a placeholder
        task_id = f"submit_{assignment.id}_{submit_at.timestamp()}"
        logger.info(f"Scheduled submission {task_id} for {submit_at}")
        return task_id