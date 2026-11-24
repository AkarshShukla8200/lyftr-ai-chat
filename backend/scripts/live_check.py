"""Live check: one real request per configured key, a different message per key.

Usage (from the repo root):
    backend/.venv/Scripts/python.exe backend/scripts/live_check.py   # Windows
    backend/.venv/bin/python backend/scripts/live_check.py           # Linux/macOS

Reads LLM_API_KEYS / LLM_MODEL / LLM_MODELS / LLM_* from ./.env (or the
environment). Prints only key ids, model, token counts and a short reply
preview; never prints keys or raw provider error text. Uses no cache.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import litellm  # noqa: E402

from app.config import Settings  # noqa: E402
from app.llm_gateway import EmptyReplyError, _extract_reply, build_slots  # noqa: E402


def load_env_file(path: Path) -> dict[str, str]:
    env: dict[str, str] = {}
    if not path.exists():
        return env
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def main() -> int:
    litellm.suppress_debug_info = True
    env = {**load_env_file(Path.cwd() / ".env"), **{k: v for k, v in os.environ.items() if k.startswith("LLM_")}}
    settings = Settings.from_env(env)
    problems = settings.config_problems()
    if settings.keys_configured < 2:
        problems.append(f"need at least 2 keys in LLM_API_KEYS, found {settings.keys_configured}")
    if problems:
        print("CONFIG PROBLEM:", "; ".join(problems))
        return 2

    failed = 0
    for slot in build_slots(settings):
        msg = f"Reply with one short sentence confirming you received check {slot.key_id} at {time.time():.0f}."
        kwargs = dict(model=slot.model, api_key=slot.api_key, messages=[{"role": "user", "content": msg}],
                      num_retries=0, timeout=settings.llm_timeout_seconds)
        if settings.llm_temperature is not None:
            kwargs["temperature"] = settings.llm_temperature
        if settings.llm_reasoning_effort:
            kwargs["reasoning_effort"] = settings.llm_reasoning_effort
        started = time.monotonic()
        try:
            resp = litellm.completion(**kwargs)
            reply = _extract_reply(resp)
        except EmptyReplyError:
            print(f"{slot.key_id}: FAIL EmptyReplyError (model={slot.model})")
            failed += 1
            continue
        except Exception as exc:  # report class/status only
            print(f"{slot.key_id}: FAIL {type(exc).__name__} status={getattr(exc, 'status_code', None)} (model={slot.model})")
            failed += 1
            continue
        ms = int((time.monotonic() - started) * 1000)
        u = resp.usage
        print(f"{slot.key_id}: OK model={slot.model} latency_ms={ms} input_tokens={u.prompt_tokens} "
              f"output_tokens={u.completion_tokens} reply={reply.strip()[:80]!r}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
