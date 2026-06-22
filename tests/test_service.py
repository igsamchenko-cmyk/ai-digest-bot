"""Tests for ai_digest.digest.service.DigestService.

Covers:
- happy path (Gemini succeeds)
- empty RSS → "no news" Telegram message
- Gemini failure → RSS fallback
- Telegram send call counts
- scheduled-run skip via marker
- --run-once semantics (digest.run_digest shim delegates to service)
- digest.py wrapper calls DigestService
"""

import unittest
from datetime import datetime, timezone
from unittest.mock import MagicMock, Mock, patch

from ai_digest.config import AppConfig
from ai_digest.digest.service import DigestService, run_digest_service

# ── Helpers ───────────────────────────────────────────────────────────────────


def _cfg(
    telegram_bot_token: str = "BOT_TOKEN",
    telegram_chat_id: str = "-100123",
    gemini_api_key: str = "GEMINI_KEY",
    news_count: int = 5,
    news_lookback_hours: int = 72,
    gemini_model: str = "",
    send_marker_path: str = ".test_marker_service",
    enforce_kyiv_hour: bool = False,
    target_kyiv_hour_start: int = 8,
    target_kyiv_hour_end: int = 9,
    send_time: str = "08:00",
) -> AppConfig:
    """Build an AppConfig suitable for unit tests."""
    return AppConfig(
        telegram_bot_token=telegram_bot_token,
        telegram_chat_id=telegram_chat_id,
        gemini_api_key=gemini_api_key,
        news_count=news_count,
        news_lookback_hours=news_lookback_hours,
        gemini_model=gemini_model,
        send_marker_path=send_marker_path,
        enforce_kyiv_hour=enforce_kyiv_hour,
        target_kyiv_hour_start=target_kyiv_hour_start,
        target_kyiv_hour_end=target_kyiv_hour_end,
        send_time=send_time,
    )


_SAMPLE_ITEMS = [
    {
        "title": "ChatGPT update",
        "link": "https://example.com/1",
        "source": "TechCrunch",
        "published_at": datetime(2026, 6, 21, 10, 0, tzinfo=timezone.utc),
        "language": "en",
    },
    {
        "title": "Gemini оновлення",
        "link": "https://ain.ua/2",
        "source": "AIN.UA",
        "published_at": datetime(2026, 6, 21, 9, 0, tzinfo=timezone.utc),
        "language": "uk",
    },
]


# ── Tests ─────────────────────────────────────────────────────────────────────


class TestDigestServiceHappyPath(unittest.TestCase):
    """run() completes the Gemini path and calls send_telegram once."""

    def test_model_override_comes_from_config(self):
        """DigestService.run() must pass cfg.gemini_model as model_override to gemini_call."""
        cfg = _cfg(gemini_model="my-custom-model")
        svc = DigestService(cfg)

        mock_resp = Mock()
        mock_resp.text = '{"summary": "s", "news": [{"id": 1, "title": "T", "category": "LLM", "importance": "high", "summary": "S", "source": "X", "why_matters": "W"}]}'

        with (
            patch.object(svc, "should_skip_scheduled_run", return_value=False),
            patch("ai_digest.digest.service.get_rss_news", return_value=_SAMPLE_ITEMS),
            patch("ai_digest.digest.service.genai"),
            patch("ai_digest.digest.service.gemini_call", return_value=mock_resp) as mock_call,
            patch("ai_digest.digest.service.send_telegram"),
            patch.object(svc, "mark_sent_if_enforcing"),
        ):
            svc.run()

        _, kwargs = mock_call.call_args
        self.assertEqual(kwargs.get("model_override"), "my-custom-model")

    def test_gemini_path_calls_send_telegram_once(self):
        cfg = _cfg()
        svc = DigestService(cfg)

        mock_resp = Mock()
        mock_resp.text = '{"summary": "Today in AI", "news": [{"id": 1, "title": "ChatGPT update", "category": "LLM", "importance": "high", "summary": "Big update", "source": "TC", "why_matters": "Matters"}]}'

        with (
            patch.object(svc, "should_skip_scheduled_run", return_value=False),
            patch("ai_digest.digest.service.get_rss_news", return_value=_SAMPLE_ITEMS),
            patch("ai_digest.digest.service.genai") as mock_genai,
            patch("ai_digest.digest.service.gemini_call", return_value=mock_resp),
            patch("ai_digest.digest.service.send_telegram") as mock_send,
            patch.object(svc, "mark_sent_if_enforcing"),
        ):
            mock_genai.Client.return_value = MagicMock()
            svc.run()

        mock_send.assert_called_once()
        args, kwargs = mock_send.call_args
        self.assertEqual(kwargs.get("token") or args[1], cfg.telegram_bot_token)
        self.assertEqual(kwargs.get("chat_id") or args[2], cfg.telegram_chat_id)

    def test_gemini_path_marks_sent(self):
        cfg = _cfg()
        svc = DigestService(cfg)

        mock_resp = Mock()
        mock_resp.text = '{"summary": "s", "news": [{"id": 1, "title": "T", "category": "LLM", "importance": "high", "summary": "S", "source": "X", "why_matters": "W"}]}'

        mark_mock = Mock()
        with (
            patch.object(svc, "should_skip_scheduled_run", return_value=False),
            patch("ai_digest.digest.service.get_rss_news", return_value=_SAMPLE_ITEMS),
            patch("ai_digest.digest.service.genai"),
            patch("ai_digest.digest.service.gemini_call", return_value=mock_resp),
            patch("ai_digest.digest.service.send_telegram"),
            patch.object(svc, "mark_sent_if_enforcing", mark_mock),
        ):
            svc.run()

        mark_mock.assert_called_once()


class TestDigestServiceEmptyRss(unittest.TestCase):
    """When RSS returns no items, service sends the 'no news' message."""

    def test_empty_rss_sends_no_news_message(self):
        cfg = _cfg(gemini_api_key="")  # Gemini disabled so we fall straight to RSS path
        svc = DigestService(cfg)

        with (
            patch.object(svc, "should_skip_scheduled_run", return_value=False),
            patch("ai_digest.digest.service.get_rss_news", return_value=[]),
            patch("ai_digest.digest.service.send_telegram") as mock_send,
            patch.object(svc, "mark_sent_if_enforcing"),
        ):
            svc.run()

        mock_send.assert_called_once()
        sent_text = mock_send.call_args[0][0]
        self.assertIn("Не вдалося знайти свіжих новин", sent_text)

    def test_empty_rss_with_gemini_key_still_sends_no_news(self):
        """When Gemini is enabled but no items found, skip Gemini and send 'no news'."""
        cfg = _cfg()  # gemini_api_key set
        svc = DigestService(cfg)

        with (
            patch.object(svc, "should_skip_scheduled_run", return_value=False),
            patch("ai_digest.digest.service.get_rss_news", return_value=[]),
            patch("ai_digest.digest.service.send_telegram") as mock_send,
            patch("ai_digest.digest.service.gemini_call") as mock_gemini,
            patch.object(svc, "mark_sent_if_enforcing"),
        ):
            svc.run()

        # Gemini must NOT be called when there are no items to summarise
        mock_gemini.assert_not_called()
        mock_send.assert_called_once()
        self.assertIn("Не вдалося знайти свіжих новин", mock_send.call_args[0][0])


class TestDigestServiceGeminiFallback(unittest.TestCase):
    """When Gemini fails, service falls back to the RSS digest."""

    def test_gemini_exception_triggers_rss_fallback(self):
        cfg = _cfg()
        svc = DigestService(cfg)

        with (
            patch.object(svc, "should_skip_scheduled_run", return_value=False),
            patch("ai_digest.digest.service.get_rss_news", return_value=_SAMPLE_ITEMS),
            patch("ai_digest.digest.service.genai"),
            patch(
                "ai_digest.digest.service.gemini_call",
                side_effect=RuntimeError("quota exceeded"),
            ),
            patch("ai_digest.digest.service.send_telegram") as mock_send,
            patch.object(svc, "mark_sent_if_enforcing"),
        ):
            svc.run()

        # Must still send — via RSS fallback
        mock_send.assert_called_once()

    def test_gemini_failure_send_count_is_one(self):
        """Fallback path must not double-send."""
        cfg = _cfg()
        svc = DigestService(cfg)

        with (
            patch.object(svc, "should_skip_scheduled_run", return_value=False),
            patch("ai_digest.digest.service.get_rss_news", return_value=_SAMPLE_ITEMS),
            patch("ai_digest.digest.service.genai"),
            patch("ai_digest.digest.service.gemini_call", side_effect=Exception("fail")),
            patch("ai_digest.digest.service.send_telegram") as mock_send,
            patch.object(svc, "mark_sent_if_enforcing"),
        ):
            svc.run()

        self.assertEqual(mock_send.call_count, 1)


class TestDigestServiceMarkerSkip(unittest.TestCase):
    """Scheduled-run skip logic via the dedup marker."""

    def test_skips_when_marker_matches_today(self):
        cfg = _cfg(enforce_kyiv_hour=True, send_marker_path=".test_marker_skip")
        svc = DigestService(cfg)
        today = datetime.now().strftime("%Y-%m-%d")

        with (
            patch.object(svc, "read_send_marker", return_value=today),
            patch("ai_digest.digest.service.get_rss_news") as mock_rss,
            patch("ai_digest.digest.service.send_telegram") as mock_send,
        ):
            # Simulate being inside the send window
            now = datetime.now().replace(hour=cfg.target_kyiv_hour_start)
            result = svc.should_skip_scheduled_run(now)

        self.assertTrue(result)
        mock_rss.assert_not_called()
        mock_send.assert_not_called()

    def test_skips_outside_send_window(self):
        cfg = _cfg(enforce_kyiv_hour=True, target_kyiv_hour_start=8, target_kyiv_hour_end=9)
        svc = DigestService(cfg)
        # Hour 3 is outside [8, 9]
        now = datetime.now().replace(hour=3)
        self.assertTrue(svc.should_skip_scheduled_run(now))

    def test_does_not_skip_inside_window_no_marker(self):
        cfg = _cfg(enforce_kyiv_hour=True, target_kyiv_hour_start=8, target_kyiv_hour_end=9)
        svc = DigestService(cfg)
        now = datetime.now().replace(hour=8)
        with patch.object(svc, "read_send_marker", return_value=""):
            self.assertFalse(svc.should_skip_scheduled_run(now))

    def test_no_enforcement_never_skips(self):
        cfg = _cfg(enforce_kyiv_hour=False)
        svc = DigestService(cfg)
        # Any hour, any marker — must never skip
        now = datetime.now().replace(hour=3)
        with patch.object(svc, "read_send_marker", return_value=now.strftime("%Y-%m-%d")):
            self.assertFalse(svc.should_skip_scheduled_run(now))

    def test_run_skips_entirely_when_should_skip(self):
        cfg = _cfg()
        svc = DigestService(cfg)
        with (
            patch.object(svc, "should_skip_scheduled_run", return_value=True),
            patch("ai_digest.digest.service.get_rss_news") as mock_rss,
            patch("ai_digest.digest.service.send_telegram") as mock_send,
        ):
            svc.run()

        mock_rss.assert_not_called()
        mock_send.assert_not_called()


class TestRunDigestServiceWrapper(unittest.TestCase):
    """run_digest_service() is a thin wrapper around DigestService.run()."""

    def test_run_digest_service_creates_service_and_calls_run(self):
        cfg = _cfg()
        with patch("ai_digest.digest.service.DigestService") as MockSvc:
            run_digest_service(cfg)
        MockSvc.assert_called_once_with(cfg)
        MockSvc.return_value.run.assert_called_once()


class TestDigestShim(unittest.TestCase):
    """digest.run_digest() delegates to service; digest.main delegates to cli."""

    def test_run_digest_shim_calls_service(self):
        import digest

        with patch("digest._run_digest_service") as mock_svc_fn:
            digest.run_digest()
        mock_svc_fn.assert_called_once_with(digest._config)

    def test_digest_main_is_cli_main(self):
        """digest.main must be the same object as ai_digest.cli.main."""
        import digest
        from ai_digest.cli import main as cli_main

        self.assertIs(digest.main, cli_main)

    def test_run_once_flag_calls_run_digest_service(self):
        """python digest.py --run-once → cli.main → run_digest_service."""
        import digest

        with (
            patch("ai_digest.cli.run_digest_service") as mock_run,
            patch("sys.argv", ["digest.py", "--run-once"]),
        ):
            digest.main()

        mock_run.assert_called_once()

    def test_run_once_env_var_calls_run_digest_service(self):
        """RUN_ONCE=true → cli.main → run_digest_service."""
        import digest

        with (
            patch("ai_digest.cli.run_digest_service") as mock_run,
            patch.dict("os.environ", {"RUN_ONCE": "true"}),
            patch("sys.argv", ["digest.py"]),
        ):
            digest.main()

        mock_run.assert_called_once()


if __name__ == "__main__":
    unittest.main()
