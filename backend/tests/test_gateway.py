"""Prompt 2 scope: real LiteLLM against a local fake Gemini; app-owned key failover."""

from __future__ import annotations

import logging
import socket
import threading
import time

import httpx
import litellm
import pytest
import uvicorn
from fastapi.testclient import TestClient

from app.gateway import AllProvidersUnavailable
from app.llm_gateway import LiteLLMGateway, build_slots
from app.main import create_app

from .conftest import make_settings
from .fake_provider import FakeGemini

KEY1 = "AIzaFAKE-key-one-0000"
KEY2 = "AIzaFAKE-key-two-1111"
MODEL = "gemini/test-model"
MSGS = [{"role": "system", "content": "sys"}, {"role": "user", "content": "hi"}]


@pytest.fixture(autouse=True)
def no_global_cache(monkeypatch):
    # Prompt 2 tests exercise live calls only; caching is covered separately.
    monkeypatch.setattr(litellm, "cache", None)


@pytest.fixture
def fake():
    with FakeGemini() as f:
        yield f


def gw_settings(tmp_path, **env):
    base = {"LLM_API_KEYS": f"{KEY1},{KEY2}", "LLM_MODEL": MODEL}
    base.update(env)
    return make_settings(tmp_path, **base)


def make_gateway(tmp_path, fake, **env):
    s = gw_settings(tmp_path, **env)
    return s, LiteLLMGateway(s, extra_completion_kwargs={"api_base": fake.base_url})


# ---------- success / metadata ----------

def test_first_key_success(tmp_path, fake):
    _, gw = make_gateway(tmp_path, fake)
    r = gw.complete(MSGS)
    assert r.reply == "Hello from fake Gemini."
    assert r.key_id == "key_1"
    assert r.fallback_attempts == 0
    assert r.model == MODEL                      # LiteLLM model string, not raw response.model
    assert (r.input_tokens, r.output_tokens) == (11, 4)  # provider usage as reported
    assert r.cache_hit is False
    assert fake.hits == {KEY1: 1}


# ---------- failover on every provider-side error ----------

@pytest.mark.parametrize(
    "error", ["429", "quota", "500", "502", "503", "401", "403", "400_bad_key", "empty", "blocked"]
)
def test_key1_failure_moves_to_key2(tmp_path, fake, error):
    fake.behaviour[KEY1] = error
    _, gw = make_gateway(tmp_path, fake)
    r = gw.complete(MSGS)
    assert r.key_id == "key_2"
    assert r.fallback_attempts == 1
    assert r.reply == "Hello from fake Gemini."
    # exactly one provider call per key: no hidden LiteLLM/SDK retries
    assert fake.hits == {KEY1: 1, KEY2: 1}


def test_timeout_moves_to_next_key(tmp_path, fake):
    fake.behaviour[KEY1] = "slow"  # sleeps 3 s
    _, gw = make_gateway(tmp_path, fake, LLM_TIMEOUT_SECONDS="1")
    started = time.monotonic()
    r = gw.complete(MSGS)
    assert r.key_id == "key_2" and r.fallback_attempts == 1
    assert time.monotonic() - started < 2.9
    assert fake.hits[KEY1] == 1


def test_connection_error_moves_to_next_key(tmp_path, fake):
    # key_1's model points at a closed port; key_2 at the fake server.
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    dead_port = sock.getsockname()[1]
    sock.close()
    s = gw_settings(tmp_path)
    real = litellm.completion

    def routed(**kw):
        kw["api_base"] = f"http://127.0.0.1:{dead_port}" if kw["api_key"] == KEY1 else fake.base_url
        return real(**kw)

    r = LiteLLMGateway(s, completion_fn=routed).complete(MSGS)
    assert r.key_id == "key_2" and r.fallback_attempts == 1


def test_all_keys_fail_raises(tmp_path, fake):
    fake.behaviour[KEY1] = "429"
    fake.behaviour[KEY2] = "503"
    _, gw = make_gateway(tmp_path, fake)
    with pytest.raises(AllProvidersUnavailable):
        gw.complete(MSGS)
    assert fake.hits == {KEY1: 1, KEY2: 1}


def test_three_keys_two_failures(tmp_path, fake):
    k3 = "AIzaFAKE-key-three-2222"
    fake.behaviour[KEY1] = "429"
    fake.behaviour[KEY2] = "500"
    _, gw = make_gateway(tmp_path, fake, LLM_API_KEYS=f"{KEY1},{KEY2},{k3}")
    r = gw.complete(MSGS)
    assert (r.key_id, r.fallback_attempts) == ("key_3", 2)


def test_non_provider_exception_is_not_swallowed(tmp_path):
    s = gw_settings(tmp_path)

    def broken(**_kw):
        raise ValueError("bug in our code")

    with pytest.raises(ValueError):
        LiteLLMGateway(s, completion_fn=broken).complete(MSGS)


# ---------- call parameters ----------

def test_call_kwargs_no_retries_no_small_max_tokens(tmp_path, fake):
    seen = []
    real = litellm.completion

    def spy(**kw):
        seen.append(dict(kw))
        return real(**kw)

    s = gw_settings(tmp_path, LLM_TIMEOUT_SECONDS="30")
    LiteLLMGateway(s, completion_fn=spy, extra_completion_kwargs={"api_base": fake.base_url}).complete(MSGS)
    kw = seen[0]
    assert kw["num_retries"] == 0
    assert kw["timeout"] == 30.0
    assert kw.get("max_tokens") is None or kw["max_tokens"] >= 1024
    assert kw["model"] == MODEL and kw["api_key"] == KEY1
    assert "temperature" not in kw and "reasoning_effort" not in kw  # unset unless configured


def test_optional_constant_params(tmp_path, fake):
    seen = []
    s = gw_settings(tmp_path, LLM_TEMPERATURE="0.2", LLM_REASONING_EFFORT="low")

    def spy(**kw):
        seen.append(kw)
        return litellm.completion(**kw)

    LiteLLMGateway(s, completion_fn=spy, extra_completion_kwargs={"api_base": fake.base_url}).complete(MSGS)
    assert seen[0]["temperature"] == 0.2 and seen[0]["reasoning_effort"] == "low"


def test_per_key_models(tmp_path):
    s = gw_settings(tmp_path, LLM_MODELS="gemini/a, groq/b")
    assert [(x.key_id, x.model) for x in build_slots(s)] == [("key_1", "gemini/a"), ("key_2", "groq/b")]
    assert s.config_problems() == []
    bad = gw_settings(tmp_path, LLM_MODELS="gemini/a")
    assert bad.config_problems()


def test_slot_repr_hides_key(tmp_path):
    s = gw_settings(tmp_path)
    assert KEY1 not in repr(build_slots(s))


# ---------- through the API ----------

def api_client(tmp_path, fake, **env):
    s, gw = make_gateway(tmp_path, fake, **env)
    monkey_cache = litellm.cache
    assert monkey_cache is None
    return s, TestClient(create_app(s, gw), raise_server_exceptions=False)


def test_api_failover_metadata_and_tokens(tmp_path, fake):
    fake.behaviour[KEY1] = "429"
    _, client = api_client(tmp_path, fake)
    with client:
        r = client.post("/chat", json={"session_id": "s1", "message": "hi"})
    assert r.status_code == 200
    md = r.json()["metadata"]
    assert md["key_id"] == "key_2" and md["fallback_attempts"] == 1
    assert md["resolution_source"] == "LIVE_INFERENCE"
    assert (md["input_tokens"], md["output_tokens"]) == (11, 4)
    assert md["model"] == MODEL


def test_api_all_fail_503_no_writes(tmp_path, fake):
    fake.behaviour[KEY1] = "500"
    fake.behaviour[KEY2] = "429"
    _, client = api_client(tmp_path, fake)
    with client:
        r = client.post("/chat", json={"session_id": "s-x", "message": "hi"})
        assert r.status_code == 503
        assert r.json() == {"detail": "all providers unavailable"}
        assert client.get("/sessions/s-x/messages").status_code == 404


def test_api_multi_turn_reaches_provider_in_order(tmp_path, fake):
    _, client = api_client(tmp_path, fake)
    with client:
        client.post("/chat", json={"session_id": "m", "message": "My name is Ada."})
        client.post("/chat", json={"session_id": "m", "message": "What is my name?"})
    texts = str(fake.bodies[-1])
    assert texts.index("My name is Ada.") < texts.index("Hello from fake Gemini.") < texts.index("What is my name?")


def test_api_non_provider_error_is_500(tmp_path):
    s = gw_settings(tmp_path)

    def broken(**_kw):
        raise ValueError("bug")

    with TestClient(create_app(s, LiteLLMGateway(s, completion_fn=broken)), raise_server_exceptions=False) as c:
        r = c.post("/chat", json={"session_id": "e", "message": "hi"})
    assert r.status_code == 500 and r.json() == {"detail": "internal server error"}


def test_health_reports_missing_model(tmp_path, fake):
    s = make_settings(tmp_path, LLM_MODEL="")
    with TestClient(create_app(s, LiteLLMGateway(s))) as c:
        r = c.get("/health")
    assert r.status_code == 503 and "LLM_MODEL" in r.json()["detail"]


# ---------- secrets ----------

def test_no_secret_in_logs_or_bodies(tmp_path, fake, caplog):
    caplog.set_level(logging.DEBUG)
    fake.behaviour[KEY1] = "400_bad_key"
    _, client = api_client(tmp_path, fake)
    with client:
        ok = client.post("/chat", json={"session_id": "sec", "message": "hi"})
        fake.behaviour[KEY2] = "401"
        bad = client.post("/chat", json={"session_id": "sec2", "message": "hi"})
        hist = client.get("/sessions/sec/messages")
        health = client.get("/health")
    blob = caplog.text + ok.text + bad.text + hist.text + health.text
    for key in (KEY1, KEY2, "AIzaFAKE"):
        assert key not in blob
    assert "key failure key_id=key_1 error=AuthenticationError" in caplog.text


# ---------- event loop not blocked ----------

def test_slow_chat_does_not_block_health(tmp_path, fake):
    fake.delay_seconds = 2.0
    s, gw = make_gateway(tmp_path, fake)
    app = create_app(s, gw)
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    t = threading.Thread(target=server.run, daemon=True)
    t.start()
    base = f"http://127.0.0.1:{port}"
    deadline = time.monotonic() + 10
    while not server.started and time.monotonic() < deadline:
        time.sleep(0.05)
    try:
        result = {}
        chat_thread = threading.Thread(
            target=lambda: result.setdefault(
                "r", httpx.post(f"{base}/chat", json={"session_id": "slow", "message": "hi"}, timeout=10)
            )
        )
        chat_thread.start()
        time.sleep(0.3)  # chat is now waiting on the slow provider
        started = time.monotonic()
        h = httpx.get(f"{base}/health", timeout=5)
        health_elapsed = time.monotonic() - started
        chat_thread.join()
        # cache is disabled in this module, so health is 503 here; timing is what matters
        assert h.status_code in (200, 503)
        assert health_elapsed < 1.0
        assert result["r"].status_code == 200
    finally:
        server.should_exit = True
        t.join(timeout=5)
