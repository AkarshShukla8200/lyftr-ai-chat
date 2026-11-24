# Requirements Matrix

Source of truth: `Lyftr_AI_Full_Stack_Assignment.pdf` (6 pages). "PDF §x" = section in the PDF. "Pack" = refinement from the prompt pack v4 where the PDF is silent.
Status values: TODO / IN PROGRESS / PASS (with real evidence) / BLOCKED (with reason). Nothing is PASS until a real test ran.

| # | Requirement | Source | Code location (planned) | Test / verification | Status |
|---|---|---|---|---|---|
| **Stack & tooling** |||||
| 1 | React frontend | PDF p1 | `frontend/` (React + Vite) | `npm run build` | PASS: React 19.1.10 + Vite 8.3.7, `npm run build` OK |
| 2 | Python FastAPI backend | PDF p1 | `backend/app/` | pytest | IN PROGRESS (app built, 48 tests pass) |
| 3 | SQLite only for storage (no Redis/Postgres) | PDF §2 Storage | `backend/app/db.py` | code review, compose has no other services | PASS: compose has only backend + frontend; SQLite file on volume |
| 4 | LiteLLM gateway, exact pinned version (not 1.82.7 / 1.82.8 / 1.107.0) | PDF §2, Pack | `backend/requirements.txt` | `pip show litellm` | PASS: litellm==1.108.4 pinned (not 1.82.7/1.82.8/1.107.0) |
| **§1 Objective** |||||
| 5 | Working full-stack app, deployed live | PDF §1 | all | public URLs smoke test | TODO |
| 6 | AI model integration keeping conversation context | PDF §1 | `backend/app/chat_service.py` | multi-turn test | IN PROGRESS: live model call works; multi-turn tested with mocks |
| 7 | Keeps working when an API key fails | PDF §1 | `backend/app/llm_gateway.py` | failover tests | PASS (mocked failover) + both live keys verified |
| 8 | Speed/cost improved by caching | PDF §1 | `backend/app/llm_gateway.py` | cache tests | PASS: live 1873 ms → cache 177 ms (2026-11-24) |
| 9 | Explain decisions | PDF §1 | `README.md` §3 | README review | TODO |
| **§2 Frontend** |||||
| 10 | Clean UI to send messages and view multi-turn conversation | PDF §2 | `frontend/src/` | manual + Vitest | PASS (browser, local): multi-turn conversation UI, responsive (375 px no overflow), light/dark |
| 11 | Per-reply metadata: resolution source, model, latency ms, input/output tokens (this request only) | PDF §2, §5 | `frontend/src/components/AssistantMessage.jsx` | Vitest selector test | PASS (browser, local): source/model/latency/tokens per reply |
| 12 | Optional system prompt field (`system-prompt-input`) | PDF §2, §5 | `frontend/src/` | Vitest | PASS (browser): optional, sent until first success, then locked |
| **§2 Backend & LiteLLM** |||||
| 13 | Multi-turn: history stored per session in SQLite; prompt rebuilt from it | PDF §2, §3 | `backend/app/chat_service.py`, `db.py` | test: fact remembered; messages sent in order | PASS (tests + browser live): "teal" remembered on turn 2 |
| 14 | Key pool ≥2 keys, one or more models | PDF §2, §7 | `backend/app/config.py` (`LLM_API_KEYS`, `LLM_MODEL`, `LLM_MODELS`) | `/health keys_configured` | PASS: 2 keys (separate projects) each answered a live request 2026-11-24 |
| 15 | Auto-fallback on 429, quota, 5xx (+ timeout/conn/400/401/403/empty reply — Pack) | PDF §2, Pack | `llm_gateway.py` app-owned loop, `num_retries=0` | mocked tests per error type | PASS (real LiteLLM vs local fake Gemini): 429/quota/500/502/503/401/403/400 bad key/empty/blocked/timeout/connection → next key, 1 call per key |
| 16 | User never sees broken screen / unhandled exception | PDF §2 | backend error middleware + frontend error bubbles | 500-with-CORS test, UI error test | TODO |
| 17 | LiteLLM built-in cache (memory or disk); report LLM_CACHE / LIVE_INFERENCE | PDF §2 | `litellm.cache = Cache(type="disk")` | cache tests + live demo | PASS: LiteLLM disk Cache (max_messages=None); live LIVE→LLM_CACHE verified |
| 18 | Per-request token tracking returned with every response | PDF §2 | metadata from provider `usage` | tests | PASS (mocked provider) |
| **§2 Storage** |||||
| 19 | DB under Docker volume `/data/app.db` via `DATABASE_URL`; survives restarts | PDF §2 | compose named volume; `config.py` | `make down`/`make up` persistence check | PASS (Docker): /data/app.db on named volume; history + cache survived make down/up |
| 20 | Schema auto-created on startup; `messages` table exactly as given (extra tables/indexes allowed) | PDF §2 | `db.py init_db()` | test | PASS (unit): schema + index + sessions table, WAL |
| **§2 Deployment** |||||
| 21 | Frontend deployed & public | PDF §2, §7 | host TBD | incognito check | TODO |
| 22 | Backend deployed & running | PDF §2, §7 | host TBD | `/health` public | TODO |
| 23 | Both tiers connected via live URLs; backend allows frontend origin | PDF §2, §5 | `ALLOWED_ORIGINS`, `VITE_API_BASE_URL` | browser test + CORS preflight | TODO |
| **§3 API contract** |||||
| 24 | Exactly three endpoints; no docs/openapi/`/` | PDF §3, Pack | `backend/app/main.py` | test: `/docs` `/redoc` `/openapi.json` `/` → 404 | PASS (unit): /docs /redoc /openapi.json / → 404 JSON |
| 25 | `GET /health` → 200 `{"status":"ok","keys_configured":N,"cache_enabled":true}` only when DB reachable + keys loaded (+ cache on); else 503 | PDF §3, Pack | `main.py` | tests | PASS (unit + live): 200 {"status":"ok","keys_configured":2,"cache_enabled":true} |
| 26 | `POST /chat` request: `session_id` 1–128 chars; `message` 1–4000 after trim; `system_prompt` optional, overrides default for session | PDF §3 | `backend/app/schemas.py` | 422 tests incl. padded 4000, 4001 | PASS (unit): 15 invalid cases → 422, padded 4000 OK |
| 27 | Unknown session_id starts new session | PDF §3 | `chat_service.py` | test | PASS (unit) |
| 28 | 200 response fields: `session_id`, `reply` (non-empty), `metadata{resolution_source, model, latency_ms, input_tokens, output_tokens, key_id, fallback_attempts}` | PDF §3 | `schemas.py` | test exact shape | TODO |
| 29 | `model` = LiteLLM model name that produced reply | PDF §3 | gateway | test | PASS (mocked provider): slot model string |
| 30 | `latency_ms` integer server-measured | PDF §3 | `time.monotonic()` | test type | TODO |
| 31 | `input_tokens` = prompt tokens of this request; `output_tokens` = completion tokens | PDF §3 | provider `usage` | test | PASS (mocked provider): provider usage as reported |
| 32 | `key_id` = key_1.. ; null on cache; never the key | PDF §3 | gateway | tests + secret-leak test | PASS (mocked provider) + secret-leak test |
| 33 | `fallback_attempts` = keys failed before success; 0 on cache | PDF §3 | gateway | tests | PASS (mocked provider): 0/1/2 |
| 34 | `GET /sessions/{id}/messages`: history oldest first, no system prompt, shape `{session_id, messages:[{role,content[,metadata]}]}` | PDF §3 | `main.py`, `db.py` | test exact body | PASS (unit): exact shape, oldest first, no system |
| 35 | Errors always JSON with `detail`; no stack traces/HTML | PDF §3 | handlers + middleware | tests | PASS (unit): 404/422/500/503 JSON |
| 36 | 422: missing/empty message or session_id, message >4000, malformed JSON | PDF §3 | Pydantic + validators | tests | PASS (unit) |
| 37 | 503 `{"detail":"all providers unavailable"}` when every key fails | PDF §3 | gateway | test | PASS (mocked provider + unit) |
| 38 | 404 `{"detail":"session not found"}` for unknown session | PDF §3 | `main.py` | test | PASS (unit) |
| 39 | Failed request (422/503) not added to history | PDF §3 | single transaction after success | test: zero rows | PASS (unit): 0 rows after 422/503/500, rollback tested |
| 40 | Cache key = model + full message list (system + history + new) | PDF §3 | LiteLLM cache key | tests | PASS (tests): model + full ordered messages; api_key/api_base/timeout not in key (inspected) |
| 41 | Same first message in new session → LLM_CACHE second time; different message never from cache | PDF §3 | gateway | tests + live demo | PASS (tests + live) |
| 42 | Cache hit: identical reply, stored tokens, key_id null | PDF §4 (p4 top) | gateway | test | PASS (tests + live): identical 177-char reply, 30/31 tokens, key_id null |
| 43 | Client sends only new message | PDF §4 | frontend `api.js` | code review / Vitest | PASS (code): body is {session_id, message[, system_prompt]} only |
| 44 | Tokens per request; equal-length first messages ≈ same input_tokens | PDF §4 | gateway | live check | TODO |
| 45 | Cache hit faster than live call | PDF §4 | disk cache | test + live demo | PASS (test with 0.5 s provider delay + live 1873→177 ms) |
| **§4 Failover test hook** |||||
| 46 | `X-Simulate-Failure` header: comma-separated `key_id=status`, `*` = all; statuses 429/500/502/503 | PDF §4 | `backend/app/simulation.py` | tests | PASS (tests + live): parser; 429/500/502/503; `*`; whitespace; unknown keys ignored; malformed → 422 |
| 47 | Effect request-scoped only | PDF §4 | per-request object, no global state | concurrency test | PASS (tests): 12 concurrent mixed requests, no leakage; no global state |
| 48 | Honored only when `ENABLE_FAILURE_SIMULATION=true`; set on deployed backend | PDF §4 | `config.py`; host env | tests + deployed check | PASS (tests): flag must be exactly "true" (false/""/True/TRUE/1/yes/" true" ignored); deployed setting pending Prompt 7 |
| 49 | `key_1=429` → 200 key_2; `key_1=500` → 200 key_2; `*=429` → 503, nothing in history | PDF §4 | gateway | tests (also after cache warm — Pack) | PASS (tests + live 2026-11-24): key_1=429 → key_2/1; key_1=500 → key_2/1; *=429 → 503 + history 404; also after cache warm |
| 50 | Simulated request returns a real answer, never error wrapped in 200 | PDF §4 | gateway | test | PASS (tests + live): real reply from key_2, provider never called for simulated key |
| **§5 Frontend contract** |||||
| 51 | `chat-input` empty after sending | PDF §5 | `ChatInput` | Vitest | PASS (browser): empty after success, 422, 503, 500, network |
| 52 | `send-button` (Enter may also send) | PDF §5 | `ChatInput` | Vitest | PASS (browser): click and Enter both send; disabled while pending |
| 53 | `assistant-message` container with reply + meta elements | PDF §5 | `AssistantMessage` | Vitest | PASS (browser) |
| 54 | `meta-source`, `meta-model`, `meta-latency` (e.g. `812 ms`), `meta-input-tokens`, `meta-output-tokens` — value only | PDF §5, Pack | `AssistantMessage` | Vitest | PASS (browser): values only, e.g. "LIVE_INFERENCE", "1372 ms", "25" |
| 55 | `system-prompt-input` (optional) | PDF §5 | `App` | Vitest | PASS (browser) |
| 56 | New session on each page load | PDF §5 | `App` session id from `crypto.randomUUID()` | Vitest / manual reload | PASS (browser): reload → new id, no web storage used |
| 57 | 422/503 errors readable in chat, never blank screen | PDF §5 | `error-message` bubble | Vitest | PASS (browser): real 422 + real 503 (via injected header) + stubbed 500/network render as error-message, never assistant-message; 503 stored nothing |
| **§6 Docker** |||||
| 58 | `make up` → backend :8000, frontend :3000 | PDF §6 | `Makefile`, `docker-compose.yml` | real run on Windows | PASS (Windows PowerShell + GNU make 4.4.1): backend :8000, frontend :3000 |
| 59 | Multi-stage Dockerfiles, small runtime images (both) | PDF §6 | `backend/Dockerfile`, `frontend/Dockerfile` | `docker images` | PASS: 2-stage Dockerfiles; backend 164 MB (python:3.13.18-slim, non-root), frontend 27 MB (nginx:1.30.8-alpine); base images pinned by tag+digest |
| 60 | Root `docker-compose.yml` with named volume at `/data` | PDF §6 | `docker-compose.yml` | persistence check | PASS: root docker-compose.yml, named volume app-data at /data |
| 61 | Makefile with `up`, `down` | PDF §6 | `Makefile` | real run | PASS: up/down; portable (make built-ins only); verified under PowerShell and Git Bash sh; missing .env → clear message, exit 2 |
| 62 | All configuration via env vars | PDF §6 | `config.py`, `.env.example` | code review | PASS: all config via env (.env / compose environment / build arg) |
| **§7 Deliverables** |||||
| 63 | Submit within 24 h; every URL public, no login | PDF §7 | — | incognito checks | TODO |
| 64 | 2–3 min voice demo of deployed app: all endpoints, cache hit, failover via header | PDF §7 | user records | public link check | TODO (user) |
| 65 | Repo structure: `/backend`, `/frontend`, `docker-compose.yml`, `Makefile`, `.env.example`, `README.md` | PDF §7 | repo root | `ls` | PASS: /backend, /frontend, docker-compose.yml, Makefile, .env.example present (README in Prompt 7) |
| 66 | Backend tests included | PDF §7 | `backend/tests/` | pytest | PASS: 145 backend tests |
| 67 | Env vars `LLM_API_KEYS`, `DATABASE_URL`, `ALLOWED_ORIGINS`, `ENABLE_FAILURE_SIMULATION` (+ others) | PDF §7 | `config.py` | tests | PASS |
| 68 | `.env.example` lists every variable with placeholders; no real keys in repo | PDF §7 | `.env.example`, `.gitignore` | `git grep` for key prefixes | PASS: .env.example lists every variable; scan of 50 to-be-committed files + both images: 0 real keys, 0 key patterns, no .env |
| 69 | Public GitHub repo | PDF §7 | — | incognito | TODO (user) |
| **README (PDF p6)** |||||
| 70 | Six headings in order: Live URLs; Run locally (Docker and without); Design decisions; Verification; Setup Used; Bonus features | PDF p6 | `README.md` | review | TODO |
| **§8 Rubric (10 pts)** |||||
| 71 | System resilience: fallback on 429/quota/5xx incl. via header; clean 503; correct 422; no crashes | PDF §8 | rows 15, 35–39, 46–50 | — | TODO |
| 72 | Caching accuracy: labels, identical replies, hits faster | PDF §8 | rows 17, 40–45 | — | TODO |
| 73 | Token usage tracking shown with each reply in UI | PDF §8 | rows 18, 31, 54 | — | PASS (local): per-reply tokens in UI; equal cached tokens 25/14 |
| 74 | Multi-turn state: remembers, sessions separate, SQLite, history endpoint correct | PDF §8 | rows 13, 34 | — | TODO |
| 75 | Full-stack deployment live, connected, contract; `make up` works | PDF §8 | rows 21–23, 58 | — | IN PROGRESS: local make up PASS; deployment pending |
| 76 | Code quality, security, docs: LiteLLM for caching and fallback, multi-stage Dockerfiles, working Makefile, complete README | PDF §8 | rows 4, 59, 61, 70 | — | TODO |

## Ambiguities and chosen behaviour (conservative)

| Ambiguity | Choice | Rationale |
|---|---|---|
| PDF example model `gemini/gemini-2.0-flash` | Do not use it; use an exact current model ID you confirm from your provider console | Pack states it was shut down 1 Jun 2026; must be confirmed by you on the day, not assumed |
| Whitespace-only `session_id` | 422 | PDF says "missing or empty"; whitespace-only treated as empty is the safer reading |
| `system_prompt` on later requests in same session | Ignored; first successful request's prompt is fixed for the session | PDF: "overrides the default system prompt for this session" — stable per session keeps cache key and history consistent |
| `system_prompt` length | ≤4000 after trim, else 422 | PDF silent; bound prevents abuse, mirrors `message` |
| 400/401/403/timeout/connection/empty-reply errors | Treated as key failures → next key → 503 if all fail | PDF only names 429/quota/5xx; keeps error surface to 422/503/404/500 and never shows a broken screen |
| Malformed `X-Simulate-Failure` while enabled (bad syntax, unsupported status, empty entry, duplicate key, invalid key id) | 422 JSON with string `detail` | PDF silent; explicit rejection is clearer than silent ignore |
| `*` combined with an explicit key | Explicit key status wins for that key | Most specific rule wins |
| Empty / whitespace-only header value | Treated as absent (normal caching) | Carries no failure instruction |
| Simulation requests and cache | `cache={"no-cache": True, "no-store": True}`: skip lookup AND do not write | Proven on LiteLLM 1.108.4: `no-cache` alone skips lookup but still overwrites the stored entry |
| LiteLLM default `max_messages=4` | Set `max_messages=None` | Default silently disables caching for requests with >4 messages (turn 2 onward); PDF key is the full message list |
| Empty/blocked reply stored in cache by LiteLLM | On an empty cache hit, re-call same key with `no-cache` so the fresh reply overwrites it | Proven: LiteLLM caches empty replies; otherwise that message would 503 forever |
| Session with only failed requests | 404 `session not found` | Failed requests persist nothing (PDF), so the session does not exist |
| Internal non-provider error | 500 `{"detail":"internal server error"}` with CORS headers | PDF: never a stack trace; browser must be able to read it |
| `/health` when cache disabled | 503 | PDF body hard-codes `cache_enabled: true`; pack requires readiness to include cache |
