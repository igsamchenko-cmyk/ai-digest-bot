import os, json, requests
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

def run():
    if not GOOGLE_API_KEY:
        raise ValueError("GOOGLE_API_KEY is not set!")
    client = genai.Client(api_key=GOOGLE_API_KEY)
    today_uk = datetime.now().strftime("%-d %B %Y")
    today_en = datetime.now().strftime("%B %-d, %Y")
    print("Starting digest for " + today_en + "...")
    send_telegram("Збираю AI-новини за " + today_uk + "...")

    resp = client.models.generate_content(
        model="gemini-2.0-flash",
        contents=(
            "Find the " + str(NEWS_COUNT) + " most important AI news from the last 24-48 hours "
            "(today is " + today_en + "). Topics: " + TOPIC + ". "
            "For each: title, source, summary, why it matters."
        ),
        config=types.GenerateContentConfig(
            tools=[types.Tool(google_search=types.GoogleSearch())]
        )
    )
    search_result = resp.text
    print("Search done. Formatting...")

    fmt = client.models.generate_content(
        model="gemini-2.0-flash",
        contents=(
            "Make a digest of " + str(NEWS_COUNT) + " most important AI news for today " + today_uk + " in Ukrainian." + chr(10) + chr(10) +
            "NEWS:" + chr(10) + search_result + chr(10) + chr(10) +
            'Reply ONLY with valid JSON:' + chr(10) +
            '{"summary":"2-3 sentences in Ukrainian","news":[{"title":"...","category":"LLM|Products|Research|Companies|Agents|Security","importance":"high|medium|low","summary":"3-4 sentences","source":"name","why_matters":"1 sentence"}]}'
        )
    )
    raw = fmt.text.replace("```json", "").replace("```", "").strip()
    d = json.loads(raw)

    ii = {"high": "HIGH", "medium": "MED", "low": "LOW"}
    sep = "=" * 19
    nl  = chr(10)
    msg = ["AI Digest " + today_uk, sep, d.get("summary", ""), ""]
    for i, item in enumerate(d.get("news", []), 1):
        imp    = item.get("importance", "medium")
        cat    = item.get("category", "")
        title  = item.get("title", "")
        source = item.get("source", "")
        summ   = item.get("summary", "")
        why    = item.get("why_matters", "")
        msg += [
            "[" + ii.get(imp,"?") + "] " + str(i) + ". " + title,
            cat + " // " + source,
            summ,
            "Why: " + why,
            ""
        ]
    msg += [sep, "Gemini 2.0 Flash + Google Search"]
    send_telegram(nl.join(msg))
    print("Done!")

if __name__ == "__main__":
    run()
