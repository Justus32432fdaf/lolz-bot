import logging

import aiohttp

from item_fields import (
    extract_competitive_rank,
    extract_inactivity_warning,
    extract_inventory_value,
    extract_knife_count,
    extract_long_inactivity_alert,
    extract_region,
)

logger = logging.getLogger(__name__)


class TelegramNotifier:
    def __init__(self, bot_token: str, chat_id: str) -> None:
        self.bot_token = bot_token
        self.chat_id = chat_id
        self._base_url = f"https://api.telegram.org/bot{bot_token}"

    async def send_listing_alert(self, session: aiohttp.ClientSession, item: dict) -> None:
        item_id = item.get("item_id")
        title = item.get("title", "Unbekannt")
        price = item.get("price", "?")
        currency = item.get("price_currency", "rub").upper()
        region = extract_region(item)
        knife_count = extract_knife_count(item)
        rank = extract_competitive_rank(item)
        inventory_value = extract_inventory_value(item)
        inactivity_warning = extract_inactivity_warning(item)
        long_inactivity_alert = extract_long_inactivity_alert(item)
        url = f"https://lzt.market/{item_id}"

        long_inactive_block = ""
        if long_inactivity_alert:
            long_inactive_block = f"\n\n🔴 <b>{_escape_html(long_inactivity_alert)}</b>"

        text = (
            f"<b>Neuer Valorant Account</b>"
            f"{long_inactive_block}\n\n"
            f"<b>{_escape_html(title)}</b>\n\n"
            f"Preis: <b>{price} {currency}</b>\n"
            f"Region: <b>{_escape_html(region)}</b>\n"
            f"Messer: <b>{knife_count}</b>\n"
            f"Competitive Rank: <b>{_escape_html(rank)}</b>\n"
            f"Inventory Value (VP): <b>{_escape_html(inventory_value)}</b>\n\n"
            f"<i>{_escape_html(inactivity_warning)}</i>\n\n"
            f'<a href="{url}">Zum Listing</a>'
        )

        payload = {
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": False,
        }

        async with session.post(f"{self._base_url}/sendMessage", json=payload) as resp:
            if resp.status != 200:
                body = await resp.text()
                logger.error("Telegram alert failed (%s): %s", resp.status, body)
                resp.raise_for_status()

        logger.info("Alert sent for item %s", item_id)

    async def send_startup_message(
        self,
        session: aiohttp.ClientSession,
        seen_count: int,
        filter_summary: str,
    ) -> None:
        await self._send_message(
            session,
            "<b>LZT Scanner gestartet</b>\n\n"
            f"Filter: {_escape_html(filter_summary)}\n"
            f"Bekannte Listings: {seen_count}\n\n"
            "Sende /status fuer eine Statusabfrage.",
        )

    async def send_status_message(
        self,
        session: aiohttp.ClientSession,
        seen_count: int,
        last_poll_ok: bool,
        last_error: str = "",
        filter_summary: str = "EU, Messer",
    ) -> None:
        status = "OK" if last_poll_ok else "Fehler"
        detail = _escape_html(last_error) if last_error and not last_poll_ok else ""
        detail_block = f"\nDetails: <code>{detail}</code>\n" if detail else "\n"
        await self._send_message(
            session,
            "<b>LZT Scanner Status</b>\n\n"
            f"API: <b>{status}</b>"
            f"{detail_block}\n"
            f"Bekannte Listings: <b>{seen_count}</b>\n"
            f"Filter: {_escape_html(filter_summary)}\n\n"
            "Sende /status fuer eine neue Abfrage.",
        )

    async def _send_message(self, session: aiohttp.ClientSession, text: str) -> None:
        payload = {
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": "HTML",
        }
        async with session.post(f"{self._base_url}/sendMessage", json=payload) as resp:
            if resp.status != 200:
                body = await resp.text()
                logger.error("Telegram send failed (%s): %s", resp.status, body)
                resp.raise_for_status()


def _escape_html(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )
