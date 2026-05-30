import anthropic
import requests
import json
import os
from datetime import datetime

# ═══════════════════════════════════════════
#  НАЛАШТУВАННЯ
# ═══════════════════════════════════════════
ANTHROPIC_API_KEY  = os.environ.get("ANTHROPIC_API_KEY", "")
TELEGRAM_BOT_TOKEN = "8917147406:AAGmWQrdtaGsPMokjcMS2YEf1QYXscfYPpU"
TELEGRAM_CHAT_ID   = "1039798805"
TOPIC      = "artificial intelligence, LLM models, AI companies, machine learning, new AI releases"
NEWS_COUNT = 5
# ═══════════════════════════════════════════


def send_telegram(text: str):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    resp = requests.post(url, json={
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }, timeout=30)
    resp.raise_for_status()


def run():
    if not ANTHROPIC_API_KEY:
        raise ValueError("ANTHROPIC_API_KEY is not set!")

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    today_uk = datetime.now().strftime("%-d %B %Y")
    today_en = datetime.now().strftime("%B %-d, %Y")

    print(f"Starting digest for {today_en}...")
    send_telegram(f"⏳ Збираю AI-новини за {today_uk}...")

    messages = [{
        "role": "user",
        "content": (
            f"Search for the latest AI news from today {today_en} about: {TOPIC}. "
            f"Find {NEWS_COUNT} most important stories from the last 24-48 hours. "
            f"Search multiple times to cover different topics."
        )
    }]

    data = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=4000,
        tools=[{"type": "web_search_20250305", "name": "web_search"}],
        messages=messages,
    )

    iterations = 0
    while data.stop_reason == "tool_use" and iterations < 6:
        iterations += 1
        print(f"Search iteration {iterations}...")

        tool_results = [
            {"type": "tool_result", "tool_use_id": b.id, "content": "done"}
            for b in data.content if b.type == "tool_use"
        ]

        messages = [
            *messages,
            {"role": "assistant", "content": data.content},
            {"role": "user", "content": tool_results},
        ]

        data = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=4000,
            tools=[{"type": "web_search_20250305", "name": "web_search"}],
            messages=messages,
        )

    search_result = " ".join(
        b.text for b in data.content if hasattr(b, "text")
    )
    print(f"Search complete. Formatting digest...")

    fmt = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=3000,
        messages=[{"role": "user", "content": f"""Based on these news make a digest of {NEWS_COUNT} most important AI news for today {today_uk} in Ukrainian language.

NEWS:
{search_result}

Reply ONLY with valid JSON (no markdown, no explanation):
{{
  "summary": "2-3 sentence summary of the day in Ukrainian",
  "news": [
    {{
      "title": "title in Ukrainian",
      "category": "LLM|Продукти|Дослідження|Компанії|Агенти|Безпека",
      "importance": "high|medium|low",
      "summary": "3-4 sentence summary in Ukrainian",
      "source": "source name",
      "why_matters": "one sentence why this matters in Ukrainian"
    }}
  ]
}}"""}]
    )

    raw = fmt.content[0].text.replace("```json", "").replace("```", "").strip()
    d = json.loads(raw)

    importance_icon = {"high": "🔴", "medium": "🟡", "low": "⚪"}
    category_icon = {
        "LLM": "🧠", "Продукти": "📦", "Дослідження": "🔬",
        "Компанії": "🏢", "Агенти": "🤖", "Безпека": "🛡",
    }

    msg = [
        f"⚡ <b>AI Дайджест</b> · {today_uk}",
        "━━━━━━━━━━━━━━━━━━━",
        f"<i>{d.get(\'summary\', \'\')}</i>",
        "",
    ]

    for i, item in enumerate(d.get("news", []), 1):
        imp  = item.get("importance", "medium")
        cat  = item.get("category", "")
        msg += [
            f"{importance_icon.get(imp, \'⚪\')} <b>{i}. {item[\'title\']}</b>",
            f"{category_icon.get(cat, \'📌\')} <code>{cat}</code>  //  {item.get(\'source\', \'\')}",
            item["summary"],
            f"💡 <i>{item.get(\'why_matters\', \'\')}</i>",
            "",
        ]

    msg += [
        "━━━━━━━━━━━━━━━━━━━",
        "🤖 Claude Sonnet 4.6 · web_search",
    ]

    send_telegram("\n".join(msg))
    print("Digest sent successfully!")


if __name__ == "__main__":
    run()
