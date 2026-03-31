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
_x_client: XApiClient | None = None
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


def _run_ai_with_retry(tweets_text: str, prompt: str, model_id: str) -> tuple[str, bool, str]:
    """
    Run AI summarization with one automatic retry on failure (10s delay).
    Returns (summary_text, success, detail_message).
    """
    last_err = ""
    for attempt in range(2):
        try:
            result = summarize_tweets(tweets_text, prompt, model_id)
            if not result.startswith("[ERROR]"):
                return result, True, ""
            last_err = result
        except Exception as e:
            last_err = str(e)[:300]
        if attempt == 0:
            logger.warning(f"  AI attempt 1 failed: {last_err[:80]}, retrying in 10s...")
            time.sleep(10)
    return last_err, False, last_err[:300]


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

        # ── Step 1: Fetch tweets ──
        try:
            client = get_x_client()
            result = client.get_watchlist_tweets(
                usernames=accounts,
                max_per_user=wl.get("max_posts_per_user", 10),
                since_ids=wl.get("since_ids", {}),
            )
            tweets = result["tweets"]
            users_map = result["users_map"]
            errors = result["errors"]

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

            for username, sid in result["new_since_ids"].items():
                config_manager.set_since_id(wl_id, username, sid)
            raw_tweets_text = tweets_to_text(tweets, users_map)

        except Exception as e:
            fetch_detail = str(e)[:300]
            logger.error(f"  Fetch error: {e}")
            config_manager.record_execution(
                wl_id=wl_id, wl_name=wl_name,
                fetch_status="error", fetch_detail=fetch_detail,
            )
            return

        # ── Step 2: AI Summarize (with retry) ──
        ai_summary_text, ai_ok, ai_err = _run_ai_with_retry(
            raw_tweets_text, wl.get("prompt", ""), ai_model_used
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
            try:
                now_vn = datetime.now(TZ_VN).strftime("%d/%m/%Y %H:%M")
                header = f"📋 **DuckX Newsfeed: {wl_name}**\n⏰ {now_vn}\n📊 {fetch_count} tweets\n\n"
                wl_targets = wl.get("telegram_targets", [])
                tg_result = (
                    send_message_to_targets(header + ai_summary_text, wl_targets)
                    if wl_targets
                    else send_message(header + ai_summary_text)
                )
                if tg_result["success"]:
                    tg_status = "success"
                    tg_detail = "Message sent"
                    logger.info("  Telegram sent OK")
                else:
                    tg_status = "error"
                    tg_detail = tg_result.get("message", "Unknown error")[:300]
                    logger.error(f"  Telegram error: {tg_detail}")
            except Exception as e:
                tg_status = "error"
                tg_detail = str(e)[:300]
                logger.error(f"  Telegram exception: {e}")

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
