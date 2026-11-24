"""Prompt 4 scope: X-Simulate-Failure parsing, injection, flag, cache bypass, isolation."""

from __future__ import annotations

import socket
import sqlite3
import threading
import time

import httpx
import litellm
import pytest
import uvicorn
from fastapi.testclient import TestClient

from app.llm_gateway import LiteLLMGateway, configure_cache
from app.main import create_app
from app.simulation import FailureSimulation, SimulationHeaderError, parse_simulation_header

from .conftest import make_settings
from .fake_provider import FakeGemini

KEY1 = "AIzaFAKE-sim-key-one"
KEY2 = "AIzaFAKE-sim-key-two"
MODEL = "gemini/test-model"


# ---------- parser ----------

@pytest.mark.parametrize(
    "header,per_key,wildcard",
    [
        ("key_1=429", {"key_1": 429}, None),
        ("key_1=500", {"key_1": 500}, None),
        ("key_1=429,key_2=500", {"key_1": 429, "key_2": 500}, None),
        ("*=429", {}, 429),
        ("  key_1 = 502 ,  key_2=503 ", {"key_1": 502, "key_2": 503}, None),
        ("key_9=429", {"key_9": 429}, None),
        ("*=503,key_1=429", {"key_1": 429}, 503),
    ],
)
def test_parse_valid(header, per_key, wildcard):
    sim = parse_simulation_header(header)
    assert sim == FailureSimulation(per_key=per_key, wildcard=wildcard)


@pytest.mark.parametrize("header", [None, "", "   "])
def test_parse_absent(header):
    assert parse_simulation_header(header) is None


@pytest.mark.parametrize(
    "header",
    [
        "key_1=404", "key_1=200", "key_1=abc", "key_1=", "=429", "key_1", "key_1=429=5",
        "foo=429", "key_0=429", "KEY_1=429", "key_1=429,", ",key_1=429", "key_1=429,,key_2=500",
        "key_1=429,key_1=500", "*=429,*=500", "key_1:429", "key_1=4 29",
    ],
)
def test_parse_invalid(header):
    with pytest.raises(SimulationHeaderError):
        parse_simulation_header(header)


def test_explicit_key_overrides_wildcard():
    sim = parse_simulation_header("*=503, key_1=429")
    assert sim.status_for("key_1") == 429
    assert sim.status_for("key_2") == 503


@pytest.mark.parametrize("status,cls", [(429, "RateLimitError"), (500, "InternalServerError"),
                                        (502, "BadGatewayError"), (503, "ServiceUnavailableError")])
def test_simulated_exception_is_litellm_class_with_status(status, cls):
    exc = parse_simulation_header(f"key_1={status}").exception_for("key_1", MODEL)
    assert type(exc).__name__ == cls and exc.status_code == status
    assert isinstance(exc, getattr(litellm, cls))


# ---------- API ----------

@pytest.fixture
def fake():
    with FakeGemini() as f:
        yield f


def build(tmp_path, fake, monkeypatch, flag="true"):
    monkeypatch.setattr(litellm, "cache", None)
    s = make_settings(
        tmp_path, LLM_API_KEYS=f"{KEY1},{KEY2}", LLM_MODEL=MODEL,
        LLM_CACHE_DIR=(tmp_path / "cache").as_posix(), ENABLE_FAILURE_SIMULATION=flag,
    )
    configure_cache(s.llm_cache_dir)
    return s, create_app(s, LiteLLMGateway(s, extra_completion_kwargs={"api_base": fake.base_url}))


@pytest.fixture
def api(tmp_path, fake, monkeypatch):
    s, app = build(tmp_path, fake, monkeypatch)
    with TestClient(app, raise_server_exceptions=False) as c:
        yield s, c


def send(client, sid, msg, header=None):
    headers = {"X-Simulate-Failure": header} if header is not None else {}
    return client.post("/chat", json={"session_id": sid, "message": msg}, headers=headers)


def rows(settings):
    conn = sqlite3.connect(settings.database_path)
    try:
        return conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0], conn.execute(
            "SELECT COUNT(*) FROM sessions").fetchone()[0]
    finally:
        conn.close()


@pytest.mark.parametrize("status", ["429", "500", "502", "503"])
def test_key1_simulated_failure_real_answer_from_key2(api, fake, status):
    _, client = api
    r = send(client, f"s-{status}", "Say hello briefly.", f"key_1={status}")
    assert r.status_code == 200
    body = r.json()
    assert body["reply"] == "Hello from fake Gemini."     # real provider answer, not an error text
    assert body["metadata"]["key_id"] == "key_2"
    assert body["metadata"]["fallback_attempts"] == 1
    assert body["metadata"]["resolution_source"] == "LIVE_INFERENCE"
    assert fake.hits == {KEY2: 1}                          # simulated key: provider never called


def test_wildcard_503_no_writes_no_provider_calls(api, fake):
    s, client = api
    r = send(client, "s-all", "Hello", "*=429")
    assert r.status_code == 503
    assert r.json() == {"detail": "all providers unavailable"}
    assert rows(s) == (0, 0)
    assert client.get("/sessions/s-all/messages").json() == {"detail": "session not found"}
    assert sum(fake.hits.values()) == 0


def test_every_key_listed_503(api, fake):
    s, client = api
    r = send(client, "s-both", "Hello", "key_1=429,key_2=500")
    assert r.status_code == 503 and rows(s) == (0, 0)


def test_simulated_503_mid_session_leaves_history_unchanged(api):
    _, client = api
    assert send(client, "s-mid", "first").status_code == 200
    before = client.get("/sessions/s-mid/messages").json()
    assert send(client, "s-mid", "second", "*=503").status_code == 503
    assert client.get("/sessions/s-mid/messages").json() == before


def test_whitespace_and_unknown_key(api, fake):
    _, client = api
    r = send(client, "s-ws", "Hi", "  key_9 = 429 , key_1= 500 ")
    assert r.status_code == 200 and r.json()["metadata"]["key_id"] == "key_2"


def test_unknown_key_only_is_ignored(api, fake):
    _, client = api
    r = send(client, "s-unk", "Hi", "key_9=429")
    assert r.status_code == 200
    md = r.json()["metadata"]
    assert (md["key_id"], md["fallback_attempts"]) == ("key_1", 0)


@pytest.mark.parametrize("header", ["key_1=404", "garbage", "key_1=429,", "foo=500"])
def test_malformed_header_422_when_enabled(api, fake, header):
    s, client = api
    r = send(client, "s-bad", "Hi", header)
    assert r.status_code == 422
    assert isinstance(r.json()["detail"], str)
    assert rows(s) == (0, 0) and sum(fake.hits.values()) == 0


def test_simulation_after_cache_warm_still_fails_over(api, fake):
    # Mandatory: proves the cache lookup is skipped for simulated requests.
    _, client = api
    fake.reply_text = "ORIGINAL"
    warm = send(client, "w-1", "Say hello briefly.").json()
    assert warm["metadata"]["resolution_source"] == "LIVE_INFERENCE"
    assert send(client, "w-2", "Say hello briefly.").json()["metadata"]["resolution_source"] == "LLM_CACHE"

    fake.reply_text = "FRESH"
    sim = send(client, "w-3", "Say hello briefly.", "key_1=429").json()
    assert sim["metadata"]["resolution_source"] == "LIVE_INFERENCE"
    assert sim["metadata"]["key_id"] == "key_2" and sim["metadata"]["fallback_attempts"] == 1
    assert sim["reply"] == "FRESH"

    after = send(client, "w-4", "Say hello briefly.").json()
    assert after["metadata"]["resolution_source"] == "LLM_CACHE"
    assert after["reply"] == "ORIGINAL"            # simulation did not overwrite the cache entry


def test_simulated_failure_logged_by_class_only(api, caplog):
    _, client = api
    caplog.set_level("WARNING")
    send(client, "s-log", "Hi", "key_1=429")
    assert "key failure key_id=key_1 error=RateLimitError status=429" in caplog.text
    assert KEY1 not in caplog.text and KEY2 not in caplog.text


# ---------- flag ----------

@pytest.mark.parametrize("flag", ["false", "", "True", "TRUE", "1", "yes", " true"])
def test_header_ignored_unless_flag_exactly_true(tmp_path, fake, monkeypatch, flag):
    s, app = build(tmp_path, fake, monkeypatch, flag=flag)
    assert s.enable_failure_simulation is False
    with TestClient(app) as c:
        r1 = send(c, "d-1", "Hi", "*=429")
        r2 = send(c, "d-2", "Different", "this is not valid at all")
        r3 = send(c, "d-3", "Hi", "*=429")            # normal caching still applies
    assert r1.status_code == 200 and r1.json()["metadata"]["key_id"] == "key_1"
    assert r2.status_code == 200
    assert r3.json()["metadata"]["resolution_source"] == "LLM_CACHE"


# ---------- concurrency: no state leakage ----------

def test_concurrent_simulated_and_normal_requests(tmp_path, fake, monkeypatch):
    fake.delay_seconds = 0.3
    _, app = build(tmp_path, fake, monkeypatch)
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    t = threading.Thread(target=server.run, daemon=True)
    t.start()
    deadline = time.monotonic() + 10
    while not server.started and time.monotonic() < deadline:
        time.sleep(0.05)
    base = f"http://127.0.0.1:{port}"
    results: dict[int, httpx.Response] = {}

    def worker(i: int):
        # i % 3 == 0: normal; otherwise odd i -> key_1=429, even i -> *=503
        headers = {"X-Simulate-Failure": "key_1=429" if i % 2 == 1 else "*=503"} if i % 3 else {}
        results[i] = httpx.post(f"{base}/chat", json={"session_id": f"c-{i}", "message": f"concurrent {i}"},
                                headers=headers, timeout=20)

    try:
        threads = [threading.Thread(target=worker, args=(i,)) for i in range(12)]
        for th in threads:
            th.start()
        for th in threads:
            th.join()
    finally:
        server.should_exit = True
        t.join(timeout=5)

    for i, r in results.items():
        if i % 3 == 0:          # normal
            assert r.status_code == 200 and r.json()["metadata"]["key_id"] == "key_1", i
            assert r.json()["metadata"]["fallback_attempts"] == 0
        elif i % 2 == 1:        # key_1=429
            assert r.status_code == 200 and r.json()["metadata"]["key_id"] == "key_2", i
        else:                   # *=503
            assert r.status_code == 503, i
    assert len(results) == 12
