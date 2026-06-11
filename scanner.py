import asyncio
import json
import logging
import time
from typing import Any

import aiohttp

from config import Config
from item_fields import matches_scan_filters, merge_item_data
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
        self._warmup = True
        self._filtered_params = _build_filtered_search_params(config)
        self._global_params = [("order_by", "pdate_to_down"), ("page", "1")]
        self._process_lock = asyncio.Lock()

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

            await asyncio.gather(
                self._poll_loop(session, "filtered", "/riot", self._filtered_params, self.config.poll_interval),
                self._poll_loop(session, "global", "/", self._global_params, 3.0, filter_client_side=True),
            )

    async def _poll_loop(
        self,
        session: aiohttp.ClientSession,
        name: str,
        path: str,
        params: list[tuple[str, str]],
        interval: float,
        filter_client_side: bool = False,
    ) -> None:
        backoff = interval
        while True:
            started = time.monotonic()
            try:
                await self._poll_once(session, path, params, filter_client_side)
                if self.command_handler and name == "filtered":
                    self.command_handler.set_poll_result(True, "OK")
                backoff = interval
            except PollError as exc:
                if self.command_handler and name == "filtered":
                    self.command_handler.set_poll_result(False, exc.message)
                logger.error("[%s] Poll failed: %s", name, exc.message)
                backoff = min(backoff * 2, 60)
            except Exception:
                if self.command_handler and name == "filtered":
                    self.command_handler.set_poll_result(False, f"{name} poll error")
                logger.exception("[%s] Unexpected poll error", name)
                backoff = min(backoff * 2, 60)

            elapsed = time.monotonic() - started
            await asyncio.sleep(max(backoff - elapsed, 0.5))

    async def _poll_once(
        self,
        session: aiohttp.ClientSession,
        path: str,
        params: list[tuple[str, str]],
        filter_client_side: bool,
    ) -> None:
        url = f"{self.config.api_base_url}{path}"
        async with session.get(url, params=params) as resp:
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
        if filter_client_side:
            items = [
                item
                for item in items
                if matches_scan_filters(
                    item,
                    self.config.max_price,
                    self.config.currency,
                    require_category=True,
                )
            ]

        if not items:
            return

        await self._process_items(session, items)

    async def _process_items(self, session: aiohttp.ClientSession, items: list[dict[str, Any]]) -> None:
        async with self._process_lock:
            await self._process_items_locked(session, items)

    async def _process_items_locked(self, session: aiohttp.ClientSession, items: list[dict[str, Any]]) -> None:
        now = time.time()
        new_items: list[dict[str, Any]] = []
        to_seed: list[tuple[int, float]] = []

        for item in items:
            item_id = item.get("item_id")
            if not item_id:
                continue
            item_id_int = int(item_id)
            if self.storage.is_seen(item_id_int):
                continue

            published = _published_timestamp(item)
            age_seconds = (now - published) if published is not None else None

            if age_seconds is not None and age_seconds > self.config.max_alert_age_seconds:
                logger.info(
                    "Skipping stale listing %s (%d min old, max %d min)",
                    item_id_int,
                    int(age_seconds / 60),
                    int(self.config.max_alert_age_seconds / 60),
                )
                to_seed.append((item_id_int, now))
                continue

            if self._warmup and age_seconds is not None and age_seconds > self.config.startup_grace_seconds:
                to_seed.append((item_id_int, now))
                continue

            new_items.append(item)

        if to_seed:
            self.storage.mark_many_seen(to_seed)
        if self._warmup:
            logger.info("Warmup: stored %d listings without alerts", len(to_seed))
            self._warmup = False

        if not new_items:
            return

        for item in reversed(new_items):
            item_id = int(item["item_id"])
            published = _published_timestamp(item)
            age_min = int((now - published) / 60) if published is not None else None
            if age_min is not None and age_min >= 5:
                logger.warning("Late alert: item %s is %d minutes old", item_id, age_min)

            details = await self._fetch_item_details(session, item_id)
            alert_item = merge_item_data(item, details)
            await self.notifier.send_listing_alert(session, alert_item, age_min)
            self.storage.mark_seen(item_id, now)
            logger.info("New listing detected: %s (%s min old)", item_id, age_min if age_min is not None else "?")

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


def _published_timestamp(item: dict[str, Any]) -> float | None:
    for key in ("published_date", "publishedDate", "pdate"):
        value = item.get(key)
        if value is None:
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return None


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


def _build_filtered_search_params(config: Config) -> list[tuple[str, str]]:
    return [
        ("knife", "true"),
        ("valorant_region[]", "EU"),
        ("order_by", "pdate_to_down"),
        ("page", "1"),
        ("pmax", str(config.max_price)),
        ("currency", config.currency),
    ]
