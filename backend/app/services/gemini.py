"""Gemini & LLM API calls used by the Study Assistant."""

import logging
import time
from urllib.parse import urlsplit, urlunsplit

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)


def _generate_groq_answer(
    *,
    prompt: str,
    system_prompt: str,
    max_output_tokens: int,
) -> str | None:
    if not settings.groq_api_key:
        return None

    base_url = urlsplit(settings.groq_base_url.rstrip("/"))
    base_path = base_url.path.rstrip("/")
    if base_url.hostname == "api.groq.com" and not base_path:
        base_path = "/openai/v1"
    endpoint = urlunsplit(
        (base_url.scheme, base_url.netloc, f"{base_path}/chat/completions", "", "")
    )

    try:
        response = httpx.post(
            endpoint,
            headers={"Authorization": f"Bearer {settings.groq_api_key}"},
            json={
                "model": settings.groq_chat_model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": prompt},
                ],
                "temperature": 0.4,
                "max_tokens": max_output_tokens,
            },
            timeout=20.0,
        )
        if response.is_success:
            body = response.json()
            choices = body.get("choices") or []
            answer = (
                choices[0].get("message", {}).get("content", "")
                if choices
                else ""
            )
            if isinstance(answer, str) and answer.strip():
                return answer.strip()
            logger.warning("Groq fallback returned an empty answer")
        else:
            logger.warning(
                "Groq fallback returned HTTP %s: %s",
                response.status_code,
                response.text[:120],
            )
    except Exception as e:
        logger.warning("Groq fallback failed: %s", e)
    return None


def generate_study_answer(
    *,
    prompt: str,
    system_prompt: str,
    model: str | None = None,
    max_output_tokens: int = 4000,
    general_knowledge: bool = False,
) -> str:
    """Generate a comprehensive Study Assistant answer using configured LLM providers."""

    # An explicit Gemini model is used for source-index jobs. Respect that
    # request even when Groq is the general chat provider.
    groq_first = settings.ai_provider.strip().lower() == "groq" and not model
    if groq_first:
        answer = _generate_groq_answer(
            prompt=prompt,
            system_prompt=system_prompt,
            max_output_tokens=max_output_tokens,
        )
        if answer:
            return answer

    if settings.gemini_api_key:
        # Current free-tier models. Keep this short: retrying retired aliases burns
        # the request deadline before a usable model gets a chance to respond.
        gemini_candidates = (
            [model, "gemini-3.1-flash-lite"]
            if model
            else [settings.study_assistant_model or "gemini-3.6-flash", "gemini-3.1-flash-lite"]
        )
        seen_gemini = set()
        deadline = time.monotonic() + 55
        for model_candidate in gemini_candidates:
            if not model_candidate or model_candidate in seen_gemini:
                continue
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
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
                    timeout=min(35.0, remaining),
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

    if not groq_first:
        answer = _generate_groq_answer(
            prompt=prompt,
            system_prompt=system_prompt,
            max_output_tokens=max_output_tokens,
        )
        if answer:
            return answer

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

    if snippets and not general_knowledge:
        context_summary = " ".join(snippets[:3])
        return (
            f"Based on your course materials regarding **{topic}**:\n\n"
            f"{context_summary}\n\n"
            f"If you'd like an in-depth breakdown, practice problems, or code examples on this topic, "
            f"feel free to ask!"
        )

    if general_knowledge:
        return (
            "I can answer general questions, but the AI service is temporarily unavailable. "
            "Please try again shortly."
        )

    return (
        f"I am ready to help you with **{topic}**.\n\n"
        f"Please upload or select relevant lecture slides, notes, or course documents, or ask me "
        f"a specific academic question to get a complete, step-by-step explanation."
    )
