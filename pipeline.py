"""
DuckX Newsfeed - Fetch-Summarize-Send Pipeline
================================================
Core pipeline: fetch tweets → AI summarize → send to Telegram.
Thread-safe via per-watchlist locks.
"""

import os
import time
import threading
import logging
from datetime import datetime
from typing import Optional

import pytz

import config_manager
from x_api import XApiClient, tweets_to_text
from ai_summarizer import summarize_tweets
from telegram_sender import send_message, send_message_to_targets

logger = logging.getLogger(__name__)

TZ_VN = pytz.timezone("Asia/Ho_Chi_Minh")

# Per-watchlist locks: prevent same watchlist running concurrently
_wl_locks: dict[str, threading.Lock] = {}
_wl_locks_guard = threading.Lock()

# Cached X API client — credentials are constant per process lifetime
_x_client: Optional[XApiClient] = None
_x_client_lock = threading.Lock()


def get_x_client() -> XApiClient:
    """Get or create the shared X API client (lazy init, thread-safe)."""
    global _x_client
    with _x_client_lock:
        if _x_client is None:
            _x_client = XApiClient(
                api_key=os.getenv("X_API_KEY", ""),
                api_secret=os.getenv("X_API_SECRET", ""),
                access_token=os.getenv("X_ACCESS_TOKEN", ""),
                access_token_secret=os.getenv("X_ACCESS_TOKEN_SECRET", ""),
            )
        return _x_client


def _get_wl_lock(wl_id: str) -> threading.Lock:
    """Get or create a per-watchlist lock."""
    with _wl_locks_guard:
        if wl_id not in _wl_locks:
            _wl_locks[wl_id] = threading.Lock()
        return _wl_locks[wl_id]


_ADMIN_TELEGRAM_ID = os.getenv("TELEGRAM_ADMIN_ID", "")
_FETCH_MAX_ATTEMPTS = 3  # 1 initial + 2 retries
_AI_MAX_ATTEMPTS = 3     # 1 initial + 2 retries
_TG_MAX_ATTEMPTS = 3     # 1 initial + 2 retries


def _run_ai_with_retry(tweets_text: str, prompt: str, model_id: str, wl_name: str = "") -> tuple[str, bool, str]:
    """
    Run AI summarization with 2 automatic retries on failure (10s delay each).
    Sends Telegram notification to admin if all 3 attempts fail.
    Returns (summary_text, success, detail_message).
    """
    last_err = ""
    for attempt in range(_AI_MAX_ATTEMPTS):
        try:
            result = summarize_tweets(tweets_text, prompt, model_id)
            if not result.startswith("[ERROR]"):
                return result, True, ""
            last_err = result
        except Exception as e:
            last_err = str(e)[:300]
        if attempt < _AI_MAX_ATTEMPTS - 1:
            logger.warning(f"  AI attempt {attempt + 1} failed: {last_err[:80]}, retrying in 10s...")
            time.sleep(10)

    # All retries exhausted — notify admin via Telegram
    _notify_ai_failure(last_err, model_id, wl_name)
    return last_err, False, last_err[:300]


def _notify_ai_failure(error_msg: str, model_id: str, wl_name: str = ""):
    """Send Telegram notification to admin when AI fails after all retries."""
    try:
        now_vn = datetime.now(TZ_VN).strftime("%d/%m/%Y %H:%M")
        wl_line = f"Watchlist: *{wl_name}*\n" if wl_name else ""
        # Truncate at 800 chars to fit Telegram limit while showing meaningful context
        err_display = error_msg[:800] + ("..." if len(error_msg) > 800 else "")
        msg = (
            f"⚠️ *DuckX Newsfeed — AI Error*\n"
            f"⏰ {now_vn}\n"
            f"{wl_line}"
            f"Model: `{model_id}`\n"
            f"Lỗi sau {_AI_MAX_ATTEMPTS} lần thử:\n`{err_display}`"
        )
        send_message_to_targets(msg, [_ADMIN_TELEGRAM_ID])
        logger.info("  Admin notified via Telegram about AI failure")
    except Exception as e:
        logger.error(f"  Failed to send AI failure notification: {e}")


def _notify_fetch_failure(error_msg: str, wl_name: str = ""):
    """Send Telegram notification to admin when Fetch fails after all retries."""
    try:
        now_vn = datetime.now(TZ_VN).strftime("%d/%m/%Y %H:%M")
        wl_line = f"Watchlist: *{wl_name}*\n" if wl_name else ""
        err_display = error_msg[:800] + ("..." if len(error_msg) > 800 else "")
        msg = (
            f"⚠️ *DuckX Newsfeed — Fetch Error*\n"
            f"⏰ {now_vn}\n"
            f"{wl_line}"
            f"Lỗi sau {_FETCH_MAX_ATTEMPTS} lần thử:\n`{err_display}`"
        )
        send_message_to_targets(msg, [_ADMIN_TELEGRAM_ID])
        logger.info("  Admin notified via Telegram about Fetch failure")
    except Exception as e:
        logger.error(f"  Failed to send Fetch failure notification: {e}")


def _run_fetch_with_retry(
    accounts: list, max_per_user: int, since_ids: dict, wl_name: str = "", user_id_cache: dict = None
) -> tuple[dict, bool, str]:
    """
    Run X API fetch with 2 automatic retries on exception (10s delay each).
    Passes user_id_cache to skip batch user lookup for known accounts.
    Sends Telegram notification to admin if all 3 attempts fail.
    Returns (result_dict, success, error_message).
    """
    client = get_x_client()
    last_err = ""
    for attempt in range(_FETCH_MAX_ATTEMPTS):
        try:
            result = client.get_watchlist_tweets(
                usernames=accounts,
                max_per_user=max_per_user,
                since_ids=since_ids,
                user_id_cache=user_id_cache or {},
            )
            return result, True, ""
        except Exception as e:
            last_err = str(e)[:300]
        if attempt < _FETCH_MAX_ATTEMPTS - 1:
            logger.warning(f"  Fetch attempt {attempt + 1} failed: {last_err[:80]}, retrying in 10s...")
            time.sleep(10)

    _notify_fetch_failure(last_err, wl_name)
    return {}, False, last_err


def _notify_telegram_failure(error_msg: str, wl_name: str = ""):
    """Send Telegram notification to admin when Telegram sending fails after all retries."""
    try:
        now_vn = datetime.now(TZ_VN).strftime("%d/%m/%Y %H:%M")
        wl_line = f"Watchlist: *{wl_name}*\n" if wl_name else ""
        err_display = error_msg[:800] + ("..." if len(error_msg) > 800 else "")
        msg = (
            f"⚠️ *DuckX Newsfeed — Telegram Error*\n"
            f"⏰ {now_vn}\n"
            f"{wl_line}"
            f"Lỗi sau {_TG_MAX_ATTEMPTS} lần thử:\n`{err_display}`"
        )
        send_message_to_targets(msg, [_ADMIN_TELEGRAM_ID])
        logger.info("  Admin notified via Telegram about Telegram send failure")
    except Exception as e:
        logger.error(f"  Failed to send Telegram failure notification: {e}")


def run_fetch_for_watchlist(wl_id: str):
    """Run full fetch cycle for a specific watchlist with step-by-step tracking."""
    lock = _get_wl_lock(wl_id)
    if not lock.acquire(blocking=False):
        logger.info(f"Watchlist {wl_id} already running, skipping")
        return

    fetch_status, fetch_detail, fetch_count = "skipped", "", 0
    ai_status, ai_detail, ai_model_used = "skipped", "", ""
    tg_status, tg_detail = "skipped", ""
    raw_tweets_text = ""
    ai_summary_text = ""

    try:
        wl = config_manager.get_watchlist_by_id(wl_id)
        if not wl:
            logger.warning(f"Watchlist {wl_id} not found")
            return

        if not wl.get("enabled", True):
            logger.info(f"Watchlist '{wl['name']}' disabled, skipping")
            return

        accounts = wl.get("accounts", [])
        wl_name = wl["name"]
        ai_model_used = wl.get("ai_model", "gemini_free_1")

        if not accounts:
            config_manager.record_execution(
                wl_id=wl_id, wl_name=wl_name,
                fetch_status="skipped", fetch_detail="No accounts configured",
            )
            return

        logger.info(f"=== FETCH: {wl_name} ({len(accounts)} accounts) ===")

        # ── Step 1: Fetch tweets (with retry + user ID cache) ──
        user_id_cache = config_manager.get_user_id_cache()
        fetch_result, fetch_ok, fetch_err = _run_fetch_with_retry(
            accounts, wl.get("max_posts_per_user", 10), wl.get("since_ids", {}), wl_name,
            user_id_cache=user_id_cache
        )
        if not fetch_ok:
            logger.error(f"  Fetch failed after {_FETCH_MAX_ATTEMPTS} attempts: {fetch_err[:100]}")
            config_manager.record_execution(
                wl_id=wl_id, wl_name=wl_name,
                fetch_status="error", fetch_detail=fetch_err,
            )
            return

        tweets = fetch_result["tweets"]
        users_map = fetch_result["users_map"]
        errors = fetch_result["errors"]

        error_details = [f"@{u}: {e}" for u, e in errors.items()]
        for d in error_details:
            logger.error(f"  Error {d}")

        fetch_count = len(tweets)
        if not tweets:
            fetch_status = "error" if error_details else "success"
            fetch_detail = "; ".join(error_details) if error_details else "No new tweets"
            config_manager.record_execution(
                wl_id=wl_id, wl_name=wl_name,
                fetch_status=fetch_status, fetch_tweet_count=0, fetch_detail=fetch_detail,
            )
            return

        fetch_status = "success"
        fetch_detail = f"Fetched {fetch_count} tweets from {len(accounts)} accounts"
        if error_details:
            fetch_detail += f" (errors: {'; '.join(error_details)})"
        logger.info(f"  Fetched {fetch_count} tweets")

        for username, sid in fetch_result["new_since_ids"].items():
            config_manager.set_since_id(wl_id, username, sid)
        raw_tweets_text = tweets_to_text(tweets, users_map)

        # Persist newly discovered user ID mappings (skips batch lookup on future runs)
        new_cache_entries = fetch_result.get("new_cache_entries", {})
        if new_cache_entries:
            config_manager.update_user_id_cache(new_cache_entries)
            logger.info(f"  Cached {len(new_cache_entries)} new user ID mappings")

        # ── Step 2: AI Summarize (with retry) ──
        ai_summary_text, ai_ok, ai_err = _run_ai_with_retry(
            raw_tweets_text, wl.get("prompt", ""), ai_model_used, wl_name
        )
        if ai_ok:
            ai_status = "success"
            ai_detail = f"Summarized {fetch_count} tweets"
            logger.info(f"  AI OK ({len(ai_summary_text)} chars)")
        else:
            ai_status = "error"
            ai_detail = ai_err
            logger.error(f"  AI failed: {ai_err[:100]}")

        # ── Step 3: Telegram (skip if AI failed) ──
        if ai_status == "error":
            tg_status = "skipped"
            tg_detail = "Skipped: AI failed after retry"
            logger.info("  Telegram skipped (AI failed)")
        else:
            tg_status, tg_detail = _send_telegram_with_retry(wl, wl_name, fetch_count, ai_summary_text)

        config_manager.record_execution(
            wl_id=wl_id, wl_name=wl_name,
            fetch_status=fetch_status, fetch_tweet_count=fetch_count, fetch_detail=fetch_detail,
            ai_status=ai_status, ai_model=ai_model_used, ai_detail=ai_detail,
            telegram_status=tg_status, telegram_detail=tg_detail,
            raw_tweets=raw_tweets_text, ai_summary=ai_summary_text,
        )
        logger.info(f"=== DONE: {wl_name} ===")

    except Exception as e:
        logger.error(f"Unexpected error in watchlist {wl_id}: {e}", exc_info=True)
    finally:
        lock.release()


def _send_telegram_step(wl: dict, wl_name: str, fetch_count: int, ai_summary: str) -> tuple[str, str]:
    """Send summary to Telegram. Returns (status, detail)."""
    try:
        now_vn = datetime.now(TZ_VN).strftime("%d/%m/%Y %H:%M")
        header = f"📋 **DuckX Newsfeed: {wl_name}**\n⏰ {now_vn}\n📊 {fetch_count} tweets\n\n"
        wl_targets = wl.get("telegram_targets", [])
        tg_result = (
            send_message_to_targets(header + ai_summary, wl_targets)
            if wl_targets
            else send_message(header + ai_summary)
        )
        if tg_result["success"]:
            logger.info("  Telegram sent OK")
            return "success", "Message sent"
        detail = tg_result.get("message", "Unknown error")[:300]
        logger.error(f"  Telegram error: {detail}")
        return "error", detail
    except Exception as e:
        logger.error(f"  Telegram exception: {e}")
        return "error", str(e)[:300]


def _send_telegram_with_retry(wl: dict, wl_name: str, fetch_count: int, ai_summary: str) -> tuple[str, str]:
    """
    Send Telegram message with 2 automatic retries on failure (10s delay each).
    Markdown parse errors are handled inside _send_telegram_step (plaintext fallback).
    Sends admin notification if all 3 attempts fail.
    Returns (status, detail).
    """
    last_status, last_detail = "error", ""
    for attempt in range(_TG_MAX_ATTEMPTS):
        last_status, last_detail = _send_telegram_step(wl, wl_name, fetch_count, ai_summary)
        if last_status == "success":
            return last_status, last_detail
        if attempt < _TG_MAX_ATTEMPTS - 1:
            logger.warning(f"  Telegram attempt {attempt + 1} failed: {last_detail[:80]}, retrying in 10s...")
            time.sleep(10)

    _notify_telegram_failure(last_detail, wl_name)
    return last_status, last_detail


def retry_execution_steps(exec_id: str):
    """
    Retry failed steps from an existing execution log entry.
    - fetch failed → re-run full pipeline
    - fetch ok, AI failed → re-run AI + Telegram using stored raw_tweets
    - AI ok, Telegram failed → re-send using stored ai_summary
    Always creates a new log entry for the retry run.
    """
    log = config_manager.get_execution_log()
    entry = next((e for e in log if e.get("id") == exec_id), None)
    if not entry:
        logger.warning(f"Execution entry {exec_id} not found for retry")
        return

    wl_id = entry.get("watchlist_id")
    wl = config_manager.get_watchlist_by_id(wl_id)
    if not wl:
        logger.warning(f"Watchlist {wl_id} not found for retry")
        return

    steps = entry.get("steps", {})
    fetch_status = steps.get("fetch", {}).get("status", "error")
    ai_status = steps.get("ai", {}).get("status", "error")
    raw_tweets = entry.get("raw_tweets", "")

    logger.info(f"=== RETRY: {wl['name']} (exec_id={exec_id}) ===")

    if fetch_status == "error" or not raw_tweets:
        # Re-run full pipeline (fetch will get fresh tweets)
        logger.info("  Retrying full pipeline")
        run_fetch_for_watchlist(wl_id)
        return

    wl_name = wl["name"]
    ai_model = wl.get("ai_model", "gemini_free_1")
    fetch_count = steps.get("fetch", {}).get("tweet_count", 0)
    fetch_detail = steps.get("fetch", {}).get("detail", "")

    if ai_status in ("error", "skipped"):
        # Retry from AI step using stored raw_tweets
        logger.info("  Retrying AI + Telegram")
        ai_summary, ai_ok, ai_err = _run_ai_with_retry(raw_tweets, wl.get("prompt", ""), ai_model, wl_name)
        ai_status_new = "success" if ai_ok else "error"
        ai_detail_new = f"Retry: Summarized {fetch_count} tweets" if ai_ok else ai_err
        tg_status, tg_detail = "skipped", "Skipped: AI failed after retry"
        if ai_ok:
            tg_status, tg_detail = _send_telegram_with_retry(wl, wl_name, fetch_count, ai_summary)
        config_manager.record_execution(
            wl_id=wl_id, wl_name=wl_name,
            fetch_status="success", fetch_tweet_count=fetch_count, fetch_detail=f"[Retry] {fetch_detail}",
            ai_status=ai_status_new, ai_model=ai_model, ai_detail=ai_detail_new,
            telegram_status=tg_status, telegram_detail=tg_detail,
            raw_tweets=raw_tweets, ai_summary=ai_summary if ai_ok else "",
        )
    else:
        # Retry Telegram only using stored ai_summary
        logger.info("  Retrying Telegram only")
        ai_detail = steps.get("ai", {}).get("detail", "")
        ai_model_used = steps.get("ai", {}).get("model", ai_model)
        ai_summary = entry.get("ai_summary", "")
        tg_status, tg_detail = _send_telegram_with_retry(wl, wl_name, fetch_count, ai_summary)
        config_manager.record_execution(
            wl_id=wl_id, wl_name=wl_name,
            fetch_status="success", fetch_tweet_count=fetch_count, fetch_detail=f"[Retry] {fetch_detail}",
            ai_status="success", ai_model=ai_model_used, ai_detail=f"[Retry] {ai_detail}",
            telegram_status=tg_status, telegram_detail=tg_detail,
            raw_tweets=raw_tweets, ai_summary=ai_summary,
        )

    logger.info(f"=== RETRY DONE: {wl_name} ===")


def run_all_watchlists():
    """Run all enabled watchlists sequentially with 30s delay (Gemini rate limit protection)."""
    enabled = [wl for wl in config_manager.get_watchlists() if wl.get("enabled", True)]
    total = len(enabled)
    logger.info(f"=== RUN ALL: {total} watchlists (30s interval) ===")

    for i, wl in enumerate(enabled):
        logger.info(f"[{i + 1}/{total}] Running: {wl['name']}")
        run_fetch_for_watchlist(wl["id"])
        if i < total - 1:
            logger.info("Waiting 30s (Gemini rate limit)...")
            time.sleep(30)

    logger.info("=== RUN ALL COMPLETE ===")
