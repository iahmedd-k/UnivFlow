"""Model assignments and optional direct clients for the four CrewAI roles."""

from dataclasses import dataclass
from typing import Literal

import httpx

from app.core.config import settings


Provider = Literal["groq", "gemini"]


@dataclass(frozen=True)
class AgentModel:
    role: str
    provider: Provider
    model: str


def normalize_model_name(provider: Provider, raw_model: str) -> str:
    cleaned = (raw_model or "").strip()
    if provider == "gemini":
        if cleaned.startswith("gemini/"):
            cleaned = cleaned[7:]
        # Gemini 2.0 Flash is no longer a safe default. Also prevent a legacy
        # Groq model value from being sent to Google's model endpoint.
        if cleaned in ("gemini-2.0-flash", "gemini-flash", "gemini-pro", "") or not cleaned.startswith("gemini-"):
            return "gemini-3.8-flash"
        return cleaned
    elif provider == "groq":
        if cleaned.startswith("groq/"):
            cleaned = cleaned[5:]
        if cleaned in ("openai/gpt-oss-120b", "openai/gpt-oss-20b", "qwen/qwen3.8-27b", ""):
            return "llama-3.3-70b-versatile"
        return cleaned
    return cleaned


def get_agent_models() -> dict[str, AgentModel]:
    """Return the configured model for each independently addressable role."""
    return {
        "planner": AgentModel("planner", "gemini", normalize_model_name("gemini", settings.planner_agent_model)),
        "theory_research": AgentModel("theory_research", "gemini", normalize_model_name("gemini", settings.theory_agent_model)),
        "coder_diagram": AgentModel("coder_diagram", "groq", normalize_model_name("groq", settings.coder_agent_model)),
        "reporter_fixer": AgentModel("reporter_fixer", "gemini", normalize_model_name("gemini", settings.reporter_agent_model)),
    }


class AgentModelClient:
    """Small async completion client for Groq and Gemini model endpoints."""

    def __init__(self, agent: AgentModel, api_key: str | None = None):
        self.agent = agent
        self.api_key = api_key if api_key is not None else (
            settings.groq_api_key if agent.provider == "groq" else settings.gemini_api_key
        )

    async def complete(
        self,
        prompt: str,
        *,
        temperature: float = 0.2,
        max_tokens: int = 4096,
        system_prompt: str | None = None,
    ) -> str:
        if not self.api_key:
            key_name = "GROQ_API_KEY" if self.agent.provider == "groq" else "GEMINI_API_KEY"
            raise ValueError(f"{key_name} is required for the {self.agent.role} agent.")

        async with httpx.AsyncClient(timeout=120.0) as client:
            if self.agent.provider == "groq":
                messages = []
                if system_prompt:
                    messages.append({"role": "system", "content": system_prompt})
                messages.append({"role": "user", "content": prompt})
                response = await client.post(
                    f"{settings.groq_base_url.rstrip('/')}/chat/completions",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    json={
                        "model": self.agent.model,
                        "messages": messages,
                        "temperature": temperature,
                        "max_tokens": max_tokens,
                    },
                )
                response.raise_for_status()
                return response.json()["choices"][0]["message"]["content"]

            contents = []
            if system_prompt:
                contents.append({"role": "user", "parts": [{"text": system_prompt}]})
                contents.append({"role": "model", "parts": [{"text": "Understood."}]})
            contents.append({"role": "user", "parts": [{"text": prompt}]})
            response = await client.post(
                "https://generativelanguage.googleapis.com/v1beta/"
                f"models/{self.agent.model}:generateContent",
                headers={"x-goog-api-key": self.api_key},
                json={
                    "contents": contents,
                    "generationConfig": {
                        "temperature": temperature,
                        "maxOutputTokens": max_tokens,
                    },
                },
            )
            response.raise_for_status()
            parts = response.json()["candidates"][0]["content"]["parts"]
            return "".join(part.get("text", "") for part in parts)


def build_agent_clients() -> dict[str, AgentModelClient]:
    """Create one separate client per configured agent role."""
    return {
        role: AgentModelClient(agent)
        for role, agent in get_agent_models().items()
    }
