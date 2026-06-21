"""
digest.py — backward-compat shim.

Business logic lives in ai_digest/. All public names are re-exported here so
that existing callers and tests importing `digest` continue to work.
Stage 5 will migrate orchestration (run_digest / main) into ai_digest/.
"""

import json  # noqa: F401 — kept for any callers that imported json via digest
import os
import sys
import time  # noqa: F401
from datetime import datetime

import schedule
from google import genai

# ── Telegram layer (re-exported for backward compat) ──────────────────────────
import ai_digest.telegram.client as _tg_client

# ── AI layer (re-exported for backward compat) ────────────────────────────────
from ai_digest.ai.gemini_client import (
    gemini_call,  # noqa: F401
    gemini_model_candidates,  # noqa: F401
)
from ai_digest.ai.parser import (
    attach_links,  # noqa: F401
    parse_gemini_response,
)
from ai_digest.ai.prompts import build_gemini_prompt_from_rss as _build_prompt

# ── Config ────────────────────────────────────────────────────────────────────
from ai_digest.config import AppConfig

# ── Sources layer (re-exported for backward compat) ───────────────────────────
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

_config = AppConfig.from_env()

NEWS_COUNT = _config.news_count
NEWS_LOOKBACK_HOURS = _config.news_lookback_hours
GEMINI_API_KEY = _config.gemini_api_key
TELEGRAM_BOT_TOKEN = _config.telegram_bot_token
TELEGRAM_CHAT_ID = _config.telegram_chat_id
SEND_MARKER_PATH = _config.send_marker_path


# ── AI shims ──────────────────────────────────────────────────────────────────
# build_gemini_prompt_from_rss needs NEWS_COUNT / NEWS_LOOKBACK_HOURS from config;
# expose as a zero-arg shim so existing call sites in run_digest stay unchanged.


def build_gemini_prompt_from_rss(items, today_en, nl):
    return _build_prompt(
        items,
        today_en,
        nl,
        news_lookback_hours=NEWS_LOOKBACK_HOURS,
        news_count=NEWS_COUNT,
    )


# ── Sources shim ──────────────────────────────────────────────────────────────


def get_rss_news():
    return _get_rss_news(
        news_lookback_hours=NEWS_LOOKBACK_HOURS,
        news_count=NEWS_COUNT,
    )


# ── Telegram shims ────────────────────────────────────────────────────────────

_CHAT_ID_CACHE = None  # kept for setUp compatibility; real cache lives in client.py


def resolve_telegram_chat_id():
    _tg_client._CHAT_ID_CACHE = _CHAT_ID_CACHE
    return _tg_resolve(token=TELEGRAM_BOT_TOKEN, chat_id=TELEGRAM_CHAT_ID)


def send_telegram(text):
    _tg_send(text, token=TELEGRAM_BOT_TOKEN, chat_id=TELEGRAM_CHAT_ID)


# ── Duplicate-send protection ─────────────────────────────────────────────────


def enforcing_window():
    return _config.enforce_kyiv_hour


def read_send_marker():
    try:
        with open(SEND_MARKER_PATH, "r", encoding="utf-8") as f:
            return f.read().strip()
    except OSError:
        return ""


def mark_sent_if_enforcing(now):
    if not enforcing_window():
        return
    try:
        with open(SEND_MARKER_PATH, "w", encoding="utf-8") as f:
            f.write(now.strftime("%Y-%m-%d"))
    except OSError as e:
        print(f"Warning: failed to write send marker: {e}")


def should_skip_scheduled_run(now):
    if not enforcing_window():
        return False
    start = _config.target_kyiv_hour_start
    end = _config.target_kyiv_hour_end
    if not (start <= now.hour <= end):
        print(f"Skipping scheduled run at Kyiv hour {now.hour}; send window is {start}-{end}.")
        return True
    today = now.strftime("%Y-%m-%d")
    if read_send_marker() == today:
        print(f"Skipping scheduled run: digest already sent today ({today}).")
        return True
    return False


# ── Orchestration ─────────────────────────────────────────────────────────────


def run_digest():
    now = datetime.now(KYIV_TZ)
    if should_skip_scheduled_run(now):
        return
    today_uk, today_en = date_labels(now)
    print("Starting digest for " + today_en + "...")
    nl = chr(10)

    items = []
    try:
        items = get_rss_news()
    except Exception as e:
        print(f"RSS fetch failed: {e}")

    if not GEMINI_API_KEY:
        print("GEMINI_API_KEY is not set. Sending RSS fallback.")
    elif items:
        try:
            client = genai.Client(api_key=GEMINI_API_KEY)
            resp = gemini_call(
                client,
                build_gemini_prompt_from_rss(items, today_en, nl),
                json_mode=True,
            )
            data = attach_links(parse_gemini_response(resp.text), items)
            send_telegram(build_gemini_message(data, today_uk))
            mark_sent_if_enforcing(now)
            print("Done via Gemini!")
            return
        except Exception as e:
            print(f"Gemini execution failed: {e}. Falling back to RSS...")

    try:
        if not items:
            send_telegram(
                "☀️ <b>Дайджест новин ШІ</b> · "
                + escape_text(today_uk)
                + "\n\nНе вдалося знайти свіжих новин на даний момент."
            )
            mark_sent_if_enforcing(now)
            return
        send_telegram(build_rss_message(items, today_uk, news_count=NEWS_COUNT))
        mark_sent_if_enforcing(now)
        print("Done via Fallback RSS!")
    except Exception as err:
        print(f"Fallback also failed: {type(err).__name__}: {err}")
        try:
            send_telegram(
                "⚠️ <b>Помилка:</b> Не вдалося завантажити новини ні через Gemini, ні через RSS."
            )
        except Exception as send_err:
            print(f"Error notification also failed: {type(send_err).__name__}")


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
    except Exception as e:
        print(f"Startup Telegram notification failed: {e}")
    schedule.every().day.at(send_time).do(run_digest)
    while True:
        schedule.run_pending()
        time.sleep(30)


if __name__ == "__main__":
    main()
