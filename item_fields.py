from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

_SKIN_CONTAINER_KEYS = ("item_get", "riot", "valorant", "account_data", "data")
_SKIP_DEEP_KEYS = frozenset(
    {
        "title",
        "description",
        "information",
        "searchurl",
        "login",
        "password",
        "temp_email",
        "copy_format_data",
        "seller",
    }
)
_INVALID_KNIFE_PATTERNS = (
    re.compile(r"vp\s*inv", re.I),
    re.compile(r"^\d+[\d\s.,]*\s*(knives?|knife)\s*$", re.I),
    re.compile(r"^knives?$", re.I),
    re.compile(r"lzt\.market", re.I),
    re.compile(r"https?://", re.I),
    re.compile(r"^\d[\d\s.,]+$"),
)

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


def extract_knife_names(item: dict[str, Any]) -> str:
    names = _collect_knife_names(item)
    if names:
        return " · ".join(names)

    count = extract_knife_count(item)
    if count.isdigit() and int(count) > 0:
        return f"{count} Messer (Namen nicht in API)"
    return "?"


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


def extract_inactivity_short(item: dict[str, Any]) -> str:
    days = extract_inactivity_days(item)
    if days is None:
        return "?"
    if days <= 0:
        return "heute"
    if days == 1:
        return "1 Tag"
    return f"{days} Tage"


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


def _collect_knife_names(item: dict[str, Any]) -> list[str]:
    names: list[str] = []

    for raw in _find_lists(
        item,
        "valorant_knives",
        "knives",
        "knife_skins",
        "riot_valorant_knives",
        "valorant_knife_skins",
        "weaponSkin",
        "weapon_skins",
        "valorant_weapon_skins",
        "riot_valorant_weapon_skins",
    ):
        names.extend(_knife_names_from_skin_list(raw))

    for container_key in _SKIN_CONTAINER_KEYS:
        container = item.get(container_key)
        if isinstance(container, dict):
            _deep_collect_knife_names(container, names)

    names.extend(_parse_knives_from_title(str(item.get("title", ""))))
    names.extend(_parse_knives_from_text_fields(item))

    return _unique_preserve_order(
        name for name in names if _is_valid_knife_display_name(name)
    )


def _knife_names_from_skin_list(value: Any) -> list[str]:
    names: list[str] = []
    if isinstance(value, str):
        if _is_melee_skin_token(value):
            names.append(_clean_skin_token(value))
    elif isinstance(value, dict):
        name = value.get("name") or value.get("title") or value.get("displayName")
        skin_type = " ".join(
            str(value.get(key, "")) for key in ("type", "category", "weaponType", "slot", "weapon")
        ).lower()
        if name and ("knife" in skin_type or "melee" in skin_type or _is_valid_knife_display_name(str(name))):
            names.append(str(name).strip())
    elif isinstance(value, list):
        for entry in value:
            names.extend(_knife_names_from_skin_list(entry))
    return names


def _deep_collect_knife_names(value: Any, names: list[str], parent_key: str = "") -> None:
    if isinstance(value, dict):
        if parent_key.lower() in _SKIP_DEEP_KEYS:
            return

        name = value.get("name") or value.get("title") or value.get("displayName")
        skin_type = " ".join(
            str(value.get(key, "")) for key in ("type", "category", "weaponType", "slot", "weapon")
        ).lower()
        if name and ("knife" in skin_type or "melee" in skin_type):
            names.append(str(name).strip())

        for key, nested in value.items():
            if str(key).lower() in _SKIP_DEEP_KEYS:
                continue
            _deep_collect_knife_names(nested, names, str(key))
    elif isinstance(value, list):
        for nested in value:
            _deep_collect_knife_names(nested, names, parent_key)
    elif isinstance(value, str) and _is_melee_skin_token(value):
        names.append(_clean_skin_token(value))


def _parse_knives_from_title(title: str) -> list[str]:
    if not title:
        return []

    names: list[str] = []
    for match in re.finditer(r'Blade\s*"([^"]+)"', title, re.IGNORECASE):
        blade = match.group(1).strip()
        if _is_valid_knife_display_name(blade):
            names.append(blade)

    for match in re.finditer(
        r'(?<![\w])([A-Z0-9][A-Za-z0-9\'\-\s]{2,}?\s+Knife)(?![\w])',
        title,
    ):
        candidate = match.group(1).strip()
        if _is_valid_knife_display_name(candidate):
            names.append(candidate)

    return names


def _parse_knives_from_text_fields(item: dict[str, Any]) -> list[str]:
    names: list[str] = []
    for key in ("information", "description"):
        text = item.get(key)
        if not isinstance(text, str):
            continue
        for match in re.finditer(
            r'(?:Knife|Messer|Blade)\s*[:\-]?\s*"?([^"\n|<]+?)"?(?:\s|$|\|)',
            text,
            re.IGNORECASE,
        ):
            candidate = match.group(1).strip()
            if _is_valid_knife_display_name(candidate):
                names.append(candidate)
    return names


def _is_melee_skin_token(value: str) -> bool:
    text = value.strip()
    if not text or not _is_valid_knife_display_name(text):
        return False
    lower = text.lower()
    if "melee" in lower:
        return True
    if re.search(r"\bknife\b", lower) and not re.match(r"^\d+\s*knives?$", lower):
        return True
    return bool(re.search(r"\b(karambit|katana|yaiba|kunitsuna)\b", lower))


def _clean_skin_token(value: str) -> str:
    text = value.strip()
    if "melee" in text.lower() and "/" in text:
        return text.split("/")[-1].strip()
    return text


def _is_valid_knife_display_name(name: str) -> bool:
    text = name.strip()
    if len(text) < 4:
        return False
    for pattern in _INVALID_KNIFE_PATTERNS:
        if pattern.search(text):
            return False
    if "|" in text:
        return False
    return True


def _unique_preserve_order(names: Any) -> list[str]:
    seen: set[str] = set()
    unique: list[str] = []
    for name in names:
        key = name.casefold()
        if key in seen:
            continue
        seen.add(key)
        unique.append(name)
    return unique


def _find_lists(item: dict[str, Any], *keys: str) -> list[Any]:
    containers: list[dict[str, Any]] = [item]
    for nested_key in ("item_get", "riot", "valorant", "account_data", "data"):
        nested = item.get(nested_key)
        if isinstance(nested, dict):
            containers.append(nested)

    results: list[Any] = []
    for container in containers:
        for key in keys:
            value = container.get(key)
            if isinstance(value, list) and value:
                results.append(value)
    return results


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
