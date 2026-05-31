import os
import sys
import json
import requests
import time
from datetime import datetime
import xml.etree.ElementTree as ET
import schedule
from google import genai
from google.genai import types

# Load .env file manually to avoid dependency on python-dotenv
def load_env_manually():
    try:
        env_path = '.env'
        if not os.path.exists(env_path):
            script_dir = os.path.dirname(os.path.abspath(__file__))
            env_path = os.path.join(script_dir, '.env')
        
        if os.path.exists(env_path):
            with open(env_path, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith('#') and '=' in line:
                        key, val = line.split('=', 1)
                        os.environ[key.strip()] = val.strip()
    except Exception as e:
        print(f"Warning: Failed to load .env file: {e}")

load_env_manually()

GOOGLE_API_KEY     = os.environ.get("GOOGLE_API_KEY", "")
TELEGRAM_BOT_TOKEN = "8917147406:AAGmWQrdtaGsPMokjcMS2YEf1QYXscfYPpU"
TELEGRAM_CHAT_ID   = "1039798805"
TOPIC      = "artificial intelligence, LLM models, AI companies, machine learning, new AI releases"
NEWS_COUNT = 5

def send_telegram(text):
    url = "https://api.telegram.org/bot" + TELEGRAM_BOT_TOKEN + "/sendMessage"
    requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": text,
        "parse_mode": "HTML", "disable_web_page_preview": True}, timeout=30).raise_for_status()

def gemini_call(client, contents, use_search=False, max_retries=3):
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
            # If it's a quota limit of 0, don't retry, just raise immediately to trigger fallback
            if "limit: 0" in err or "limit of 0" in err:
                raise RuntimeError("Gemini API key has 0 quota limit")
                
            if "429" in err or "RESOURCE_EXHAUSTED" in err:
                wait = 5 * (2 ** attempt)
                print("Rate limit. Waiting " + str(wait) + "s (attempt " + str(attempt + 1) + "/" + str(max_retries) + ")...")
                time.sleep(wait)
            else:
                raise
    raise RuntimeError("Gemini: max retries exceeded")

def get_rss_news():
    """Fallback function to fetch AI news from Google News RSS feed when Gemini is unavailable."""
    print("Fetching news from Google News RSS feed...")
    url = "https://news.google.com/rss/search?q=ChatGPT+OR+Claude+OR+Gemini+OR+OpenAI+OR+Copilot+OR+Google+AI&hl=uk&gl=UA&ceid=UA:uk"
    response = requests.get(url, timeout=30)
    response.raise_for_status()
    
    root = ET.fromstring(response.content)
    items = []
    for item in root.findall('.//item')[:10]:
        title = item.find('title').text
        link = item.find('link').text
        source_elem = item.find('source')
        source = source_elem.text if source_elem is not None else 'Google News'
        items.append({
            'title': title,
            'link': link,
            'source': source
        })
    return items

def run_digest():
    # Setup Ukrainian and English dates
    now = datetime.now()
    months_uk = [
        "січня", "лютого", "березня", "квітня", "травня", "червня",
        "липня", "серпня", "вересня", "жовтня", "листопада", "грудня"
    ]
    months_en = [
        "January", "February", "March", "April", "May", "June",
        "July", "August", "September", "October", "November", "December"
    ]
    today_uk = f"{now.day} {months_uk[now.month - 1]} {now.year}"
    today_en = f"{months_en[now.month - 1]} {now.day}, {now.year}"
    
    print("Starting digest for " + today_en + "...")
    try:
        send_telegram("Збираю AI-новини за " + today_uk + "...")
    except Exception as e:
        print(f"Telegram status message failed: {e}")

    nl = chr(10)
    
    # Try using Gemini API first
    use_fallback = False
    if not GOOGLE_API_KEY:
        print("GOOGLE_API_KEY is not set. Falling back to RSS.")
        use_fallback = True
    else:
        try:
            client = genai.Client(api_key=GOOGLE_API_KEY)
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
            print("Done via Gemini!")
            return
            
        except Exception as e:
            print(f"Gemini execution failed: {e}. Falling back to RSS...")
            use_fallback = True

    if use_fallback:
        try:
            items = get_rss_news()
            if not items:
                send_telegram("☀️ <b>Дайджест новин ШІ</b> · " + today_uk + "\n\nНе вдалося знайти свіжих новин на даний момент.")
                return
                
            sep = "━" * 19
            msg = ["⚡ <b>AI Дайджест (Резервний)</b> · " + today_uk, sep,
                   "<i>На жаль, сервіс штучного інтелекту Gemini наразі недоступний через обмеження API-ключа. "
                   "Ось список останніх новин зі світу AI безпосередньо з пошукової стрічки:</i>", ""]
            
            for i, item in enumerate(items, 1):
                title = item['title'].replace('<', '&lt;').replace('>', '&gt;')
                source = item['source'].replace('<', '&lt;').replace('>', '&gt;')
                msg += [
                    f"📰 <b>{i}. {title}</b>",
                    f"🔗 <a href=\"{item['link']}\">Читати на {source}</a>",
                    ""
                ]
            
            msg += [sep, "📡 Google News RSS Feed"]
            send_telegram(nl.join(msg))
            print("Done via Fallback RSS!")
        except Exception as err:
            print(f"Fallback also failed: {err}")
            send_telegram("⚠️ <b>Помилка:</b> Не вдалося завантажити новини ні через Gemini, ні через RSS.")

def main():
    # Support running once (for GitHub Actions or manual testing)
    run_once = os.environ.get("RUN_ONCE", "false").lower() == "true" or "--run-once" in sys.argv
    
    if run_once:
        print("Running in one-shot mode...")
        run_digest()
        print("One-shot run complete.")
    else:
        print("Starting in schedule mode...")
        send_time = os.environ.get("SEND_TIME", "08:00")
        
        # Test connection at startup
        try:
            send_telegram(f"✅ Бот успішно запущено в режимі демона! Дайджест надходитиме щодня о {send_time}.")
            print("Startup notification sent successfully.")
        except Exception as e:
            print(f"Startup Telegram notification failed: {e}")
            
        schedule.every().day.at(send_time).do(run_digest)
        print(f"Schedule set for: daily at {send_time}")
        
        while True:
            schedule.run_pending()
            time.sleep(30)

if __name__ == "__main__":
    main()
