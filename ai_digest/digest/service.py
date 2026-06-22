"""DigestService: orchestration of the full AI digest workflow.

Single responsibility: given an AppConfig, run one digest cycle —
fetch news, call Gemini (with RSS fallback), send to Telegram,
and update the dedup marker.

All side-effectful I/O is channelled through the injectable helpers so the
class is easy to unit-test with standard mock.patch.
"""

from __future__ import annotations

import logging
from datetime import datetime

from google import genai

from ai_digest.ai.gemini_client import gemini_call
from ai_digest.ai.parser import attach_links, parse_gemini_response
from ai_digest.ai.prompts import build_gemini_prompt_from_rss
from ai_digest.config import AppConfig
from ai_digest.sources.collector import get_rss_news
from ai_digest.telegram.client import send_telegram
from ai_digest.telegram.formatter import (
    KYIV_TZ,
    build_gemini_message,
    build_rss_message,
    date_labels,
    escape_text,
)

logger = logging.getLogger(__name__)


class DigestService:
    """Runs a single AI digest cycle for the given configuration."""

    def __init__(self, config: AppConfig) -> None:
        self._cfg = config

    # ── Dedup-marker helpers ──────────────────────────────────────────────────

    def enforcing_window(self) -> bool:
        """True when the time-window guard is active."""
        return self._cfg.enforce_kyiv_hour

    def read_send_marker(self) -> str:
        """Return the date string stored in the send-marker file, or ''."""
        try:
            with open(self._cfg.send_marker_path, "r", encoding="utf-8") as fh:
                return fh.read().strip()
        except OSError:
            return ""

    def mark_sent_if_enforcing(self, now: datetime) -> None:
        """Write today's date to the marker file when window-enforcement is on."""
        if not self.enforcing_window():
            return
        try:
            with open(self._cfg.send_marker_path, "w", encoding="utf-8") as fh:
                fh.write(now.strftime("%Y-%m-%d"))
        except OSError as exc:
            logger.warning("Failed to write send marker: %s", exc)

    def should_skip_scheduled_run(self, now: datetime) -> bool:
        """Return True (and log) when this scheduled run should be suppressed."""
        if not self.enforcing_window():
            return False
        start = self._cfg.target_kyiv_hour_start
        end = self._cfg.target_kyiv_hour_end
        if not (start <= now.hour <= end):
            logger.info(
                "Skipping scheduled run at Kyiv hour %d; send window is %d-%d.",
                now.hour,
                start,
                end,
            )
            return True
        today = now.strftime("%Y-%m-%d")
        if self.read_send_marker() == today:
            logger.info("Skipping scheduled run: digest already sent today (%s).", today)
            return True
        return False

    # ── Orchestration ─────────────────────────────────────────────────────────

    def run(self) -> None:
        """Execute one full digest cycle."""
        cfg = self._cfg
        now = datetime.now(KYIV_TZ)
        if self.should_skip_scheduled_run(now):
            return

        today_uk, today_en = date_labels(now)
        logger.info("Starting digest for %s.", today_en)
        nl = chr(10)

        # ── 1. Fetch news ─────────────────────────────────────────────────────
        items: list[dict] = []
        try:
            items = get_rss_news(
                news_lookback_hours=cfg.news_lookback_hours,
                news_count=cfg.news_count,
            )
        except Exception as exc:
            logger.error("RSS fetch failed: %s", exc)

        # ── 2. Try Gemini path ────────────────────────────────────────────────
        if not cfg.gemini_api_key:
            logger.info("GEMINI_API_KEY is not set. Using RSS fallback.")
        elif items:
            try:
                client = genai.Client(api_key=cfg.gemini_api_key)
                resp = gemini_call(
                    client,
                    build_gemini_prompt_from_rss(
                        items,
                        today_en,
                        nl,
                        news_lookback_hours=cfg.news_lookback_hours,
                        news_count=cfg.news_count,
                    ),
                    json_mode=True,
                    model_override=cfg.gemini_model,
                )
                data = attach_links(parse_gemini_response(resp.text), items)
                send_telegram(
                    build_gemini_message(data, today_uk),
                    token=cfg.telegram_bot_token,
                    chat_id=cfg.telegram_chat_id,
                )
                self.mark_sent_if_enforcing(now)
                logger.info("Done via Gemini!")
                return
            except Exception as exc:
                logger.error("Gemini execution failed: %s. Falling back to RSS...", exc)

        # ── 3. RSS fallback ───────────────────────────────────────────────────
        try:
            if not items:
                send_telegram(
                    "☀️ <b>Дайджест новин ШІ</b> · "
                    + escape_text(today_uk)
                    + "\n\nНе вдалося знайти свіжих новин на даний момент.",
                    token=cfg.telegram_bot_token,
                    chat_id=cfg.telegram_chat_id,
                )
                self.mark_sent_if_enforcing(now)
                return
            send_telegram(
                build_rss_message(items, today_uk, news_count=cfg.news_count),
                token=cfg.telegram_bot_token,
                chat_id=cfg.telegram_chat_id,
            )
            self.mark_sent_if_enforcing(now)
            logger.info("Done via Fallback RSS!")
        except Exception as err:
            logger.error("Fallback also failed: %s: %s", type(err).__name__, err)
            try:
                send_telegram(
                    "⚠️ <b>Помилка:</b> Не вдалося завантажити новини ні через Gemini, ні через RSS.",
                    token=cfg.telegram_bot_token,
                    chat_id=cfg.telegram_chat_id,
                )
            except Exception as send_err:
                logger.error("Error notification also failed: %s", type(send_err).__name__)


def run_digest_service(config: AppConfig) -> None:
    """Convenience wrapper: create a DigestService and run one cycle."""
    DigestService(config).run()
