import asyncio
import logging

import aiohttp

from notifier import TelegramNotifier
from storage import ItemStorage

logger = logging.getLogger(__name__)


class TelegramCommandHandler:
    def __init__(self, bot_token: str, chat_id: str, notifier: TelegramNotifier, storage: ItemStorage) -> None:
        self.chat_id = str(chat_id)
        self.notifier = notifier
        self.storage = storage
        self._base_url = f"https://api.telegram.org/bot{bot_token}"
        self._offset = 0
        self._last_poll_ok = False
        self._last_error = "Noch kein Poll ausgefuehrt"

    def set_poll_result(self, ok: bool, error: str | None = None) -> None:
        self._last_poll_ok = ok
        if error:
            self._last_error = error

    def get_last_error(self) -> str:
        return self._last_error

    async def run(self) -> None:
        timeout = aiohttp.ClientTimeout(total=35)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            while True:
                try:
                    await self._poll_updates(session)
                except asyncio.CancelledError:
                    raise
                except Exception:
                    logger.exception("Telegram command handler error")
                    await asyncio.sleep(5)

    async def _poll_updates(self, session: aiohttp.ClientSession) -> None:
        params = {"timeout": 30, "offset": self._offset}
        async with session.get(f"{self._base_url}/getUpdates", params=params) as resp:
            resp.raise_for_status()
            data = await resp.json()

        if not data.get("ok"):
            logger.warning("Telegram getUpdates failed: %s", data)
            await asyncio.sleep(3)
            return

        for update in data.get("result", []):
            self._offset = update["update_id"] + 1
            await self._handle_update(session, update)

    async def _handle_update(self, session: aiohttp.ClientSession, update: dict) -> None:
        message = update.get("message") or update.get("edited_message")
        if not message:
            return

        chat_id = str(message.get("chat", {}).get("id", ""))
        if chat_id != self.chat_id:
            return

        text = (message.get("text") or "").strip().lower()
        if text not in ("/start", "/status"):
            return

        await self.notifier.send_status_message(
            session,
            self.storage.count(),
            self._last_poll_ok,
            self._last_error,
        )
        logger.info("Replied to %s command", text)
