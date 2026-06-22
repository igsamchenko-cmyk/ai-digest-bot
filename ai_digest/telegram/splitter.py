"""Split long messages to stay under Telegram's 4096-char limit."""

from __future__ import annotations

TELEGRAM_LIMIT = 3900


def split_message(text: str, limit: int = TELEGRAM_LIMIT) -> list[str]:
    if len(text) <= limit:
        return [text]
    chunks: list[str] = []
    current: list[str] = []
    current_len = 0
    for paragraph in text.split("\n\n"):
        block = paragraph if not current else "\n\n" + paragraph
        if current and current_len + len(block) > limit:
            chunks.append("".join(current))
            current = [paragraph]
            current_len = len(paragraph)
        elif len(paragraph) > limit:
            if current:
                chunks.append("".join(current))
                current = []
                current_len = 0
            for i in range(0, len(paragraph), limit):
                chunks.append(paragraph[i : i + limit])
        else:
            current.append(block)
            current_len += len(block)
    if current:
        chunks.append("".join(current))
    return chunks
