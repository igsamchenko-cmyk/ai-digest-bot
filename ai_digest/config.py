"""Centralized configuration: single source of truth for all env parameters."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass

logger = logging.getLogger(__name__)


def _load_env_from_file() -> None:
    """Load .env file into os.environ (skips already-set keys)."""
    try:
        env_path = ".env"
        if not os.path.exists(env_path):
            script_dir = os.path.dirname(os.path.abspath(__file__))
            env_path = os.path.join(script_dir, ".env")
        if not os.path.exists(env_path):
            return
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, val = line.split("=", 1)
                    os.environ.setdefault(key.strip(), val.strip().strip("\"'"))
    except Exception as e:
        logger.warning("Failed to load .env file: %s", e)


@dataclass(frozen=True)
class AppConfig:
    telegram_bot_token: str
    telegram_chat_id: str
    gemini_api_key: str
    news_count: int
    news_lookback_hours: int
    gemini_model: str
    send_marker_path: str
    enforce_kyiv_hour: bool
    target_kyiv_hour_start: int
    target_kyiv_hour_end: int
    send_time: str

    @classmethod
    def from_env(cls) -> "AppConfig":
        _load_env_from_file()
        gemini_api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY", "")
        start = int(
            os.environ.get("TARGET_KYIV_HOUR_START", os.environ.get("TARGET_KYIV_HOUR", "8"))
        )
        return cls(
            telegram_bot_token=os.environ.get("TELEGRAM_BOT_TOKEN", ""),
            telegram_chat_id=os.environ.get("TELEGRAM_CHAT_ID", ""),
            gemini_api_key=gemini_api_key,
            news_count=int(os.environ.get("NEWS_COUNT", "5")),
            news_lookback_hours=int(os.environ.get("NEWS_LOOKBACK_HOURS", "72")),
            gemini_model=os.environ.get("GEMINI_MODEL", "").strip(),
            send_marker_path=os.environ.get("SEND_MARKER_PATH", ".digest_last_sent"),
            enforce_kyiv_hour=os.environ.get("ENFORCE_KYIV_HOUR", "").lower() == "true",
            target_kyiv_hour_start=start,
            target_kyiv_hour_end=int(os.environ.get("TARGET_KYIV_HOUR_END", str(start + 1))),
            send_time=os.environ.get("SEND_TIME", "08:00"),
        )
