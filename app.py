"""
DuckX Newsfeed - Application Entry Point
==========================================
Starts the Flask web server with APScheduler.

Usage:
  python app.py              # Default: http://127.0.0.1:5000
  python app.py --port 8080  # Custom port
"""

import os
import sys
import signal
import logging
import argparse
import threading

from flask import Flask
from dotenv import load_dotenv

import config_manager
from routes import bp
from scheduler_manager import scheduler, rebuild_scheduler

load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.register_blueprint(bp)


def main():
    parser = argparse.ArgumentParser(description="DuckX Newsfeed")
    parser.add_argument("--port", type=int, default=5000)
    parser.add_argument("--host", type=str, default="127.0.0.1")
    args = parser.parse_args()

    rebuild_scheduler()
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
