"""AI-topic regex filter and title normalisation for deduplication."""

from __future__ import annotations

import re

# Matches Ukrainian and English AI-topic keywords
AI_PATTERN = re.compile(
    r"(штучн\w*\s+інтелект|нейромереж|нейронн\w*\s+мереж|машинн\w*\s+навчанн"
    r"|\bші\b|\bai\b|openai|chatgpt|\bgpt-?[45o\d]|anthropic|claude|gemini|deepmind"
    r"|\bllm\b|copilot|midjourney|mistral|deepseek|\bgrok\b|\bxai\b|perplexity"
    r"|llama|qwen|stable diffusion|hugging face)",
    re.IGNORECASE,
)


def normalize_title(title: str | None) -> str:
    """Return a canonical deduplication key: lowercase first 10 words."""
    words = re.findall(r"\w+", (title or "").lower())
    return " ".join(words[:10])
