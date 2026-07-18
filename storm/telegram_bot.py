"""Minimal Telegram Bot API client using plain HTTPS requests.

Storm stays synchronous end-to-end, so this talks to Telegram's REST API
directly instead of pulling in python-telegram-bot's async runtime.
"""

from __future__ import annotations

import logging

import requests

logger = logging.getLogger(__name__)


class TelegramNotifier:
    def __init__(self, bot_token: str, chat_id: str, timeout: float = 10.0):
        self._base_url = f"https://api.telegram.org/bot{bot_token}"
        self._chat_id = chat_id
        self._timeout = timeout
        self._enabled = bool(bot_token and chat_id)

    @property
    def enabled(self) -> bool:
        return self._enabled

    def send(self, text: str) -> None:
        if not self._enabled:
            return
        try:
            resp = requests.post(
                f"{self._base_url}/sendMessage",
                json={"chat_id": self._chat_id, "text": text, "disable_web_page_preview": True},
                timeout=self._timeout,
            )
            resp.raise_for_status()
        except Exception:
            logger.exception("Telegram send failed")

    def get_updates(self, offset: int | None, poll_timeout: int = 25) -> list[dict]:
        params: dict = {"timeout": poll_timeout}
        if offset is not None:
            params["offset"] = offset
        resp = requests.get(
            f"{self._base_url}/getUpdates",
            params=params,
            timeout=poll_timeout + self._timeout,
        )
        resp.raise_for_status()
        return resp.json().get("result", [])
