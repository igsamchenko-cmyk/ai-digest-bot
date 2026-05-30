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
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": text,
        "parse_mode": "HTML", "disable_web_page_preview": True}, timeout=30).raise_for_status()

def run():
    if not GOOGLE_API_KEY:
        raise ValueError("GOOGLE_API_KEY is not set!")
    client = genai.Client(api_key=GOOGLE_API_KEY)
    today_uk = datetime.now().strftime("%-d %B %Y")
    today_en = datetime.now().strftime("%B %-d, %Y")
    print(f"Starting digest for {today_en}...")
    send_telegram(f"\u23f3 \u0417\u0431\u0438\u0440\u0430\u044e AI-\u043d\u043e\u0432\u0438\u043d\u0438 \u0437\u0430 {today_uk}...")

    # Step 1: Search with Google Search grounding
    resp = client.models.generate_content(
        model="gemini-2.0-flash",
        contents=(
            f"Find the {NEWS_COUNT} most important AI news from the last 24-48 hours "
            f"(today is {today_en}). Topics: {TOPIC}. "
            f"For each: title, source, summary, why it matters."
        ),
        config=types.GenerateContentConfig(
            tools=[types.Tool(google_search=types.GoogleSearch())]
        )
    )
    search_result = resp.text
    print("Search done. Formatting...")

    # Step 2: Format as JSON in Ukrainian
    fmt = client.models.generate_content(
        model="gemini-2.0-flash",
        contents=(
            f"Make a digest of {NEWS_COUNT} most important AI news for today {today_uk} in Ukrainian.\n\n"
            f"NEWS:\n{search_result}\n\n"
            'Reply ONLY with valid JSON:\n'
            '{"summary":"2-3 sentences in Ukrainian","news":[{"title":"...","category":"LLM|\u041f\u0440\u043e\u0434\u0443\u043a\u0442\u0438|\u0414\u043e\u0441\u043b\u0456\u0434\u0436\u0435\u043d\u043d\u044f|\u041a\u043e\u043c\u043f\u0430\u043d\u0456\u0457|\u0410\u0433\u0435\u043d\u0442\u0438|\u0411\u0435\u0437\u043f\u0435\u043a\u0430","importance":"high|medium|low","summary":"3-4 sentences","source":"name","why_matters":"1 sentence"}]}'
        )
    )
    raw = fmt.text.replace("```json","").replace("```","").strip()
    d = json.loads(raw)

    ii = {"high":"\ud83d\udd34","medium":"\ud83d\udfe1","low":"\u26aa"}
    ci = {"LLM":"\ud83e\udde0","\u041f\u0440\u043e\u0434\u0443\u043a\u0442\u0438":"\ud83d\udce6","\u0414\u043e\u0441\u043b\u0456\u0434\u0436\u0435\u043d\u043d\u044f":"\ud83d\udd2c","\u041a\u043e\u043c\u043f\u0430\u043d\u0456\u0457":"\ud83c\udfe2","\u0410\u0433\u0435\u043d\u0442\u0438":"\ud83e\udd16","\u0411\u0435\u0437\u043f\u0435\u043a\u0430":"\ud83d\udee1"}
    msg = [f"\u26a1 <b>AI \u0414\u0430\u0439\u0434\u0436\u0435\u0441\u0442</b> \u00b7 {today_uk}","\u2501"*19,f"<i>{d.get('summary','')}</i>",""]
    for i,item in enumerate(d.get("news",[]),1):
        imp,cat = item.get("importance","medium"),item.get("category","")
        msg += [f"{ii.get(imp,'\u26aa')} <b>{i}. {item['title']}</b>",
                f"{ci.get(cat,'\ud83d\udccc')} <code>{cat}</code>  //  {item.get('source','')}",
                item.get("summary",""),f"\ud83d\udca1 <i>{item.get('why_matters','')}</i>",""]
    msg += ["\u2501"*19,"\ud83e\udd16 Gemini 2.0 Flash \u00b7 Google Search"]
    send_telegram("\n".join(msg))
    print("Done!")

if __name__ == "__main__":
    run()
