import asyncio
import json
import logging
import time
from typing import Any

import aiohttp

from config import Config
from item_fields import merge_item_data
from notifier import TelegramNotifier
from storage import ItemStorage

logger = logging.getLogger(__name__)

class PollError(Exception):
    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


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
        self._search_params = _build_search_params(config)

    async def run(self) -> None:
        timeout = aiohttp.ClientTimeout(total=30)
        headers = {
            "Authorization": f"Bearer {self.config.lzt_api_token}",
            "Accept": "application/json",
            "User-Agent": "lolz-bot/1.0",
        }

        async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
            await self.notifier.send_startup_message(
                session,
                self.storage.count(),
                self.config.filter_summary,
            )

            while True:
                started = time.monotonic()
                try:
                    await self._poll_once(session)
                    if self.command_handler:
                        self.command_handler.set_poll_result(True, "OK")
                    self._backoff = self.config.poll_interval
                except PollError as exc:
                    if self.command_handler:
                        self.command_handler.set_poll_result(False, exc.message)
                    logger.error("Poll failed: %s", exc.message)
                    self._backoff = min(self._backoff * 2, 60)
                except aiohttp.ClientResponseError as exc:
                    body = getattr(exc, "message", str(exc))
                    error = f"HTTP {exc.status}: {body}"
                    if self.command_handler:
                        is_rate_limit = exc.status == 429
                        self.command_handler.set_poll_result(
                            is_rate_limit,
                            "Rate limit (429) - warte..." if is_rate_limit else error,
                        )
                    if exc.status == 429:
                        retry_after = float(exc.headers.get("Retry-After", self._backoff * 2))
                        self._backoff = min(max(retry_after, self.config.poll_interval), 60)
                        logger.warning("Rate limited (429), backing off to %.1fs", self._backoff)
                    else:
                        logger.error("API error: %s", error)
                        self._backoff = min(self._backoff * 2, 60)
                except aiohttp.ClientError as exc:
                    error = f"Netzwerkfehler: {exc}"
                    if self.command_handler:
                        self.command_handler.set_poll_result(False, error)
                    logger.error(error)
                    self._backoff = min(self._backoff * 2, 60)
                except Exception as exc:
                    error = f"Unerwarteter Fehler: {exc}"
                    if self.command_handler:
                        self.command_handler.set_poll_result(False, error)
                    logger.exception("Unexpected error during poll")
                    self._backoff = min(self._backoff * 2, 60)

                elapsed = time.monotonic() - started
                sleep_for = max(self._backoff - elapsed, 0.5)
                await asyncio.sleep(sleep_for)

    async def _poll_once(self, session: aiohttp.ClientSession) -> None:
        url = f"{self.config.api_base_url}/riot"
        async with session.get(url, params=self._search_params) as resp:
            body = await resp.text()
            if resp.status >= 400:
                raise PollError(f"HTTP {resp.status}: {body[:300]}")

        try:
            data = json.loads(body)
        except json.JSONDecodeError as exc:
            raise PollError(f"Ungueltige API-Antwort: {body[:200]}") from exc

        if data.get("errors"):
            raise PollError(f"LZT API Fehler: {data['errors']}")

        items = _extract_items(data)
        total = data.get("totalItems")
        if not items:
            if total:
                raise PollError(f"0 Listings geparst (totalItems={total})")
            logger.warning("Poll OK but market returned 0 items for this filter")
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

        for item in reversed(new_items):
            item_id = int(item["item_id"])
            self.storage.mark_seen(item_id, now)
            details = await self._fetch_item_details(session, item_id)
            alert_item = merge_item_data(item, details)
            await self.notifier.send_listing_alert(session, alert_item)
            logger.info("New listing detected: %s - %s", item_id, item.get("title", ""))

    async def _fetch_item_details(self, session: aiohttp.ClientSession, item_id: int) -> dict[str, Any]:
        url = f"{self.config.api_base_url}/{item_id}"
        try:
            async with session.get(url) as resp:
                body = await resp.text()
                if resp.status >= 400:
                    logger.warning("Item detail fetch failed for %s: HTTP %s", item_id, resp.status)
                    return {}
                data = json.loads(body)
        except Exception:
            logger.exception("Item detail fetch failed for %s", item_id)
            return {}

        details: dict[str, Any] = {}
        item = data.get("item")
        if isinstance(item, dict):
            details.update(item)
        item_get = data.get("item_get")
        if isinstance(item_get, dict):
            details["item_get"] = item_get
        return details


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


def _build_search_params(config: Config) -> list[tuple[str, str]]:
    return [
        ("knife", "true"),
        ("valorant_region[]", "EU"),
        ("order_by", "pdate_to_down"),
        ("page", "1"),
        ("pmax", str(config.max_price)),
        ("currency", config.currency),
    ]
