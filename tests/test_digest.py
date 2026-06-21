import unittest
from datetime import datetime, timezone
from unittest.mock import Mock, patch

import ai_digest.telegram.client as _tg_client
import digest


class DigestFormattingTests(unittest.TestCase):
    def setUp(self):
        # Скидаємо кеш chat_id між тестами (реальний кеш — у client.py)
        _tg_client._CHAT_ID_CACHE = None
        digest._CHAT_ID_CACHE = None

    def test_escape_text_for_telegram_html(self):
        self.assertEqual(
            digest.escape_text("OpenAI < ChatGPT & Gemini > Claude"),
            "OpenAI &lt; ChatGPT &amp; Gemini &gt; Claude",
        )

    def test_split_message_keeps_chunks_under_limit(self):
        text = "\n\n".join(f"Paragraph {i} " + ("x" * 120) for i in range(40))
        chunks = digest.split_message(text, limit=500)
        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(len(chunk) <= 500 for chunk in chunks))
        self.assertEqual("".join(chunks).replace("\n\n", ""), text.replace("\n\n", ""))

    def test_build_rss_message_escapes_titles_sources_and_links(self):
        message = digest.build_rss_message(
            [
                {
                    "title": "OpenAI <launch> & update",
                    "source": "Tech <News>",
                    "link": 'https://example.com/news?q=ai&tag="llm"',
                    "published_at": datetime(2026, 5, 31, 12, 30, tzinfo=timezone.utc),
                }
            ],
            "May 31, 2026",
        )
        self.assertIn("OpenAI &lt;launch&gt; &amp; update", message)
        self.assertIn("Tech &lt;News&gt;", message)
        self.assertIn("31.05", message)
        self.assertIn("q=ai&amp;tag=&quot;llm&quot;", message)
        self.assertNotIn("OpenAI <launch>", message)

    def test_build_gemini_message_escapes_model_output(self):
        message = digest.build_gemini_message(
            {
                "summary": "Summary with <tag> & data",
                "news": [
                    {
                        "title": "Title <bad>",
                        "category": "LLM",
                        "importance": "high",
                        "summary": "Body & details",
                        "source": "Source <A>",
                        "why_matters": "Because > now",
                    }
                ],
            },
            "May 31, 2026",
        )
        self.assertIn("Summary with &lt;tag&gt; &amp; data", message)
        self.assertIn("Title &lt;bad&gt;", message)
        self.assertIn("Source &lt;A&gt;", message)
        self.assertIn("Because &gt; now", message)

    def test_build_gemini_message_renders_clickable_title(self):
        message = digest.build_gemini_message(
            {
                "summary": "Огляд",
                "news": [
                    {
                        "title": "Новина",
                        "category": "LLM",
                        "importance": "high",
                        "summary": "Текст",
                        "source": "AIN.UA",
                        "why_matters": "Важливо",
                        "link": 'https://example.com/a?x=1&y="2"',
                    }
                ],
            },
            "10 червня 2026",
        )
        self.assertIn('<a href="https://example.com/a?x=1&amp;y=&quot;2&quot;">Новина</a>', message)

    def test_attach_links_maps_ids_to_real_urls(self):
        items = [
            {"title": "A", "link": "https://ua.example/1", "source": "DOU"},
            {"title": "B", "link": "https://world.example/2", "source": "TechCrunch"},
        ]
        data = digest.attach_links(
            {"summary": "s", "news": [{"id": 2, "title": "Б"}, {"id": 99, "title": "X"}]},
            items,
        )
        self.assertEqual(len(data["news"]), 1)
        self.assertEqual(data["news"][0]["link"], "https://world.example/2")
        self.assertEqual(data["news"][0]["source"], "TechCrunch")

    def test_attach_links_raises_without_valid_ids(self):
        with self.assertRaises(RuntimeError):
            digest.attach_links({"news": [{"id": 99, "title": "X"}]}, [])

    def test_resolve_telegram_chat_id_from_updates(self):
        response = Mock()
        response.json.return_value = {
            "ok": True,
            "result": [
                {"message": {"chat": {"id": 12345}}},
                {"message": {"chat": {"id": 67890}}},
            ],
        }
        response.raise_for_status.return_value = None
        # requests.get is called inside ai_digest.telegram.client
        with (
            patch.object(digest, "TELEGRAM_CHAT_ID", ""),
            patch.object(digest, "TELEGRAM_BOT_TOKEN", "token"),
            patch("ai_digest.telegram.client.requests.get", return_value=response),
        ):
            self.assertEqual(digest.resolve_telegram_chat_id(), "67890")

    def test_resolve_telegram_chat_id_prefers_env_value(self):
        with (
            patch.object(digest, "TELEGRAM_CHAT_ID", "555"),
            patch("ai_digest.telegram.client.requests.get") as get,
        ):
            self.assertEqual(digest.resolve_telegram_chat_id(), "555")
            get.assert_not_called()

    def test_gemini_model_candidates_prefers_configured_model(self):
        with patch.dict("os.environ", {"GEMINI_MODEL": "custom-model"}):
            self.assertEqual(digest.gemini_model_candidates()[0], "custom-model")
        self.assertIn("gemini-2.5-flash-lite", digest.gemini_model_candidates())

    def test_parse_feed_datetime_rfc822_and_iso(self):
        parsed = digest.parse_feed_datetime("Sun, 31 May 2026 12:30:00 GMT")
        self.assertEqual(parsed, datetime(2026, 5, 31, 12, 30, tzinfo=timezone.utc))
        parsed_iso = digest.parse_feed_datetime("2026-05-31T12:30:00Z")
        self.assertEqual(parsed_iso, datetime(2026, 5, 31, 12, 30, tzinfo=timezone.utc))

    def test_parse_feed_items_rss_and_atom(self):
        rss = (
            b'<?xml version="1.0"?><rss><channel><item><title>T1</title>'
            b"<link>https://a/1</link><pubDate>Tue, 09 Jun 2026 10:00:00 GMT</pubDate>"
            b"</item></channel></rss>"
        )
        atom = (
            b'<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom"><entry>'
            b'<title>T2</title><link href="https://a/2"/>'
            b"<updated>2026-06-09T10:00:00Z</updated></entry></feed>"
        )
        self.assertEqual(digest.parse_feed_items(rss, "X")[0]["link"], "https://a/1")
        self.assertEqual(digest.parse_feed_items(atom, "Y")[0]["link"], "https://a/2")
        self.assertEqual(digest.parse_feed_items(b"not xml", "Z"), [])

    def test_ai_pattern_filters_titles(self):
        self.assertTrue(digest.AI_PATTERN.search("Штучний інтелект у школах"))
        self.assertTrue(digest.AI_PATTERN.search("OpenAI показала нову модель"))
        self.assertFalse(digest.AI_PATTERN.search("Найкращі ноутбуки 2026 року"))
        self.assertFalse(digest.AI_PATTERN.search("Наші більші плани на літо"))


if __name__ == "__main__":
    unittest.main()
