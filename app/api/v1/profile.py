from __future__ import annotations
import asyncio
from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.ephemeris import birth_to_julian_day, calculate_natal_chart
from app.db.models import Profile
from app.db.models import User
from app.db.repositories.advice_repository import delete_advice
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
from app.services.redis_service import delete_cached_advice

router = APIRouter()


def _chart_signs(natal_chart: dict) -> tuple[str, str, str]:
    planets = natal_chart.get("planets", {})
    sun_sign   = planets.get("Sun",  {}).get("sign", "Unknown")
    moon_sign  = planets.get("Moon", {}).get("sign", "Unknown")
    rising     = natal_chart.get("houses", {}).get("asc_sign", "Unknown")
    return sun_sign, moon_sign, rising


def _natal_response(profile: Profile) -> NatalChartResponse:
    sun_sign, moon_sign, rising = _chart_signs(profile.natal_chart_json)
    return NatalChartResponse(
        natal_chart=profile.natal_chart_json,
        sun_sign=sun_sign,
        moon_sign=moon_sign,
        rising_sign=rising,
        time_known=profile.time_known,
        name=profile.name,
        gender=profile.gender,
        date_of_birth=profile.date_of_birth,
        time_of_birth=profile.time_of_birth,
        city_name=profile.city_name,
        latitude=profile.latitude,
        longitude=profile.longitude,
    )


async def _invalidate_today_advice(db: AsyncSession, user_id, mode: str) -> None:
    today = datetime.now(timezone.utc).date()
    await delete_cached_advice(str(user_id), today.isoformat(), mode)
    await delete_advice(db, user_id, today, mode)


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
    return _natal_response(profile)


@router.put("/update", response_model=NatalChartResponse)
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

    # If any birth data changed, recalculate natal chart
    birth_fields = [body.date_of_birth, body.time_of_birth, body.latitude, body.longitude,
                    body.timezone_id, body.utc_offset_at_birth, body.time_known, body.city_name]
    if any(f is not None for f in birth_fields):
        if body.date_of_birth is not None:
            profile.date_of_birth = body.date_of_birth
        if body.time_of_birth is not None:
            profile.time_of_birth = body.time_of_birth
        if body.time_known is not None:
            profile.time_known = body.time_known
        if body.city_name is not None:
            profile.city_name = body.city_name
        if body.latitude is not None:
            profile.latitude = body.latitude
        if body.longitude is not None:
            profile.longitude = body.longitude
        if body.timezone_id is not None:
            profile.timezone_id = body.timezone_id
        if body.utc_offset_at_birth is not None:
            profile.utc_offset_at_birth = body.utc_offset_at_birth

        birth_time = profile.time_of_birth
        jd = await asyncio.get_event_loop().run_in_executor(
            None,
            birth_to_julian_day,
            profile.date_of_birth.year,
            profile.date_of_birth.month,
            profile.date_of_birth.day,
            birth_time.hour,
            birth_time.minute,
            birth_time.second,
            profile.utc_offset_at_birth,
        )
        profile.natal_chart_json = await asyncio.get_event_loop().run_in_executor(
            None, calculate_natal_chart, jd, profile.latitude, profile.longitude
        )

    advice_affecting_change = any([
        body.name is not None and body.name != profile.name,
        body.gender is not None and body.gender != profile.gender,
        body.date_of_birth is not None,
        body.time_of_birth is not None,
        body.latitude is not None,
        body.longitude is not None,
    ])

    await update_profile(db, profile)

    if advice_affecting_change:
        await _invalidate_today_advice(db, current_user.id, profile.interpretation_mode)

    return _natal_response(profile)


@router.get("/natal", response_model=NatalChartResponse)
async def get_natal_chart(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    profile = await get_profile_by_user_id(db, current_user.id)
    if not profile:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Profile not found")
    return _natal_response(profile)
