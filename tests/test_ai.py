"""Unit tests for ai_digest.ai.*

Coverage:
  - gemini_model_candidates: ordering, dedup, env fallback, empty config
  - build_gemini_prompt_from_rss: structure, required fields, link exclusion invariant
  - attach_links: correct mapping, range/type guards, hallucinated-URL prevention
  - parse_gemini_response: plain JSON, markdown wrappers, invalid JSON
  - gemini_call: success, limit:0 fallback, 429 backoff, unexpected exception,
                 all-models-exhausted, json_mode config
"""

import json
import unittest
from datetime import datetime, timezone
from unittest.mock import Mock, call, patch

from ai_digest.ai.gemini_client import gemini_call, gemini_model_candidates
from ai_digest.ai.parser import attach_links, parse_gemini_response
from ai_digest.ai.prompts import build_gemini_prompt_from_rss

# ─── helpers ──────────────────────────────────────────────────────────────────

_NOW = datetime(2026, 6, 21, 9, 0, tzinfo=timezone.utc)
_NL = "\n"


def _items(*titles):
    return [
        {
            "title": t,
            "link": f"https://example.com/{i}",
            "source": f"Source{i}",
            "lang": "en",
            "published_at": _NOW,
        }
        for i, t in enumerate(titles, 1)
    ]


def _gemini_data(*ids):
    """Build minimal Gemini-style response dict with given item ids."""
    return {
        "summary": "Test summary",
        "news": [{"id": i, "title": f"Translated {i}"} for i in ids],
    }


# ─── gemini_model_candidates ──────────────────────────────────────────────────


class TestGeminiModelCandidates(unittest.TestCase):
    def test_configured_model_is_first(self):
        models = gemini_model_candidates("my-custom-model")
        self.assertEqual(models[0], "my-custom-model")

    def test_defaults_present_after_configured(self):
        models = gemini_model_candidates("custom")
        self.assertIn("gemini-2.5-flash-lite", models)
        self.assertIn("gemini-2.5-flash", models)

    def test_no_duplicates_when_configured_matches_default(self):
        models = gemini_model_candidates("gemini-2.5-flash-lite")
        self.assertEqual(models.count("gemini-2.5-flash-lite"), 1)

    def test_empty_string_not_in_result(self):
        models = gemini_model_candidates("")
        self.assertNotIn("", models)

    def test_env_fallback_when_no_argument(self):
        with patch.dict("os.environ", {"GEMINI_MODEL": "env-model"}):
            models = gemini_model_candidates()
        self.assertEqual(models[0], "env-model")

    def test_no_env_no_arg_returns_defaults_only(self):
        with patch.dict("os.environ", {}, clear=True):
            models = gemini_model_candidates()
        self.assertGreater(len(models), 0)
        self.assertNotIn("", models)

    def test_result_is_ordered_list_not_set(self):
        """Order must be stable: configured first, then default priority order."""
        models = gemini_model_candidates("z-model")
        self.assertEqual(models[0], "z-model")
        flash_lite_idx = models.index("gemini-2.5-flash-lite")
        flash_idx = models.index("gemini-2.5-flash")
        self.assertLess(flash_lite_idx, flash_idx)


# ─── build_gemini_prompt_from_rss ─────────────────────────────────────────────


class TestBuildGeminiPromptFromRss(unittest.TestCase):
    def setUp(self):
        self.items = _items("OpenAI GPT-5 release", "Anthropic Claude update")
        self.prompt = build_gemini_prompt_from_rss(
            self.items,
            today_en="June 21, 2026",
            nl=_NL,
            news_lookback_hours=48,
            news_count=3,
        )

    def test_contains_today_date(self):
        self.assertIn("June 21, 2026", self.prompt)

    def test_contains_item_titles(self):
        self.assertIn("OpenAI GPT-5 release", self.prompt)
        self.assertIn("Anthropic Claude update", self.prompt)

    def test_contains_item_sources(self):
        self.assertIn("Source1", self.prompt)
        self.assertIn("Source2", self.prompt)

    def test_numbered_list_format(self):
        self.assertIn("1. Title:", self.prompt)
        self.assertIn("2. Title:", self.prompt)

    def test_links_not_in_prompt(self):
        """KEY INVARIANT: Gemini must never see real URLs — attach_links adds them later."""
        for item in self.items:
            self.assertNotIn(item["link"], self.prompt)

    def test_lookback_hours_in_prompt(self):
        self.assertIn("48", self.prompt)

    def test_news_count_in_prompt(self):
        """Expected selection count = min(news_count, len(items)) = min(3, 2) = 2."""
        self.assertIn("2", self.prompt)

    def test_categories_in_prompt(self):
        self.assertIn("LLM", self.prompt)
        self.assertIn("Безпека", self.prompt)

    def test_json_schema_hint_in_prompt(self):
        self.assertIn('"id"', self.prompt)
        self.assertIn('"summary"', self.prompt)
        self.assertIn('"importance"', self.prompt)

    def test_published_dates_in_prompt(self):
        self.assertIn(_NOW.isoformat(), self.prompt)

    def test_language_field_in_prompt(self):
        self.assertIn("Language: en", self.prompt)

    def test_default_params_produce_valid_prompt(self):
        prompt = build_gemini_prompt_from_rss(_items("AI news"), "Jan 1, 2026", "\n")
        self.assertIn("AI news", prompt)
        self.assertIn("72", prompt)  # default lookback


# ─── attach_links ─────────────────────────────────────────────────────────────


class TestAttachLinks(unittest.TestCase):
    def setUp(self):
        self.items = _items("Article A", "Article B", "Article C")

    def test_maps_id_1_to_first_item(self):
        data = attach_links(_gemini_data(1), self.items)
        self.assertEqual(data["news"][0]["link"], "https://example.com/1")
        self.assertEqual(data["news"][0]["source"], "Source1")

    def test_maps_id_2_to_second_item(self):
        data = attach_links(_gemini_data(2), self.items)
        self.assertEqual(data["news"][0]["link"], "https://example.com/2")
        self.assertEqual(data["news"][0]["source"], "Source2")

    def test_multiple_valid_ids(self):
        data = attach_links(_gemini_data(3, 1), self.items)
        links = [n["link"] for n in data["news"]]
        self.assertIn("https://example.com/3", links)
        self.assertIn("https://example.com/1", links)

    def test_out_of_range_id_skipped(self):
        data = attach_links(_gemini_data(1, 99), self.items)
        self.assertEqual(len(data["news"]), 1)  # only id=1 valid

    def test_id_zero_skipped(self):
        data = attach_links(_gemini_data(1, 0), self.items)
        links = [n["link"] for n in data["news"]]
        self.assertNotIn("https://example.com/0", links)

    def test_non_numeric_id_skipped(self):
        malformed = {"summary": "s", "news": [{"id": "abc", "title": "X"}, {"id": 1}]}
        data = attach_links(malformed, self.items)
        self.assertEqual(len(data["news"]), 1)

    def test_raises_when_no_valid_ids(self):
        with self.assertRaises(RuntimeError):
            attach_links(_gemini_data(99, 100), self.items)

    def test_raises_on_empty_items_list(self):
        with self.assertRaises(RuntimeError):
            attach_links(_gemini_data(1), [])

    def test_hallucinated_link_not_used(self):
        """Gemini sometimes adds a link field — it must be overwritten with the real URL."""
        data = {
            "summary": "s",
            "news": [{"id": 1, "title": "T", "link": "https://hallucinated.example/bad"}],
        }
        result = attach_links(data, self.items)
        self.assertEqual(result["news"][0]["link"], "https://example.com/1")
        self.assertNotIn("hallucinated", result["news"][0]["link"])

    def test_modifies_data_in_place_and_returns_it(self):
        data = _gemini_data(1)
        returned = attach_links(data, self.items)
        self.assertIs(returned, data)


# ─── parse_gemini_response ────────────────────────────────────────────────────


class TestParseGeminiResponse(unittest.TestCase):
    _PAYLOAD = {"summary": "ok", "news": [{"id": 1}]}

    def test_plain_json(self):
        raw = json.dumps(self._PAYLOAD)
        self.assertEqual(parse_gemini_response(raw), self._PAYLOAD)

    def test_json_with_backtick_json_wrapper(self):
        raw = "```json\n" + json.dumps(self._PAYLOAD) + "\n```"
        self.assertEqual(parse_gemini_response(raw), self._PAYLOAD)

    def test_json_with_plain_backtick_wrapper(self):
        raw = "```\n" + json.dumps(self._PAYLOAD) + "\n```"
        self.assertEqual(parse_gemini_response(raw), self._PAYLOAD)

    def test_leading_trailing_whitespace_stripped(self):
        raw = "  \n" + json.dumps(self._PAYLOAD) + "\n  "
        self.assertEqual(parse_gemini_response(raw), self._PAYLOAD)

    def test_none_input_raises(self):
        with self.assertRaises((json.JSONDecodeError, ValueError)):
            parse_gemini_response(None)

    def test_empty_string_raises(self):
        with self.assertRaises(json.JSONDecodeError):
            parse_gemini_response("")

    def test_invalid_json_raises(self):
        with self.assertRaises(json.JSONDecodeError):
            parse_gemini_response("not json {{{")


# ─── gemini_call ──────────────────────────────────────────────────────────────


class TestGeminiCall(unittest.TestCase):
    """Patch gemini_model_candidates to use a controlled 2-model list."""

    _MODELS = ["model-primary", "model-fallback"]
    _MODELS_PATCH = "ai_digest.ai.gemini_client.gemini_model_candidates"
    _SLEEP_PATCH = "ai_digest.ai.gemini_client.time.sleep"

    def _client(self, side_effect=None, return_value=None):
        c = Mock()
        if side_effect is not None:
            c.models.generate_content.side_effect = side_effect
        else:
            c.models.generate_content.return_value = return_value or Mock()
        return c

    # ── model_override forwarding ─────────────────────────────────────────

    def test_model_override_forwarded_to_candidates(self):
        """gemini_call must pass model_override to gemini_model_candidates."""
        client = self._client(return_value=Mock())
        with patch(self._MODELS_PATCH) as mock_candidates:
            mock_candidates.return_value = ["cfg-model"]
            gemini_call(client, "p", model_override="cfg-model")
        mock_candidates.assert_called_once_with("cfg-model")

    def test_empty_model_override_still_works(self):
        """Default empty model_override must not break existing behavior."""
        mock_resp = Mock()
        client = self._client(return_value=mock_resp)
        with patch(self._MODELS_PATCH, return_value=self._MODELS) as mock_candidates:
            result = gemini_call(client, "prompt")
        mock_candidates.assert_called_once_with("")
        self.assertIs(result, mock_resp)

    # ── success paths ──────────────────────────────────────────────────────

    def test_success_returns_response(self):
        mock_resp = Mock()
        client = self._client(return_value=mock_resp)
        with patch(self._MODELS_PATCH, return_value=self._MODELS):
            result = gemini_call(client, "prompt")
        self.assertIs(result, mock_resp)

    def test_called_with_correct_model_and_contents(self):
        client = self._client(return_value=Mock())
        with patch(self._MODELS_PATCH, return_value=["model-x"]):
            gemini_call(client, "my-prompt")
        kwargs = client.models.generate_content.call_args[1]
        self.assertEqual(kwargs["model"], "model-x")
        self.assertEqual(kwargs["contents"], "my-prompt")

    def test_json_mode_sets_response_mime_type(self):
        client = self._client(return_value=Mock())
        with patch(self._MODELS_PATCH, return_value=["model-x"]):
            gemini_call(client, "p", json_mode=True)
        kwargs = client.models.generate_content.call_args[1]
        self.assertIn("config", kwargs)
        self.assertEqual(kwargs["config"].response_mime_type, "application/json")

    # ── quota / limit:0 ───────────────────────────────────────────────────

    def test_limit_zero_tries_next_model(self):
        mock_resp = Mock()
        client = self._client(
            side_effect=[
                Exception("quota limit: 0 exceeded"),
                mock_resp,  # fallback model succeeds
            ]
        )
        with patch(self._MODELS_PATCH, return_value=self._MODELS):
            result = gemini_call(client, "p")
        self.assertIs(result, mock_resp)
        self.assertEqual(client.models.generate_content.call_count, 2)

    def test_limit_of_zero_variant_also_skips_model(self):
        mock_resp = Mock()
        client = self._client(side_effect=[Exception("limit of 0 per day"), mock_resp])
        with patch(self._MODELS_PATCH, return_value=self._MODELS):
            result = gemini_call(client, "p")
        self.assertIs(result, mock_resp)

    def test_all_models_quota_exhausted_raises(self):
        client = self._client(
            side_effect=[
                Exception("limit: 0"),
                Exception("limit: 0"),
            ]
        )
        with patch(self._MODELS_PATCH, return_value=self._MODELS):
            with self.assertRaises(RuntimeError) as ctx:
                gemini_call(client, "p")
        self.assertIn("all model candidates failed", str(ctx.exception))

    # ── rate limiting / 429 ────────────────────────────────────────────────

    def test_429_retries_then_succeeds(self):
        mock_resp = Mock()
        client = self._client(
            side_effect=[
                Exception("429 RESOURCE_EXHAUSTED"),
                mock_resp,
            ]
        )
        with (
            patch(self._MODELS_PATCH, return_value=["model-x"]),
            patch(self._SLEEP_PATCH) as mock_sleep,
        ):
            result = gemini_call(client, "p", max_retries=3)
        self.assertIs(result, mock_resp)
        mock_sleep.assert_called_once_with(5)  # 5 * 2^0 = 5

    def test_429_exponential_backoff_delays(self):
        mock_resp = Mock()
        client = self._client(
            side_effect=[
                Exception("429"),
                Exception("429"),
                mock_resp,
            ]
        )
        with (
            patch(self._MODELS_PATCH, return_value=["model-x"]),
            patch(self._SLEEP_PATCH) as mock_sleep,
        ):
            result = gemini_call(client, "p", max_retries=3)
        self.assertIs(result, mock_resp)
        mock_sleep.assert_has_calls([call(5), call(10)])  # 5*1, 5*2

    def test_resource_exhausted_string_also_triggers_retry(self):
        mock_resp = Mock()
        client = self._client(side_effect=[Exception("RESOURCE_EXHAUSTED quota"), mock_resp])
        with patch(self._MODELS_PATCH, return_value=["model-x"]), patch(self._SLEEP_PATCH):
            result = gemini_call(client, "p", max_retries=2)
        self.assertIs(result, mock_resp)

    def test_all_retries_exhausted_falls_to_next_model(self):
        mock_resp = Mock()
        # model-primary: 3 × 429; model-fallback: success
        client = self._client(
            side_effect=[
                Exception("429"),
                Exception("429"),
                Exception("429"),
                mock_resp,
            ]
        )
        with patch(self._MODELS_PATCH, return_value=self._MODELS), patch(self._SLEEP_PATCH):
            result = gemini_call(client, "p", max_retries=3)
        self.assertIs(result, mock_resp)

    # ── unexpected exception ───────────────────────────────────────────────

    def test_unexpected_exception_re_raised_immediately(self):
        client = self._client(side_effect=ValueError("something unexpected"))
        with patch(self._MODELS_PATCH, return_value=self._MODELS):
            with self.assertRaises(ValueError):
                gemini_call(client, "p")
        # Must not try the second model
        self.assertEqual(client.models.generate_content.call_count, 1)

    def test_all_models_raise_runtime_error_when_exhausted(self):
        client = self._client(side_effect=[Exception("429")] * 6)  # 2 models × 3 retries
        with patch(self._MODELS_PATCH, return_value=self._MODELS), patch(self._SLEEP_PATCH):
            with self.assertRaises(RuntimeError):
                gemini_call(client, "p", max_retries=3)



# ─── prompt safety rules ──────────────────────────────────────────────────────


class TestPromptSafetyRules(unittest.TestCase):
    """Verify that conservative generation rules are present in the prompt."""

    def setUp(self):
        items = _items("Some vague AI headline")
        self.prompt = build_gemini_prompt_from_rss(
            items,
            today_en="June 24, 2026",
            nl=_NL,
        )

    def test_prompt_forbids_inventing_facts(self):
        self.assertIn("Do not invent facts", self.prompt)

    def test_prompt_forbids_invented_numbers_dates_quotes(self):
        # All of these must be listed in the no-invent rule
        for term in ("numbers", "dates", "quotes"):
            with self.subTest(term=term):
                self.assertIn(term, self.prompt)

    def test_prompt_forbids_invented_product_names_benchmarks_funding(self):
        for term in ("product names", "benchmarks", "funding amounts"):
            with self.subTest(term=term):
                self.assertIn(term, self.prompt)

    def test_prompt_requires_valid_json_output(self):
        self.assertIn("Return valid JSON only", self.prompt)

    def test_prompt_instructs_caution_on_vague_titles(self):
        self.assertIn("vague", self.prompt)

    def test_prompt_forbids_url_generation(self):
        self.assertIn("Never create", self.prompt)
        # Ensure URL-related instruction is present
        self.assertIn("URLs", self.prompt)

    def test_prompt_does_not_contain_rss_item_links(self):
        """KEY INVARIANT preserved: no real URLs from items appear in prompt."""
        item = _items("Some vague AI headline")[0]
        self.assertNotIn(item["link"], self.prompt)

    def test_prompt_instructs_grounded_why_matters(self):
        self.assertIn("why_matters", self.prompt)
        self.assertIn("grounded", self.prompt)

if __name__ == "__main__":
    unittest.main()
