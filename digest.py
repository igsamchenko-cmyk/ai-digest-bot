"""
digest.py — backward-compat shim.

Business logic lives in ai_digest/. All public names are re-exported here so
that existing callers and tests importing `digest` continue to work.
Stage 5 will migrate DigestService and orchestration into ai_digest/.
"""

import json
import os
import sys
import time

import schedule
from google import genai
from google.genai import types

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

# ── Telegram layer (re-exported for backward compat) ──────────────────────────
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

# ── Config ────────────────────────────────────────────────────────────────────
# Module-level names kept so tests can do `patch.object(digest, "TELEGRAM_BOT_TOKEN", ...)`
_config = AppConfig.from_env()

NEWS_COUNT = _config.news_count
NEWS_LOOKBACK_HOURS = _config.news_lookback_hours
GEMINI_API_KEY = _config.gemini_api_key
TELEGRAM_BOT_TOKEN = _config.telegram_bot_token
TELEGRAM_CHAT_ID = _config.telegram_chat_id
SEND_MARKER_PATH = _config.send_marker_path


# ── Sources shim ──────────────────────────────────────────────────────────────


def get_rss_news():
    """Shim: delegates to collector with module-level config values."""
    return _get_rss_news(
        news_lookback_hours=NEWS_LOOKBACK_HOURS,
        news_count=NEWS_COUNT,
    )


# ── Telegram shims ────────────────────────────────────────────────────────────
# Wrappers read module-level TELEGRAM_* at call time so patch.object still works.

import ai_digest.telegram.client as _tg_client  # noqa: E402

_CHAT_ID_CACHE = None  # kept for setUp compatibility; real cache lives in client.py


def resolve_telegram_chat_id():
    _tg_client._CHAT_ID_CACHE = _CHAT_ID_CACHE  # sync reset from tests
    return _tg_resolve(token=TELEGRAM_BOT_TOKEN, chat_id=TELEGRAM_CHAT_ID)


def send_telegram(text):
    _tg_send(text, token=TELEGRAM_BOT_TOKEN, chat_id=TELEGRAM_CHAT_ID)


# ── Gemini ────────────────────────────────────────────────────────────────────


def gemini_model_candidates():
    configured = os.environ.get("GEMINI_MODEL", "").strip()
    candidates = [
        configured,
        "gemini-2.5-flash-lite",
        "gemini-2.5-flash",
        "gemini-2.0-flash-lite",
        "gemini-2.0-flash",
    ]
    result = []
    for model in candidates:
        if model and model not in result:
            result.append(model)
    return result


def gemini_call(client, contents, use_search=False, json_mode=False, max_retries=3):
    config_kwargs = {}
    if use_search:
        config_kwargs["tools"] = [types.Tool(google_search=types.GoogleSearch())]
    if json_mode and not use_search:
        config_kwargs["response_mime_type"] = "application/json"
    config = types.GenerateContentConfig(**config_kwargs) if config_kwargs else None

    last_error = None
    for model in gemini_model_candidates():
        print("Trying Gemini model: " + model)
        for attempt in range(max_retries):
            try:
                kwargs = {"model": model, "contents": contents}
                if config:
                    kwargs["config"] = config
                response = client.models.generate_content(**kwargs)
                print("Gemini model succeeded: " + model)
                return response
            except Exception as e:
                err = str(e)
                last_error = e
                if "limit: 0" in err or "limit of 0" in err:
                    print("Gemini model has 0 quota, trying next model: " + model)
                    break
                if "429" in err or "RESOURCE_EXHAUSTED" in err:
                    wait = 5 * (2**attempt)
                    print(
                        f"Rate limit on {model}. Waiting {wait}s"
                        f" (attempt {attempt + 1}/{max_retries})..."
                    )
                    time.sleep(wait)
                else:
                    raise
    raise RuntimeError("Gemini: all model candidates failed; last error: " + str(last_error))


def build_gemini_prompt_from_rss(items, today_en, nl):
    categories = "LLM|Продукти|Дослідження|Компанії|Агенти|Безпека"
    news_lines = []
    for i, item in enumerate(items, 1):
        published = item.get("published_at")
        published_text = published.isoformat() if published else "unknown"
        news_lines.append(
            str(i)
            + ". Title: "
            + str(item.get("title", ""))
            + nl
            + "Source: "
            + str(item.get("source", ""))
            + nl
            + "Language: "
            + str(item.get("lang", "en"))
            + nl
            + "Published: "
            + published_text
        )
    return (
        "You are a Ukrainian AI news editor. Today is "
        + today_en
        + "."
        + nl
        + "Below is a numbered list of news items from the last "
        + str(NEWS_LOOKBACK_HOURS)
        + " hours. Select the "
        + str(min(NEWS_COUNT, len(items)))
        + " most relevant, fresh, non-duplicate AI news items. Prioritize model releases, major"
        " product launches, benchmarks, and competitive moves by OpenAI, Anthropic,"
        " Google/Gemini, Meta/Llama, Mistral, DeepSeek, Qwen, xAI/Grok, Microsoft, Perplexity."
        + nl
        + "When two items cover the same story, prefer the one with Language: uk (Ukrainian source)."
        + nl
        + "Reject evergreen articles, explainers, old announcements, and rumors without substance."
        + nl
        + "Translate titles to Ukrainian and write concise summaries in Ukrainian."
        + nl
        + 'Return ONLY valid JSON (no markdown). The "id" field MUST be the exact number of the'
        " item in the list below — never invent it:"
        + nl
        + '{"summary":"2-3 sentence overview in Ukrainian","news":['
        + nl
        + '{"id":1,"title":"заголовок українською","category":"'
        + categories
        + '",'
        + '"importance":"high|medium|low","summary":"2-3 sentences in Ukrainian",'
        + '"why_matters":"1 sentence in Ukrainian"}]}'
        + nl
        + "NEWS LIST:"
        + nl
        + (nl + nl).join(news_lines)
    )


def attach_links(data, items):
    """Attach real URLs by id — Gemini never generates URLs itself."""
    enriched = []
    for n in data.get("news", []):
        try:
            idx = int(n.get("id", 0)) - 1
        except (TypeError, ValueError):
            continue
        if 0 <= idx < len(items):
            n["link"] = items[idx]["link"]
            n["source"] = items[idx]["source"]
            enriched.append(n)
    if not enriched:
        raise RuntimeError("Gemini response had no valid item ids")
    data["news"] = enriched
    return data


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
    now = KYIV_TZ and __import__("datetime").datetime.now(KYIV_TZ)
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
            raw = (resp.text or "").replace("```json", "").replace("```", "").strip()
            data = attach_links(json.loads(raw), items)
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
        print(f"Fallback also failed: {err}")
        send_telegram(
            "⚠️ <b>Помилка:</b> Не вдалося завантажити новини ні через Gemini, ні через RSS."
        )


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
