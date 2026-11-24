"""Shared fixtures. FakeGateway is a test double only; production uses LiteLLM."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional

import pytest
from fastapi.testclient import TestClient

from app.config import Settings
from app.gateway import AllProvidersUnavailable, LLMResult
from app.main import create_app

ALLOWED_ORIGIN = "http://localhost:3000"


@dataclass
class FakeGateway:
    keys_configured: int = 2
    cache_enabled: bool = True
    calls: list = field(default_factory=list)
    behaviour: Optional[Callable[[list], LLMResult]] = None

    def complete(self, messages, simulation=None):
        self.calls.append([dict(m) for m in messages])
        if self.behaviour is not None:
            return self.behaviour(messages)
        return LLMResult(
            reply=f"echo: {messages[-1]['content']}",
            model="test/fake-model",
            input_tokens=10 * len(messages),
            output_tokens=5,
            key_id="key_1",
            fallback_attempts=0,
            cache_hit=False,
        )


def make_settings(tmp_path, **overrides) -> Settings:
    env = {
        "DATABASE_URL": f"sqlite:///{(tmp_path / 'app.db').as_posix()}",
        "ALLOWED_ORIGINS": ALLOWED_ORIGIN,
        "LLM_API_KEYS": "fake-key-one,fake-key-two",
        "LLM_MODEL": "test/fake-model",
        "LLM_CACHE_DIR": (tmp_path / "cache").as_posix(),
    }
    env.update(overrides)
    return Settings.from_env(env)


@pytest.fixture
def gateway():
    return FakeGateway()


@pytest.fixture
def settings(tmp_path):
    return make_settings(tmp_path)


@pytest.fixture
def client(settings, gateway):
    app = create_app(settings, gateway)
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


def raise_unavailable(_messages):
    raise AllProvidersUnavailable()
