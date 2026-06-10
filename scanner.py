import asyncio
import logging
import time
from typing import Any

import aiohttp

from config import Config
from notifier import TelegramNotifier
from storage import ItemStorage

logger = logging.getLogger(__name__)

SEARCH_PARAMS = {
    "knife": "true",
    "valorant_region[]": "EU",
    "order_by": "pdate_to_down",
    "page": "1",
}


class LZTScanner:
    def __init__(
        self,
        config: Config,
        storage: ItemStorage,
        notifier: TelegramNotifier,
        command_handler: "TelegramCommandHandler | None" = None,
    ) -> None:
        self.config = config
        self.storage = storage
        self.notifier = notifier
        self.command_handler = command_handler
        self._backoff = config.poll_interval
        self._first_run = storage.count() == 0

    async def run(self) -> None:
        timeout = aiohttp.ClientTimeout(total=30)
        headers = {
            "Authorization": f"Bearer {self.config.lzt_api_token}",
            "Accept": "application/json",
        }

        async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
            await self.notifier.send_startup_message(session, self.storage.count())

            while True:
                started = time.monotonic()
                try:
                    await self._poll_once(session)
                    if self.command_handler:
                        self.command_handler.set_last_poll_ok(True)
                    self._backoff = self.config.poll_interval
                except aiohttp.ClientResponseError as exc:
                    if self.command_handler:
                        self.command_handler.set_last_poll_ok(False)
                    if exc.status == 429:
                        retry_after = float(exc.headers.get("Retry-After", self._backoff * 2))
                        self._backoff = min(max(retry_after, self.config.poll_interval), 60)
                        logger.warning("Rate limited (429), backing off to %.1fs", self._backoff)
                    else:
                        logger.error("API error %s: %s", exc.status, exc.message)
                        self._backoff = min(self._backoff * 2, 60)
                except aiohttp.ClientError as exc:
                    if self.command_handler:
                        self.command_handler.set_last_poll_ok(False)
                    logger.error("Network error: %s", exc)
                    self._backoff = min(self._backoff * 2, 60)
                except Exception:
                    if self.command_handler:
                        self.command_handler.set_last_poll_ok(False)
                    logger.exception("Unexpected error during poll")
                    self._backoff = min(self._backoff * 2, 60)

                elapsed = time.monotonic() - started
                sleep_for = max(self._backoff - elapsed, 0.5)
                await asyncio.sleep(sleep_for)

    async def _poll_once(self, session: aiohttp.ClientSession) -> None:
        url = f"{self.config.api_base_url}/riot"
        async with session.get(url, params=SEARCH_PARAMS) as resp:
            if resp.status == 429:
                resp.raise_for_status()
            resp.raise_for_status()
            data = await resp.json()

        if data.get("errors"):
            logger.error("LZT API returned errors: %s", data["errors"])
            return

        items = _extract_items(data)
        if not items:
            logger.warning("Poll OK but 0 listings parsed (totalItems=%s)", data.get("totalItems"))
            return

        logger.info("Poll OK: %d listings on page 1 (tracking %d known)", len(items), self.storage.count())

        now = time.time()

        if self._first_run:
            to_seed = [
                (int(item["item_id"]), now)
                for item in items
                if item.get("item_id") and not self.storage.is_seen(int(item["item_id"]))
            ]
            if to_seed:
                logger.info("First run: seeding %d listings without alerts", len(to_seed))
                self.storage.mark_many_seen(to_seed)
            self._first_run = False
            return

        new_items: list[dict[str, Any]] = []
        for item in items:
            item_id = item.get("item_id")
            if not item_id:
                continue
            if self.storage.is_seen(int(item_id)):
                continue
            new_items.append(item)

        # Process oldest-first so alerts arrive in chronological order.
        for item in reversed(new_items):
            item_id = int(item["item_id"])
            self.storage.mark_seen(item_id, now)
            await self.notifier.send_listing_alert(session, item)
            logger.info("New listing detected: %s - %s", item_id, item.get("title", ""))


def _extract_items(data: dict[str, Any]) -> list[dict[str, Any]]:
    items = data.get("items")
    if not isinstance(items, list):
        return []

    normalized: list[dict[str, Any]] = []
    for entry in items:
        item = _normalize_listing(entry)
        if item is not None:
            normalized.append(item)
    return normalized


def _normalize_listing(entry: Any) -> dict[str, Any] | None:
    if not isinstance(entry, dict):
        return None

    if entry.get("item_id"):
        return entry

    nested = entry.get("item")
    if isinstance(nested, dict) and nested.get("item_id"):
        return nested

    return None
