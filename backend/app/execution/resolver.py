import re
from typing import Optional

from app.execution.language_registry import (
    LanguageConfig,
    LANGUAGE_REGISTRY,
    get_language_config,
    get_all_languages,
)
from app.execution.models import ExecutionType


class UnsupportedLanguageError(Exception):
    def __init__(self, language: str, available: list):
        self.language = language
        self.available = available
        super().__init__(f"Unsupported language: '{language}'. Available: {', '.join(available)}")


def normalize_language_input(language: str) -> str:
    if not language:
        return ""
    normalized = language.strip().lower()
    normalized = re.sub(r"\s+", "", normalized)
    return normalized


def resolve_language(language: str) -> LanguageConfig:
    normalized = normalize_language_input(language)

    if not normalized:
        raise UnsupportedLanguageError(language, list(LANGUAGE_REGISTRY.keys()))

    if normalized in LANGUAGE_REGISTRY:
        return LANGUAGE_REGISTRY[normalized]

    for lang_id, config in LANGUAGE_REGISTRY.items():
        if normalized in [alias.lower() for alias in config.aliases]:
            return config

    for lang_id, config in LANGUAGE_REGISTRY.items():
        if normalized.startswith(lang_id) or lang_id.startswith(normalized):
            return config

    available = []
    for config in LANGUAGE_REGISTRY.values():
        available.append(config.id)
        available.extend(config.aliases)

    raise UnsupportedLanguageError(language, available)


def resolve_language_safe(language: str) -> Optional[LanguageConfig]:
    try:
        return resolve_language(language)
    except UnsupportedLanguageError:
        return None


def get_execution_backend(language: str) -> Optional[str]:
    config = resolve_language_safe(language)
    if config:
        return config.backend.value
    return None


def get_execution_type(language: str) -> Optional[ExecutionType]:
    config = resolve_language_safe(language)
    if config:
        return config.execution_type
    return None