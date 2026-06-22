"""Gemini response parsing and link attachment."""

from __future__ import annotations

import json
import logging

logger = logging.getLogger(__name__)


def parse_gemini_response(raw_text: str | None) -> dict:
    """Strip optional ```json ... ``` wrapper and parse Gemini's JSON response.

    Raises json.JSONDecodeError on invalid JSON.
    """
    text = (raw_text or "").replace("```json", "").replace("```", "").strip()
    return json.loads(text)


def attach_links(data: dict, items: list[dict]) -> dict:
    """Substitute real URLs and sources into Gemini's response by item id.

    Gemini receives only numeric ids (never URLs) — this function is the sole
    place that maps id → real link, preventing hallucinated URLs in the digest.

    Skips any entry with a missing, invalid, or out-of-range id.
    Raises RuntimeError when zero valid entries remain after filtering.
    """
    enriched: list[dict] = []
    for n in data.get("news", []):
        try:
            idx = int(n.get("id", 0)) - 1
        except (TypeError, ValueError):
            logger.debug("Skipping Gemini item with non-numeric id: %r", n.get("id"))
            continue
        if 0 <= idx < len(items):
            n["link"] = items[idx]["link"]
            n["source"] = items[idx]["source"]
            enriched.append(n)
        else:
            logger.debug("Skipping Gemini item with out-of-range id: %d", n.get("id", 0))

    if not enriched:
        raise RuntimeError("Gemini response had no valid item ids")
    data["news"] = enriched
    return data
