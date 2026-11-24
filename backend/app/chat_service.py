"""Chat orchestration: rebuild context from SQLite, call the gateway, persist on success."""

from __future__ import annotations

import time

from .config import Settings
from .db import Database
from .gateway import LLMGateway
from .schemas import ChatMetadata, ChatRequest, ChatResponse


class ChatService:
    def __init__(self, settings: Settings, db: Database, gateway: LLMGateway) -> None:
        self.settings = settings
        self.db = db
        self.gateway = gateway

    def chat(self, request: ChatRequest, simulation: object = None) -> ChatResponse:
        started = time.monotonic()

        # The first successful request fixes the system prompt for the session.
        stored_prompt = self.db.get_system_prompt(request.session_id)
        system_prompt = (
            stored_prompt
            if stored_prompt is not None
            else (request.system_prompt or self.settings.default_system_prompt)
        )

        history = self.db.get_history(request.session_id)
        messages = [{"role": "system", "content": system_prompt}]
        messages += [{"role": m["role"], "content": m["content"]} for m in history]
        messages.append({"role": "user", "content": request.message})

        # Raises AllProvidersUnavailable when every key fails; nothing is written then.
        result = self.gateway.complete(messages, simulation)

        metadata = ChatMetadata(
            resolution_source="LLM_CACHE" if result.cache_hit else "LIVE_INFERENCE",
            model=result.model,
            latency_ms=int((time.monotonic() - started) * 1000),
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
            key_id=None if result.cache_hit else result.key_id,
            fallback_attempts=0 if result.cache_hit else result.fallback_attempts,
        )

        self.db.save_turn(
            session_id=request.session_id,
            system_prompt=system_prompt,
            user_content=request.message,
            assistant_content=result.reply,
            metadata=metadata.model_dump(),
        )
        return ChatResponse(session_id=request.session_id, reply=result.reply, metadata=metadata)
