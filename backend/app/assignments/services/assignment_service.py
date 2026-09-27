import logging
from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta
from uuid import UUID, uuid4

from app.assignments.schemas.assignment import (
    AssignmentRecord, ExtractedRequirements, SolutionPackage,
    GoogleDocInfo, SubmissionReceipt, ApproveRequest, ChangesRequest,
    AutoApprovalConfig, AutoApprovalConfigRequest, AssignmentReviewResponse,
    AssignmentStatus, ApprovalMode, TaskType
)
from app.assignments.services.document_parser import DocumentParserFactory
from app.assignments.services.requirements_extractor import RequirementsExtractor
from app.assignments.services.solution_generator import SolutionGenerator
from app.google_docs.template_engine import GoogleDocsTemplateEngine
from app.assignments.services.submission_executor import SubmissionService

logger = logging.getLogger(__name__)


class AssignmentService:
    """
    Main orchestration service for the Assignment Solver flow.
    
    Flow:
    1. Detect assignment → Create AssignmentRecord
    2. Parse documents → Extract requirements
    3. Generate solution → Review
    4. Create Google Doc from template
    5. Present for approval
    6. Submit on approval
    """
    
    def __init__(
        self,
        document_parser: DocumentParserFactory,
        requirements_extractor: RequirementsExtractor,
        solution_generator: SolutionGenerator,
        template_engine: GoogleDocsTemplateEngine,
        submission_service: SubmissionService,
        db_session=None  # SQLAlchemy session
    ):
        self.document_parser = document_parser
        self.requirements_extractor = requirements_extractor
        self.solution_generator = solution_generator
        self.template_engine = template_engine
        self.submission_service = submission_service
        self.db = db_session
    
    # ============================================================
    # PHASE 1: ASSIGNMENT DETECTION & INGESTION
    # ============================================================
    
    async def ingest_assignment(
        self,
        user_id: UUID,
        portal_id: UUID,
        external_id: str,
        title: str,
        course_code: str,
        course_name: str,
        due_date: datetime,
        description: str = "",
        assigned_date: Optional[datetime] = None,
        source_document_urls: List[str] = None,
        source_google_doc_ids: List[str] = None,
        instructor: str = "",
        semester: str = "",
        section: str = ""
    ) -> AssignmentRecord:
        """Create new assignment record from portal detection."""
        
        assignment = AssignmentRecord(
            id=uuid4(),
            user_id=user_id,
            portal_id=portal_id,
            external_id=external_id,
            title=title,
            description=description,
            course_code=course_code,
            course_name=course_name,
            due_date=due_date,
            assigned_date=assigned_date or datetime.utcnow(),
            status=AssignmentStatus.DETECTED
        )
        
        # Save to DB
        if self.db:
            self.db.add(assignment)
            await self.db.commit()
        
        # Start processing pipeline
        await self.process_assignment(assignment.id)
        
        return assignment
    
    # ============================================================
    # PHASE 2: DOCUMENT PARSING & REQUIREMENTS EXTRACTION
    # ============================================================
    
    async def process_assignment(self, assignment_id: UUID) -> AssignmentRecord:
        """Main processing pipeline."""
        assignment = await self._get_assignment(assignment_id)
        if not assignment:
            raise ValueError(f"Assignment {assignment_id} not found")
        
        try:
            # Step 1: Parse documents
            await self._update_status(assignment_id, AssignmentStatus.PARSING)
            parsed_docs = await self._parse_source_documents(assignment)
            assignment.source_documents = parsed_docs
            
            # Step 2: Extract requirements
            await self._update_status(assignment_id, AssignmentStatus.ANALYZING)
            requirements = await self._extract_requirements(assignment)
            assignment.requirements = requirements
            
            # Step 3: Generate solution
            await self._update_status(assignment_id, AssignmentStatus.GENERATING)
            solution = await self._generate_solution(assignment)
            assignment.generated_solution = solution
            
            # Step 4: Create Google Doc
            await self._update_status(assignment_id, AssignmentStatus.REVIEWING)
            google_doc = await self._create_google_doc(assignment)
            assignment.google_doc = google_doc
            
            # Step 5: Ready for approval
            await self._update_status(assignment_id, AssignmentStatus.READY_FOR_APPROVAL)
            
            # Check auto-approval
            if await self._should_auto_approve(assignment):
                await self.approve_assignment(assignment_id, ApproveRequest(mode=ApprovalMode.AUTO))
            
            return assignment
            
        except Exception as e:
            logger.error(f"Processing failed for {assignment_id}: {e}")
            assignment.status = AssignmentStatus.FAILED
            assignment.error_log.append(f"{datetime.utcnow()}: {str(e)}")
            if self.db:
                await self.db.commit()
            raise
    
    async def _parse_source_documents(self, assignment: AssignmentRecord) -> List:
        """Parse all source documents."""
        parsed = []
        
        # Parse Google Docs
        for doc_id in assignment.source_google_doc_ids or []:
            try:
                parsed_doc = await self.document_parser.parse_google_doc(doc_id)
                parsed.append(parsed_doc)
            except Exception as e:
                logger.error(f"Failed to parse Google Doc {doc_id}: {e}")
        
        # Parse URLs (PDF, Word, etc.)
        for url in assignment.source_document_urls or []:
            try:
                # Fetch and parse
                # In production: use httpx to download
                pass
            except Exception as e:
                logger.error(f"Failed to parse URL {url}: {e}")
        
        return parsed
    
    async def _extract_requirements(self, assignment: AssignmentRecord) -> ExtractedRequirements:
        """Extract requirements from parsed documents."""
        # Combine all document content
        combined_content = "\n\n".join([doc.content for doc in assignment.source_documents])
        
        # Create a combined document for analysis
        from app.assignments.schemas.assignment import ParsedDocument, DocumentStructure, DocumentMetadata
        combined_doc = ParsedDocument(
            content=combined_content,
            structure=DocumentStructure(),
            metadata=DocumentMetadata(),
            source="COMBINED"
        )
        
        return await self.requirements_extractor.extract(
            document=combined_doc,
            assignment_title=assignment.title,
            course_name=assignment.course_name,
            course_code=assignment.course_code,
            due_date=assignment.due_date,
            description=assignment.description
        )
    
    async def _generate_solution(self, assignment: AssignmentRecord) -> SolutionPackage:
        """Generate solution using multi-agent pipeline."""
        user_context = await self._get_user_context(assignment.user_id)
        assignment_context = {
            "course_name": assignment.course_name,
            "course_code": assignment.course_code,
            "title": assignment.title,
            "technical_specs": assignment.description
        }
        
        return await self.solution_generator.generate(
            requirements=assignment.requirements,
            assignment_context=assignment_context,
            user_context=user_context
        )
    
    async def _create_google_doc(self, assignment: AssignmentRecord) -> GoogleDocInfo:
        """Create Google Doc from template with solution."""
        # Get user template
        user_template = await self._get_user_template(assignment.user_id)
        if not user_template:
            # Create default template
            user_context = await self._get_user_context(assignment.user_id)
            template_result = await self.template_engine.create_default_template(
                str(assignment.user_id), user_context
            )
            user_template = template_result
        
        # Prepare solution content
        solution_content = self._format_solution_for_doc(assignment.generated_solution)
        
        # Prepare metadata
        assignment_metadata = {
            "title": assignment.title,
            "course_name": assignment.course_name,
            "course_code": assignment.course_code,
            "instructor": assignment.instructor or "",
            "due_date": assignment.due_date,
            "semester": assignment.semester or "",
            "section": assignment.section or ""
        }
        
        user_context = await self._get_user_context(assignment.user_id)
        
        # Create document
        result = await self.template_engine.create_submission_document(
            template_doc_id=user_template["doc_id"] if isinstance(user_template, dict) else user_template.template_doc_id,
            placeholders=user_template.placeholders if isinstance(user_template, dict) else user_template.placeholders,
            solution_content=solution_content,
            assignment_metadata=assignment_metadata,
            user_metadata=user_context
        )
        
        return GoogleDocInfo(**result)
    
    def _format_solution_for_doc(self, solution: SolutionPackage) -> str:
        """Format solution package for Google Doc insertion."""
        parts = []
        
        for req_id, content in solution.content.items():
            if isinstance(content, dict):
                if "content" in content:
                    parts.append(f"## {req_id}\n\n{content['content']}")
                elif "files" in content:
                    parts.append(f"## {req_id} - Code Solution\n\n")
                    for f in content["files"]:
                        parts.append(f"### {f['name']}\n```\n{f['content']}\n```\n")
                else:
                    parts.append(f"## {req_id}\n\n{json.dumps(content, indent=2)}")
            else:
                parts.append(f"## {req_id}\n\n{content}")
        
        return "\n\n---\n\n".join(parts)
    
    # ============================================================
    # PHASE 3: APPROVAL WORKFLOW
    # ============================================================
    
    async def get_review_data(self, assignment_id: UUID) -> AssignmentReviewResponse:
        """Get all data needed for review page."""
        assignment = await self._get_assignment(assignment_id)
        if not assignment:
            raise ValueError(f"Assignment {assignment_id} not found")
        
        # Check auto-approval eligibility
        can_auto, reason = await self._check_auto_approval_eligibility(assignment)
        
        return AssignmentReviewResponse(
            assignment=assignment,
            requirements=assignment.requirements,
            generated_solution=assignment.generated_solution,
            google_doc=assignment.google_doc,
            confidence_score=assignment.generated_solution.confidence if assignment.generated_solution else 0,
            ai_reasoning=assignment.generated_solution.reviewer_feedback if assignment.generated_solution else "",
            can_auto_approve=can_auto,
            auto_approval_reason=reason
        )
    
    async def approve_assignment(
        self, 
        assignment_id: UUID, 
        request: ApproveRequest
    ) -> AssignmentRecord:
        """Approve and optionally submit assignment."""
        assignment = await self._get_assignment(assignment_id)
        if not assignment:
            raise ValueError(f"Assignment {assignment_id} not found")
        
        if assignment.status not in [AssignmentStatus.READY_FOR_APPROVAL, AssignmentStatus.APPROVED]:
            raise ValueError(f"Assignment not ready for approval: {assignment.status}")
        
        # Update approval info
        assignment.approval_mode = request.mode
        assignment.approved_at = datetime.utcnow()
        assignment.approved_by = request.changes_requested  # Would be user_id from auth
        assignment.approval_notes = request.changes_requested
        assignment.status = AssignmentStatus.APPROVED
        
        if self.db:
            await self.db.commit()
        
        # Submit if approved
        if request.mode == ApprovalMode.AUTO or not request.changes_requested:
            await self.submit_assignment(assignment_id)
        
        return assignment
    
    async def request_changes(
        self, 
        assignment_id: UUID, 
        request: ChangesRequest
    ) -> AssignmentRecord:
        """Request changes to generated solution."""
        assignment = await self._get_assignment(assignment_id)
        if not assignment:
            raise ValueError(f"Assignment {assignment_id} not found")
        
        # Add feedback to regeneration context
        # In production: store feedback and re-run generator with constraints
        assignment.status = AssignmentStatus.GENERATING
        assignment.error_log.append(f"Changes requested: {request.feedback}")
        
        if self.db:
            await self.db.commit()
        
        # Re-generate with feedback
        # This would need a more sophisticated regeneration pipeline
        # For now, just mark as needing regeneration
        assignment.status = AssignmentStatus.REVIEWING
        
        if self.db:
            await self.db.commit()
        
        return assignment
    
    # ============================================================
    # PHASE 4: SUBMISSION
    # ============================================================
    
    async def submit_assignment(self, assignment_id: UUID) -> SubmissionReceipt:
        """Submit approved assignment to portal."""
        assignment = await self._get_assignment(assignment_id)
        if not assignment:
            raise ValueError(f"Assignment {assignment_id} not found")
        
        if assignment.status != AssignmentStatus.APPROVED:
            raise ValueError(f"Assignment not approved: {assignment.status}")
        
        # Get student credentials
        student_credentials = await self._get_student_credentials(assignment.user_id)
        student_info = await self._get_user_context(assignment.user_id)
        
        # Submit
        receipt = await self.submission_service.submit_assignment(
            assignment=assignment,
            solution=assignment.generated_solution,
            google_doc=assignment.google_doc,
            student_credentials=student_credentials,
            student_info=student_info
        )
        
        # Update assignment
        assignment.status = AssignmentStatus.SUBMITTED
        assignment.submission_receipt = receipt
        assignment.submitted_at = datetime.utcnow()
        
        if self.db:
            await self.db.commit()
        
        return receipt
    
    # ============================================================
    # AUTO-APPROVAL LOGIC
    # ============================================================
    
    async def _should_auto_approve(self, assignment: AssignmentRecord) -> bool:
        """Check if assignment should be auto-approved."""
        config = await self.get_auto_approval_config(assignment.user_id)
        if not config or not config.enabled:
            return False
        
        return await self._check_auto_approval_eligibility(assignment)[0]
    
    async def _check_auto_approval_eligibility(
        self, 
        assignment: AssignmentRecord
    ) -> tuple[bool, str]:
        """Check if assignment meets auto-approval criteria."""
        config = await self.get_auto_approval_config(assignment.user_id)
        if not config or not config.enabled:
            return False, "Auto-approval disabled"
        
        solution = assignment.generated_solution
        if not solution:
            return False, "No solution generated"
        
        # Check confidence
        if solution.confidence < config.min_confidence:
            return False, f"Confidence {solution.confidence:.0%} below threshold {config.min_confidence:.0%}"
        
        # Check task type
        if assignment.requirements.task_type not in config.allowed_task_types:
            return False, f"Task type {assignment.requirements.task_type} not allowed for auto-approval"
        
        # Check excluded courses
        if assignment.course_code in config.excluded_courses:
            return False, f"Course {assignment.course_code} excluded from auto-approval"
        
        # Check excluded keywords
        title_lower = assignment.title.lower()
        for keyword in config.excluded_keywords:
            if keyword.lower() in title_lower:
                return False, f"Title contains excluded keyword: {keyword}"
        
        # Check manual requirements
        if config.require_manual_for.get("group_work") and assignment.description and "group" in assignment.description.lower():
            return False, "Group work requires manual approval"
        
        return True, "Eligible for auto-approval"
    
    async def get_auto_approval_config(self, user_id: UUID) -> Optional[AutoApprovalConfig]:
        """Get user's auto-approval configuration."""
        # In production: fetch from DB
        return AutoApprovalConfig()
    
    async def update_auto_approval_config(
        self, 
        user_id: UUID, 
        config: AutoApprovalConfigRequest
    ) -> AutoApprovalConfig:
        """Update user's auto-approval configuration."""
        # In production: save to DB
        return AutoApprovalConfig(**config.dict())
    
    # ============================================================
    # HELPER METHODS
    # ============================================================
    
    async def _get_assignment(self, assignment_id: UUID) -> Optional[AssignmentRecord]:
        """Fetch assignment from database."""
        if self.db:
            return await self.db.get(AssignmentRecord, assignment_id)
        return None
    
    async def _update_status(self, assignment_id: UUID, status: AssignmentStatus):
        """Update assignment status."""
        assignment = await self._get_assignment(assignment_id)
        if assignment:
            assignment.status = status
            assignment.updated_at = datetime.utcnow()
            if self.db:
                await self.db.commit()
    
    async def _get_user_context(self, user_id: UUID) -> Dict[str, Any]:
        """Get user context for template filling."""
        # In production: fetch from user profile
        return {
            "name": "John Doe",
            "student_id": "STU123456",
            "email": "john.doe@university.edu",
            "university": "Sample University",
            "level": "Undergraduate"
        }
    
    async def _get_user_template(self, user_id: UUID) -> Optional[Dict]:
        """Get user's saved template."""
        # In production: fetch from DB
        return None
    
    async def _get_student_credentials(self, user_id: UUID) -> Dict[str, Any]:
        """Get student's portal credentials."""
        # In production: fetch encrypted credentials from secure storage
        return {
            "google_oauth": {
                "token": "...",
                "refresh_token": "...",
                "client_id": "...",
                "client_secret": "..."
            }
        }