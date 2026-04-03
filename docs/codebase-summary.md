# DuckX Newsfeed — Codebase Summary

## Module Overview

Complete inventory of project files with line counts, responsibilities, and key functions.

| File | LOC | Purpose | Key Functions |
|------|-----|---------|----------------|
| `app.py` | ~160 | Flask entry point, APScheduler init | `app.run()`, scheduler setup |
| `pipeline.py` | ~580 | Core ETL pipeline: fetch→summarize→send | `run_fetch_for_watchlist()`, `retry_execution_steps()`, `run_all_watchlists()` |
| `routes.py` | ~270 | Flask REST API (21 endpoints) | `GET/POST/DELETE /api/...` handlers |
| `config_manager.py` | ~700 | JSON config I/O, watchlist CRUD, execution log | `load_config()`, `save_watchlist()`, `log_execution()`, `get_dashboard_stats()` |
| `x_api.py` | ~750 | X API v2 OAuth 1.0a client | `XApiClient.get_watchlist_tweets()`, `batch_lookup_users()` |
| `telegram_sender.py` | ~390 | Telegram Bot API, message formatting | `send_message_to_targets()`, `convert_markdown_to_legacy()` |
| `ai_summarizer.py` | ~100 | Gemini AI integration, model routing | `summarize_with_gemini()`, `summarize_tweets()` |
| `scheduler_manager.py` | ~50 | APScheduler singleton | `get_scheduler()`, scheduler config |
| `main.py` | ~244 | CLI tool for X API testing | `XApiClient.get_home_timeline()`, `get_me()` |
| `templates/index.html` | ~724 | Vanilla JS SPA (Dashboard, Settings, Logs) | Fetch/render API data, form submission handlers |
| `static/style.css` | ~798 | Dark theme styling | Responsive layout, tab switching, form inputs |

**Total:** ~4566 LOC (excluding test files and config examples)

---

## Module Descriptions

### 1. `app.py` (~160 LOC) — Flask Entry Point & Scheduler Init

**Responsibility:** Flask application initialization, APScheduler setup, debug mode toggle.

**Key Functions:**
- `create_app()` — Initialize Flask app with config
- `main()` — Parse CLI arguments, start Flask + scheduler

**Signal Handling:**
- `signal.signal(signal.SIGTERM/SIGINT, ...)` → graceful shutdown on interrupt

---

### 2. `pipeline.py` (~580 LOC) — Core ETL Pipeline

**Responsibility:** Main execution pipeline: fetch tweets → summarize → send to Telegram. Retry logic with intelligent resume.

**Key Classes/Functions:**
- `get_x_client()` — Lazy-init singleton X API client (thread-safe)
- `_get_wl_lock(wl_id)` — Get or create per-watchlist `threading.Lock()`
- `run_fetch_for_watchlist(wl_id)` — Main 3-step pipeline executor
  - Step 1: Fetch tweets (X API)
  - Step 2: Summarize (Gemini)
  - Step 3: Send to Telegram
  - Tracks status + detail in execution log
- `_run_fetch_with_retry()` — X API fetch with 2 retries (10s delay)
- `_run_ai_with_retry()` — Gemini summarization with 2 retries
- `_send_telegram_with_retry()` — Telegram send with 2 retries
- `retry_execution_steps(exec_id)` — Intelligent retry from last failed step (resume capability)
- `run_all_watchlists()` — Sequential execution of all enabled watchlists with 30s delay

**Thread Safety:**
- `_wl_locks` dict with per-watchlist `threading.Lock()`
- Prevents same watchlist running concurrently; different watchlists run in parallel

---

### 3. `routes.py` (~270 LOC) — Flask REST API (21 Endpoints)

**Responsibility:** Blueprint-based HTTP routes for Web UI. 21 total API endpoints.

**Endpoint Categories:**

**Dashboard & Admin:**
- `GET /api/stats` — Dashboard stats + active jobs
- `GET /api/execution-log` → Full execution history
- `DELETE /api/execution-log` → Clear all logs
- `DELETE /api/execution-log/<index>` → Delete single entry
- `POST /api/execution-log/bulk-delete` → Bulk delete by indices
- `POST /api/execution-log/<exec_id>/retry` → Retry from failed step
- `POST /api/reset-sync` → Reset all since_ids

**Watchlist CRUD:**
- `GET /api/watchlists` → List all
- `POST /api/watchlists` → Create
- `PUT /api/watchlists/<id>` → Update
- `DELETE /api/watchlists/<id>` → Delete

**Account Management:**
- `POST /api/watchlists/<id>/accounts` → Add account
- `DELETE /api/watchlists/<id>/accounts/<username>` → Remove account
- `POST /api/watchlists/<id>/refresh-user-cache` → Refresh user ID cache
- `POST /api/watchlists/<id>/duplicate` → Duplicate watchlist

**Triggers & Tests:**
- `POST /api/run-now` → Manual trigger (all or specific watchlist)
- `POST /api/test-telegram` → Test Telegram connection

**Configuration:**
- `GET /api/ai-models` → List AI models with key status
- `GET /api/telegram-targets` → List Telegram targets

---

### 4. `config_manager.py` (~700 LOC) — Configuration & Logging

**Responsibility:** JSON file I/O for config, execution logs, Telegram targets. Thread-safe with `RLock`.

**Constants:**
- `CONFIG_FILE` = `app_config.json`
- `LOG_FILE` = `execution_log.json`
- `TELEGRAM_TARGETS_FILE` = `telegram_targets.json`
- `MAX_LOG_ENTRIES` = 200 (auto-prune oldest)
- `DEFAULT_AI_PROMPT` — Vietnamese AI instruction template

**Key Functions:**
- `load_config()` → dict (app_config.json)
- `save_config(config)` → write to app_config.json
- `get_watchlist_by_id(wl_id)` → find watchlist in config
- `save_watchlist(wl)` → insert/update watchlist
- `delete_watchlist(wl_id)` → remove from config
- `add_account(wl_id, username)` → append account to watchlist
- `update_since_id(wl_id, username, tweet_id)` → update dedup tracking
- `log_execution(entry_dict)` → append to execution_log.json (auto-prune on 200+ entries)
- `get_execution_log()` → list of log entries
- `delete_execution_log_entry(index)` → remove log by index

**Thread Safety:**
- All file I/O guarded by `_io_lock = threading.RLock()`

**Telegram Targets Cache:**
- `load_telegram_targets()` / `save_telegram_targets()` — separate file for quick refresh

**AI Models Registry:**
```python
AI_MODELS = {
    "gemini_free_1": {"label": "Gemini Free 1", "env_key": "GEMINI_API_KEY_1"},
    "gemini_free_2": {"label": "Gemini Free 2", "env_key": "GEMINI_API_KEY_2"},
    "gemini_free_3": {"label": "Gemini Free 3", "env_key": "GEMINI_API_KEY_3"},
    "gemini_paid_1": {"label": "Gemini Paid 1", "env_key": "GEMINI_API_KEY_PAID"},
}
```

---

### 5. `x_api.py` (~750 LOC) — X (Twitter) API v2 Client

**Responsibility:** OAuth 1.0a authentication, tweet fetching, user batch lookup, deduplication.

**Key Class: `XApiClient`**
- `__init__(api_key, api_secret, access_token, access_token_secret)` — OAuth 1.0a setup
- `_make_request(method, endpoint, params, max_retries)` — HTTP request with 429 retry logic
- `get_me()` → authenticated user info
- `batch_lookup_users(usernames)` → single API call to resolve usernames → user IDs
- `get_user_tweets(user_id, max_results, since_id)` → fetch user timeline (max 100 tweets)
- `get_watchlist_tweets(usernames, max_results_per_user, since_ids)` → fetch all users' tweets
  - Returns: `(tweets_list, users_map, updated_since_ids)`

**Helper Functions:**
- `tweets_to_text(tweets, users_map)` → format tweets as readable text (username + text)
- `_is_expired_token()` → check token age (if >24h old, ask re-auth)

**API Endpoints Used:**
- `GET /2/users/me` — Get authenticated user
- `GET /2/users/by` → Batch username lookup (max 100)
- `GET /2/users/{id}/tweets` → User timeline (with pagination)

**Error Handling:**
- 401 (Unauthorized) → API key invalid
- 403 (Forbidden) → Insufficient permissions or credit
- 429 (Rate Limit) → Retry with exponential backoff (max 30s wait)
- 5xx (Server Error) → Retry with same backoff

**Rate Limit Protection:**
- Respects `Retry-After` header from API

---

### 6. `telegram_sender.py` (~390 LOC) — Telegram Bot API

**Responsibility:** Message delivery to Telegram, Markdown formatting, message splitting.

**Key Functions:**
- `get_telegram_config()` → read `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` from .env
- `convert_markdown_to_legacy(text)` → Convert AI-generated Markdown to Telegram Markdown Legacy
  - Step 1: Remove unsupported (strikethrough, blockquotes, rules)
  - Step 2: Italic: `*text*` → `_text_`
  - Step 3: Headings: `## Title` → `*TITLE*`
  - Step 4: Bold: `**text**` → `*text*`
  - Step 5: Lists: `*` / `+` → `-`
- `convert_markdown_to_plaintext(text)` → Plain text fallback (links, formatting removed)
- `split_message(text, max_length=4000)` → Smart split: try `\n\n` > `\n` > space
- `send_message(chat_id, text, parse_mode)` → Single API call to send message
- `send_message_to_targets(text, targets)` → Parallel send to multiple chat IDs
- `test_connection(bot_token, chat_id)` → Validate bot token + chat ID

**Message Splitting Strategy:**
- Max length: 4000 chars (Telegram limit is 4096, safe margin)
- Priority order: `\n\n` (paragraph) > `\n` (line) > space
- Fallback: Split at 4000 if no delimiter found

**Telegram API:**
- `POST /bot<TOKEN>/sendMessage` → Send message with Markdown Legacy parsing

**Threading:**
- `ThreadPoolExecutor(max_workers=3)` for parallel sends to multiple chat IDs

**Error Handling:**
- API errors logged; returns success count + failed list
- Silently falls back to plaintext if Markdown parse fails

---

### 7. `ai_summarizer.py` (~100 LOC) — Gemini AI Integration

**Responsibility:** Gemini 3 Flash Preview API calls, model routing, client caching.

**Key Functions:**
- `_get_client(api_key)` → Get or create cached `genai.Client` (per API key)
- `_get_api_key(model_id)` → Resolve model ID (e.g., "gemini_free_1") to env var
- `summarize_with_gemini(tweets_text, prompt, api_key)` → Call Gemini API
  - Uses `google-genai` SDK (official Google GenAI SDK)
  - Model: `gemini-3-flash-preview`
  - Thinking disabled (thinking_budget=0)
  - Temperature: default 1.0
- `summarize_tweets(tweets_text, prompt, ai_model)` → Route to correct API key, retry once on 5xx

**Client Caching:**
- `_client_cache` dict keyed by API key
- Avoids re-instantiation overhead on every request

**Error Handling:**
- Return `[ERROR] ...` message if API key missing
- Retry once after 10s wait on 5xx errors
- Log all errors

**Gemini Model Configuration:**
- Free tier: up to ~50 requests/min (use 3 keys to distribute load)
- Paid tier: higher quotas
- Model: `gemini-3-flash-preview`
- Model only supports text input/output (no images, files)

---

### 8. `scheduler_manager.py` (~50 LOC) — APScheduler Singleton

**Responsibility:** Singleton pattern for APScheduler instance. Centralized scheduler management.

**Key Functions:**
- `get_scheduler()` → Return or create APScheduler instance
- Scheduler config: background executor, misfire grace time (900s), UTC+7 timezone

---

### 9. `main.py` (~244 LOC) — CLI Tool

**Responsibility:** Command-line testing of X API without scheduler/web UI.

**Key Functions:**
- `main()` → Entry point; parse args and execute
- `XApiClient.get_home_timeline()` — Fetch authenticated user's timeline
- `XApiClient.get_me()` — Print user info
- Display tweets in readable format

**CLI Arguments:**
- `--count <N>` — Number of tweets to fetch (default 20)
- `--user <username>` — Fetch specific user's tweets (instead of home timeline)

**Usage Examples:**
```bash
python main.py                    # Home timeline, 20 tweets
python main.py --count 50         # Home timeline, 50 tweets
python main.py --user elonmusk    # @elonmusk's tweets
```

**Purpose:** Debug X API without starting scheduler; verify OAuth credentials work.

---

### 10. `templates/index.html` (~724 LOC) — Web UI (Vanilla JS SPA)

**Responsibility:** Single-page application with Dashboard, Settings, Execution Log tabs.

**Structure:**
- Single HTML file with inline `<style>` and `<script>`
- Vanilla JS (no framework, no build tool)
- CSS-based tab switching (`:checked` pseudo-class)

**Main Sections:**

**Dashboard Tab:**
- Stats: Total watchlists, total executions, success/error counts
- Active jobs: List of currently running scheduler jobs (job_id, next_run_time)
- Last execution summary

**Settings Tab:**
- **Watchlists Panel:**
  - List all watchlists with edit/delete buttons
  - New Watchlist form: name input
  - Per-watchlist settings:
    - Accounts: list with add/remove
    - Schedule times: comma-separated times (HH:MM format, UTC+7)
    - Max posts per user: number input (1-100)
    - AI Model: dropdown (gemini_free_1/2/3, gemini_paid_1)
    - Prompt: textarea for custom AI instruction
    - Telegram targets: list of chat IDs
    - Enabled toggle

- **Telegram Config Panel:**
  - Bot Token display (masked)
  - Chat ID input (comma-separated)
  - Test button → `POST /api/test-telegram`

- **AI Models Panel:**
  - List of 4 models with status: ✓ configured / ✗ missing key
  - Link to API key generation docs

**Execution Log Tab:**
- Table with columns: timestamp, watchlist, fetch status, ai status, telegram status, actions
- Per-entry actions: view details (expanded modal), delete, bulk delete

**Key JS Functions:**
- `fetchData(endpoint)` → GET request with error handling
- `submitForm(formId, endpoint)` → POST/PUT/DELETE with form data
- `showModal(content)` → Display expanded log entry
- `formatTime(isoString)` → Convert ISO timestamp to local time
- Event listeners on form submit, tab switching, button clicks

---

### 11. `static/style.css` (~798 LOC) — Dark Theme Styling

**Responsibility:** Responsive layout, form styling, dark theme, animations.

**Design:**
- Dark theme: `#1e1e1e` background, `#e0e0e0` text
- Color accents: `#4a9eff` (blue), `#4caf50` (green), `#f44336` (red)
- Sans-serif fonts: `Segoe UI`, `Roboto`, fallback `sans-serif`

**Key Classes:**
- `.container` — Max width, centered, padding
- `.card` — Padded box with border
- `.form-group` → Form input styling
- `.btn` → Button base (primary/danger/success variants)
- `.table` → Table styling with striped rows
- `.modal` → Overlay modal for expanded content
- `.tab-content` → Hidden by default; shown when `input:checked`

**Responsive:**
- Mobile-first breakpoints: `@media (max-width: 768px)`
- Tabs stack vertically on small screens
- Form inputs full-width

**Animations:**
- Fade-in on load (0.3s)
- Button hover effects
- Smooth color transitions

---

## Key Design Patterns

### 1. Per-Watchlist Locking
```python
_wl_locks = {}  # {wl_id: threading.Lock()}
lock = _get_wl_lock(wl_id)
if not lock.acquire(blocking=False):  # Non-blocking
    return  # Skip if already running
```
**Purpose:** Prevent concurrent execution of the same watchlist; allow parallel execution of different watchlists.

### 2. X API Client Caching
```python
_x_client: XApiClient | None = None

def get_x_client() -> XApiClient:
    global _x_client
    with _x_client_lock:
        if _x_client is None:
            _x_client = XApiClient(...)
        return _x_client
```
**Purpose:** Reuse the OAuth1 session across pipeline runs — avoids re-initializing per call.

### 3. Client Caching (Gemini)
```python
_client_cache = {}  # {api_key: genai.Client()}
def _get_client(api_key):
    if api_key not in _client_cache:
        _client_cache[api_key] = genai.Client(api_key=api_key)
    return _client_cache[api_key]
```
**Purpose:** Reuse client instances; avoid re-initialization overhead.

### 4. Thread-Safe File I/O
```python
_io_lock = threading.RLock()
def load_config():
    with _io_lock:
        return json.load(open(CONFIG_FILE))
```
**Purpose:** Prevent file corruption; ensure atomic reads/writes. `get_dashboard_stats()` also reads config+log under a single lock for consistency.

### 4. JSON-Based Config
- Single source of truth: `app_config.json`
- Separate logs: `execution_log.json`
- No database; easy to backup/restore

### 5. Markdown → Legacy Conversion Pipeline
- Step-by-step regex transforms
- Fallback to plaintext if Telegram parse fails
- Prioritizes readability over features

### 6. Message Splitting Strategy
- Smart delimiter priority: paragraph > line > word > character
- Respects Telegram's 4096-char limit (use 4000 margin)

---

## Error Handling Strategy

| Layer | Error Type | Handling |
|-------|-----------|----------|
| X API | 401 Unauthorized | Log + notify user (bad API keys) |
| X API | 403 Forbidden | Log + notify (insufficient credits) |
| X API | 429 Rate Limit | Auto-retry with backoff (max 30s) |
| X API | 5xx Server Error | Auto-retry with backoff |
| Gemini | API key missing | Return `[ERROR]` message to log |
| Gemini | 5xx error | Retry once after 10s; if still fail → log error |
| Telegram | API error | Log failed message; continue (non-blocking) |
| Config | JSON corrupt | Load defaults; warn user |
| Scheduler | Job exception | Log full traceback; mark as error in execution log |

**Result:** Graceful degradation; no silent failures.

---

## Dependencies & Versions

| Package | Purpose | Version |
|---------|---------|---------|
| `flask` | Web server | 3.x |
| `apscheduler` | Background scheduler | 3.x |
| `google-genai` | Google GenAI SDK (Gemini) | latest |
| `requests` | HTTP client (X API, Telegram) | 2.x |
| `requests-oauthlib` | OAuth 1.0a | 1.x |
| `python-dotenv` | .env file parsing | 1.x |
| `pytz` | Timezone support | 2024.x |

**Python:** 3.10+ required (type hints, modern async patterns)

---

## File I/O & Concurrency

### Atomic Operations
- Config CRUD: Load → Modify → Save (atomic via `RLock`)
- Log append: Read → Append → Prune oldest → Write (atomic)
- Telegram targets: Cached in memory; refreshed at startup + on Telegram config change

### Watchlist Execution Isolation
- Per-watchlist locks ensure only one run at a time per watchlist
- Different watchlists' executions don't block each other
- Execution logs appended after each run (thread-safe via RLock)

### Scheduler Concurrency
- APScheduler runs jobs in thread pool
- Each job acquires its watchlist's lock before running
- Missed jobs re-run if within 900s grace window

---

## Performance Considerations

| Operation | Latency | Bottleneck |
|-----------|---------|-----------|
| Fetch tweets (1 user, 10 tweets) | 2-3s | X API network |
| Summarize (1000 chars) | 3-5s | Gemini API response time |
| Send to Telegram (1 message, 3 chat IDs) | 1-2s | Telegram API + parallelization |
| Full pipeline (2 users, 10 tweets ea.) | ~10-15s | Sequential fetch → AI → send |
| Web UI load | <1s | Static HTML + JS execution |

**Optimization Opportunities:**
- Batch X API calls (already done: batch_lookup_users)
- Parallel Telegram sends (already done: ThreadPoolExecutor)
- Gemini caching (already done: client reuse)
- Config lazy-load (not needed: files are small)

---

## Known Issues & TODOs

**None documented in code.** Project appears stable with no pending bugs or refactors flagged.

Potential future improvements:
- Add TypeScript + build toolchain for frontend (currently vanilla JS)
- Migrate to PostgreSQL for large-scale deployments
- Implement webhook-based updates (instead of polling)
- Add user authentication (currently no access control; single-user app)
- Support for more messaging platforms (Discord, Slack, etc.)

