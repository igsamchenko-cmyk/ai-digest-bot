"""Tests for structured RUN SUMMARY and run_summary.json artifact.

Covers:
- A. Gemini path: log contains new fields, JSON written and valid
- B. RSS fallback path: path=rss, selected count
- C. Skipped path: path=skipped, sent=false, selected=0
- D. Error path: path=error, sent=false, error_type non-empty
- E. Best-effort JSON write: OSError does not crash the run
"""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from datetime import datetime, timezone
from unittest.mock import Mock, patch

from ai_digest.config import AppConfig
from ai_digest.digest.service import DigestService


def _cfg(
    telegram_bot_token: str = "BOT_TOKEN",
    telegram_chat_id: str = "-100123",
    gemini_api_key: str = "GEMINI_KEY",
    news_count: int = 5,
    news_lookback_hours: int = 72,
    gemini_model: str = "gemini-2.5-flash-lite",
    send_marker_path: str = ".test_marker_summary",
    enforce_kyiv_hour: bool = False,
    target_kyiv_hour_start: int = 8,
    target_kyiv_hour_end: int = 9,
    send_time: str = "08:00",
    use_gemini: bool = True,
    rss_fallback_news_count: int = 3,
) -> AppConfig:
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
        use_gemini=use_gemini,
        rss_fallback_news_count=rss_fallback_news_count,
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
    {
        "title": "Third item",
        "link": "https://example.com/3",
        "source": "Wired",
        "published_at": datetime(2026, 6, 21, 8, 0, tzinfo=timezone.utc),
        "language": "en",
    },
]


def _gemini_resp(news_count: int = 2) -> Mock:
    news = [
        {
            "id": i + 1,
            "title": f"Title {i + 1}",
            "category": "LLM",
            "importance": "high",
            "summary": "S",
            "source": "X",
            "why_matters": "W",
            "link": f"https://example.com/{i + 1}",
        }
        for i in range(news_count)
    ]
    m = Mock()
    m.text = json.dumps({"summary": "Today in AI", "news": news})
    return m


class TestRunSummaryGeminiPath(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()
        self._orig = os.getcwd()
        os.chdir(self._tmpdir)

    def tearDown(self):
        os.chdir(self._orig)

    def test_log_contains_required_fields(self):
        cfg = _cfg()
        svc = DigestService(cfg)
        with (
            patch.object(svc, "should_skip_scheduled_run", return_value=False),
            patch("ai_digest.digest.service.get_rss_news", return_value=_SAMPLE_ITEMS),
            patch("ai_digest.digest.service.genai"),
            patch("ai_digest.digest.service.gemini_call", return_value=_gemini_resp(2)),
            patch("ai_digest.digest.service.send_telegram"),
            patch.object(svc, "mark_sent_if_enforcing"),
            self.assertLogs("ai_digest.digest.service", level="INFO") as cm,
        ):
            svc.run()
        lines = [l for l in cm.output if "RUN SUMMARY" in l]
        self.assertTrue(lines)
        line = lines[-1]
        self.assertIn("path=gemini", line)
        self.assertIn("sent=true", line)
        self.assertIn("selected=", line)
        self.assertIn("duration_ms=", line)

    def test_json_written_valid_and_correct(self):
        cfg = _cfg()
        svc = DigestService(cfg)
        with (
            patch.object(svc, "should_skip_scheduled_run", return_value=False),
            patch("ai_digest.digest.service.get_rss_news", return_value=_SAMPLE_ITEMS),
            patch("ai_digest.digest.service.genai"),
            patch("ai_digest.digest.service.gemini_call", return_value=_gemini_resp(2)),
            patch("ai_digest.digest.service.send_telegram"),
            patch.object(svc, "mark_sent_if_enforcing"),
        ):
            svc.run()
        self.assertTrue(os.path.exists("run_summary.json"))
        with open("run_summary.json", encoding="utf-8") as fh:
            data = json.load(fh)
        self.assertEqual(data["path"], "gemini")
        self.assertTrue(data["sent"])
        self.assertEqual(data["selected"], 2)
        self.assertGreaterEqual(data["duration_ms"], 0)
        self.assertIsInstance(data["duration_ms"], int)
        self.assertIn("rss_items", data)
        self.assertIn("error_type", data)
        self.assertIn("model", data)
        self.assertIs(data["gemini_enabled"], True)
        self.assertEqual(data["fallback_reason"], "")


class TestRunSummaryRssPath(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()
        self._orig = os.getcwd()
        os.chdir(self._tmpdir)

    def tearDown(self):
        os.chdir(self._orig)

    def test_rss_path_json(self):
        cfg = _cfg(rss_fallback_news_count=2)
        svc = DigestService(cfg)
        with (
            patch.object(svc, "should_skip_scheduled_run", return_value=False),
            patch("ai_digest.digest.service.get_rss_news", return_value=_SAMPLE_ITEMS),
            patch("ai_digest.digest.service.genai"),
            patch("ai_digest.digest.service.gemini_call", side_effect=RuntimeError("quota")),
            patch("ai_digest.digest.service.send_telegram"),
            patch.object(svc, "mark_sent_if_enforcing"),
        ):
            svc.run()
        self.assertTrue(os.path.exists("run_summary.json"))
        with open("run_summary.json", encoding="utf-8") as fh:
            data = json.load(fh)
        self.assertEqual(data["path"], "rss")
        self.assertTrue(data["sent"])
        self.assertEqual(data["selected"], 2)
        self.assertIs(data["gemini_enabled"], True)
        self.assertEqual(data["fallback_reason"], "")

    def test_rss_only_json_marks_gemini_disabled(self):
        cfg = _cfg(use_gemini=False, rss_fallback_news_count=2)
        svc = DigestService(cfg)
        with (
            patch.object(svc, "should_skip_scheduled_run", return_value=False),
            patch("ai_digest.digest.service.get_rss_news", return_value=_SAMPLE_ITEMS),
            patch("ai_digest.digest.service.gemini_call") as mock_gemini,
            patch("ai_digest.digest.service.send_telegram"),
            patch.object(svc, "mark_sent_if_enforcing"),
        ):
            svc.run()
        mock_gemini.assert_not_called()
        self.assertTrue(os.path.exists("run_summary.json"))
        with open("run_summary.json", encoding="utf-8") as fh:
            data = json.load(fh)
        self.assertEqual(data["path"], "rss")
        self.assertTrue(data["sent"])
        self.assertEqual(data["selected"], 2)
        self.assertIs(data["gemini_enabled"], False)
        self.assertEqual(data["fallback_reason"], "gemini_disabled")

    def test_rss_path_log(self):
        cfg = _cfg(rss_fallback_news_count=2)
        svc = DigestService(cfg)
        with (
            patch.object(svc, "should_skip_scheduled_run", return_value=False),
            patch("ai_digest.digest.service.get_rss_news", return_value=_SAMPLE_ITEMS),
            patch("ai_digest.digest.service.genai"),
            patch("ai_digest.digest.service.gemini_call", side_effect=RuntimeError("quota")),
            patch("ai_digest.digest.service.send_telegram"),
            patch.object(svc, "mark_sent_if_enforcing"),
            self.assertLogs("ai_digest.digest.service", level="INFO") as cm,
        ):
            svc.run()
        lines = [l for l in cm.output if "RUN SUMMARY" in l]
        self.assertTrue(lines)
        self.assertIn("path=rss", lines[-1])
        self.assertIn("sent=true", lines[-1])


class TestRunSummarySkippedPath(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()
        self._orig = os.getcwd()
        os.chdir(self._tmpdir)

    def tearDown(self):
        os.chdir(self._orig)

    def test_skipped_json(self):
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
        self.assertTrue(os.path.exists("run_summary.json"))
        with open("run_summary.json", encoding="utf-8") as fh:
            data = json.load(fh)
        self.assertEqual(data["path"], "skipped")
        self.assertFalse(data["sent"])
        self.assertEqual(data["selected"], 0)

    def test_skipped_log(self):
        cfg = _cfg()
        svc = DigestService(cfg)
        with (
            patch.object(svc, "should_skip_scheduled_run", return_value=True),
            patch("ai_digest.digest.service.get_rss_news"),
            patch("ai_digest.digest.service.send_telegram"),
            self.assertLogs("ai_digest.digest.service", level="INFO") as cm,
        ):
            svc.run()
        lines = [l for l in cm.output if "RUN SUMMARY" in l]
        self.assertTrue(lines)
        line = lines[-1]
        self.assertIn("path=skipped", line)
        self.assertIn("sent=false", line)
        self.assertIn("selected=0", line)


class TestRunSummaryErrorPath(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()
        self._orig = os.getcwd()
        os.chdir(self._tmpdir)

    def tearDown(self):
        os.chdir(self._orig)

    def test_error_json(self):
        cfg = _cfg()
        svc = DigestService(cfg)
        with (
            patch.object(svc, "should_skip_scheduled_run", return_value=False),
            patch("ai_digest.digest.service.get_rss_news", return_value=_SAMPLE_ITEMS),
            patch("ai_digest.digest.service.genai"),
            patch("ai_digest.digest.service.gemini_call", side_effect=RuntimeError("gemini down")),
            patch("ai_digest.digest.service.send_telegram", side_effect=ConnectionError("tg down")),
            patch.object(svc, "mark_sent_if_enforcing"),
        ):
            svc.run()
        self.assertTrue(os.path.exists("run_summary.json"))
        with open("run_summary.json", encoding="utf-8") as fh:
            data = json.load(fh)
        self.assertEqual(data["path"], "error")
        self.assertFalse(data["sent"])
        self.assertNotEqual(data["error_type"], "")
        self.assertEqual(data["selected"], 0)

    def test_error_log(self):
        cfg = _cfg()
        svc = DigestService(cfg)
        with (
            patch.object(svc, "should_skip_scheduled_run", return_value=False),
            patch("ai_digest.digest.service.get_rss_news", return_value=_SAMPLE_ITEMS),
            patch("ai_digest.digest.service.genai"),
            patch("ai_digest.digest.service.gemini_call", side_effect=RuntimeError("fail")),
            patch("ai_digest.digest.service.send_telegram", side_effect=OSError("tg fail")),
            patch.object(svc, "mark_sent_if_enforcing"),
            self.assertLogs("ai_digest.digest.service", level="INFO") as cm,
        ):
            svc.run()
        lines = [l for l in cm.output if "RUN SUMMARY" in l]
        self.assertTrue(lines)
        self.assertIn("path=error", lines[-1])
        self.assertIn("sent=false", lines[-1])


class TestRunSummaryBestEffortWrite(unittest.TestCase):
    def setUp(self):
        self._tmpdir = tempfile.mkdtemp()
        self._orig = os.getcwd()
        os.chdir(self._tmpdir)

    def tearDown(self):
        os.chdir(self._orig)

    def test_oserror_does_not_crash_run(self):
        cfg = _cfg()
        svc = DigestService(cfg)
        import builtins

        real_open = builtins.open

        def patched_open(file, *args, **kwargs):
            if str(file) == "run_summary.json":
                raise OSError("disk full")
            return real_open(file, *args, **kwargs)

        with (
            patch.object(svc, "should_skip_scheduled_run", return_value=False),
            patch("ai_digest.digest.service.get_rss_news", return_value=_SAMPLE_ITEMS),
            patch("ai_digest.digest.service.genai"),
            patch("ai_digest.digest.service.gemini_call", return_value=_gemini_resp(1)),
            patch("ai_digest.digest.service.send_telegram"),
            patch.object(svc, "mark_sent_if_enforcing"),
            patch("builtins.open", side_effect=patched_open),
        ):
            try:
                svc.run()
            except OSError:
                self.fail("OSError from run_summary.json write must not propagate")

    def test_oserror_emits_warning(self):
        cfg = _cfg()
        svc = DigestService(cfg)
        import builtins

        real_open = builtins.open

        def patched_open(file, *args, **kwargs):
            if str(file) == "run_summary.json":
                raise OSError("disk full")
            return real_open(file, *args, **kwargs)

        with (
            patch.object(svc, "should_skip_scheduled_run", return_value=False),
            patch("ai_digest.digest.service.get_rss_news", return_value=_SAMPLE_ITEMS),
            patch("ai_digest.digest.service.genai"),
            patch("ai_digest.digest.service.gemini_call", return_value=_gemini_resp(1)),
            patch("ai_digest.digest.service.send_telegram"),
            patch.object(svc, "mark_sent_if_enforcing"),
            patch("builtins.open", side_effect=patched_open),
            self.assertLogs("ai_digest.digest.service", level="WARNING") as cm,
        ):
            svc.run()
        warnings = [l for l in cm.output if "run_summary.json" in l and "WARNING" in l]
        self.assertTrue(warnings, "Expected WARNING about failed JSON write")


if __name__ == "__main__":
    unittest.main()
