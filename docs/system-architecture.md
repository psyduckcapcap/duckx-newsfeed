# DuckX Newsfeed — System Architecture

## System Diagram

```
┌─────────────────────────────────────────────────────────────┐
│                      External Services                      │
├──────────────────┬──────────────────┬──────────────────┐
│   X (Twitter)    │  Google Gemini   │  Telegram Bot    │
│   API v2         │  API             │  API             │
│ (OAuth 1.0a)     │ (Text only)      │ (sendMessage)    │
└──────────────────┴──────────────────┴──────────────────┘
         ▲                    ▲                   ▲
         │                    │                   │
    ┌────┴────────────────────┴───────────────────┴──────┐
    │                                                     │
┌───┴────────────────────────────────────────────────────┘
│
│    ┌──────────────────────────────────────────────────┐
│    │         Flask Web Server (app.py)               │
│    │                                                  │
│    │  ┌──────────────┐      ┌──────────────┐        │
│    │  │ REST API     │      │  APScheduler │        │
│    │  │ routes       │      │  (UTC+7)     │        │
│    │  │ GET/POST/DEL │      │  CronTrigger │        │
│    │  └──────────────┘      └──────────────┘        │
│    │         ▲                      ▼                │
│    │         │           ┌──────────────────────┐   │
│    │         │           │ run_fetch_for_      │   │
│    │         │           │ watchlist(wl_id)    │   │
│    │         │           └──────────────────────┘   │
│    │         │                    │                 │
│    │         └────────────────────┼─────────────────┼───────┐
│    └────────────────────────────────────────────────┼───────┘
│                                                     │
│  Step 1: Fetch Tweets                             │
│  ┌─────────────────────────────────────────┐      │
│  │  XApiClient (x_api.py)                  │      │
│  │  ├─ OAuth 1.0a auth                     │      │
│  │  ├─ batch_lookup_users(usernames)       │      │
│  │  ├─ get_user_tweets(user_id, since_id)  │      │
│  │  └─ tweets_to_text(tweets)              │      │
│  └─────────────────────────────────────────┘      │
│                    │                                │
│                    ▼                                │
│  ┌────────────────────────────────────────┐       │
│  │ tweets_text (raw)                      │       │
│  │ Example: "@user: tweet content..."    │       │
│  └────────────────────────────────────────┘       │
│                    │                                │
│                    ▼                                │
│  Step 2: Summarize with AI                        │
│  ┌─────────────────────────────────────────┐      │
│  │  AI Summarizer (ai_summarizer.py)       │      │
│  │  ├─ _get_client(api_key) [cached]       │      │
│  │  ├─ _get_api_key(model_id)              │      │
│  │  └─ summarize_with_gemini(text, prompt)│      │
│  └─────────────────────────────────────────┘      │
│                    │                                │
│                    ▼                                │
│  ┌────────────────────────────────────────┐       │
│  │ ai_summary_text (Markdown)             │       │
│  │ Example: "*IMPORTANT*: 3 new..."       │       │
│  └────────────────────────────────────────┘       │
│                    │                                │
│                    ▼                                │
│  Step 3: Send to Telegram                         │
│  ┌─────────────────────────────────────────┐      │
│  │  Telegram Sender (telegram_sender.py)   │      │
│  │  ├─ convert_markdown_to_legacy(text)    │      │
│  │  ├─ split_message(text, max=4000)       │      │
│  │  ├─ send_message(chat_id, text)         │      │
│  │  └─ ThreadPoolExecutor (parallel send)  │      │
│  └─────────────────────────────────────────┘      │
│                    │                                │
│                    ▼                                │
│  ┌────────────────────────────────────────┐       │
│  │ Telegram (multiple chat IDs)           │       │
│  │ Status: success/error                  │       │
│  └────────────────────────────────────────┘       │
│                    │                                │
│                    ▼                                │
│  Step 4: Log Execution                            │
│  ┌─────────────────────────────────────────┐      │
│  │  Config Manager (config_manager.py)     │      │
│  │  ├─ log_execution(entry)                │      │
│  │  │  └─ execution_log.json               │      │
│  │  ├─ update_since_id(wl, user, id)       │      │
│  │  │  └─ app_config.json                  │      │
│  │  └─ RLock (thread-safe I/O)             │      │
│  └─────────────────────────────────────────┘      │
│
│
│  ┌──────────────────────────────────────────────┐
│  │         Web UI (templates/index.html)       │
│  │  Vanilla JS SPA (no framework)              │
│  │  ├─ Dashboard Tab (stats + active jobs)     │
│  │  ├─ Settings Tab (watchlist CRUD)           │
│  │  └─ Logs Tab (execution history)            │
│  │                                              │
│  │  Styling: static/style.css (dark theme)    │
│  └──────────────────────────────────────────────┘
│         ▲
│         │ (HTTP: GET/POST/DELETE)
│         │
└─────────┘ (Browser)

    ┌──────────────────────────────────────────┐
    │      Data Storage (JSON Files)           │
    ├──────────────────────────────────────────┤
    │  app_config.json                         │
    │  ├─ watchlists[]                         │
    │  │  ├─ id, name, accounts[]              │
    │  │  ├─ schedule_times[], ai_model        │
    │  │  ├─ since_ids{user: tweet_id}         │
    │  │  └─ telegram_targets[]                │
    │  └─ total_fetches (counter)              │
    ├──────────────────────────────────────────┤
    │  execution_log.json                      │
    │  └─ [{timestamp, watchlist, status...}] │
    │     (max 200 entries, auto-prune)        │
    ├──────────────────────────────────────────┤
    │  telegram_targets.json                   │
    │  └─ [cached target info for Telegram]    │
    └──────────────────────────────────────────┘
```

---

## Data Flow: Single Fetch Cycle

```
Timeline (UTC+7): 08:00 AM

1. Scheduler triggers run_fetch_for_watchlist("wl_crypto")
   │
   ├─ Check lock: is "wl_crypto" running?
   │  └─ No → acquire lock, proceed
   │  └─ Yes → skip (return early)
   │
2. Load watchlist config from app_config.json
   │
   ├─ wl_crypto = {
   │    accounts: ["elonmusk", "vitalikbuterin"],
   │    since_ids: {elonmusk: "1234567", vitalikbuterin: "7654321"},
   │    max_posts_per_user: 10,
   │    ai_model: "gemini_free_1",
   │    prompt: "Summarize crypto...",
   │    telegram_targets: [123456789, -1009876543210]
   │  }
   │
3. XApiClient.get_watchlist_tweets(["elonmusk", "vitalikbuterin"], ...)
   │
   ├─ API Call 1: batch_lookup_users(["elonmusk", "vitalikbuterin"])
   │  └─ Returns: {elonmusk: "12345", vitalikbuterin: "67890"}
   │
   ├─ API Call 2: get_user_tweets("12345", since_id="1234567", max=10)
   │  └─ Returns: [tweet1, tweet2, ..., tweet12]
   │
   ├─ API Call 3: get_user_tweets("67890", since_id="7654321", max=10)
   │  └─ Returns: [tweet_a, tweet_b, ..., tweet_c]
   │
   └─ Result:
      tweets = [tweet1, tweet2, ..., tweet_a, tweet_b, ..., tweet_c]
      new_since_ids = {elonmusk: "newest_id_1", vitalikbuterin: "newest_id_2"}
      raw_tweets_text = "@elonmusk: tweet1...\n@vitalikbuterin: tweet_a...\n..."
      fetch_count = 20

4. Log fetch step
   │
   ├─ entry.fetch_status = "success"
   ├─ entry.fetch_detail = "Fetched 20 tweets from 2 accounts"
   ├─ entry.fetch_count = 20
   ├─ entry.raw_tweets_text = "..." (full text)
   │
5. Summarize with Gemini (ai_summarizer.py)
   │
   ├─ API Key: GEMINI_API_KEY_1 (from .env)
   ├─ Client: _client_cache[GEMINI_API_KEY_1] (reuse)
   ├─ Request:
   │  {
   │    system: "You are a news summarizer...",
   │    prompt: "Summarize these crypto tweets:\n[raw_tweets_text]"
   │  }
   │
   └─ Response:
      ai_summary_text = "*KEY FINDINGS:*\n1. **Elon tweets about...**\n..."
      (Markdown format)

6. Log summarization step
   │
   ├─ entry.ai_status = "success"
   ├─ entry.ai_detail = "Gemini summarization completed"
   ├─ entry.ai_model_used = "gemini_free_1"
   ├─ entry.ai_summary_text = "..." (full summary)
   │
7. Send to Telegram (telegram_sender.py)
   │
   ├─ Step 1: convert_markdown_to_legacy(ai_summary_text)
   │  └─ **text** → *text*, __text__ → *text*, ## Title → *TITLE*
   │
   ├─ Step 2: split_message(converted_text, max=4000)
   │  └─ Return: [msg1_4000chars, msg2_3500chars, ...]
   │
   ├─ Step 3: Send in parallel to chat IDs [123456789, -1009876543210]
   │  │
   │  ├─ send_message(123456789, msg1) → Thread 1
   │  ├─ send_message(123456789, msg2) → Thread 2
   │  ├─ send_message(-1009876543210, msg1) → Thread 3
   │  ├─ send_message(-1009876543210, msg2) → Thread 4
   │  └─ Wait for all threads → success count + failures
   │
   └─ Result: All 2 chat IDs received messages
      status = "success"
      detail = "Sent to 2 chat IDs"

8. Log telegram step
   │
   ├─ entry.tg_status = "success"
   ├─ entry.tg_detail = "Sent to 2 chat IDs"
   │
9. Save execution log entry to execution_log.json
   │
   ├─ Lock: _io_lock.acquire()
   ├─ Load current log: json.load(LOG_FILE)
   ├─ Append entry
   ├─ Prune if >200 entries (remove oldest)
   ├─ Save: json.dump(log, LOG_FILE)
   ├─ Lock: _io_lock.release()
   │
10. Update since_ids in app_config.json
    │
    ├─ Lock: _io_lock.acquire()
    ├─ Load config: json.load(CONFIG_FILE)
    ├─ Update since_ids in watchlist:
    │  config.watchlists[idx].since_ids = {
    │    elonmusk: "newest_id_1",
    │    vitalikbuterin: "newest_id_2"
    │  }
    ├─ Save: json.dump(config, CONFIG_FILE)
    ├─ Lock: _io_lock.release()
    │
11. Release per-watchlist lock
    │
    └─ _wl_locks["wl_crypto"].release()

Cycle Complete: 08:05 (roughly 5 minutes for 2 users, 20 tweets)
Next run: 12:00 (per schedule_times)
```

---

## Concurrency & Thread Safety

### Scheduler Threading Model

```
Main Thread (Flask + APScheduler)
│
├─ Thread Pool (APScheduler background executor)
│  │
│  ├─ Job 1: run_fetch_for_watchlist("wl_crypto")
│  │  ├─ Acquire: _wl_locks["wl_crypto"] (threading.Lock)
│  │  ├─ Critical Section: Fetch → Summarize → Send
│  │  └─ Release lock
│  │
│  ├─ Job 2: run_fetch_for_watchlist("wl_ai") [concurrent with Job 1]
│  │  ├─ Acquire: _wl_locks["wl_ai"] (different lock, no contention)
│  │  ├─ Critical Section: Fetch → Summarize → Send
│  │  └─ Release lock
│  │
│  └─ Job 3: run_fetch_for_watchlist("wl_crypto") [blocked, retry skipped]
│     ├─ Try: _wl_locks["wl_crypto"].acquire(blocking=False)
│     │  └─ FAILS (already held by Job 1)
│     └─ Skip job and return
│
└─ File I/O (all guarded by _io_lock: RLock)
   ├─ Thread A: load_config() → holds _io_lock
   ├─ Thread B: save_config() → waits for _io_lock
   ├─ Thread B: log_execution() → waits for _io_lock
   └─ Lock ensures no file corruption
```

### Lock Hierarchy

```
1. _wl_locks_guard (protects _wl_locks dict creation)
   └─ 2. _wl_locks[wl_id] (per-watchlist execution lock)
      └─ 3. _io_lock (all file I/O: config, log, targets)
```

**Rule:** Always respect lock order to prevent deadlock.
- Never acquire a higher lock while holding a lower lock.
- Currently code follows this: file I/O happens after watchlist lock acquired.

---

## API Endpoint Routing

```
Flask App (app.py)
│
├─ GET / (root)
│  └─ render_template("index.html") [serves SPA]
│
├─ API Routes (JSON responses)
│  │
│  ├─ GET /api/stats
│  │  └─ Dashboard: {total_watchlists, total_fetches, success/error counts, active_jobs}
│  │
│  ├─ GET /api/watchlists
│  │  └─ List all watchlists
│  │
│  ├─ POST /api/watchlists
│  │  └─ Create watchlist (body: {name, accounts, schedule_times, ...})
│  │
│  ├─ PUT /api/watchlists/<id>
│  │  └─ Update watchlist
│  │
│  ├─ DELETE /api/watchlists/<id>
│  │  └─ Delete watchlist (stop all jobs)
│  │
│  ├─ POST /api/watchlists/<id>/accounts
│  │  └─ Add account (body: {username})
│  │
│  ├─ DELETE /api/watchlists/<id>/accounts/<username>
│  │  └─ Remove account
│  │
│  ├─ GET /api/execution-log
│  │  └─ List all execution log entries (paginated or full)
│  │
│  ├─ DELETE /api/execution-log
│  │  └─ Clear all logs
│  │
│  ├─ DELETE /api/execution-log/<index>
│  │  └─ Delete single log entry
│  │
│  ├─ POST /api/execution-log/bulk-delete
│  │  └─ Delete multiple entries (body: {indices: [0, 1, 2, ...]})
│  │
│  ├─ POST /api/run-now
│  │  └─ Trigger immediate run (body: {watchlist_id: "wl_xxx" or null for all})
│  │
│  ├─ POST /api/reset-sync
│  │  └─ Clear all since_ids (reset dedup tracking)
│  │
│  ├─ POST /api/test-telegram
│  │  └─ Test Telegram connection
│  │
│  ├─ GET /api/ai-models
│  │  └─ List AI models with key status (present: true/false)
│  │
│  └─ GET /api/telegram-targets
│     └─ List Telegram target info
│
└─ Error Handlers
   ├─ 404: Endpoint not found
   ├─ 500: Internal server error (logged with traceback)
```

---

## Configuration Cascading

```
Priority Order (highest → lowest):

1. CLI Arguments (--port, --host)
   │
2. Environment Variables (.env file)
   ├─ X_API_KEY, X_API_SECRET, X_ACCESS_TOKEN, X_ACCESS_TOKEN_SECRET
   ├─ TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
   ├─ GEMINI_API_KEY_1, GEMINI_API_KEY_2, GEMINI_API_KEY_3, GEMINI_API_KEY_PAID
   │
3. JSON Config Files
   ├─ app_config.json (watchlists, schedule_times, prompts, since_ids)
   ├─ execution_log.json (logs from previous runs)
   ├─ telegram_targets.json (cached target info)
   │
4. Hardcoded Defaults (in code)
   ├─ TZ_VN = pytz.timezone("Asia/Ho_Chi_Minh")
   ├─ MAX_LOG_ENTRIES = 200
   ├─ MAX_MESSAGE_LENGTH = 4000 (Telegram)
   ├─ DEFAULT_AI_PROMPT = "Summarize crypto tweets..."
   ├─ MISFIRE_GRACE_TIME = 900 (seconds)
   └─ 30-second delay between watchlist runs

Example: User loads app.py
   │
   1. Read .env → X_API_KEY, etc.
   2. Create XApiClient with .env credentials
   3. Load app_config.json → watchlists + since_ids
   4. Schedule jobs based on schedule_times
   5. Load execution_log.json → display on dashboard
   6. Start Flask + APScheduler
```

---

## Error Recovery & Resilience

### Fetch Errors (X API)
```
Attempt 1: Call X API → Error
   │
   ├─ 401 Unauthorized → Log error, skip watchlist, notify user
   ├─ 403 Forbidden → Log error, skip watchlist, notify user
   ├─ 429 Rate Limit → Sleep + Retry (max 2 retries, up to 30s wait)
   ├─ 5xx Server Error → Sleep + Retry (max 2 retries)
   │
Attempt 3: Still failing → Log "error", mark entry as "error", send Telegram fail message
```

### Summarization Errors (Gemini)
```
Attempt 1: Call Gemini → Error (5xx)
   │
   ├─ Retry after 10s delay
   │
Attempt 2: Still 5xx → Log error, return "[ERROR] Gemini API unavailable"
              └─ Message still sent to Telegram (degraded mode)
```

### Telegram Send Errors
```
For each chat ID:
   ├─ send_message(chat_id, text) → Error (404, 403, 5xx)
   │  └─ Log error for that chat ID
   │  └─ Continue to next chat ID (non-blocking)
   │
Result: If any chat ID succeeds → log as "partial success"
        If all fail → log as "error"
```

### File I/O Errors
```
load_config() → JSON corrupt or file missing
   │
   ├─ Exception caught → Return DEFAULT_CONFIG
   ├─ Log warning
   └─ User sees empty watchlist list
   
save_config() → Permission denied or disk full
   │
   ├─ Exception caught
   ├─ Log error (critical)
   └─ In-memory config remains; next save might succeed
```

### Scheduler Errors
```
Job run_fetch_for_watchlist() raises exception
   │
   ├─ APScheduler catches it (no crash)
   ├─ Log full traceback
   ├─ Mark execution log entry as "error"
   ├─ Misfire grace time: 900s (15 min)
   │  └─ If job missed, retry if within 15 min
   │
└─ Next scheduled time: job runs again per schedule_times
```

---

## Deployment Architecture

### Single-Machine Deployment (Current)

```
Server Machine
│
├─ Python 3.10+ runtime
├─ /app/duckx-newsfeed/
│  ├─ app.py (entrypoint)
│  ├─ config_manager.py
│  ├─ x_api.py
│  ├─ ai_summarizer.py
│  ├─ telegram_sender.py
│  ├─ main.py
│  ├─ templates/
│  ├─ static/
│  ├─ app_config.json (runtime config)
│  ├─ execution_log.json (runtime logs)
│  ├─ telegram_targets.json (runtime cache)
│  └─ .env (secrets, not in git)
│
├─ Process Management
│  └─ systemd service or supervisord or Docker container
│     ├─ Start: python app.py
│     ├─ Port: 5000 (default) or custom
│     ├─ Restart policy: on-failure
│     └─ Signal handling: SIGTERM → graceful shutdown
│
└─ Reverse Proxy (optional, for production)
   └─ nginx or Apache
      ├─ Proxy requests to http://localhost:5000
      ├─ SSL/TLS termination
      └─ Rate limiting
```

### Backup Strategy

```
Backup important files:
│
├─ app_config.json (watchlists, schedule_times, since_ids)
│  └─ Backup daily or on changes
│
├─ execution_log.json (history, useful for audit)
│  └─ Backup weekly (capped at 200 entries, not critical)
│
├─ .env (API keys, SECRETS)
│  └─ Backup to secure storage (encrypted, NOT in git)
│
├─ Code (app.py, templates/, etc.)
│  └─ Git repository (version control)
│
└─ Restore procedure:
   ├─ If config lost: Manually recreate watchlists from backup
   ├─ If logs lost: History is gone (not recoverable)
   ├─ If .env lost: Regenerate API keys (time-consuming)
   └─ If code lost: git clone (quick)
```

---

## Scaling Considerations

### Current Limits
- **Max watchlists:** ~100 (config file stays <1 MB)
- **Max execution log entries:** 200 (auto-pruned, configured)
- **Max tweets per run:** 100 per user (X API limit)
- **Concurrent watchlists:** Limited by Gemini free tier (30s delay between runs)

### Scaling Beyond Limits

| Limit | Solution | Effort |
|-------|----------|--------|
| Max watchlists (100+) | Migrate to PostgreSQL | High |
| Max log entries (200) | Implement archival (compress old logs) | Medium |
| Gemini rate limits | Use paid tier + queue management | Low |
| Scheduler performance | Distribute to multiple machines + Redis | High |
| Single point of failure | Add redundancy + load balancer | High |

### Current Performance Targets
- **Fetch latency:** 2-3s per 1-2 accounts
- **Summarize latency:** 3-5s per 1000 chars
- **Telegram send latency:** 1-2s per message (parallelized)
- **Total E2E latency:** ~10-15s for typical watchlist (2 users, 10 tweets ea.)
- **Dashboard load:** <1s (static HTML + JS)

---

## Security Architecture

### API Key Management

```
.env file (local, never committed)
│
├─ X OAuth 1.0a keys (4 secrets)
│  └─ Used by: XApiClient
│  └─ Scope: Read-only tweets
│  └─ Risk: If leaked, attacker can read tweets
│
├─ Telegram Bot Token (1 secret)
│  └─ Used by: telegram_sender.py
│  └─ Scope: Send messages to configured chat IDs
│  └─ Risk: If leaked, attacker can spam chats
│
└─ Gemini API Keys (4 secrets)
   └─ Used by: ai_summarizer.py
   └─ Scope: Text summarization (no write)
   └─ Risk: If leaked, attacker wastes API quota
```

### No Authentication (Single-User App)

```
Current design: No auth layer
│
├─ Assumption: Running on trusted network or private server
├─ Web UI accessible to anyone with network access
├─ No user login required
│
├─ Future: If exposing publicly, add:
│  ├─ Basic Auth (username/password)
│  ├─ Token-based auth (JWT)
│  └─ Rate limiting (per IP)
```

### Logging & Audit Trail

```
execution_log.json provides audit trail:
│
├─ Timestamp of each run
├─ Watchlist name + ID
├─ Fetch count (how many tweets)
├─ AI model used
├─ Success/error status + detail
├─ Raw tweets text + AI summary
│
├─ Useful for:
│  ├─ Debugging failures
│  ├─ Auditing API usage
│  └─ Cost estimation (Gemini, X API)
│
└─ Privacy concern: logs contain user content (tweets, summaries)
   └─ Solution: Encrypt logs at rest or restrict access
```

---

## Monitoring & Observability

### Current Logging

```
Logging output: stderr + Flask access logs
│
├─ Log level: INFO (by default)
│  └─ DEBUG: Detailed info for developers
│  └─ INFO: Status updates (fetch started, summary completed)
│  └─ WARNING: Recoverable errors (API 429, retry)
│  └─ ERROR: Non-fatal failures (chat ID invalid, summary failed)
│
├─ Format: [YYYY-MM-DD HH:MM:SS] [LEVEL] message
│
├─ Logged events:
│  ├─ Scheduler job start/end (with status)
│  ├─ X API calls (rate limit retries)
│  ├─ Gemini API errors
│  ├─ Telegram send results
│  ├─ File I/O errors
│  └─ Watchlist enable/disable
│
└─ Persistence: Logs to stderr (forward to syslog, journalctl, ELK, etc.)
```

### Metrics (Not Implemented)

Future enhancements:
- Prometheus metrics export
- Dashboard integration (Grafana)
- Alert on error thresholds

### Health Checks

```
Current: Manual testing
├─ CLI: python main.py (test X API)
├─ Web UI: /api/stats (check if Flask is running)
└─ Telegram: POST /api/test-telegram (validate bot connection)

Future: Automated health checks
├─ Liveness probe: Flask responds to GET /health
├─ Readiness probe: Can connect to X API + Gemini + Telegram
└─ Integration tests: End-to-end fetch → summarize → send
```

---

## Technical Debt & Future Improvements

### High Priority
- [ ] Add TypeScript + build toolchain for frontend (currently vanilla JS)
- [ ] Implement user authentication (currently single-user)
- [ ] Add unit/integration tests (currently manual testing)
- [ ] Database migration guide (JSON → PostgreSQL)

### Medium Priority
- [ ] Webhook support (instead of polling)
- [ ] Discord/Slack integration (currently Telegram only)
- [ ] Log archival & compression
- [ ] API rate limiting per client

### Low Priority
- [ ] Dark mode toggle (currently always dark)
- [ ] Multi-language support (currently Vietnamese/English mixed)
- [ ] Advanced scheduling (cron expressions instead of time slots)
- [ ] Tweet caching & dedup optimization

