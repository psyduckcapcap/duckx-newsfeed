# DuckX Newsfeed — Project Overview & PDR

## Overview

**DuckX Newsfeed** is a Python/Flask application that automates the process of fetching tweets from X (Twitter) watchlists, summarizing them using Google Gemini AI, and delivering daily digests to Telegram. Designed for users who want to monitor multiple Twitter accounts and receive AI-powered summaries on a fixed schedule.

Built with a clean REST API backend (Flask) and lightweight vanilla JavaScript frontend. Stores configuration and execution logs as JSON files. Fully Vietnamese-localized UI and codebase comments.

**Status:** Production-ready with scheduler, multi-watchlist support, multiple AI models (free + paid tiers), and detailed execution logging.

---

## Functional Requirements

| Requirement | Status | Description |
|-------------|--------|-------------|
| Create/edit watchlists | DONE | Web UI allows creating groups of Twitter accounts (e.g., "Crypto News", "AI Tech") |
| Schedule automation | DONE | APScheduler runs jobs at fixed UTC+7 times; multiple times per day per watchlist |
| Fetch tweets | DONE | X API v2 client fetches tweets from watched accounts; deduplicates via since_id per user |
| Summarize with AI | DONE | Gemini 2.0 Flash integration; supports 3 free keys + 1 paid key |
| Send to Telegram | DONE | Sends summaries to multiple Telegram chat IDs; Markdown Legacy formatting with plaintext fallback |
| Web dashboard | DONE | Single-page app (vanilla JS): Dashboard (stats), Settings (CRUD), Execution Log (history) |
| Deduplication | DONE | since_id tracking per user per watchlist; cleared on reset |
| Execution log | DONE | Detailed per-run logs stored in JSON; tracks fetch count, AI model used, success/error states |
| Rate-limit handling | DONE | Automatic retry on X API 429/5xx; 2 retries per step with 10s delay |
| CLI testing | DONE | main.py tool for direct X API testing without scheduler |
| Retry with resume | DONE | `retry_execution_steps()` can resume from last failed step (fetch/AI/Telegram) |

---

## Non-Functional Requirements

| Requirement | Status | Implementation |
|-------------|--------|-----------------|
| Thread safety | DONE | RLock on all file I/O; per-watchlist locks prevent concurrent runs |
| Graceful shutdown | DONE | Signal handlers (SIGTERM/SIGINT) stop scheduler cleanly |
| Error resilience | DONE | Detailed logging; execution log tracks success/error; retry logic on API failures |
| Performance | DONE | Client caching for Gemini (per API key); message splitting (4000 chars with `\n\n` priority) |
| Configurability | DONE | .env file for API keys; per-watchlist prompt customization |
| Scalability | DONE | Per-watchlist thread locks allow concurrent execution; max 200 log entries (pruned automatically) |
| Security | DONE | OAuth 1.0a for X API; Telegram bot token in .env; API keys not logged |

---

## Architecture Overview

### High-Level Data Flow

```
User Web UI → Flask REST API
              ↓
         APScheduler (UTC+7 CronTrigger)
              ↓
    run_fetch_for_watchlist(wl_id)
         ├── Step 1: Fetch tweets (X API v2)
         ├── Step 2: Summarize (Gemini API)
         └── Step 3: Send to Telegram (Bot API)
              ↓
       Execution Log (JSON)
```

### Component Responsibilities

| Component | Module | Purpose |
|-----------|--------|---------|
| **Flask Server** | `app.py` | Application initialization, APScheduler setup |
| **REST API Routes** | `routes.py` | 21 HTTP endpoints (GET/POST/DELETE), CORS, JSON responses |
| **ETL Pipeline** | `pipeline.py` | Core 3-step execution: fetch → summarize → send; retry logic with resume |
| **Scheduler** | `scheduler_manager.py` | APScheduler singleton, per-watchlist locking, job management |
| **X API Client** | `x_api.py` | OAuth 1.0a, batch user lookup, since_id tracking |
| **AI Summarizer** | `ai_summarizer.py` | Gemini 2.0 Flash, client caching, 4-model routing |
| **Telegram Sender** | `telegram_sender.py` | Bot API calls, Markdown Legacy conversion, message splitting |
| **Config Manager** | `config_manager.py` | JSON file I/O (config + log + targets), thread-safe locking |
| **Web UI** | `templates/index.html` | Vanilla JS SPA (Dashboard, Settings, Execution Log tabs) |

---

## Core Design Decisions

### Per-Watchlist Locking
- **Problem:** Multiple concurrent scheduler jobs might try to run the same watchlist simultaneously.
- **Solution:** `_wl_locks` dict with per-watchlist `threading.Lock()`. Different watchlists run in parallel; same watchlist waits or skips.
- **Benefit:** Allows independent watchlists to fetch concurrently without interference.

### Deduplication via since_id
- **Problem:** Repeatedly fetching the same tweets wastes API quota and clutters logs.
- **Solution:** Store `since_id` per user per watchlist in config. X API returns only newer tweets.
- **Manual Reset:** Web UI provides `POST /api/reset-sync` to clear all since_ids.

### Separate JSON Files
- **Config** (`app_config.json`): Watchlists, schedules, since_ids.
- **Logs** (`execution_log.json`): Execution history (max 200 entries).
- **Telegram Targets** (`telegram_targets.json`): Cached target info (refreshed at startup).
- **Benefit:** Cleaner separation, faster read/write, easier to back up.

### Client Caching (Gemini)
- **Problem:** Creating a new GenAI client on every request is expensive.
- **Solution:** `_client_cache` dict keyed by API key. Reuse client across requests.
- **Benefit:** Reduced initialization overhead for high-frequency summarization calls.

### Markdown Legacy + Plaintext Fallback
- **Problem:** Telegram doesn't support full Markdown (e.g., `##` headings, code blocks not universal).
- **Solution:** Aggressive Markdown Legacy conversion (bold: `*text*`, italic: `_text_`). If parse fails → plaintext.
- **Benefit:** AI-generated summaries render reliably; fallback prevents rendering errors.

### 30-Second Delay Between Watchlists
- **Problem:** Gemini free tier has low rate limits; burst requests trigger 429 errors.
- **Solution:** Sleep 30s between watchlist completions in batch mode.
- **Trade-off:** Slower batch runs, but prevents quota exhaustion.

### Misfire Grace Time (900s)
- **Problem:** If scheduler can't run a job on time (system overload, etc.), APScheduler discards the job by default.
- **Solution:** Set `misfire_grace_time=900` to re-run missed jobs within 15 minutes of original time.
- **Benefit:** Ensures scheduled runs don't disappear.

---

## API Routes (21 Total Endpoints)

### Dashboard & Admin (7 endpoints)
- `GET /` → Web UI (SPA)
- `GET /api/stats` → Dashboard stats + active job list
- `GET /api/execution-log` → Full execution history
- `DELETE /api/execution-log` → Clear all logs
- `DELETE /api/execution-log/<index>` → Delete single entry
- `POST /api/execution-log/<exec_id>/retry` → Retry from failed step
- `POST /api/execution-log/bulk-delete` → Bulk delete by indices

### Watchlist CRUD (4 endpoints)
- `GET /api/watchlists` → List all watchlists
- `POST /api/watchlists` → Create new watchlist
- `PUT /api/watchlists/<id>` → Update watchlist
- `DELETE /api/watchlists/<id>` → Delete watchlist

### Account & Watchlist Management (4 endpoints)
- `POST /api/watchlists/<id>/accounts` → Add account to watchlist
- `DELETE /api/watchlists/<id>/accounts/<username>` → Remove account
- `POST /api/watchlists/<id>/refresh-user-cache` → Refresh user ID cache
- `POST /api/watchlists/<id>/duplicate` → Duplicate watchlist

### Triggers & Tests (2 endpoints)
- `POST /api/run-now` → Trigger immediate run (all watchlists or specific)
- `POST /api/test-telegram` → Test Telegram bot connection

### Configuration (3 endpoints)
- `GET /api/ai-models` → List AI models with key status (present/missing)
- `GET /api/telegram-targets` → List configured Telegram targets
- `POST /api/reset-sync` → Reset all since_ids

---

## Data Models

### Config File (`app_config.json`)
Root structure:
```json
{
  "watchlists": [
    {
      "id": "wl_xxxxxxxx",
      "name": "Crypto News",
      "accounts": ["username1", "username2"],
      "schedule_times": ["08:00", "12:00", "18:00"],
      "ai_model": "gemini_free_1",
      "prompt": "Summarize crypto news...",
      "enabled": true,
      "since_ids": {"username1": "1234567890", "username2": "0987654321"},
      "max_posts_per_user": 10,
      "telegram_targets": [123456789, -1009876543210]
    }
  ],
  "total_fetches": 42
}
```

### Execution Log (`execution_log.json`)
Array of execution entries (max 200, auto-pruned):
```json
[
  {
    "timestamp": "2026-03-31T14:30:00+07:00",
    "watchlist_id": "wl_xxx",
    "watchlist_name": "Crypto News",
    "fetch_status": "success",
    "fetch_detail": "Fetched 12 tweets from 2 accounts",
    "fetch_count": 12,
    "ai_status": "success",
    "ai_detail": "Gemini summarization completed",
    "ai_model_used": "gemini_free_1",
    "tg_status": "success",
    "tg_detail": "Sent to 2 chat IDs",
    "raw_tweets_text": "[raw tweet text here]",
    "ai_summary_text": "[AI summary here]"
  }
]
```

### Telegram Targets Cache (`telegram_targets.json`)
Cached info for quick reference:
```json
[
  {
    "chat_id": 123456789,
    "name": "My Channel"
  }
]
```

---

## Environment Variables

| Variable | Purpose | Example |
|----------|---------|---------|
| `X_API_KEY` | X OAuth 1.0a consumer key | `xxx...` |
| `X_API_SECRET` | X OAuth 1.0a consumer secret | `xxx...` |
| `X_ACCESS_TOKEN` | X OAuth 1.0a access token | `xxx...` |
| `X_ACCESS_TOKEN_SECRET` | X OAuth 1.0a access token secret | `xxx...` |
| `TELEGRAM_BOT_TOKEN` | Telegram Bot API token | `123456:ABC-DEF...` |
| `TELEGRAM_CHAT_ID` | Telegram chat IDs (comma-separated) | `123456789, -1009876543210` |
| `GEMINI_API_KEY_1` | Free Gemini API key 1 | `xxx...` |
| `GEMINI_API_KEY_2` | Free Gemini API key 2 | `xxx...` |
| `GEMINI_API_KEY_3` | Free Gemini API key 3 | `xxx...` |
| `GEMINI_API_KEY_PAID` | Paid Gemini API key | `xxx...` |

---

## Success Criteria

| Criterion | Measure |
|-----------|---------|
| Tweet fetching | Zero duplicate tweets across runs; accurate since_id tracking |
| Summarization | Gemini API responses valid; summary text under 4000 chars when split |
| Telegram delivery | Message received in all configured chat IDs; formatting renders correctly |
| Scheduler reliability | Scheduled runs occur at specified times (UTC+7); missed jobs re-run within 15 min |
| Web UI responsiveness | Dashboard updates reflect latest execution log; CRUD operations persist to JSON |
| Thread safety | No file corruption under concurrent watchlist execution; logs append atomically |
| Error handling | Graceful degradation on API failures; execution log records status/detail; no silent crashes |

---

## Known Limitations & Trade-offs

| Limitation | Reason | Workaround |
|-----------|--------|-----------|
| JSON file storage | Simplicity; no database required | For large-scale deployments, migrate to PostgreSQL |
| Single-machine deployment | No distributed scheduler | Deploy on dedicated machine; use systemd/cron for restart |
| Gemini free tier rate limits | Cost; free tier has ~50 requests/min | Use multiple API keys; monitor usage via dashboard |
| Max 200 execution log entries | Keep logs lightweight | Implement data export or archival script |
| Vanilla JS frontend | Minimizes dependencies; easy to inspect | Trade-off: no TypeScript, build toolchain |

---

## Success Metrics

- **Uptime:** Scheduler runs 99%+ of scheduled jobs (accounting for system downtime).
- **Accuracy:** All tweets fetched without duplicates; since_id tracking validated.
- **Latency:** End-to-end pipeline (fetch → summarize → send) completes in <5 min for typical watchlist (10 tweets, 2 users).
- **User Experience:** Web UI loads in <1s; CRUD operations reflect changes immediately.
- **Reliability:** No data loss on unclean shutdown; logs survive crashes.

