"""Gemini API calls used by the Study Assistant."""

import httpx

from app.core.config import settings


def generate_study_answer(
    *,
    prompt: str,
    system_prompt: str,
    model: str | None = None,
    max_output_tokens: int = 3500,
) -> str:
    """Generate a grounded Study Assistant answer using Gemini."""
    if not settings.gemini_api_key:
        raise ValueError("GEMINI_API_KEY is not configured in the environment.")

    model_name = (model or settings.study_assistant_model).strip()
    if not model_name:
        raise ValueError("A Gemini model must be configured for the Study Assistant.")

    response = httpx.post(
        f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:generateContent",
        headers={"x-goog-api-key": settings.gemini_api_key},
        json={
            "systemInstruction": {"parts": [{"text": system_prompt}]},
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            # Gemini 3 models use their default thinking level; omit deprecated
            # sampling parameters so the request stays compatible with 3.8.
            "generationConfig": {
                "maxOutputTokens": max_output_tokens,
                "thinkingConfig": {"thinkingLevel": "low"},
            },
        },
        timeout=90.0,
    )
    if not response.is_success:
        raise RuntimeError(
            f"Gemini Study Assistant request failed ({response.status_code}): "
            f"{response.text[:1000]}"
        )

    try:
        body = response.json()
        candidates = body.get("candidates") or []
        parts = candidates[0].get("content", {}).get("parts", [])
        answer = "".join(
            part.get("text", "")
            for part in parts
            if isinstance(part, dict) and not part.get("thought")
        ).strip()
    except (IndexError, AttributeError, TypeError, ValueError) as error:
        raise RuntimeError("Gemini returned no usable Study Assistant answer.") from error

    if not answer:
        finish_reason = candidates[0].get("finishReason", "unknown") if candidates else "no_candidate"
        raise RuntimeError(f"Gemini returned no text answer (finish reason: {finish_reason}).")
    return answer
