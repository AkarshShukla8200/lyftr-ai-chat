# Final Verification

Audit against `Lyftr_AI_Full_Stack_Assignment.pdf` (sections 1–8 and the 10-point rubric), done on 2026-11-24. Every PASS below comes from a real run whose output is quoted or summarized here. Nothing is marked PASS on expectation.

**Deployed:** frontend https://lyftr-ai-chat-six.vercel.app · backend https://lyftr-chat-backend-spyc.onrender.com · repo https://github.com/AkarshShukla8200/lyftr-ai-chat

## 1. Automated tests

| Suite | Command | Result |
|---|---|---|
| Backend (pytest) | `cd backend && python -m pytest -q` | **145 passed** (real LiteLLM against a local fake Gemini HTTP server; no keys, no network) |
| Frontend (Vitest) | `cd frontend && npx vitest run` | **11 passed** |
| Frontend build | `cd frontend && npm run build` | built OK |

## 2. Live audit of the deployed stack (run 1795520097)

| Area | Check | Result |
|---|---|---|
| Health | `GET /health` → 200 `{"status":"ok","keys_configured":2,"cache_enabled":true}` | PASS |
| Only 3 endpoints | `/docs`, `/redoc`, `/openapi.json`, `/` → 404 | PASS |
| 422 | blank message, 4001 chars, empty and whitespace `session_id`, null message, int `session_id`, missing message, malformed JSON | PASS (8/8) |
| 422 boundary | message of 4000 chars padded with whitespace → 200 | PASS |
| 404 | unknown session → `{"detail":"session not found"}` | PASS |
| Cache | new unique message → `LIVE_INFERENCE`, key_1, 1899 ms, 28/31 tokens | PASS |
| Cache | same message, new session → `LLM_CACHE`, identical reply (176 chars), same 28/31 tokens, `key_id` null, `fallback_attempts` 0, **5 ms** | PASS |
| Cache | different message → `LIVE_INFERENCE` | PASS |
| Multi-turn | turn 1 "codename Bluefin-…" → 200; turn 2 → "Bluefin-1795520261" | PASS (re-run, see note) |
| Isolation | other session asked for the codename → "unknown" | PASS |
| Tokens | two equal-length first messages → 28 vs 28 `input_tokens` | PASS |
| History | `{session_id, messages}`; roles user, assistant, user, assistant (oldest first); user `{role, content}`, assistant `{role, content, metadata}`; no system prompt | PASS (re-run) |
| Failover | `X-Simulate-Failure: key_1=429` → 200, key_2, `fallback_attempts` 1, real reply | PASS |
| Failover | `key_1=500` → 200, key_2, 1 | PASS |
| All fail | `*=429` → 503 `{"detail":"all providers unavailable"}`; that session's history → 404 | PASS |
| Simulation vs cache | warm message + `key_1=429` → `LIVE_INFERENCE` key_2 (lookup skipped); next plain request → `LLM_CACHE` with the original reply (not overwritten) | PASS |
| Simulation header | `key_1=404` → 422 | PASS |
| CORS | preflight from `https://lyftr-ai-chat-six.vercel.app` allows `X-Simulate-Failure`; a 503 response carries `access-control-allow-origin`; `http://localhost:3000` is not allowed | PASS |
| Frontend | public 200 without login; bundle contains the Render URL and no `localhost:8000` | PASS |

**Note on the multi-turn re-run.** In the first audit pass, the first turn of the multi-turn test hit a **real Gemini outage on both keys**. Render log, 11:35 UTC:

```
key failure key_id=key_1 error=Timeout status=408
key failure key_id=key_2 error=ServiceUnavailableError status=503
all providers unavailable after 2 key failures  ->  POST /chat 503
```

The app tried key_1, failed over to key_2, returned a clean 503 and stored nothing, as specified. So turn 2 correctly saw an empty history, and my audit script (which did not check turn 1's status) reported 2 failures. A re-run that asserts turn 1 = 200 passed both checks. **Final: 36/36 live checks PASS**, with no code changes needed.

**Live UI (built-in browser on the Vercel URL):**
- First message → `LIVE_INFERENCE`, 33/15 tokens. The follow-up was answered "Kyoto" (62 input tokens, history included).
- The input box is empty after each send.
- A reload gives a new session id. The same first message then returned `LLM_CACHE` with the identical reply and tokens (755 ms).
- No error bubbles appeared. Locally I also showed a real 422 and a real 503, plus stubbed 500 and network errors, all rendered as `error-message`.

## 3. Local Docker (Windows PowerShell, GNU make 4.4.1, Docker 28.1.1)

- `make up` exits 0. Health returns 200 and the container is `healthy`. The frontend serves on :3000 and the backend on :8000.
- Persistence: after `make down` (the volume is kept) and `make up`, a session's 4 messages were still there. The same first message in a new session returned `LLM_CACHE` in 230 ms with no provider call.
- Without `.env`, both PowerShell and Git Bash `sh` print `.env missing - copy .env.example to .env and add two keys` and exit 2. The Makefile uses only make built-ins.
- Images are multi-stage: backend 164 MB (python 3.13.18-slim, non-root `app` user, `/data` owned by `app`), frontend 27 MB (nginx 1.30.8-alpine).

## 4. Repository, secrets and pins

- **Git history:** 2 commits and 55 files scanned: **0** real keys, **0** `AIza…`/`sk-…`/`gsk_…` strings. No `.env`, PDF, `.db` or `data/` ever committed. Anonymous requests to GitHub show the repo as public; the `.env` raw URL returns 404.
- **Images:** no `.env` file inside either image, and no key in the image config, build history or app files.
- **Pins:**
  - `litellm==1.108.4`; the malicious 1.82.7, 1.82.8 and 1.107.0 are not used.
  - All 72 runtime Python packages are hash-locked.
  - npm packages are pinned exactly, with integrity hashes in `package-lock.json`.
  - Base images are pinned by version tag and digest.
- **Model:** `gemini/gemini-3.5-flash-lite`. Google's models page lists it as Stable with no shutdown date announced, and it is not an alias (the docs name `gemini-3.5-flash` → 3.6 as an alias, not flash-lite).
- **Raw provider error text** never appears in responses or logs. Logs contain only `key_id`, the exception class and the status code (checked by tests and in the Render logs above).
- **README:** six numbered headings, exactly the PDF's wording and in order.

## 5. Known limitations

1. **The deployed backend runs on Render Free, which has no persistent disk.** The SQLite file and LiteLLM cache are wiped on restart, redeploy or idle spin-down (after 15 minutes). Locally, the Docker named volume persists both (verified). This is stated in README section 3.
2. **Cold start:** the first request after idling takes about 50–60 s. The UI shows a "server waking up" hint after 5 s.
3. **Free Gemini quota** is 15 requests per minute and 500 per day per project (1,000 a day across both keys). A burst of more than about 15 model calls per minute can exhaust both keys → 503 by design. During the audit, Gemini itself also had a short outage (timeout and 503).
4. The **LiteLLM disk cache is process-global**, so the backend runs one uvicorn worker.

## 6. Demo video script (2–3 min, voice, deployed app only)

**Before recording:**
- Open https://lyftr-chat-backend-spyc.onrender.com/health once to wake the backend, and wait for `"status":"ok"`.
- Choose a **new** question you have never sent, for example add today's time to it, so it starts as `LIVE_INFERENCE`.
- Don't show `.env` or the Render Environment page.

Have PowerShell open with this prepared (paste the lines in when you reach each step):

```powershell
$B = "https://lyftr-chat-backend-spyc.onrender.com"; $U = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds()
# 0:15 health
Invoke-RestMethod "$B/health"
# 1:30 failover: key_1 forced 429, then 500
Invoke-RestMethod -Method Post -Uri "$B/chat" -ContentType 'application/json' -Headers @{ 'X-Simulate-Failure' = 'key_1=429' } -Body (@{ session_id = "demo-429-$U"; message = "Say hello briefly. $U" } | ConvertTo-Json) | ConvertTo-Json -Depth 5
Invoke-RestMethod -Method Post -Uri "$B/chat" -ContentType 'application/json' -Headers @{ 'X-Simulate-Failure' = 'key_1=500' } -Body (@{ session_id = "demo-500-$U"; message = "Say hello again. $U" } | ConvertTo-Json) | ConvertTo-Json -Depth 5
# 2:05 every key fails -> 503, then that session's history -> 404
'{"session_id":"demo-fail-' + $U + '","message":"Hello"}' | Out-File -Encoding ascii body.json
curl.exe -i -X POST "$B/chat" -H "Content-Type: application/json" -H "X-Simulate-Failure: *=429" --data-binary "@body.json"
curl.exe -i "$B/sessions/demo-fail-$U/messages"
# 2:25 history of the UI session (click the session id at the top right of the page once to select it, then Ctrl+C)
Invoke-RestMethod "$B/sessions/<paste-session-id>/messages" | ConvertTo-Json -Depth 6
```

| Time | Show | Say (suggested) |
|---|---|---|
| 0:00–0:15 | GitHub repo README (architecture diagram) | "React frontend, FastAPI backend, SQLite for session history, and LiteLLM as the gateway with two Gemini keys from two separate projects and LiteLLM's disk cache." |
| 0:15–0:30 | `Invoke-RestMethod "$B/health"` | "Health checks the database, the key pool (2 keys) and that the cache is enabled." |
| 0:30–1:05 | Live UI: ask your new question, then a follow-up that refers to it | "The first reply is LIVE_INFERENCE from key_1, with the model, latency and this request's tokens. The follow-up remembers context because the backend rebuilds the conversation from SQLite. Note the input tokens grow." |
| 1:05–1:30 | Reload the page (new session), ask the **same first question** | "New session, same first message, so the cache key matches: LLM_CACHE, identical reply and tokens, much lower latency, and no key used." |
| 1:30–2:05 | The two failover commands | "X-Simulate-Failure makes key_1 fail with 429, then 500, for this request only. We still get a real answer from key_2 with fallback_attempts 1." |
| 2:05–2:25 | `*=429` command, then the 404 | "When every key fails we get a clean 503, 'all providers unavailable', and nothing is stored: that session's history is 404." |
| 2:25–2:45 | History of the UI session | "History comes from SQLite, oldest first, without the system prompt, and each assistant message carries its metadata." |

**Upload:** YouTube **Unlisted**, or Google Drive with **"Anyone with the link – Viewer"**. Open the link in an incognito window to confirm it plays without login.

## 7. After recording: deployed cache cleared

Graders' first requests (including the PDF's example message) should return `LIVE_INFERENCE`, so the deployed cache was cleared after the video was recorded.

- **19:07 IST, Render "Manual Deploy → Restart service":** this did **not** wipe `/data`. A session created at about 17:06 was still readable afterwards (`GET /sessions/M-1795520261/messages` → 200). So on Render Free a restart keeps the container's files; my earlier assumption that it wipes them was wrong.
- **19:08 IST, Render "Manual Deploy → Deploy latest commit" (8ddc07c, backend code unchanged):** this builds a fresh container. At 19:09:33 the same session returned **404**, so `/data` (SQLite and the LiteLLM cache directory) is empty.
- **Afterwards I called only `/health`** → `{"status":"ok","keys_configured":2,"cache_enabled":true}`, plus the read-only history check above. No `/chat` request was sent, so the cache is empty for graders.

To repeat this later: Render → `lyftr-chat-backend` → **Manual Deploy → Deploy latest commit**, then call only `/health`. The cache also empties by itself when the free instance spins down after 15 minutes idle and is redeployed.

## 8. Submission text

```
Frontend:  https://lyftr-ai-chat-six.vercel.app
Backend:   https://lyftr-chat-backend-spyc.onrender.com
GitHub:    https://github.com/AkarshShukla8200/lyftr-ai-chat
Demo:      https://drive.google.com/file/d/1Apwqd6NEdap9HLiVeq4qmqHkE_Lo19KF/view?usp=sharing
```

**Public-link check (anonymous requests, no cookies, 2026-11-24 19:10 IST):** frontend 200 "Lyftr Chat", backend `/health` 200, GitHub 200, Drive video 200 "lyftr_ai_proj.mp4". None redirected to a login page.

**Status: READY TO SUBMIT.** All mandatory deliverables exist and are public, and the README has no PENDING items. Submit the four URLs above through the assignment's Submission Form before your 24-hour deadline.
