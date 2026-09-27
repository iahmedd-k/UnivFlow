# Assignment Solver Flow - Complete Architecture

## Overview
End-to-end flow: **Portal Detection → Document Analysis → AI Solution → Google Docs Template → Submission → User Approval**

---

## 1. TRIGGER: Assignment Published Detection

```
┌─────────────────────────────────────────────────────────────────┐
│                    PORTAL MONITOR (Scheduler)                   │
├─────────────────────────────────────────────────────────────────┤
│  • Polls LMS portals (GCR, Canvas, Blackboard, Moodle)         │
│  • Webhook receivers for real-time updates                     │
│  • Detects: NEW_ASSIGNMENT, ASSIGNMENT_UPDATED                 │
│  • Filters: Only courses user is enrolled in                   │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                    ASSIGNMENT INGESTION SERVICE                 │
├─────────────────────────────────────────────────────────────────┤
│  • Normalize assignment data across portals                    │
│  • Extract: title, description, due_date, attachments, links   │
│  • Identify document links (Google Docs, PDF, Word, etc.)      │
│  • Create AssignmentRecord in DB with status: PENDING_ANALYSIS │
└─────────────────────────────────────────────────────────────────┘
```

---

## 2. DOCUMENT ACQUISITION & PARSING

```
┌─────────────────────────────────────────────────────────────────┐
│                    DOCUMENT FETCHER SERVICE                     │
├─────────────────────────────────────────────────────────────────┤
│  For each attachment/link:                                      │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐             │
│  │ Google Docs │  │    PDF      │  │  Word/Other │             │
│  │   (API)     │  │  (pdf-parse)│  │ (python-docx)│            │
│  └─────────────┘  └─────────────┘  └─────────────┘             │
│         │               │               │                        │
│         └───────────────┼───────────────┘                        │
│                         ▼                                        │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │              UNIFIED DOCUMENT MODEL                      │   │
│  │  {                                                       │   │
│  │    content: string,           // Full text               │   │
│  │    structure: {               // Headings, sections      │   │
│  │      headings: [],                                                       
│  │      tables: [],                                                        
│  │      images: [],                                                        
│  │      links: []                                                         
│  │    },                                                                  
│  │    metadata: {                // Doc metadata            │   │
│  │      title, author, created, modified, permissions        │   │
│  │    },                                                                  
│  │    source: 'GOOGLE_DOCS' | 'PDF' | 'WORD' | 'LMS_NATIVE'  │   │
│  │    docId: string,             // For Google Docs updates   │   │
│  │  }                                                       │   │
│  └─────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
```

---

## 3. REQUIREMENTS EXTRACTION (AI Analysis)

```
┌─────────────────────────────────────────────────────────────────┐
│                   REQUIREMENTS EXTRACTOR (LLM)                  │
├─────────────────────────────────────────────────────────────────┤
│  INPUT:                                                         │
│  • Document content + structure                                 │
│  • Assignment metadata (title, course, due date)               │
│  • User context (major, level, previous submissions)           │
│                                                                 │
│  PROMPT TEMPLATE:                                               │
│  ─────────────────────────────────────────────────────────────  │
│  You are an expert academic assignment analyzer. Extract:       │
│                                                                 │
│  1. TASK_TYPE: "essay" | "code" | "math" | "report" |          │
│     "presentation" | "data_analysis" | "research" | "other"    │
│                                                                 │
│  2. REQUIREMENTS: [                                             │
│     {                                                            │
│       id: "req_1",                                               │
│       description: "Write a 1500-word essay on...",            │
│       type: "WRITING" | "CODING" | "CALCULATION" |              │
│              "RESEARCH" | "FORMATTING" | "CITATION",           │
│       priority: "HIGH" | "MEDIUM" | "LOW",                     │
│       deliverable: "DOCUMENT" | "CODE_FILE" | "SPREADSHEET"    │
│              | "PRESENTATION" | "PDF",                         │
│       constraints: {                                             │
│         word_count: 1500,                                       │
│         format: "APA",                                          │
│         language: "Python",                                     │
│         libraries: ["pandas", "numpy"]                          │
│       },                                                         │
│       rubric_criteria: [                                        │
│         { criterion: "Analysis depth", weight: 30 },           │
│         { criterion: "Code quality", weight: 25 }              │
│       ]                                                         │
│     }                                                            │
│  ]                                                               │
│                                                                 │
│  3. DELIVERABLES: [                                             │
│     { name: "main.py", type: "CODE", required: true },         │
│     { name: "report.pdf", type: "DOCUMENT", required: true },  │
│     { name: "data.xlsx", type: "SPREADSHEET", required: false }│
│  ]                                                               │
│                                                                 │
│  4. SUBMISSION_FORMAT: "GOOGLE_DOC" | "FILE_UPLOAD"            │
│              | "GITHUB_REPO" | "LMS_NATIVE"                    │
│                                                                 │
│  5. TEMPLATE_REQUIRED: boolean  // Does user have a template?  │
│                                                                 │
│  OUTPUT: StructuredRequirements (JSON)                          │
└─────────────────────────────────────────────────────────────────┘
```

---

## 4. SOLUTION GENERATION (AI Agent)

```
┌─────────────────────────────────────────────────────────────────┐
│                    SOLUTION GENERATOR (Agent)                   │
├─────────────────────────────────────────────────────────────────┤
│  For EACH requirement:                                          │
│                                                                 │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │  PLANNER AGENT                                           │   │
│  │  • Breaks requirement into subtasks                     │   │
│  │  • Determines approach, resources needed                │   │
│  │  • Creates execution plan                                │   │
│  └─────────────────────────────────────────────────────────┘   │
│                           │                                     │
│                           ▼                                     │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │  EXECUTOR AGENTS (per requirement type)                 │   │
│  │  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌────────────┐ │   │
│  │  │ WRITING  │ │  CODING  │ │  MATH    │ │ RESEARCH   │ │   │
│  │  │ Agent    │ │ Agent    │ │ Agent    │ │ Agent      │ │   │
│  │  └──────────┘ └──────────┘ └──────────┘ └────────────┘ │   │
│  └─────────────────────────────────────────────────────────┘   │
│                           │                                     │
│                           ▼                                     │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │  REVIEWER AGENT                                          │   │
│  │  • Validates against requirements                       │   │
│  │  • Checks formatting, citations, code quality           │   │
│  │  • Scores against rubric (if available)                 │   │
│  │  • Returns: PASS | NEEDS_REVISION (with feedback)       │   │
│  └─────────────────────────────────────────────────────────┘   │
│                           │                                     │
│           ┌───────────────┴───────────────┐                   │
│           ▼                               ▼                   │
│  ┌──────────────────┐           ┌──────────────────┐         │
│  │   REVISE         │           │   FINAL OUTPUT   │         │
│  │   (loop back)    │           │  {               │         │
│  └──────────────────┘           │    files: [],    │         │
│                                 │    content: {},  │         │
│                                 │    metadata: {}  │         │
│                                 │  }               │         │
│                                 └──────────────────┘         │
└─────────────────────────────────────────────────────────────────┘
```

---

## 5. GOOGLE DOCS TEMPLATE PROCESSING

```
┌─────────────────────────────────────────────────────────────────┐
│              GOOGLE DOCS TEMPLATE ENGINE                        │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  USER TEMPLATE (stored in user settings):                       │
│  ─────────────────────────────────────────────────────────────  │
│  [COVER PAGE]                                                   │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │                                                         │   │
│  │           {{UNIVERSITY_LOGO}}                           │   │
│  │                                                         │   │
│  │           {{ASSIGNMENT_TITLE}}                          │   │
│  │                                                         │   │
│  │    Submitted by: {{STUDENT_NAME}}                       │   │
│  │    Student ID: {{STUDENT_ID}}                           │   │
│  │    Course: {{COURSE_NAME}} ({{COURSE_CODE}})            │   │
│  │    Instructor: {{INSTRUCTOR_NAME}}                      │   │
│  │    Date: {{SUBMISSION_DATE}}                            │   │
│  │                                                         │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                 │
│  [SOLUTION CONTENT PLACEHOLDER]                                 │
│  {{SOLUTION_CONTENT}}                                           │
│                                                                 │
│  PROCESSING:                                                    │
│  ─────────────────────────────────────────────────────────────  │
│  1. Fetch user's saved template (or use default)               │
│  2. Replace placeholders:                                       │
│     • {{STUDENT_NAME}} → from Clerk/user profile               │
│     • {{STUDENT_ID}} → from university profile                 │
│     • {{COURSE_NAME/CODE}} → from assignment context           │
│     • {{INSTRUCTOR_NAME}} → from course data                   │
│     • {{SUBMISSION_DATE}} → current date (formatted)           │
│     • {{ASSIGNMENT_TITLE}} → from assignment                   │
│     • {{SOLUTION_CONTENT}} → generated solution                │
│  3. Apply formatting:                                           │
│     • Preserve template styles (fonts, spacing, margins)       │
│     • Insert code blocks with syntax highlighting              │
│     • Insert tables, images, charts as inline elements         │
│     • Add page breaks between sections                         │
│  4. Create NEW document in user's Google Drive                 │
│     • Location: "Uniflow/Assignments/{{COURSE_CODE}}/"         │
│     • Name: "{{ASSIGNMENT_TITLE}} - {{STUDENT_NAME}} - {{DATE}}"│
│  5. Return: docId, docUrl, driveFileId                         │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

---

## 6. SUBMISSION PACKAGE CREATION

```
┌─────────────────────────────────────────────────────────────────┐
│                    SUBMISSION PACKAGER                          │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  INPUT: Generated files + Google Doc + Requirements            │
│                                                                 │
│  OUTPUT: SubmissionPackage                                      │
│  ─────────────────────────────────────────────────────────────  │
│  {                                                              │
│    assignmentId: "assign_123",                                 │
│    studentId: "user_456",                                      │
│    googleDoc: {                                                │
│      docId: "1abc...",                                         │
│      url: "https://docs.google.com/...",                       │
│      driveFileId: "1xyz..."                                    │
│    },                                                          │
│    additionalFiles: [                                          │
│      { name: "main.py", content: "...", mimeType: "text/x-python" }, │
│      { name: "data.csv", content: "...", mimeType: "text/csv" }      │
│    ],                                                          │
│    metadata: {                                                 │
│      generatedAt: "2026-01-15T10:30:00Z",                      │
│      aiModel: "gpt-4o",                                        │
│      requirementsMet: ["req_1", "req_2", "req_3"],            │
│      confidenceScore: 0.92                                     │
│    },                                                          │
│    submissionTarget: "GOOGLE_CLASSROOM" | "CANVAS" | "PORTAL"  │
│  }                                                              │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

---

## 7. USER APPROVAL WORKFLOW

```
┌─────────────────────────────────────────────────────────────────┐
│                    APPROVAL WORKFLOW                            │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │  NOTIFICATION SENT (Push/Email/In-app)                 │   │
│  │  "New solution ready for: {{ASSIGNMENT_TITLE}}"        │   │
│  │  Due: {{DUE_DATE}} | Confidence: 92%                   │   │
│  └─────────────────────────────────────────────────────────┘   │
│                           │                                     │
│                           ▼                                     │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │  USER REVIEW PAGE (/dashboard/assignments/{{id}}/review)│   │
│  │                                                          │   │
│  │  ┌─────────────────────────────────────────────────┐   │   │
│  │  │  ASSIGNMENT PREVIEW                             │   │   │
│  │  │  • Requirements checklist (✓/✗)                │   │   │
│  │  │  • Generated files preview                     │   │   │
│  │  │  • Google Doc link (editable)                  │   │   │
│  │  │  • AI Confidence score + reasoning             │   │   │
│  │  └─────────────────────────────────────────────────┘   │   │
│  │                                                          │   │
│  │  ┌─────────────────┐  ┌─────────────────┐               │   │
│  │  │  REQUEST CHANGES│  │  APPROVE & SUBMIT│              │   │
│  │  │  (opens chat)   │  │  (manual)        │               │   │
│  │  └─────────────────┘  └─────────────────┘               │   │
│  │                                                          │   │
│  │  ┌─────────────────────────────────────────────────┐   │   │
│  │  │  ⚙️  AUTO-APPROVAL SETTINGS                     │   │   │
│  │  │  [ ] Enable auto-submit when confidence > 90%  │   │   │
│  │  │  [ ] Auto-submit for: [CODE] [WRITING] [MATH]  │   │   │
│  │  │  [ ] Notify me before auto-submit (5 min)      │   │   │
│  │  │  [ ] Only for assignments < 20% of grade       │   │   │
│  │  └─────────────────────────────────────────────────┘   │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

---

## 8. SUBMISSION EXECUTION

```
┌─────────────────────────────────────────────────────────────────┐
│                    SUBMISSION EXECUTOR                          │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  GOOGLE CLASSROOM (GCR) SUBMISSION:                            │
│  ─────────────────────────────────────────────────────────────  │
│  1. Use Classroom API: courses.courseWork.studentSubmissions   │
│  2. Attach Google Doc (driveFileId)                            │
│  3. Attach additional files                                    │
│  4. Call: studentSubmissions.turnIn({ submissionId })          │
│  5. Handle: already submitted, late submission, errors         │
│                                                                 │
│  CANVAS/BLACKBOARD/MOODLE:                                     │
│  ─────────────────────────────────────────────────────────────  │
│  • Use portal-specific scraper (Playwright)                    │
│  • Navigate to assignment submission page                      │
│  • Upload files / paste Google Doc link                        │
│  • Click "Submit" / "Turn In"                                  │
│  • Capture confirmation screenshot                             │
│                                                                 │
│  POST-SUBMISSION:                                              │
│  ─────────────────────────────────────────────────────────────  │
│  • Update AssignmentRecord status: SUBMITTED                   │
│  • Store submission receipt (confirmation ID, timestamp)       │
│  • Notify user: "Submitted successfully!"                      │
│  • Schedule grade check (when grades posted)                   │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

---

## 9. DATA MODELS (Database)

```python
# backend/app/assignments/models.py

class AssignmentRecord(Base):
    __tablename__ = "assignment_records"
    
    id = Column(UUID, primary_key=True)
    user_id = Column(UUID, ForeignKey("users.id"))
    portal_id = Column(UUID, ForeignKey("portals.id"))
    external_id = Column(String)  # LMS assignment ID
    
    # Assignment metadata
    title = Column(String)
    description = Column(Text)
    course_code = Column(String)
    course_name = Column(String)
    due_date = Column(DateTime)
    assigned_date = Column(DateTime)
    
    # Document references
    source_documents = Column(JSON)  # [{url, type, docId, parsedContent}]
    
    # AI Processing
    status = Column(Enum(
        "DETECTED", "PARSING", "ANALYZING", "GENERATING", 
        "REVIEWING", "READY_FOR_APPROVAL", "APPROVED", 
        "SUBMITTED", "GRADED", "FAILED"
    ))
    
    requirements = Column(JSON)  # ExtractedRequirements
    generated_solution = Column(JSON)  # SolutionPackage
    google_doc = Column(JSON)  # {docId, url, driveFileId}
    
    # Approval
    approval_mode = Column(Enum("MANUAL", "AUTO"), default="MANUAL")
    auto_approval_config = Column(JSON)  # User preferences
    approved_at = Column(DateTime)
    approved_by = Column(UUID)  # user_id
    
    # Submission
    submission_target = Column(String)  # GCR, CANVAS, etc.
    submission_receipt = Column(JSON)  # {confirmationId, submittedAt, method}
    submitted_at = Column(DateTime)
    
    # Grading
    grade = Column(Float)
    graded_at = Column(DateTime)
    feedback = Column(Text)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, onupdate=datetime.utcnow)


class UserTemplate(Base):
    __tablename__ = "user_templates"
    
    id = Column(UUID, primary_key=True)
    user_id = Column(UUID, ForeignKey("users.id"), unique=True)
    
    # Google Docs template
    template_doc_id = Column(String)  # User's master template
    template_url = Column(String)
    
    # Placeholder mappings (customizable)
    placeholders = Column(JSON)  # { "STUDENT_NAME": "{{name}}", ... }
    
    # Default settings
    default_font = Column(String, default="Times New Roman")
    default_font_size = Column(Integer, default=12)
    margins = Column(JSON)  # {top, bottom, left, right}
    
    created_at = Column(DateTime)
    updated_at = Column(DateTime)


class AutoApprovalConfig(Base):
    __tablename__ = "auto_approval_configs"
    
    id = Column(UUID, primary_key=True)
    user_id = Column(UUID, ForeignKey("users.id"), unique=True)
    
    enabled = Column(Boolean, default=False)
    min_confidence = Column(Float, default=0.90)  # 90%
    
    # Allowed task types for auto-approval
    allowed_task_types = Column(JSON, default=["CODE", "MATH"])
    
    # Constraints
    max_grade_percentage = Column(Float, default=20.0)  # % of course grade
    notify_before_submit = Column(Boolean, default=True)
    notify_minutes_before = Column(Integer, default=5)
    
    # Exclusions
    excluded_courses = Column(JSON, default=[])
    excluded_keywords = Column(JSON, default=[])  # "final", "thesis", "capstone"
    
    created_at = Column(DateTime)
    updated_at = Column(DateTime)
```

---

## 10. API ENDPOINTS

```python
# backend/app/assignments/router.py

router = APIRouter(prefix="/assignments", tags=["assignments"])

@router.get("/{assignment_id}/status")
async def get_assignment_status(assignment_id: UUID)

@router.get("/{assignment_id}/review")
async def get_review_data(assignment_id: UUID)
# Returns: requirements, generated files, google doc preview, confidence

@router.post("/{assignment_id}/approve")
async def approve_submission(assignment_id: UUID, request: ApproveRequest)
# Request: { mode: "MANUAL" | "AUTO", changes_requested?: string }

@router.post("/{assignment_id}/request-changes")
async def request_changes(assignment_id: UUID, request: ChangesRequest)
# Request: { feedback: string, specific_requirements: string[] }

@router.get("/{assignment_id}/google-doc")
async def get_google_doc(assignment_id: UUID)
# Returns: { docId, url, editableUrl }

@router.put("/{assignment_id}/google-doc")
async def update_google_doc(assignment_id: UUID, request: UpdateDocRequest)
# User can edit the doc before approval

@router.post("/{assignment_id}/submit")
async def manual_submit(assignment_id: UUID)
# Triggers submission executor

@router.get("/{assignment_id}/submission-history")
async def get_submission_history(assignment_id: UUID)

# Auto-approval config
@router.get("/auto-approval/config")
async def get_auto_approval_config()

@router.put("/auto-approval/config")
async def update_auto_approval_config(config: AutoApprovalConfigRequest)
```

---

## 11. FRONTEND COMPONENTS (React/Next.js)

```tsx
// frontend/app/dashboard/assignments/[id]/review/page.tsx

export default function AssignmentReviewPage({ params }: { params: { id: string } }) {
  const { data: review } = useQuery(['assignment-review', params.id]);
  const { data: config } = useQuery(['auto-approval-config']);
  
  return (
    <div className="container mx-auto p-6">
      {/* Header */}
      <div className="mb-6">
        <h1 className="text-2xl font-bold">{review.assignment.title}</h1>
        <div className="flex gap-4 text-sm text-gray-600 mt-2">
          <span>Due: {format(review.assignment.dueDate, 'PPP')}</span>
          <span>Course: {review.assignment.courseCode}</span>
          <ConfidenceBadge score={review.confidenceScore} />
        </div>
      </div>

      {/* Requirements Checklist */}
      <Card className="mb-6">
        <CardHeader>
          <CardTitle>Requirements Checklist</CardTitle>
        </CardHeader>
        <CardContent>
          {review.requirements.map(req => (
            <RequirementRow key={req.id} requirement={req} 
              status={review.generatedSolution.metRequirements.includes(req.id)} />
          ))}
        </CardContent>
      </Card>

      {/* Generated Files Preview */}
      <Card className="mb-6">
        <CardHeader>
          <CardTitle>Generated Files</CardTitle>
        </CardHeader>
        <CardContent>
          <FilePreviewGrid files={review.generatedSolution.files} />
          <GoogleDocPreview doc={review.googleDoc} />
        </CardContent>
      </Card>

      {/* AI Reasoning */}
      <Card className="mb-6">
        <CardHeader>
          <CardTitle>AI Analysis</CardTitle>
        </CardHeader>
        <CardContent>
          <AIReasoningPanel reasoning={review.aiReasoning} />
        </CardContent>
      </Card>

      {/* Approval Actions */}
      <div className="flex gap-4">
        <Button variant="outline" onClick={handleRequestChanges}>
          Request Changes
        </Button>
        <Button onClick={handleApprove} className="flex-1">
          Approve & Submit
        </Button>
      </div>

      {/* Auto-Approval Settings */}
      <AutoApprovalSettings config={config} onUpdate={handleConfigUpdate} />
    </div>
  );
}
```

---

## 12. EVENT FLOW SUMMARY

```
TIMELINE:
────────────────────────────────────────────────────────────────►

[0s]     Assignment published on portal
         │
[5s]     Scheduler detects → Creates AssignmentRecord
         │
[10s]    Document Fetcher downloads all attachments
         │
[30s]    Requirements Extractor (LLM) analyzes docs
         │
[60s]    Solution Generator (Multi-agent) creates solution
         │
[120s]   Google Docs Template Engine creates formatted doc
         │
[130s]   Notification sent to user: "Ready for review"
         │
[User]   User opens review page → Views solution → Decides
         │
[Manual] User clicks "Approve & Submit" → Submits to GCR
[Auto]   If auto-approval enabled + confidence > 90% → Auto-submit
         │
[Done]   Status: SUBMITTED → Receipt stored → Grade monitoring starts
```

---

## 13. CONFIGURATION (User Settings)

```typescript
// User configurable options
interface AutoApprovalConfig {
  enabled: boolean;
  minConfidence: number;        // 0.85 - 0.99
  allowedTaskTypes: TaskType[]; // ['CODE', 'MATH', 'DATA_ANALYSIS']
  maxGradeWeight: number;       // % of course grade (default 20%)
  notifyBeforeSubmit: boolean;
  notifyMinutesBefore: number;  // 1 - 60
  excludedCourses: string[];    // Course codes
  excludedKeywords: string[];   // ['final', 'thesis', 'capstone', 'midterm']
  requireManualFor: {
    groupWork: boolean;
    presentations: boolean;
    peerReview: boolean;
  };
}
```

---

## 14. ERROR HANDLING & RETRY LOGIC

| Stage | Failure Mode | Recovery |
|-------|--------------|----------|
| Document Fetch | Access denied / 404 | Notify user, fallback to manual upload |
| Parsing | Corrupted PDF | OCR fallback (Tesseract) |
| Requirements | LLM hallucination | Confidence threshold, human review flag |
| Generation | Code doesn't run | Auto-test in sandbox, retry with fix |
| Template | Placeholder missing | Use defaults, warn user |
| Submission | Portal down / changed | Queue retry, alert user |
| Approval | User never responds | Auto-expire after 24h (configurable) |

---

## 15. SECURITY & PRIVACY

- **Google OAuth scopes**: `drive.file`, `documents`, `classroom.coursework.students`
- **Data encryption**: Solution content encrypted at rest
- **Audit log**: Every AI generation, user action, submission logged
- **FERPA compliance**: No PII in prompts, user data isolated
- **Rate limits**: Respect portal APIs, exponential backoff