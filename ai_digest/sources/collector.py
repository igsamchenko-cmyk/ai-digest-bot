"""Feed fetching, deduplication, freshness filtering, and collection."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import requests

from ai_digest.sources.feeds import (
    HTTP_HEADERS,
    UA_FEEDS,
    google_news_url,
    parse_feed_items,
    world_rss_queries,
)
from ai_digest.sources.filters import AI_PATTERN, normalize_title

logger = logging.getLogger(__name__)


def item_sort_time(item: dict) -> datetime:
    return item.get("published_at") or datetime.min.replace(tzinfo=timezone.utc)


def fetch_feed(url: str, default_source: str) -> list[dict]:
    """Fetch and parse a single feed URL.

    Returns [] on any network/parse error — one dead source never kills the run.
    """
    try:
        response = requests.get(url, timeout=30, headers=HTTP_HEADERS)
        response.raise_for_status()
    except requests.RequestException as exc:
        logger.warning("Feed failed (%s): %s", default_source, exc)
        return []
    return parse_feed_items(response.content, default_source)


def get_rss_news(
    news_lookback_hours: int = 72,
    news_count: int = 5,
) -> list[dict]:
    """Collect and deduplicate news from UA feeds and Google News.

    Returns up to max(news_count * 4, 12) items sorted by recency (UA first).
    """
    logger.info("Fetching news (UA feeds + Google News)...")
    cutoff = datetime.now(timezone.utc) - timedelta(hours=news_lookback_hours)
    seen_links: set[str] = set()
    seen_titles: set[str] = set()
    ua_items: list[dict] = []
    world_items: list[dict] = []

    def add(
        raw_items: list[dict],
        bucket: list[dict],
        lang: str,
        require_keywords: bool = False,
        require_date: bool = False,
    ) -> None:
        for it in raw_items:
            published = it.get("published_at")
            if require_date and not published:
                continue
            if published and published < cutoff:
                continue
            if require_keywords and not AI_PATTERN.search(it["title"]):
                continue
            title_key = normalize_title(it["title"])
            if it["link"] in seen_links or title_key in seen_titles:
                continue
            seen_links.add(it["link"])
            seen_titles.add(title_key)
            it["lang"] = lang
            bucket.append(it)

    # 1. Direct feeds from Ukrainian publications (AI-topic filter)
    for source, url in UA_FEEDS.items():
        add(fetch_feed(url, source), ua_items, "uk", require_keywords=True, require_date=True)

    # 2. Google News in Ukrainian
    for query in [
        "штучний інтелект when:3d",
        "OpenAI OR ChatGPT OR Gemini OR Claude when:3d",
    ]:
        add(fetch_feed(google_news_url(query, "uk"), "Google News UA"), ua_items, "uk")

    # 3. Global AI news (Google News, English)
    for query in world_rss_queries():
        add(fetch_feed(google_news_url(query, "en"), "Google News"), world_items, "en")

    ua_items.sort(key=item_sort_time, reverse=True)
    world_items.sort(key=item_sort_time, reverse=True)
    items = ua_items + world_items

    logger.info(
        "Found %d UA + %d world items (last %dh).",
        len(ua_items),
        len(world_items),
        news_lookback_hours,
    )
    return items[: max(news_count * 4, 12)]
