# Lyftr AI Chat: LLM chatbot with key failover and response caching

A full-stack chat app. A **React + Vite** UI talks to a **FastAPI** backend, which keeps each session's history in **SQLite** and sends every model call through **LiteLLM**. LiteLLM uses a pool of two API keys with automatic failover, and its built-in **disk cache** serves repeated prompts. Every reply shows its source (`LIVE_INFERENCE` / `LLM_CACHE`), model, latency and the token usage of that one request.

```
Browser (React)  ──POST /chat {session_id, message}──▶  FastAPI
                                                         │ rebuild prompt from SQLite history
                                                         ▼
                                    LiteLLM disk cache ──hit──▶ reply (LLM_CACHE, key_id=null)
                                                         │ miss
                                                         ▼
                              key_1 ──fail(429/5xx/...)──▶ key_2 ──fail──▶ 503
                                                         │ success
                                                         ▼
                               SQLite: session + user/assistant pair (one transaction)
```

Model: `gemini/gemini-3.5-flash-lite`. Two Gemini API keys from **two separate Google Cloud projects**, because Gemini quotas are per project, not per key.

## 1. Live URLs

| What | URL |
|---|---|
| Frontend | https://lyftr-ai-chat-six.vercel.app |
| Backend | https://lyftr-chat-backend-spyc.onrender.com (try `/health`) |
| GitHub repository | https://github.com/AkarshShukla8200/lyftr-ai-chat |
| Demo video (public, no login) | PENDING |

The backend runs on Render's free plan. It sleeps after 15 minutes without traffic, so the first request after that takes about a minute while it wakes up, and the UI shows a "server waking up" hint. See the persistence note in section 3.

## 2. Run locally: with Docker and without

### With Docker (recommended)

Requirements: Docker Desktop (or Docker Engine with Compose v2) and GNU make.

```bash
cp .env.example .env          # then put two real keys in LLM_API_KEYS and set LLM_MODEL
make up                       # frontend http://localhost:3000, backend http://localhost:8000
make down                     # stops both; the named volume (SQLite + cache) is kept
```

On Windows (PowerShell):

```powershell
Copy-Item .env.example .env   # then edit .env
make up
make down
```

Windows has no built-in `make`. Install GNU make with `winget install ezwinports.make` (then open a new terminal), or run `make` from Git Bash or WSL. The Makefile uses only make built-ins, so the same file works under `sh` (Linux/macOS) and `cmd`/PowerShell. If `.env` is missing, `make up` stops with `.env missing - copy .env.example to .env and add two keys`.

### Without Docker

Requirements: Python 3.13, Node 24.

Backend (from the repo root):

```bash
python -m venv backend/.venv
source backend/.venv/bin/activate                  # Windows: backend\.venv\Scripts\Activate.ps1
pip install -r backend/requirements.txt            # hash-locked; add -r backend/requirements-dev.txt for tests
cd backend
export LLM_API_KEYS="key-one,key-two" LLM_MODEL="gemini/gemini-3.5-flash-lite" \
       DATABASE_URL="sqlite:///./data/app.db" LLM_CACHE_DIR="./data/litellm-cache" \
       ALLOWED_ORIGINS="http://localhost:3000" ENABLE_FAILURE_SIMULATION="true"
uvicorn app.server:app --host 127.0.0.1 --port 8000 --workers 1
```

PowerShell equivalent for the environment and start command:

```powershell
cd backend
$env:LLM_API_KEYS="key-one,key-two"; $env:LLM_MODEL="gemini/gemini-3.5-flash-lite"
$env:DATABASE_URL="sqlite:///./data/app.db"; $env:LLM_CACHE_DIR="./data/litellm-cache"
$env:ALLOWED_ORIGINS="http://localhost:3000"; $env:ENABLE_FAILURE_SIMULATION="true"
uvicorn app.server:app --host 127.0.0.1 --port 8000 --workers 1
```

Instead of exporting each variable, you can keep them in the root `.env` and add `--env-file ../.env`. Variables you set in the shell take precedence, so still set `DATABASE_URL` and `LLM_CACHE_DIR` to the local paths above, because `.env.example` uses the Docker path `/data`.

Frontend:

```bash
cd frontend
npm ci
VITE_API_BASE_URL=http://localhost:8000 npm run dev -- --port 3000
```

```powershell
cd frontend
npm ci
$env:VITE_API_BASE_URL="http://localhost:8000"; npm run dev -- --port 3000
```

Tests:

```bash
cd backend && python -m pytest -q        # 145 tests, no network or keys needed
cd frontend && npx vitest run            # 11 tests
```

### Environment variables

Every variable is listed in `.env.example`.

| Variable | Meaning |
|---|---|
| `LLM_API_KEYS` | Comma-separated key pool (at least 2). Ids are `key_1`, `key_2`, … in this order. |
| `LLM_MODEL` | Exact LiteLLM model string for all keys, e.g. `gemini/gemini-3.5-flash-lite`. |
| `LLM_MODELS` | Optional: one model per key (same order) for mixed providers. |
| `LLM_TIMEOUT_SECONDS` | Per-attempt provider timeout, default `30`. |
| `LLM_TEMPERATURE`, `LLM_REASONING_EFFORT` | Optional constants sent on every call (part of the cache key). Unset by default. |
| `LLM_CACHE_DIR` | LiteLLM disk cache directory, `/data/litellm-cache` in Docker. |
| `DEFAULT_SYSTEM_PROMPT` | Used when a session does not set one. |
| `DATABASE_URL` | SQLite URL, `sqlite:////data/app.db` in Docker. |
| `ALLOWED_ORIGINS` | Comma-separated CORS origins (exact scheme + host, no trailing slash). |
| `ENABLE_FAILURE_SIMULATION` | `true` (exactly) enables the `X-Simulate-Failure` header. |
| `VITE_API_BASE_URL` | Frontend build-time backend URL as seen by the browser. |

## 3. Design decisions: key fallback, caching, SQLite session storage

**Key fallback: app-owned loop over `litellm.completion`.**
For each request the backend walks the keys in order. Each attempt is one `litellm.completion(model, api_key, messages, timeout, num_retries=0)` call. LiteLLM makes every provider call, owns the cache, and classifies provider errors into its exception classes. Those classes are what trigger failover.

I did not use `litellm.Router`. The Router can disable cooldowns and does report attempted fallbacks, but it has no documented way to make one chosen key fail with a chosen status for a single request, which `X-Simulate-Failure` needs. An app-owned loop gives an exact, testable `key_id` and `fallback_attempts` (the number of keys that failed before the one that answered).

- **What counts as a key failure:** any LiteLLM provider exception. That covers 429/quota (`RateLimitError`), 500/502/503 (`InternalServerError`, `BadGatewayError`, `ServiceUnavailableError`), timeouts, connection errors, 401/403, and any 400. It also covers an empty or safety-blocked reply.
  - The PDF only requires 429, quota and 5xx. Treating the rest as key failures too means one bad key (for example Gemini's `API_KEY_INVALID`, which LiteLLM 1.108.4 reports as `AuthenticationError`) never breaks the app. The error surface stays at 422 / 503 / 404, plus 500 for internal bugs.
- **If every key fails:** `503 {"detail": "all providers unavailable"}`, and nothing is written.
- **Retries:** all hidden retries are disabled (`num_retries=0`). Tests confirm the provider receives exactly one call per key.
- **`max_tokens` is not set:** Gemini Flash models spend reasoning tokens from the same budget, so a small cap would produce empty replies. Those count as key failures.
- **Token counts:** `output_tokens` is the provider's `completion_tokens`, which may include reasoning tokens. `input_tokens` is the provider's `prompt_tokens` for this request (system + history + new message), never a running total.
- **Internal errors:** non-provider exceptions return `500 {"detail": "internal server error"}`. A catch-all middleware is registered *inside* the CORS middleware, so even 500 responses carry `Access-Control-Allow-Origin` and the browser can read them.
- **No secrets in output:** raw provider error text is never returned, logged or stored. Logs contain only `key_id`, the exception class and the status code.

**Caching: LiteLLM built-in disk cache.**
The cache is configured as `litellm.cache = Cache(type="disk", disk_cache_dir=LLM_CACHE_DIR, max_messages=None)`, with one uvicorn worker.

- **Cache key:** LiteLLM builds it from the model plus the full ordered message list (system prompt + SQLite history + new message), plus constant parameters. In the installed version, `api_key`, `api_base`, `timeout` and `num_retries` are not part of the key. So a reply first served by key_2 is a hit for the same messages later, and a hit needs no healthy key.
- **`max_messages=None`:** LiteLLM 1.108.x defaults to 4, which silently disables caching for every request with more than 4 messages (turn 2 onward). The PDF's key is the *full* message list, so the limit is removed.
- **Hit detection:** a hit is detected only through LiteLLM's own flag (`response._hidden_params["cache_hit"]`), never from timing. On a hit:
  - `resolution_source = "LLM_CACHE"`, `key_id = null`, `fallback_attempts = 0`;
  - the reply text is identical;
  - the tokens are the usage stored with the cached response.
  - Measured: cache hits took 5–230 ms when the backend was warm (up to about 1 s right after a free-tier wake-up). Live calls took 1.2–1.9 s, and up to about 8 s during a cold start.
- **Simulation bypass:** a request with an active `X-Simulate-Failure` header is sent with `cache={"no-cache": True, "no-store": True}`. A test proves that, on the installed version, `no-cache` skips the lookup (the provider *is* called) but would still overwrite the stored entry. `no-store` prevents that overwrite. So a simulated request can never be answered from cache, and it cannot change the cache either.
- **Empty replies:** LiteLLM caches empty replies too (proven by a test). If a cache hit is empty, the gateway asks the provider again with the lookup skipped, and the fresh reply replaces the bad entry. Otherwise that prompt would return 503 forever.
- **Extra dependencies:** every cache hit in LiteLLM 1.103–1.110 imports part of LiteLLM's proxy package, which needs `orjson` and `soundfile`. Both are pinned. The full `litellm[proxy]` extra (about 50 packages) is avoided.

**SQLite session storage.**
- **Schema:** created on startup. It has the PDF's `messages` table, an index on `(session_id, id)`, and a `sessions` table holding each session's fixed system prompt.
- **Connections:** a new connection per operation (`timeout=10`) and WAL mode, so concurrent requests don't hit "database is locked". Every query is parameterized.
- **Transactional writes:** the session row and the user/assistant pair are written in **one transaction, only after a successful LLM call**. A failed request (422 / 503 / 500) stores nothing, and a session with only failed requests returns `404 session not found`.
- **Multi-turn context:** the backend rebuilds the prompt from SQLite on every request. The client only ever sends the newest message.
- **System prompt per session:** the trimmed `system_prompt` of the first *successful* request (or `DEFAULT_SYSTEM_PROMPT`) is stored and reused. Later values are ignored, so the cache key and the history stay consistent. The system prompt is never returned by the history endpoint.

**Validation choices.**
- `session_id` must be a 1–128 character string, and a whitespace-only value is rejected.
- `message` is trimmed and must then be 1–4000 characters, so a padded 4000-character message is valid.
- `system_prompt` is optional and at most 4000 characters after trimming. A blank value counts as absent.
- Missing, null or non-string values are rejected without type coercion, and malformed JSON returns 422.

**`X-Simulate-Failure`.**
- **When it applies:** it is honored only when `ENABLE_FAILURE_SIMULATION` is exactly `true`; otherwise the header is never parsed.
- **Effect:** a listed key raises the matching LiteLLM exception for that request only, without calling the provider. Unaffected keys make real calls, and there is no global state.
- **Parsing:** spaces are tolerated and well-formed unknown key ids (`key_9`) are ignored. An explicit key overrides `*`.
- **Malformed header:** a malformed header, unsupported status, empty entry or duplicated key returns **422** with a string `detail`. The PDF does not specify this case, so this is my choice: an explicit rejection is clearer than silently ignoring the header.

**Persistence limitation (deployment).** Locally, SQLite and the cache live on the Docker named volume at `/data` and survive `make down` / `make up` (verified). The deployed backend uses Render's **free** plan, which supports no persistent disk. Its filesystem is wiped on every restart, redeploy or idle spin-down, so deployed history and cache reset then. Within a running instance, everything behaves as specified.

**Supply chain.**
- **LiteLLM** is pinned to `litellm==1.108.4`. Releases 1.82.7, 1.82.8 and 1.107.0 were malicious and must never be used; I chose a stable release at least 14 days old.
- **Python dependencies:** `backend/requirements.txt` is a full lock of all 72 runtime packages with SHA-256 hashes, generated by `pip-compile --generate-hashes` from `requirements.in`. Docker installs it with `--require-hashes --only-binary=:all:`.
- **npm packages** are pinned exactly, with integrity hashes in `package-lock.json`.
- **Base images** are pinned by version tag and digest. The backend image runs as a non-root user.
- **No secrets in images:** `.env` is git-ignored and excluded by `.dockerignore` in both images.

## 4. Verification: how to see failover, cache hits and per-message token usage

**In the UI.** Every assistant reply shows Source (`LIVE_INFERENCE` / `LLM_CACHE`), Model, Latency (ms), Input tokens, Output tokens, Key and Fallbacks.
1. Ask a question you have never asked before. You'll get `LIVE_INFERENCE`.
2. Reload the page, which starts a new session, and ask exactly the same first question. You'll get `LLM_CACHE` with the identical reply and tokens, and lower latency.
3. Ask a follow-up in the same session that refers to the earlier message. The bot remembers it, and the input tokens grow because the history is included.

The disk cache persists, so a message that was ever sent before comes back as `LLM_CACHE` even on its first request in a new session. Use a unique message (the `$U` suffix below) to see `LIVE_INFERENCE` first.

**bash / curl:**

```bash
BACKEND_URL=http://localhost:8000          # or the deployed backend URL
U=$(date +%s)                              # unique suffix so the cache demo starts LIVE

curl -i "$BACKEND_URL/health"

# Cache: same unique first message in two new sessions -> LIVE_INFERENCE, then LLM_CACHE
curl -sS -X POST "$BACKEND_URL/chat" -H 'Content-Type: application/json' \
  -d "{\"session_id\":\"demo-A-$U\",\"message\":\"Explain caching in one sentence. ref $U\"}"
curl -sS -X POST "$BACKEND_URL/chat" -H 'Content-Type: application/json' \
  -d "{\"session_id\":\"demo-B-$U\",\"message\":\"Explain caching in one sentence. ref $U\"}"

# History (oldest first, assistant messages carry metadata, no system prompt)
curl -sS "$BACKEND_URL/sessions/demo-A-$U/messages"

# Failover: key_1 forced 429 / 500 -> 200, key_id "key_2", fallback_attempts 1
curl -sS -X POST "$BACKEND_URL/chat" -H 'Content-Type: application/json' \
  -H 'X-Simulate-Failure: key_1=429' \
  -d "{\"session_id\":\"demo-fo-$U\",\"message\":\"Say hello briefly.\"}"
curl -sS -X POST "$BACKEND_URL/chat" -H 'Content-Type: application/json' \
  -H 'X-Simulate-Failure: key_1=500' \
  -d "{\"session_id\":\"demo-fo500-$U\",\"message\":\"Say hello briefly.\"}"

# Every key fails -> 503, nothing stored -> history 404
curl -i -X POST "$BACKEND_URL/chat" -H 'Content-Type: application/json' \
  -H 'X-Simulate-Failure: *=429' \
  -d "{\"session_id\":\"demo-fail-$U\",\"message\":\"Hello\"}"
curl -i "$BACKEND_URL/sessions/demo-fail-$U/messages"

# Validation -> 422
curl -i -X POST "$BACKEND_URL/chat" -H 'Content-Type: application/json' -d '{"session_id":"v1","message":"   "}'
curl -i -X POST "$BACKEND_URL/chat" -H 'Content-Type: application/json' -d '{bad json'
```

**PowerShell** (Windows PowerShell 5.1: `curl` is an alias for `Invoke-WebRequest`, so use `Invoke-RestMethod` or `curl.exe`):

```powershell
$B = "http://localhost:8000"     # or the deployed backend URL
$U = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds()

Invoke-RestMethod "$B/health"

# Cache demo
$msg = "Explain caching in one sentence. ref $U"
Invoke-RestMethod -Method Post -Uri "$B/chat" -ContentType 'application/json' `
  -Body (@{ session_id = "demo-A-$U"; message = $msg } | ConvertTo-Json) | ConvertTo-Json -Depth 5
Invoke-RestMethod -Method Post -Uri "$B/chat" -ContentType 'application/json' `
  -Body (@{ session_id = "demo-B-$U"; message = $msg } | ConvertTo-Json) | ConvertTo-Json -Depth 5

# History
Invoke-RestMethod "$B/sessions/demo-A-$U/messages" | ConvertTo-Json -Depth 6

# Failover: key_1 forced 429 (use key_1=500 for the 5xx case)
Invoke-RestMethod -Method Post -Uri "$B/chat" -ContentType 'application/json' `
  -Headers @{ 'X-Simulate-Failure' = 'key_1=429' } `
  -Body (@{ session_id = "demo-fo-$U"; message = 'Say hello briefly.' } | ConvertTo-Json) | ConvertTo-Json -Depth 5

# Every key fails -> 503, then history -> 404 (curl.exe shows the status line)
'{"session_id":"demo-fail-' + $U + '","message":"Hello"}' | Out-File -Encoding ascii body.json
curl.exe -i -X POST "$B/chat" -H "Content-Type: application/json" -H "X-Simulate-Failure: *=429" --data-binary "@body.json"
curl.exe -i "$B/sessions/demo-fail-$U/messages"
Remove-Item body.json
```

On PowerShell 7 you can also use `Invoke-RestMethod ... -SkipHttpErrorCheck -StatusCodeVariable s` to see 503/404 status codes.

**Tokens per request.** `input_tokens` grows turn by turn within a session, because the history is resent, while `output_tokens` is only that reply's length. Two new sessions with equal-length first messages report about the same `input_tokens`.

## 5. Setup Used: your editor and AI tools

- **AI tools:** Claude Code (Anthropic) in the Claude desktop app, used for implementation, tests, verification and documentation, directed and reviewed by me.
- **Editor:** PENDING
- **Environment:** Windows 11, PowerShell 5.1, Docker Desktop 28.1, GNU make 4.4.1 (winget `ezwinports.make`), Python 3.13, Node 24.

## 6. Bonus features (if any): what you added beyond the requirements and why

- **Hash-locked Python dependencies and digest-pinned base images:** reproducible builds and supply-chain safety, given LiteLLM's history of malicious releases.
- **Simulation never touches the cache (`no-cache` + `no-store`) and empty cached replies are refreshed:** failover demos stay honest, and one bad provider response can't poison a prompt.
- **`max_messages=None`:** caching keeps working for long conversations, matching the "full message list" cache key.
- **The UI also shows `key_id` and `fallback_attempts`** next to the required metadata, so failover is visible without curl.
- **Optional system-prompt field** (`system-prompt-input`), locked after the first successful reply.
- **Cold-start hint** after 5 s and a 90 s request timeout, for the free-tier backend.
- **Readable errors for every failure mode** (422 details turned into a sentence, 503, 500, network, timeout), plus 500 responses that keep CORS headers.
- **Tests:** 145 backend tests run real LiteLLM against a local fake Gemini server, covering failover, the cache, simulation, validation and secret leakage. 11 frontend Vitest tests cover the selectors and errors.
