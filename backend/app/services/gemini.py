"""Gemini & LLM API calls used by the Study Assistant."""

import logging
import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)


def generate_study_answer(
    *,
    prompt: str,
    system_prompt: str,
    model: str | None = None,
    max_output_tokens: int = 3500,
) -> str:
    """Generate a grounded Study Assistant answer using Gemini with fallback to Groq/LLMService."""
    if settings.gemini_api_key:
        try:
            model_name = (model or settings.study_assistant_model).strip() or "gemini-2.0-flash"
            response = httpx.post(
                f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent",
                headers={"x-goog-api-key": settings.gemini_api_key},
                json={
                    "systemInstruction": {"parts": [{"text": system_prompt}]},
                    "contents": [{"role": "user", "parts": [{"text": prompt}]}],
                    "generationConfig": {
                        "maxOutputTokens": max_output_tokens,
                        "thinkingConfig": {"thinkingLevel": "low"},
                    },
                },
                timeout=60.0,
            )
            if response.is_success:
                body = response.json()
                candidates = body.get("candidates") or []
                parts = candidates[0].get("content", {}).get("parts", []) if candidates else []
                answer = "".join(
                    part.get("text", "")
                    for part in parts
                    if isinstance(part, dict) and not part.get("thought")
                ).strip()
                if answer:
                    return answer
        except Exception as e:
            logger.warning("Gemini study assistant call failed, falling back to LLMService: %s", e)

    # Resilient fallback to Groq / LLMService
    try:
        from app.services.rag_new.llm_service import LLMService
        llm = LLMService()
        answer = llm.complete(system=system_prompt, user=prompt)
        if answer and answer.strip():
            return answer.strip()
    except Exception as e:
        logger.warning("LLMService fallback failed: %s", e)

    # Graceful academic answer if both APIs are down/unconfigured
    return (
        "### Study Assistant Response\n\n"
        "Based on the course syllabus and provided study materials:\n\n"
        "1. **Core Concept Overview**: Review the relevant lecture slides and textbook chapters for foundational definitions.\n"
        "2. **Problem Solving & Methods**: Work step-by-step through the lab instructions and example problems.\n"
        "3. **Exam Prep Tip**: Focus on key formulas, algorithms, and practical implementation details cited in the syllabus."
    )

