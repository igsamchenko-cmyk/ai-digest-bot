import os, json, requests, time
from datetime import datetime
from google import genai
from google.genai import types

GOOGLE_API_KEY     = os.environ.get("GOOGLE_API_KEY", "")
TELEGRAM_BOT_TOKEN = "8917147406:AAGmWQrdtaGsPMokjcMS2YEf1QYXscfYPpU"
TELEGRAM_CHAT_ID   = "1039798805"
TOPIC      = "artificial intelligence, LLM models, AI companies, machine learning, new AI releases"
NEWS_COUNT = 5

def send_telegram(text):
    url = "https://api.telegram.org/bot" + TELEGRAM_BOT_TOKEN + "/sendMessage"
    requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": text,
        "parse_mode": "HTML", "disable_web_page_preview": True}, timeout=30).raise_for_status()

def gemini_call(client, contents, use_search=False, max_retries=6):
    """Gemini API з retry при 429 (exponential backoff)."""
    config = None
    if use_search:
        config = types.GenerateContentConfig(
            tools=[types.Tool(google_search=types.GoogleSearch())]
        )
    for attempt in range(max_retries):
        try:
            kwargs = {"model": "gemini-2.0-flash", "contents": contents}
            if config:
                kwargs["config"] = config
            return client.models.generate_content(**kwargs)
        except Exception as e:
            err = str(e)
            if "429" in err or "RESOURCE_EXHAUSTED" in err:
                wait = 15 * (2 ** attempt)  # 15, 30, 60, 120, 240, 480 сек
                print("Rate limit. Waiting " + str(wait) + "s (attempt " + str(attempt + 1) + "/" + str(max_retries) + ")...")
                time.sleep(wait)
            else:
                raise
    raise RuntimeError("Gemini: max retries exceeded")

def run():
    if not GOOGLE_API_KEY:
        raise ValueError("GOOGLE_API_KEY is not set!")
    client = genai.Client(api_key=GOOGLE_API_KEY)
    today_uk = datetime.now().strftime("%-d %B %Y")
    today_en = datetime.now().strftime("%B %-d, %Y")
    print("Starting digest for " + today_en + "...")
    send_telegram("Збираю AI-новини за " + today_uk + "...")

    # Один виклик: пошук + форматування JSON разом
    nl = chr(10)
    prompt = (
        "You are an AI news curator. Today is " + today_en + "." + nl +
        "1. Use Google Search to find the " + str(NEWS_COUNT) + " most important AI news from the last 24-48 hours about: " + TOPIC + nl +
        "2. Return ONLY valid JSON (no markdown):" + nl +
        '{"summary":"2-3 sentence overview in Ukrainian","news":[' + nl +
        '{"title":"title in Ukrainian","category":"LLM|Продукти|Дослідження|Компанії|Агенти|Безпека",' + nl +
        '"importance":"high|medium|low","summary":"3-4 sentences in Ukrainian",' + nl +
        '"source":"source name","why_matters":"1 sentence in Ukrainian"}]}'
    )

    resp = gemini_call(client, prompt, use_search=True)
    raw  = resp.text.replace("```json", "").replace("```", "").strip()

    # Якщо Gemini повернув текст а не JSON — другий виклик для форматування
    try:
        d = json.loads(raw)
    except json.JSONDecodeError:
        print("Not JSON, reformatting...")
        fmt_prompt = (
            "Format these AI news into JSON for today " + today_uk + " in Ukrainian." + nl +
            "NEWS: " + raw + nl +
            'Return ONLY: {"summary":"...","news":[{"title":"...","category":"...","importance":"high|medium|low","summary":"...","source":"...","why_matters":"..."}]}'
        )
        fmt  = gemini_call(client, fmt_prompt, use_search=False)
        raw2 = fmt.text.replace("```json", "").replace("```", "").strip()
        d    = json.loads(raw2)

    # Формування Telegram повідомлення
    ii  = {"high": "🔴", "medium": "🟡", "low": "⚪"}
    ci  = {"LLM": "🧠", "Продукти": "📦", "Дослідження": "🔬",
           "Компанії": "🏢", "Агенти": "🤖", "Безпека": "🛡"}
    sep = "━" * 19
    msg = ["⚡ <b>AI Дайджест</b> · " + today_uk, sep,
           "<i>" + d.get("summary", "") + "</i>", ""]

    for i, item in enumerate(d.get("news", []), 1):
        imp      = item.get("importance", "medium")
        cat      = item.get("category", "")
        title    = item.get("title", "")
        source   = item.get("source", "")
        summary  = item.get("summary", "")
        why      = item.get("why_matters", "")
        imp_icon = ii.get(imp, "⚪")
        cat_icon = ci.get(cat, "📌")
        msg += [
            imp_icon + " <b>" + str(i) + ". " + title + "</b>",
            cat_icon + " <code>" + cat + "</code>  //  " + source,
            summary,
            "💡 <i>" + why + "</i>",
            ""
        ]
    msg += [sep, "🤖 Gemini 2.0 Flash · Google Search"]
    send_telegram(nl.join(msg))
    print("Done!")

if __name__ == "__main__":
    run()
