"""Tests for AppConfig defaults and env overrides for news item counts."""

from __future__ import annotations

import os
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from ai_digest.config import AppConfig


def _no_load_env() -> None:
    """Stub: prevents .env file from being read during tests."""


class TestAppConfigNewsCountDefaults(unittest.TestCase):
    """from_env() must default to 10 items for both Gemini and RSS fallback paths."""

    def setUp(self) -> None:
        self._load_patcher = patch("ai_digest.config._load_env_from_file", _no_load_env)
        self._load_patcher.start()

    def tearDown(self) -> None:
        self._load_patcher.stop()

    def _from_env(self, **overrides: str) -> AppConfig:
        """Call from_env() with a clean env (no NEWS_COUNT / RSS_FALLBACK_NEWS_COUNT)."""
        base = {
            k: v
            for k, v in os.environ.items()
            if k not in ("NEWS_COUNT", "RSS_FALLBACK_NEWS_COUNT")
        }
        base.update(overrides)
        with patch.dict("os.environ", base, clear=True):
            return AppConfig.from_env()

    def test_news_count_default_is_10(self) -> None:
        cfg = self._from_env()
        self.assertEqual(cfg.news_count, 10)

    def test_rss_fallback_default_is_10(self) -> None:
        cfg = self._from_env()
        self.assertEqual(cfg.rss_fallback_news_count, 10)

    def test_rss_fallback_default_equals_news_count(self) -> None:
        """When RSS_FALLBACK_NEWS_COUNT is unset it mirrors NEWS_COUNT."""
        cfg = self._from_env()
        self.assertEqual(cfg.rss_fallback_news_count, cfg.news_count)

    def test_news_count_env_override(self) -> None:
        cfg = self._from_env(NEWS_COUNT="7")
        self.assertEqual(cfg.news_count, 7)

    def test_rss_fallback_follows_news_count_when_not_set(self) -> None:
        cfg = self._from_env(NEWS_COUNT="6")
        self.assertEqual(cfg.rss_fallback_news_count, 6)

    def test_rss_fallback_env_override_independent(self) -> None:
        cfg = self._from_env(NEWS_COUNT="10", RSS_FALLBACK_NEWS_COUNT="15")
        self.assertEqual(cfg.news_count, 10)
        self.assertEqual(cfg.rss_fallback_news_count, 15)


class TestAppConfigFieldDefault(unittest.TestCase):
    """Direct AppConfig(...) construction must use rss_fallback_news_count=10 as default."""

    def test_rss_fallback_field_default_is_10(self) -> None:
        cfg = AppConfig(
            telegram_bot_token="t",
            telegram_chat_id="c",
            gemini_api_key="k",
            news_count=5,
            news_lookback_hours=72,
            gemini_model="",
            send_marker_path=".marker",
            enforce_kyiv_hour=False,
            target_kyiv_hour_start=8,
            target_kyiv_hour_end=9,
            send_time="08:00",
        )
        self.assertEqual(cfg.rss_fallback_news_count, 10)

    def test_rss_fallback_field_can_be_set_explicitly(self) -> None:
        cfg = AppConfig(
            telegram_bot_token="t",
            telegram_chat_id="c",
            gemini_api_key="k",
            news_count=10,
            news_lookback_hours=72,
            gemini_model="",
            send_marker_path=".marker",
            enforce_kyiv_hour=False,
            target_kyiv_hour_start=8,
            target_kyiv_hour_end=9,
            send_time="08:00",
            rss_fallback_news_count=20,
        )
        self.assertEqual(cfg.rss_fallback_news_count, 20)


class TestRssFallbackPassesOwnCount(unittest.TestCase):
    """DigestService must pass cfg.rss_fallback_news_count to build_rss_message."""

    _SAMPLE_ITEMS = [
        {
            "title": f"News {i}",
            "link": f"https://example.com/{i}",
            "source": "TestSrc",
            "published_at": datetime(2026, 6, 23, tzinfo=timezone.utc),
        }
        for i in range(20)
    ]

    def test_rss_fallback_uses_rss_fallback_news_count(self) -> None:
        from ai_digest.digest.service import DigestService

        cfg = AppConfig(
            telegram_bot_token="t",
            telegram_chat_id="c",
            gemini_api_key="",  # no Gemini key => straight to RSS fallback
            news_count=5,
            news_lookback_hours=72,
            gemini_model="",
            send_marker_path=".test_rss_count",
            enforce_kyiv_hour=False,
            target_kyiv_hour_start=8,
            target_kyiv_hour_end=9,
            send_time="08:00",
            rss_fallback_news_count=12,
        )
        svc = DigestService(cfg)

        with (
            patch.object(svc, "should_skip_scheduled_run", return_value=False),
            patch("ai_digest.digest.service.get_rss_news", return_value=self._SAMPLE_ITEMS),
            patch("ai_digest.digest.service.send_telegram"),
            patch.object(svc, "mark_sent_if_enforcing"),
            patch("ai_digest.digest.service.build_rss_message", return_value="msg") as mock_build,
        ):
            svc.run()

        mock_build.assert_called_once()
        _args, kwargs = mock_build.call_args
        self.assertEqual(kwargs.get("news_count"), 12)

    def test_gemini_prompt_uses_news_count_not_fallback(self) -> None:
        """Gemini prompt must use news_count, not rss_fallback_news_count."""
        from ai_digest.ai.prompts import build_gemini_prompt_from_rss

        items = self._SAMPLE_ITEMS[:5]
        prompt = build_gemini_prompt_from_rss(items, "June 23, 2026", "\n", news_count=10)
        # min(news_count=10, len(items)=5) = 5
        self.assertIn("Select the 5", prompt)


if __name__ == "__main__":
    unittest.main()
