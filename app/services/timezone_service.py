import httpx

from app.config import settings

_TIMEZONEDB_URL = "https://api.timezonedb.com/v2.1/get-time-zone"


async def resolve_timezone(lat: float, lng: float, timestamp: int) -> dict:
    params = {
        "key": settings.timezonedb_api_key,
        "format": "json",
        "by": "position",
        "lat": lat,
        "lng": lng,
        "time": timestamp,
    }
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(_TIMEZONEDB_URL, params=params)
        resp.raise_for_status()
        data = resp.json()

    if data.get("status") != "OK":
        raise ValueError(f"TimeZoneDB error: {data.get('message', 'unknown error')}")

    return {
        "zone_name": data["zoneName"],
        "gmt_offset": data["gmtOffset"],   # seconds
        "abbreviation": data["abbreviation"],
        "dst": data.get("dst") == "1",
    }
