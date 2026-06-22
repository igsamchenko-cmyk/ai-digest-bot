"""Gemini model selection, call wrapper with quota/rate-limit handling."""

from __future__ import annotations

import logging
import os
import time

from google.genai import types

logger = logging.getLogger(__name__)


def gemini_model_candidates(configured_model: str = "") -> list[str]:
    """Return ordered list of Gemini models to try, deduped.

    If *configured_model* is empty, falls back to the GEMINI_MODEL env var.
    The configured model (if any) is always first; defaults follow.
    """
    if not configured_model:
        configured_model = os.environ.get("GEMINI_MODEL", "").strip()
    candidates = [
        configured_model,
        "gemini-2.5-flash-lite",
        "gemini-2.5-flash",
        "gemini-2.0-flash-lite",
        "gemini-2.0-flash",
    ]
    result: list[str] = []
    for model in candidates:
        if model and model not in result:
            result.append(model)
    return result


def gemini_call(
    client,
    contents,
    use_search: bool = False,
    json_mode: bool = False,
    max_retries: int = 3,
    model_override: str = "",
):
    """Call Gemini with automatic model fallback and retry on quota/rate errors.

    *model_override* is forwarded to gemini_model_candidates(); if empty, the
    function falls back to the GEMINI_MODEL env var (backward-compat default).

    Tries each candidate model in order:
      - "limit: 0" / "limit of 0" → model has zero quota; skip to next model.
      - "429" / "RESOURCE_EXHAUSTED" → rate limit; exponential backoff then retry.
      - Any other exception → re-raised immediately (caller decides fallback).

    Raises RuntimeError when all model candidates are exhausted.
    """
    config_kwargs: dict = {}
    if use_search:
        config_kwargs["tools"] = [types.Tool(google_search=types.GoogleSearch())]
    if json_mode and not use_search:
        config_kwargs["response_mime_type"] = "application/json"
    gen_config = types.GenerateContentConfig(**config_kwargs) if config_kwargs else None

    last_error: Exception | None = None
    for model in gemini_model_candidates(model_override):
        logger.info("Trying Gemini model: %s", model)
        for attempt in range(max_retries):
            try:
                kwargs: dict = {"model": model, "contents": contents}
                if gen_config:
                    kwargs["config"] = gen_config
                response = client.models.generate_content(**kwargs)
                logger.info("Gemini model succeeded: %s", model)
                return response
            except Exception as exc:
                err = str(exc)
                last_error = exc
                if "limit: 0" in err or "limit of 0" in err:
                    logger.warning("Model %s has 0 quota, trying next.", model)
                    break  # move to next model
                if "429" in err or "RESOURCE_EXHAUSTED" in err:
                    wait = 5 * (2**attempt)
                    logger.warning(
                        "Rate limit on %s. Waiting %ds (attempt %d/%d).",
                        model,
                        wait,
                        attempt + 1,
                        max_retries,
                    )
                    time.sleep(wait)
                    # continue to next attempt
                else:
                    raise  # unexpected error — propagate immediately

    raise RuntimeError("Gemini: all model candidates failed; last error: " + str(last_error))
