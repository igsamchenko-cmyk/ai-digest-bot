"""Tests for logging activation, secret redaction, and run summary.

Covers:
- cli.main() configures logging with the bot token from config
- SecretRedactingFilter scrubs the token from log records once attached
- DigestService.run() emits exactly one RUN SUMMARY line (gemini path)
"""

import logging
import unittest
from datetime import datetime, timezone
from unittest.mock import MagicMock, Mock, patch

from ai_digest.config import AppConfig
from ai_digest.digest.service import DigestService
from ai_digest.logging_setup import SecretRedactingFilter, setup_logging


def _cfg(**overrides) -> AppConfig:
    base = dict(
        telegram_bot_token="BOT_TOKEN",
        telegram_chat_id="-100123",
        gemini_api_key="GEMINI_KEY",
        news_count=5,
        news_lookback_hours=72,
        gemini_model="",
        send_marker_path=".test_marker_logging",
        enforce_kyiv_hour=False,
        target_kyiv_hour_start=8,
        target_kyiv_hour_end=9,
        send_time="08:00",
    )
    base.update(overrides)
    return AppConfig(**base)


_SAMPLE_ITEMS = [
    {
        "title": "ChatGPT update",
        "link": "https://example.com/1",
        "source": "TechCrunch",
        "published_at": datetime(2026, 6, 21, 10, 0, tzinfo=timezone.utc),
        "language": "en",
    }
]


class TestCliConfiguresLogging(unittest.TestCase):
    """main() must activate logging using the token from AppConfig."""

    def test_cli_main_configures_logging(self):
        captured = {}

        def fake_setup(level=logging.INFO, token=""):
            captured["level"] = level
            captured["token"] = token

        with (
            patch("ai_digest.cli.setup_logging", side_effect=fake_setup),
            patch("ai_digest.cli.run_digest_service"),
            patch("ai_digest.cli.AppConfig.from_env", return_value=_cfg()),
            patch("sys.argv", ["ai-digest", "--run-once"]),
        ):
            from ai_digest.cli import main

            main()

        self.assertEqual(captured.get("token"), "BOT_TOKEN")
        self.assertEqual(captured.get("level"), logging.INFO)


class TestSecretRedactionActive(unittest.TestCase):
    """Once setup_logging attaches the filter, the token must be scrubbed."""

    def test_secret_redaction_active(self):
        token = "123456789:ABCdefGHIjklMNOpqrSTUvwxYZ0123456789"
        setup_logging(level=logging.INFO, token=token)
        try:
            record = logging.LogRecord(
                name="t",
                level=logging.INFO,
                pathname=__file__,
                lineno=1,
                msg="sending with token %s",
                args=(token,),
                exc_info=None,
            )
            handler = logging.getLogger().handlers[0]
            for flt in handler.filters:
                flt.filter(record)
            rendered = record.getMessage()
            self.assertNotIn(token, rendered)
            self.assertIn("[REDACTED]", rendered)
        finally:
            logging.getLogger().handlers.clear()

    def test_filter_scrubs_token_directly(self):
        token = "987654321:ZYXwvuTSRqponMLKjihGFEdcba9876543210"
        flt = SecretRedactingFilter(token)
        record = logging.LogRecord(
            name="t",
            level=logging.INFO,
            pathname=__file__,
            lineno=1,
            msg=token,
            args=None,
            exc_info=None,
        )
        flt.filter(record)
        self.assertEqual(record.getMessage(), "[REDACTED]")


class TestRunSummary(unittest.TestCase):
    """run() must log exactly one RUN SUMMARY line describing the outcome."""

    def test_run_logs_summary_gemini_path(self):
        cfg = _cfg()
        svc = DigestService(cfg)

        mock_resp = Mock()
        mock_resp.text = (
            '{"summary": "s", "news": [{"id": 1, "title": "T", "category": "LLM",'
            ' "importance": "high", "summary": "S", "source": "X", "why_matters": "W"}]}'
        )

        with (
            patch.object(svc, "should_skip_scheduled_run", return_value=False),
            patch("ai_digest.digest.service.get_rss_news", return_value=_SAMPLE_ITEMS),
            patch("ai_digest.digest.service.genai") as mock_genai,
            patch("ai_digest.digest.service.gemini_call", return_value=mock_resp),
            patch("ai_digest.digest.service.send_telegram"),
            patch.object(svc, "mark_sent_if_enforcing"),
            self.assertLogs("ai_digest.digest.service", level="INFO") as cm,
        ):
            mock_genai.Client.return_value = MagicMock()
            svc.run()

        summaries = [m for m in cm.output if "RUN SUMMARY" in m]
        self.assertEqual(len(summaries), 1)
        self.assertIn("path=gemini", summaries[0])
        self.assertIn("sent=true", summaries[0])

    def test_run_logs_summary_skipped_path(self):
        cfg = _cfg()
        svc = DigestService(cfg)
        with (
            patch.object(svc, "should_skip_scheduled_run", return_value=True),
            self.assertLogs("ai_digest.digest.service", level="INFO") as cm,
        ):
            svc.run()
        summaries = [m for m in cm.output if "RUN SUMMARY" in m]
        self.assertEqual(len(summaries), 1)
        self.assertIn("path=skipped", summaries[0])
        self.assertIn("sent=false", summaries[0])


if __name__ == "__main__":
    unittest.main()


class TestSecretRedactingFilterArgTypes(unittest.TestCase):
    """SecretRedactingFilter must not corrupt non-string logging args."""

    def test_integer_arg_preserved_with_percent_d(self):
        """%d format with an integer arg must not raise after filtering."""
        token = "111111111:AABBccDDeeFFggHHiiJJkkLLmmNNooP12345"
        flt = SecretRedactingFilter(token)
        record = logging.LogRecord(
            name="t",
            level=logging.INFO,
            pathname=__file__,
            lineno=1,
            msg="RUN SUMMARY: rss_items=%d path=%s sent=%s",
            args=(20, "gemini", "true"),
            exc_info=None,
        )
        flt.filter(record)
        # Must not raise TypeError - integer must stay integer
        msg = record.getMessage()
        self.assertEqual(msg, "RUN SUMMARY: rss_items=20 path=gemini sent=true")

    def test_string_arg_with_token_is_redacted(self):
        """String args that contain the token must be scrubbed."""
        token = "222222222:AABBccDDeeFFggHHiiJJkkLLmmNNooP12345"
        flt = SecretRedactingFilter(token)
        record = logging.LogRecord(
            name="t",
            level=logging.INFO,
            pathname=__file__,
            lineno=1,
            msg="sending to url %s",
            args=(f"https://api.telegram.org/bot{token}/sendMessage",),
            exc_info=None,
        )
        flt.filter(record)
        msg = record.getMessage()
        self.assertNotIn(token, msg)
        self.assertIn("[REDACTED]", msg)

    def test_token_in_message_string_is_redacted(self):
        """Token embedded directly in record.msg (no args) must be scrubbed."""
        token = "333333333:AABBccDDeeFFggHHiiJJkkLLmmNNooP12345"
        flt = SecretRedactingFilter(token)
        record = logging.LogRecord(
            name="t",
            level=logging.INFO,
            pathname=__file__,
            lineno=1,
            msg=f"token={token}",
            args=None,
            exc_info=None,
        )
        flt.filter(record)
        self.assertNotIn(token, record.getMessage())
        self.assertIn("[REDACTED]", record.getMessage())

    def test_run_summary_emits_clean_info_line(self):
        """When setup_logging is active, RUN SUMMARY must appear as clean INFO."""
        token = "444444444:AABBccDDeeFFggHHiiJJkkLLmmNNooP12345"
        setup_logging(level=logging.INFO, token=token)
        logger = logging.getLogger("test.run_summary")
        try:
            with self.assertLogs("test.run_summary", level="INFO") as cm:
                logger.info(
                    "RUN SUMMARY: rss_items=%d path=%s sent=%s",
                    42,
                    "gemini",
                    "true",
                )
            self.assertEqual(len(cm.output), 1)
            self.assertIn("RUN SUMMARY", cm.output[0])
            self.assertIn("rss_items=42", cm.output[0])
            self.assertIn("path=gemini", cm.output[0])
            self.assertIn("sent=true", cm.output[0])
        finally:
            logging.getLogger().handlers.clear()

    def test_non_string_args_types_unchanged(self):
        """Filter must leave int, float args with their original types."""
        token = "555555555:AABBccDDeeFFggHHiiJJkkLLmmNNooP12345"
        flt = SecretRedactingFilter(token)
        record = logging.LogRecord(
            name="t",
            level=logging.INFO,
            pathname=__file__,
            lineno=1,
            msg="%d %.2f %s",
            args=(7, 3.14, "hello"),
            exc_info=None,
        )
        flt.filter(record)
        assert isinstance(record.args, tuple)
        self.assertIsInstance(record.args[0], int)
        self.assertIsInstance(record.args[1], float)
        self.assertIsInstance(record.args[2], str)
