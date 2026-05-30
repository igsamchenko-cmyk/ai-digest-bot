import anthropic, requests, json, os
from datetime import datetime

ANTHROPIC_API_KEY  = os.environ.get("ANTHROPIC_API_KEY", "")
TELEGRAM_BOT_TOKEN = "8917147406:AAGmWQrdtaGsPMokjcMS2YEf1QYXscfYPpU"
TELEGRAM_CHAT_ID   = "1039798805"
TOPIC      = "artificial intelligence, LLM models, AI companies, machine learning, new AI releases"
NEWS_COUNT = 5

def send_telegram(text):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": text,
        "parse_mode": "HTML", "disable_web_page_preview": True}, timeout=30).raise_for_status()

def run():
    if not ANTHROPIC_API_KEY:
        raise ValueError("ANTHROPIC_API_KEY is not set!")
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    today_uk = datetime.now().strftime("%-d %B %Y")
    today_en = datetime.now().strftime("%B %-d, %Y")
    print(f"Starting digest for {today_en}...")
    send_telegram(f"⏳ Збираю AI-новини за {today_uk}...")
    messages = [{"role": "user", "content": (
        f"Search for the latest AI news from today {today_en} about: {TOPIC}. "
        f"Find {NEWS_COUNT} most important stories from the last 24-48 hours. "
        f"Search multiple times to cover different topics.")}]
    data = client.messages.create(model="claude-sonnet-4-6", max_tokens=4000,
        tools=[{"type": "web_search_20250305", "name": "web_search"}], messages=messages)
    iterations = 0
    while data.stop_reason == "tool_use" and iterations < 6:
        iterations += 1
        print(f"Search iteration {iterations}...")
        tool_results = [{"type": "tool_result", "tool_use_id": b.id, "content": "done"}
                        for b in data.content if b.type == "tool_use"]
        messages = [*messages, {"role": "assistant", "content": data.content},
                    {"role": "user", "content": tool_results}]
        data = client.messages.create(model="claude-sonnet-4-6", max_tokens=4000,
            tools=[{"type": "web_search_20250305", "name": "web_search"}], messages=messages)
    search_result = " ".join(b.text for b in data.content if hasattr(b, "text"))
    print("Formatting digest...")
    prompt = (
        f"Make a digest of {NEWS_COUNT} most important AI news for today {today_uk} in Ukrainian language.\n\n"
        f"NEWS:\n{search_result}\n\n"
        'Reply ONLY with valid JSON (no markdown):\n'
        '{"summary":"...","news":[{"title":"...","category":"LLM|\u041f\u0440\u043e\u0434\u0443\u043a\u0442\u0438|\u0414\u043e\u0441\u043b\u0456\u0434\u0436\u0435\u043d\u043d\u044f|\u041a\u043e\u043c\u043f\u0430\u043d\u0456\u0457|\u0410\u0433\u0435\u043d\u0442\u0438|\u0411\u0435\u0437\u043f\u0435\u043a\u0430","importance":"high|medium|low","summary":"...","source":"...","why_matters":"..."}]}'
    )
    fmt = client.messages.create(model="claude-sonnet-4-6", max_tokens=3000,
        messages=[{"role": "user", "content": prompt}])
    raw = fmt.content[0].text.replace("```json","").replace("```","").strip()
    d = json.loads(raw)
    ii = {"high":"🔴","medium":"🟡","low":"⚪"}
    ci = {"LLM":"🧠","Продукти":"📦","Дослідження":"🔬","Компанії":"🏢","Агенти":"🤖","Безпека":"🛡"}
    msg = [f"⚡ <b>AI Дайджест</b> · {today_uk}", "━"*19, f"<i>{d.get('summary','')}</i>",""]
    for i,item in enumerate(d.get("news",[]),1):
        imp,cat = item.get("importance","medium"),item.get("category","")
        msg += [f"{ii.get(imp,'⚪')} <b>{i}. {item['title']}</b>",
                f"{ci.get(cat,'📌')} <code>{cat}</code>  //  {item.get('source','')}",
                item.get("summary",""), f"💡 <i>{item.get('why_matters','')}</i>",""]
    msg += ["━"*19, "🤖 Claude Sonnet 4.6 · web_search"]
    send_telegram("\n".join(msg))
    print("Done!")

if __name__ == "__main__":
    run()
