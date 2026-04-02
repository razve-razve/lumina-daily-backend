import asyncio

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.ephemeris import birth_to_julian_day, calculate_natal_chart
from app.db.models import Profile
from app.db.models import User
from app.db.repositories.profile_repository import (
    create_profile,
    get_profile_by_user_id,
    update_profile,
)
from app.dependencies import get_current_user, get_db
from app.schemas.profile import (
    NatalChartResponse,
    ProfileCreateRequest,
    ProfileResponse,
    ProfileUpdateRequest,
)

router = APIRouter()


def _chart_signs(natal_chart: dict) -> tuple[str, str, str]:
    planets = natal_chart.get("planets", {})
    sun_sign   = planets.get("Sun",  {}).get("sign", "Unknown")
    moon_sign  = planets.get("Moon", {}).get("sign", "Unknown")
    rising     = natal_chart.get("houses", {}).get("asc_sign", "Unknown")
    return sun_sign, moon_sign, rising


@router.post("/create", status_code=status.HTTP_201_CREATED, response_model=NatalChartResponse)
async def create_profile_endpoint(
    body: ProfileCreateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    existing = await get_profile_by_user_id(db, current_user.id)
    if existing:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Profile already exists. Use PUT /profile/update.")

    birth_time = body.time_of_birth
    jd = await asyncio.get_event_loop().run_in_executor(
        None,
        birth_to_julian_day,
        body.date_of_birth.year,
        body.date_of_birth.month,
        body.date_of_birth.day,
        birth_time.hour,
        birth_time.minute,
        birth_time.second,
        body.utc_offset_at_birth,
    )
    natal_chart = await asyncio.get_event_loop().run_in_executor(
        None, calculate_natal_chart, jd, body.latitude, body.longitude
    )

    profile = Profile(
        user_id=current_user.id,
        name=body.name,
        gender=body.gender,
        date_of_birth=body.date_of_birth,
        time_of_birth=body.time_of_birth,
        time_known=body.time_known,
        city_name=body.city_name,
        latitude=body.latitude,
        longitude=body.longitude,
        timezone_id=body.timezone_id,
        utc_offset_at_birth=body.utc_offset_at_birth,
        natal_chart_json=natal_chart,
        interpretation_mode=body.interpretation_mode,
        notification_time=body.notification_time,
    )
    await create_profile(db, profile)

    sun_sign, moon_sign, rising = _chart_signs(natal_chart)
    return NatalChartResponse(
        natal_chart=natal_chart,
        sun_sign=sun_sign,
        moon_sign=moon_sign,
        rising_sign=rising,
        time_known=body.time_known,
    )


@router.put("/update", response_model=ProfileResponse)
async def update_profile_endpoint(
    body: ProfileUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    profile = await get_profile_by_user_id(db, current_user.id)
    if not profile:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Profile not found")

    if body.name is not None:
        profile.name = body.name
    if body.gender is not None:
        profile.gender = body.gender
    if body.notification_time is not None:
        profile.notification_time = body.notification_time
    if body.interpretation_mode is not None:
        profile.interpretation_mode = body.interpretation_mode

    await update_profile(db, profile)
    sun_sign, moon_sign, rising = _chart_signs(profile.natal_chart_json)

    return ProfileResponse(
        name=profile.name,
        gender=profile.gender,
        sun_sign=sun_sign,
        moon_sign=moon_sign,
        rising_sign=rising,
        time_known=profile.time_known,
        city_name=profile.city_name,
        interpretation_mode=profile.interpretation_mode,
    )


@router.get("/natal", response_model=NatalChartResponse)
async def get_natal_chart(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    profile = await get_profile_by_user_id(db, current_user.id)
    if not profile:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Profile not found")

    sun_sign, moon_sign, rising = _chart_signs(profile.natal_chart_json)
    return NatalChartResponse(
        natal_chart=profile.natal_chart_json,
        sun_sign=sun_sign,
        moon_sign=moon_sign,
        rising_sign=rising,
        time_known=profile.time_known,
    )
