import logging

import aiohttp

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
        region = _extract_region(item)
        knife_count = _extract_knife_count(item)
        url = f"https://lzt.market/{item_id}"

        text = (
            f"<b>Neuer Valorant Account</b>\n\n"
            f"<b>{_escape_html(title)}</b>\n\n"
            f"Preis: <b>{price} {currency}</b>\n"
            f"Region: <b>{_escape_html(region)}</b>\n"
            f"Messer: <b>{knife_count}</b>\n\n"
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

    async def send_startup_message(self, session: aiohttp.ClientSession, seen_count: int) -> None:
        await self._send_message(
            session,
            "<b>LZT Scanner gestartet</b>\n\n"
            "Filter: EU Region, hat Messer\n"
            f"Bekannte Listings: {seen_count}\n\n"
            "Sende /status fuer eine Statusabfrage.",
        )

    async def send_status_message(
        self,
        session: aiohttp.ClientSession,
        seen_count: int,
        last_poll_ok: bool,
    ) -> None:
        status = "OK" if last_poll_ok else "Fehler beim letzten Poll"
        await self._send_message(
            session,
            "<b>LZT Scanner Status</b>\n\n"
            f"API: <b>{status}</b>\n"
            f"Bekannte Listings: <b>{seen_count}</b>\n"
            "Filter: EU, Messer\n\n"
            "Der Bot antwortet nur auf /status und /start.",
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


def _extract_region(item: dict) -> str:
    riot = item.get("riot_valorant_region") or item.get("valorant_region")
    if riot:
        return str(riot)
    item_get = item.get("item_get") or {}
    if isinstance(item_get, dict):
        region = item_get.get("valorant_region") or item_get.get("riot_valorant_region")
        if region:
            return str(region)
    return "EU"


def _extract_knife_count(item: dict) -> str:
    for key in ("valorant_knife", "knife_count", "knifes"):
        value = item.get(key)
        if value is not None:
            return str(value)
    item_get = item.get("item_get") or {}
    if isinstance(item_get, dict):
        value = item_get.get("valorant_knife") or item_get.get("knife_count")
        if value is not None:
            return str(value)
    return "1+"


def _escape_html(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )
