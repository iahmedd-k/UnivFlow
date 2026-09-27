from enum import Enum
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field
from datetime import datetime
from uuid import UUID, uuid4


class TaskType(str, Enum):
    ESSAY = "essay"
    CODE = "code"
    MATH = "math"
    REPORT = "report"
    PRESENTATION = "presentation"
    DATA_ANALYSIS = "data_analysis"
    RESEARCH = "research"
    OTHER = "other"


class RequirementType(str, Enum):
    WRITING = "WRITING"
    CODING = "CODING"
    CALCULATION = "CALCULATION"
    RESEARCH = "RESEARCH"
    FORMATTING = "FORMATTING"
    CITATION = "CITATION"


class DeliverableType(str, Enum):
    DOCUMENT = "DOCUMENT"
    CODE_FILE = "CODE_FILE"
    SPREADSHEET = "SPREADSHEET"
    PRESENTATION = "PRESENTATION"
    PDF = "PDF"
    IMAGE = "IMAGE"
    ARCHIVE = "ARCHIVE"


class SubmissionFormat(str, Enum):
    GOOGLE_DOC = "GOOGLE_DOC"
    FILE_UPLOAD = "FILE_UPLOAD"
    GITHUB_REPO = "GITHUB_REPO"
    LMS_NATIVE = "LMS_NATIVE"
    EMAIL = "EMAIL"


class AssignmentStatus(str, Enum):
    DETECTED = "DETECTED"
    PARSING = "PARSING"
    ANALYZING = "ANALYZING"
    GENERATING = "GENERATING"
    REVIEWING = "REVIEWING"
    READY_FOR_APPROVAL = "READY_FOR_APPROVAL"
    APPROVED = "APPROVED"
    SUBMITTED = "SUBMITTED"
    GRADED = "GRADED"
    FAILED = "FAILED"


class ApprovalMode(str, Enum):
    MANUAL = "MANUAL"
    AUTO = "AUTO"


class DocumentSource(str, Enum):
    GOOGLE_DOCS = "GOOGLE_DOCS"
    PDF = "PDF"
    WORD = "WORD"
    LMS_NATIVE = "LMS_NATIVE"
    URL = "URL"
    TEXT = "TEXT"


class ConstraintModel(BaseModel):
    word_count: Optional[int] = None
    format: Optional[str] = None  # APA, MLA, IEEE, etc.
    language: Optional[str] = None  # Python, Java, C++, etc.
    libraries: List[str] = Field(default_factory=list)
    required_sections: List[str] = Field(default_factory=list)
    prohibited_content: List[str] = Field(default_factory=list)
    file_types: List[str] = Field(default_factory=list)
    max_file_size_mb: Optional[int] = None
    custom: Dict[str, Any] = Field(default_factory=dict)


class RubricCriterion(BaseModel):
    criterion: str
    weight: float  # percentage
    description: Optional[str] = None


class Requirement(BaseModel):
    id: str = Field(default_factory=lambda: f"req_{uuid4().hex[:8]}")
    description: str
    type: RequirementType
    priority: str = "MEDIUM"  # HIGH, MEDIUM, LOW
    deliverable: DeliverableType
    constraints: ConstraintModel = Field(default_factory=ConstraintModel)
    rubric_criteria: List[RubricCriterion] = Field(default_factory=list)
    depends_on: List[str] = Field(default_factory=list)  # other requirement IDs


class Deliverable(BaseModel):
    name: str
    type: DeliverableType
    required: bool = True
    description: Optional[str] = None


class ExtractedRequirements(BaseModel):
    task_type: TaskType
    requirements: List[Requirement]
    deliverables: List[Deliverable]
    submission_format: SubmissionFormat
    template_required: bool = False
    template_doc_id: Optional[str] = None
    raw_analysis: Optional[str] = None  # Full LLM response for debugging
    confidence: float = Field(ge=0.0, le=1.0)
    extracted_at: datetime = Field(default_factory=datetime.utcnow)


class DocumentStructure(BaseModel):
    headings: List[Dict[str, Any]] = Field(default_factory=list)  # {level, text, position}
    tables: List[Dict[str, Any]] = Field(default_factory=list)
    images: List[Dict[str, Any]] = Field(default_factory=list)
    links: List[Dict[str, Any]] = Field(default_factory=list)
    code_blocks: List[Dict[str, Any]] = Field(default_factory=list)
    lists: List[Dict[str, Any]] = Field(default_factory=list)


class DocumentMetadata(BaseModel):
    title: Optional[str] = None
    author: Optional[str] = None
    created: Optional[datetime] = None
    modified: Optional[datetime] = None
    permissions: Optional[Dict[str, Any]] = None
    page_count: Optional[int] = None
    word_count: Optional[int] = None


class ParsedDocument(BaseModel):
    content: str
    structure: DocumentStructure
    metadata: DocumentMetadata
    source: DocumentSource
    doc_id: Optional[str] = None  # For Google Docs
    url: Optional[str] = None
    fetched_at: datetime = Field(default_factory=datetime.utcnow)
    parser_version: str = "1.0"


class GeneratedFile(BaseModel):
    name: str
    content: str  # Base64 for binary, text for code/docs
    mime_type: str
    size_bytes: int
    requirement_ids: List[str] = Field(default_factory=list)
    encoding: str = "utf-8"  # utf-8, base64


class SolutionPackage(BaseModel):
    files: List[GeneratedFile]
    content: Dict[str, Any]  # Structured content by requirement
    metadata: Dict[str, Any] = Field(default_factory=dict)
    ai_model: str
    generation_time_ms: int
    confidence: float = Field(ge=0.0, le=1.0)
    requirements_met: List[str] = Field(default_factory=list)
    requirements_partial: List[str] = Field(default_factory=list)
    requirements_failed: List[str] = Field(default_factory=list)
    reviewer_feedback: Optional[str] = None
    generated_at: datetime = Field(default_factory=datetime.utcnow)


class GoogleDocInfo(BaseModel):
    doc_id: str
    url: str
    drive_file_id: str
    title: str
    created_at: datetime = Field(default_factory=datetime.utcnow)
    editable_url: Optional[str] = None


class SubmissionReceipt(BaseModel):
    confirmation_id: str
    submitted_at: datetime
    method: str  # GCR_API, PLAYWRIGHT, MANUAL
    portal_submission_id: Optional[str] = None
    screenshot_url: Optional[str] = None
    raw_response: Optional[Dict[str, Any]] = None


class AutoApprovalConfig(BaseModel):
    enabled: bool = False
    min_confidence: float = Field(default=0.90, ge=0.5, le=1.0)
    allowed_task_types: List[TaskType] = Field(default_factory=lambda: [TaskType.CODE, TaskType.MATH, TaskType.DATA_ANALYSIS])
    max_grade_percentage: float = Field(default=20.0, ge=0, le=100)
    notify_before_submit: bool = True
    notify_minutes_before: int = Field(default=5, ge=1, le=60)
    excluded_courses: List[str] = Field(default_factory=list)
    excluded_keywords: List[str] = Field(default_factory=lambda: ["final", "thesis", "capstone", "midterm", "dissertation"])
    require_manual_for: Dict[str, bool] = Field(default_factory=lambda: {
        "group_work": True,
        "presentations": True,
        "peer_review": True
    })


class UserTemplate(BaseModel):
    template_doc_id: str
    template_url: str
    placeholders: Dict[str, str] = Field(default_factory=dict)
    default_font: str = "Times New Roman"
    default_font_size: int = 12
    margins: Dict[str, float] = Field(default_factory=lambda: {"top": 1.0, "bottom": 1.0, "left": 1.0, "right": 1.0})


class AssignmentRecord(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    user_id: UUID
    portal_id: UUID
    external_id: str
    
    title: str
    description: Optional[str] = None
    course_code: str
    course_name: str
    due_date: datetime
    assigned_date: Optional[datetime] = None
    
    source_documents: List[ParsedDocument] = Field(default_factory=list)
    
    status: AssignmentStatus = AssignmentStatus.DETECTED
    
    requirements: Optional[ExtractedRequirements] = None
    generated_solution: Optional[SolutionPackage] = None
    google_doc: Optional[GoogleDocInfo] = None
    
    approval_mode: ApprovalMode = ApprovalMode.MANUAL
    auto_approval_config: Optional[AutoApprovalConfig] = None
    approved_at: Optional[datetime] = None
    approved_by: Optional[UUID] = None
    approval_notes: Optional[str] = None
    
    submission_target: Optional[str] = None
    submission_receipt: Optional[SubmissionReceipt] = None
    submitted_at: Optional[datetime] = None
    
    grade: Optional[float] = None
    graded_at: Optional[datetime] = None
    feedback: Optional[str] = None
    
    error_log: List[str] = Field(default_factory=list)
    retry_count: int = 0
    
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


# API Request/Response Models
class ApproveRequest(BaseModel):
    mode: ApprovalMode = ApprovalMode.MANUAL
    changes_requested: Optional[str] = None
    auto_approve_future: bool = False


class ChangesRequest(BaseModel):
    feedback: str
    specific_requirements: List[str] = Field(default_factory=list)
    priority: str = "HIGH"


class UpdateDocRequest(BaseModel):
    content: Optional[str] = None
    replacement_map: Optional[Dict[str, str]] = None  # For placeholder replacement


class AutoApprovalConfigRequest(BaseModel):
    enabled: bool
    min_confidence: float = 0.90
    allowed_task_types: List[TaskType] = []
    max_grade_percentage: float = 20.0
    notify_before_submit: bool = True
    notify_minutes_before: int = 5
    excluded_courses: List[str] = []
    excluded_keywords: List[str] = []
    require_manual_for: Dict[str, bool] = {}


class AssignmentReviewResponse(BaseModel):
    assignment: AssignmentRecord
    requirements: ExtractedRequirements
    generated_solution: SolutionPackage
    google_doc: GoogleDocInfo
    confidence_score: float
    ai_reasoning: str
    can_auto_approve: bool
    auto_approval_reason: Optional[str] = None


class DocumentFetchRequest(BaseModel):
    urls: List[str]
    google_doc_ids: List[str] = Field(default_factory=list)
    portal_attachment_ids: List[str] = Field(default_factory=list)