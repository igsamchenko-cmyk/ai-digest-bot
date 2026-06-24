"""Tests for sort_news_by_importance (importance-aware ordering).

Coverage:
  A. high before medium, medium before low.
  B. Unknown importance goes last.
  C. Sort is stable within the same importance group.
  D. Links are preserved after sorting.
  E. Integration: Gemini path calls sort before build_gemini_message.
"""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from ai_digest.ai.parser import sort_news_by_importance

# ─── helpers ──────────────────────────────────────────────────────────────────


def _item(importance: str, title: str, link: str = "") -> dict:
    return {
        "id": 1,
        "title": title,
        "importance": importance,
        "link": link or f"https://example.com/{title.replace(' ', '-')}",
        "source": "TestSource",
    }


# ─── A: high → medium → low ──────────────────────────────────────────────────


class TestBasicOrdering(unittest.TestCase):
    def setUp(self) -> None:
        # Intentionally shuffled: low, high, medium
        self.news = [
            _item("low", "Low story"),
            _item("high", "High story"),
            _item("medium", "Medium story"),
        ]
        self.result = sort_news_by_importance(self.news)

    def test_high_comes_first(self) -> None:
        self.assertEqual(self.result[0]["importance"], "high")

    def test_medium_comes_second(self) -> None:
        self.assertEqual(self.result[1]["importance"], "medium")

    def test_low_comes_third(self) -> None:
        self.assertEqual(self.result[2]["importance"], "low")

    def test_all_items_preserved(self) -> None:
        self.assertEqual(len(self.result), 3)

    def test_original_list_not_mutated(self) -> None:
        titles_before = [n["title"] for n in self.news]
        sort_news_by_importance(self.news)
        self.assertEqual([n["title"] for n in self.news], titles_before)


# ─── B: unknown importance goes last ─────────────────────────────────────────


class TestUnknownImportance(unittest.TestCase):
    def test_unknown_string_goes_last(self) -> None:
        news = [
            _item("unknown_value", "Weird story"),
            _item("high", "High story"),
        ]
        result = sort_news_by_importance(news)
        self.assertEqual(result[0]["importance"], "high")
        self.assertEqual(result[1]["importance"], "unknown_value")

    def test_empty_string_importance_goes_last(self) -> None:
        news = [
            _item("", "No importance"),
            _item("medium", "Medium story"),
        ]
        result = sort_news_by_importance(news)
        self.assertEqual(result[0]["importance"], "medium")

    def test_missing_importance_key_goes_last(self) -> None:
        news = [
            {"id": 1, "title": "No key", "link": "https://x.com/1", "source": "S"},
            _item("low", "Low story"),
        ]
        result = sort_news_by_importance(news)
        self.assertEqual(result[0]["importance"], "low")
        self.assertNotIn("importance", result[1])

    def test_none_importance_goes_last(self) -> None:
        news = [
            {
                "id": 1,
                "title": "None imp",
                "importance": None,
                "link": "https://x.com/1",
                "source": "S",
            },
            _item("high", "High story"),
        ]
        result = sort_news_by_importance(news)
        self.assertEqual(result[0]["importance"], "high")
        self.assertIsNone(result[1]["importance"])

    def test_unknown_comes_after_low(self) -> None:
        news = [
            _item("unknown_xyz", "Unknown story"),
            _item("low", "Low story"),
        ]
        result = sort_news_by_importance(news)
        self.assertEqual(result[0]["importance"], "low")
        self.assertEqual(result[1]["importance"], "unknown_xyz")


# ─── C: stability within same importance group ────────────────────────────────


class TestStableSort(unittest.TestCase):
    def test_two_high_items_keep_original_order(self) -> None:
        news = [
            _item("high", "High first"),
            _item("high", "High second"),
        ]
        result = sort_news_by_importance(news)
        self.assertEqual(result[0]["title"], "High first")
        self.assertEqual(result[1]["title"], "High second")

    def test_two_medium_items_keep_original_order(self) -> None:
        news = [
            _item("medium", "Med A"),
            _item("medium", "Med B"),
        ]
        result = sort_news_by_importance(news)
        self.assertEqual(result[0]["title"], "Med A")
        self.assertEqual(result[1]["title"], "Med B")

    def test_multiple_same_importance_keeps_order(self) -> None:
        titles = [f"Story {i}" for i in range(5)]
        news = [_item("low", t) for t in titles]
        result = sort_news_by_importance(news)
        self.assertEqual([r["title"] for r in result], titles)

    def test_mixed_with_stable_groups(self) -> None:
        news = [
            _item("medium", "Med 1"),
            _item("high", "High 1"),
            _item("medium", "Med 2"),
            _item("high", "High 2"),
            _item("low", "Low 1"),
        ]
        result = sort_news_by_importance(news)
        self.assertEqual(result[0]["title"], "High 1")
        self.assertEqual(result[1]["title"], "High 2")
        self.assertEqual(result[2]["title"], "Med 1")
        self.assertEqual(result[3]["title"], "Med 2")
        self.assertEqual(result[4]["title"], "Low 1")


# ─── D: links preserved after sorting ────────────────────────────────────────


class TestLinksPreserved(unittest.TestCase):
    def setUp(self) -> None:
        self.news = [
            _item("low", "Low story", "https://example.com/low"),
            _item("high", "High story", "https://example.com/high"),
            _item("medium", "Medium story", "https://example.com/medium"),
        ]
        self.result = sort_news_by_importance(self.news)

    def test_high_item_retains_correct_link(self) -> None:
        high = next(r for r in self.result if r["importance"] == "high")
        self.assertEqual(high["link"], "https://example.com/high")

    def test_medium_item_retains_correct_link(self) -> None:
        med = next(r for r in self.result if r["importance"] == "medium")
        self.assertEqual(med["link"], "https://example.com/medium")

    def test_low_item_retains_correct_link(self) -> None:
        low = next(r for r in self.result if r["importance"] == "low")
        self.assertEqual(low["link"], "https://example.com/low")

    def test_all_links_present(self) -> None:
        links = {r["link"] for r in self.result}
        self.assertIn("https://example.com/high", links)
        self.assertIn("https://example.com/medium", links)
        self.assertIn("https://example.com/low", links)

    def test_source_field_preserved(self) -> None:
        for item in self.result:
            self.assertEqual(item["source"], "TestSource")


# ─── E: integration — Gemini path sorts before build_gemini_message ───────────


class TestGeminiPathIntegration(unittest.TestCase):
    """Verify DigestService.run() applies importance ordering before Telegram send."""

    def _make_config(self) -> object:
        cfg = MagicMock()
        cfg.gemini_api_key = "fake-key"
        cfg.gemini_model = ""
        cfg.news_lookback_hours = 48
        cfg.news_count = 10
        cfg.rss_fallback_news_count = 10
        cfg.telegram_bot_token = "fake-token"
        cfg.telegram_chat_id = "fake-chat"
        cfg.enforce_kyiv_hour = False
        cfg.send_marker_path = "/tmp/marker"
        return cfg

    def _rss_items(self) -> list[dict]:
        from datetime import datetime, timezone

        return [
            {
                "title": f"Story {i}",
                "link": f"https://example.com/{i}",
                "source": f"Source{i}",
                "lang": "en",
                "published_at": datetime(2026, 6, 24, 9, 0, tzinfo=timezone.utc),
            }
            for i in range(1, 4)
        ]

    def _gemini_json(self) -> str:
        import json

        # Gemini returns them in order: low, high, medium — should be reordered
        return json.dumps(
            {
                "summary": "Test summary",
                "news": [
                    {"id": 1, "title": "Low story", "importance": "low", "category": "LLM"},
                    {"id": 2, "title": "High story", "importance": "high", "category": "LLM"},
                    {"id": 3, "title": "Medium story", "importance": "medium", "category": "LLM"},
                ],
            }
        )

    def test_gemini_path_sends_high_before_medium_before_low(self) -> None:
        """After sort, the message builder sees high → medium → low order."""
        captured_news: list[list[dict]] = []

        def fake_build_gemini_message(data: dict, today_uk: str) -> str:
            captured_news.append(list(data["news"]))
            return "fake-message"

        cfg = self._make_config()
        items = self._rss_items()
        gemini_resp = MagicMock()
        gemini_resp.text = self._gemini_json()

        with (
            patch("ai_digest.digest.service.get_rss_news", return_value=items),
            patch("ai_digest.digest.service.genai.Client"),
            patch("ai_digest.digest.service.gemini_call", return_value=gemini_resp),
            patch(
                "ai_digest.digest.service.build_gemini_message",
                side_effect=fake_build_gemini_message,
            ),
            patch("ai_digest.digest.service.send_telegram"),
            patch("builtins.open", unittest.mock.mock_open()),
        ):
            from ai_digest.digest.service import DigestService

            DigestService(cfg).run()

        self.assertEqual(len(captured_news), 1, "build_gemini_message should be called once")
        news = captured_news[0]
        self.assertEqual(len(news), 3)
        self.assertEqual(news[0]["importance"], "high")
        self.assertEqual(news[1]["importance"], "medium")
        self.assertEqual(news[2]["importance"], "low")

    def test_gemini_path_links_intact_after_sort(self) -> None:
        """Each item's link must match the rss_items entry after sorting."""
        captured_news: list[list[dict]] = []

        def fake_build(data: dict, today_uk: str) -> str:
            captured_news.append(list(data["news"]))
            return "msg"

        cfg = self._make_config()
        items = self._rss_items()
        gemini_resp = MagicMock()
        gemini_resp.text = self._gemini_json()

        with (
            patch("ai_digest.digest.service.get_rss_news", return_value=items),
            patch("ai_digest.digest.service.genai.Client"),
            patch("ai_digest.digest.service.gemini_call", return_value=gemini_resp),
            patch("ai_digest.digest.service.build_gemini_message", side_effect=fake_build),
            patch("ai_digest.digest.service.send_telegram"),
            patch("builtins.open", unittest.mock.mock_open()),
        ):
            from ai_digest.digest.service import DigestService

            DigestService(cfg).run()

        news = captured_news[0]
        # id=2 → items[1] → link https://example.com/2
        high_item = next(n for n in news if n["importance"] == "high")
        self.assertEqual(high_item["link"], "https://example.com/2")
        # id=1 → items[0] → link https://example.com/1
        low_item = next(n for n in news if n["importance"] == "low")
        self.assertEqual(low_item["link"], "https://example.com/1")


if __name__ == "__main__":
    unittest.main()
