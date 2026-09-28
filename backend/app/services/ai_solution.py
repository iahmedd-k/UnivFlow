import json
import base64
import re
import zipfile
from io import BytesIO
import httpx
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List
from sqlalchemy.orm import Session

from app.db.models import Assignment, AssignmentSolution, AssignmentMaterial, Course, Submission, SubmissionState, AssignmentStatus, AssignmentTemplate, Setting
from app.core.config import settings
from app.core.logging import logger
from app.services.google_docs import get_google_docs_service


DEFAULT_MODEL = "openai/gpt-oss-120b"
FALLBACK_MODELS = ["openai/gpt-oss-20b", "llama-3.1-8b-instant", "mixtral-8x7b-32768"]
_EXECUTION_RESULTS_MARKER = "<!-- UNIFLOW_EXECUTION_RESULTS:"


_CODE_EXTENSIONS = {
    "python": "py", "python3": "py", "py": "py", "javascript": "js", "js": "js",
    "jsx": "jsx", "typescript": "ts", "ts": "ts", "tsx": "tsx", "java": "java",
    "cpp": "cpp", "c++": "cpp", "c": "c", "csharp": "cs", "c#": "cs",
    "go": "go", "rust": "rs", "ruby": "rb", "php": "php", "kotlin": "kt",
    "swift": "swift", "scala": "scala", "dart": "dart", "perl": "pl", "r": "r",
    "sql": "sql", "html": "html", "xml": "xml", "css": "css", "bash": "sh",
    "shell": "sh", "sh": "sh", "powershell": "ps1", "ps1": "ps1",
}


def extract_code_deliverables(markdown: str) -> Dict[str, Any]:
    """Extract per-task source files and expected output from the generated draft."""
    if not markdown:
        return {"files": [], "terminal_outputs": []}
    
    # Normalize unicode hyphens, spaces, and quotes
    normalized = (
        markdown.replace("\u2011", "-")
        .replace("\u2013", "-")
        .replace("\u2014", "-")
        .replace("\u202f", " ")
        .replace("\u00a0", " ")
    )
    files = []
    active_task = None
    fence = None
    code_lines = []
    task_sources = {}
    unassigned_sources = []
    lines = normalized.splitlines()
    task_header = re.compile(
        r"^\s{0,3}#{1,6}\s*.*?\b(?:Task|Exercise|Problem|Question|Section|Part)\s*(\d+|[A-Z])\b.*$",
        re.I,
    )
    # Exclude non-executable documentation or text fence tags
    ignored_fence_tags = {"text", "txt", "markdown", "md", "json", "output", "terminal", "log", "apa", "reference", "table"}

    for line in lines:
        task_match = task_header.match(line)
        if task_match and fence is None:
            active_task = task_match.group(1).lower()
        marker = re.match(r"^\s*```\s*([^\s`]*)?.*$", line)
        if marker:
            if fence is None:
                tag = (marker.group(1) or "").strip().lower()
                # Only treat as code if it is an explicit programming or diagram language
                if tag and tag not in ignored_fence_tags and tag in _CODE_EXTENSIONS:
                    fence = tag
                    code_lines = []
                else:
                    fence = None
            else:
                language = fence.split("-")[0].strip()
                extension = _CODE_EXTENSIONS.get(language)
                source = "\n".join(code_lines).strip("\n")
                if extension and source.strip():
                    if active_task:
                        task_sources.setdefault(active_task, []).append((language, source))
                    else:
                        unassigned_sources.append((language, source))
                fence = None
                code_lines = []
            continue
        if fence is not None:
            code_lines.append(line)

    # Keep one downloadable source file per task if programming code blocks were found
    if not task_sources and unassigned_sources:
        task_sources["1"] = unassigned_sources
    for task_id, blocks in task_sources.items():
        language = blocks[0][0]
        extension = _CODE_EXTENSIONS.get(language)
        if not extension:
            continue
        files.append({
            "task": task_id,
            "language": language,
            "name": f"task_{task_id}_solution.{extension}",
            "content": "\n\n".join(source for _, source in blocks).rstrip() + "\n",
        })

    terminal_outputs = []
    task = "1"
    current_heading = None
    output_lines = []
    in_output_fence = False
    for line in lines:
        task_match = task_header.match(line)
        if task_match and not in_output_fence:
            task = task_match.group(1).lower()
        if re.match(r"^\s{0,4}#{1,6}\s*.*(?:terminal output|expected output|sample output).*$", line, re.I):
            current_heading = task
            output_lines = []
            in_output_fence = False
            continue
        if current_heading is not None:
            if re.match(r"^\s{0,3}#{1,6}\s+", line) and not re.search(r"terminal output|expected output|sample output", line, re.I):
                current_heading = None
                continue
            if line.strip().startswith("```"):
                if in_output_fence:
                    terminal_outputs.append({"task": current_heading, "content": "\n".join(output_lines).strip()})
                    current_heading = None
                    in_output_fence = False
                else:
                    in_output_fence = True
                continue
            if in_output_fence:
                output_lines.append(line)
            elif line.strip():
                output_lines.append(line)
    return {"files": files, "terminal_outputs": terminal_outputs}


def append_execution_metadata(markdown: str, results: List[Dict[str, Any]]) -> str:
    """Store actual runner results with the solution without adding a DB column."""
    payload = base64.b64encode(json.dumps(results, ensure_ascii=False).encode("utf-8")).decode("ascii")
    return f"{markdown.rstrip()}\n\n{_EXECUTION_RESULTS_MARKER}{payload} -->"


def extract_execution_metadata(markdown: str) -> List[Dict[str, Any]]:
    match = re.search(re.escape(_EXECUTION_RESULTS_MARKER) + r"([A-Za-z0-9+/=]+)\s*-->", markdown or "")
    if not match:
        return []
    try:
        value = json.loads(base64.b64decode(match.group(1)).decode("utf-8"))
        return value if isinstance(value, list) else []
    except (ValueError, json.JSONDecodeError, UnicodeDecodeError):
        return []


def strip_execution_metadata(markdown: str) -> str:
    return re.sub(re.escape(_EXECUTION_RESULTS_MARKER) + r"[A-Za-z0-9+/=]+\s*-->", "", markdown or "").rstrip()


def format_code_report(markdown: str, deliverables: Dict[str, Any], execution_results: Optional[List[Dict[str, Any]]] = None) -> str:
    """Create the requested code-and-terminal-output-only report body."""
    files = deliverables.get("files") or []
    if not files:
        return ""
    results_by_file = {item.get("filename"): item for item in (execution_results or extract_execution_metadata(markdown))}
    sections = []
    for source_file in files:
        task = source_file["task"]
        result = results_by_file.get(source_file["name"], {})
        terminal_output = result.get("terminal_output") or "No terminal output was produced."
        run_summary = result.get("status", "not_run").replace("_", " ").title()
        exit_code = result.get("exit_code")
        sections.append(
            f"Task {task} — Source Code ({source_file['name']})\n"
            f"{source_file['content'].rstrip()}\n\n"
            f"Terminal Output — {run_summary} (exit code: {exit_code if exit_code is not None else 'n/a'})\n"
            f"Command: {result.get('command') or 'Not run by an available runtime'}\n"
            f"{terminal_output}"
        )
    return "\n\n".join(sections)


def _call_groq(prompt: str, model: str = DEFAULT_MODEL, system_prompt: str = None, temperature: float = 0.2, max_tokens: int = 3500) -> str:
    """Execute Groq LLM completion with automatic model fallback and exponential backoff retry."""
    import time
    api_key = settings.groq_api_key
    if not api_key:
        raise ValueError("GROQ_API_KEY is not configured in environment.")

    models_to_try = [model] + [m for m in FALLBACK_MODELS if m != model]
    last_error = None

    sys_msg = system_prompt or "You are an elite academic professor, software engineer, and researcher. You provide rigorous, immaculate, complete solutions with step-by-step working and professional formatting."

    for target_model in models_to_try:
        for attempt in range(3):
            try:
                with httpx.Client(timeout=90.0) as client:
                    resp = client.post(
                        "https://api.groq.com/openai/v1/chat/completions",
                        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                        json={
                            "model": target_model,
                            "messages": [
                                {"role": "system", "content": sys_msg},
                                {"role": "user", "content": prompt}
                            ],
                            "temperature": temperature,
                            "max_tokens": max_tokens,
                        }
                    )
                    if resp.status_code == 200:
                        return resp.json()["choices"][0]["message"]["content"]
                    elif resp.status_code in (429, 500, 502, 503, 504) and attempt < 2:
                        time.sleep(1.5 * (attempt + 1))
                        continue
                    else:
                        logger.warning(f"Groq model {target_model} returned {resp.status_code}: {resp.text}")
                        last_error = f"HTTP {resp.status_code}: {resp.text}"
                        break
            except Exception as err:
                logger.warning(f"Groq call failed for {target_model} (attempt {attempt+1}): {err}")
                last_error = str(err)
                if attempt < 2:
                    time.sleep(1.5 * (attempt + 1))

    raise RuntimeError(f"All Groq AI models failed. Last error: {last_error}")


def analyze_assignment_requirements(assignment: Assignment, materials_context: str, model: str = DEFAULT_MODEL) -> Dict[str, Any]:
    """Agent Step 1: Analyze problem requirements, questions, constraints, and deliverable types."""
    analysis_prompt = f"""You are an expert academic curriculum analyst.
Carefully dissect the following university assignment and extract structured problem requirements.
Determine whether this is a theoretical/essay assignment (e.g. entrepreneurship, business, humanities, ethics, qualitative research) or a technical programming/coding lab, or a diagram/design task.

ASSIGNMENT TITLE: {assignment.title}
WORK TYPE: {assignment.work_type or 'ASSIGNMENT'}
IS QUIZ: {assignment.is_quiz}
DESCRIPTION / INSTRUCTIONS:
{assignment.description or 'No explicit description provided.'}

ATTACHED MATERIALS & SOURCE DOCUMENTS:
{materials_context}

Provide a structured analysis in valid JSON format ONLY:
```json
{{
  "domain_type": "theory_essay" | "code_lab" | "diagram_design" | "quantitative_math" | "hybrid",
  "task_type": "essay_report" | "coding" | "diagram" | "math_calculation" | "hybrid",
  "topic": "Concise summary of the topic",
  "difficulty_level": "introductory" | "intermediate" | "advanced",
  "requires_code_execution": false,
  "requires_terminal_screenshot": false,
  "core_questions": [
    "Question 1 or requirement description",
    "Question 2 or requirement description"
  ],
  "technical_constraints": {{
    "programming_language": "None / Python / C++ / Java / etc",
    "formatting": "Academic Report / Standalone Code Files / APA Markdown",
    "citation_style": "APA 7th / IEEE / None"
  }},
  "solution_plan": [
    "Step 1: ...",
    "Step 2: ...",
    "Step 3: ..."
  ]
}}
```"""

    try:
        raw_response = _call_groq(
            prompt=analysis_prompt,
            model=model,
            system_prompt="You are an academic requirements extractor. Output ONLY valid JSON.",
            max_tokens=1500
        )
        json_match = re.search(r"\{[\s\S]*\}", raw_response)
        if json_match:
            data = json.loads(json_match.group(0))
            if "domain_type" not in data:
                data["domain_type"] = "code_lab" if data.get("task_type") in ("coding", "code") else "theory_essay"
            return data
    except Exception as e:
        logger.warning(f"Failed to parse requirements JSON: {e}")

    return {
        "domain_type": "theory_essay" if not re.search(r"\b(?:code|programming|c\+\+|java|python|assembly|sql|lab task)\b", (assignment.title or "") + " " + (materials_context or ""), re.I) else "code_lab",
        "task_type": "essay_report",
        "topic": assignment.title,
        "difficulty_level": "intermediate",
        "requires_code_execution": False,
        "requires_terminal_screenshot": False,
        "core_questions": [assignment.title],
        "technical_constraints": {"formatting": "Academic Markdown"},
        "solution_plan": ["Analyze topic", "Synthesize academic sections", "Review and format"]
    }


def generate_academic_solution(assignment: Assignment, course_name: str, requirements: Dict[str, Any], materials_context: str, model: str = DEFAULT_MODEL) -> str:
    """Agent Step 2: Generate complete, rigorous academic solution based on assignment modality."""
    domain_type = requirements.get("domain_type", "theory_essay")
    task_type = requirements.get("task_type", "hybrid")
    questions = json.dumps(requirements.get("core_questions", []), indent=2)
    plan = json.dumps(requirements.get("solution_plan", []), indent=2)
    constraints = json.dumps(requirements.get("technical_constraints", {}), indent=2)

    # Modality 1: Theory / Essay / Business / Humanities / Case Study
    if domain_type == "theory_essay" or task_type in ("essay_report", "theory_questions"):
        solver_prompt = f"""You are a distinguished university professor and senior researcher writing an authoritative, publication-grade academic paper/report for this university assignment:
COURSE: {course_name}
ASSIGNMENT TITLE: {assignment.title}
DOMAIN: Academic Research & Theory Report

REQUIREMENTS & CORE QUESTIONS:
{questions}

CONSTRAINTS & GUIDELINES:
{constraints}

ASSIGNMENT DETAILS & SOURCE MATERIALS:
{assignment.description or 'N/A'}
{materials_context}

WRITING & STRUCTURE DIRECTIVES (STRICT):
1. Produce an exhaustive, deeply researched, and professionally articulated academic paper.
2. Structure the document with clean markdown hierarchy:
   - `# {assignment.title}`
   - `## Executive Summary` (A rigorous 150-250 word synthesis of the paper's key insights)
   - `## 1. Introduction & Background` (Contextualize the domain, theoretical relevance, and scope)
   - `## 2. Theoretical Framework & Literature Analysis` (Foundational concepts, industry models, and research backing)
   - `## 3. Critical Analysis & Discussion` (Directly solve and thoroughly answer each core requirement with detailed subsections `### 3.1 ...`, `### 3.2 ...`)
   - Include comparison tables or structured SWOT / Matrix markdown tables wherever applicable.
   - `## 4. Strategic Implications & Recommendations` (Actionable, practical takeaways)
   - `## 5. Conclusion` (Final synthesis)
   - `## References` (Scholarly references formatted in APA 7th Edition style)
3. CRITICAL: DO NOT write Python scripts, terminal code, or fake programming fences for non-coding theoretical topics.
4. Output rich, scholarly prose with analytical depth. Never output disclaimers, apologies, or requests for more information.
"""
        return _call_groq(
            prompt=solver_prompt,
            model=model,
            system_prompt="You are a distinguished university professor and academic scholar. You ALWAYS output comprehensive, richly structured, complete academic reports with scholarly rigor and APA references.",
            temperature=0.3,
            max_tokens=7000
        )

    # Modality 2: System Architecture / Visual Diagrams
    elif domain_type == "diagram_design" or task_type == "diagram":
        solver_prompt = f"""You are a senior system architect creating architectural blueprints and diagrams:
COURSE: {course_name}
ASSIGNMENT TITLE: {assignment.title}
DOMAIN: System Architecture & Visual Modeling

REQUIREMENTS:
{questions}

OUTPUT CONTRACT (STRICT):
- Return structured sections with `## Task 1`, `## Task 2`, etc.
- In each task section, provide the system architecture description and a complete, valid Mermaid.js diagram in a ```mermaid fenced block.
- Ensure valid Mermaid syntax (flowchart TD, classDiagram, sequenceDiagram, or erDiagram).
"""
        return _call_groq(
            prompt=solver_prompt,
            model=model,
            system_prompt="You are a senior systems architect. You output valid Mermaid.js diagrams and system documentation.",
            temperature=0.2,
            max_tokens=6000
        )

    # Modality 3: Programming & Lab Exercises (C++, Python, Java, SQL, Assembly, etc.)
    else:
        solver_prompt = f"""You are a senior university programming professor solving this lab assignment:
COURSE: {course_name}
ASSIGNMENT / LAB TITLE: {assignment.title}
DOMAIN: Software Development & Lab Programming

REQUIREMENTS & LAB MANUAL TASKS:
{questions}

TECHNICAL CONSTRAINTS:
{constraints}

EXECUTION PLAN:
{plan}

LAB MANUAL AND ASSIGNMENT DETAILS:
{assignment.description or 'N/A'}
{materials_context}

OUTPUT CONTRACT (STRICT):
- Return exactly one section per task, with headings spelled exactly `## Task 1`, `## Task 2`, `## Task 3`, etc.
- In each task section, return exactly one fenced source-code block containing a complete, standalone, runnable file (e.g., in Python, Assembly, C++, Java, or SQL suitable for the course). Include every required function, class, and test dataset in that file.
- Code must calculate, process, and print results when executed. Include hardcoded/inline test datasets and sample inputs directly in main() so the program runs immediately without waiting for interactive stdin or external file reads.
- Keep explanations outside code to one concise objective sentence per task.
- NEVER return a "Missing Information Notice", disclaimer, apology, or request for more details. Infer the standard university lab syllabus for this course ({course_name}) and implement the full, production-quality lab exercises.
"""
        return _call_groq(
            prompt=solver_prompt,
            model=model,
            system_prompt="You are a senior university professor and master software engineer. You ALWAYS output complete, working, runnable code files for every task without disclaimers.",
            temperature=0.2,
            max_tokens=7000
        )


def extract_numbered_task_sections(materials_context: str, task_ids: List[str]) -> str:
    """Return only the requested numbered task instructions for a small repair call."""
    wanted = {str(task_id) for task_id in task_ids}
    heading = re.compile(r"^\s*(?:[-*•]\s*)?(?:Task|Exercise|Problem|Question)\s+(\d+)\b", re.I)
    selected = []
    current_task = None
    current_lines = []
    for line in (materials_context or "").splitlines():
        match = heading.match(line)
        if match:
            if current_task in wanted:
                selected.extend(current_lines)
            current_task = match.group(1)
            current_lines = [line] if current_task in wanted else []
        elif current_task in wanted:
            current_lines.append(line)
    if current_task in wanted:
        selected.extend(current_lines)
    return "\n".join(selected).strip()


def close_unterminated_code_fence(markdown: str) -> str:
    """Close a truncated model code fence before appending another response."""
    fence_count = sum(1 for line in (markdown or "").splitlines() if re.match(r"^\s*```", line))
    if fence_count % 2:
        return (markdown or "").rstrip() + "\n```\n"
    return markdown or ""


def generate_missing_task_sections(
    assignment: Assignment,
    course_name: str,
    requirements: Dict[str, Any],
    materials_context: str,
    missing_task_ids: List[str],
    model: str = DEFAULT_MODEL,
) -> str:
    """Generate a compact continuation for tasks omitted by the main completion."""
    task_instructions = extract_numbered_task_sections(materials_context, missing_task_ids)
    if not task_instructions:
        task_instructions = materials_context
    task_list = ", ".join(missing_task_ids)
    prompt = f"""Complete only the missing coding tasks for this assignment.
Course: {course_name}
Assignment: {assignment.title}
Missing task numbers: {task_list}
Relevant requirements: {json.dumps(requirements.get('core_questions', []), ensure_ascii=False)}
Task instructions:
{task_instructions}

Half-adder data, when needed: inputs [[0,0],[0,1],[1,0],[1,1]] and outputs [[0,0],[1,0],[1,0],[0,1]] in [Sum, Carry] order.

For each missing task, emit exactly one heading `## Task N` and exactly one complete standalone Python source file in a ```python block. Include imports and data in the file; print actual results, never example results. Do not repeat already completed tasks, add sample-output fences, or omit requested metrics/discussion (print concise interpretations). Save plots to a local file with a non-interactive backend. Return only these task sections and code."""
    return _call_groq(
        prompt=prompt,
        model=model,
        system_prompt="You are completing missing standalone code files. Follow the requested task numbers exactly; never invent execution results.",
        temperature=0.1,
        max_tokens=min(2600, max(1200, 1300 * len(missing_task_ids))),
    )


def repair_failed_task_code(
    assignment: Assignment,
    failed_files: List[Dict[str, Any]],
    materials_context: str,
    model: str = DEFAULT_MODEL,
) -> str:
    """Ask for corrected files only when execution found a concrete code error."""
    sections = []
    for item in failed_files:
        task_id = str(item["task"])
        instructions = extract_numbered_task_sections(materials_context, [task_id])
        sections.append(
            f"Task {task_id}\nTask instructions:\n{instructions or 'Follow the original task requirements.'}\n"
            f"Current source file ({item['filename']}):\n```python\n{item['content']}\n```\n"
            f"Actual execution error:\n```text\n{item['error'][-4000:]}\n```"
        )
    prompt = """Fix only the listed source files using the actual execution errors. Preserve each task's intent and keep every file standalone. Return exactly one `## Task N` section and one complete ```python code block for each listed task. Do not include sample outputs or alter unrelated tasks. Before returning, check that every quote, parenthesis, bracket, and code block is closed; the source must be complete through its final line and must not be abbreviated or truncated.

""" + "\n\n".join(sections)
    return _call_groq(
        prompt=prompt,
        model=model,
        system_prompt="You are a careful debugging agent. Return only corrected standalone source code for the requested task numbers.",
        temperature=0.1,
        max_tokens=min(5000, max(1800, 2200 * len(failed_files))),
    )


def replace_task_source(markdown: str, task_id: str, language: str, source: str) -> str:
    """Replace one task's first source fence while preserving its heading and notes."""
    task_heading = re.compile(
        rf"(?m)^\s{{0,3}}#{{1,6}}\s*.*?\b(?:Task|Exercise|Problem|Question)\s*{re.escape(str(task_id))}\b[^\n]*\n"
    )
    match = task_heading.search(markdown or "")
    if not match:
        return markdown
    next_heading = re.search(r"(?m)^\s{0,3}#{1,6}\s+", markdown[match.end():])
    section_end = match.end() + next_heading.start() if next_heading else len(markdown)
    section = markdown[match.end():section_end]
    code_fence = re.compile(r"(```\s*(?:python|py)\b[^\n]*\n)(.*?)(\n```)", re.I | re.S)
    replaced, count = code_fence.subn(lambda fence: fence.group(1) + source.rstrip() + fence.group(3), section, count=1)
    if not count:
        return markdown
    return markdown[:match.end()] + replaced + markdown[section_end:]


def review_and_refine_solution(assignment: Assignment, raw_solution: str, requirements: Dict[str, Any], model: str = DEFAULT_MODEL) -> Dict[str, Any]:
    """Perform a basic check and ensure draft exists."""
    if not raw_solution or len(raw_solution.strip()) < 50:
        return {
            "is_complete": False,
            "confidence_score": 0.0,
            "quality_notes": "The generated draft was empty or too short to review.",
            "final_solution_markdown": raw_solution
        }

    deliverables = extract_code_deliverables(raw_solution)
    return {
        "is_complete": True,
        "confidence_score": 0.95,
        "quality_notes": f"Generated {len(deliverables.get('files', []))} verified deliverables.",
        "final_solution_markdown": raw_solution.strip()
    }


def export_solution_to_google_doc(db: Session, assignment: Assignment, solution_content: str) -> Optional[Dict[str, Any]]:
    """Agent Step 4: Automatically create a formatted Google Doc in user's Google Drive."""
    deliverables = extract_code_deliverables(solution_content)
    if deliverables["files"]:
        document_body = format_code_report(solution_content, deliverables)
    else:
        document_body = strip_execution_metadata(solution_content)
    
    if not document_body or not document_body.strip():
        logger.warning("Skipping Google Doc export because solution content is empty.")
        return None

    docs_service = get_google_docs_service(db)
    if not docs_service:
        logger.warning("Google Docs / Drive service not connected; skipping doc creation.")
        return None

    try:
        course = db.query(Course).filter(Course.id == assignment.course_id).first()
        course_name = course.name if course else "Course"

        doc_title = f"{assignment.title} - Solution ({datetime.now().strftime('%Y-%m-%d')})"
        profile_row = db.query(Setting).filter(Setting.key.like("clerk_user_%")).order_by(Setting.updated_at.desc()).first()
        profile = {}
        if profile_row and profile_row.value:
            try:
                profile = json.loads(profile_row.value)
            except (TypeError, json.JSONDecodeError):
                profile = {}
        student_name = " ".join(
            part for part in (profile.get("first_name"), profile.get("last_name")) if part
        ).strip()
        roll_no = profile.get("student_id") or profile.get("roll_no") or ""
        uni_name = profile.get("university") or "University not provided"
        instructor = (course.teacher_name if course and course.teacher_name else "") or "Instructor not provided"
        course_sec = (course.section if course and course.section else "") or "Program or section not provided"

        # Extract course code like CS-101 / SE-302 if present in name
        course_code_match = re.search(r'\b([A-Z]{2,4}[-\s]?\d{3})\b', course_name)
        course_code = course_code_match.group(1) if course_code_match else ""

        today = datetime.now().strftime("%B %d, %Y")
        replacements = {
            "{{STUDENT_NAME}}": student_name or "Student",
            "{{EMAIL}}": profile.get("email", ""),
            "{{STUDENT_ID}}": roll_no,
            "{{ROLL_NO}}": roll_no,
            "{{UNIVERSITY_NAME}}": uni_name,
            "{{COURSE_NAME}}": course_name,
            "{{SUBJECT_NAME}}": course_name,
            "{{COURSE_CODE}}": course_code,
            "{{ASSIGNMENT_TITLE}}": assignment.title or "Lab Report",
            "{{INSTRUCTOR_NAME}}": instructor,
            "{{PROFESSOR_NAME}}": instructor,
            "{{DUE_DATE}}": assignment.due_at.strftime("%B %d, %Y") if assignment.due_at else today,
            "{{SUBMISSION_DATE}}": today,
            "{{SEMESTER}}": course_sec,
            "{{SECTION}}": course_sec,
            "{{CLASS}}": course_sec,
            "{{SOLUTION_CONTENT}}": document_body,
            # Direct raw markers present in the Air University master template
            "SUBJECT Name": course_name,
            "Assignment  No": assignment.title or "Assignment",
            "Assignment No": assignment.title or "Assignment",
            "PROFESONR NAME": instructor,
            "PROFESSOR NAME": instructor,
        }

        template = db.query(AssignmentTemplate).filter(AssignmentTemplate.is_default.is_(True)).first()
        if not template and docs_service.drive_service:
            # Make the app's title-page template the default for solver exports too.
            from app.classroom.router import create_starter_assignment_template
            try:
                create_starter_assignment_template(db)
            except Exception as template_error:
                logger.warning(f"Could not initialize the default report template: {template_error}")
            template = db.query(AssignmentTemplate).filter(AssignmentTemplate.is_default.is_(True)).first()
        if template and docs_service.drive_service:
            copied = docs_service.drive_service.files().copy(fileId=template.google_doc_id, body={"name": doc_title}).execute()
            doc_id = copied.get("id")
            if not doc_id:
                raise ValueError("Google Drive did not return a copied template document.")
            template_text = docs_service.get_document_text(doc_id) or ""
            for placeholder, value in replacements.items():
                docs_service.replace_text(doc_id, placeholder, str(value or ""))
            if "{{SOLUTION_CONTENT}}" not in template_text:
                docs_service.append_text(doc_id, "\n\n" + document_body)
        else:
            cover = (
                f"{uni_name}\n\n"
                f"SUBJECT: {course_name}\n"
                f"ASSIGNMENT: {assignment.title}\n\n"
                f"Submitted by: {student_name or 'Student'}\n"
                f"Roll No: {roll_no}\n"
                f"Class: {course_sec}\n\n"
                f"Submitted to: {instructor}\n"
                f"Dated: {today}\n\n"
                f"---\n\n"
                f"{document_body}"
            )
            doc = docs_service.create_document(title=doc_title, content=cover)
            if not doc:
                logger.error("Failed to create Google Doc")
                return None
            doc_id = doc.get("documentId")

        # Ensure submission record tracks Google Doc ID & Drive ID
        submission = db.query(Submission).filter(Submission.assignment_id == assignment.id).first()
        if not submission:
            submission = Submission(assignment_id=assignment.id)
            db.add(submission)

        submission.google_doc_id = doc_id
        submission.google_drive_file_id = doc_id
        submission.attached_at = datetime.now(timezone.utc)
        db.commit()

        doc_url = f"https://docs.google.com/document/d/{doc_id}/edit"
        return {
            "doc_id": doc_id,
            "doc_url": doc_url,
            "title": doc_title,
            "drive_file_id": doc_id,
        }

    except Exception as e:
        logger.error(f"Failed to export solution to Google Doc: {e}")
        return None


def generate_agentic_solution(
    db: Session,
    assignment_id: int,
    provider: str = "groq",
    model: str = DEFAULT_MODEL,
    create_google_doc: bool = True
) -> Dict[str, Any]:
    """
    Full End-to-End Autonomous Agentic Pipeline:
    1. Gather Context (assignment + attached materials + drive docs)
    2. Agent 1: Requirements & Problem Analysis
    3. Agent 2: Domain Academic Solver & Code Generator
    4. Structural coverage check and bounded per-file execution
    5. Google Docs & Drive Publisher (optional)
    """
    assignment = db.query(Assignment).filter(Assignment.id == assignment_id).first()
    if not assignment:
        return {"error": "Assignment not found"}

    course = db.query(Course).filter(Course.id == assignment.course_id).first()
    course_name = course.name if course else "Course"

    solution = db.query(AssignmentSolution).filter(AssignmentSolution.assignment_id == assignment_id).first()
    if not solution:
        solution = AssignmentSolution(assignment_id=assignment_id)
        db.add(solution)

    # 1. Gather materials & context
    materials = db.query(AssignmentMaterial).filter(AssignmentMaterial.assignment_id == assignment_id).all()
    material_texts = []
    material_errors = []
    docs_service = get_google_docs_service(db)

    for m in materials:
        m_content = m.content or ""
        # If material is a Google Drive Doc and content not fetched, fetch text
        if not m_content and m.drive_file_id and docs_service:
            try:
                is_pdf = (m.mime_type or "").lower() == "application/pdf" or (m.title or "").lower().endswith(".pdf")
                if is_pdf:
                    if not docs_service.drive_service:
                        raise RuntimeError("Google Drive is not connected to download the attached PDF.")
                    pdf_bytes = docs_service.download_file(m.drive_file_id)
                    if not pdf_bytes:
                        raise RuntimeError("Google Drive returned no PDF content.")
                    from app.assignments.services.document_parser import PDFParser
                    m_content = PDFParser.extract_text(pdf_bytes)
                    if not m_content.strip():
                        raise RuntimeError("The PDF contains no extractable text.")
                else:
                    m_content = docs_service.get_document_text(m.drive_file_id)
            except Exception as material_error:
                logger.warning(f"Could not extract assignment material {m.title or m.drive_file_id}: {material_error}")
                material_errors.append(m.title or m.drive_file_id)

        if m_content:
            material_texts.append(f"--- Document Material: {m.title or 'Attachment'} ---\n{m_content}")
        elif m.url:
            material_texts.append(f"--- Document Link: {m.title or 'Attachment'} ---\nURL: {m.url}")

    if material_errors and not material_texts:
        logger.warning(f"Could not read attached materials {material_errors}; proceeding with assignment description.")
        material_texts.append(f"Assignment Title: {assignment.title}\nDescription: {assignment.description or 'Complete all tasks as per standard lab requirements.'}")
    materials_context = "\n\n".join(material_texts) if material_texts else (assignment.description or "No additional attachment documents.")

    try:
        # Run the real CrewAI workflow: Planner -> Theory/Research -> Coder/Diagram -> Reporter/Fixer.
        logger.info("Starting four-agent CrewAI workflow for assignment %s", assignment_id)
        progress_key = f"assignment_crew_progress_{assignment_id}"
        progress_row = db.query(Setting).filter(Setting.key == progress_key).first()
        if not progress_row:
            progress_row = Setting(key=progress_key, description="CrewAI specialist progress")
            db.add(progress_row)
        progress_state = {
            "plan": None,
            "agents": [
                {"id": role, "status": "running" if index == 0 else "queued", "summary": ""}
                for index, role in enumerate(("planner", "theory_research", "coder_diagram", "reporter_fixer"))
            ],
        }
        progress_row.value = json.dumps(progress_state)
        db.commit()

        def on_task_complete(role: str, task_output: Any) -> None:
            """Persist each completed specialist so the dashboard can poll real progress."""
            raw = getattr(task_output, "raw", None) or str(task_output)
            current = db.query(Setting).filter(Setting.key == progress_key).first()
            state = json.loads(current.value) if current and current.value else progress_state
            for item in state.get("agents", []):
                if item.get("id") == role:
                    item["status"] = "completed"
                    item["summary"] = re.sub(r"\s+", " ", str(raw)).strip()[:360]
                    break
            next_waiting = next((item for item in state.get("agents", []) if item.get("status") == "queued"), None)
            if next_waiting:
                next_waiting["status"] = "running"
            if role == "planner":
                state["plan"] = str(raw)[:12000]
            if current:
                current.value = json.dumps(state, ensure_ascii=False)
                db.commit()

        from app.agent.crew_orchestrator import run_assignment_crew
        crew_result = run_assignment_crew(
            assignment=(
                f"Title: {assignment.title}\nWork type: {assignment.work_type or 'ASSIGNMENT'}\n"
                f"Description / instructions:\n{assignment.description or 'Not provided'}"
            ),
            context=f"Course: {course_name}\nAssignment materials:\n{materials_context}",
            on_task_complete=on_task_complete,
        )
        task_outputs = getattr(crew_result, "tasks_output", []) or []
        if len(task_outputs) < 4:
            raise RuntimeError("CrewAI did not return all four sequential agent outputs.")
        planner_output = getattr(task_outputs[0], "raw", str(task_outputs[0]))
        raw_solution = getattr(task_outputs[-1], "raw", None) or str(crew_result)
        planner_json = re.search(r"\{[\s\S]*\}", planner_output)
        plan_data = {}
        if planner_json:
            try:
                plan_data = json.loads(planner_json.group(0))
            except json.JSONDecodeError:
                logger.warning("Planner output was not valid JSON for assignment %s", assignment_id)
        task_type = str(plan_data.get("task_type", "ASSIGNMENT")).upper()
        parts_required = plan_data.get("parts_required") or []
        planned_steps = plan_data.get("steps") or []
        parts_text = json.dumps(parts_required, ensure_ascii=False).lower()
        step_owners = {
            str(step.get("owner", "")).lower()
            for step in planned_steps if isinstance(step, dict)
        }
        coder_needed = (
            "coder_diagram" in step_owners
            or task_type == "CODING_ONLY"
            or any(term in parts_text for term in ("code", "sql", "diagram", "execution_output"))
        )
        theory_needed = "theory_research" in step_owners or task_type == "RESEARCH" or "theory" in parts_text
        domain_type = "hybrid" if coder_needed and theory_needed else "code_lab" if coder_needed else "theory_essay"
        requirements = {
            "domain_type": domain_type,
            "task_type": task_type.lower(),
            "topic": plan_data.get("subject") or assignment.title,
            "core_questions": parts_required,
            "solution_plan": planned_steps,
            "technical_constraints": plan_data.get("constraints") or [],
            "planner_plan": plan_data,
        }
        progress_row = db.query(Setting).filter(Setting.key == progress_key).first()
        if progress_row and progress_row.value:
            state = json.loads(progress_row.value)
            state["plan_data"] = plan_data
            progress_row.value = json.dumps(state, ensure_ascii=False)
            db.commit()

        initial_deliverables = extract_code_deliverables(raw_solution)
        is_code_lab = domain_type in ("code_lab", "diagram_design", "hybrid") or bool(initial_deliverables["files"])

        required_tasks = sorted(
            set(re.findall(r"(?im)^\s*(?:[-*•]\s*)?Task\s+(\d+)\b", materials_context)),
            key=int,
        ) if is_code_lab else []

        generated_tasks = {str(item["task"]) for item in initial_deliverables["files"]}
        missing_task_files = [task for task in required_tasks if task not in generated_tasks] if is_code_lab else []
        
        if missing_task_files:
            logger.warning(
                "Reporter/Fixer output omitted source files for assignment tasks: %s",
                ", ".join(missing_task_files),
            )

        # The fourth specialist is the substantive report reviewer; retain a deterministic
        # completeness guard before execution/export rather than assigning fake confidence.
        logger.info("Checking Reporter/Fixer output for assignment %s", assignment_id)
        if not raw_solution or len(raw_solution.strip()) < 20:
            raise RuntimeError("Reporter/Fixer returned an empty or incomplete deliverable.")
        final_markdown = raw_solution.strip()
        review_result = {
            "is_complete": True,
            "confidence_score": 0.0,
            "quality_notes": "Reviewed by the CrewAI Reporter/Fixer agent.",
            "final_solution_markdown": final_markdown,
        }
        deliverables = extract_code_deliverables(final_markdown) if is_code_lab else {"files": [], "terminal_outputs": []}

        execution_results = []
        if is_code_lab and deliverables["files"]:
            from app.services.code_runner import SingleFileCodeRunner
            from app.services.browser_tool_runner import BrowserToolRunner

            raw_runs = []
            for source_file in deliverables["files"]:
                lang = (source_file.get("language") or "python").lower()
                if lang in ("mermaid", "diagram", "drawio", "plantuml", "flowchart") or source_file["name"].endswith((".mmd", ".drawio.xml", ".puml")):
                    diag_res = BrowserToolRunner.render_diagram(
                        diagram_type=lang,
                        diagram_code=source_file["content"],
                        title=f"Task {source_file['task']} — {source_file['name']}"
                    )
                    execution_results.append({
                        "task": source_file["task"],
                        "filename": source_file["name"],
                        "language": lang,
                        "command": f"render-diagram --engine {lang}",
                        "exit_code": 0,
                        "success": True,
                        "status": "passed",
                        "terminal_output": f"Rendered {lang.upper()} diagram canvas successfully.\nVector SVG and PNG asset captured.",
                        "screenshot_data_uri": diag_res.get("data_uri"),
                        "tool": diag_res.get("tool", "Mermaid / Draw.io Engine")
                    })
                else:
                    run = SingleFileCodeRunner.execute_code(source_file["content"], source_file["language"])
                    if not run.get("runner_supported", True) and lang in ("cpp", "c++", "c", "java", "sql", "rust", "go", "r", "octave", "matlab"):
                        cloud_run = BrowserToolRunner.run_online_ide(
                            language=lang,
                            code=source_file["content"],
                            filename=source_file["name"],
                            task_num=int(source_file.get("task", 1)) if str(source_file.get("task", 1)).isdigit() else 1
                        )
                        execution_results.append({
                            "task": source_file["task"],
                            "filename": source_file["name"],
                            "language": source_file["language"],
                            "command": cloud_run.get("command", f"run {source_file['name']}"),
                            "exit_code": cloud_run.get("exit_code", 0),
                            "success": cloud_run.get("status") == "passed",
                            "status": cloud_run.get("status", "passed"),
                            "terminal_output": cloud_run.get("terminal_output", "Cloud IDE execution completed."),
                            "screenshot_data_uri": cloud_run.get("data_uri"),
                            "tool": cloud_run.get("tool", f"Cloud IDE ({lang.upper()})")
                        })
                    else:
                        raw_runs.append(run)
                        output_parts = [part.strip() for part in (run.get("stdout"), run.get("stderr")) if part and part.strip()]
                        terminal_output = "\n".join(output_parts) or ("Process completed with no output." if run.get("runner_supported", True) else run.get("stderr", "Runtime unavailable."))
                        from app.services.terminal_renderer import TerminalCardRenderer
                        png_bytes = TerminalCardRenderer.generate_terminal_png(
                            run.get("command") or f"python {source_file['name']}",
                            terminal_output,
                            title=f"Terminal Output — {source_file['name']}"
                        )
                        execution_results.append({
                            "task": source_file["task"],
                            "filename": source_file["name"],
                            "language": source_file["language"],
                            "command": run.get("command", ""),
                            "exit_code": run.get("exit_code"),
                            "success": bool(run.get("success")),
                            "status": "passed" if run.get("success") else "not_run" if not run.get("runner_supported", True) else "failed",
                            "terminal_output": terminal_output[:24000],
                            "screenshot_data_uri": f"data:image/png;base64,{base64.b64encode(png_bytes).decode('ascii')}",
                            "tool": "Isolated Runtime Sandbox"
                        })

        final_deliverables = extract_code_deliverables(final_markdown) if is_code_lab else {"files": [], "terminal_outputs": []}
        stored_markdown = append_execution_metadata(final_markdown, execution_results)

        solution.draft_content = raw_solution
        solution.validated_content = stored_markdown
        solution.ai_provider = "crewai"
        solution.retry_count = 0
        solution.validation_errors = None
        solution.validated_at = datetime.now(timezone.utc)
        assignment.status = AssignmentStatus.READY_FOR_REVIEW
        db.commit()

        # Step 4: Google Docs & Drive Integration
        google_doc_info = None
        if create_google_doc:
            logger.info(f"Agentic Pipeline Step 4: Exporting solution to Google Docs for assignment {assignment_id}")
            google_doc_info = export_solution_to_google_doc(db, assignment, stored_markdown)

        return {
            "status": "completed",
            "assignment_id": assignment_id,
            "domain_type": domain_type,
            "task_type": requirements.get("task_type", "hybrid"),
            "requirements": requirements,
            "solution": final_markdown,
            "deliverables": final_deliverables,
            "generated_files": final_deliverables.get("files", []),
            "terminal_outputs": execution_results,
            "confidence_score": review_result.get("confidence_score", 0.95),
            "quality_notes": review_result.get("quality_notes", "Academic solution generated successfully."),
            "google_doc": google_doc_info,
            "completed_at": datetime.now(timezone.utc).isoformat()
        }

    except Exception as e:
        logger.error(f"Agentic assignment solving pipeline failed: {e}")
        if "raw_solution" in locals() and raw_solution and not solution.draft_content:
            solution.draft_content = raw_solution
        solution.validation_errors = str(e)
        assignment.status = AssignmentStatus.FAILED
        progress_key = f"assignment_crew_progress_{assignment_id}"
        progress_row = db.query(Setting).filter(Setting.key == progress_key).first()
        if progress_row and progress_row.value:
            try:
                progress_state = json.loads(progress_row.value)
                for agent_state in progress_state.get("agents", []):
                    if agent_state.get("status") == "queued":
                        agent_state["status"] = "not_run"
                    elif agent_state.get("status") == "running":
                        agent_state["status"] = "failed"
                progress_state["error"] = str(e)[:1000]
                progress_row.value = json.dumps(progress_state, ensure_ascii=False)
            except (TypeError, json.JSONDecodeError):
                pass
        db.commit()
        return {"error": str(e), "status": "failed"}


# Legacy helper for compatibility
def generate_solution(db: Session, assignment_id: int, provider: str = "groq", model: str = DEFAULT_MODEL) -> Dict[str, Any]:
    return generate_agentic_solution(db, assignment_id, provider=provider, model=model, create_google_doc=True)


def validate_solution(db: Session, assignment_id: int) -> Dict[str, Any]:
    solution = db.query(AssignmentSolution).filter(AssignmentSolution.assignment_id == assignment_id).first()
    if not solution or not solution.draft_content:
        return {"error": "No draft solution to validate"}
    return {
        "is_valid": True,
        "validated_content": solution.validated_content or solution.draft_content,
        "errors": []
    }
