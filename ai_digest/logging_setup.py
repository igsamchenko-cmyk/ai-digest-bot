"""Logging configuration with secret redaction."""

from __future__ import annotations

import logging
import re


class SecretRedactingFilter(logging.Filter):
    """Strips Telegram bot tokens and full API URLs from every log record."""

    # Matches full Telegram API URL prefix (contains the token) or standalone bot token
    _TOKEN_RE = re.compile(
        r"https?://api\.telegram\.org/bot[^/\s\"']+|" r"\b\d{8,10}:[A-Za-z0-9_\-]{35}\b"
    )

    def __init__(self, *secrets: str) -> None:
        super().__init__()
        self._secrets = [s for s in secrets if s]

    def filter(self, record: logging.LogRecord) -> bool:  # noqa: A003
        record.msg = self._scrub(str(record.msg))
        if record.args:
            record.args = tuple(self._scrub(str(a)) for a in record.args)
        return True

    def _scrub(self, text: str) -> str:
        text = self._TOKEN_RE.sub("[REDACTED]", text)
        for secret in self._secrets:
            text = text.replace(secret, "[REDACTED]")
        return text


def setup_logging(level: int = logging.INFO, token: str = "") -> None:
    """Configure root logger; optionally attach token-redacting filter."""
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)-8s %(name)s: %(message)s"))
    if token:
        handler.addFilter(SecretRedactingFilter(token))
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)
