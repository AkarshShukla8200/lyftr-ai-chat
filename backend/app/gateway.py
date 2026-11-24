"""LLM gateway interface.

The production implementation (LiteLLM, app-owned key failover, disk cache)
is added in Prompt 2/3. Tests inject fakes through this interface.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Protocol


class AllProvidersUnavailable(Exception):
    """Every configured key failed for this request."""


@dataclass(frozen=True)
class LLMResult:
    reply: str
    model: str
    input_tokens: int
    output_tokens: int
    key_id: Optional[str]
    fallback_attempts: int
    cache_hit: bool


class LLMGateway(Protocol):
    @property
    def keys_configured(self) -> int: ...

    @property
    def cache_enabled(self) -> bool: ...

    def complete(self, messages: list[dict[str, str]], simulation: object = None) -> LLMResult:
        """Return a real completion or raise AllProvidersUnavailable."""
        ...
