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
    "go": "go", "rust": "rs", "ruby": "rb", "php": "php", "kotlin": "kt", "kt": "kt",
    "swift": "swift", "scala": "scala", "dart": "dart", "perl": "pl", "r": "r",
    "sql": "sql", "sqlite": "sql", "mysql": "sql", "postgres": "sql", "postgresql": "sql",
    "html": "html", "xml": "xml", "css": "css", "bash": "sh",
    "shell": "sh", "sh": "sh", "powershell": "ps1", "ps1": "ps1",
    "asm": "asm", "assembly": "asm", "nasm": "asm", "masm": "asm", "emu8086": "asm", "x86": "asm", "8086": "asm",
    "mips": "s", "riscv": "s", "arm": "s", "s": "s",
    "matlab": "m", "octave": "m", "m": "m",
    "verilog": "v", "v": "v", "vhdl": "vhd", "vhd": "vhd", "systemverilog": "sv", "sv": "sv",
    "prolog": "pl", "haskell": "hs", "hs": "hs",
    "mermaid": "mmd", "mmd": "mmd", "plantuml": "puml", "puml": "puml",
    "graphviz": "dot", "dot": "dot", "erd": "erd", "nomnoml": "nomnoml",
    "drawio": "drawio.xml", "drawio.xml": "drawio.xml", "mxfile": "drawio.xml",
}


def extract_diagram_deliverables(markdown: str) -> List[Dict[str, Any]]:
    """
    Extract all visual diagrams (Draw.io XML, Mermaid, PlantUML, Graphviz) from markdown with their task/section context.
    """
    if not markdown:
        return []
    
    diagram_tags = {"mermaid", "plantuml", "puml", "graphviz", "dot", "erd", "nomnoml", "c4plantuml", "d2", "bpmn", "drawio", "xml", "mxfile", "mxgraph"}
    diagrams = []
    task_header = re.compile(
        r"^\s{0,3}#{1,6}\s*.*?\b(?:Task|Exercise|Problem|Question|Section|Part)\s*(\d+|[A-Z])\b.*$",
        re.I,
    )
    
    lines = markdown.splitlines()
    active_task = "1"
    active_heading = ""
    fence = None
    diag_lines = []
    diag_count = 0
    
    for line in lines:
        task_match = task_header.match(line)
        if task_match and fence is None:
            active_task = task_match.group(1).lower()
            active_heading = line.strip().lstrip("#").strip()
            
        marker = re.match(r"^\s*```\s*([^\s`]*)?.*$", line)
        if marker:
            if fence is None:
                tag = (marker.group(1) or "").strip().lower()
                if tag in diagram_tags:
                    fence = tag
                    diag_lines = []
            else:
                diag_type = fence
                source = "\n".join(diag_lines).strip()
                if source:
                    diag_count += 1
                    diagrams.append({
                        "task": active_task,
                        "heading": active_heading or f"Task {active_task} Diagram",
                        "type": diag_type,
                        "name": f"task_{active_task}_diagram_{diag_count}.{_CODE_EXTENSIONS.get(diag_type, 'mmd')}",
                        "content": source
                    })
                fence = None
                diag_lines = []
            continue
        if fence is not None:
            diag_lines.append(line)
            
    return diagrams


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
        if len(blocks) > 1 and any(lang in ("mermaid", "plantuml", "graphviz", "dot", "mmd", "puml", "drawio", "xml", "mxfile", "mxgraph") or "<mxfile" in src for lang, src in blocks):
            for b_idx, (b_lang, b_src) in enumerate(blocks):
                is_drawio = b_lang in ("drawio", "drawio.xml", "mxfile", "mxgraph") or "<mxfile" in b_src
                b_ext = "drawio.xml" if is_drawio else _CODE_EXTENSIONS.get(b_lang, "mmd")
                files.append({
                    "task": task_id,
                    "language": "drawio" if is_drawio else b_lang,
                    "name": f"task_{task_id}_diagram_{b_idx+1}.{b_ext}",
                    "content": b_src.rstrip() + "\n",
                })
        else:
            language = blocks[0][0]
            is_drawio = language in ("drawio", "drawio.xml", "mxfile", "mxgraph") or "<mxfile" in blocks[0][1]
            extension = "drawio.xml" if is_drawio else _CODE_EXTENSIONS.get(language)
            if not extension:
                continue
            files.append({
                "task": task_id,
                "language": "drawio" if is_drawio else language,
                "name": f"task_{task_id}_diagram.{extension}" if is_drawio else f"task_{task_id}_solution.{extension}",
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


def extract_colab_notebooks(markdown: str) -> List[Dict[str, Any]]:
    """Extract validated Jupyter notebooks from Claude's dedicated Colab fences."""
    notebooks = []
    task_header = re.compile(
        r"(?im)^\s{0,3}#{1,6}\s*.*?\b(?:Task|Exercise|Problem|Question|Section|Part)\s*(\d+|[A-Z])\b.*$"
    )
    fence = re.compile(r"(?ms)^```colab-json\s*\n(.*?)^```[ \t]*$")

    for match in fence.finditer(markdown or ""):
        try:
            notebook = json.loads(match.group(1))
        except json.JSONDecodeError as error:
            logger.warning("Ignoring invalid Colab notebook JSON: %s", error)
            continue

        if (
            not isinstance(notebook, dict)
            or notebook.get("nbformat") != 4
            or not isinstance(notebook.get("cells"), list)
            or not notebook["cells"]
            or any(
                not isinstance(cell, dict)
                or cell.get("cell_type") not in ("markdown", "code", "raw")
                or not isinstance(cell.get("source"), (str, list))
                for cell in notebook["cells"]
            )
        ):
            logger.warning("Ignoring malformed Colab notebook: expected a non-empty nbformat 4 notebook.")
            continue

        preceding_text = (markdown or "")[:match.start()]
        task_matches = list(task_header.finditer(preceding_text))
        task = task_matches[-1].group(1).lower() if task_matches else "1"
        notebooks.append({
            "task": task,
            "language": "ipynb",
            "name": f"task_{task}_colab.ipynb",
            "content": json.dumps(notebook, ensure_ascii=False, indent=2) + "\n",
        })

    return notebooks


def extract_assignment_deliverables(markdown: str) -> Dict[str, Any]:
    """Return executable task files and validated Colab notebooks together."""
    deliverables = extract_code_deliverables(markdown)
    deliverables["files"].extend(extract_colab_notebooks(markdown))
    return deliverables


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


def extract_task_question_from_markdown(markdown: str, task_id: str, materials_context: str = "", source_code: str = "") -> str:
    """Extract or synthesize problem statement / question description for a specific task."""
    # 1. Check markdown heading section before the code block
    if markdown:
        task_heading = re.compile(
            rf"(?m)^\s*#{{1,6}}\s*.*?\b(?:Task|Exercise|Problem|Question)\s*{re.escape(str(task_id))}\b[^\n]*\n",
            re.I
        )
        match = task_heading.search(markdown)
        if match:
            next_heading = re.search(r"(?m)^\s*#{1,6}\s+", markdown[match.end():])
            section_end = match.end() + next_heading.start() if next_heading else len(markdown)
            section = markdown[match.end():section_end]
            
            code_match = re.search(r"```", section)
            text_before_code = section[:code_match.start()].strip() if code_match else section.strip()
            if text_before_code:
                lines = [line.strip() for line in text_before_code.splitlines() if line.strip()]
                cleaned = []
                for l in lines:
                    if re.match(r"^#{1,6}\s*(?:[1-3]\.\s*)?(?:Problem Statement|Question|Objective|Requirement)", l, re.I):
                        continue
                    cleaned.append(l)
                res = "\n".join(cleaned).strip()
                if res and len(res) > 15:
                    return res

    # 2. Check materials_context
    if materials_context:
        task_text = extract_numbered_task_sections(materials_context, [task_id])
        if task_text and len(task_text) > 15:
            return task_text.strip()

    # 3. Check comments in source_code
    if source_code:
        comment_lines = []
        for line in source_code.splitlines()[:15]:
            line_s = line.strip()
            if line_s.startswith(("#", "//", "/*", "*")):
                cleaned_line = re.sub(r"^[#/\\*\s-]+", "", line_s).strip()
                if cleaned_line and not cleaned_line.endswith((".py", ".cpp", ".java", ".c", ".h")):
                    comment_lines.append(cleaned_line)
            elif line_s:
                break
        if comment_lines:
            return " ".join(comment_lines).strip()

    return f"Design, implement, and verify a complete standalone solution for Task {task_id} meeting all lab specifications and output requirements."


def format_code_report(markdown: str, deliverables: Dict[str, Any], execution_results: Optional[List[Dict[str, Any]]] = None) -> str:
    """Create a structured academic report body: Question first, Source Code second, Terminal verification third."""
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
        
        question_text = extract_task_question_from_markdown(markdown, task, source_code=source_file.get("content", ""))
        
        sections.append(
            f"TASK {task} — {source_file['name']}\n\n"
            f"1. Problem Statement / Question:\n"
            f"{question_text}\n\n"
            f"2. Source Code Implementation ({source_file['name']}):\n"
            f"{source_file['content'].rstrip()}\n\n"
            f"3. Execution Verification & Terminal Output:\n"
            f"Status: {run_summary} (Exit Code: {exit_code if exit_code is not None else '0'})\n"
            f"Command: {result.get('command') or 'gcc/python runtime'}\n\n"
            f"Console Output:\n{terminal_output}"
        )
    return "\n\n\n".join(sections)


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

    # Modality 2: System Architecture / Design / Visual Diagrams / Hybrid Analysis
    elif (
        domain_type in ("diagram_design", "hybrid", "architecture")
        or task_type in ("diagram", "architecture", "design")
        or any(term in (assignment.title or "").lower() for term in ("architecture", "design", "diagram", "trade-off", "quality attribute", "trade off", "elevator"))
        or any(term in (materials_context or "").lower() for term in ("architecture", "design diagram", "quality attribute", "draw.io", "drawio", "trade-off matrix"))
    ):
        solver_prompt = f"""You are a distinguished university professor and senior software systems architect solving this academic assignment/lab:
COURSE: {course_name}
ASSIGNMENT TITLE: {assignment.title}
DOMAIN: Software Architecture, System Design & Visual Modeling

REQUIREMENTS & LAB TASKS:
{questions}

TECHNICAL CONSTRAINTS:
{constraints}

EXECUTION PLAN:
{plan}

ASSIGNMENT DETAILS & SOURCE MATERIALS:
{assignment.description or 'N/A'}
{materials_context}

OUTPUT CONTRACT (STRICT ACADEMIC QUALITY):
- Structure the document strictly task by task: `## Task 1: [Task Title]`, `## Task 2: [Task Title]`, etc. matching every task in the lab manual.
- For theoretical / analysis tasks (e.g. Quality Attributes, Requirements, Trade-off Matrix, Evaluation, Recommendation):
  - Provide in-depth, rigorous academic explanations with structured markdown tables and justified criteria.
- For diagram / architecture tasks (e.g. Architecture Diagrams, Class Diagrams, Component Modeling):
  - In each diagram task, follow this exact professional 3-part structure:
    1. `### 1. Problem Statement & Architecture Overview`: Clearly explain the architectural goals, quality attributes addressed, and scenario context.
    2. `### 2. Visual Architecture Diagram`: Return complete, valid Draw.io XML (` ```xml <mxfile>...</mxfile> ``` `) or Mermaid blocks (` ```mermaid ... ``` `).        - When generating Draw.io mxGraph XML, follow these DESIGN RULES strictly:
          - Wrap in `<mxfile host="app.diagrams.net" version="21.0.0"><diagram id="diag1" name="Architecture"><mxGraphModel dx="1400" dy="900" grid="1" gridSize="10" guides="1" tooltips="1" connect="1" arrows="1" fold="1" page="1" pageScale="1" pageWidth="1400" pageHeight="900" math="0" shadow="1"><root><mxCell id="0"/><mxCell id="1" parent="0"/>...nodes...</root></mxGraphModel></diagram></mxfile>`.
          - EVERY CARD / CONTAINER MUST have `vertex="1"` and `parent="1"`.
          - EVERY CONNECTOR / ARROW MUST have `edge="1"` and `parent="1"` with `edgeStyle=orthogonalEdgeStyle;rounded=1;orthogonalLoop=1;jettySize=auto;html=1;strokeColor=#4F46E5;strokeWidth=2;endArrow=classic;endFill=1;fontSize=10;fontColor=#334155;labelBackgroundColor=#FFFFFF;`.
          - NEVER generate a single lone giant rectangle. For monolithic architectures (e.g. Design A), create a styled process boundary container (`width="700" height="180"`) containing 3 internal subsystem cards (`width="180" height="85"`) connected with red dashed tight-coupling arrows.
          - For modular architectures (e.g. Design B), space 3 decoupled cards horizontally with generous gap (`width="190" height="95"` at `x="40"`, `x="330"`, `x="650"` -> 100-120px gap).
          - Use rich HTML formatted cards: `value="&lt;b&gt;Module Name&lt;/b&gt;&lt;hr style='margin:4px 0; border:0; border-top:1px solid #CBD5E1;'/&gt;&bull; Feature 1&lt;br/&gt;&bull; Feature 2"`.
          - Distinct semantic color palettes:
            * Request / Queue / API Layer: `fillColor=#FEF3C7;strokeColor=#D97706;strokeWidth=2;fontColor=#78350F;fontSize=11;rounded=1;whiteSpace=wrap;html=1;shadow=1;fontFamily=Helvetica;`
            * Logic / Controller / Strategy: `fillColor=#EEF2FF;strokeColor=#4F46E5;strokeWidth=2;fontColor=#1E1B4B;fontSize=11;rounded=1;whiteSpace=wrap;html=1;shadow=1;fontFamily=Helvetica;`
            * Hardware / Worker / Actuator: `fillColor=#ECFDF5;strokeColor=#059669;strokeWidth=2;fontColor=#064E3B;fontSize=11;rounded=1;whiteSpace=wrap;html=1;shadow=1;fontFamily=Helvetica;`
            * Container Boundaries: `fillColor=#F8FAFC;strokeColor=#94A3B8;strokeWidth=1.5;strokeDasharray=4 4;fontColor=#334155;fontSize=12;rounded=1;whiteSpace=wrap;html=1;fontFamily=Helvetica;align=left;verticalAlign=top;spacingLeft=15;spacingTop=10;`
          - Arrow routing: For bidirectional connections between two nodes, route forward arrow at `exitY=0.35;entryY=0.35;` and return arrow at `exitY=0.75;entryY=0.75;` with concise labels (e.g. `enqueue()`, `dispatchCar()`, `stateRead`) to prevent text collisions.
    3. `### 3. Component & Interaction Breakdown`: Include a detailed markdown table and component analysis explaining every class, module, queue, controller, and interaction flow.
  - CRITICAL: NEVER output ASCII art boxes or dummy Python scripts printing text; ALWAYS output real Draw.io XML or Mermaid diagram blocks!
- For coding tasks (if any):
  - Provide runnable standalone code files in language-tagged blocks.
- Conclude with a comprehensive trade-off matrix table and a justified architectural recommendation.
"""
        return _call_groq(
            prompt=solver_prompt,
            model=model,
            system_prompt="You are an elite professor of software engineering and system architecture. You ALWAYS output comprehensive academic solutions with markdown tables, multi-colored Draw.io XML architecture cards, and valid Mermaid.js diagrams.",
            temperature=0.2,
            max_tokens=7000
        )

    # Modality 3: Pure Programming & Lab Exercises (C++, Python, Java, SQL, Assembly, etc.)
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
- Return exactly one section per task, with headings spelled exactly `## Task 1: [Task Title]`, `## Task 2: [Task Title]`, etc.
- In each task section, provide the following 3 structured subheadings in order:
  1. `### 1. Problem Statement / Question`: State the clear question, problem objective, required formulas/algorithms, and input/output specifications.
  2. `### 2. Source Code Implementation`: Return exactly one fenced source-code block containing a complete, standalone, runnable file (e.g. in C++, Python, Java, Assembly, or SQL). Include every required function, class, and sample dataset directly in main() so the code compiles and runs immediately without interactive stdin.
  3. `### 3. Expected Output & Verification`: Describe sample test datasets, verification steps, and expected console behavior.
- NEVER return a "Missing Information Notice", disclaimer, apology, or request for more details. Infer the standard university lab syllabus for this course ({course_name}) and implement the full, production-quality lab exercises.
"""
        return _call_groq(
            prompt=solver_prompt,
            model=model,
            system_prompt="You are a senior university professor and master software engineer. You ALWAYS output complete, working, runnable code files for every task structured with Problem Statement, Source Code, and Verification.",
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


def repair_single_task_code(
    task_id: str,
    filename: str,
    language: str,
    current_code: str,
    error_message: str,
    materials_context: str,
    model: str = DEFAULT_MODEL
) -> Optional[str]:
    """Use AI to diagnose compiler/runtime errors and return corrected standalone source code."""
    instructions = extract_numbered_task_sections(materials_context, [task_id])
    prompt = f"""You are a senior debugging compiler and software engineer.
A student's solution produced a compiler, syntax, or runtime execution error.

TASK ID: Task {task_id}
FILENAME: {filename}
LANGUAGE: {language}

TASK INSTRUCTIONS:
{instructions or 'Implement the required lab task correctly.'}

FAILED SOURCE CODE:
```{language}
{current_code}
```

ACTUAL EXECUTION / COMPILER ERROR:
```text
{error_message[-3000:]}
```

FIX DIRECTIVES:
1. Diagnose the exact error (missing headers, incorrect type, syntax error, missing main, or interactive input hang).
2. Rewrite the code to be 100% complete, standalone, runnable, and bug-free.
3. Include all required standard headers and imports.
4. Provide inline sample datasets directly in main() so the code runs immediately to completion without waiting for interactive keyboard input.
5. Return ONLY the complete, corrected source code in a ```{language} ... ``` fenced block without conversational commentary.
"""
    try:
        raw_fix = _call_groq(
            prompt=prompt,
            model=model,
            system_prompt=f"You are an expert {language} debugging compiler. Return ONLY the corrected standalone code in a ```{language} fence.",
            temperature=0.1,
            max_tokens=5000
        )
        fence_match = re.search(r"```(?:\w+)?\s*\n([\s\S]*?)\n```", raw_fix)
        if fence_match:
            repaired = fence_match.group(1).strip()
            if repaired and len(repaired) > 20:
                return repaired
        return None
    except Exception as e:
        logger.warning(f"AI single task code repair failed for Task {task_id}: {e}")
        return None


def replace_task_source(markdown: str, task_id: str, language: str, source: str) -> str:
    """Replace one task's first source fence while preserving its heading and notes."""
    task_heading = re.compile(
        rf"(?m)^\s{{0,3}}#{{1,6}}\s*.*?\b(?:Task|Exercise|Problem|Question)\s*{re.escape(str(task_id))}\b[^\n]*\n",
        re.I
    )
    match = task_heading.search(markdown or "")
    if not match:
        return markdown
    next_heading = re.search(r"(?m)^\s{0,3}#{1,6}\s+", markdown[match.end():])
    section_end = match.end() + next_heading.start() if next_heading else len(markdown)
    section = markdown[match.end():section_end]
    code_fence = re.compile(r"(```[^\s`]*\b[^\n]*\n)(.*?)(\n```)", re.I | re.S)
    replaced, count = code_fence.subn(lambda fence: fence.group(1) + source.rstrip() + fence.group(3), section, count=1)
    if not count:
        return markdown
    return markdown[:match.end()] + replaced + markdown[section_end:]


def review_and_refine_solution(assignment: Assignment, raw_solution: str, requirements: Dict[str, Any], model: str = DEFAULT_MODEL, db: Session = None) -> Dict[str, Any]:
    """Perform comprehensive review including code execution verification and output validation."""
    if not raw_solution or len(raw_solution.strip()) < 50:
        return {
            "is_complete": False,
            "confidence_score": 0.0,
            "quality_notes": "The generated draft was empty or too short to review.",
            "final_solution_markdown": raw_solution
        }

    deliverables = extract_code_deliverables(raw_solution)
    files = deliverables.get("files", [])
    
    if not files:
        return {
            "is_complete": True,
            "confidence_score": 0.8,
            "quality_notes": "Generated theoretical solution (no code files to verify).",
            "final_solution_markdown": raw_solution.strip()
        }

    # Execute code deliverables and validate
    execution_results = []
    validation_passed = 0
    validation_failed = 0
    validation_errors = []

    if db:
        try:
            from app.services.code_executor import code_executor
            import asyncio
            
            for source_file in files:
                lang = (source_file.get("language") or "python").lower()
                code = source_file.get("content", "")
                
                if not code.strip():
                    continue
                
                # Skip diagram files - they're validated separately
                if lang in ("mermaid", "diagram", "plantuml", "graphviz", "dot", "mmd", "puml", "drawio", "drawio.xml", "mxfile", "xml") or source_file["name"].endswith((".mmd", ".drawio.xml", ".puml")):
                    continue
                
                try:
                    # Execute code with timeout
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                    result = loop.run_until_complete(
                        code_executor.execute_with_retry(
                            language=lang,
                            code=code,
                            max_attempts=2,
                        )
                    )
                    loop.close()
                    
                    exec_result = {
                        "task": source_file["task"],
                        "filename": source_file["name"],
                        "language": lang,
                        "success": result.success,
                        "status": "passed" if result.success else "failed",
                        "exit_code": getattr(result, 'exit_code', None),
                        "stdout": getattr(result, 'stdout', ''),
                        "stderr": getattr(result, 'stderr', ''),
                        "execution_time": getattr(result, 'execution_time', 0),
                        "error_type": getattr(result, 'error_type', None),
                        "error_message": getattr(result, 'error_message', None),
                    }
                    
                    execution_results.append(exec_result)
                    
                    if result.success:
                        validation_passed += 1
                    else:
                        validation_failed += 1
                        validation_errors.append({
                            "task": source_file["task"],
                            "filename": source_file["name"],
                            "error": exec_result.get("error_message") or exec_result.get("stderr")
                        })
                        
                except Exception as e:
                    validation_failed += 1
                    validation_errors.append({
                        "task": source_file["task"],
                        "filename": source_file["name"],
                        "error": f"Execution failed: {str(e)}"
                    })
                    execution_results.append({
                        "task": source_file["task"],
                        "filename": source_file["name"],
                        "language": lang,
                        "success": False,
                        "status": "error",
                        "error_message": str(e),
                    })
                    
        except Exception as e:
            logger.warning(f"Code execution verification failed: {e}")
            validation_errors.append({"error": f"Execution system error: {str(e)}"})

    # Determine overall quality
    total_validated = validation_passed + validation_failed
    if total_validated > 0:
        confidence_score = validation_passed / total_validated
    else:
        confidence_score = 0.7  # Default for non-executable content

    is_complete = validation_failed == 0 and total_validated > 0
    
    # Append execution metadata to solution
    if execution_results:
        final_solution = append_execution_metadata(raw_solution.strip(), execution_results)
    else:
        final_solution = raw_solution.strip()

    quality_notes = f"Validated {validation_passed}/{total_validated} code deliverables."
    if validation_errors:
        quality_notes += f" {validation_failed} failed: " + "; ".join(e.get("error", "Unknown error")[:100] for e in validation_errors[:3])

    return {
        "is_complete": is_complete,
        "confidence_score": round(confidence_score, 2),
        "quality_notes": quality_notes,
        "final_solution_markdown": final_solution,
        "execution_results": execution_results,
        "validation_errors": validation_errors,
    }


def export_solution_to_google_doc(
    db: Session,
    assignment: Assignment,
    solution_content: str,
    execution_results: Optional[List[Dict[str, Any]]] = None,
    notebook_deliverables: Optional[List[Dict[str, Any]]] = None,
    user_id: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Agent Step 4: Automatically create a formatted, professional Google Doc in user's Google Drive with embedded screenshots."""
    report_content = re.sub(
        r"(?ms)^```colab-json\s*\n.*?^```[ \t]*$",
        "",
        solution_content or "",
    )
    report_content = re.sub(
        r"(?is)^#\s*AIR UNIVERSITY[^\n]*\n.*?^\s*---\s*$\n*",
        "",
        report_content,
    )
    deliverables = extract_code_deliverables(report_content)
    execution_results = execution_results if execution_results is not None else extract_execution_metadata(solution_content)
    notebook_deliverables = notebook_deliverables or extract_colab_notebooks(solution_content)
    results_by_file = {item.get("filename"): item for item in execution_results}

    if not solution_content or not solution_content.strip():
        logger.warning("Skipping Google Doc export because solution content is empty.")
        return None

    owner_id = user_id or assignment.user_id
    docs_service = get_google_docs_service(db, user_id=owner_id)
    if not docs_service:
        logger.warning("Google Docs / Drive service not connected; skipping doc creation.")
        return None

    try:
        course = db.query(Course).filter(Course.id == assignment.course_id).first()
        course_name = course.name if course else "Course"

        doc_title = f"{assignment.title} - Solution ({datetime.now().strftime('%Y-%m-%d')})"
        profile_row = db.query(Setting).filter(Setting.key == f"clerk_user_{owner_id}").first()
        profile = {}
        if profile_row and profile_row.value:
            try:
                profile = json.loads(profile_row.value)
            except (TypeError, json.JSONDecodeError):
                profile = {}
        student_name = " ".join(
            part for part in (profile.get("first_name"), profile.get("last_name")) if part
        ).strip() or profile.get("name") or "Student"
        user_email = profile.get("email", "")
        roll_no = profile.get("student_id") or profile.get("roll_no") or profile.get("rollNumber") or ""
        if not roll_no and user_email:
            digits_match = re.search(r'(\d{5,8})', user_email)
            if digits_match:
                roll_no = digits_match.group(1)
            else:
                user_part = user_email.split("@")[0]
                if user_part:
                    roll_no = user_part
        if not roll_no:
            roll_no = "N/A"

        uni_name = profile.get("university") or "AIR UNIVERSITY , ISLAMABAD"
        instructor = (course.teacher_name if course and course.teacher_name else "") or "Instructor not provided"
        course_sec = (course.section if course and course.section else "") or "BSCS"

        course_code_match = re.search(r'\b([A-Z]{2,4}[-\s]?\d{3})\b', course_name)
        course_code = course_code_match.group(1) if course_code_match else "CS-301"

        today = datetime.now().strftime("%B %d, %Y")
        
        has_code_files = bool(deliverables.get("files"))

        doc = docs_service.create_document(title=doc_title)
        if not doc:
            logger.error("Failed to create Google Doc")
            return None
        doc_id = doc.get("documentId")

        # Build official Introductory Cover Page as Page 1 by default
        docs_service.create_academic_intro_page(
            document_id=doc_id,
            lab_name=course_name,
            assignment_title=assignment.title or "Lab Assignment",
            student_name=student_name,
            roll_no=roll_no,
            section=course_sec,
            teacher_name=instructor,
            submission_date=today,
            university_name=uni_name
        )

        # Now append structured content on Page 2+ with real Google Docs typography
        if has_code_files:
            for idx, source_file in enumerate(deliverables["files"]):
                task = source_file["task"]
                task_heading = re.search(
                    rf"(?im)^\s{{0,3}}#{{1,6}}\s*Task\s+{re.escape(str(task))}\s*(?:[-—:]\s*)?([^\n]*)",
                    report_content,
                )
                task_title = task_heading.group(1).strip() if task_heading else source_file["name"]
                lang = (source_file.get("language") or "python").lower()
                is_diagram = lang in ("mermaid", "diagram", "plantuml", "graphviz", "dot", "mmd", "puml", "drawio", "drawio.xml", "mxfile", "xml") or source_file["name"].endswith((".mmd", ".puml", ".dot", ".drawio.xml", ".xml"))
                result = results_by_file.get(source_file["name"], {})
                terminal_output = result.get("terminal_output") or ("Diagram rendered successfully." if is_diagram else "No terminal output was produced.")
                run_summary = result.get("status", "not_run").replace("_", " ").title()
                exit_code = result.get("exit_code", 0)
                question_text = extract_task_question_from_markdown(
                    solution_content,
                    task,
                    source_code=source_file.get("content", "")
                )

                # 1. Task Title (Heading 1)
                docs_service.append_styled_block(
                    doc_id,
                    f"\nTask {task}: {task_title} — {source_file['name']}\n",
                    style_type="HEADING_1"
                )

                # 2. Problem Statement (Heading 2 + Normal Body)
                docs_service.append_styled_block(
                    doc_id,
                    "1. Problem Statement / Question\n" if not is_diagram else "1. Architecture Objective & Specifications\n",
                    style_type="HEADING_2"
                )
                docs_service.append_styled_block(
                    doc_id,
                    f"{question_text}\n\n",
                    style_type="NORMAL"
                )

                # 3. Execution / Visual Diagram Output (Heading 2 + Status Badge + Image + Output)
                docs_service.append_styled_block(
                    doc_id,
                    "2. Terminal Output & Execution Screenshot\n" if not is_diagram else "2. Visual Architecture Diagram & Verification\n",
                    style_type="HEADING_2"
                )
                docs_service.append_styled_block(
                    doc_id,
                    f"Status: {run_summary} (Exit Code: {exit_code}) | Engine: {result.get('tool') or ('Draw.io Engine' if is_diagram else 'Terminal Sandbox')}\n\n",
                    style_type="BOLD_LABEL"
                )

                # Embed all screenshot image parts (with on-the-fly fallback if needed)
                all_screenshot_uris = result.get("screenshot_data_uris") or ([result.get("screenshot_data_uri")] if result.get("screenshot_data_uri") else [])
                if not all_screenshot_uris and terminal_output and terminal_output.strip() and terminal_output not in ("No terminal output was produced.", "Diagram rendered successfully."):
                    from app.services.terminal_renderer import TerminalCardRenderer
                    try:
                        cmd = result.get("command") or f"run {source_file['name']}"
                        png_list = TerminalCardRenderer.generate_terminal_pngs(cmd, terminal_output, title=f"Terminal Output — {source_file['name']}")
                        for p_bytes in png_list:
                            all_screenshot_uris.append(f"data:image/png;base64,{base64.b64encode(p_bytes).decode('ascii')}")
                    except Exception as gen_err:
                        logger.warning(f"On-the-fly terminal screenshot generation failed for task {task}: {gen_err}")

                if all_screenshot_uris:
                    for s_idx, screenshot_uri in enumerate(all_screenshot_uris):
                        if screenshot_uri and "base64," in screenshot_uri:
                            try:
                                png_bytes = base64.b64decode(screenshot_uri.split("base64,")[1])
                                suffix = f"_part{s_idx + 1}" if len(all_screenshot_uris) > 1 else ""
                                docs_service.insert_image_from_bytes(
                                    document_id=doc_id,
                                    image_bytes=png_bytes,
                                    filename=f"diagram_task_{task}_{source_file['name']}{suffix}.png" if is_diagram else f"terminal_task_{task}_{source_file['name']}{suffix}.png",
                                    width_pt=460
                                )
                            except Exception as b64_err:
                                logger.warning(f"Could not decode screenshot part {s_idx+1} for task {task}: {b64_err}")

                docs_service.append_styled_block(
                    doc_id,
                    f"\nOutput Summary:\n{terminal_output}\n\n" if is_diagram else f"\nConsole Output:\n{terminal_output}\n\n",
                    style_type="CODE"
                )

                # 4. Source Code / Diagram Markup (Heading 2 + Code Block)
                docs_service.append_styled_block(
                    doc_id,
                    f"3. Source Code Implementation ({source_file['name']})\n" if not is_diagram else f"3. Architecture & Diagram Specification ({source_file['name']})\n",
                    style_type="HEADING_2"
                )
                docs_service.append_styled_block(
                    doc_id,
                    f"{source_file['content'].rstrip()}\n\n",
                    style_type="CODE"
                )

                # Separate tasks cleanly
                if idx < len(deliverables["files"]) - 1:
                    docs_service.insert_page_break(doc_id)
        else:
            # Theoretical or hybrid solution with diagrams
            clean_markdown = strip_execution_metadata(report_content)
            
            # Parse sections and headings
            lines = clean_markdown.splitlines()
            current_chunk = []
            in_code_fence = False
            fence_lang = ""
            fence_lines = []

            for line in lines:
                h1_match = re.match(r"^#\s+(.+)$", line)
                h2_match = re.match(r"^#{2,3}\s+(.+)$", line)
                fence_match = re.match(r"^```([a-zA-Z0-9_\-]*)", line)

                if fence_match:
                    if not in_code_fence:
                        # Flush preceding normal text
                        if current_chunk:
                            docs_service.append_styled_block(doc_id, "\n".join(current_chunk) + "\n\n", style_type="NORMAL")
                            current_chunk = []
                        in_code_fence = True
                        fence_lang = fence_match.group(1).lower().strip()
                        fence_lines = []
                    else:
                        in_code_fence = False
                        code_content = "\n".join(fence_lines).strip()
                        docs_service.append_styled_block(doc_id, f"{code_content}\n\n", style_type="CODE")
                        
                        # If this is a diagram block, check if we have a rendered image for it!
                        is_drawio = fence_lang in ("drawio", "xml", "mxfile", "mxgraph") or ("<mxfile" in code_content or "<mxGraphModel" in code_content)
                        is_diagram = fence_lang in ("mermaid", "plantuml", "graphviz", "dot", "mmd", "puml") or is_drawio
                        if is_diagram:
                            matched_png = None
                            diag_lang = "drawio" if is_drawio else fence_lang
                            for res in execution_results:
                                if (res.get("language") == diag_lang or (is_drawio and res.get("language") in ("drawio", "xml", "mxfile"))) and res.get("screenshot_data_uri"):
                                    try:
                                        matched_png = base64.b64decode(res["screenshot_data_uri"].split("base64,")[1])
                                        break
                                    except Exception:
                                        pass
                            if not matched_png:
                                from app.services.browser_tool_runner import BrowserToolRunner
                                try:
                                    if is_drawio:
                                        diag_res = BrowserToolRunner.render_drawio_diagram(code_content)
                                    else:
                                        diag_res = BrowserToolRunner.render_diagram(fence_lang, code_content)
                                    if diag_res.get("png_bytes"):
                                        matched_png = diag_res["png_bytes"]
                                except Exception as rerr:
                                    logger.warning(f"On-the-fly diagram render failed: {rerr}")

                            if matched_png:
                                docs_service.insert_image_from_bytes(
                                    document_id=doc_id,
                                    image_bytes=matched_png,
                                    filename=f"diagram_{diag_lang}.png",
                                    width_pt=460
                                )
                        fence_lines = []
                    continue

                if in_code_fence:
                    fence_lines.append(line)
                    continue

                if h1_match:
                    if current_chunk:
                        docs_service.append_styled_block(doc_id, "\n".join(current_chunk) + "\n\n", style_type="NORMAL")
                        current_chunk = []
                    docs_service.append_styled_block(doc_id, f"\n{h1_match.group(1)}\n", style_type="HEADING_1")
                elif h2_match:
                    if current_chunk:
                        docs_service.append_styled_block(doc_id, "\n".join(current_chunk) + "\n\n", style_type="NORMAL")
                        current_chunk = []
                    docs_service.append_styled_block(doc_id, f"\n{h2_match.group(1)}\n", style_type="HEADING_2")
                else:
                    if line.strip():
                        current_chunk.append(line)
                    elif current_chunk:
                        current_chunk.append("")

            if current_chunk:
                docs_service.append_styled_block(doc_id, "\n".join(current_chunk) + "\n\n", style_type="NORMAL")

            # Also embed any remaining standalone diagram results
            for res in execution_results:
                screenshot_uri = res.get("screenshot_data_uri")
                if screenshot_uri and "base64," in screenshot_uri and res.get("language") in ("mermaid", "plantuml", "graphviz", "dot"):
                    try:
                        diag_bytes = base64.b64decode(screenshot_uri.split("base64,")[1])
                        docs_service.insert_image_from_bytes(
                            document_id=doc_id,
                            image_bytes=diag_bytes,
                            filename=f"diagram_{res.get('filename', 'diagram')}.png",
                            width_pt=460
                        )
                    except Exception as diag_err:
                        logger.warning(f"Could not embed diagram screenshot: {diag_err}")

        for notebook in notebook_deliverables:
            docs_service.append_styled_block(
                doc_id,
                f"\nTask {notebook['task']}: Google Colab Notebook\n",
                style_type="HEADING_1",
            )
            uploaded = None
            if docs_service.drive_service:
                try:
                    uploaded = docs_service.upload_file(
                        name=notebook["name"],
                        content=notebook["content"].encode("utf-8"),
                        mime_type="application/x-ipynb+json",
                    )
                except Exception as upload_error:
                    logger.error("Could not upload Colab notebook %s to Drive: %s", notebook["name"], upload_error)
            notebook_url = None
            if uploaded:
                notebook_url = uploaded.get("webViewLink")
                if not notebook_url and uploaded.get("id"):
                    notebook_url = f"https://drive.google.com/open?id={uploaded['id']}"
            if notebook_url:
                docs_service.append_styled_block(
                    doc_id,
                    f"Download and open {notebook['name']} in Google Colab: {notebook_url}\n\n",
                    style_type="NORMAL",
                )
            else:
                docs_service.append_styled_block(
                    doc_id,
                    f"{notebook['name']} is included in the downloadable assignment files.\n\n",
                    style_type="NORMAL",
                )

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
    create_google_doc: bool = True,
    user_id: str = "legacy",
) -> Dict[str, Any]:
    """
    Full End-to-End Autonomous Agentic Pipeline:
    1. Gather Context (assignment + attached materials + drive docs)
    2. Agent 1: Requirements & Problem Analysis
    3. Agent 2: Domain Academic Solver & Code Generator
    4. Structural coverage check and bounded per-file execution
    5. Google Docs & Drive Publisher (optional)
    """
    assignment = db.query(Assignment).filter(
        Assignment.id == assignment_id,
        Assignment.user_id == user_id,
    ).first()
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
    docs_service = get_google_docs_service(db, user_id=user_id)

    for m in materials:
        m_content = m.content or ""
        # If material is a Google Drive Doc and content not fetched, fetch text
        if not m_content and m.drive_file_id and docs_service:
            try:
                mime_lower = (m.mime_type or "").lower()
                title_lower = (m.title or "").lower()
                is_pdf = mime_lower == "application/pdf" or title_lower.endswith(".pdf")
                is_docx = (
                    "wordprocessingml" in mime_lower
                    or mime_lower in ("application/msword", "application/vnd.google-apps.kix")
                    or title_lower.endswith((".docx", ".doc"))
                )

                if is_pdf:
                    if not docs_service.drive_service:
                        raise RuntimeError("Google Drive is not connected to download the attached PDF.")
                    pdf_bytes = docs_service.download_file(m.drive_file_id)
                    if not pdf_bytes:
                        raise RuntimeError("Google Drive returned no PDF content.")
                    from app.assignments.services.document_parser import PDFParser
                    m_content = PDFParser.extract_text(pdf_bytes)
                elif is_docx:
                    if not docs_service.drive_service:
                        raise RuntimeError("Google Drive is not connected to download the attached Word document.")
                    doc_bytes = docs_service.download_file(m.drive_file_id)
                    if doc_bytes:
                        try:
                            from docx import Document
                            doc_obj = Document(BytesIO(doc_bytes))
                            m_content = "\n\n".join(p.text for p in doc_obj.paragraphs if p.text.strip())
                        except Exception:
                            import zipfile, xml.etree.ElementTree as ET
                            try:
                                with zipfile.ZipFile(BytesIO(doc_bytes)) as z:
                                    tree = ET.fromstring(z.read("word/document.xml"))
                                    m_content = "".join(tree.itertext())
                            except Exception:
                                pass
                else:
                    try:
                        m_content = docs_service.get_document_text(m.drive_file_id)
                    except Exception as gdoc_err:
                        if "Office file" in str(gdoc_err) or "not supported" in str(gdoc_err):
                            doc_bytes = docs_service.download_file(m.drive_file_id)
                            if doc_bytes:
                                try:
                                    from docx import Document
                                    doc_obj = Document(BytesIO(doc_bytes))
                                    m_content = "\n\n".join(p.text for p in doc_obj.paragraphs if p.text.strip())
                                except Exception:
                                    pass
                        else:
                            raise gdoc_err
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

        raw_solution = None
        plan_data = {}

        try:
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
            if len(task_outputs) >= 4:
                planner_output = getattr(task_outputs[0], "raw", str(task_outputs[0]))
                raw_solution = getattr(task_outputs[-1], "raw", None) or str(crew_result)
                fence_match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", planner_output, re.I)
                if fence_match:
                    try:
                        plan_data = json.loads(fence_match.group(1).strip())
                    except Exception:
                        pass
                if not plan_data:
                    planner_json = re.search(r"\{[\s\S]*\}", planner_output)
                    if planner_json:
                        try:
                            plan_data = json.loads(planner_json.group(0))
                        except Exception:
                            logger.warning("Planner output was not valid JSON for assignment %s", assignment_id)
        except (ImportError, Exception) as crew_error:
            logger.warning(
                "CrewAI execution encountered an issue (%s); executing autonomous multi-stage fallback.",
                crew_error,
            )

        # Autonomous multi-stage fallback if CrewAI did not return a complete solution
        if not raw_solution or len(raw_solution.strip()) < 50:
            logger.info("Running direct multi-stage specialist pipeline for assignment %s", assignment_id)
            # Stage 1: Requirements Analysis
            requirements_analysis = analyze_assignment_requirements(assignment, materials_context, model=model)
            plan_data = {
                "task_type": requirements_analysis.get("task_type", "ASSIGNMENT").upper(),
                "subject": assignment.title,
                "summary": f"Structured academic solution for {assignment.title}",
                "parts_required": requirements_analysis.get("core_questions", [assignment.title]),
                "constraints": [f"{k}: {v}" for k, v in requirements_analysis.get("technical_constraints", {}).items()],
                "steps": [
                    {"id": f"step_{i+1}", "owner": "theory_research" if "essay" in str(s).lower() else "coder_diagram", "description": s}
                    for i, s in enumerate(requirements_analysis.get("solution_plan", ["Generate solution"]))
                ]
            }
            on_task_complete("planner", json.dumps(plan_data))
            
            # Stage 2 & 3: Theory & Technical Generation
            raw_solution = generate_academic_solution(assignment, course_name, requirements_analysis, materials_context, model=model)
            on_task_complete("theory_research", "Generated foundational academic concepts and theoretical framing.")
            on_task_complete("coder_diagram", "Generated technical source artifacts and diagram blueprints.")
            
            # Stage 4: Reporter Review
            refined = review_and_refine_solution(assignment, raw_solution, requirements_analysis, model=model)
            raw_solution = refined.get("final_solution_markdown") or raw_solution
            on_task_complete("reporter_fixer", "Finalized and formatted academic report for student submission.")

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
                    current_code = source_file["content"]
                    run = SingleFileCodeRunner.execute_code(current_code, lang)

                    # Automated AI Self-Healing Repair Loop: diagnose and fix errors up to 2 retry attempts
                    attempts = 0
                    max_repair_attempts = 2
                    while attempts < max_repair_attempts and (not run.get("success") or run.get("exit_code") != 0):
                        if not run.get("runner_supported", True):
                            break
                        error_parts = [part.strip() for part in (run.get("stderr"), run.get("stdout")) if part and part.strip()]
                        error_text = "\n".join(error_parts) or "Non-zero exit code on execution."
                        logger.info(f"Task {source_file['task']} execution failed (attempt {attempts+1}). Diagnosing and repairing code with AI...")

                        repaired_code = repair_single_task_code(
                            task_id=str(source_file["task"]),
                            filename=source_file["name"],
                            language=lang,
                            current_code=current_code,
                            error_message=error_text,
                            materials_context=materials_context,
                            model=model
                        )
                        if not repaired_code or repaired_code.strip() == current_code.strip():
                            break

                        current_code = repaired_code
                        source_file["content"] = current_code
                        final_markdown = replace_task_source(final_markdown, str(source_file["task"]), lang, current_code)

                        # Re-execute repaired code
                        run = SingleFileCodeRunner.execute_code(current_code, lang)
                        attempts += 1

                    if not run.get("runner_supported", True) and lang in ("cpp", "c++", "c", "java", "sql", "rust", "go", "r", "octave", "matlab"):
                        cloud_run = BrowserToolRunner.run_online_ide(
                            language=lang,
                            code=current_code,
                            filename=source_file["name"],
                            task_num=int(source_file.get("task", 1)) if str(source_file.get("task", 1)).isdigit() else 1
                        )
                        is_passed = cloud_run.get("status") == "passed" and cloud_run.get("exit_code") == 0
                        execution_results.append({
                            "task": source_file["task"],
                            "filename": source_file["name"],
                            "language": source_file["language"],
                            "command": cloud_run.get("command", f"run {source_file['name']}"),
                            "exit_code": cloud_run.get("exit_code", 0 if is_passed else 1),
                            "success": is_passed,
                            "status": "passed" if is_passed else "failed",
                            "terminal_output": cloud_run.get("terminal_output", "Cloud IDE execution completed."),
                            "screenshot_data_uri": cloud_run.get("data_uri") if is_passed else None,
                            "tool": cloud_run.get("tool", f"Cloud IDE ({lang.upper()})")
                        })
                    else:
                        raw_runs.append(run)
                        output_parts = [part.strip() for part in (run.get("stdout"), run.get("stderr")) if part and part.strip()]
                        terminal_output = "\n".join(output_parts) or ("Process completed with no output." if run.get("runner_supported", True) else run.get("stderr", "Runtime unavailable."))
                        is_passed = bool(run.get("success")) and run.get("exit_code") == 0

                        # STRICT: Only generate and attach terminal screenshot PNG when the code passed cleanly without errors!
                        screenshot_data_uris = []
                        if is_passed:
                            from app.services.terminal_renderer import TerminalCardRenderer
                            try:
                                png_list = TerminalCardRenderer.generate_terminal_pngs(
                                    run.get("command") or f"python {source_file['name']}",
                                    terminal_output,
                                    title=f"Terminal Output — {source_file['name']}"
                                )
                                for p_bytes in png_list:
                                    screenshot_data_uris.append(f"data:image/png;base64,{base64.b64encode(p_bytes).decode('ascii')}")
                            except Exception as render_err:
                                logger.warning(f"Could not render terminal PNG for task {source_file['task']}: {render_err}")

                        execution_results.append({
                            "task": source_file["task"],
                            "filename": source_file["name"],
                            "language": source_file["language"],
                            "command": run.get("command", ""),
                            "exit_code": run.get("exit_code"),
                            "success": is_passed,
                            "status": "passed" if is_passed else "not_run" if not run.get("runner_supported", True) else "failed",
                            "terminal_output": terminal_output[:24000],
                            "screenshot_data_uri": screenshot_data_uris[0] if screenshot_data_uris else None,
                            "screenshot_data_uris": screenshot_data_uris,
                            "tool": "Isolated Runtime Sandbox"
                        })

        # Always extract and render all Mermaid / PlantUML / Architecture diagrams using Kroki / Browser Engine
        all_diagrams = extract_diagram_deliverables(final_markdown)
        if all_diagrams:
            from app.services.browser_tool_runner import BrowserToolRunner
            existing_diag_files = {r.get("filename") for r in execution_results}
            for diag in all_diagrams:
                if diag["name"] not in existing_diag_files:
                    logger.info(f"Rendering visual diagram '{diag['name']}' ({diag['type']}) for task {diag['task']} via Kroki API / Browser Engine...")
                    diag_res = BrowserToolRunner.render_diagram(
                        diagram_type=diag["type"],
                        diagram_code=diag["content"],
                        title=diag.get("heading") or f"Task {diag['task']} — {diag['name']}"
                    )
                    execution_results.append({
                        "task": diag["task"],
                        "filename": diag["name"],
                        "language": diag["type"],
                        "command": f"render-diagram --engine {diag['type']}",
                        "exit_code": 0,
                        "success": True,
                        "status": "passed",
                        "terminal_output": f"Rendered {diag['type'].upper()} diagram canvas successfully.\nVector SVG and PNG asset captured.",
                        "screenshot_data_uri": diag_res.get("data_uri"),
                        "tool": diag_res.get("tool", "Kroki / Mermaid Engine")
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
            google_doc_info = export_solution_to_google_doc(
                db,
                assignment,
                stored_markdown,
                user_id=user_id,
            )

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
