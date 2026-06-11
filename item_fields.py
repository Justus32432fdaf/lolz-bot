from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

VALORANT_RANKS: dict[int, str] = {
    3: "Iron 1",
    4: "Iron 2",
    5: "Iron 3",
    6: "Bronze 1",
    7: "Bronze 2",
    8: "Bronze 3",
    9: "Silver 1",
    10: "Silver 2",
    11: "Silver 3",
    12: "Gold 1",
    13: "Gold 2",
    14: "Gold 3",
    15: "Platinum 1",
    16: "Platinum 2",
    17: "Platinum 3",
    18: "Diamond 1",
    19: "Diamond 2",
    20: "Diamond 3",
    21: "Ascendant 1",
    22: "Ascendant 2",
    23: "Ascendant 3",
    24: "Immortal 1",
    25: "Immortal 2",
    26: "Immortal 3",
    27: "Radiant",
}

INACTIVITY_WARNING_THRESHOLD_DAYS = 30


def merge_item_data(*sources: dict[str, Any]) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    for source in sources:
        if isinstance(source, dict):
            merged.update(source)
    return merged


def extract_region(item: dict[str, Any]) -> str:
    value = _find_value(
        item,
        "riot_valorant_region",
        "valorant_region",
        "region",
    )
    return str(value) if value is not None else "Unbekannt"


def extract_knife_count(item: dict[str, Any]) -> str:
    value = _find_value(
        item,
        "valorant_knife",
        "knife_count",
        "knifes",
        "knife",
    )
    return str(value) if value is not None else "1+"


def extract_competitive_rank(item: dict[str, Any]) -> str:
    rank_name = _find_value(
        item,
        "riot_valorant_rank_name",
        "valorant_rank_name",
        "rank_name",
        "riot_rank_name",
    )
    if rank_name:
        return str(rank_name)

    rank_id = _find_value(
        item,
        "riot_valorant_rank",
        "valorant_rank",
        "rank",
        "riot_rank",
        "rmin",
    )
    if rank_id is not None:
        try:
            mapped = VALORANT_RANKS.get(int(rank_id))
            if mapped:
                return mapped
        except (TypeError, ValueError):
            pass
        return str(rank_id)

    return "Unranked / Unbekannt"


def extract_inventory_value(item: dict[str, Any]) -> str:
    value = _find_value(
        item,
        "riot_valorant_inventory_value",
        "valorant_inventory_value",
        "riot_inventory_value",
        "inventory_value",
        "inv_value",
        "inventoryValue",
        "valorant_inventory",
    )
    if value is None:
        return "Unbekannt"

    if isinstance(value, str):
        text = value.strip()
        if text.lower().endswith("vp"):
            return text
        digits = "".join(ch for ch in text if ch.isdigit())
        if digits:
            return _format_vp(int(digits))
        return f"{text} VP"

    try:
        return _format_vp(int(float(value)))
    except (TypeError, ValueError):
        return f"{value} VP"


def _format_vp(amount: int) -> str:
    formatted = f"{amount:,}".replace(",", ".")
    return f"{formatted} VP"


def extract_inactivity_days(item: dict[str, Any]) -> int | None:
    daybreak = _find_value(item, "daybreak", "days_offline", "offline_days")
    if daybreak is not None:
        try:
            return max(int(daybreak), 0)
        except (TypeError, ValueError):
            pass

    timestamp = _find_value(
        item,
        "riot_last_activity",
        "riot_valorant_last_activity",
        "last_activity",
        "last_activity_date",
        "valorant_last_activity",
    )
    if timestamp is not None:
        try:
            dt = datetime.fromtimestamp(float(timestamp), tz=timezone.utc)
            now = datetime.now(timezone.utc)
            return max((now.date() - dt.date()).days, 0)
        except (TypeError, ValueError, OSError):
            pass

    return None


def is_inactive_over_threshold(
    item: dict[str, Any],
    threshold_days: int = INACTIVITY_WARNING_THRESHOLD_DAYS,
) -> bool:
    days = extract_inactivity_days(item)
    return days is not None and days > threshold_days


def extract_long_inactivity_alert(item: dict[str, Any]) -> str | None:
    days = extract_inactivity_days(item)
    if days is None or days <= INACTIVITY_WARNING_THRESHOLD_DAYS:
        return None
    return (
        f"WARNUNG: Account seit {days} Tagen inaktiv "
        f"(>{INACTIVITY_WARNING_THRESHOLD_DAYS} Tage)! Hohes Rueckhol-Risiko."
    )


def extract_inactivity(item: dict[str, Any]) -> str:
    phrase = _find_value(
        item,
        "riot_last_activity_text",
        "last_activity_text",
        "activity_text",
        "last_activity_phrase",
    )
    if phrase:
        return str(phrase)

    days = extract_inactivity_days(item)
    if days is not None:
        if days <= 0:
            return "Heute aktiv"
        if days == 1:
            return "Zuletzt aktiv: gestern"
        return f"Zuletzt aktiv: vor {days} Tagen"

    return "Unbekannt"


def extract_inactivity_warning(item: dict[str, Any]) -> str:
    inactivity = extract_inactivity(item)
    return (
        f"Letzte Nutzung: {inactivity}. "
        "Der Besitzer kann den Account zurueckholen — du koenntest den Zugang verlieren."
    )


def _format_last_activity(timestamp: float) -> str:
    dt = datetime.fromtimestamp(timestamp, tz=timezone.utc)
    now = datetime.now(timezone.utc)
    day_diff = (now.date() - dt.date()).days
    time_part = dt.strftime("%H:%M UTC")

    if day_diff <= 0:
        return f"heute um {time_part}"
    if day_diff == 1:
        return f"gestern um {time_part}"
    if day_diff < 7:
        return f"vor {day_diff} Tagen ({dt.strftime('%d.%m.%Y %H:%M UTC')})"
    return dt.strftime("%d.%m.%Y %H:%M UTC")


def _find_value(item: dict[str, Any], *keys: str) -> Any:
    containers: list[dict[str, Any]] = [item]
    for nested_key in ("item_get", "riot", "valorant", "account_data", "data"):
        nested = item.get(nested_key)
        if isinstance(nested, dict):
            containers.append(nested)

    for container in containers:
        for key in keys:
            if key in container and container[key] not in (None, "", []):
                return container[key]

    return None
