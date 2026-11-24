# Implementation Status

Read this file at the start of every new Claude Code session.

Last updated: 2026-11-24 (Prompt 0)

## Completed
- Prompt 0: read the 6-page PDF (text extracted with pypdf) and the prompt pack v4.
- Created `REQUIREMENTS_MATRIX.md` (76 rows covering PDF §1–§8 + README + rubric, plus ambiguity decisions).
- Created `.gitignore`, `.gitattributes`; initialised local git repo with `core.autocrlf=false` (repo-local setting only).

## Environment (verified 2026-11-24)
| Tool | Version | Notes |
|---|---|---|
| Python | 3.13.5 | |
| Node / npm | 24.11.1 / 11.4.1 | |
| Docker | 28.1.1 | Docker Desktop installed; daemon **not running** at check time (start Docker Desktop before Prompt 6) |
| git | 2.55.0 | |
| GNU make | 4.4.1 | installed 2026-11-24 via `winget install ezwinports.make` (open a new terminal to pick up PATH) |

Project folder is under OneDrive (`Desktop\lyftr_ai_project`); OneDrive sync of `node_modules`/`.venv` can be slow or lock files.

- Prompt 1 (2026-11-24): `backend/` with FastAPI, Pydantic v2, SQLite.
  - `app/config.py` env settings (keys hidden from repr; simulation flag only on exact `true`; `DATABASE_URL` sqlite:/// parsing).
  - `app/db.py` schema on startup (`messages` per PDF + index `(session_id,id)` + `sessions` table), WAL, `timeout=10`, new connection per operation, single `BEGIN IMMEDIATE` transaction for session row + user/assistant pair.
  - `app/schemas.py` strict validation (no coercion, trim-then-length, blank system_prompt = absent).
  - `app/gateway.py` interface only (`LLMGateway`, `LLMResult`, `AllProvidersUnavailable`).
  - `app/chat_service.py` prompt rebuild from SQLite, latency via `time.monotonic()`, persist after success only.
  - `app/main.py` `create_app(settings, gateway)`; 3 endpoints; docs/openapi disabled; catch-all 500 middleware registered before CORS; `/chat` is a sync `def`.
  - Dependencies pinned: `litellm==1.108.4` (newest stable ≥14 days old at 2026-11-24, uploaded 2026-11-09; 1.82.7/1.82.8/1.107.0 not on PyPI), fastapi 0.165.0, starlette 1.10.0, pydantic 2.14.4, uvicorn 0.54.0, diskcache 5.6.3; dev: pytest 9.2.0, httpx 0.28.1. Direct deps pinned; transitive deps not yet locked.

- Prompt 2 (2026-11-24): `app/llm_gateway.py` — app-owned ordered loop over keys, each `litellm.completion(model, api_key, messages, timeout, num_retries=0)`; no `max_tokens`; optional constant `LLM_TEMPERATURE` / `LLM_REASONING_EFFORT`; any `openai.APIError` subclass (all LiteLLM provider exceptions) or empty/blocked reply = key failure; logs only key_id, exception class and status. `app/server.py` production entrypoint (`uvicorn app.server:app`), LiteLLM debug logging off. `.env.example` created. `backend/scripts/live_check.py` for per-key live verification.
  - Verified on installed LiteLLM 1.108.4 (local fake Gemini server): 400 `API_KEY_INVALID` → `AuthenticationError`(401); 403 → `BadRequestError`(403); 502 → `APIConnectionError`; empty text and safety block return `content=None` with no exception (gateway treats as failure); key is sent in `x-goog-api-key` header, never in URL or logs.

- Prompt 3 (2026-11-24): LiteLLM built-in disk cache via `configure_cache()` (`Cache(type="disk", disk_cache_dir=LLM_CACHE_DIR, max_messages=None)`), enabled in `server.py`; hit detection via LiteLLM's `_hidden_params["cache_hit"]`; on hit key_id=null, fallback_attempts=0, stored usage replayed; simulation requests send `cache={"no-cache": True, "no-store": True}`; empty cached replies are refreshed.
  - Findings on LiteLLM 1.108.4 (all proven by probes/tests):
    - **Cache hits crash without `orjson` + `soundfile`**: `_should_defer_streaming_cache_hit_callbacks` imports the Anthropic pass-through → `litellm.proxy.*`. Same import present in every version checked (1.103.11, 1.104.8, 1.104.9, 1.105.7, 1.106.7, 1.108.16, 1.109.3, 1.110.2). Fix: pinned `orjson==3.13.0`, `soundfile==0.14.0` (both from LiteLLM's declared `proxy` extra; brings `cffi`, `numpy`). Rejected: full `litellm[proxy]` (~50 packages).
    - `max_messages` default 4 disables caching for >4 messages → set to None.
    - Cache key excludes `api_key`, `api_base`, `timeout`, `num_retries`; includes `model`, `messages`, `temperature`, `reasoning_effort` → cache is key-independent.
    - `no-cache` skips lookup but still stores; `no-store` prevents the write.
    - Empty replies ARE cached → refresh logic added.
  - Note: my first static scan wrongly reported 1.104.x/1.109.x/1.110.x as unaffected (missed the `experimental_pass_through` module name); corrected by a real run and a fixed scan.
- Dependency lock (2026-11-24, CLOSED): `backend/requirements.in` (direct pins) → `backend/requirements.txt` = full hash-locked lock (72 packages, `pip-compile --generate-hashes`, pip-tools 7.6.2 run from a separate scratch venv, not a project dependency). `requirements-dev.in` → `requirements-dev.txt` (76 packages, constrained to the runtime lock). Project venv synced with `pip-sync`: installed set == dev lock exactly (scripted check, no diffs); `pip check` clean; no Linux-only requirement missing from the runtime lock (markers evaluated for linux/x86_64/py3.13). `openai` back to 3.58.0 via the lock. 90 tests pass on the locked env.

- Prompt 4 (2026-11-24): `app/simulation.py` parser (`key_N=status` / `*=status`, statuses 429/500/502/503, whitespace tolerated, unknown well-formed key ids ignored, explicit key overrides `*`, malformed/unsupported/empty entry/duplicate → 422 string `detail`, empty header = absent). Header read in `/chat` only when `ENABLE_FAILURE_SIMULATION` is exactly `true`. Gateway raises the matching LiteLLM exception (`RateLimitError`/`InternalServerError`/`BadGatewayError`/`ServiceUnavailableError`, correct `status_code`) for a simulated key **without calling the provider**; unaffected keys call the real provider; any active simulation sends `cache={"no-cache": True, "no-store": True}`. Request-scoped object, no global state.

- Prompt 5 (2026-11-24): `frontend/` React 19.1.10 + Vite 8.3.7 + @vitejs/plugin-react 6.3.0 (newest releases ≥14 days old; exact pins via `.npmrc save-exact`; `package-lock.json` with integrity hashes; `npm install` reported 0 vulnerabilities). `src/session.js` (`s-` + `crypto.randomUUID()` per load, never stored), `src/api.js` (only newest message sent; 90 s timeout; 422 detail → sentence; 503/500/network/timeout/invalid-response messages; `VITE_API_BASE_URL`), `src/App.jsx` (Enter/Shift+Enter, duplicate sends blocked, input cleared on send, auto-scroll, >5 s cold-start hint, system prompt sent until first success then locked), `src/components/AssistantMessage.jsx` (value-only `meta-*`). `.claude/launch.json` for the dev preview.

- Prompt 6 (2026-11-24): `backend/Dockerfile` (2 stages; builder venv via `pip install --require-hashes --only-binary=:all:`; runtime `python:3.13.18-slim@sha256:6d68eb63…`, non-root `app` uid 999, `/data` created+chowned before `USER`, `CMD uvicorn … --port ${PORT:-8000} --workers 1`), `frontend/Dockerfile` (2 stages; `node:24.22.3-slim@sha256:32e57b57…` `npm ci --ignore-scripts`, `VITE_API_BASE_URL` build arg → `nginx:1.30.8-alpine@sha256:6437a63b…` on :3000 with SPA fallback, `frontend/nginx.conf`), `.dockerignore` in both, root `docker-compose.yml` (named volume `app-data:/data`, `DATABASE_URL`/`LLM_CACHE_DIR` fixed in compose, python-urllib healthcheck, frontend not gated on health), root `Makefile` exactly per pack (TAB recipes, LF).
  - nginx: chose 1.30.8 stable over `1.29-alpine` (image from April 2026). `nginx:stable-alpine` and `nginx:1.30.8-alpine` had different digests but same build date, nginx and Alpine 3.24.4; pinned the exact-tag digest.
- Vitest (after Prompt 6, per pack): vitest 5.1.0, @testing-library/react 16.3.3, @testing-library/dom 10.4.2, jsdom **29.1.1** (31.0.0 requires Node ≥24.15; local Node is 24.11.1). `frontend/src/App.test.jsx` (11 tests), `vitest.config.js`, `src/test-setup.js` (jsdom lacks `scrollIntoView`).
  - npm 11.4.1 (local global npm) crashes installing vitest (`Cannot read properties of null (reading 'edgesOut')` in arborist `#loadPeerSet`); used `npx npm@11.19.1` (= npm bundled in the node:24.22.3 build image) for frontend installs; global npm untouched. Lockfile now written by the same npm as Docker `npm ci`.

## Known gaps (intentional, by prompt)

## Test results
- 2026-11-24, Prompt 1: `backend/.venv/Scripts/python.exe -m pytest -q` → **48 passed** (fake gateway; no live keys used).
- 2026-11-24, Prompt 2: `pytest -q` → **75 passed** (27 new: real LiteLLM against local fake Gemini HTTP server; no live keys used).
- 2026-11-24: `live_check.py` → exit 2 "LLM_MODEL not configured; need at least 2 keys" (no `.env`).
- 2026-11-24: model switched to `gemini/gemini-3.5-flash-lite` after user's AI Studio rate-limit table (3.8 Flash: 5 RPM / 20 RPD; 3.5 Flash Lite: 15 RPM / 500 RPD per project). LiteLLM 1.108.4 maps it (supports system messages and reasoning).
- 2026-11-24: `live_check.py` with user's keys → **both keys FAIL AuthenticationError**. Direct REST call to Google (no LiteLLM) → HTTP 400 `API_KEY_INVALID` for both. Key values are 26 chars, no `AIza` prefix, no whitespace/quotes, distinct. Conclusion: Google rejects the key values themselves; gateway code is not the cause. Resolved: user re-copied full keys.

## Decisions recorded
- Provider: two Gemini API keys from **two separate Google Cloud projects**, same model for both (user delegated choice; chosen so a cached reply is valid regardless of which key served it and `model` is constant).
- Model (proposed 2026-11-24, from aistudio.google.com/docs/models + /deprecations): `gemini/gemini-3.8-flash` (badged Stable). Avoid `gemini-2.0-flash` (shut down 1 Jun 2026), `gemini-2.5-*` (existing users only), `gemini-3.5-flash` (routes to 3.6), `gemini-flash-latest` (hot-swapped alias). Alternative: `gemini-3.5-flash-lite` (Stable) if its free RPD is higher. Docs: limits are per project, not per key; exact per-model numbers only at aistudio.google.com/rate-limit. New AI Studio keys are "auth keys" since 28 May 2026; LiteLLM compatibility with them is unverified until the live check.
- `.env` created at repo root from `.env.example` with placeholder keys (git-ignored, verified with `git check-ignore`).
- Hosting: backend on **Render** (Docker), frontend on **Vercel**. Render persistent-disk availability/pricing to be checked against current docs in Prompt 7.

## Blockers / inputs needed from user
1. Two Gemini keys (separate projects) in local `.env` only — never in chat.
2. Exact Gemini model ID, copied from AI Studio today (confirm not deprecated and not an alias).
3. Render, Vercel and GitHub accounts (user creates).
4. Actual assignment receipt time (deadline = receipt + 24 h).

## Critical-path plan (time-boxed, ~7–8 h of work)
| Window | Deliverable | Stop condition |
|---|---|---|
| 0:00–0:30 | Prompt 0 + keys, model, hosting accounts, GNU make | each key answers one real request |
| 0:30–1:30 | Prompt 1: FastAPI, SQLite, validation, errors | tests green without keys |
| 1:30–2:30 | Prompt 2: LiteLLM loop failover, metadata | mocked failover tests + 1 live call per key |
| 2:30–3:15 | Prompt 3: disk cache, hit detection, `no-cache` proof | cache tests green |
| 3:15–3:45 | Prompt 4: `X-Simulate-Failure` | simulation tests green incl. after cache warm |
| 3:45–5:00 | Prompt 5: React UI | selectors + error bubbles |
| 5:00–6:00 | Prompt 6: Docker, Makefile, persistence | `make up` on Windows; data survives restart |
| 6:00–7:15 | Prompt 7: deploy + README | public smoke tests pass |
| 7:15–8:00 | Prompt 8: audit, demo script, cache clear | all mandatory items PASS/BLOCKED |

## Dependency / secret checklist
- [ ] Two working keys from separate quotas, stored only in local `.env` and host secrets
- [ ] Exact current model ID (not `gemini-2.0-flash`, not an alias ID, no Gemini 2.5 unless already accessible)
- [ ] LiteLLM exact version, not 1.82.7 / 1.82.8 / 1.107.0
- [ ] All Python and npm deps pinned exactly
- [ ] GNU make installed (`make --version`)
- [ ] Hosting accounts (backend + frontend) and GitHub repo created by user

## Deployment plan
- Backend: a host with a persistent volume at `/data` if usable within 30 min (candidates to check against current docs: Railway, Fly.io, Render, Hugging Face Spaces); otherwise ephemeral disk with the limitation stated in README.
- Frontend: static build on Vercel / Netlify / Cloudflare Pages with `VITE_API_BASE_URL` = backend https URL.
- Backend env: `LLM_API_KEYS`, `LLM_MODEL`, `DATABASE_URL`, `LLM_CACHE_DIR`, `ALLOWED_ORIGINS` (exact frontend origin), `ENABLE_FAILURE_SIMULATION=true`, `DEFAULT_SYSTEM_PROMPT`, `LLM_TIMEOUT_SECONDS=30`.

- 2026-11-24: `live_check.py` after re-copy → **key_1 OK** (2065 ms, 26 in / 21 out tokens, non-empty reply), **key_2 OK** (1463 ms, 26 in / 21 out, non-empty reply); different message per key. **Prompt 2 gate PASSED.** `LLM_REASONING_EFFORT` left unset (outputs are short; no evidence it is needed).

- 2026-11-24, Prompt 3: `pytest -q` → **90 passed** (15 new cache tests, real LiteLLM disk cache + local fake Gemini).
- 2026-11-24, Prompt 3 live (real keys, production `app.server:app` via TestClient, scratch DB/cache): health 200 `{"status":"ok","keys_configured":2,"cache_enabled":true}`; session A → `LIVE_INFERENCE`, key_1, 1873 ms, 30 in / 31 out; session B same unique message → `LLM_CACHE`, key_id null, 177 ms, 30 in / 31 out; stored replies byte-identical (177 chars). **Prompt 3 gate PASSED** (no-cache/no-store proven by tests).

- 2026-11-24, Prompt 4: `pytest -q` → **145 passed** (55 new). First run had 1 failure caused by a wrong header/assertion mapping in my concurrency test (app behaved correctly per logs); test fixed, rerun green.
- 2026-11-24, Prompt 4 live (real keys, production app, flag true, scratch DB/cache): warm → LIVE key_1 1455 ms 25/17; same msg new session → LLM_CACHE null 226 ms 25/17; `key_1=429` → 200 LIVE **key_2**, fallback_attempts **1** (fresh reply text differs → cache skipped); `key_1=500` → 200 LIVE **key_2**, **1**; `*=429` → **503** `all providers unavailable`, history **404**; plain request afterwards → LLM_CACHE with the original reply (simulations did not overwrite cache); `key_1=404` → 422. Logs show only key_id/class/status. Also re-confirms Prompt 2/3 live behaviour on the final locked dependency set (openai 3.58.0). **Prompt 4 gate PASSED.**

- 2026-11-24, Prompt 5 browser verification (built-in browser, local backend `uvicorn app.server:app` with real keys + Vite dev server on :3000): turn 1 → LIVE_INFERENCE 1372 ms 25/14; turn 2 "What is my favourite colour?" → "Teal" (52 in); `meta-*` contents value-only (e.g. "LIVE_INFERENCE", "gemini/gemini-3.5-flash-lite", "1372 ms", "25", "14"); chat-input empty after every send; reload → new session id, no localStorage/sessionStorage keys; same first message after reload → LLM_CACHE, identical text, 25/14, 197 ms; 4001-char message → real 422 shown as error-message "Request rejected: message must be at most 4000 characters after trimming."; real 503 (header injected via fetch wrapper) → error-message, DB still only 2 rows for that session; stubbed 500 and network error → error-message; cold-start hint appears after 5 s, send disabled while pending; 375 px light mode → no horizontal overflow. Only console errors = browser's own 422/503 resource logs. `npm run build` OK. **Prompt 5 gate PASSED** (Vitest pending post-Prompt 6).

- 2026-11-24, Prompt 6 (Windows PowerShell, Docker 28.1.1, Compose v2.35.1, GNU make 4.4.1): `make up` exit 0 → health 200 `{"status":"ok","keys_configured":2,"cache_enabled":true}`, container `healthy`; `/docs` `/redoc` `/openapi.json` `/` → 404; frontend `/` and deep link → 200; built bundle contains `http://localhost:8000`; CORS preflight from `http://localhost:3000` allows `X-Simulate-Failure`; run 1795513453: A → LIVE key_1 1210 ms 27/28, B same msg → LLM_CACHE null 153 ms 27/28 identical reply; follow-up in A → LIVE 64/6; `key_1=429` and `key_1=500` → 200 key_2 attempts 1; `*=429` → 503 `{"detail":"all providers unavailable"}` (+ CORS header) and history 404; blank message / empty session_id / 4001 chars / malformed JSON → 422.
  - Persistence: `/data` owned by `app`, contains `app.db` + `litellm-cache/cache.db`; `make down` → 0 containers, volume kept; `make up` → history A still 4 messages; same first message in new session → LLM_CACHE 230 ms identical reply (no provider call).
  - Missing `.env` (scratch dir with only the Makefile): PowerShell and Git Bash `sh` both print `Makefile:4: *** .env missing - copy .env.example to .env and add two keys.  Stop.` exit 2; `make -n up down` with a `.env` prints only the two docker commands.
  - Secrets: 50 files git would commit → 0 contain a real key, 0 match `AIza…`/`sk-…`/`gsk_…`; no `.env`/db/data/PDF/node_modules/venv/dist. Images: no `.env` files, keys absent from image config + history + app files; backend `/app` contains only `app/`.
  - Docker UI in browser: message → LIVE_INFERENCE, 1442 ms, input cleared.
  - Rebuild after Vitest deps: `make up` exit 0, health 200, frontend 200. `make down` at end (volume kept).
  - Frontend `npx vitest run` → **11 passed** (first run: 11 failed because jsdom lacks `scrollIntoView` → setup stub; then 2 failed from my test reusing one Response object → fresh Response per call). Backend `pytest` → **145 passed**. **Prompt 6 gate PASSED.**

- 2026-11-24, Prompt 7 (in progress): decisions — Render **Free** (no persistent disk per render.com/docs/free; limitation stated in README §3), commits authored by the user's git identity with **no Claude co-author trailer** (user request). README written (URLs + editor PENDING), `frontend/vercel.json` SPA rewrite. Commit `5921815` (52 files; secret scan 0 keys) pushed by the user via Git Credential Manager to https://github.com/AkarshShukla8200/lyftr-ai-chat (remote main == local HEAD; anonymous API 200, `private: false`, owner AkarshShukla8200; `.env` raw URL 404).

- 2026-11-24: User reported the Render deploy without giving the URL. I **assumed** Render's default URL for the service name — WRONG: that address belongs to an unrelated service owned by someone else (its `/docs`, `/redoc`, `/openapi.json` return 200; model `groq/openai/gpt-oss-120b`; Pydantic default 422 text). ~9 harmless test requests (no keys, no personal data) were sent there before I noticed; stopped. **None of those results count as evidence.** Need the real URL from the Render dashboard.

- 2026-11-24: Real backend URL from user: **https://lyftr-chat-backend-spyc.onrender.com** (identity confirmed: docs/openapi 404, our validator text). First `/health` → 503 "LLM_MODEL not configured; no API keys configured" (service had no env vars). With the user's sign-in in the built-in browser I added 7 non-secret env vars + an empty `LLM_API_KEYS` row; the **user pasted the keys** (I do not enter real keys) and clicked "Save, rebuild, and deploy". 16:52 → health 200 `{"status":"ok","keys_configured":2,"cache_enabled":true}`.
- 2026-11-24, deployed backend smoke test (run 1795519338): `/docs` `/redoc` `/openapi.json` `/` → 404; A → LIVE key_1 4408 ms 27/26 `gemini/gemini-3.5-flash-lite`; B same msg → LLM_CACHE null 994 ms 27/26, stored replies identical (139 chars); follow-up A → LIVE 62/6 context kept; `key_1=429` → key_2/1; `key_1=500` → key_2/1; `*=429` → 503 + history 404; blank message + malformed JSON → 422; history shape exact. **Backend deployment PASS.**

- 2026-11-24, Vercel: after the user signed in and approved the GitHub login + GitHub app (only `lyftr-ai-chat`), I imported the repo as "frontend" project (team spartan, Hobby), Root Directory `frontend`, preset Vite, env `VITE_API_BASE_URL=https://lyftr-chat-backend-spyc.onrender.com`, Deploy → "Deployed to Production". Production domain (read from Settings → Domains): **https://lyftr-ai-chat-six.vercel.app** — anonymous GET 200, title "Lyftr Chat", bundle contains the Render URL and 0 `localhost:8000`, deep link 200.
- Render `ALLOWED_ORIGINS` changed (revealed only that row) to `https://lyftr-ai-chat-six.vercel.app` → Save, rebuild, deploy → 16:59:39 preflight allows the Vercel origin, `localhost:3000` no longer allowed; health still `keys_configured: 2` (masked values survived the save).
- Live UI (built-in browser on the Vercel URL): "favourite city Kyoto" → LIVE 33/15 8343 ms; follow-up → "Kyoto" (62 in); input cleared; reload → new session id; same first message → LLM_CACHE identical reply 33/15 755 ms; no error bubbles. **Deployment gate PASSED.**

- 2026-11-24, Prompt 8 audit: README headings = PDF exactly; testids, 3 routes, env vars all present. pytest 145 passed, vitest 11 passed, build OK. Live audit (run 1795520097) 34/36 on first pass — the 2 fails were one multi-turn request that hit a REAL Gemini outage (Render log 11:35 UTC: key_1 Timeout 408, key_2 ServiceUnavailableError 503 → clean 503, nothing stored; my audit script did not assert turn-1 status). Re-run with that assertion → PASS both → 36/36. Git history (2 commits, 55 files): 0 keys, 0 key-like strings, no .env/PDF/db/data. Redacted the other service's URL from this file; corrected README cache-timing sentence to measured values. Verified Render "Manual Deploy → Restart service" exists. UI header now shows the full, selectable session id (for the demo's history step). `FINAL_VERIFICATION.md` written (evidence, limitations, timed demo script, cache-clear steps, submission text with video PENDING).

- 2026-11-24 evening: video uploaded by user to Google Drive (anonymous request → 200, title "lyftr_ai_proj.mp4", no login redirect). Editor: Claude Code only. README updated (no PENDING). Cache clear: Render "Restart service" (19:07) did NOT wipe /data (post-17:06 session still 200); "Deploy latest commit" (19:08) did → that session 404 at 19:09:33; afterwards only `/health` (ok, 2 keys, cache on) + read-only history. All four URLs anonymous 200. **READY TO SUBMIT.**

## Next steps (superseded)
User: record + upload 2–3 min voice demo (public link); tell me the editor for README §5. Then Prompt 8 audit, cache clear after recording, submission text. (Docker, root dir `backend`, Free, env vars, health path `/health`) → send backend URL. Then Vercel (root `frontend`, `VITE_API_BASE_URL`) → send frontend URL. Then set Render `ALLOWED_ORIGINS` to the Vercel origin.
