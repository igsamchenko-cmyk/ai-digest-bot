"""DigestService: orchestration of the full AI digest workflow.

Single responsibility: given an AppConfig, run one digest cycle —
fetch news, call Gemini (with RSS fallback), send to Telegram,
and update the dedup marker.

All side-effectful I/O is channelled through the injectable helpers so the
class is easy to unit-test with standard mock.patch.
"""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime

from google import genai

from ai_digest.ai.gemini_client import gemini_call
from ai_digest.ai.parser import attach_links, parse_gemini_response, sort_news_by_importance
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
        gemini_enabled = getattr(cfg, "use_gemini", True) is not False
        now = datetime.now(KYIV_TZ)
        start_time = time.monotonic()

        def _summary(
            path: str,
            sent: bool,
            selected: int = 0,
            error_type: str = "",
            fallback_reason: str = "",
        ) -> None:
            """Emit one structured end-of-run line and write run_summary.json."""
            duration_ms = round((time.monotonic() - start_time) * 1000)
            model = cfg.gemini_model or ""
            logger.info(
                "RUN SUMMARY: rss_items=%d selected=%d path=%s sent=%s"
                " duration_ms=%d error_type=%s model=%s gemini_enabled=%s"
                " fallback_reason=%s",
                len(items),
                selected,
                path,
                "true" if sent else "false",
                duration_ms,
                error_type,
                model,
                "true" if gemini_enabled else "false",
                fallback_reason,
            )
            summary_dict: dict = {
                "rss_items": len(items),
                "path": path,
                "sent": sent,
                "selected": selected,
                "duration_ms": duration_ms,
                "error_type": error_type,
                "model": model,
                "gemini_enabled": gemini_enabled,
                "fallback_reason": fallback_reason,
            }
            try:
                with open("run_summary.json", "w", encoding="utf-8") as fh:
                    json.dump(summary_dict, fh, indent=2)
            except OSError as exc:
                logger.warning("Failed to write run_summary.json: %s", exc)

        items: list[dict] = []
        if self.should_skip_scheduled_run(now):
            _summary("skipped", False)
            return

        today_uk, today_en = date_labels(now)
        logger.info("Starting digest for %s.", today_en)
        nl = chr(10)

        # ── 1. Fetch news ─────────────────────────────────────────────────────
        try:
            items = get_rss_news(
                news_lookback_hours=cfg.news_lookback_hours,
                news_count=cfg.news_count,
            )
        except Exception as exc:
            logger.error("RSS fetch failed: %s", exc)

        fallback_reason = "gemini_disabled" if not gemini_enabled else ""

        # ── 2. Try Gemini path ────────────────────────────────────────────────
        if not gemini_enabled:
            logger.info("USE_GEMINI=false. Using RSS-only digest mode.")
        elif not cfg.gemini_api_key:
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
                data["news"] = sort_news_by_importance(data["news"])
                send_telegram(
                    build_gemini_message(data, today_uk),
                    token=cfg.telegram_bot_token,
                    chat_id=cfg.telegram_chat_id,
                )
                self.mark_sent_if_enforcing(now)
                logger.info("Done via Gemini!")
                _summary("gemini", True, selected=len(data["news"]))
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
                _summary("empty", True, selected=0, fallback_reason=fallback_reason)
                return
            send_telegram(
                build_rss_message(items, today_uk, news_count=cfg.rss_fallback_news_count),
                token=cfg.telegram_bot_token,
                chat_id=cfg.telegram_chat_id,
            )
            self.mark_sent_if_enforcing(now)
            logger.info("Done via Fallback RSS!")
            _summary(
                "rss",
                True,
                selected=min(len(items), cfg.rss_fallback_news_count),
                fallback_reason=fallback_reason,
            )
        except Exception as err:
            logger.error("Fallback also failed: %s: %s", type(err).__name__, err)
            _summary("error", False, error_type=type(err).__name__, fallback_reason=fallback_reason)
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
