"""
DuckX Newsfeed - Config Manager
================================
Manages per-watchlist configuration in app_config.json.
Execution logs stored separately in execution_log.json.
"""

import json
import os
import uuid
from datetime import datetime

CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "app_config.json")
LOG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "execution_log.json")

DEFAULT_AI_PROMPT = (
    "Ban la mot tro ly AI. Hay tom tat cac tweets sau bang tieng Viet, "
    "nhom theo chu de. Voi moi chu de, viet 2-3 cau tom tat ngan gon. "
    "Neu co tin quan trong hoac dot pha, danh dau bang [QUAN TRONG]. "
    "Cuoi cung, liet ke top 3 tweets dang chu y nhat."
)

DEFAULT_CONFIG = {
    "watchlists": [],
    "total_fetches": 0,
}

MAX_LOG_ENTRIES = 200

AI_MODELS = {
    "gemini_free_1": {"label": "Gemini Free 1", "env_key": "GEMINI_API_KEY_1"},
    "gemini_free_2": {"label": "Gemini Free 2", "env_key": "GEMINI_API_KEY_2"},
    "gemini_free_3": {"label": "Gemini Free 3", "env_key": "GEMINI_API_KEY_3"},
    "gemini_paid_1": {"label": "Gemini Paid 1", "env_key": "GEMINI_API_KEY_PAID"},
}


# ─────────────────────────────────────────────
# Core Config I/O
# ─────────────────────────────────────────────

def load_config() -> dict:
    if not os.path.exists(CONFIG_FILE):
        save_config(DEFAULT_CONFIG)
        return DEFAULT_CONFIG.copy()
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            config = json.load(f)
        for key, value in DEFAULT_CONFIG.items():
            if key not in config:
                config[key] = value
        return config
    except (json.JSONDecodeError, IOError):
        save_config(DEFAULT_CONFIG)
        return DEFAULT_CONFIG.copy()


def save_config(config: dict):
    # Remove execution_log if it exists in config (migration cleanup)
    config.pop("execution_log", None)
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)


# ─────────────────────────────────────────────
# Execution Log I/O (separate file)
# ─────────────────────────────────────────────

def _load_log() -> list:
    if not os.path.exists(LOG_FILE):
        return []
    try:
        with open(LOG_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, IOError):
        return []


def _save_log(log: list):
    with open(LOG_FILE, "w", encoding="utf-8") as f:
        json.dump(log, f, indent=2, ensure_ascii=False)


def _migrate_log_from_config():
    """One-time migration: move execution_log from app_config.json to execution_log.json."""
    if os.path.exists(LOG_FILE):
        return  # Already migrated
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            config = json.load(f)
        old_log = config.get("execution_log", [])
        if old_log:
            # Convert old format entries to new format
            migrated = []
            for entry in old_log:
                migrated.append({
                    "id": f"exec_{uuid.uuid4().hex[:8]}",
                    "time": entry.get("time", ""),
                    "watchlist_id": "",
                    "watchlist_name": entry.get("watchlist", ""),
                    "steps": {
                        "fetch": {
                            "status": "success" if entry.get("tweet_count", 0) > 0 else "skipped",
                            "tweet_count": entry.get("tweet_count", 0),
                            "detail": "",
                        },
                        "ai": {
                            "status": "error" if "[AI Error" in entry.get("summary_preview", "") else ("success" if entry.get("summary_preview") else "skipped"),
                            "model": "",
                            "detail": "",
                        },
                        "telegram": {
                            "status": "success" if entry.get("summary_preview") else "skipped",
                            "detail": "",
                        },
                    },
                    "raw_tweets": "",
                    "ai_summary": entry.get("summary_preview", ""),
                })
            _save_log(migrated)
            # Remove from config
            config.pop("execution_log", None)
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(config, f, indent=2, ensure_ascii=False)
    except Exception:
        pass


# ─────────────────────────────────────────────
# Watchlist CRUD
# ─────────────────────────────────────────────

def get_watchlists() -> list:
    return load_config().get("watchlists", [])


def get_watchlist_by_id(wl_id: str) -> dict:
    for wl in get_watchlists():
        if wl["id"] == wl_id:
            return wl
    return None


def create_watchlist(name: str) -> dict:
    config = load_config()
    new_wl = {
        "id": f"wl_{uuid.uuid4().hex[:8]}",
        "name": name.strip(),
        "accounts": [],
        "schedule_times": ["08:00", "12:00", "18:00"],
        "ai_model": "gemini_free_1",
        "prompt": DEFAULT_AI_PROMPT,
        "enabled": True,
        "since_ids": {},
        "max_posts_per_user": 10,
    }
    config["watchlists"].append(new_wl)
    save_config(config)
    return new_wl


def update_watchlist(wl_id: str, updates: dict) -> bool:
    config = load_config()
    for wl in config["watchlists"]:
        if wl["id"] == wl_id:
            allowed_fields = ["name", "schedule_times", "ai_model", "prompt", "enabled", "max_posts_per_user"]
            for key in allowed_fields:
                if key in updates:
                    wl[key] = updates[key]
            save_config(config)
            return True
    return False


def delete_watchlist(wl_id: str) -> bool:
    config = load_config()
    original_len = len(config["watchlists"])
    config["watchlists"] = [wl for wl in config["watchlists"] if wl["id"] != wl_id]
    if len(config["watchlists"]) < original_len:
        save_config(config)
        return True
    return False


# ─────────────────────────────────────────────
# Account Management (per watchlist)
# ─────────────────────────────────────────────

def add_account(wl_id: str, username: str) -> bool:
    username = username.lstrip("@").strip()
    if not username:
        return False
    config = load_config()
    for wl in config["watchlists"]:
        if wl["id"] == wl_id:
            if username.lower() in [a.lower() for a in wl["accounts"]]:
                return False
            wl["accounts"].append(username)
            save_config(config)
            return True
    return False


def remove_account(wl_id: str, username: str) -> bool:
    username = username.lstrip("@").strip()
    config = load_config()
    for wl in config["watchlists"]:
        if wl["id"] == wl_id:
            new_list = [a for a in wl["accounts"] if a.lower() != username.lower()]
            if len(new_list) < len(wl["accounts"]):
                wl["accounts"] = new_list
                save_config(config)
                return True
    return False


# ─────────────────────────────────────────────
# Since IDs (dedup per watchlist)
# ─────────────────────────────────────────────

def get_since_ids(wl_id: str) -> dict:
    wl = get_watchlist_by_id(wl_id)
    if wl:
        return wl.get("since_ids", {})
    return {}


def set_since_id(wl_id: str, username: str, tweet_id: str):
    config = load_config()
    for wl in config["watchlists"]:
        if wl["id"] == wl_id:
            if "since_ids" not in wl:
                wl["since_ids"] = {}
            wl["since_ids"][username.lower()] = tweet_id
            save_config(config)
            return


def reset_all_since_ids():
    """Xóa tất cả since_ids ở mọi watchlist để force app lấy lại mọi thứ từ đầu."""
    config = load_config()
    for wl in config.get("watchlists", []):
        wl["since_ids"] = {}
    save_config(config)

# ─────────────────────────────────────────────
# Execution Log & Stats
# ─────────────────────────────────────────────

def record_execution(
    wl_id: str,
    wl_name: str,
    fetch_status: str = "skipped",
    fetch_tweet_count: int = 0,
    fetch_detail: str = "",
    ai_status: str = "skipped",
    ai_model: str = "",
    ai_detail: str = "",
    telegram_status: str = "skipped",
    telegram_detail: str = "",
    raw_tweets: str = "",
    ai_summary: str = "",
):
    """Record a detailed execution entry."""
    # Increment total_fetches
    config = load_config()
    config["total_fetches"] = config.get("total_fetches", 0) + 1
    save_config(config)

    # Save log entry
    entry = {
        "id": f"exec_{uuid.uuid4().hex[:8]}",
        "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "watchlist_id": wl_id,
        "watchlist_name": wl_name,
        "steps": {
            "fetch": {
                "status": fetch_status,
                "tweet_count": fetch_tweet_count,
                "detail": fetch_detail,
            },
            "ai": {
                "status": ai_status,
                "model": ai_model,
                "detail": ai_detail,
            },
            "telegram": {
                "status": telegram_status,
                "detail": telegram_detail,
            },
        },
        "raw_tweets": raw_tweets[:10000],  # Cap at 10k chars
        "ai_summary": ai_summary[:5000],   # Cap at 5k chars
    }

    log = _load_log()
    log.insert(0, entry)
    log = log[:MAX_LOG_ENTRIES]
    _save_log(log)


def get_execution_log() -> list:
    """Get execution log (runs migration on first call if needed)."""
    _migrate_log_from_config()
    return _load_log()


def delete_execution_log(index: int = None):
    """
    Xóa log ở vị trí `index`.
    Nếu index=None, xóa toàn bộ log.
    """
    if index is None:
        _save_log([])
        return
    log = _load_log()
    if 0 <= index < len(log):
        log.pop(index)
        _save_log(log)

def delete_multiple_execution_logs(indices: list):
    """Xóa nhiều log một lúc theo danh sách index."""
    log = _load_log()
    # Delete from highest index to lowest to avoid shifting issues
    indices = sorted([i for i in indices if 0 <= i < len(log)], reverse=True)
    for i in indices:
        log.pop(i)
    _save_log(log)



def get_dashboard_stats() -> dict:
    config = load_config()
    watchlists = config.get("watchlists", [])
    total_accounts = sum(len(wl.get("accounts", [])) for wl in watchlists)

    log = _load_log()
    total = len(log)
    success_count = sum(
        1 for e in log
        if e.get("steps", {}).get("fetch", {}).get("status") == "success"
        and e.get("steps", {}).get("ai", {}).get("status") == "success"
        and e.get("steps", {}).get("telegram", {}).get("status") == "success"
    )
    error_count = sum(
        1 for e in log
        if any(
            e.get("steps", {}).get(step, {}).get("status") == "error"
            for step in ("fetch", "ai", "telegram")
        )
    )
    last_run = log[0]["time"] if log else "--"

    return {
        "watchlist_count": len(watchlists),
        "total_accounts": total_accounts,
        "total_fetches": total,  # Fetch from logs dynamic size
        "success_count": success_count,
        "error_count": error_count,
        "success_rate": round(success_count / total * 100) if total > 0 else 0,
        "last_run": last_run,
    }
