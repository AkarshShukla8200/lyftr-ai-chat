"""Application settings, read only from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass, field

DEFAULT_SYSTEM_PROMPT = "You are a helpful, concise assistant."


def _split_csv(value: str | None) -> list[str]:
    if not value:
        return []
    return [part.strip() for part in value.split(",") if part.strip()]


def sqlite_path_from_url(url: str) -> str:
    """Convert a SQLAlchemy-style SQLite URL to a filesystem path.

    sqlite:////data/app.db    -> /data/app.db   (absolute)
    sqlite:///./data/app.db   -> ./data/app.db  (relative)
    sqlite:///C:/tmp/app.db   -> C:/tmp/app.db  (Windows absolute)
    """
    prefix = "sqlite:///"
    if not url.startswith(prefix):
        raise ValueError("DATABASE_URL must start with sqlite:///")
    path = url[len(prefix):]
    if not path:
        raise ValueError("DATABASE_URL has no file path")
    return path


@dataclass(frozen=True)
class Settings:
    database_path: str
    allowed_origins: list[str]
    enable_failure_simulation: bool
    default_system_prompt: str
    llm_model: str
    llm_models: list[str]
    llm_timeout_seconds: float
    llm_cache_dir: str
    llm_temperature: float | None = None
    llm_reasoning_effort: str | None = None
    # repr=False so keys never appear in logs or tracebacks that print settings.
    llm_api_keys: list[str] = field(repr=False, default_factory=list)

    @property
    def keys_configured(self) -> int:
        return len(self.llm_api_keys)

    def config_problems(self) -> list[str]:
        """Configuration errors that make the key pool unusable (reported by /health)."""
        problems = []
        if self.llm_models:
            if len(self.llm_models) != len(self.llm_api_keys):
                problems.append("LLM_MODELS count must match LLM_API_KEYS count")
        elif not self.llm_model:
            problems.append("LLM_MODEL not configured")
        return problems

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> "Settings":
        env = dict(os.environ) if env is None else env
        keys = _split_csv(env.get("LLM_API_KEYS"))
        model = env.get("LLM_MODEL", "").strip()
        models = _split_csv(env.get("LLM_MODELS"))
        origins = [o.rstrip("/") for o in _split_csv(env.get("ALLOWED_ORIGINS"))]
        prompt = (env.get("DEFAULT_SYSTEM_PROMPT") or "").strip() or DEFAULT_SYSTEM_PROMPT
        return cls(
            database_path=sqlite_path_from_url(
                env.get("DATABASE_URL", "sqlite:///./data/app.db").strip()
            ),
            allowed_origins=origins,
            # Exactly "true" enables the hook; anything else leaves it off.
            enable_failure_simulation=env.get("ENABLE_FAILURE_SIMULATION", "") == "true",
            default_system_prompt=prompt,
            llm_model=model,
            llm_models=models,
            llm_timeout_seconds=float(env.get("LLM_TIMEOUT_SECONDS", "30")),
            llm_cache_dir=env.get("LLM_CACHE_DIR", "./data/litellm-cache").strip(),
            llm_temperature=(
                float(env["LLM_TEMPERATURE"]) if (env.get("LLM_TEMPERATURE") or "").strip() else None
            ),
            llm_reasoning_effort=(env.get("LLM_REASONING_EFFORT") or "").strip() or None,
            llm_api_keys=keys,
        )
