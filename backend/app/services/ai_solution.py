import json
import httpx
from typing import Optional, Dict, Any
from sqlalchemy.orm import Session
from app.db.models import Assignment, AssignmentSolution, AssignmentMaterial
from app.core.config import settings
from app.core.logging import logger


def generate_solution(db: Session, assignment_id: int, provider: str = "groq", model: str = "openai/gpt-oss-120b") -> Dict[str, Any]:
    """Generate AI solution for an assignment"""
    assignment = db.query(Assignment).filter(Assignment.id == assignment_id).first()
    if not assignment:
        return {"error": "Assignment not found"}
    
    solution = db.query(AssignmentSolution).filter(AssignmentSolution.assignment_id == assignment_id).first()
    if not solution:
        solution = AssignmentSolution(assignment_id=assignment_id)
        db.add(solution)
    
    # Gather context: assignment description + materials
    materials = db.query(AssignmentMaterial).filter(AssignmentMaterial.assignment_id == assignment_id).all()
    material_texts = []
    for m in materials:
        if m.content:
            material_texts.append(f"Material: {m.title}\n{m.content}")
        elif m.url:
            material_texts.append(f"Material: {m.title}\nURL: {m.url}")
    
    materials_context = "\n\n".join(material_texts) if material_texts else "No additional materials provided."
    
    prompt = f"""You are an expert academic assistant. Solve the following assignment completely and accurately.

ASSIGNMENT: {assignment.title}
DESCRIPTION: {assignment.description or "No description provided"}
WORK TYPE: {assignment.work_type or "ASSIGNMENT"}
IS QUIZ: {assignment.is_quiz}

MATERIALS:
{materials_context}

Provide a complete, well-structured solution. Include:
1. Step-by-step explanation
2. Final answer/code
3. Any assumptions made

Format as clear markdown."""
    
    try:
        if provider == "groq":
            result = _call_groq(prompt, model)
        elif provider == "claude":
            result = _call_claude(prompt, model)
        else:
            result = _call_groq(prompt, model)
        
        solution.draft_content = result
        solution.ai_provider = provider
        solution.generated_at = db.query(AssignmentSolution).filter(AssignmentSolution.assignment_id == assignment_id).first().generated_at
        db.commit()
        
        return {"status": "generated", "content": result}
    
    except Exception as e:
        logger.error(f"AI generation failed: {e}")
        solution.validation_errors = str(e)
        db.commit()
        return {"error": str(e)}


def _call_groq(prompt: str, model: str) -> str:
    api_key = settings.groq_api_key
    if not api_key:
        raise ValueError("GROQ_API_KEY not configured")
    
    with httpx.Client(timeout=60.0) as client:
        resp = client.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": "You are an expert academic assistant. Provide complete, accurate solutions with clear explanations."},
                    {"role": "user", "content": prompt}
                ],
                "temperature": 0.1,
                "max_tokens": 4000
            }
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]


def _call_claude(prompt: str, model: str) -> str:
    # Placeholder for Claude API integration
    raise NotImplementedError("Claude provider not yet implemented")


def validate_solution(db: Session, assignment_id: int) -> Dict[str, Any]:
    """Validate AI solution by checking against requirements"""
    solution = db.query(AssignmentSolution).filter(AssignmentSolution.assignment_id == assignment_id).first()
    if not solution or not solution.draft_content:
        return {"error": "No draft solution to validate"}
    
    assignment = db.query(Assignment).filter(Assignment.id == assignment_id).first()
    
    validation_prompt = f"""Review the following AI-generated solution for correctness and completeness.

ORIGINAL ASSIGNMENT: {assignment.title}
DESCRIPTION: {assignment.description or "No description"}

AI SOLUTION:
{solution.draft_content}

Check for:
1. Correctness of approach
2. Completeness (all parts addressed)
3. Clarity of explanation
4. Any errors or missing steps

Respond with JSON:
{{
  "is_valid": true/false,
  "errors": ["list of issues if any"],
  "suggestions": ["improvement suggestions"]
}}"""
    
    try:
        validation_result = _call_groq(validation_prompt, "openai/gpt-oss-120b")
        import re
        json_match = re.search(r"\{[\s\S]*\}", validation_result)
        if json_match:
            result = json.loads(json_match.group(0))
            if result.get("is_valid"):
                solution.validated_content = solution.draft_content
                solution.validated_at = db.query(AssignmentSolution).filter(AssignmentSolution.assignment_id == assignment_id).first().validated_at
                solution.validation_errors = None
            else:
                solution.validation_errors = json.dumps(result.get("errors", []))
            db.commit()
            return result
    except Exception as e:
        logger.error(f"Validation failed: {e}")
        solution.validation_errors = str(e)
        db.commit()
    
    return {"error": "Validation failed"}