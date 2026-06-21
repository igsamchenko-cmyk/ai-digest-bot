"""Telegram API client: chat-id resolution and message delivery."""

from __future__ import annotations

import logging

import requests

from ai_digest.telegram.splitter import split_message

logger = logging.getLogger(__name__)

# Module-level cache; reset in tests via `ai_digest.telegram.client._CHAT_ID_CACHE = None`
_CHAT_ID_CACHE: str | None = None


def _http_error_msg(exc: requests.HTTPError, action: str) -> str:
    if exc.response is not None:
        return f"{action} failed: HTTP {exc.response.status_code} {exc.response.reason}"
    return f"{action} failed: {exc}"


def resolve_telegram_chat_id(token: str, chat_id: str) -> str:
    """Return the resolved chat ID, using cache then env value then getUpdates."""
    global _CHAT_ID_CACHE
    if _CHAT_ID_CACHE:
        return _CHAT_ID_CACHE
    if chat_id:
        _CHAT_ID_CACHE = chat_id
        return _CHAT_ID_CACHE
    if not token:
        raise RuntimeError("Missing required environment variable: TELEGRAM_BOT_TOKEN")
    # NOTE: never log the URL — it contains the bot token
    url = "https://api.telegram.org/bot" + token + "/getUpdates"
    try:
        response = requests.get(url, timeout=30)
        response.raise_for_status()
    except requests.HTTPError as exc:
        raise RuntimeError(_http_error_msg(exc, "Telegram getUpdates")) from exc
    data = response.json()
    if not data.get("ok"):
        raise RuntimeError("Telegram getUpdates returned ok=false")
    for update in reversed(data.get("result", [])):
        message = (
            update.get("message") or update.get("edited_message") or update.get("channel_post")
        )
        if not message:
            continue
        resolved = message.get("chat", {}).get("id")
        if resolved:
            _CHAT_ID_CACHE = str(resolved)
            logger.info("Resolved TELEGRAM_CHAT_ID from getUpdates")
            return _CHAT_ID_CACHE
    raise RuntimeError(
        "TELEGRAM_CHAT_ID is not set and getUpdates has no messages. "
        "Open your Telegram bot, send /start or any message, then re-run the workflow."
    )


def send_telegram(text: str, token: str, chat_id: str) -> None:
    """Send text to Telegram, splitting into parts if needed."""
    resolved = resolve_telegram_chat_id(token, chat_id)
    # NOTE: never log the URL — it contains the bot token
    url = "https://api.telegram.org/bot" + token + "/sendMessage"
    for part in split_message(text):
        try:
            resp = requests.post(
                url,
                json={
                    "chat_id": resolved,
                    "text": part,
                    "parse_mode": "HTML",
                    "disable_web_page_preview": True,
                },
                timeout=30,
            )
            resp.raise_for_status()
        except requests.HTTPError as exc:
            raise RuntimeError(_http_error_msg(exc, "Telegram sendMessage")) from exc
