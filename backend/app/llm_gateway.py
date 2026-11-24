"""Production LLM gateway: LiteLLM performs every provider call; the app owns the key loop.

Why not litellm.Router: the Router can disable cooldowns and reports attempted
fallbacks, but it has no documented way to make one chosen key fail with a
chosen status for a single request (needed for X-Simulate-Failure). An
app-owned ordered loop gives exact, testable key_id / fallback_attempts.
LiteLLM still makes every call, owns the response cache and classifies the
provider errors that drive failover.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

import litellm
import openai
from litellm.caching.caching import Cache

from .config import Settings
from .gateway import AllProvidersUnavailable, LLMResult
from .simulation import FailureSimulation

logger = logging.getLogger("app.gateway")

# Every LiteLLM provider exception (RateLimitError, InternalServerError,
# ServiceUnavailableError, BadGatewayError, Timeout, APIConnectionError,
# AuthenticationError, PermissionDeniedError, BadRequestError incl. Gemini's
# 400 API_KEY_INVALID, ContentPolicyViolationError, ...) subclasses
# openai.APIError in the installed version (verified by tests).
PROVIDER_ERRORS: tuple[type[BaseException], ...] = (openai.APIError,)


# Per-request cache control for requests that must reach the provider
# (X-Simulate-Failure). Verified on the installed LiteLLM by tests:
#   no-cache -> skips the cache LOOKUP (provider is called)
#   no-store -> does not WRITE the result (cache entry stays as it was)
CACHE_BYPASS = {"no-cache": True, "no-store": True}


def configure_cache(cache_dir: str) -> Cache:
    """Enable LiteLLM's built-in disk cache (process-global, one uvicorn worker).

    max_messages=None: LiteLLM 1.108.x defaults to 4, which silently skips
    caching for any request with more than 4 messages (every turn after the
    second). The PDF's cache key is model + the FULL message list, so the limit
    is removed.
    """
    os.makedirs(cache_dir, exist_ok=True)
    litellm.cache = Cache(type="disk", disk_cache_dir=cache_dir, max_messages=None)
    return litellm.cache


class EmptyReplyError(Exception):
    """Provider returned no text (empty, blocked, or token budget exhausted)."""


@dataclass(frozen=True)
class KeySlot:
    key_id: str
    model: str
    api_key: str = field(repr=False)


def build_slots(settings: Settings) -> list[KeySlot]:
    keys = settings.llm_api_keys
    if settings.llm_models:
        models = settings.llm_models
    else:
        models = [settings.llm_model] * len(keys)
    return [
        KeySlot(key_id=f"key_{i}", model=model, api_key=key)
        for i, (key, model) in enumerate(zip(keys, models), start=1)
    ]


class LiteLLMGateway:
    def __init__(
        self,
        settings: Settings,
        completion_fn: Optional[Callable[..., Any]] = None,
        extra_completion_kwargs: Optional[dict[str, Any]] = None,
    ) -> None:
        self._settings = settings
        self._slots = build_slots(settings)
        self._completion = completion_fn or litellm.completion
        # Used by tests to point LiteLLM at a local fake provider (api_base).
        self._extra = dict(extra_completion_kwargs or {})

    @property
    def keys_configured(self) -> int:
        return len(self._slots)

    @property
    def cache_enabled(self) -> bool:
        return litellm.cache is not None

    def _call_kwargs(
        self,
        slot: KeySlot,
        messages: list[dict[str, str]],
        cache_control: Optional[dict[str, bool]] = None,
    ) -> dict[str, Any]:
        kwargs: dict[str, Any] = {
            "model": slot.model,
            "messages": messages,
            "api_key": slot.api_key,
            "timeout": self._settings.llm_timeout_seconds,
            "num_retries": 0,  # no hidden LiteLLM retries; the app loop is the only retry
            # max_tokens deliberately unset: reasoning tokens share the budget and a
            # small cap produces empty replies (= key failure).
        }
        if self._settings.llm_temperature is not None:
            kwargs["temperature"] = self._settings.llm_temperature
        if self._settings.llm_reasoning_effort:
            kwargs["reasoning_effort"] = self._settings.llm_reasoning_effort
        if cache_control:
            kwargs["cache"] = dict(cache_control)
        kwargs.update(self._extra)
        return kwargs

    def _attempt(self, slot: KeySlot, messages: list[dict[str, str]], bypass_cache: bool):
        """One key attempt. Returns (response, reply, cache_hit) or raises a key failure."""
        response = self._completion(
            **self._call_kwargs(slot, messages, CACHE_BYPASS if bypass_cache else None)
        )
        cache_hit = _is_cache_hit(response)
        try:
            return response, _extract_reply(response), cache_hit
        except EmptyReplyError:
            if not cache_hit:
                raise
        # An empty reply was stored in the cache earlier. Ask the provider again
        # with the lookup skipped; the fresh reply overwrites the bad entry.
        logger.warning("empty cached reply; refreshing key_id=%s", slot.key_id)
        response = self._completion(
            **self._call_kwargs(slot, messages, CACHE_BYPASS if bypass_cache else {"no-cache": True})
        )
        return response, _extract_reply(response), False

    def complete(
        self, messages: list[dict[str, str]], simulation: Optional[FailureSimulation] = None
    ) -> LLMResult:
        # An active simulation must never be answered from (or pollute) the cache,
        # otherwise a cached reply would hide the failover being demonstrated.
        bypass_cache = simulation is not None
        failures = 0
        for slot in self._slots:
            try:
                simulated = simulation.exception_for(slot.key_id, slot.model) if simulation else None
                if simulated is not None:
                    raise simulated  # behaves like the provider returned that status; no call made
                response, reply, cache_hit = self._attempt(slot, messages, bypass_cache)
            except (*PROVIDER_ERRORS, EmptyReplyError) as exc:
                # Never log the exception message: provider errors may echo URLs/keys.
                logger.warning(
                    "key failure key_id=%s error=%s status=%s",
                    slot.key_id,
                    type(exc).__name__,
                    getattr(exc, "status_code", None),
                )
                failures += 1
                continue

            usage = getattr(response, "usage", None)
            return LLMResult(
                reply=reply,
                # Model is part of the cache key, so on a hit this is also the
                # model string of the request that created the entry.
                model=slot.model,
                # On a hit LiteLLM replays the usage stored with the cached response.
                input_tokens=int(getattr(usage, "prompt_tokens", 0) or 0),
                output_tokens=int(getattr(usage, "completion_tokens", 0) or 0),
                key_id=None if cache_hit else slot.key_id,
                fallback_attempts=0 if cache_hit else failures,
                cache_hit=cache_hit,
            )

        logger.warning("all providers unavailable after %d key failures", failures)
        raise AllProvidersUnavailable()


def _is_cache_hit(response: Any) -> bool:
    # LiteLLM's own flag (True on hit, None on miss); never inferred from speed.
    hidden = getattr(response, "_hidden_params", None) or {}
    return hidden.get("cache_hit") is True


def _extract_reply(response: Any) -> str:
    try:
        content = response.choices[0].message.content
    except (AttributeError, IndexError):
        raise EmptyReplyError() from None
    if not isinstance(content, str) or not content.strip():
        raise EmptyReplyError()
    return content
