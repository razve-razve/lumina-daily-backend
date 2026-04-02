import httpx

from app.config import settings

_AUTOCOMPLETE_URL = "https://maps.googleapis.com/maps/api/place/autocomplete/json"
_DETAILS_URL = "https://maps.googleapis.com/maps/api/place/details/json"


async def search_places(query: str, session_token: str) -> list[dict]:
    params = {
        "input": query,
        "types": "(cities)",
        "key": settings.google_places_api_key,
        "sessiontoken": session_token,
    }
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(_AUTOCOMPLETE_URL, params=params)
        resp.raise_for_status()
        data = resp.json()

    predictions = []
    for p in data.get("predictions", []):
        st = p.get("structured_formatting", {})
        predictions.append({
            "place_id": p["place_id"],
            "description": p["description"],
            "main_text": st.get("main_text", ""),
            "secondary_text": st.get("secondary_text", ""),
        })
    return predictions


async def get_place_details(place_id: str, session_token: str) -> dict:
    params = {
        "place_id": place_id,
        "fields": "place_id,name,formatted_address,geometry",
        "key": settings.google_places_api_key,
        "sessiontoken": session_token,
    }
    async with httpx.AsyncClient(timeout=10.0) as client:
        resp = await client.get(_DETAILS_URL, params=params)
        resp.raise_for_status()
        data = resp.json()

    result = data.get("result", {})
    location = result.get("geometry", {}).get("location", {})
    return {
        "place_id": result.get("place_id", place_id),
        "display_name": result.get("formatted_address", ""),
        "latitude": location.get("lat"),
        "longitude": location.get("lng"),
    }
