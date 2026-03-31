# DuckX Newsfeed — Code Standards & Conventions

## Python Code Style

### File Organization
- **Header:** Module docstring (3 lines: title, separator, description)
- **Imports:** Standard library → Third-party → Local modules (separated by blank line)
- **Constants:** UPPERCASE_WITH_UNDERSCORES (module-level)
- **Classes:** PascalCase (definitions near top after imports/constants)
- **Functions:** snake_case (organized by logical section with comment dividers)
- **Line length:** 120 characters max (focus on readability, not 80-char rigid limit)

### Example Header
```python
"""
DuckX Newsfeed - Config Manager
================================
Manages per-watchlist configuration in app_config.json.
"""

import json
import os
import threading

CONFIG_FILE = os.path.join(...)
MAX_LOG_ENTRIES = 200

class MyClass:
    pass

def my_function():
    pass
```

### Naming Conventions
| Item | Convention | Example |
|------|-----------|---------|
| Modules | `snake_case.py` | `config_manager.py`, `x_api.py` |
| Classes | `PascalCase` | `XApiClient`, `ConfigManager` |
| Functions | `snake_case` | `run_fetch_for_watchlist()`, `batch_lookup_users()` |
| Constants | `CONSTANT_CASE` | `MAX_LOG_ENTRIES`, `TZ_VN` |
| Private (internal) | `_leading_underscore` | `_io_lock`, `_get_wl_lock()` |
| Booleans | `is_*` or `has_*` | `is_expired_token()`, `has_error` |

### Type Hints
- **Required** for function signatures (parameters + return type)
- **Optional** for local variables (use only if clarity improves readability)
- Use `dict`, `list`, `str`, `bool` for built-ins; `Optional[T]` for nullable types

```python
def load_config() -> dict:
    """Load config from file."""
    pass

def get_watchlist_by_id(wl_id: str) -> Optional[dict]:
    """Find watchlist; return None if not found."""
    pass
```

### Error Handling
- **Prefer explicit exceptions** over silent failures
- **Log before raising** (context helps debugging)
- **Catch specific exceptions** (not bare `except:`)
- **Use try-except sparingly** (only for expected API errors, file I/O)

```python
try:
    response = requests.get(url, timeout=5)
    response.raise_for_status()
except requests.exceptions.HTTPError as e:
    logger.error(f"X API request failed: {e}")
    raise
except Exception as e:
    logger.exception("Unexpected error")
    raise
```

### Docstrings
- **Module-level:** 1-2 sentences describing the module's purpose
- **Class-level:** 1 sentence; list main methods if complex
- **Function-level:** 1-2 sentences + **Args** / **Returns** sections if helpful

```python
def get_watchlist_tweets(
    usernames: list[str],
    max_results_per_user: int,
    since_ids: dict[str, str]
) -> tuple[list[dict], dict, dict]:
    """
    Fetch tweets from multiple users.
    
    Args:
        usernames: List of Twitter usernames (no @)
        max_results_per_user: Max tweets per user (1-100)
        since_ids: {username: last_tweet_id} for dedup
    
    Returns:
        (tweets_list, users_map, updated_since_ids)
    """
    pass
```

### Logging
- **Use Python's `logging` module** (not print statements)
- **Log level:**
  - `logger.debug()` — Detailed info for developers
  - `logger.info()` — Status updates, job starts/completions
  - `logger.warning()` — Recoverable errors (retries, API rate limits)
  - `logger.error()` — Non-fatal errors (API failures, config issues)
  - `logger.exception()` — In except blocks (includes traceback)
- **Format:** ISO timestamp + level + message (configured in `app.py`)

```python
logger.info(f"Fetching tweets for watchlist '{wl_name}' ({wl_id})")
logger.warning(f"X API 429, retrying in {wait}s")
logger.error(f"Telegram send failed for chat {chat_id}: {error}")
logger.exception("Unexpected error during fetch")
```

### Comments
- **Use sparingly** — Code should be self-documenting
- **WHY comments, not WHAT comments** — Explain intent, not the obvious

```python
# Good: Explains intent
# Retry on rate limit (429) because X API quota resets in small windows
if response.status_code == 429:
    time.sleep(retry_after)

# Bad: States the obvious
# If status code is 429, sleep
if response.status_code == 429:
    time.sleep(retry_after)
```

### Threading
- **Locks:** Use `threading.Lock()` or `threading.RLock()` for mutable shared state
- **Lock scope:** As small as possible (lock → operate → release)
- **Avoid deadlock:** Always release locks (use `with` statements or try-finally)

```python
_io_lock = threading.RLock()

def load_config():
    with _io_lock:  # Acquire lock
        with open(CONFIG_FILE) as f:
            config = json.load(f)
    # Lock released automatically
    return config
```

### File I/O
- **Always use context managers** (`with` statements)
- **Specify encoding:** UTF-8 for config/log files
- **Atomic operations:** Read → modify → write in single locked block

```python
with open(filepath, "r", encoding="utf-8") as f:
    data = json.load(f)

with open(filepath, "w", encoding="utf-8") as f:
    json.dump(data, f, indent=2, ensure_ascii=False)
```

---

## JavaScript (Vanilla) Code Style

### File Organization
- **Single file:** `templates/index.html` (HTML + CSS + JS combined)
- **Sections:** Separated by `<!-- ===== SECTION NAME ===== -->` comments
- **JS functions:** Organized by feature/tab (Dashboard, Settings, Logs)

### Naming Conventions
| Item | Convention | Example |
|------|-----------|---------|
| Functions | `camelCase` | `fetchData()`, `submitForm()` |
| Variables | `camelCase` | `watchlistId`, `chatId` |
| HTML IDs | `kebab-case` | `#watchlist-list`, `#settings-tab` |
| CSS classes | `kebab-case` | `.form-group`, `.btn-primary` |
| Constants | `CONSTANT_CASE` | `API_BASE = "/api"` |

### Example Function
```javascript
// Fetch data from API; log errors
async function fetchData(endpoint) {
    try {
        const response = await fetch(`/api/${endpoint}`);
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        return await response.json();
    } catch (error) {
        console.error(`Fetch failed: ${error.message}`);
        alert("Error loading data. Check console.");
        return null;
    }
}
```

### Event Handlers
```javascript
// Attach listener to form submit
document.getElementById("form-id").addEventListener("submit", async (e) => {
    e.preventDefault();
    const formData = new FormData(e.target);
    await submitForm("form-id", "/api/endpoint");
});
```

### DOM Manipulation
- **Use `getElementById()` for specific elements** (clearer intent)
- **Use `querySelector()` for complex selectors** (when ID not available)
- **Avoid global variables** — Encapsulate in functions or IIFE

```javascript
// Good: Clear intent
const watchlistList = document.getElementById("watchlist-list");

// Also acceptable: Complex selector
const disabledWatchlists = document.querySelectorAll(".watchlist.disabled");
```

### Async/Await
- **Use async/await for Promises** (clearer than .then() chains)
- **Always try-catch async operations**

```javascript
async function loadDashboard() {
    try {
        const stats = await fetchData("stats");
        if (!stats) return;
        renderStats(stats);
    } catch (error) {
        console.error("Dashboard load failed:", error);
    }
}
```

### Comments
- **Code is self-documenting** — Minimize comments
- **Use comments for non-obvious logic** (regex patterns, complex event handling)

```javascript
// Parse ISO timestamp to local time string
function formatTime(isoString) {
    return new Date(isoString).toLocaleString();
}

// Regex: match @username mentions in tweets
const mentionRegex = /@\w+/g;
```

---

## JSON Data Format

### Config File (`app_config.json`)
```json
{
  "watchlists": [
    {
      "id": "wl_uuid_here",
      "name": "Crypto News",
      "accounts": ["elonmusk", "vitalikbuterin"],
      "schedule_times": ["08:00", "14:00", "20:00"],
      "ai_model": "gemini_free_1",
      "prompt": "Summarize crypto news...",
      "enabled": true,
      "since_ids": {"elonmusk": "1234567", "vitalikbuterin": "7654321"},
      "max_posts_per_user": 10,
      "telegram_targets": [123456789]
    }
  ],
  "total_fetches": 42
}
```

### Execution Log (`execution_log.json`)
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
    "raw_tweets_text": "[raw tweet text]",
    "ai_summary_text": "[AI summary]"
  }
]
```

**Conventions:**
- Field names: `snake_case`
- Timestamps: ISO 8601 with timezone (UTC+7)
- Status: "success" | "error" | "skipped" (lowercase)
- Indentation: 2 spaces (human-readable)
- Unicode: UTF-8 (ensure_ascii=False in json.dump)

---

## API Response Format

### Success Response
```json
{
  "status": "success",
  "data": {...} or [...]
}
```

### Error Response
```json
{
  "status": "error",
  "message": "Human-readable error message"
}
```

### Examples
```python
# GET /api/watchlists
{
  "status": "success",
  "data": [
    {"id": "wl_xxx", "name": "Crypto News", ...},
    {"id": "wl_yyy", "name": "AI Tech", ...}
  ]
}

# POST /api/watchlists/wl_xxx/accounts (error)
{
  "status": "error",
  "message": "Account '@john' already exists in this watchlist"
}
```

---

## Flask Patterns

### Route Definition
```python
@app.route("/api/watchlists", methods=["GET", "POST"])
def watchlists():
    if request.method == "GET":
        return jsonify({"status": "success", "data": config_manager.get_watchlists()})
    
    if request.method == "POST":
        data = request.get_json()
        wl = config_manager.save_watchlist(data)
        return jsonify({"status": "success", "data": wl}), 201
```

### Error Handling
```python
@app.errorhandler(404)
def not_found(error):
    return jsonify({"status": "error", "message": "Endpoint not found"}), 404

@app.errorhandler(500)
def internal_error(error):
    logger.exception("Internal server error")
    return jsonify({"status": "error", "message": "Internal server error"}), 500
```

---

## HTML/CSS Conventions

### HTML Structure
- **Semantic tags** — `<header>`, `<main>`, `<section>`, `<button>` (not divs everywhere)
- **Accessible IDs** — Every interactive element has unique ID
- **Data attributes** — `data-watchlist-id` for passing context to JS

```html
<button id="btn-run-now" class="btn btn-primary" data-watchlist-id="wl_123">
  Run Now
</button>
```

### CSS Classes
- **BEM-inspired** — `.component__element--modifier` for clarity
- **Semantic names** — `.btn-primary` (not `.red-button`)
- **Reusable** — No ID-based styling (use classes)

```css
.card { /* Component */ }
.card__header { /* Element */ }
.card--highlighted { /* Modifier */ }

.btn { /* Base button */ }
.btn--primary { /* Primary variant */ }
.btn--danger { /* Danger variant */ }
```

### Responsive Design
- **Mobile-first** — Base styles are mobile, add `@media` for larger screens
- **Breakpoint:** 768px (tablet and up)

```css
.container { width: 100%; } /* Mobile */

@media (min-width: 768px) {
    .container { width: 750px; } /* Tablet and up */
}
```

---

## Testing & Validation

### Unit Testing (Implicit)
- **No formal test suite** in this project (single-file SPA + JSON storage)
- **Manual testing:** Use CLI tool (`main.py`) for X API; web UI for CRUD
- **Integration testing:** Run `python app.py` locally; verify fetch-summarize-send pipeline

### Linting (Not Enforced)
- **Python:** Use `flake8` or `pylint` for code quality (not strict; focus on functionality)
- **JavaScript:** Use `eslint` if adding a build toolchain (currently none)
- **No strict formatting:** Readability > rigid style rules

### Code Review Checklist
- [ ] Does the code follow naming conventions?
- [ ] Are docstrings present for public functions?
- [ ] Are errors logged before raising exceptions?
- [ ] Are locks/RLocks used for shared mutable state?
- [ ] Does the code handle the X API's 429 (rate limit) responses?
- [ ] Are Telegram messages split correctly (under 4000 chars)?
- [ ] Is JSON handling thread-safe (file I/O inside locks)?
- [ ] Does the execution log gracefully handle 200+ entries (auto-prune)?

---

## Secrets & Security

### API Keys
- **Never hardcode** API keys in source code
- **Store in `.env` file** (use `python-dotenv` to load)
- **Git ignore:** `.env` is in `.gitignore` (not committed)
- **Log safety:** Never log API keys or tokens (sanitize before logging)

```python
# Bad: Logs include token
logger.info(f"Telegram token: {bot_token}")

# Good: Log is generic
logger.info("Testing Telegram connection")
```

### OAuth 1.0a
- **X API uses OAuth 1.0a** (more secure than API key alone)
- **4 credentials required:** API Key, API Secret, Access Token, Token Secret
- **Token scope:** Read-only (not write); safe for public repos

### Telegram Bot Token
- **Sensitive:** Treat like a password
- **In `.env` only**
- **Do NOT expose in logs or frontend**

---

## Performance Guidelines

### Caching
- **Gemini clients:** Cached by API key (reuse across requests)
- **Config:** Loaded fresh from disk (small file, no performance impact)
- **Telegram targets:** Cached in memory; refreshed at startup

### Batch Operations
- **X API:** Use `batch_lookup_users()` (single API call for multiple usernames)
- **Telegram:** Use `ThreadPoolExecutor` to send to multiple chat IDs in parallel

### Rate Limiting
- **X API:** Auto-retry on 429 with exponential backoff
- **Gemini free tier:** 30s delay between watchlists (manual pacing)
- **Telegram:** No documented rate limits; reasonable to assume <100 msgs/min safe

### Database
- **JSON file storage:** Fast for small data (<10 MB)
- **Scaling limit:** ~100 watchlists with history
- **Beyond that:** Migrate to PostgreSQL or similar

---

## Deprecation & Breaking Changes

### Policy
- **Deprecate responsibly:** Add warning log messages before removing features
- **Version in docs:** Note breaking changes in CHANGELOG
- **Migration guide:** Provide clear upgrade path

### Example
```python
def old_function():
    logger.warning("old_function() is deprecated; use new_function() instead")
    # ... implementation
```

---

## Dependencies Management

### Adding New Packages
1. Add to `requirements.txt` with version pin
2. Update `config.example.env` if new env vars needed
3. Document in `README.md` (Cài đặt section)
4. Commit both files

### Removing Packages
1. Remove from code
2. Remove from `requirements.txt`
3. Update docs if user-facing
4. Commit

### Pinning Versions
- **Use approximate versions** (e.g., `flask>=3.0,<4.0`) to allow patch updates
- **Avoid pinning exact versions** unless there's a known incompatibility

```
flask>=3.0,<4.0
apscheduler>=3.10,<4.0
google-genai>=0.3.0
```

---

## Documentation Standards

### README.md
- **Vietnamese-first** (primary audience)
- **Features, Installation, Configuration, Usage**
- **Examples for all CLI tools and common tasks**

### Inline Comments
- **Minimal:** Code is self-documenting
- **Explain WHY, not WHAT**
- **Prefer clear function/variable names over comments**

### Docstrings
- **Module-level:** 1-2 lines describing purpose
- **Class-level:** 1 line + main methods if needed
- **Function-level:** 1-2 lines + Args/Returns sections

---

## Continuous Improvement

### Code Smell Indicators
| Smell | Fix | Example |
|-------|-----|---------|
| Functions >50 lines | Split into smaller functions | Break up `run_fetch_for_watchlist()` |
| Nested loops 3+ deep | Extract inner loop to function | `for watchlist in ... for account in ...` |
| Try-except catching `Exception` | Catch specific exceptions | Only catch `HTTPError`, `JSONDecodeError`, etc. |
| Global variables | Pass as parameters or use class | Avoid global `_wl_locks` outside of module scope |
| Long argument lists (>5) | Use dataclass or dict | Consolidate into config object |

### Regular Reviews
- **Monthly:** Check for deprecation warnings (third-party packages)
- **Quarterly:** Audit error logs for patterns (missing validation, API issues)
- **Yearly:** Evaluate breaking changes in dependencies; plan upgrades

