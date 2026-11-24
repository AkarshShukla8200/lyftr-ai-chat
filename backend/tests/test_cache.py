"""Prompt 3 scope: LiteLLM built-in disk cache, hit detection, no-cache/no-store proof.

Real LiteLLM + real disk cache (tmp dir) against the local fake Gemini server.
"""

from __future__ import annotations

import litellm
import pytest
from fastapi.testclient import TestClient

from app.llm_gateway import CACHE_BYPASS, LiteLLMGateway, configure_cache
from app.simulation import FailureSimulation
from app.main import create_app

from .conftest import make_settings
from .fake_provider import FakeGemini

KEY1 = "AIzaFAKE-cache-key-one"
KEY2 = "AIzaFAKE-cache-key-two"
MODEL = "gemini/test-model"
SIMULATE = FailureSimulation()  # active simulation with no failing key => cache bypass only


@pytest.fixture
def fake():
    with FakeGemini() as f:
        yield f


@pytest.fixture
def env(tmp_path, fake, monkeypatch):
    monkeypatch.setattr(litellm, "cache", None)  # restored after the test
    settings = make_settings(
        tmp_path, LLM_API_KEYS=f"{KEY1},{KEY2}", LLM_MODEL=MODEL,
        LLM_CACHE_DIR=(tmp_path / "litellm-cache").as_posix(),
    )
    configure_cache(settings.llm_cache_dir)
    gw = LiteLLMGateway(settings, extra_completion_kwargs={"api_base": fake.base_url})
    with TestClient(create_app(settings, gw), raise_server_exceptions=False) as client:
        yield settings, gw, client


def post(client, sid, msg, **extra):
    r = client.post("/chat", json={"session_id": sid, "message": msg, **extra})
    assert r.status_code == 200, r.text
    return r.json()


def total_hits(fake):
    return sum(fake.hits.values())


def test_cache_dir_created_and_health_reports_cache(env):
    settings, _, client = env
    import os
    assert os.path.isdir(settings.llm_cache_dir)
    assert client.get("/health").json() == {"status": "ok", "keys_configured": 2, "cache_enabled": True}


def test_same_first_message_in_two_new_sessions_live_then_cache(env, fake):
    _, _, client = env
    a = post(client, "s-a", "What is the capital of France?")
    fake.reply_text = "A DIFFERENT live answer"  # would show up if the provider were called
    b = post(client, "s-b", "What is the capital of France?")
    assert a["metadata"]["resolution_source"] == "LIVE_INFERENCE"
    assert a["metadata"]["key_id"] == "key_1"
    assert b["metadata"]["resolution_source"] == "LLM_CACHE"
    assert b["reply"] == a["reply"]
    assert b["metadata"]["input_tokens"] == a["metadata"]["input_tokens"]
    assert b["metadata"]["output_tokens"] == a["metadata"]["output_tokens"]
    assert b["metadata"]["key_id"] is None
    assert b["metadata"]["fallback_attempts"] == 0
    assert b["metadata"]["model"] == a["metadata"]["model"] == MODEL
    assert total_hits(fake) == 1
    # the cached turn is stored in history with its cache metadata
    hist = client.get("/sessions/s-b/messages").json()["messages"]
    assert hist[1]["metadata"]["resolution_source"] == "LLM_CACHE"


def test_different_message_is_live(env, fake):
    _, _, client = env
    post(client, "s1", "Question one")
    r = post(client, "s2", "Question two")
    assert r["metadata"]["resolution_source"] == "LIVE_INFERENCE"
    assert total_hits(fake) == 2


def test_same_message_different_system_prompt_is_live(env, fake):
    _, _, client = env
    post(client, "s1", "Hello", system_prompt="Be formal.")
    r = post(client, "s2", "Hello", system_prompt="Be casual.")
    assert r["metadata"]["resolution_source"] == "LIVE_INFERENCE"
    assert total_hits(fake) == 2


def test_different_model_is_live(tmp_path, fake, monkeypatch):
    monkeypatch.setattr(litellm, "cache", None)
    configure_cache((tmp_path / "c").as_posix())
    msgs = [{"role": "system", "content": "s"}, {"role": "user", "content": "q"}]
    s1 = make_settings(tmp_path, LLM_API_KEYS=KEY1 + "," + KEY2, LLM_MODEL="gemini/model-a")
    s2 = make_settings(tmp_path, LLM_API_KEYS=KEY1 + "," + KEY2, LLM_MODEL="gemini/model-b")
    extra = {"api_base": fake.base_url}
    assert LiteLLMGateway(s1, extra_completion_kwargs=extra).complete(msgs).cache_hit is False
    assert LiteLLMGateway(s2, extra_completion_kwargs=extra).complete(msgs).cache_hit is False
    assert LiteLLMGateway(s1, extra_completion_kwargs=extra).complete(msgs).cache_hit is True


def test_second_turn_same_session_is_not_a_hit_of_first_turn(env, fake):
    _, _, client = env
    post(client, "s-t", "Repeat me")
    r = post(client, "s-t", "Repeat me")  # same text, but history differs now
    assert r["metadata"]["resolution_source"] == "LIVE_INFERENCE"
    assert total_hits(fake) == 2


def test_long_conversation_is_cached_beyond_four_messages(env, fake):
    # LiteLLM's default max_messages=4 would skip caching from turn 2 on.
    _, _, client = env
    for turn in ("one", "two", "three"):
        post(client, "long-a", f"turn {turn}")
    calls_after_a = total_hits(fake)
    sources = [post(client, "long-b", f"turn {t}")["metadata"]["resolution_source"] for t in ("one", "two", "three")]
    assert sources == ["LLM_CACHE", "LLM_CACHE", "LLM_CACHE"]  # turn 3 sends 6 messages
    assert total_hits(fake) == calls_after_a


def test_cache_is_key_independent(env, fake):
    # First served by key_2 (key_1 rate-limited), later hit with both keys healthy.
    _, _, client = env
    fake.behaviour[KEY1] = "429"
    a = post(client, "k-a", "Key independent?")
    assert a["metadata"]["key_id"] == "key_2"
    fake.behaviour.clear()
    b = post(client, "k-b", "Key independent?")
    assert b["metadata"]["resolution_source"] == "LLM_CACHE" and b["reply"] == a["reply"]


def test_cache_hit_needs_no_healthy_key(env, fake):
    _, _, client = env
    post(client, "w-a", "Warm me")
    fake.behaviour[KEY1] = "429"
    fake.behaviour[KEY2] = "503"
    r = post(client, "w-b", "Warm me")
    assert r["metadata"]["resolution_source"] == "LLM_CACHE"


def test_cache_hit_faster_than_live(env, fake):
    _, _, client = env
    fake.delay_seconds = 0.5  # realistic provider latency
    live = post(client, "f-a", "Speed test")
    hit = post(client, "f-b", "Speed test")
    assert hit["metadata"]["resolution_source"] == "LLM_CACHE"
    assert hit["metadata"]["latency_ms"] < live["metadata"]["latency_ms"]
    assert live["metadata"]["latency_ms"] >= 500


def test_cache_survives_restart(tmp_path, fake, monkeypatch):
    monkeypatch.setattr(litellm, "cache", None)
    cache_dir = (tmp_path / "persist").as_posix()
    s = make_settings(tmp_path, LLM_API_KEYS=f"{KEY1},{KEY2}", LLM_MODEL=MODEL, LLM_CACHE_DIR=cache_dir)
    msgs = [{"role": "system", "content": "s"}, {"role": "user", "content": "persist me"}]
    extra = {"api_base": fake.base_url}
    configure_cache(cache_dir)
    first = LiteLLMGateway(s, extra_completion_kwargs=extra).complete(msgs)
    litellm.cache.cache.disk_cache.close()
    litellm.cache = None                      # "process stops"
    configure_cache(cache_dir)                # "process starts" on the same volume
    second = LiteLLMGateway(s, extra_completion_kwargs=extra).complete(msgs)
    assert (first.cache_hit, second.cache_hit) == (False, True)
    assert second.reply == first.reply
    assert total_hits(fake) == 1


# ---------- no-cache / no-store proof (simulation bypass) ----------

def test_no_cache_skips_lookup_and_no_store_keeps_entry(env, fake):
    _, gw, _ = env
    msgs = [{"role": "system", "content": "s"}, {"role": "user", "content": "bypass"}]
    fake.reply_text = "ORIGINAL"
    warm = gw.complete(msgs)
    assert warm.cache_hit is False and total_hits(fake) == 1

    fake.reply_text = "FRESH"
    bypass = gw.complete(msgs, simulation=SIMULATE)
    assert total_hits(fake) == 2               # no-cache: lookup skipped, provider called
    assert bypass.cache_hit is False and bypass.reply == "FRESH" and bypass.key_id == "key_1"

    again = gw.complete(msgs)
    assert again.cache_hit is True
    assert again.reply == "ORIGINAL"           # no-store: the fresh reply was not written
    assert total_hits(fake) == 2


def test_simulation_request_never_returns_llm_cache(env, fake):
    _, gw, _ = env
    msgs = [{"role": "system", "content": "s"}, {"role": "user", "content": "warm then simulate"}]
    gw.complete(msgs)
    for _ in range(2):
        r = gw.complete(msgs, simulation=SIMULATE)
        assert r.cache_hit is False and r.key_id == "key_1"


def test_bypass_flags_reach_litellm(env, fake):
    settings, _, _ = env
    seen = []

    def spy(**kw):
        seen.append(kw.get("cache"))
        return litellm.completion(**kw)

    gw = LiteLLMGateway(settings, completion_fn=spy, extra_completion_kwargs={"api_base": fake.base_url})
    msgs = [{"role": "user", "content": "flags"}]
    gw.complete(msgs)
    gw.complete(msgs, simulation=SIMULATE)
    assert seen == [None, CACHE_BYPASS]


# ---------- empty replies never stick in the cache ----------

def test_empty_reply_does_not_poison_cache(env, fake):
    _, _, client = env
    fake.behaviour[KEY1] = "empty"
    r = post(client, "e-a", "Empty first")
    assert r["reply"] == "Hello from fake Gemini."
    assert r["metadata"]["key_id"] == "key_2" and r["metadata"]["fallback_attempts"] == 1
    fake.behaviour.clear()
    again = post(client, "e-b", "Empty first")
    assert again["reply"] == "Hello from fake Gemini."
    assert again["metadata"]["resolution_source"] == "LLM_CACHE"
