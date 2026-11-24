"""Request/response models for the public API contract."""

from __future__ import annotations

from typing import Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, StrictStr, field_validator

MAX_SESSION_ID = 128
MAX_MESSAGE = 4000
MAX_SYSTEM_PROMPT = 4000


class ChatRequest(BaseModel):
    # strict: no int -> str coercion; missing/null required fields are 422.
    model_config = ConfigDict(strict=True)

    session_id: StrictStr
    message: StrictStr
    system_prompt: Optional[StrictStr] = None

    @field_validator("session_id")
    @classmethod
    def _check_session_id(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("session_id must not be empty")
        if len(value) > MAX_SESSION_ID:
            raise ValueError(f"session_id must be at most {MAX_SESSION_ID} characters")
        return value  # stored unmodified

    @field_validator("message")
    @classmethod
    def _check_message(cls, value: str) -> str:
        trimmed = value.strip()
        if not trimmed:
            raise ValueError("message must not be empty")
        if len(trimmed) > MAX_MESSAGE:
            raise ValueError(f"message must be at most {MAX_MESSAGE} characters after trimming")
        return trimmed

    @field_validator("system_prompt")
    @classmethod
    def _check_system_prompt(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        trimmed = value.strip()
        if not trimmed:
            return None  # blank = absent
        if len(trimmed) > MAX_SYSTEM_PROMPT:
            raise ValueError(
                f"system_prompt must be at most {MAX_SYSTEM_PROMPT} characters after trimming"
            )
        return trimmed


class ChatMetadata(BaseModel):
    resolution_source: Literal["LIVE_INFERENCE", "LLM_CACHE"]
    model: str
    latency_ms: int
    input_tokens: int
    output_tokens: int
    key_id: Optional[str]
    fallback_attempts: int


class ChatResponse(BaseModel):
    session_id: str
    reply: str
    metadata: ChatMetadata


class UserHistoryMessage(BaseModel):
    role: Literal["user"]
    content: str


class AssistantHistoryMessage(BaseModel):
    role: Literal["assistant"]
    content: str
    metadata: ChatMetadata


class HistoryResponse(BaseModel):
    session_id: str
    messages: list[Union[UserHistoryMessage, AssistantHistoryMessage]]


class HealthResponse(BaseModel):
    status: Literal["ok"]
    keys_configured: int
    cache_enabled: bool
