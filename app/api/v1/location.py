from fastapi import APIRouter, HTTPException, Query, status

from app.schemas.location import LocationDetailsResponse, LocationSearchResponse
from app.services.places_service import get_place_details, search_places

router = APIRouter()


@router.get("/search", response_model=LocationSearchResponse)
async def location_search(
    q: str = Query(..., min_length=2, description="Search query"),
    session_token: str = Query(..., description="Client-generated UUID for billing session grouping"),
):
    try:
        predictions = await search_places(q, session_token)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Places API error: {str(e)}",
        )
    return LocationSearchResponse(predictions=predictions)


@router.get("/details", response_model=LocationDetailsResponse)
async def location_details(
    place_id: str = Query(...),
    session_token: str = Query(...),
):
    try:
        details = await get_place_details(place_id, session_token)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Places API error: {str(e)}",
        )
    return LocationDetailsResponse(**details)
