"""Feed definitions, URL builders, and low-level RSS/Atom parsing."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import quote_plus

ATOM_NS = "{http://www.w3.org/2005/Atom}"
HTTP_HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; ai-digest-bot/2.0)"}

# Direct RSS feeds from Ukrainian IT publications (clean article URLs)
UA_FEEDS: dict[str, str] = {
    "DOU": "https://dou.ua/feed/",
    "AIN.UA": "https://ain.ua/feed/",
    "Mezha.Media": "https://mezha.media/feed/",
    "ITC.ua": "https://itc.ua/feed/",
    "dev.ua": "https://dev.ua/rss",
    "SPEKA": "https://speka.media/feed",
}


def world_rss_queries() -> list[str]:
    return [
        '("AI model" OR "language model" OR LLM) (released OR launches OR announced OR update OR benchmark) when:3d',
        "(OpenAI OR ChatGPT OR GPT) (model OR release OR update OR launch) when:3d",
        "(Anthropic OR Claude) (model OR release OR update OR launch OR benchmark) when:3d",
        "(Google OR Gemini OR DeepMind) (AI model OR release OR update OR launch) when:3d",
        "(Meta OR Llama OR Mistral OR DeepSeek OR Qwen OR xAI OR Grok) (model OR release OR update OR launch) when:3d",
        '(Microsoft Copilot OR Perplexity OR "AI agent" OR "coding agent") (release OR update OR launch) when:3d',
    ]


def google_news_url(query: str, lang: str = "en") -> str:
    encoded = quote_plus(query)
    if lang == "uk":
        return f"https://news.google.com/rss/search?q={encoded}&hl=uk&gl=UA&ceid=UA:uk"
    return f"https://news.google.com/rss/search?q={encoded}&hl=en-US&gl=US&ceid=US:en"


def parse_feed_datetime(value: str | None) -> datetime | None:
    """Parse RFC-822 or ISO-8601 date string; return UTC datetime or None."""
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


def parse_feed_items(content: bytes, default_source: str) -> list[dict]:
    """Parse RSS 2.0 or Atom feed bytes; return list of item dicts.

    Each dict has keys: title, link, source, published_at.
    Returns [] on parse error (never raises).
    """
    items: list[dict] = []
    try:
        root = ET.fromstring(content)
    except ET.ParseError as exc:
        import logging

        logging.getLogger(__name__).debug("Feed parse error (%s): %s", default_source, exc)
        return items

    # RSS 2.0
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

    # Atom
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
