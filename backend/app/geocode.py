"""Names a point: (19.0176, 72.8172) becomes "Worli, Mumbai".

Every report is filed with coordinates, so the server can always name it
itself instead of trusting whatever the phone managed. OpenStreetMap's
Nominatim needs no key; its policy asks for an identifying User-Agent and at
most one request a second, which a report rate comfortably stays under. The
backfill job sleeps between calls to keep to it.
"""
import logging
import re

import httpx

from .config import get_settings

log = logging.getLogger(__name__)

# Most specific first. A report is somewhere on a street, so the name leads
# with the street or building and follows with the neighbourhood people say
# ("Lower Parel"). Wards and zones are administrative and cover kilometres, so
# every report nearby would read the same; they are skipped.
_SPOT_KEYS = ("road", "pedestrian", "residential", "square", "neighbourhood", "quarter")
_AREA_KEYS = ("suburb", "neighbourhood", "quarter", "village", "hamlet", "town", "city_district")
_CITY_KEYS = ("city", "town", "municipality", "county", "state_district", "state")
_ADMINISTRATIVE = re.compile(r"\b(ward|zone|district)\b", re.IGNORECASE)


def _clean(value: str | None) -> str | None:
    """Drops a bracketed alias: "Shankar Rao Naram Path (Gowalia Chawl Lane)"."""
    if not value:
        return None
    value = re.sub(r"\s*\([^)]*\)", "", value).strip()
    return value or None


def _first(address: dict, keys: tuple[str, ...], *, skip: tuple[str | None, ...] = ()) -> str | None:
    for key in keys:
        value = _clean(address.get(key))
        if value and value not in skip and not _ADMINISTRATIVE.search(value):
            return value
    return None


def _name(address: dict) -> str | None:
    area = _first(address, _AREA_KEYS)
    spot = _first(address, _SPOT_KEYS, skip=(area,))
    if spot and area:
        parts = (spot, area)
    else:
        parts = (spot or area, _first(address, _CITY_KEYS, skip=(spot or area,)))
    name = ", ".join(p for p in parts if p)
    return name[:120] or None


async def locality(
    latitude: float,
    longitude: float,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
) -> str | None:
    """The area and city for a point, or None when the lookup fails. Never raises:
    a report is never refused for want of a place name."""
    settings = get_settings()
    if not settings.geocoder_enabled:
        return None
    try:
        async with httpx.AsyncClient(
            timeout=settings.geocoder_timeout_seconds, transport=transport
        ) as client:
            response = await client.get(
                settings.geocoder_url,
                params={
                    "lat": latitude,
                    "lon": longitude,
                    "format": "jsonv2",
                    "zoom": 17,
                    "addressdetails": 1,
                    "accept-language": "en",
                },
                headers={"User-Agent": settings.geocoder_user_agent},
            )
            response.raise_for_status()
            return _name(response.json().get("address") or {})
    except Exception:
        log.warning("could not name %.5f, %.5f", latitude, longitude, exc_info=True)
        return None
