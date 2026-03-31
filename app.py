"""
DuckX Newsfeed - Flask Web Server + Scheduler
===============================================
Per-watchlist scheduling with fixed UTC+7 time slots.

Usage:
  python app.py              # Run app (web UI + scheduler)
  python app.py --port 5000  # Custom port
"""

import os
import sys
import signal
import logging
import argparse
import time
import threading
from datetime import datetime, timedelta, timezone

from flask import Flask, render_template, request, jsonify
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from dotenv import load_dotenv
import pytz

import config_manager
from x_api import XApiClient, tweets_to_text
from ai_summarizer import summarize_tweets
from telegram_sender import send_message, send_message_to_targets, test_connection

# Load .env
load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

# UTC+7 timezone
TZ_VN = pytz.timezone("Asia/Ho_Chi_Minh")

# Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

# Flask app
app = Flask(__name__)
scheduler = BackgroundScheduler(timezone=TZ_VN)
# Per-watchlist locks: prevents same watchlist from running twice, but allows different watchlists concurrently
_wl_locks = {}
_wl_locks_guard = threading.Lock()


# ─────────────────────────────────────────────────
# Core: Fetch → Summarize → Send (per watchlist)
# ─────────────────────────────────────────────────

def create_x_client():
    return XApiClient(
        api_key=os.getenv("X_API_KEY", ""),
        api_secret=os.getenv("X_API_SECRET", ""),
        access_token=os.getenv("X_ACCESS_TOKEN", ""),
        access_token_secret=os.getenv("X_ACCESS_TOKEN_SECRET", ""),
    )


def _get_wl_lock(wl_id: str) -> threading.Lock:
    """Get or create a per-watchlist lock."""
    with _wl_locks_guard:
        if wl_id not in _wl_locks:
            _wl_locks[wl_id] = threading.Lock()
        return _wl_locks[wl_id]


def run_fetch_for_watchlist(wl_id: str):
    """Run fetch cycle for a specific watchlist with detailed step tracking."""
    lock = _get_wl_lock(wl_id)
    if not lock.acquire(blocking=False):
        logger.info(f"Watchlist {wl_id} is already running, skipping...")
        return

    # Step tracking
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
            logger.info(f"Watchlist '{wl['name']}' is disabled, skipping")
            return

        accounts = wl.get("accounts", [])
        wl_name = wl["name"]
        ai_model_used = wl.get("ai_model", "gemini_free_1")

        if not accounts:
            logger.info(f"Watchlist '{wl_name}' has no accounts")
            fetch_status = "skipped"
            fetch_detail = "No accounts configured"
            config_manager.record_execution(
                wl_id=wl_id, wl_name=wl_name,
                fetch_status=fetch_status, fetch_detail=fetch_detail,
            )
            return

        logger.info(f"=== FETCH: {wl_name} ({len(accounts)} accounts) ===")

        # ── Step 1: Fetch tweets ──
        try:
            client = create_x_client()
            since_ids = wl.get("since_ids", {})
            max_posts = wl.get("max_posts_per_user", 10)
            result = client.get_watchlist_tweets(
                usernames=accounts,
                max_per_user=max_posts,
                since_ids=since_ids,
            )

            tweets = result["tweets"]
            users_map = result["users_map"]
            errors = result["errors"]

            error_details = []
            for user, err in errors.items():
                logger.error(f"  Error @{user}: {err}")
                error_details.append(f"@{user}: {err}")

            fetch_count = len(tweets)

            if not tweets:
                logger.info(f"  No new tweets for '{wl_name}'")
                fetch_status = "success"
                fetch_detail = "No new tweets"
                if error_details:
                    fetch_status = "error"
                    fetch_detail = "; ".join(error_details)

                config_manager.record_execution(
                    wl_id=wl_id, wl_name=wl_name,
                    fetch_status=fetch_status, fetch_tweet_count=0,
                    fetch_detail=fetch_detail,
                )
                return

            fetch_status = "success"
            fetch_detail = f"Fetched {fetch_count} tweets from {len(accounts)} accounts"
            if error_details:
                fetch_detail += f" (errors: {'; '.join(error_details)})"

            logger.info(f"  Fetched {fetch_count} tweets")

            # Save since_ids
            for username, sid in result["new_since_ids"].items():
                config_manager.set_since_id(wl_id, username, sid)

            # Format tweets
            raw_tweets_text = tweets_to_text(tweets, users_map)

        except Exception as e:
            fetch_status = "error"
            fetch_detail = str(e)[:300]
            logger.error(f"  Fetch error: {e}")
            config_manager.record_execution(
                wl_id=wl_id, wl_name=wl_name,
                fetch_status=fetch_status, fetch_detail=fetch_detail,
            )
            return

        # ── Step 2: AI Summarize (with retry) ──
        ai_failed = False
        try:
            ai_summary_text = summarize_tweets(
                raw_tweets_text,
                wl.get("prompt", ""),
                ai_model_used,
            )

            if ai_summary_text.startswith("[ERROR]"):
                logger.warning(f"  AI Error (1st attempt): {ai_summary_text}")
                logger.info("  Retrying AI in 10s...")
                time.sleep(10)
                ai_summary_text = summarize_tweets(
                    raw_tweets_text,
                    wl.get("prompt", ""),
                    ai_model_used,
                )

                if ai_summary_text.startswith("[ERROR]"):
                    ai_status = "error"
                    ai_detail = ai_summary_text[:300]
                    ai_failed = True
                    logger.error(f"  AI Error (2nd attempt): {ai_summary_text}")
                else:
                    ai_status = "success"
                    ai_detail = f"Summarized {fetch_count} tweets (succeeded on retry)"
                    logger.info(f"  AI Summary OK on retry ({len(ai_summary_text)} chars)")
            else:
                ai_status = "success"
                ai_detail = f"Summarized {fetch_count} tweets"
                logger.info(f"  AI Summary OK ({len(ai_summary_text)} chars)")

        except Exception as e:
            logger.warning(f"  AI exception (1st attempt): {e}")
            logger.info("  Retrying AI in 10s...")
            time.sleep(10)
            try:
                ai_summary_text = summarize_tweets(
                    raw_tweets_text,
                    wl.get("prompt", ""),
                    ai_model_used,
                )
                if ai_summary_text.startswith("[ERROR]"):
                    ai_status = "error"
                    ai_detail = ai_summary_text[:300]
                    ai_failed = True
                    logger.error(f"  AI Error (2nd attempt): {ai_summary_text}")
                else:
                    ai_status = "success"
                    ai_detail = f"Summarized {fetch_count} tweets (succeeded on retry)"
                    logger.info(f"  AI Summary OK on retry ({len(ai_summary_text)} chars)")
            except Exception as e2:
                ai_status = "error"
                ai_detail = str(e2)[:300]
                ai_failed = True
                logger.error(f"  AI exception (2nd attempt): {e2}")

        # ── Step 3: Send to Telegram (skip if AI failed) ──
        if ai_failed:
            tg_status = "skipped"
            tg_detail = "Skipped: AI summarization failed after retry"
            logger.info(f"  Telegram skipped (AI failed)")
        else:
            try:
                now_vn = datetime.now(TZ_VN).strftime("%d/%m/%Y %H:%M")
                header = f"📋 **DuckX Newsfeed: {wl_name}**\n⏰ {now_vn}\n📊 {fetch_count} tweets\n\n"
                # Use watchlist-specific targets if configured, otherwise fall back to global
                wl_targets = wl.get("telegram_targets", [])
                if wl_targets:
                    tg_result = send_message_to_targets(header + ai_summary_text, wl_targets)
                else:
                    tg_result = send_message(header + ai_summary_text)

                if tg_result["success"]:
                    tg_status = "success"
                    tg_detail = "Message sent"
                    logger.info(f"  Telegram sent OK")
                else:
                    tg_status = "error"
                    tg_detail = tg_result.get("message", "Unknown error")[:300]
                    logger.error(f"  Telegram error: {tg_detail}")

            except Exception as e:
                tg_status = "error"
                tg_detail = str(e)[:300]
                logger.error(f"  Telegram exception: {e}")

        # ── Record everything ──
        config_manager.record_execution(
            wl_id=wl_id,
            wl_name=wl_name,
            fetch_status=fetch_status,
            fetch_tweet_count=fetch_count,
            fetch_detail=fetch_detail,
            ai_status=ai_status,
            ai_model=ai_model_used,
            ai_detail=ai_detail,
            telegram_status=tg_status,
            telegram_detail=tg_detail,
            raw_tweets=raw_tweets_text,
            ai_summary=ai_summary_text,
        )
        logger.info(f"=== DONE: {wl_name} ===")

    except Exception as e:
        logger.error(f"Fetch error: {e}", exc_info=True)
    finally:
        lock.release()


def run_all_watchlists():
    """Run fetch for all enabled watchlists (batch mode with 30s delay to avoid Gemini rate limits)."""
    enabled_wls = [wl for wl in config_manager.get_watchlists() if wl.get("enabled", True)]
    total = len(enabled_wls)
    logger.info(f"=== RUN ALL: {total} watchlists (batch mode, 30s interval) ===")

    for i, wl in enumerate(enabled_wls):
        logger.info(f"[{i + 1}/{total}] Running watchlist: {wl['name']}")
        run_fetch_for_watchlist(wl["id"])

        # Wait 30s between watchlists to avoid Gemini free tier rate limit (5 req/min)
        if i < total - 1:
            logger.info(f"Waiting 30s before next watchlist (rate limit protection)...")
            time.sleep(30)

    logger.info(f"=== RUN ALL COMPLETE ===")


# ─────────────────────────────────────────────────
# Scheduler Management
# ─────────────────────────────────────────────────

def rebuild_scheduler():
    """Rebuild all scheduled jobs from config."""
    for job in scheduler.get_jobs():
        if job.id.startswith("wl_"):
            scheduler.remove_job(job.id)

    for wl in config_manager.get_watchlists():
        if not wl.get("enabled", True):
            continue

        schedule_times = wl.get("schedule_times", [])
        if not schedule_times:
            continue

        for t in schedule_times:
            try:
                parts = t.strip().split(":")
                h, m = int(parts[0]), int(parts[1])
                job_id = f"{wl['id']}_{h:02d}{m:02d}"

                scheduler.add_job(
                    run_fetch_for_watchlist,
                    CronTrigger(hour=h, minute=m, timezone=TZ_VN),
                    id=job_id,
                    args=[wl["id"]],
                    name=f"{wl['name']} @ {h:02d}:{m:02d}",
                    replace_existing=True,
                    misfire_grace_time=900,
                )
            except Exception as e:
                logger.error(f"Failed to schedule {wl['name']} @ {t}: {e}")

    if not scheduler.running:
        scheduler.start()

    jobs = [j for j in scheduler.get_jobs() if j.id.startswith("wl_")]
    logger.info(f"Scheduler rebuilt: {len(jobs)} jobs active")


# ─────────────────────────────────────────────────
# Flask Routes
# ─────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html")


# --- Dashboard API ---

@app.route("/api/stats")
def api_stats():
    stats = config_manager.get_dashboard_stats()
    # Next run info
    jobs = [j for j in scheduler.get_jobs() if j.id.startswith("wl_")]
    active_jobs_list = []
    
    # Calculate telegram target total outside loop
    all_tg_targets = len(config_manager.get_cached_telegram_targets())

    if jobs:
        next_runs = [j.next_run_time for j in jobs if j.next_run_time]
        if next_runs:
            nearest = min(next_runs)
            stats["next_run"] = nearest.strftime("%H:%M:%S")
        else:
            stats["next_run"] = "N/A"
    else:
        stats["next_run"] = "No jobs"
        
    for wl in config_manager.get_watchlists():
        if not wl.get("enabled", True):
            continue
            
        acc_count = len(wl.get("accounts", []))
        wl_targets = wl.get("telegram_targets", [])
        # If empty means all targets
        tg_count = len(wl_targets) if wl_targets else all_tg_targets
        
        for t in wl.get("schedule_times", []):
            active_jobs_list.append({
                "time": t,
                "wl_name": wl.get("name", "Unknown"),
                "accounts_count": acc_count,
                "tg_targets_count": tg_count
            })
            
    # Sort by time
    active_jobs_list.sort(key=lambda x: x["time"])
    
    stats["active_jobs"] = len(jobs)
    stats["active_jobs_list"] = active_jobs_list
    
    return jsonify(stats)



@app.route("/api/execution-log", methods=["GET"])
def api_execution_log():
    return jsonify({"log": config_manager.get_execution_log()})


@app.route("/api/execution-log", methods=["DELETE"])
def api_clear_execution_log():
    config_manager.delete_execution_log()
    return jsonify({"success": True, "message": "Da xoa tat ca log"})


@app.route("/api/execution-log/<int:index>", methods=["DELETE"])
def api_delete_execution_entry(index):
    config_manager.delete_execution_log(index)
    return jsonify({"success": True, "message": "Da xoa ban ghi"})


@app.route("/api/execution-log/bulk-delete", methods=["POST"])
def api_bulk_delete_execution_logs():
    data = request.get_json() or {}
    indices = data.get("indices", [])
    if indices:
        config_manager.delete_multiple_execution_logs(indices)
    return jsonify({"success": True, "message": f"Da xoa {len(indices)} ban ghi"})


@app.route("/api/reset-sync", methods=["POST"])
def api_reset_sync():
    config_manager.reset_all_since_ids()
    return jsonify({"success": True, "message": "Da reset lich su sync"})

# --- Watchlist CRUD API ---

@app.route("/api/watchlists", methods=["GET"])
def api_get_watchlists():
    return jsonify({"watchlists": config_manager.get_watchlists()})


@app.route("/api/watchlists", methods=["POST"])
def api_create_watchlist():
    data = request.get_json()
    name = data.get("name", "").strip()
    if not name:
        return jsonify({"success": False, "message": "Ten watchlist khong duoc trong"})
    wl = config_manager.create_watchlist(name)
    rebuild_scheduler()
    return jsonify({"success": True, "watchlist": wl})


@app.route("/api/watchlists/<wl_id>", methods=["PUT"])
def api_update_watchlist(wl_id):
    data = request.get_json()
    if config_manager.update_watchlist(wl_id, data):
        rebuild_scheduler()
        return jsonify({"success": True, "message": "Da cap nhat"})
    return jsonify({"success": False, "message": "Watchlist khong ton tai"})


@app.route("/api/watchlists/<wl_id>", methods=["DELETE"])
def api_delete_watchlist(wl_id):
    if config_manager.delete_watchlist(wl_id):
        rebuild_scheduler()
        return jsonify({"success": True, "message": "Da xoa"})
    return jsonify({"success": False, "message": "Khong tim thay"})


# --- Account API ---

@app.route("/api/watchlists/<wl_id>/accounts", methods=["POST"])
def api_add_account(wl_id):
    data = request.get_json()
    username = data.get("username", "")
    if config_manager.add_account(wl_id, username):
        return jsonify({"success": True, "message": f"Da them @{username}"})
    return jsonify({"success": False, "message": f"@{username} da ton tai hoac khong hop le"})


@app.route("/api/watchlists/<wl_id>/accounts/<username>", methods=["DELETE"])
def api_remove_account(wl_id, username):
    if config_manager.remove_account(wl_id, username):
        return jsonify({"success": True, "message": f"Da xoa @{username}"})
    return jsonify({"success": False, "message": f"Khong tim thay @{username}"})


# --- Actions ---

@app.route("/api/run-now", methods=["POST"])
def api_run_now():
    data = request.get_json(silent=True) or {}
    wl_id = data.get("wl_id")

    if wl_id:
        logger.info(f"[api_run_now] Triggered single watchlist: {wl_id}")
        thread = threading.Thread(target=run_fetch_for_watchlist, args=[wl_id], daemon=False)
    else:
        logger.info("[api_run_now] Triggered RUN ALL (batch mode)")
        thread = threading.Thread(target=run_all_watchlists, daemon=False)
    thread.daemon = False
    thread.start()
    logger.info(f"[api_run_now] Thread started: {thread.name}")
    return jsonify({"success": True, "message": "Dang chay..."})


@app.route("/api/test-telegram", methods=["POST"])
def api_test_telegram():
    return jsonify(test_connection())


@app.route("/api/ai-models")
def api_ai_models():
    models = []
    for mid, info in config_manager.AI_MODELS.items():
        has_key = bool(os.getenv(info["env_key"], ""))
        models.append({"id": mid, "label": info["label"], "configured": has_key})
    return jsonify({"models": models})


@app.route("/api/telegram-targets")
def api_telegram_targets():
    """Return list of Telegram chat IDs from cache for UI display."""
    return jsonify({"targets": config_manager.get_cached_telegram_targets()})


# ─────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="DuckX Newsfeed")
    parser.add_argument("--port", type=int, default=5000)
    parser.add_argument("--host", type=str, default="127.0.0.1")
    args = parser.parse_args()

    rebuild_scheduler()

    # Cập nhật Telegram Targets Cache ở background ngay khi mở app
    threading.Thread(target=config_manager.update_telegram_targets_cache, daemon=True).start()

    wl_count = len(config_manager.get_watchlists())
    jobs = [j for j in scheduler.get_jobs() if j.id.startswith("wl_")]

    print()
    print("=" * 55)
    print("  DuckX Newsfeed")
    print("=" * 55)
    print(f"  Web UI:     http://{args.host}:{args.port}")
    print(f"  Watchlists: {wl_count}")
    print(f"  Jobs:       {len(jobs)} scheduled")
    print(f"  Timezone:   UTC+7 (Asia/Ho_Chi_Minh)")
    print("=" * 55)
    print()

    def graceful_shutdown(signum, frame):
        logger.info("Shutting down gracefully...")
        scheduler.shutdown(wait=False)
        sys.exit(0)

    signal.signal(signal.SIGTERM, graceful_shutdown)
    signal.signal(signal.SIGINT, graceful_shutdown)

    app.run(host=args.host, port=args.port, debug=False, use_reloader=False)


if __name__ == "__main__":
    main()
