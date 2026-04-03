"""
DuckX Newsfeed - Flask Routes (Blueprint)
==========================================
All REST API endpoints and web UI route.
"""

import os
import threading

from flask import Blueprint, render_template, request, jsonify

import config_manager
from pipeline import run_fetch_for_watchlist, run_all_watchlists, retry_execution_steps
from scheduler_manager import scheduler, rebuild_scheduler
from telegram_sender import test_connection

bp = Blueprint("main", __name__)


@bp.route("/")
def index():
    return render_template("index.html")


# ── Dashboard ──

@bp.route("/api/stats")
def api_stats():
    stats = config_manager.get_dashboard_stats()
    jobs = [j for j in scheduler.get_jobs() if j.id.startswith("wl_")]
    all_tg_targets = len(config_manager.get_cached_telegram_targets())

    if jobs:
        next_runs = [j.next_run_time for j in jobs if j.next_run_time]
        stats["next_run"] = min(next_runs).strftime("%H:%M:%S") if next_runs else "N/A"
    else:
        stats["next_run"] = "No jobs"

    active_jobs_list = []
    for wl in config_manager.get_watchlists():
        if not wl.get("enabled", True):
            continue
        wl_targets = wl.get("telegram_targets", [])
        tg_count = len(wl_targets) if wl_targets else all_tg_targets
        for t in wl.get("schedule_times", []):
            active_jobs_list.append({
                "time": t,
                "wl_name": wl.get("name", "Unknown"),
                "accounts_count": len(wl.get("accounts", [])),
                "tg_targets_count": tg_count,
            })
    active_jobs_list.sort(key=lambda x: x["time"])

    stats["active_jobs"] = len(jobs)
    stats["active_jobs_list"] = active_jobs_list
    return jsonify(stats)


@bp.route("/api/execution-log", methods=["GET"])
def api_execution_log():
    return jsonify({"log": config_manager.get_execution_log()})


@bp.route("/api/execution-log", methods=["DELETE"])
def api_clear_execution_log():
    config_manager.delete_execution_log()
    return jsonify({"success": True, "message": "Da xoa tat ca log"})


@bp.route("/api/execution-log/<int:index>", methods=["DELETE"])
def api_delete_execution_entry(index):
    config_manager.delete_execution_log(index)
    return jsonify({"success": True, "message": "Da xoa ban ghi"})


@bp.route("/api/execution-log/<exec_id>/retry", methods=["POST"])
def api_retry_execution(exec_id):
    thread = threading.Thread(target=retry_execution_steps, args=[exec_id], daemon=False)
    thread.start()
    return jsonify({"success": True, "message": "Retry started..."})


@bp.route("/api/execution-log/bulk-delete", methods=["POST"])
def api_bulk_delete_execution_logs():
    data = request.get_json() or {}
    indices = data.get("indices", [])
    if indices:
        config_manager.delete_multiple_execution_logs(indices)
    return jsonify({"success": True, "message": f"Da xoa {len(indices)} ban ghi"})


@bp.route("/api/reset-sync", methods=["POST"])
def api_reset_sync():
    config_manager.reset_all_since_ids()
    return jsonify({"success": True, "message": "Da reset lich su sync"})


# ── Watchlist CRUD ──

@bp.route("/api/watchlists", methods=["GET"])
def api_get_watchlists():
    return jsonify({"watchlists": config_manager.get_watchlists()})


@bp.route("/api/watchlists", methods=["POST"])
def api_create_watchlist():
    data = request.get_json()
    name = data.get("name", "").strip()
    if not name:
        return jsonify({"success": False, "message": "Ten watchlist khong duoc trong"})
    wl = config_manager.create_watchlist(name)
    rebuild_scheduler()
    return jsonify({"success": True, "watchlist": wl})


@bp.route("/api/watchlists/<wl_id>", methods=["PUT"])
def api_update_watchlist(wl_id):
    data = request.get_json()
    if config_manager.update_watchlist(wl_id, data):
        rebuild_scheduler()
        return jsonify({"success": True, "message": "Da cap nhat"})
    return jsonify({"success": False, "message": "Watchlist khong ton tai"})


@bp.route("/api/watchlists/<wl_id>/refresh-user-cache", methods=["POST"])
def api_refresh_user_cache(wl_id):
    """Xoa cache user ID cho watchlist nay, buoc fetch lan tiep theo se lookup lai X API."""
    wl = config_manager.get_watchlist_by_id(wl_id)
    if not wl:
        return jsonify({"success": False, "message": "Watchlist không tồn tại"})
    accounts = wl.get("accounts", [])
    config_manager.clear_user_id_cache(accounts)
    return jsonify({"success": True, "message": f"Đã xoá cache cho {len(accounts)} accounts. Sẽ refresh lần chạy tiếp theo."})


@bp.route("/api/watchlists/<wl_id>/duplicate", methods=["POST"])
def api_duplicate_watchlist(wl_id):
    wl = config_manager.duplicate_watchlist(wl_id)
    if wl:
        rebuild_scheduler()
        return jsonify({"success": True, "watchlist": wl})
    return jsonify({"success": False, "message": "Watchlist khong ton tai"})


@bp.route("/api/watchlists/<wl_id>", methods=["DELETE"])
def api_delete_watchlist(wl_id):
    if config_manager.delete_watchlist(wl_id):
        rebuild_scheduler()
        return jsonify({"success": True, "message": "Da xoa"})
    return jsonify({"success": False, "message": "Khong tim thay"})


# ── Accounts ──

@bp.route("/api/watchlists/<wl_id>/accounts", methods=["POST"])
def api_add_account(wl_id):
    data = request.get_json()
    username = data.get("username", "")
    if config_manager.add_account(wl_id, username):
        return jsonify({"success": True, "message": f"Da them @{username}"})
    return jsonify({"success": False, "message": f"@{username} da ton tai hoac khong hop le"})


@bp.route("/api/watchlists/<wl_id>/accounts/<username>", methods=["DELETE"])
def api_remove_account(wl_id, username):
    if config_manager.remove_account(wl_id, username):
        return jsonify({"success": True, "message": f"Da xoa @{username}"})
    return jsonify({"success": False, "message": f"Khong tim thay @{username}"})


# ── Actions ──

@bp.route("/api/run-now", methods=["POST"])
def api_run_now():
    data = request.get_json(silent=True) or {}
    wl_id = data.get("wl_id")
    if wl_id:
        thread = threading.Thread(target=run_fetch_for_watchlist, args=[wl_id], daemon=False)
    else:
        thread = threading.Thread(target=run_all_watchlists, daemon=False)
    thread.start()
    return jsonify({"success": True, "message": "Dang chay..."})


@bp.route("/api/test-telegram", methods=["POST"])
def api_test_telegram():
    return jsonify(test_connection())


@bp.route("/api/ai-models")
def api_ai_models():
    models = [
        {"id": mid, "label": info["label"], "configured": bool(os.getenv(info["env_key"], ""))}
        for mid, info in config_manager.AI_MODELS.items()
    ]
    return jsonify({"models": models})


@bp.route("/api/telegram-targets")
def api_telegram_targets():
    return jsonify({"targets": config_manager.get_cached_telegram_targets()})
