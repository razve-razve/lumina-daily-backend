from fastapi import APIRouter, HTTPException, Query, status

from app.schemas.location import TimezoneResponse
from app.services.timezone_service import resolve_timezone

router = APIRouter()


@router.get("/resolve", response_model=TimezoneResponse)
async def timezone_resolve(
    lat: float = Query(..., ge=-90, le=90),
    lng: float = Query(..., ge=-180, le=180),
    timestamp: int = Query(..., description="Unix timestamp of the birth moment (UTC)"),
):
    try:
        result = await resolve_timezone(lat, lng, timestamp)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"TimeZoneDB error: {str(e)}",
        )
    return TimezoneResponse(**result)
