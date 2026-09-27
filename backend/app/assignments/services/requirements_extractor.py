import json
import logging
from typing import Optional, List, Dict, Any
from datetime import datetime

from app.assignments.schemas.assignment import (
    ParsedDocument, ExtractedRequirements, Requirement, 
    Deliverable, TaskType, RequirementType, DeliverableType, 
    SubmissionFormat, ConstraintModel, RubricCriterion
)

logger = logging.getLogger(__name__)


REQUIREMENTS_EXTRACTION_PROMPT = """You are an expert academic assignment analyzer. Analyze the assignment document and extract structured requirements.

ASSIGNMENT CONTEXT:
- Title: {title}
- Course: {course_name} ({course_code})
- Due Date: {due_date}
- Description: {description}

DOCUMENT CONTENT:
{document_content}

DOCUMENT STRUCTURE:
{document_structure}

Extract the following as JSON:

{{
  "task_type": "essay|code|math|report|presentation|data_analysis|research|other",
  "requirements": [
    {{
      "id": "req_1",
      "description": "Clear, specific description of what is required",
      "type": "WRITING|CODING|CALCULATION|RESEARCH|FORMATTING|CITATION",
      "priority": "HIGH|MEDIUM|LOW",
      "deliverable": "DOCUMENT|CODE_FILE|SPREADSHEET|PRESENTATION|PDF|IMAGE|ARCHIVE",
      "constraints": {{
        "word_count": 1500,
        "format": "APA|MLA|IEEE|CHICAGO|NONE",
        "language": "Python|Java|C++|JavaScript|R|MATLAB|NONE",
        "libraries": ["pandas", "numpy"],
        "required_sections": ["Introduction", "Methodology", "Results", "Conclusion"],
        "prohibited_content": [],
        "file_types": [".py", ".pdf"],
        "max_file_size_mb": 10,
        "custom": {{}}
      }},
      "rubric_criteria": [
        {{"criterion": "Analysis depth", "weight": 30, "description": "Depth of analysis"}},
        {{"criterion": "Code quality", "weight": 25, "description": "Clean, documented code"}}
      ],
      "depends_on": []
    }}
  ],
  "deliverables": [
    {{"name": "main.py", "type": "CODE_FILE", "required": true, "description": "Main solution file"}},
    {{"name": "report.pdf", "type": "DOCUMENT", "required": true, "description": "Written report"}}
  ],
  "submission_format": "GOOGLE_DOC|FILE_UPLOAD|GITHUB_REPO|LMS_NATIVE",
  "template_required": false,
  "template_doc_id": null,
  "confidence": 0.95
}}

RULES:
1. Be specific - "Write code" is bad, "Implement Dijkstra's algorithm in Python with O(E log V) complexity" is good
2. Identify ALL deliverables explicitly mentioned
3. Detect citation style (APA, MLA, IEEE) from context
4. Detect programming language from code snippets or course context
5. Extract rubric if provided, otherwise infer from requirements
6. Set confidence based on clarity of requirements (0.0-1.0)
7. If template is mentioned or implied, set template_required=true
8. For code tasks, identify required libraries/frameworks
9. For writing tasks, identify word count, format, sections
10. Mark dependencies between requirements (e.g., "report depends on code output")
"""


class RequirementsExtractor:
    def __init__(self, llm_client=None):
        self.llm_client = llm_client
    
    async def extract(
        self,
        document: ParsedDocument,
        assignment_title: str,
        course_name: str,
        course_code: str,
        due_date: datetime,
        description: str = "",
        user_context: Optional[Dict[str, Any]] = None
    ) -> ExtractedRequirements:
        """
        Extract structured requirements from assignment document.
        """
        # Prepare document content for LLM
        doc_content = self._prepare_document_content(document)
        doc_structure = self._prepare_document_structure(document)
        
        prompt = REQUIREMENTS_EXTRACTION_PROMPT.format(
            title=assignment_title,
            course_name=course_name,
            course_code=course_code,
            due_date=due_date.isoformat() if due_date else "Not specified",
            description=description or "Not provided",
            document_content=doc_content[:15000],  # Limit for token budget
            document_structure=json.dumps(doc_structure, indent=2)
        )
        
        if self.llm_client:
            response = await self.llm_client.complete(prompt, temperature=0.1, max_tokens=4000)
            return self._parse_llm_response(response)
        else:
            # Fallback: basic heuristic extraction
            return self._heuristic_extraction(document, assignment_title)
    
    def _prepare_document_content(self, document: ParsedDocument) -> str:
        """Prepare document content for LLM analysis."""
        parts = []
        
        if document.metadata.title:
            parts.append(f"DOCUMENT TITLE: {document.metadata.title}")
        
        parts.append(f"FULL TEXT:\n{document.content}")
        
        return "\n\n".join(parts)
    
    def _prepare_document_structure(self, document: ParsedDocument) -> Dict[str, Any]:
        """Prepare document structure summary."""
        return {
            "headings_count": len(document.structure.headings),
            "headings": [{"level": h.get("level"), "text": h.get("text")[:100]} for h in document.structure.headings[:20]],
            "tables_count": len(document.structure.tables),
            "images_count": len(document.structure.images),
            "links_count": len(document.structure.links),
            "code_blocks_count": len(document.structure.code_blocks),
            "word_count": document.metadata.word_count,
            "page_count": document.metadata.page_count
        }
    
    def _parse_llm_response(self, response: str) -> ExtractedRequirements:
        """Parse LLM JSON response into ExtractedRequirements."""
        try:
            # Extract JSON from response (handle markdown code blocks)
            json_str = response
            if "```json" in response:
                json_str = response.split("```json")[1].split("```")[0]
            elif "```" in response:
                json_str = response.split("```")[1].split("```")[0]
            
            data = json.loads(json_str.strip())
            
            # Convert to Pydantic models
            requirements = [Requirement(**req) for req in data.get("requirements", [])]
            deliverables = [Deliverable(**d) for d in data.get("deliverables", [])]
            
            return ExtractedRequirements(
                task_type=TaskType(data.get("task_type", "other")),
                requirements=requirements,
                deliverables=deliverables,
                submission_format=SubmissionFormat(data.get("submission_format", "FILE_UPLOAD")),
                template_required=data.get("template_required", False),
                template_doc_id=data.get("template_doc_id"),
                confidence=data.get("confidence", 0.8),
                raw_analysis=response
            )
        except Exception as e:
            logger.error(f"Failed to parse LLM response: {e}")
            logger.debug(f"Response: {response[:500]}")
            raise
    
    def _heuristic_extraction(
        self,
        document: ParsedDocument,
        assignment_title: str
    ) -> ExtractedRequirements:
        """Fallback heuristic extraction when LLM unavailable."""
        content_lower = document.content.lower()
        
        # Detect task type
        task_type = TaskType.OTHER
        if any(kw in content_lower for kw in ["code", "program", "implement", "function", "algorithm", "script"]):
            task_type = TaskType.CODE
        elif any(kw in content_lower for kw in ["essay", "write", "discuss", "analyze", "argue", "reflect"]):
            task_type = TaskType.ESSAY
        elif any(kw in content_lower for kw in ["report", "laboratory", "lab report", "experiment"]):
            task_type = TaskType.REPORT
        elif any(kw in content_lower for kw in ["presentation", "slides", "present"]):
            task_type = TaskType.PRESENTATION
        elif any(kw in content_lower for kw in ["data", "analyze", "dataset", "statistics", "visualization"]):
            task_type = TaskType.DATA_ANALYSIS
        elif any(kw in content_lower for kw in ["research", "literature review", "cite", "bibliography"]):
            task_type = TaskType.RESEARCH
        elif any(kw in content_lower for kw in ["calculate", "solve", "prove", "derive", "equation"]):
            task_type = TaskType.MATH
        
        # Basic requirements
        requirements = []
        
        # Word count detection
        import re
        word_count_match = re.search(r'(\d+)\s*words?', content_lower)
        word_count = int(word_count_match.group(1)) if word_count_match else None
        
        # Format detection
        format_style = None
        if "apa" in content_lower:
            format_style = "APA"
        elif "mla" in content_lower:
            format_style = "MLA"
        elif "ieee" in content_lower:
            format_style = "IEEE"
        elif "chicago" in content_lower:
            format_style = "CHICAGO"
        
        # Language detection
        language = None
        if "python" in content_lower:
            language = "Python"
        elif "java" in content_lower:
            language = "Java"
        elif "c++" in content_lower or "cpp" in content_lower:
            language = "C++"
        elif "javascript" in content_lower or "js" in content_lower:
            language = "JavaScript"
        elif "r " in content_lower or "rstudio" in content_lower:
            language = "R"
        elif "matlab" in content_lower:
            language = "MATLAB"
        
        # Build requirement based on task type
        if task_type == TaskType.CODE:
            requirements.append(Requirement(
                id="req_1",
                description=f"Implement the required solution in {language or 'the specified language'}",
                type=RequirementType.CODING,
                priority="HIGH",
                deliverable=DeliverableType.CODE_FILE,
                constraints=ConstraintModel(
                    language=language,
                    libraries=[],
                    file_types=[f".{language.lower()}" if language else ".py"]
                )
            ))
            deliverables = [Deliverable(name="solution.py", type=DeliverableType.CODE_FILE, required=True)]
        
        elif task_type in [TaskType.ESSAY, TaskType.REPORT, TaskType.RESEARCH]:
            requirements.append(Requirement(
                id="req_1",
                description=f"Write a {word_count or 'specified length'} {task_type.value} on the given topic",
                type=RequirementType.WRITING,
                priority="HIGH",
                deliverable=DeliverableType.DOCUMENT,
                constraints=ConstraintModel(
                    word_count=word_count,
                    format=format_style,
                    required_sections=["Introduction", "Body", "Conclusion"] if task_type == TaskType.ESSAY else 
                                   ["Abstract", "Introduction", "Methodology", "Results", "Discussion", "Conclusion"]
                )
            ))
            deliverables = [Deliverable(name="report.pdf", type=DeliverableType.DOCUMENT, required=True)]
        
        else:
            requirements.append(Requirement(
                id="req_1",
                description=f"Complete the {task_type.value} assignment",
                type=RequirementType.WRITING,
                priority="HIGH",
                deliverable=DeliverableType.DOCUMENT,
                constraints=ConstraintModel(word_count=word_count, format=format_style)
            ))
            deliverables = [Deliverable(name="submission.pdf", type=DeliverableType.DOCUMENT, required=True)]
        
        # Add formatting requirement if format detected
        if format_style:
            requirements.append(Requirement(
                id="req_format",
                description=f"Format document in {format_style} style with proper citations",
                type=RequirementType.FORMATTING,
                priority="MEDIUM",
                deliverable=DeliverableType.DOCUMENT,
                constraints=ConstraintModel(format=format_style)
            ))
        
        return ExtractedRequirements(
            task_type=task_type,
            requirements=requirements,
            deliverables=deliverables,
            submission_format=SubmissionFormat.FILE_UPLOAD,
            template_required=False,
            confidence=0.6
        )