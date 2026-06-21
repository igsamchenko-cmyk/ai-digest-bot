"""Unified CLI entry point for the AI Digest Bot.

All three invocation styles delegate here:

    python digest.py [--run-once]        → digest.main()  → cli.main()
    python -m ai_digest [--run-once]     → __main__.main() → cli.main()
    ai-digest [--run-once]               → cli.main()  (project.scripts)

Keeping the logic in one place means --run-once, RUN_ONCE=true, and the
scheduler loop behave identically regardless of how the bot is started.
"""

from __future__ import annotations

import os
import sys
import time

import schedule

from ai_digest.config import AppConfig
from ai_digest.digest.service import run_digest_service
from ai_digest.telegram.client import send_telegram
from ai_digest.telegram.formatter import escape_text


def main() -> None:
    """Parse CLI flags, then either run once or start the daily scheduler."""
    config = AppConfig.from_env()
    run_once = os.environ.get("RUN_ONCE", "").lower() == "true" or "--run-once" in sys.argv
    if run_once:
        print("Running in one-shot mode...")
        run_digest_service(config)
        print("One-shot run complete.")
        return

    send_time = config.send_time
    print(f"Starting in scheduler mode. Daily digest time: {send_time}")
    try:
        send_telegram(
            "✅ Бот запущено в режимі демона. "
            f"Дайджест надходитиме щодня о {escape_text(send_time)}.",
            token=config.telegram_bot_token,
            chat_id=config.telegram_chat_id,
        )
    except Exception as exc:
        print(f"Startup Telegram notification failed: {exc}")

    schedule.every().day.at(send_time).do(run_digest_service, config)
    while True:
        schedule.run_pending()
        time.sleep(30)
