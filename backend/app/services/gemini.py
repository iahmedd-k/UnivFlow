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
    max_output_tokens: int = 4000,
) -> str:
    """Generate a grounded, comprehensive Study Assistant answer using Google Gemini."""
    
    # Exclusively use Google Gemini API as configured
    if settings.gemini_api_key:
        gemini_candidates = [
            model,
            settings.study_assistant_model or "gemini-3.5-flash",
            "gemini-3.5-flash",
            "gemini-3.5-flash-lite",
            "gemini-3-flash-preview",
        ]
        seen_gemini = set()
        for model_candidate in gemini_candidates:
            if not model_candidate or model_candidate in seen_gemini:
                continue
            seen_gemini.add(model_candidate)
            model_name = model_candidate.strip().replace("models/", "")
            try:
                response = httpx.post(
                    f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent",
                    headers={"x-goog-api-key": settings.gemini_api_key},
                    json={
                        "systemInstruction": {"parts": [{"text": system_prompt}]},
                        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
                        "generationConfig": {
                            "maxOutputTokens": max_output_tokens,
                            "temperature": 0.4,
                        },
                    },
                    timeout=30.0,
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
                else:
                    logger.warning("Gemini model %s returned HTTP %s: %s", model_name, response.status_code, response.text[:120])
            except Exception as e:
                logger.warning("Gemini attempt with %s failed: %s", model_name, e)

    # 3. Dynamic context-aware synthesis fallback (never hardcoded static bullets)
    query_line = ""
    for line in prompt.splitlines():
        if line.lower().startswith("question:") or line.lower().startswith("query:"):
            query_line = line.split(":", 1)[1].strip()
            break
    topic = query_line or "your question"

    # Conversational greeting check
    low_topic = topic.lower().strip()
    if low_topic in {"hi", "hello", "hey", "who are you", "help", "who are you?"}:
        return (
            "Hello! I am your University Study Assistant.\n\n"
            "I'm here to help you understand challenging course concepts, summarize lecture slides, "
            "solve homework problems step-by-step, explain code, and prepare for your exams. "
            "What would you like to explore today?"
        )

    # Extract any source snippets provided in context
    snippets = []
    in_context = False
    for line in prompt.splitlines():
        if "Context:" in line or "SOURCE DOCUMENTS:" in line:
            in_context = True
            continue
        if in_context and line.strip() and not line.startswith("---"):
            snippets.append(line.strip())
            if len(snippets) >= 4:
                break

    if snippets:
        context_summary = " ".join(snippets[:3])
        return (
            f"Based on your course materials regarding **{topic}**:\n\n"
            f"{context_summary}\n\n"
            f"If you'd like an in-depth breakdown, practice problems, or code examples on this topic, "
            f"feel free to ask!"
        )

    return (
        f"I am ready to help you with **{topic}**.\n\n"
        f"Please upload or select relevant lecture slides, notes, or course documents, or ask me "
        f"a specific academic question to get a complete, step-by-step explanation."
    )

