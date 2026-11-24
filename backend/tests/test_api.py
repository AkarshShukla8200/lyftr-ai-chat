"""Prompt 1 scope: validation, history, persistence, errors, routes, CORS."""

from __future__ import annotations

import sqlite3

import pytest
from fastapi.testclient import TestClient

from app.config import Settings, sqlite_path_from_url
from app.main import create_app

from .conftest import ALLOWED_ORIGIN, FakeGateway, make_settings, raise_unavailable


def chat(client, **body):
    return client.post("/chat", json=body)


def row_count(settings) -> int:
    conn = sqlite3.connect(settings.database_path)
    try:
        return conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0] + conn.execute(
            "SELECT COUNT(*) FROM sessions"
        ).fetchone()[0]
    finally:
        conn.close()


# ---------- routes ----------

@pytest.mark.parametrize("path", ["/docs", "/redoc", "/openapi.json", "/"])
def test_only_three_endpoints(client, path):
    r = client.get(path)
    assert r.status_code == 404
    assert r.headers["content-type"].startswith("application/json")
    assert "detail" in r.json()


def test_health_ok(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "keys_configured": 2, "cache_enabled": True}


@pytest.mark.parametrize(
    "gw", [FakeGateway(keys_configured=0), FakeGateway(cache_enabled=False)]
)
def test_health_not_ready_is_503_json(settings, gw):
    with TestClient(create_app(settings, gw)) as c:
        r = c.get("/health")
    assert r.status_code == 503
    assert isinstance(r.json()["detail"], str)


# ---------- 422 validation ----------

@pytest.mark.parametrize(
    "body",
    [
        {"session_id": "s1"},                                   # missing message
        {"message": "hi"},                                      # missing session_id
        {"session_id": "s1", "message": ""},                    # empty
        {"session_id": "s1", "message": "   \n\t "},            # whitespace only
        {"session_id": "s1", "message": "a" * 4001},            # too long
        {"session_id": "s1", "message": "  " + "a" * 4001},     # too long after trim
        {"session_id": "", "message": "hi"},                    # empty session
        {"session_id": "   ", "message": "hi"},                 # whitespace session
        {"session_id": "s" * 129, "message": "hi"},             # session too long
        {"session_id": None, "message": "hi"},                  # null
        {"session_id": "s1", "message": None},                  # null
        {"session_id": 123, "message": "hi"},                   # int, no coercion
        {"session_id": "s1", "message": 42},                    # int, no coercion
        {"session_id": "s1", "message": "hi", "system_prompt": 5},
        {"session_id": "s1", "message": "hi", "system_prompt": "p" * 4001},
    ],
)
def test_validation_422(client, settings, gateway, body):
    r = chat(client, **body)
    assert r.status_code == 422
    assert "detail" in r.json()
    assert gateway.calls == []
    assert row_count(settings) == 0


def test_malformed_json_422(client, settings):
    r = client.post("/chat", content=b"{bad json", headers={"Content-Type": "application/json"})
    assert r.status_code == 422
    assert "detail" in r.json()
    assert row_count(settings) == 0


def test_non_object_body_422(client):
    r = client.post("/chat", json=["not", "an", "object"])
    assert r.status_code == 422


def test_padded_4000_is_valid_and_trimmed(client, gateway):
    msg = "a" * 4000
    r = chat(client, session_id="s-pad", message=f"   {msg}  \n")
    assert r.status_code == 200
    assert gateway.calls[0][-1] == {"role": "user", "content": msg}
    hist = client.get("/sessions/s-pad/messages").json()
    assert hist["messages"][0]["content"] == msg


def test_session_id_128_ok_and_stored_unmodified(client):
    sid = " x" + "y" * 126  # 128 chars with a leading space
    r = chat(client, session_id=sid, message="hi")
    assert r.status_code == 200
    assert r.json()["session_id"] == sid


# ---------- 200 shape ----------

def test_chat_response_shape(client):
    r = chat(client, session_id="s-shape", message="Hello")
    assert r.status_code == 200
    body = r.json()
    assert set(body) == {"session_id", "reply", "metadata"}
    assert body["session_id"] == "s-shape"
    assert body["reply"]
    md = body["metadata"]
    assert set(md) == {
        "resolution_source", "model", "latency_ms", "input_tokens",
        "output_tokens", "key_id", "fallback_attempts",
    }
    assert md["resolution_source"] == "LIVE_INFERENCE"
    assert isinstance(md["latency_ms"], int)
    assert md["key_id"] == "key_1"
    assert md["fallback_attempts"] == 0


# ---------- history ----------

def test_history_exact_shape_and_order(client):
    chat(client, session_id="s-h", message="first")
    chat(client, session_id="s-h", message="second")
    r = client.get("/sessions/s-h/messages")
    assert r.status_code == 200
    body = r.json()
    assert set(body) == {"session_id", "messages"}
    assert body["session_id"] == "s-h"
    msgs = body["messages"]
    assert [(m["role"], m["content"]) for m in msgs] == [
        ("user", "first"), ("assistant", "echo: first"),
        ("user", "second"), ("assistant", "echo: second"),
    ]
    assert set(msgs[0]) == {"role", "content"}
    assert set(msgs[1]) == {"role", "content", "metadata"}
    assert msgs[1]["metadata"]["resolution_source"] == "LIVE_INFERENCE"
    assert all(m["role"] != "system" for m in msgs)


def test_unknown_session_404(client):
    r = client.get("/sessions/never-seen/messages")
    assert r.status_code == 404
    assert r.json() == {"detail": "session not found"}


def test_multi_turn_context_sent_in_order(client, gateway):
    chat(client, session_id="s-mt", message="My name is Ada.")
    chat(client, session_id="s-mt", message="What is my name?")
    sent = gateway.calls[1]
    assert [m["role"] for m in sent] == ["system", "user", "assistant", "user"]
    assert sent[1]["content"] == "My name is Ada."
    assert sent[2]["content"] == "echo: My name is Ada."
    assert sent[3]["content"] == "What is my name?"


def test_sessions_isolated(client, gateway):
    chat(client, session_id="s-a", message="alpha")
    chat(client, session_id="s-b", message="beta")
    assert len(gateway.calls[1]) == 2  # system + its own message only
    a = client.get("/sessions/s-a/messages").json()["messages"]
    b = client.get("/sessions/s-b/messages").json()["messages"]
    assert [m["content"] for m in a] == ["alpha", "echo: alpha"]
    assert [m["content"] for m in b] == ["beta", "echo: beta"]


# ---------- system prompt ----------

def test_default_system_prompt_used(client, gateway, settings):
    chat(client, session_id="s-d", message="hi")
    assert gateway.calls[0][0] == {"role": "system", "content": settings.default_system_prompt}


def test_system_prompt_fixed_per_session(client, gateway):
    chat(client, session_id="s-p", message="one", system_prompt="  Be a pirate.  ")
    chat(client, session_id="s-p", message="two", system_prompt="Be a robot.")
    assert gateway.calls[0][0]["content"] == "Be a pirate."
    assert gateway.calls[1][0]["content"] == "Be a pirate."


def test_blank_system_prompt_means_default(client, gateway, settings):
    chat(client, session_id="s-bp", message="hi", system_prompt="   ")
    assert gateway.calls[0][0]["content"] == settings.default_system_prompt


def test_system_prompt_from_first_successful_request(client, gateway, settings):
    gateway.behaviour = raise_unavailable
    r = chat(client, session_id="s-fs", message="hi", system_prompt="Prompt A")
    assert r.status_code == 503
    gateway.behaviour = None
    chat(client, session_id="s-fs", message="hi", system_prompt="Prompt B")
    assert gateway.calls[-1][0]["content"] == "Prompt B"


# ---------- failure: 503, rollback, 500 ----------

def test_all_providers_unavailable_503_and_no_writes(client, gateway, settings):
    gateway.behaviour = raise_unavailable
    r = chat(client, session_id="s-fail", message="hello")
    assert r.status_code == 503
    assert r.json() == {"detail": "all providers unavailable"}
    assert row_count(settings) == 0
    assert client.get("/sessions/s-fail/messages").status_code == 404


def test_failure_mid_session_keeps_history_unchanged(client, gateway):
    chat(client, session_id="s-mid", message="ok")
    gateway.behaviour = raise_unavailable
    assert chat(client, session_id="s-mid", message="fails").status_code == 503
    msgs = client.get("/sessions/s-mid/messages").json()["messages"]
    assert [m["content"] for m in msgs] == ["ok", "echo: ok"]


def test_db_write_failure_rolls_back(settings, gateway, monkeypatch):
    app = create_app(settings, gateway)
    with TestClient(app, raise_server_exceptions=False) as c:
        original_dumps = __import__("json").dumps

        def boom(obj, *a, **k):  # fails while building the assistant row
            if isinstance(obj, dict) and "resolution_source" in obj:
                raise RuntimeError("disk full")
            return original_dumps(obj, *a, **k)

        monkeypatch.setattr("app.db.json.dumps", boom)
        r = c.post("/chat", json={"session_id": "s-rb", "message": "hi"})
    assert r.status_code == 500
    assert row_count(settings) == 0


def test_internal_error_500_json_with_cors(settings):
    def explode(_messages):
        raise RuntimeError("secret internal detail")

    gw = FakeGateway(behaviour=explode)
    with TestClient(create_app(settings, gw), raise_server_exceptions=False) as c:
        r = c.post(
            "/chat",
            json={"session_id": "s-500", "message": "hi"},
            headers={"Origin": ALLOWED_ORIGIN},
        )
    assert r.status_code == 500
    assert r.json() == {"detail": "internal server error"}
    assert r.headers.get("access-control-allow-origin") == ALLOWED_ORIGIN
    assert "secret internal detail" not in r.text
    assert row_count(settings) == 0


def test_internal_error_log_has_class_only(settings, caplog):
    def explode(_messages):
        raise RuntimeError("secret internal detail")

    gw = FakeGateway(behaviour=explode)
    with TestClient(create_app(settings, gw), raise_server_exceptions=False) as c:
        c.post("/chat", json={"session_id": "s-log", "message": "hi"})
    assert "RuntimeError" in caplog.text
    assert "secret internal detail" not in caplog.text


# ---------- CORS ----------

def test_cors_preflight_allows_simulation_header(client):
    r = client.options(
        "/chat",
        headers={
            "Origin": ALLOWED_ORIGIN,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type,x-simulate-failure",
        },
    )
    assert r.status_code == 200
    assert r.headers["access-control-allow-origin"] == ALLOWED_ORIGIN
    allowed = r.headers["access-control-allow-headers"].lower()
    assert "x-simulate-failure" in allowed and "content-type" in allowed


def test_cors_rejects_unknown_origin(client):
    r = client.options(
        "/chat",
        headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "POST"},
    )
    assert r.headers.get("access-control-allow-origin") is None


def test_cors_on_422_and_503(client, gateway):
    r = client.post("/chat", json={"session_id": "", "message": "x"}, headers={"Origin": ALLOWED_ORIGIN})
    assert r.headers.get("access-control-allow-origin") == ALLOWED_ORIGIN
    gateway.behaviour = raise_unavailable
    r = client.post("/chat", json={"session_id": "c", "message": "x"}, headers={"Origin": ALLOWED_ORIGIN})
    assert r.status_code == 503
    assert r.headers.get("access-control-allow-origin") == ALLOWED_ORIGIN


# ---------- config ----------

@pytest.mark.parametrize(
    "url,path",
    [
        ("sqlite:////data/app.db", "/data/app.db"),
        ("sqlite:///./data/app.db", "./data/app.db"),
        ("sqlite:///C:/tmp/app.db", "C:/tmp/app.db"),
    ],
)
def test_sqlite_url_parsing(url, path):
    assert sqlite_path_from_url(url) == path


def test_settings_parsing_and_key_repr(tmp_path):
    s = make_settings(
        tmp_path,
        ALLOWED_ORIGINS=" http://a.com/ , https://b.com ",
        ENABLE_FAILURE_SIMULATION="True",
    )
    assert s.allowed_origins == ["http://a.com", "https://b.com"]
    assert s.enable_failure_simulation is False  # only exactly "true"
    assert s.keys_configured == 2
    assert "fake-key-one" not in repr(s)
    assert Settings.from_env({"ENABLE_FAILURE_SIMULATION": "true"}).enable_failure_simulation


def test_db_parent_dir_created_and_wal(tmp_path, gateway):
    s = make_settings(tmp_path, DATABASE_URL=f"sqlite:///{(tmp_path / 'nested' / 'x.db').as_posix()}")
    with TestClient(create_app(s, gateway)) as c:
        assert c.get("/health").status_code == 200
    conn = sqlite3.connect(s.database_path)
    try:
        assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    finally:
        conn.close()
