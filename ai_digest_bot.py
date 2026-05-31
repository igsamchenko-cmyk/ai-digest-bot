#!/usr/bin/env python3
"""
AI Дайджест — Telegram бот
Щодня о 7:00 надсилає свіжі новини зі світу ШІ
"""

import anthropic
import os
import requests
import schedule
import time
import json
from datetime import datetime

# ═══════════════════════════════════════════
#  НАЛАШТУВАННЯ
# ═══════════════════════════════════════════
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID   = os.environ.get("TELEGRAM_CHAT_ID", "")

# Тема дайджесту (можна змінити)
TOPIC = "штучний інтелект, LLM, нові AI моделі, AI компанії, машинне навчання"

# Кількість новин
NEWS_COUNT = 5

# Час відправки (24-годинний формат)
SEND_TIME = "07:00"
# ═══════════════════════════════════════════


def send_telegram(text: str):
    """Відправляє повідомлення в Telegram"""
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    resp = requests.post(url, json=payload, timeout=30)
    resp.raise_for_status()
    return resp.json()


def fetch_and_format_news() -> str:
    """Шукає новини через web_search і форматує дайджест"""
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    today_uk = datetime.now().strftime("%-d %B %Y")
    today_en = datetime.now().strftime("%B %-d, %Y")

    print(f"[{datetime.now().strftime('%H:%M:%S')}] Шукаю новини...")

    # КРОК 1: Пошук реальних новин
    messages = [{
        "role": "user",
        "content": (
            f"Search for the latest AI news from today {today_en} about: {TOPIC}. "
            f"Find {NEWS_COUNT} most important stories from the last 24-48 hours. "
            f"Use multiple searches to cover different aspects."
        )
    }]

    data = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=4000,
        tools=[{"type": "web_search_20250305", "name": "web_search"}],
        messages=messages,
    )

    # КРОК 2: Обробка web_search циклів
    iterations = 0
    while data.stop_reason == "tool_use" and iterations < 6:
        iterations += 1
        print(f"[{datetime.now().strftime('%H:%M:%S')}] Пошук {iterations}...")

        tool_results = []
        for block in data.content:
            if block.type == "tool_use":
                tool_results.append({
                    "type": "tool_result",
                    "tool_use_id": block.id,
                    "content": getattr(block, "content", "search completed"),
                })

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
        block.text for block in data.content if hasattr(block, "text")
    )

    # КРОК 3: Форматування в структурований JSON
    print(f"[{datetime.now().strftime('%H:%M:%S')}] Форматую дайджест...")

    format_resp = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=3000,
        messages=[{
            "role": "user",
            "content": f"""На основі знайдених новин склади дайджест.

ЗНАЙДЕНІ НОВИНИ:
{search_result}

Склади дайджест із {NEWS_COUNT} найважливіших новин на тему AI за сьогодні ({today_uk}).
Для кожної новини: 3-4 речення збалансованого резюме.

Відповідай ЛИШЕ валідним JSON (без markdown):
{{
  "topic": "назва теми",
  "summary": "загальний підсумок дня у 2 реченнях",
  "news": [
    {{
      "title": "заголовок українською",
      "category": "LLM|Продукти|Дослідження|Компанії|Агенти|Безпека",
      "importance": "high|medium|low",
      "summary": "резюме новини",
      "source": "джерело",
      "why_matters": "чому важливо — одне речення"
    }}
  ]
}}"""
        }]
    )

    raw = format_resp.content[0].text
    clean = raw.replace("```json", "").replace("```", "").strip()
    return json.loads(clean)


def build_telegram_message(data: dict, today: str) -> str:
    """Збирає красиве Telegram повідомлення з HTML-форматуванням"""

    importance_icon = {"high": "🔴", "medium": "🟡", "low": "⚪"}
    category_icon = {
        "LLM": "🧠", "Продукти": "📦", "Дослідження": "🔬",
        "Компанії": "🏢", "Агенти": "🤖", "Безпека": "🛡",
    }

    lines = [
        f"⚡ <b>AI Дайджест</b> · {today}",
        f"━━━━━━━━━━━━━━━━━━━",
        f"<i>{data.get('summary', '')}</i>",
        "",
    ]

    for i, item in enumerate(data.get("news", []), 1):
        imp  = item.get("importance", "medium")
        cat  = item.get("category", "")
        icon = importance_icon.get(imp, "⚪")
        cicon = category_icon.get(cat, "📌")

        lines += [
            f"{icon} <b>{i}. {item['title']}</b>",
            f"{cicon} <code>{cat}</code>  //  {item.get('source', '')}",
            f"{item['summary']}",
            f"💡 <i>{item.get('why_matters', '')}</i>",
            "",
        ]

    lines += [
        "━━━━━━━━━━━━━━━━━━━",
        f"🤖 Claude Sonnet 4.6 · web_search",
    ]

    return "\n".join(lines)


def run_digest():
    """Головна функція — збирає і відправляє дайджест"""
    today = datetime.now().strftime("%-d %B %Y")
    print(f"\n{'='*50}")
    print(f"Запуск дайджесту: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*50}")

    try:
        # Повідомлення про старт
        send_telegram(f"⏳ Збираю AI-новини за {today}...")

        data = fetch_and_format_news()
        message = build_telegram_message(data, today)
        send_telegram(message)

        print(f"[{datetime.now().strftime('%H:%M:%S')}] ✅ Дайджест надіслано!")

    except json.JSONDecodeError as e:
        err = f"❌ Помилка парсингу JSON: {e}"
        print(err)
        send_telegram(err)
    except requests.RequestException as e:
        print(f"❌ Telegram помилка: {e}")
    except Exception as e:
        err = f"❌ Помилка: {e}"
        print(err)
        try:
            send_telegram(err)
        except Exception:
            pass


def main():
    print("=" * 50)
    print("  AI Дайджест — Telegram бот")
    print(f"  Відправка щодня о {SEND_TIME}")
    print(f"  Chat ID: {TELEGRAM_CHAT_ID}")
    print("=" * 50)

    # Тест підключення
    try:
        send_telegram(f"✅ Бот запущено! Дайджест надходитиме щодня о {SEND_TIME}.")
        print("✅ Telegram підключено успішно")
    except Exception as e:
        print(f"❌ Помилка Telegram: {e}")
        return

    # Розклад
    schedule.every().day.at(SEND_TIME).do(run_digest)
    print(f"✅ Розклад встановлено: щодня о {SEND_TIME}")
    print("   (Ctrl+C щоб зупинити)\n")

    # Запитати чи запустити зараз для тесту
    try:
        answer = input("Запустити дайджест зараз для тесту? (y/n): ").strip().lower()
        if answer == 'y':
            run_digest()
    except (EOFError, KeyboardInterrupt):
        pass

    # Основний цикл
    while True:
        schedule.run_pending()
        time.sleep(30)


if __name__ == "__main__":
    main()
