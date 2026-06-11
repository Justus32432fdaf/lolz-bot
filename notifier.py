import logging

import aiohttp

from item_fields import (
    INACTIVITY_WARNING_THRESHOLD_DAYS,
    extract_competitive_rank,
    extract_inactivity_days,
    extract_inactivity_short,
    extract_inventory_value,
    extract_knife_names,
    extract_region,
)

logger = logging.getLogger(__name__)


class TelegramNotifier:
    def __init__(self, bot_token: str, chat_id: str) -> None:
        self.bot_token = bot_token
        self.chat_id = chat_id
        self._base_url = f"https://api.telegram.org/bot{bot_token}"

    async def send_listing_alert(
        self,
        session: aiohttp.ClientSession,
        item: dict,
        listing_age_min: int | None = None,
    ) -> None:
        item_id = item.get("item_id")
        price = item.get("price", "?")
        currency = item.get("price_currency", "eur").upper()
        region = extract_region(item)
        knife_names = extract_knife_names(item)
        rank = extract_competitive_rank(item)
        inventory_value = extract_inventory_value(item)
        inactivity = extract_inactivity_short(item)
        inactive_days = extract_inactivity_days(item)
        url = f"https://lzt.market/{item_id}"

        warning = ""
        if inactive_days is not None and inactive_days > INACTIVITY_WARNING_THRESHOLD_DAYS:
            warning = f"🔴 <b>{inactive_days}d inaktiv — Rueckhol-Risiko!</b>\n\n"

        if listing_age_min is None:
            age_line = ""
        elif listing_age_min <= 0:
            age_line = "🕐 Gerade gepostet\n"
        elif listing_age_min >= 5:
            age_line = f"🕐 <b>{listing_age_min} Min alt</b> — spaete Meldung\n"
        else:
            age_line = f"🕐 {listing_age_min} Min alt\n"

        text = (
            f"{warning}"
            f"{age_line}"
            f"<b>{price} {currency}</b> · {_escape_html(rank)} · "
            f"{_escape_html(inventory_value)} · {_escape_html(region)}\n"
            f"🔪 {_escape_html(knife_names)}\n"
            f"Inaktiv: {inactivity}\n\n"
            f'<a href="{url}">→ Listing</a>'
        )

        payload = {
            "chat_id": self.chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
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
            f"<b>Scanner läuft</b>\n{_escape_html(filter_summary)} · {seen_count} bekannt",
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
        detail = f" ({_escape_html(last_error)})" if last_error and not last_poll_ok else ""
        await self._send_message(
            session,
            f"<b>Status: {status}</b>{detail}\n"
            f"{_escape_html(filter_summary)} · {seen_count} bekannt",
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
