import logging
import json
import asyncio
import re
from typing import Optional, List, Dict, Any
from datetime import datetime
from dataclasses import dataclass
from enum import Enum

from app.assignments.schemas.assignment import (
    ExtractedRequirements, Requirement, SolutionPackage, 
    GeneratedFile, DeliverableType, TaskType, RequirementType
)

logger = logging.getLogger(__name__)


def _extract_json_object(text: str) -> Dict[str, Any]:
    """Parse one JSON object from a model response, including fenced responses."""
    source = (text or "").strip()
    fenced = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", source, re.IGNORECASE)
    if fenced:
        source = fenced.group(1).strip()

    start = source.find("{")
    if start < 0:
        raise ValueError("Planner response did not contain a JSON object")

    depth = 0
    in_string = False
    escaped = False
    for index in range(start, len(source)):
        char = source[index]
        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                parsed = json.loads(source[start:index + 1])
                if not isinstance(parsed, dict):
                    break
                return parsed
    raise ValueError("Planner response contained incomplete or invalid JSON")


class AgentRole(str, Enum):
    PLANNER = "planner"
    WRITER = "writer"
    CODER = "coder"
    MATH_SOLVER = "math_solver"
    RESEARCHER = "researcher"
    DATA_ANALYST = "data_analyst"
    REVIEWER = "reviewer"


@dataclass
class AgentTask:
    requirement_id: str
    role: AgentRole
    prompt: str
    context: Dict[str, Any]
    dependencies: List[str] = None


@dataclass
class AgentResult:
    requirement_id: str
    role: AgentRole
    success: bool
    output: Any
    error: Optional[str] = None
    metadata: Dict[str, Any] = None


class BaseAgent:
    def __init__(self, llm_client=None):
        self.llm_client = llm_client
    
    async def execute(self, task: AgentTask) -> AgentResult:
        raise NotImplementedError


class PlannerAgent(BaseAgent):
    """Breaks down requirements into executable subtasks."""
    
    PLANNING_PROMPT = """You are a senior academic planning specialist. Analyze the assignment and produce a precise, dependency-aware execution plan for the downstream specialists. Plan only; do not solve any part of the assignment.

REQUIREMENT:
{requirement}

CONTEXT:
- Task Type: {task_type}
- Course: {course_name}
- Other Requirements: {other_requirements}
- Available Tools: {available_tools}

Planning quality checks:
- Cover every explicit task, question, sub-question, and deliverable once, preserving the source order and numbering.
- Preserve stated requirements and constraints. Do not fill gaps with invented facts; where the schema has no missing-information field, describe the uncertainty in the relevant subtask's inputs_needed or expected_output.
- For mixed assignments, route each subtask to the appropriate specialist and make dependencies explicit. Keep independent work independent.
- Ensure every dependency points to another subtask id, contains no self-reference, and forms an acyclic order.
- Consider unavailable datasets, unspecified language or tools, unreadable or contradictory instructions, hardware requirements, and empty context. Make conservative assumptions visible in the plan.
- Keep expected outputs concrete and verifiable, and keep estimated time and complexity proportionate to the work.
- Return exactly the schema below as JSON; use only the listed domain types and specialist roles.

Classify the assignment into:
- domain_type: "THEORY_ACADEMIC" | "CODING_LAB" | "DIAGRAM_DESIGN" | "HEAVY_ML" | "QUANTITATIVE_MATH"
- deliverable_format: "academic_essay_report" | "runnable_code_with_terminal_output" | "drawio_diagram_xml" | "jupyter_colab_notebook"

Create a detailed execution plan as JSON:
{{
  "domain_type": "THEORY_ACADEMIC",
  "deliverable_format": "academic_essay_report",
  "subtasks": [
    {{
      "id": "sub_1",
      "description": "Specific action to take",
      "agent_role": "WRITER|CODER|MATH_SOLVER|RESEARCHER|DATA_ANALYST",
      "inputs_needed": ["data", "files", "references"],
      "expected_output": "Description of output",
      "depends_on": []
    }}
  ],
  "estimated_time_minutes": 15,
  "complexity": "LOW|MEDIUM|HIGH"
}}"""
    
    async def execute(self, task: AgentTask) -> AgentResult:
        if not self.llm_client:
            return AgentResult(
                requirement_id=task.requirement_id,
                role=AgentRole.PLANNER,
                success=False,
                output=None,
                error="LLM client not configured"
            )
        
        prompt = self.PLANNING_PROMPT.format(
            requirement=json.dumps(task.context.get("requirement", {}), indent=2),
            task_type=task.context.get("task_type", "other"),
            course_name=task.context.get("course_name", ""),
            other_requirements=task.context.get("other_requirements", []),
            available_tools=task.context.get("available_tools", [])
        )
        
        try:
            response = await self.llm_client.complete(prompt, temperature=0.2, max_tokens=2000)
            plan = _extract_json_object(response)
            required_keys = {"domain_type", "deliverable_format", "subtasks", "estimated_time_minutes", "complexity"}
            if not required_keys.issubset(plan):
                missing = sorted(required_keys - set(plan))
                raise ValueError(f"Planner response is missing required fields: {', '.join(missing)}")
            if not isinstance(plan.get("subtasks"), list) or not plan["subtasks"]:
                raise ValueError("Planner response must include at least one subtask")

            seen_ids = set()
            for subtask in plan["subtasks"]:
                if not isinstance(subtask, dict):
                    raise ValueError("Each planned subtask must be a JSON object")
                subtask_id = str(subtask.get("id") or "").strip()
                if not subtask_id or subtask_id in seen_ids:
                    raise ValueError("Each planned subtask must have a unique, non-empty id")
                seen_ids.add(subtask_id)

            for subtask in plan["subtasks"]:
                dependencies = subtask.get("depends_on") or []
                if not isinstance(dependencies, list):
                    raise ValueError(f"Dependencies for {subtask['id']} must be a list")
                if str(subtask["id"]) in set(map(str, dependencies)):
                    raise ValueError(f"Subtask {subtask['id']} cannot depend on itself")
                unknown = set(map(str, dependencies)) - seen_ids
                if unknown:
                    raise ValueError(f"Subtask {subtask['id']} references unknown dependencies: {', '.join(sorted(unknown))}")

            SolutionGenerator._validate_subtask_dependencies(plan["subtasks"])
            
            return AgentResult(
                requirement_id=task.requirement_id,
                role=AgentRole.PLANNER,
                success=True,
                output=plan,
                metadata={"subtask_count": len(plan.get("subtasks", []))}
            )
        except Exception as e:
            logger.error(f"Planner failed: {e}")
            return AgentResult(
                requirement_id=task.requirement_id,
                role=AgentRole.PLANNER,
                success=False,
                output=None,
                error=str(e)
            )


class WriterAgent(BaseAgent):
    """Generates written content (essays, reports, research papers)."""
    
    WRITING_PROMPT = """You are an expert academic writer. Generate high-quality content for the requirement.

REQUIREMENT:
{requirement}

CONSTRAINTS:
- Word count: {word_count}
- Format: {format_style}
- Language: {language}
- Required sections: {required_sections}
- Tone: Academic, formal, well-structured

CONTEXT:
- Course: {course_name} ({course_code})
- Assignment: {assignment_title}
- Student level: {student_level}
- Previous work samples: {previous_samples}

ADDITIONAL INSTRUCTIONS:
{additional_instructions}

Generate the content directly. Do not include meta-commentary.
Use proper academic structure with clear headings.
Include citations in {format_style} format where appropriate.
"""

    async def execute(self, task: AgentTask) -> AgentResult:
        if not self.llm_client:
            return AgentResult(
                requirement_id=task.requirement_id,
                role=AgentRole.WRITER,
                success=False,
                output=None,
                error="LLM client not configured"
            )
        
        req = task.context.get("requirement", {})
        constraints = req.get("constraints", {})
        
        prompt = self.WRITING_PROMPT.format(
            requirement=json.dumps(req, indent=2),
            word_count=constraints.get("word_count", "Not specified"),
            format_style=constraints.get("format", "APA"),
            language=constraints.get("language", "English"),
            required_sections=constraints.get("required_sections", []),
            course_name=task.context.get("course_name", ""),
            course_code=task.context.get("course_code", ""),
            assignment_title=task.context.get("assignment_title", ""),
            student_level=task.context.get("student_level", "Undergraduate"),
            previous_samples=task.context.get("previous_samples", "None"),
            additional_instructions=task.context.get("additional_instructions", "")
        )
        
        try:
            response = await self.llm_client.complete(prompt, temperature=0.7, max_tokens=8000)
            
            return AgentResult(
                requirement_id=task.requirement_id,
                role=AgentRole.WRITER,
                success=True,
                output={"content": response.strip(), "type": "document"},
                metadata={"word_count": len(response.split())}
            )
        except Exception as e:
            logger.error(f"Writer failed: {e}")
            return AgentResult(
                requirement_id=task.requirement_id,
                role=AgentRole.WRITER,
                success=False,
                output=None,
                error=str(e)
            )


class CoderAgent(BaseAgent):
    """Generates code solutions."""
    
    CODING_PROMPT = """You are an expert software engineer. Write production-quality code for the requirement.

REQUIREMENT:
{requirement}

CONSTRAINTS:
- Language: {language}
- Required libraries: {libraries}
- File types: {file_types}
- Complexity requirements: {complexity}
- Code style: Clean, documented, tested

CONTEXT:
- Course: {course_name} ({course_code})
- Assignment: {assignment_title}
- Related requirements: {related_requirements}

TECHNICAL SPECIFICATIONS:
{technical_specs}

Generate complete, runnable code files. Include:
1. Main solution file
2. Helper modules if needed
3. Requirements/dependencies file
4. Basic tests
5. README with usage instructions

Output as JSON:
{{
  "files": [
    {{"name": "main.py", "content": "...", "description": "Main solution"}},
    {{"name": "requirements.txt", "content": "...", "description": "Dependencies"}},
    {{"name": "test_main.py", "content": "...", "description": "Unit tests"}},
    {{"name": "README.md", "content": "...", "description": "Documentation"}}
  ]
}}
"""

    async def execute(self, task: AgentTask) -> AgentResult:
        if not self.llm_client:
            return AgentResult(
                requirement_id=task.requirement_id,
                role=AgentRole.CODER,
                success=False,
                output=None,
                error="LLM client not configured"
            )
        
        req = task.context.get("requirement", {})
        constraints = req.get("constraints", {})
        
        prompt = self.CODING_PROMPT.format(
            requirement=json.dumps(req, indent=2),
            language=constraints.get("language", "Python"),
            libraries=constraints.get("libraries", []),
            file_types=constraints.get("file_types", [".py"]),
            complexity=constraints.get("custom", {}).get("complexity", "Not specified"),
            course_name=task.context.get("course_name", ""),
            course_code=task.context.get("course_code", ""),
            assignment_title=task.context.get("assignment_title", ""),
            related_requirements=task.context.get("related_requirements", []),
            technical_specs=task.context.get("technical_specs", "Not provided")
        )
        
        try:
            response = await self.llm_client.complete(prompt, temperature=0.3, max_tokens=8000)
            
            # Parse JSON output
            json_str = response.strip()
            if "```json" in json_str:
                json_str = json_str.split("```json")[1].split("```")[0]
            elif "```" in json_str:
                json_str = json_str.split("```")[1].split("```")[0]
            
            result = json.loads(json_str)
            
            return AgentResult(
                requirement_id=task.requirement_id,
                role=AgentRole.CODER,
                success=True,
                output=result,
                metadata={"file_count": len(result.get("files", []))}
            )
        except Exception as e:
            logger.error(f"Coder failed: {e}")
            return AgentResult(
                requirement_id=task.requirement_id,
                role=AgentRole.CODER,
                success=False,
                output=None,
                error=str(e)
            )


class MathSolverAgent(BaseAgent):
    """Solves mathematical problems."""
    
    MATH_PROMPT = """You are an expert mathematician. Solve the problem step by step.

REQUIREMENT:
{requirement}

CONSTRAINTS:
- Show all steps: {show_steps}
- Format: {format_style}
- Tools allowed: {tools}

CONTEXT:
- Course: {course_name} ({course_code})
- Topic: {topic}
- Level: {level}

Provide:
1. Problem restatement
2. Given information
3. Step-by-step solution
4. Final answer clearly marked
5. Verification if applicable

Output as JSON:
{{
  "problem_statement": "...",
  "given": [...],
  "steps": [
    {{"step": 1, "description": "...", "calculation": "...", "result": "..."}}
  ],
  "final_answer": "...",
  "verification": "...",
  "latex": "..."  // Optional LaTeX for rendering
}}
"""

    async def execute(self, task: AgentTask) -> AgentResult:
        if not self.llm_client:
            return AgentResult(
                requirement_id=task.requirement_id,
                role=AgentRole.MATH_SOLVER,
                success=False,
                output=None,
                error="LLM client not configured"
            )
        
        req = task.context.get("requirement", {})
        constraints = req.get("constraints", {})
        
        prompt = self.MATH_PROMPT.format(
            requirement=json.dumps(req, indent=2),
            show_steps=constraints.get("custom", {}).get("show_steps", True),
            format_style=constraints.get("format", "Standard"),
            tools=constraints.get("custom", {}).get("tools", "Calculator, symbolic math"),
            course_name=task.context.get("course_name", ""),
            course_code=task.context.get("course_code", ""),
            topic=task.context.get("topic", "General Mathematics"),
            level=task.context.get("level", "Undergraduate")
        )
        
        try:
            response = await self.llm_client.complete(prompt, temperature=0.1, max_tokens=4000)
            
            json_str = response.strip()
            if "```json" in json_str:
                json_str = json_str.split("```json")[1].split("```")[0]
            elif "```" in json_str:
                json_str = json_str.split("```")[1].split("```")[0]
            
            result = json.loads(json_str)
            
            return AgentResult(
                requirement_id=task.requirement_id,
                role=AgentRole.MATH_SOLVER,
                success=True,
                output=result,
                metadata={"steps_count": len(result.get("steps", []))}
            )
        except Exception as e:
            logger.error(f"Math solver failed: {e}")
            return AgentResult(
                requirement_id=task.requirement_id,
                role=AgentRole.MATH_SOLVER,
                success=False,
                output=None,
                error=str(e)
            )


class ReviewerAgent(BaseAgent):
    """Reviews generated solutions against requirements."""
    
    REVIEW_PROMPT = """You are an expert academic reviewer. Evaluate the solution against requirements.

REQUIREMENT:
{requirement}

GENERATED SOLUTION:
{solution}

RUBRIC CRITERIA:
{rubric_criteria}

Evaluate:
1. Does the solution address ALL parts of the requirement?
2. Quality of content/code/analysis
3. Adherence to constraints (word count, format, language, etc.)
4. Academic rigor and correctness
5. Completeness of deliverables

Score each criterion (0-100) and provide overall assessment.

Output as JSON:
{{
  "requirement_id": "req_1",
  "meets_requirement": true/false,
  "criteria_scores": {{"criterion_name": score}},
  "overall_score": 85,
  "strengths": ["..."],
  "weaknesses": ["..."],
  "missing_elements": ["..."],
  "suggestions": ["..."],
  "confidence": 0.9
}}
"""

    async def execute(self, task: AgentTask) -> AgentResult:
        if not self.llm_client:
            return AgentResult(
                requirement_id=task.requirement_id,
                role=AgentRole.REVIEWER,
                success=False,
                output=None,
                error="LLM client not configured"
            )
        
        req = task.context.get("requirement", {})
        solution = task.context.get("solution", {})
        rubric = req.get("rubric_criteria", [])
        
        prompt = self.REVIEW_PROMPT.format(
            requirement=json.dumps(req, indent=2),
            solution=json.dumps(solution, indent=2)[:5000],
            rubric_criteria=json.dumps(rubric, indent=2)
        )
        
        try:
            response = await self.llm_client.complete(prompt, temperature=0.1, max_tokens=3000)
            
            json_str = response.strip()
            if "```json" in json_str:
                json_str = json_str.split("```json")[1].split("```")[0]
            elif "```" in json_str:
                json_str = json_str.split("```")[1].split("```")[0]
            
            result = json.loads(json_str)
            
            return AgentResult(
                requirement_id=task.requirement_id,
                role=AgentRole.REVIEWER,
                success=True,
                output=result,
                metadata={"overall_score": result.get("overall_score", 0)}
            )
        except Exception as e:
            logger.error(f"Reviewer failed: {e}")
            return AgentResult(
                requirement_id=task.requirement_id,
                role=AgentRole.REVIEWER,
                success=False,
                output=None,
                error=str(e)
            )


class SolutionGenerator:
    """Orchestrates the multi-agent solution generation pipeline."""
    
    def __init__(self, llm_client=None):
        self.llm_client = llm_client
        self.planner = PlannerAgent(llm_client)
        self.writer = WriterAgent(llm_client)
        self.coder = CoderAgent(llm_client)
        self.math_solver = MathSolverAgent(llm_client)
        self.reviewer = ReviewerAgent(llm_client)
    
    def _get_agent_for_requirement(self, requirement: Requirement) -> BaseAgent:
        """Select appropriate agent based on requirement type."""
        type_mapping = {
            RequirementType.WRITING: self.writer,
            RequirementType.CODING: self.coder,
            RequirementType.CALCULATION: self.math_solver,
            RequirementType.RESEARCH: self.writer,  # Uses writer with research focus
            RequirementType.FORMATTING: self.writer,
            RequirementType.CITATION: self.writer,
        }
        return type_mapping.get(requirement.type, self.writer)
    
    async def generate(
        self,
        requirements: ExtractedRequirements,
        assignment_context: Dict[str, Any],
        user_context: Dict[str, Any]
    ) -> SolutionPackage:
        """
        Generate complete solution for all requirements.
        """
        start_time = datetime.now()
        all_results = {}
        all_files = []
        content_by_req = {}
        requirements_met = []
        requirements_partial = []
        requirements_failed = []
        
        # Sort requirements by dependencies
        sorted_reqs = self._topological_sort(requirements.requirements)
        
        for req in sorted_reqs:
            logger.info(f"Processing requirement: {req.id} ({req.type})")

            blocked_dependencies = [
                dep for dep in (req.depends_on or [])
                if dep not in all_results or not all_results[dep].success
            ]
            if blocked_dependencies:
                result = AgentResult(
                    requirement_id=req.id,
                    role=AgentRole.WRITER,
                    success=False,
                    output=None,
                    error=f"Blocked by unsuccessful prerequisite(s): {', '.join(map(str, blocked_dependencies))}",
                )
                all_results[req.id] = result
                requirements_failed.append(req.id)
                logger.warning("Skipping requirement %s because dependencies failed: %s", req.id, blocked_dependencies)
                continue
            
            # Prepare context for this requirement
            req_context = {
                "requirement": req.dict(),
                "task_type": requirements.task_type.value,
                "course_name": assignment_context.get("course_name", ""),
                "course_code": assignment_context.get("course_code", ""),
                "assignment_title": assignment_context.get("title", ""),
                "student_level": user_context.get("level", "Undergraduate"),
                "previous_samples": user_context.get("writing_samples", []),
                "related_requirements": [r.id for r in requirements.requirements if r.id != req.id],
                "technical_specs": assignment_context.get("technical_specs", ""),
                "available_tools": ["web_search", "code_execution", "latex_rendering"]
            }
            
            # Get appropriate agent
            agent = self._get_agent_for_requirement(req)
            
            # Execute
            task = AgentTask(
                requirement_id=req.id,
                role=AgentRole(req.type.value.lower()) if req.type.value.lower() in [r.value for r in AgentRole] else AgentRole.WRITER,
                prompt="",
                context=req_context
            )
            
            result = await agent.execute(task)
            all_results[req.id] = result
            
            if result.success:
                content_by_req[req.id] = result.output
                requirements_met.append(req.id)
                
                # Convert to GeneratedFile(s)
                files = self._convert_to_files(req, result.output)
                all_files.extend(files)
            else:
                requirements_failed.append(req.id)
                logger.error(f"Requirement {req.id} failed: {result.error}")
        
        # Review phase
        review_results = {}
        for req in requirements.requirements:
            if req.id in requirements_met:
                review_task = AgentTask(
                    requirement_id=req.id,
                    role=AgentRole.REVIEWER,
                    prompt="",
                    context={
                        "requirement": req.dict(),
                        "solution": content_by_req.get(req.id, {})
                    }
                )
                review_result = await self.reviewer.execute(review_task)
                review_results[req.id] = review_result
                
                if review_result.success and isinstance(review_result.output, dict) and review_result.output.get("meets_requirement"):
                    pass  # Already in met
                elif review_result.success and isinstance(review_result.output, dict):
                    requirements_partial.append(req.id)
                    if req.id in requirements_met:
                        requirements_met.remove(req.id)
                elif not review_result.success:
                    logger.warning("Reviewer could not verify requirement %s: %s", req.id, review_result.error)
        
        # Calculate overall confidence
        total_reqs = len(requirements.requirements)
        met_count = len(requirements_met)
        partial_count = len(requirements_partial)
        confidence = (met_count + 0.5 * partial_count) / total_reqs if total_reqs > 0 else 0
        
        # Generate reviewer feedback summary
        reviewer_feedback = self._generate_feedback_summary(review_results)
        
        generation_time = int((datetime.now() - start_time).total_seconds() * 1000)
        
        return SolutionPackage(
            files=all_files,
            content=content_by_req,
            metadata={
                "requirements_processed": total_reqs,
                "agent_results": {k: v.metadata for k, v in all_results.items() if v.success},
                "review_results": {k: v.output for k, v in review_results.items() if v.success}
            },
            ai_model="gpt-4o",  # Would be dynamic
            generation_time_ms=generation_time,
            confidence=confidence,
            requirements_met=requirements_met,
            requirements_partial=requirements_partial,
            requirements_failed=requirements_failed,
            reviewer_feedback=reviewer_feedback
        )
    
    def _topological_sort(self, requirements: List[Requirement]) -> List[Requirement]:
        """Return requirements in dependency order; reject missing links and cycles."""
        req_map = {r.id: r for r in requirements}
        state = {}
        sorted_ids = []
        
        def visit(req_id):
            current = state.get(req_id, 0)
            if current == 2:
                return
            if current == 1:
                raise ValueError(f"Requirement dependency cycle detected at {req_id}")
            req = req_map.get(req_id)
            if req is None:
                raise ValueError(f"Requirement dependency references unknown id {req_id}")
            state[req_id] = 1
            for dep in req.depends_on or []:
                if dep not in req_map:
                    raise ValueError(f"Requirement {req_id} depends on unknown requirement {dep}")
                visit(dep)
            state[req_id] = 2
            sorted_ids.append(req_id)
        
        for req in requirements:
            visit(req.id)
        
        return [req_map[rid] for rid in sorted_ids]

    @staticmethod
    def _validate_subtask_dependencies(subtasks: List[Dict[str, Any]]) -> None:
        """Ensure planner dependencies form a valid acyclic graph."""
        subtask_map = {str(item["id"]): item for item in subtasks}
        state = {}

        def visit(subtask_id: str) -> None:
            current = state.get(subtask_id, 0)
            if current == 1:
                raise ValueError(f"Planner dependency cycle detected at {subtask_id}")
            if current == 2:
                return
            state[subtask_id] = 1
            for dependency in subtask_map[subtask_id].get("depends_on") or []:
                visit(str(dependency))
            state[subtask_id] = 2

        for subtask_id in subtask_map:
            visit(subtask_id)
    
    def _convert_to_files(self, requirement: Requirement, output: Any) -> List[GeneratedFile]:
        """Convert agent output to GeneratedFile objects."""
        files = []
        
        if isinstance(output, dict):
            if "files" in output:
                # Coder output format
                for f in output["files"]:
                    files.append(GeneratedFile(
                        name=f["name"],
                        content=f["content"],
                        mime_type=self._get_mime_type(f["name"]),
                        size_bytes=len(f["content"].encode()),
                        requirement_ids=[requirement.id]
                    ))
            elif "content" in output:
                # Writer output format
                ext = self._get_extension_for_deliverable(requirement.deliverable)
                files.append(GeneratedFile(
                    name=f"{requirement.id}{ext}",
                    content=output["content"],
                    mime_type=self._get_mime_type(f"{requirement.id}{ext}"),
                    size_bytes=len(output["content"].encode()),
                    requirement_ids=[requirement.id]
                ))
            else:
                # Generic JSON output
                files.append(GeneratedFile(
                    name=f"{requirement.id}.json",
                    content=json.dumps(output, indent=2),
                    mime_type="application/json",
                    size_bytes=len(json.dumps(output).encode()),
                    requirement_ids=[requirement.id]
                ))
        
        return files
    
    def _get_extension_for_deliverable(self, deliverable: DeliverableType) -> str:
        mapping = {
            DeliverableType.DOCUMENT: ".md",
            DeliverableType.CODE_FILE: ".py",
            DeliverableType.SPREADSHEET: ".csv",
            DeliverableType.PRESENTATION: ".md",
            DeliverableType.PDF: ".pdf",
            DeliverableType.IMAGE: ".png",
            DeliverableType.ARCHIVE: ".zip",
        }
        return mapping.get(deliverable, ".txt")
    
    def _get_mime_type(self, filename: str) -> str:
        ext = filename.split(".")[-1].lower() if "." in filename else ""
        mime_types = {
            "py": "text/x-python",
            "js": "application/javascript",
            "ts": "application/typescript",
            "java": "text/x-java-source",
            "cpp": "text/x-c++src",
            "c": "text/x-csrc",
            "md": "text/markdown",
            "txt": "text/plain",
            "json": "application/json",
            "csv": "text/csv",
            "pdf": "application/pdf",
            "png": "image/png",
            "jpg": "image/jpeg",
            "zip": "application/zip",
        }
        return mime_types.get(ext, "text/plain")
    
    def _generate_feedback_summary(self, review_results: Dict[str, AgentResult]) -> str:
        """Generate human-readable feedback summary."""
        if not review_results:
            return "No review performed."
        
        summary = []
        for req_id, result in review_results.items():
            if result.success and result.output:
                score = result.output.get("overall_score", 0)
                meets = result.output.get("meets_requirement", False)
                status = "✓ PASS" if meets else "⚠ PARTIAL"
                summary.append(f"{req_id}: {status} (Score: {score}/100)")
                if result.output.get("weaknesses"):
                    summary.append(f"  Issues: {', '.join(result.output['weaknesses'][:3])}")
        
        return "\n".join(summary)
