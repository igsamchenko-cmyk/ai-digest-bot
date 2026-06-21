"""
digest.py — backward-compat shim.

Business logic lives in ai_digest/. All public names are re-exported here so
that existing callers and tests importing `digest` continue to work.
Stages 3-5 will migrate sources, Gemini, and DigestService into ai_digest/.
"""

import json
import os
import re
import sys
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import quote_plus
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import requests
import schedule
from google import genai
from google.genai import types

from ai_digest.config import AppConfig
from ai_digest.telegram.client import resolve_telegram_chat_id as _tg_resolve
from ai_digest.telegram.client import send_telegram as _tg_send
from ai_digest.telegram.formatter import (  # noqa: F401  # noqa: F401
    KYIV_TZ,  # noqa: F401
    build_gemini_message,
    build_rss_message,
    date_labels,  # noqa: F401
    escape_attr,
    escape_text,
)
from ai_digest.telegram.splitter import (
    TELEGRAM_LIMIT,  # noqa: F401
    split_message,  # noqa: F401
)

try:
    KYIV_TZ = ZoneInfo("Europe/Kyiv")  # type: ignore[assignment]
except ZoneInfoNotFoundError:
    KYIV_TZ = timezone(timedelta(hours=3), name="Europe/Kyiv")  # type: ignore[assignment]

ATOM_NS = "{http://www.w3.org/2005/Atom}"
HTTP_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; ai-digest-bot/2.0)"}

# ── Config ────────────────────────────────────────────────────────────────────
# Module-level names kept so tests can do `patch.object(digest, "TELEGRAM_BOT_TOKEN", ...)`
_config = AppConfig.from_env()

NEWS_COUNT = _config.news_count
NEWS_LOOKBACK_HOURS = _config.news_lookback_hours
GEMINI_API_KEY = _config.gemini_api_key
TELEGRAM_BOT_TOKEN = _config.telegram_bot_token
TELEGRAM_CHAT_ID = _config.telegram_chat_id
SEND_MARKER_PATH = _config.send_marker_path

# ── UA feeds & AI filter ──────────────────────────────────────────────────────
UA_FEEDS = {
    "DOU": "https://dou.ua/feed/",
    "AIN.UA": "https://ain.ua/feed/",
    "Mezha.Media": "https://mezha.media/feed/",
    "ITC.ua": "https://itc.ua/feed/",
    "dev.ua": "https://dev.ua/rss",
    "SPEKA": "https://speka.media/feed",
}

AI_PATTERN = re.compile(
    r"(штучн\w*\s+інтелект|нейромереж|нейронн\w*\s+мереж|машинн\w*\s+навчанн"
    r"|\bші\b|\bai\b|openai|chatgpt|\bgpt-?[45o\d]|anthropic|claude|gemini|deepmind"
    r"|\bllm\b|copilot|midjourney|mistral|deepseek|\bgrok\b|\bxai\b|perplexity"
    r"|llama|qwen|stable diffusion|hugging face)",
    re.IGNORECASE,
)


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


# ── Telegram shims ────────────────────────────────────────────────────────────
# Wrappers read module-level TELEGRAM_* at call time, so patch.object still works.

_CHAT_ID_CACHE = None  # kept for setUp compatibility; real cache lives in client.py


def resolve_telegram_chat_id():
    import ai_digest.telegram.client as _client

    _client._CHAT_ID_CACHE = _CHAT_ID_CACHE  # sync reset from tests
    result = _tg_resolve(token=TELEGRAM_BOT_TOKEN, chat_id=TELEGRAM_CHAT_ID)
    return result


def send_telegram(text):
    _tg_send(text, token=TELEGRAM_BOT_TOKEN, chat_id=TELEGRAM_CHAT_ID)


# ── Gemini ────────────────────────────────────────────────────────────────────


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


# ── News collection ───────────────────────────────────────────────────────────


def world_rss_queries():
    return [
        '("AI model" OR "language model" OR LLM) (released OR launches OR announced OR update OR benchmark) when:3d',
        "(OpenAI OR ChatGPT OR GPT) (model OR release OR update OR launch) when:3d",
        "(Anthropic OR Claude) (model OR release OR update OR launch OR benchmark) when:3d",
        "(Google OR Gemini OR DeepMind) (AI model OR release OR update OR launch) when:3d",
        "(Meta OR Llama OR Mistral OR DeepSeek OR Qwen OR xAI OR Grok) (model OR release OR update OR launch) when:3d",
        '(Microsoft Copilot OR Perplexity OR "AI agent" OR "coding agent") (release OR update OR launch) when:3d',
    ]


def google_news_url(query, lang="en"):
    encoded = quote_plus(query)
    if lang == "uk":
        return f"https://news.google.com/rss/search?q={encoded}&hl=uk&gl=UA&ceid=UA:uk"
    return f"https://news.google.com/rss/search?q={encoded}&hl=en-US&gl=US&ceid=US:en"


def parse_feed_datetime(value):
    if not value:
        return None
    parsed = None
    try:
        parsed = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        try:
            parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except (TypeError, ValueError):
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def parse_feed_items(content, default_source):
    """Parse RSS 2.0 and Atom. Returns list of dicts."""
    items = []
    try:
        root = ET.fromstring(content)
    except ET.ParseError as e:
        print(f"Feed parse error ({default_source}): {e}")
        return items
    for item in root.findall(".//item"):
        title = item.findtext("title")
        link = item.findtext("link")
        if not title or not link:
            continue
        source = item.findtext("source") or default_source
        items.append(
            {
                "title": title.strip(),
                "link": link.strip(),
                "source": source.strip(),
                "published_at": parse_feed_datetime(item.findtext("pubDate")),
            }
        )
    for entry in root.findall(f".//{ATOM_NS}entry"):
        title = entry.findtext(f"{ATOM_NS}title")
        link_el = entry.find(f"{ATOM_NS}link")
        link = link_el.get("href") if link_el is not None else None
        if not title or not link:
            continue
        published = entry.findtext(f"{ATOM_NS}published") or entry.findtext(f"{ATOM_NS}updated")
        items.append(
            {
                "title": title.strip(),
                "link": link.strip(),
                "source": default_source,
                "published_at": parse_feed_datetime(published),
            }
        )
    return items


def normalize_title(title):
    words = re.findall(r"\w+", (title or "").lower())
    return " ".join(words[:10])


def item_sort_time(item):
    return item.get("published_at") or datetime.min.replace(tzinfo=timezone.utc)


def fetch_feed(url, default_source):
    try:
        response = requests.get(url, timeout=30, headers=HTTP_HEADERS)
        response.raise_for_status()
    except requests.RequestException as e:
        print(f"Feed failed ({default_source}): {e}")
        return []
    return parse_feed_items(response.content, default_source)


def get_rss_news():
    """Collect news: UA sources first, then global (Google News)."""
    print("Fetching news (UA feeds + Google News)...")
    cutoff = datetime.now(timezone.utc) - timedelta(hours=NEWS_LOOKBACK_HOURS)
    seen_links = set()
    seen_titles = set()
    ua_items = []
    world_items = []

    def add(raw_items, bucket, lang, require_keywords=False, require_date=False):
        for it in raw_items:
            published = it.get("published_at")
            if require_date and not published:
                continue
            if published and published < cutoff:
                continue
            if require_keywords and not AI_PATTERN.search(it["title"]):
                continue
            title_key = normalize_title(it["title"])
            if it["link"] in seen_links or title_key in seen_titles:
                continue
            seen_links.add(it["link"])
            seen_titles.add(title_key)
            it["lang"] = lang
            bucket.append(it)

    for source, url in UA_FEEDS.items():
        add(fetch_feed(url, source), ua_items, "uk", require_keywords=True, require_date=True)

    for query in ["штучний інтелект when:3d", "OpenAI OR ChatGPT OR Gemini OR Claude when:3d"]:
        add(fetch_feed(google_news_url(query, "uk"), "Google News UA"), ua_items, "uk")

    for query in world_rss_queries():
        add(fetch_feed(google_news_url(query, "en"), "Google News"), world_items, "en")

    ua_items.sort(key=item_sort_time, reverse=True)
    world_items.sort(key=item_sort_time, reverse=True)
    items = ua_items + world_items
    print(
        f"Found {len(ua_items)} UA + {len(world_items)} world items (last {NEWS_LOOKBACK_HOURS}h)."
    )
    return items[: max(NEWS_COUNT * 4, 12)]


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


# ── Gemini: select & translate news ──────────────────────────────────────────


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
