"""Telegram delivery + a minimal command listener.

Sending uses the Bot API ``sendMessage`` endpoint (HTML formatting). The
optional command listener long-polls ``getUpdates`` and hands recognised
commands to a callback so the bot can answer ``/status``, ``/symbols`` etc.

Both halves degrade gracefully: if no token/chat is configured the notifier
logs the message instead of raising, so the engine can run in a dry mode.
"""
from __future__ import annotations

import asyncio
from typing import Awaitable, Callable

import aiohttp

from ..utils.logging import get_logger

log = get_logger(__name__)

CommandHandler = Callable[[str, str], Awaitable[str | None]]


class TelegramNotifier:
    def __init__(
        self,
        token: str | None,
        chat_ids: list[str] | None,
        api_base: str = "https://api.telegram.org",
    ) -> None:
        self.token = token
        self.chat_ids = [c for c in (chat_ids or []) if c]
        self.api_base = api_base.rstrip("/")
        self.enabled = bool(token and self.chat_ids)
        self._session: aiohttp.ClientSession | None = None
        if not self.enabled:
            log.warning(
                "Telegram disabled (missing token or chat id); "
                "messages will be logged only."
            )

    async def __aenter__(self) -> "TelegramNotifier":
        self._session = aiohttp.ClientSession()
        return self

    async def __aexit__(self, *exc) -> None:
        if self._session:
            await self._session.close()
            self._session = None

    def _api(self, method: str) -> str:
        return f"{self.api_base}/bot{self.token}/{method}"

    async def _session_or_temp(self) -> aiohttp.ClientSession:
        if self._session is None:
            self._session = aiohttp.ClientSession()
        return self._session

    async def send(self, text: str, *, parse_mode: str = "HTML") -> None:
        if not self.enabled:
            log.info("[telegram-dry] %s", text.replace("\n", " | "))
            return
        session = await self._session_or_temp()
        for chat_id in self.chat_ids:
            payload = {
                "chat_id": chat_id,
                "text": text,
                "parse_mode": parse_mode,
                "disable_web_page_preview": True,
            }
            try:
                async with session.post(
                    self._api("sendMessage"), json=payload, timeout=15
                ) as resp:
                    if resp.status != 200:
                        body = await resp.text()
                        log.error("telegram send failed %s: %s", resp.status, body)
            except Exception as exc:  # noqa: BLE001
                log.error("telegram send error: %s", exc)

    async def listen_commands(self, stop: asyncio.Event, handler: CommandHandler) -> None:
        """Long-poll for commands until ``stop`` is set. No-op when disabled."""
        if not self.enabled:
            return
        session = await self._session_or_temp()
        offset = 0
        while not stop.is_set():
            try:
                async with session.get(
                    self._api("getUpdates"),
                    params={"offset": offset, "timeout": 25},
                    timeout=40,
                ) as resp:
                    data = await resp.json()
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                log.debug("getUpdates error: %s", exc)
                await asyncio.sleep(3)
                continue

            for update in data.get("result", []):
                offset = update["update_id"] + 1
                message = update.get("message") or update.get("channel_post")
                if not message:
                    continue
                text = (message.get("text") or "").strip()
                if not text.startswith("/"):
                    continue
                parts = text[1:].split(maxsplit=1)
                cmd = parts[0].split("@")[0].lower()
                args = parts[1] if len(parts) > 1 else ""
                try:
                    reply = await handler(cmd, args)
                except Exception as exc:  # noqa: BLE001
                    log.error("command handler error: %s", exc)
                    reply = "⚠️ command failed"
                if reply:
                    await self.send(reply)
