"""Unit tests for ai_digest.sources.*

Coverage targets:
  - parse_feed_items: valid RSS, valid Atom, broken XML, empty feed, missing fields
  - parse_feed_datetime: RFC-822, ISO-8601, None/invalid
  - fetch_feed: success, RequestException (unavailable source)
  - normalize_title: deduplication key shape
  - AI_PATTERN: positive / negative matches
  - get_rss_news: URL deduplication, title deduplication, one-source-fails fallback
"""

import unittest
from datetime import datetime, timezone
from unittest.mock import Mock, patch

import requests as req

from ai_digest.sources.collector import fetch_feed, get_rss_news
from ai_digest.sources.feeds import parse_feed_datetime, parse_feed_items
from ai_digest.sources.filters import AI_PATTERN, normalize_title

# ─── helpers ──────────────────────────────────────────────────────────────────

_NOW = datetime(2026, 6, 21, 10, 0, tzinfo=timezone.utc)

RSS_SINGLE = b"""<?xml version="1.0"?>
<rss><channel>
  <item>
    <title>OpenAI launches GPT-5</title>
    <link>https://example.com/gpt5</link>
    <pubDate>Sat, 21 Jun 2026 09:00:00 GMT</pubDate>
    <source>TechCrunch</source>
  </item>
</channel></rss>"""

RSS_NO_TITLE = b"""<?xml version="1.0"?>
<rss><channel>
  <item><link>https://example.com/no-title</link></item>
</channel></rss>"""

RSS_NO_LINK = b"""<?xml version="1.0"?>
<rss><channel>
  <item><title>No link item</title></item>
</channel></rss>"""

RSS_EMPTY = b"""<?xml version="1.0"?><rss><channel></channel></rss>"""

ATOM_SINGLE = b"""<?xml version="1.0"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <title>Anthropic releases Claude 4</title>
    <link href="https://example.com/claude4"/>
    <published>2026-06-21T09:30:00Z</published>
  </entry>
</feed>"""


def _fresh_item(title="OpenAI new model", link="https://example.com/1", source="DOU"):
    """Return a dict that passes all freshness/keyword filters in get_rss_news."""
    return {
        "title": title,
        "link": link,
        "source": source,
        "published_at": _NOW,
    }


# ─── parse_feed_items ─────────────────────────────────────────────────────────


class TestParseFeedItems(unittest.TestCase):
    def test_rss_returns_correct_fields(self):
        items = parse_feed_items(RSS_SINGLE, "Fallback")
        self.assertEqual(len(items), 1)
        item = items[0]
        self.assertEqual(item["title"], "OpenAI launches GPT-5")
        self.assertEqual(item["link"], "https://example.com/gpt5")
        self.assertEqual(item["source"], "TechCrunch")  # from <source> tag
        self.assertIsInstance(item["published_at"], datetime)

    def test_rss_uses_default_source_when_no_source_tag(self):
        rss = b"""<?xml version="1.0"?><rss><channel>
          <item>
            <title>AI news</title>
            <link>https://example.com/ai</link>
          </item>
        </channel></rss>"""
        items = parse_feed_items(rss, "MyDefault")
        self.assertEqual(items[0]["source"], "MyDefault")

    def test_atom_returns_correct_fields(self):
        items = parse_feed_items(ATOM_SINGLE, "AtomSource")
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["title"], "Anthropic releases Claude 4")
        self.assertEqual(items[0]["link"], "https://example.com/claude4")
        self.assertEqual(items[0]["source"], "AtomSource")
        self.assertIsNotNone(items[0]["published_at"])

    def test_broken_xml_returns_empty_list(self):
        self.assertEqual(parse_feed_items(b"not xml at all <<<", "X"), [])

    def test_empty_feed_returns_empty_list(self):
        self.assertEqual(parse_feed_items(RSS_EMPTY, "X"), [])

    def test_skips_item_without_title(self):
        items = parse_feed_items(RSS_NO_TITLE, "X")
        self.assertEqual(items, [])

    def test_skips_item_without_link(self):
        items = parse_feed_items(RSS_NO_LINK, "X")
        self.assertEqual(items, [])

    def test_multiple_items_all_returned(self):
        rss = b"""<?xml version="1.0"?><rss><channel>
          <item><title>A</title><link>https://x.com/a</link></item>
          <item><title>B</title><link>https://x.com/b</link></item>
          <item><title>C</title><link>https://x.com/c</link></item>
        </channel></rss>"""
        self.assertEqual(len(parse_feed_items(rss, "X")), 3)

    def test_strips_whitespace_from_title_and_link(self):
        rss = b"""<?xml version="1.0"?><rss><channel>
          <item><title>  Spaced Title  </title><link>  https://x.com/s  </link></item>
        </channel></rss>"""
        item = parse_feed_items(rss, "X")[0]
        self.assertEqual(item["title"], "Spaced Title")
        self.assertEqual(item["link"], "https://x.com/s")


# ─── parse_feed_datetime ──────────────────────────────────────────────────────


class TestParseFeedDatetime(unittest.TestCase):
    def test_rfc822_format(self):
        dt = parse_feed_datetime("Sat, 21 Jun 2026 09:00:00 GMT")
        self.assertEqual(dt, datetime(2026, 6, 21, 9, 0, tzinfo=timezone.utc))

    def test_iso8601_with_z(self):
        dt = parse_feed_datetime("2026-06-21T09:30:00Z")
        self.assertEqual(dt, datetime(2026, 6, 21, 9, 30, tzinfo=timezone.utc))

    def test_iso8601_with_offset(self):
        dt = parse_feed_datetime("2026-06-21T12:00:00+03:00")
        self.assertEqual(dt, datetime(2026, 6, 21, 9, 0, tzinfo=timezone.utc))

    def test_none_returns_none(self):
        self.assertIsNone(parse_feed_datetime(None))

    def test_empty_string_returns_none(self):
        self.assertIsNone(parse_feed_datetime(""))

    def test_invalid_string_returns_none(self):
        self.assertIsNone(parse_feed_datetime("not a date at all"))

    def test_result_is_always_utc(self):
        dt = parse_feed_datetime("Sat, 21 Jun 2026 12:00:00 +0300")
        self.assertIsNotNone(dt)
        self.assertEqual(dt.tzinfo, timezone.utc)
        self.assertEqual(dt.hour, 9)  # 12:00 +03 → 09:00 UTC


# ─── normalize_title & AI_PATTERN ─────────────────────────────────────────────


class TestFilters(unittest.TestCase):
    def test_normalize_title_is_lowercase(self):
        self.assertEqual(normalize_title("OpenAI GPT"), "openai gpt")

    def test_normalize_title_takes_first_10_words(self):
        long = "one two three four five six seven eight nine ten eleven twelve"
        key = normalize_title(long)
        self.assertEqual(len(key.split()), 10)
        self.assertNotIn("eleven", key)

    def test_normalize_title_handles_none(self):
        self.assertEqual(normalize_title(None), "")

    def test_normalize_title_handles_empty_string(self):
        self.assertEqual(normalize_title(""), "")

    def test_normalize_title_strips_punctuation(self):
        key = normalize_title("OpenAI: GPT-5 released!")
        # re.findall(r"\w+") splits on punctuation
        self.assertIn("openai", key)
        self.assertIn("gpt", key)

    def test_ai_pattern_matches_ukrainian_keywords(self):
        self.assertTrue(AI_PATTERN.search("Штучний інтелект у медицині"))
        self.assertTrue(AI_PATTERN.search("Нейромережі навчаються швидше"))

    def test_ai_pattern_matches_english_names(self):
        for phrase in ["OpenAI model", "ChatGPT update", "Anthropic Claude", "Gemini Pro"]:
            with self.subTest(phrase=phrase):
                self.assertTrue(AI_PATTERN.search(phrase))

    def test_ai_pattern_rejects_unrelated_titles(self):
        for phrase in [
            "Найкращі ноутбуки 2026 року",
            "Рецепти здорового харчування",
            "Ukraine football results",
        ]:
            with self.subTest(phrase=phrase):
                self.assertFalse(AI_PATTERN.search(phrase))


# ─── fetch_feed ───────────────────────────────────────────────────────────────


class TestFetchFeed(unittest.TestCase):
    def test_success_returns_parsed_items(self):
        mock_resp = Mock()
        mock_resp.content = RSS_SINGLE
        mock_resp.raise_for_status.return_value = None
        with patch("ai_digest.sources.collector.requests.get", return_value=mock_resp):
            items = fetch_feed("https://example.com/feed", "TestSource")
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["title"], "OpenAI launches GPT-5")

    def test_connection_error_returns_empty_list(self):
        """Unavailable source must not raise — returns [] so other sources keep running."""
        with patch(
            "ai_digest.sources.collector.requests.get",
            side_effect=req.ConnectionError("refused"),
        ):
            items = fetch_feed("https://dead.example.com/feed", "Dead")
        self.assertEqual(items, [])

    def test_timeout_returns_empty_list(self):
        with patch(
            "ai_digest.sources.collector.requests.get",
            side_effect=req.Timeout("timed out"),
        ):
            items = fetch_feed("https://slow.example.com/feed", "Slow")
        self.assertEqual(items, [])

    def test_http_error_returns_empty_list(self):
        mock_resp = Mock()
        mock_resp.raise_for_status.side_effect = req.HTTPError("404")
        with patch("ai_digest.sources.collector.requests.get", return_value=mock_resp):
            items = fetch_feed("https://example.com/gone", "Gone")
        self.assertEqual(items, [])

    def test_empty_feed_returns_empty_list(self):
        mock_resp = Mock()
        mock_resp.content = RSS_EMPTY
        mock_resp.raise_for_status.return_value = None
        with patch("ai_digest.sources.collector.requests.get", return_value=mock_resp):
            items = fetch_feed("https://example.com/empty", "Empty")
        self.assertEqual(items, [])


# ─── get_rss_news (deduplication & fallback) ─────────────────────────────────


class TestGetRssNews(unittest.TestCase):
    """Patch fetch_feed at the collector level to avoid real HTTP."""

    _PATCH = "ai_digest.sources.collector.fetch_feed"

    def test_deduplicates_by_link(self):
        """Same URL appearing in multiple feeds must appear only once."""
        item = _fresh_item(title="OpenAI new model", link="https://dup.example.com/1")

        with patch(self._PATCH, return_value=[item]):
            items = get_rss_news(news_lookback_hours=72, news_count=5)

        links = [i["link"] for i in items]
        self.assertEqual(len(links), len(set(links)), "Duplicate links found")

    def test_deduplicates_by_normalised_title(self):
        """Two items with the same first-10-word title key must yield only one result."""
        base_title = "OpenAI releases groundbreaking new artificial intelligence model today"
        item_a = _fresh_item(
            title=base_title + " — extra words A",
            link="https://source-a.example.com/1",
        )
        # Different link but title key (first 10 words) is identical
        item_b = _fresh_item(
            title=base_title + " — extra words B",
            link="https://source-b.example.com/2",
        )

        call_n = {"n": 0}

        def _side_effect(url, source):
            call_n["n"] += 1
            # First call returns item_a, second call returns item_b (same key)
            return [item_a] if call_n["n"] == 1 else [item_b]

        with patch(self._PATCH, side_effect=_side_effect):
            items = get_rss_news(news_lookback_hours=72, news_count=5)

        titles = [i["title"] for i in items]
        # Only one of the two near-identical titles should survive
        matching = [t for t in titles if base_title in t]
        self.assertEqual(len(matching), 1)

    def test_one_source_failure_does_not_block_others(self):
        """If one feed call returns [], items from other calls are still collected."""
        good_item = _fresh_item(title="OpenAI model release", link="https://good.example.com/1")

        call_n = {"n": 0}

        def _side_effect(url, source):
            call_n["n"] += 1
            return [] if call_n["n"] == 1 else [good_item]

        with patch(self._PATCH, side_effect=_side_effect):
            items = get_rss_news(news_lookback_hours=72, news_count=5)

        self.assertGreater(len(items), 0, "Expected items from surviving sources")

    def test_all_sources_empty_returns_empty_list(self):
        with patch(self._PATCH, return_value=[]):
            items = get_rss_news(news_lookback_hours=72, news_count=5)
        self.assertEqual(items, [])

    def test_result_capped_at_news_count_times_four(self):
        """Return at most max(news_count*4, 12) items."""
        news_count = 3
        # Generate more items than the cap, all with unique links and AI-matching titles
        many_items = [
            _fresh_item(
                title=f"OpenAI model release number {i}",
                link=f"https://example.com/{i}",
            )
            for i in range(50)
        ]
        with patch(self._PATCH, return_value=many_items):
            items = get_rss_news(news_lookback_hours=72, news_count=news_count)
        self.assertLessEqual(len(items), max(news_count * 4, 12))

    def test_stale_items_excluded(self):
        """Items older than news_lookback_hours must be filtered out."""
        from datetime import timedelta

        old_item = _fresh_item(title="OpenAI old news", link="https://example.com/old")
        old_item["published_at"] = _NOW - timedelta(hours=200)

        with patch(self._PATCH, return_value=[old_item]):
            # Very tight window — 1 hour, item is 200 h old
            items = get_rss_news(news_lookback_hours=1, news_count=5)

        self.assertEqual(items, [])


if __name__ == "__main__":
    unittest.main()
