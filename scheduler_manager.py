"""
DuckX Newsfeed - Scheduler Manager
=====================================
APScheduler singleton and job management for per-watchlist cron triggers (UTC+7).
"""

import logging

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
import pytz

import config_manager
from pipeline import run_fetch_for_watchlist

logger = logging.getLogger(__name__)

TZ_VN = pytz.timezone("Asia/Ho_Chi_Minh")
scheduler = BackgroundScheduler(timezone=TZ_VN)


def rebuild_scheduler():
    """Rebuild all scheduled jobs from current config."""
    for job in scheduler.get_jobs():
        if job.id.startswith("wl_"):
            scheduler.remove_job(job.id)

    for wl in config_manager.get_watchlists():
        if not wl.get("enabled", True):
            continue
        for t in wl.get("schedule_times", []):
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
