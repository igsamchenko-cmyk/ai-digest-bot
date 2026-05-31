import unittest

import digest


class DigestFormattingTests(unittest.TestCase):
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
                }
            ],
            "May 31, 2026",
        )

        self.assertIn("OpenAI &lt;launch&gt; &amp; update", message)
        self.assertIn("Tech &lt;News&gt;", message)
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


if __name__ == "__main__":
    unittest.main()
