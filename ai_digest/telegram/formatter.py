"""HTML message formatting for Telegram."""

from __future__ import annotations

import html
from datetime import datetime, timedelta, timezone

try:
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

    KYIV_TZ = ZoneInfo("Europe/Kyiv")
except ZoneInfoNotFoundError:
    KYIV_TZ = timezone(timedelta(hours=3), name="Europe/Kyiv")  # type: ignore[assignment]


def escape_text(value: object) -> str:
    return html.escape(str(value or ""), quote=False)


def escape_attr(value: object) -> str:
    return html.escape(str(value or ""), quote=True)


def date_labels(now: datetime) -> tuple[str, str]:
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


def build_gemini_message(data: dict, today_uk: str) -> str:
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
        title_html = escape_text(item.get("title", ""))
        link = item.get("link", "")
        if link:
            title_html = '<a href="' + escape_attr(link) + '">' + title_html + "</a>"
        lines += [
            importance_icon.get(importance, "⚪") + " <b>" + str(i) + ". " + title_html + "</b>",
            category_icon.get(category, "📌")
            + " <code>"
            + escape_text(category)
            + "</code> // "
            + escape_text(item.get("source", "")),
            escape_text(item.get("summary", "")),
            "💡 <i>" + escape_text(item.get("why_matters", "")) + "</i>",
            "",
        ]
    lines += [sep, "🤖 Gemini · UA RSS + Google News"]
    return "\n".join(lines)


def build_rss_message(items: list[dict], today_uk: str, news_count: int = 5) -> str:
    sep = "━" * 19
    lines = [
        "⚡ <b>AI Дайджест (резервний)</b> · " + escape_text(today_uk),
        sep,
        "<i>Gemini зараз недоступний. Надсилаю свіжі новини напряму з RSS.</i>",
        "",
    ]
    for i, item in enumerate(items[: news_count * 2], 1):
        published = item.get("published_at")
        published_label = (
            published.astimezone(KYIV_TZ).strftime("%d.%m %H:%M") if published else "свіже"
        )
        lines += [
            f"📰 <b>{i}. {escape_text(item['title'])}</b>",
            f"🕒 {escape_text(published_label)} · "
            f'<a href="{escape_attr(item["link"])}">Читати на {escape_text(item["source"])}</a>',
            "",
        ]
    lines += [sep, "📡 RSS Feed"]
    return "\n".join(lines)
