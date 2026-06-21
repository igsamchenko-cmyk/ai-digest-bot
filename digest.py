"""
digest.py — backward-compat entrypoint and public re-export shim.

Business logic lives in ai_digest/. Stage 5 moved orchestration and marker
logic to ai_digest/digest/service.py (DigestService). This file:

  - Re-exports every public name from ai_digest.* so that external callers
    and the existing test suite can continue to use `import digest`.
  - Provides thin shims for functions that consumed config globals
    (get_rss_news, build_gemini_prompt_from_rss, send_telegram, …).
  - Keeps main() + the scheduler loop here (daemon entry point).
"""

import json  # noqa: F401 — kept for callers that imported json via digest
import os
import sys
import time  # noqa: F401
from datetime import datetime  # noqa: F401 — re-exported for callers

import schedule
from google import genai  # noqa: F401 — re-exported

# ── Telegram layer ────────────────────────────────────────────────────────────
import ai_digest.telegram.client as _tg_client

# ── AI layer ──────────────────────────────────────────────────────────────────
from ai_digest.ai.gemini_client import (
    gemini_call,  # noqa: F401
    gemini_model_candidates,  # noqa: F401
)
from ai_digest.ai.parser import (
    attach_links,  # noqa: F401
    parse_gemini_response,  # noqa: F401
)
from ai_digest.ai.prompts import build_gemini_prompt_from_rss as _build_prompt

# ── Config ────────────────────────────────────────────────────────────────────
from ai_digest.config import AppConfig

# ── Digest service (Stage 5) ──────────────────────────────────────────────────
from ai_digest.digest.service import DigestService
from ai_digest.digest.service import run_digest_service as _run_digest_service

# ── Sources layer ─────────────────────────────────────────────────────────────
from ai_digest.sources.collector import (
    fetch_feed,  # noqa: F401
    item_sort_time,  # noqa: F401
)
from ai_digest.sources.collector import get_rss_news as _get_rss_news
from ai_digest.sources.feeds import (
    UA_FEEDS,  # noqa: F401
    google_news_url,  # noqa: F401
    parse_feed_datetime,  # noqa: F401
    parse_feed_items,  # noqa: F401
    world_rss_queries,  # noqa: F401
)
from ai_digest.sources.filters import (
    AI_PATTERN,  # noqa: F401
    normalize_title,  # noqa: F401
)
from ai_digest.telegram.client import resolve_telegram_chat_id as _tg_resolve
from ai_digest.telegram.client import send_telegram as _tg_send
from ai_digest.telegram.formatter import (
    KYIV_TZ,  # noqa: F401
    build_gemini_message,  # noqa: F401
    build_rss_message,  # noqa: F401
    date_labels,  # noqa: F401
    escape_attr,  # noqa: F401
    escape_text,  # noqa: F401
)
from ai_digest.telegram.splitter import (
    TELEGRAM_LIMIT,  # noqa: F401
    split_message,  # noqa: F401
)

# ── Module-level config ───────────────────────────────────────────────────────
_config = AppConfig.from_env()

NEWS_COUNT = _config.news_count
NEWS_LOOKBACK_HOURS = _config.news_lookback_hours
GEMINI_API_KEY = _config.gemini_api_key
TELEGRAM_BOT_TOKEN = _config.telegram_bot_token
TELEGRAM_CHAT_ID = _config.telegram_chat_id
SEND_MARKER_PATH = _config.send_marker_path

# ── AI shim ───────────────────────────────────────────────────────────────────


def build_gemini_prompt_from_rss(items, today_en, nl):
    """Shim: forwards to ai_digest.ai.prompts with config defaults."""
    return _build_prompt(
        items,
        today_en,
        nl,
        news_lookback_hours=NEWS_LOOKBACK_HOURS,
        news_count=NEWS_COUNT,
    )


# ── Sources shim ──────────────────────────────────────────────────────────────


def get_rss_news():
    """Shim: forwards to collector with config defaults."""
    return _get_rss_news(
        news_lookback_hours=NEWS_LOOKBACK_HOURS,
        news_count=NEWS_COUNT,
    )


# ── Telegram shims ────────────────────────────────────────────────────────────

_CHAT_ID_CACHE = None  # kept for test setUp compatibility; real cache in client.py


def resolve_telegram_chat_id():
    """Shim: sync test cache reset, then delegate."""
    _tg_client._CHAT_ID_CACHE = _CHAT_ID_CACHE
    return _tg_resolve(token=TELEGRAM_BOT_TOKEN, chat_id=TELEGRAM_CHAT_ID)


def send_telegram(text):
    """Shim: delegate to client with config credentials."""
    _tg_send(text, token=TELEGRAM_BOT_TOKEN, chat_id=TELEGRAM_CHAT_ID)


# ── Marker shims (delegate to DigestService) ──────────────────────────────────


def enforcing_window():
    return DigestService(_config).enforcing_window()


def read_send_marker():
    return DigestService(_config).read_send_marker()


def mark_sent_if_enforcing(now):
    DigestService(_config).mark_sent_if_enforcing(now)


def should_skip_scheduled_run(now):
    return DigestService(_config).should_skip_scheduled_run(now)


# ── Orchestration shim ────────────────────────────────────────────────────────


def run_digest():
    """Shim: delegate one digest cycle to DigestService."""
    _run_digest_service(_config)


# ── Daemon entry point ────────────────────────────────────────────────────────


def main():
    run_once = os.environ.get("RUN_ONCE", "").lower() == "true" or "--run-once" in sys.argv
    if run_once:
        print("Running in one-shot mode...")
        run_digest()
        print("One-shot run complete.")
        return
    send_time = _config.send_time
    print(f"Starting in scheduler mode. Daily digest time: {send_time}")
    try:
        send_telegram(
            f"✅ Бот запущено в режимі демона. Дайджест надходитиме щодня о {escape_text(send_time)}."
        )
    except Exception as exc:
        print(f"Startup Telegram notification failed: {exc}")
    schedule.every().day.at(send_time).do(run_digest)
    while True:
        schedule.run_pending()
        time.sleep(30)


if __name__ == "__main__":
    main()
