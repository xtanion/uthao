"""Names a point: (19.0176, 72.8172) becomes "Worli, Mumbai".

Every report is filed with coordinates, so the server can always name it
itself instead of trusting whatever the phone managed. OpenStreetMap's
Nominatim needs no key; its policy asks for an identifying User-Agent and at
most one request a second, which a report rate comfortably stays under. The
backfill job sleeps between calls to keep to it.
"""
import logging

import httpx

from .config import get_settings

log = logging.getLogger(__name__)

# Most specific first. Indian addresses in OSM put the neighbourhood people
# actually say ("Worli", "Bandra West") in one of these, depending on the city.
_AREA_KEYS = ("suburb", "neighbourhood", "quarter", "city_district", "village", "hamlet")
_CITY_KEYS = ("city", "town", "municipality", "county", "state_district", "state")


def _name(address: dict) -> str | None:
    area = next((address[k] for k in _AREA_KEYS if address.get(k)), None)
    city = next((address[k] for k in _CITY_KEYS if address.get(k)), None)
    parts = [p for i, p in enumerate((area, city)) if p and p not in (area, city)[:i]]
    name = ", ".join(parts)
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
                    "zoom": 14,
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
