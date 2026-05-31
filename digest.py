import html
import json
import os
import sys
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import requests
import schedule
from google import genai
from google.genai import types


try:
    KYIV_TZ = ZoneInfo("Europe/Kyiv")
except ZoneInfoNotFoundError:
    KYIV_TZ = timezone(timedelta(hours=3), name="Europe/Kyiv")

TELEGRAM_LIMIT = 3900


def load_env_manually():
    try:
        env_path = ".env"
        if not os.path.exists(env_path):
            script_dir = os.path.dirname(os.path.abspath(__file__))
            env_path = os.path.join(script_dir, ".env")

        if os.path.exists(env_path):
            with open(env_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        key, val = line.split("=", 1)
                        os.environ.setdefault(key.strip(), val.strip().strip("\"'"))
    except Exception as e:
        print(f"Warning: Failed to load .env file: {e}")


load_env_manually()

NEWS_COUNT = int(os.environ.get("NEWS_COUNT", "5"))
TOPIC = os.environ.get(
    "DIGEST_TOPIC",
    "artificial intelligence, LLM models, AI companies, machine learning, new AI releases",
)
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY", "")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")


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


def escape_text(value):
    return html.escape(str(value or ""), quote=False)


def escape_attr(value):
    return html.escape(str(value or ""), quote=True)


def require_telegram_config():
    if not TELEGRAM_BOT_TOKEN:
        raise RuntimeError("Missing required environment variable: TELEGRAM_BOT_TOKEN")


def resolve_telegram_chat_id():
    if TELEGRAM_CHAT_ID:
        return TELEGRAM_CHAT_ID

    require_telegram_config()
    url = "https://api.telegram.org/bot" + TELEGRAM_BOT_TOKEN + "/getUpdates"
    response = requests.get(url, timeout=30)
    response.raise_for_status()
    data = response.json()
    if not data.get("ok"):
        raise RuntimeError("Telegram getUpdates failed: " + str(data))

    for update in reversed(data.get("result", [])):
        message = update.get("message") or update.get("edited_message") or update.get("channel_post")
        if not message:
            continue
        chat = message.get("chat", {})
        chat_id = chat.get("id")
        if chat_id:
            resolved = str(chat_id)
            print("Resolved TELEGRAM_CHAT_ID from getUpdates: " + resolved)
            return resolved

    raise RuntimeError(
        "TELEGRAM_CHAT_ID is not set and getUpdates has no messages. "
        "Open your Telegram bot, send /start or any message, then re-run the workflow."
    )


def split_message(text, limit=TELEGRAM_LIMIT):
    if len(text) <= limit:
        return [text]

    chunks = []
    current = []
    current_len = 0
    for paragraph in text.split("\n\n"):
        block = paragraph if not current else "\n\n" + paragraph
        if current and current_len + len(block) > limit:
            chunks.append("".join(current))
            current = [paragraph]
            current_len = len(paragraph)
        elif len(paragraph) > limit:
            if current:
                chunks.append("".join(current))
                current = []
                current_len = 0
            for i in range(0, len(paragraph), limit):
                chunks.append(paragraph[i : i + limit])
        else:
            current.append(block)
            current_len += len(block)

    if current:
        chunks.append("".join(current))
    return chunks


def send_telegram(text):
    chat_id = resolve_telegram_chat_id()
    url = "https://api.telegram.org/bot" + TELEGRAM_BOT_TOKEN + "/sendMessage"
    for part in split_message(text):
        requests.post(
            url,
            json={
                "chat_id": chat_id,
                "text": part,
                "parse_mode": "HTML",
                "disable_web_page_preview": True,
            },
            timeout=30,
        ).raise_for_status()


def gemini_call(client, contents, use_search=False, max_retries=3):
    config = None
    if use_search:
        config = types.GenerateContentConfig(
            tools=[types.Tool(google_search=types.GoogleSearch())]
        )

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
                    print(f"Rate limit on {model}. Waiting {wait}s (attempt {attempt + 1}/{max_retries})...")
                    time.sleep(wait)
                else:
                    raise

    raise RuntimeError("Gemini: all model candidates failed; last error: " + str(last_error))


def get_rss_news():
    print("Fetching news from Google News RSS feed...")
    url = "https://news.google.com/rss/search?q=ChatGPT+OR+Claude+OR+Gemini+OR+OpenAI+OR+Copilot+OR+Google+AI&hl=uk&gl=UA&ceid=UA:uk"
    response = requests.get(url, timeout=30)
    response.raise_for_status()

    root = ET.fromstring(response.content)
    items = []
    seen_links = set()
    for item in root.findall(".//item"):
        title_elem = item.find("title")
        link_elem = item.find("link")
        if title_elem is None or link_elem is None or not title_elem.text or not link_elem.text:
            continue

        link = link_elem.text
        if link in seen_links:
            continue
        seen_links.add(link)

        source_elem = item.find("source")
        source = source_elem.text if source_elem is not None and source_elem.text else "Google News"
        items.append({"title": title_elem.text, "link": link, "source": source})
        if len(items) >= 10:
            break
    return items


def should_skip_scheduled_run(now):
    if os.environ.get("ENFORCE_KYIV_HOUR", "").lower() != "true":
        return False
    target_hour = int(os.environ.get("TARGET_KYIV_HOUR", "8"))
    return now.hour != target_hour


def build_gemini_prompt(today_en, nl):
    categories = "LLM|Продукти|Дослідження|Компанії|Агенти|Безпека"
    return (
        "You are an AI news curator. Today is " + today_en + "." + nl
        + "1. Use Google Search to find the "
        + str(NEWS_COUNT)
        + " most important AI news from the last 24-48 hours about: "
        + TOPIC
        + nl
        + "2. Return ONLY valid JSON (no markdown):"
        + nl
        + '{"summary":"2-3 sentence overview in Ukrainian","news":['
        + nl
        + '{"title":"title in Ukrainian","category":"'
        + categories
        + '",'
        + nl
        + '"importance":"high|medium|low","summary":"3-4 sentences in Ukrainian",'
        + nl
        + '"source":"source name","why_matters":"1 sentence in Ukrainian"}]}'
    )


def build_gemini_prompt_from_rss(items, today_en, nl):
    categories = "LLM|Продукти|Дослідження|Компанії|Агенти|Безпека"
    news_lines = []
    for i, item in enumerate(items, 1):
        news_lines.append(
            str(i)
            + ". Title: "
            + str(item.get("title", ""))
            + nl
            + "Source: "
            + str(item.get("source", ""))
            + nl
            + "Link: "
            + str(item.get("link", ""))
        )

    return (
        "You are a Ukrainian AI news editor. Today is " + today_en + "." + nl
        + "Below is a Google News RSS list. Select the "
        + str(min(NEWS_COUNT, len(items)))
        + " most relevant and non-duplicate AI news items, translate titles to Ukrainian, and write concise summaries."
        + nl
        + "Return ONLY valid JSON (no markdown):"
        + nl
        + '{"summary":"2-3 sentence overview in Ukrainian","news":['
        + nl
        + '{"title":"title in Ukrainian","category":"'
        + categories
        + '","importance":"high|medium|low","summary":"2-3 sentences in Ukrainian","source":"source name","why_matters":"1 sentence in Ukrainian"}]}'
        + nl
        + "RSS NEWS:"
        + nl
        + (nl + nl).join(news_lines)
    )


def build_gemini_message(data, today_uk):
    importance_icon = {"high": "🔴", "medium": "🟡", "low": "⚪"}
    category_icon = {
        "LLM": "🧠",
        "Продукти": "📦",
        "Дослідження": "🔬",
        "Компанії": "🏢",
        "Агенти": "🤖",
        "Безпека": "🛡️",
    }
    sep = "━" * 19
    lines = [
        "⚡ <b>AI Дайджест</b> · " + escape_text(today_uk),
        sep,
        "<i>" + escape_text(data.get("summary", "")) + "</i>",
        "",
    ]

    for i, item in enumerate(data.get("news", []), 1):
        importance = item.get("importance", "medium")
        category = item.get("category", "")
        lines += [
            importance_icon.get(importance, "⚪")
            + " <b>"
            + str(i)
            + ". "
            + escape_text(item.get("title", ""))
            + "</b>",
            category_icon.get(category, "📌")
            + " <code>"
            + escape_text(category)
            + "</code>  //  "
            + escape_text(item.get("source", "")),
            escape_text(item.get("summary", "")),
            "💡 <i>" + escape_text(item.get("why_matters", "")) + "</i>",
            "",
        ]

    lines += [sep, "🤖 Gemini · Google News RSS"]
    return "\n".join(lines)


def build_rss_message(items, today_uk):
    sep = "━" * 19
    lines = [
        "⚡ <b>AI Дайджест (резервний)</b> · " + escape_text(today_uk),
        sep,
        "<i>Gemini зараз недоступний або ключ не налаштований. Надсилаю свіжі новини з Google News RSS.</i>",
        "",
    ]

    for i, item in enumerate(items, 1):
        lines += [
            f"📰 <b>{i}. {escape_text(item['title'])}</b>",
            f"🔗 <a href=\"{escape_attr(item['link'])}\">Читати на {escape_text(item['source'])}</a>",
            "",
        ]

    lines += [sep, "📡 Google News RSS Feed"]
    return "\n".join(lines)


def date_labels(now):
    months_uk = [
        "січня",
        "лютого",
        "березня",
        "квітня",
        "травня",
        "червня",
        "липня",
        "серпня",
        "вересня",
        "жовтня",
        "листопада",
        "грудня",
    ]
    months_en = [
        "January",
        "February",
        "March",
        "April",
        "May",
        "June",
        "July",
        "August",
        "September",
        "October",
        "November",
        "December",
    ]
    return (
        f"{now.day} {months_uk[now.month - 1]} {now.year}",
        f"{months_en[now.month - 1]} {now.day}, {now.year}",
    )


def run_digest():
    now = datetime.now(KYIV_TZ)
    if should_skip_scheduled_run(now):
        print(f"Skipping scheduled run at Kyiv hour {now.hour}; target is {os.environ.get('TARGET_KYIV_HOUR', '8')}.")
        return

    today_uk, today_en = date_labels(now)
    print("Starting digest for " + today_en + "...")
    send_telegram("⏳ Збираю AI-новини за " + escape_text(today_uk) + "...")

    nl = chr(10)
    items = []
    try:
        items = get_rss_news()
    except Exception as e:
        print(f"RSS fetch failed before Gemini formatting: {e}")

    if not GEMINI_API_KEY:
        print("GEMINI_API_KEY is not set. Sending RSS fallback.")
    else:
        try:
            if not items:
                raise RuntimeError("No RSS items available for Gemini formatting")

            client = genai.Client(api_key=GEMINI_API_KEY)
            resp = gemini_call(client, build_gemini_prompt_from_rss(items, today_en, nl), use_search=False)
            raw = resp.text.replace("```json", "").replace("```", "").strip()

            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                print("Not JSON, reformatting...")
                fmt_prompt = (
                    "Format these AI news into JSON for today "
                    + today_uk
                    + " in Ukrainian."
                    + nl
                    + "NEWS: "
                    + raw
                    + nl
                    + 'Return ONLY: {"summary":"...","news":[{"title":"...","category":"...","importance":"high|medium|low","summary":"...","source":"...","why_matters":"..."}]}'
                )
                fmt = gemini_call(client, fmt_prompt, use_search=False)
                raw2 = fmt.text.replace("```json", "").replace("```", "").strip()
                data = json.loads(raw2)

            send_telegram(build_gemini_message(data, today_uk))
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
            return

        send_telegram(build_rss_message(items, today_uk))
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

    send_time = os.environ.get("SEND_TIME", "08:00")
    print(f"Starting in scheduler mode. Daily digest time: {send_time}")
    try:
        send_telegram(f"✅ Бот запущено в режимі демона. Дайджест надходитиме щодня о {escape_text(send_time)}.")
        print("Startup notification sent successfully.")
    except Exception as e:
        print(f"Startup Telegram notification failed: {e}")

    schedule.every().day.at(send_time).do(run_digest)
    while True:
        schedule.run_pending()
        time.sleep(30)


if __name__ == "__main__":
    main()
