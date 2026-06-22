"""Gemini prompt construction for the AI digest pipeline."""

from __future__ import annotations

from datetime import datetime


def build_gemini_prompt_from_rss(
    items: list[dict],
    today_en: str,
    nl: str,
    news_lookback_hours: int = 72,
    news_count: int = 5,
) -> str:
    """Build the numbered-list prompt for Gemini selection + translation.

    IMPORTANT: item links are intentionally EXCLUDED from the prompt.
    Gemini returns only numeric ids; attach_links() maps them back to real URLs.
    This prevents hallucinated or modified links from reaching the final message.
    """
    categories = "LLM|Продукти|Дослідження|Компанії|Агенти|Безпека"
    news_lines: list[str] = []
    for i, item in enumerate(items, 1):
        published: datetime | None = item.get("published_at")
        published_text = published.isoformat() if published else "unknown"
        news_lines.append(
            str(i)
            + ". Title: "
            + str(item.get("title", ""))
            + nl
            + "Source: "
            + str(item.get("source", ""))
            + nl
            + "Language: "
            + str(item.get("lang", "en"))
            + nl
            + "Published: "
            + published_text
        )

    return (
        "You are a Ukrainian AI news editor. Today is "
        + today_en
        + "."
        + nl
        + "Below is a numbered list of news items from the last "
        + str(news_lookback_hours)
        + " hours. Select the "
        + str(min(news_count, len(items)))
        + " most relevant, fresh, non-duplicate AI news items."
        " Prioritize model releases, major product launches, benchmarks,"
        " and competitive moves by OpenAI, Anthropic, Google/Gemini, Meta/Llama,"
        " Mistral, DeepSeek, Qwen, xAI/Grok, Microsoft, Perplexity."
        + nl
        + "When two items cover the same story,"
        " prefer the one with Language: uk (Ukrainian source)."
        + nl
        + "Reject evergreen articles, explainers, old announcements,"
        " and rumors without substance."
        + nl
        + "Translate titles to Ukrainian and write concise summaries in Ukrainian."
        + nl
        + 'Return ONLY valid JSON (no markdown). The "id" field MUST be the exact'
        " number of the item in the list below — never invent it:"
        + nl
        + '{"summary":"2-3 sentence overview in Ukrainian","news":['
        + nl
        + '{"id":1,"title":"заголовок українською","category":"'
        + categories
        + '",'
        + '"importance":"high|medium|low","summary":"2-3 sentences in Ukrainian",'
        + '"why_matters":"1 sentence in Ukrainian"}]}'
        + nl
        + "NEWS LIST:"
        + nl
        + (nl + nl).join(news_lines)
    )
