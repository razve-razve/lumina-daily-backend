from __future__ import annotations
import asyncio
from datetime import date, datetime, timezone
from typing import Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.advice_generator import generate_all_advice, generate_transit_explanation
from app.core.ephemeris import (
    calculate_current_transits,
    calculate_transit_aspects_to_natal,
    get_moon_phase,
    now_julian_day,
)
from app.core.scoring import build_transit_tags, score_categories
from app.db.models import DailyAdvice, User
from app.db.repositories.advice_repository import create_advice, get_advice
from app.db.repositories.profile_repository import get_profile_by_user_id
from app.dependencies import get_current_user, get_db
from app.schemas.advice import CategoryCard, DailyAdviceResponse
from app.services.redis_service import cache_advice, get_cached_advice, redis_get, redis_setex

router = APIRouter()


def _user_local_date(device_timezone: str | None) -> date:
    """Return the current calendar date in the user's local timezone (UTC fallback)."""
    if not device_timezone:
        return datetime.now(timezone.utc).date()
    try:
        tz = ZoneInfo(device_timezone)
        return datetime.now(tz).date()
    except (ZoneInfoNotFoundError, Exception):
        return datetime.now(timezone.utc).date()


def _to_response(advice: DailyAdvice) -> DailyAdviceResponse:
    return DailyAdviceResponse(
        date=advice.date,
        generated_at=advice.generated_at,
        mode=advice.mode,
        theme=advice.theme,
        moon_phase=advice.moon_phase,
        transit_tags=advice.transit_tags or [],
        love=CategoryCard(score=advice.love_score, text=advice.love_text),
        work=CategoryCard(score=advice.work_score, text=advice.work_text),
        energy=CategoryCard(score=advice.energy_score, text=advice.energy_text),
        communication=CategoryCard(score=advice.communication_score, text=advice.communication_text),
        mood=CategoryCard(score=advice.mood_score, text=advice.mood_text),
        watch_for=advice.risk_text,
    )


async def _generate_and_store(
    profile,
    user_id,
    language: str,
    target_date: date,
    db: AsyncSession,
) -> DailyAdvice:
    mode = profile.interpretation_mode
    natal_chart = profile.natal_chart_json
    natal_planets = natal_chart.get("planets", {})

    jd_now = await asyncio.get_event_loop().run_in_executor(None, now_julian_day)
    transits = await asyncio.get_event_loop().run_in_executor(None, calculate_current_transits, jd_now)
    transit_aspects = await asyncio.get_event_loop().run_in_executor(
        None, calculate_transit_aspects_to_natal, transits, natal_planets
    )

    scores = score_categories(transit_aspects)
    moon_phase = get_moon_phase(transits)
    transit_tags = build_transit_tags(transit_aspects, transits)

    texts = await generate_all_advice(
        name=profile.name,
        gender=profile.gender,
        language=language,
        mode=mode,
        natal_chart=natal_chart,
        transit_aspects=transit_aspects,
        moon_phase=moon_phase,
    )

    advice = DailyAdvice(
        user_id=user_id,
        date=target_date,
        mode=mode,
        language=language,
        theme=texts["theme"],
        moon_phase=moon_phase,
        transit_tags=transit_tags,
        love_score=scores["love"],
        love_text=texts["love_text"],
        work_score=scores["work"],
        work_text=texts["work_text"],
        energy_score=scores["energy"],
        energy_text=texts["energy_text"],
        communication_score=scores["communication"],
        communication_text=texts["communication_text"],
        mood_score=scores["mood"],
        mood_text=texts["mood_text"],
        risk_text=texts["risk_text"],
    )
    return await create_advice(db, advice)


@router.get("/today", response_model=DailyAdviceResponse)
async def get_today_advice(
    client_date: Optional[date] = Query(
        None,
        description="The client's local calendar date (YYYY-MM-DD). "
                    "When provided this is used as 'today'; otherwise the server "
                    "derives it from the user's stored device_timezone.",
    ),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    # Extract plain Python values immediately — db.commit() inside create_advice
    # expires all ORM objects in the session, making later attribute access fail
    # with MissingGreenlet in an async context.
    user_id = current_user.id
    lang = current_user.language or "en"

    profile = await get_profile_by_user_id(db, user_id)
    if not profile:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Profile not found. Complete onboarding first.")

    # Determine "today" using (in priority order):
    # 1. client_date — device knows its own date with certainty
    # 2. profile.device_timezone — server-side conversion (slightly stale if user travelled)
    # 3. UTC date — safe fallback
    today = client_date or _user_local_date(profile.device_timezone)

    mode = profile.interpretation_mode

    # 1. Check Redis cache (keyed by language so EN and RU are stored separately)
    cached = await get_cached_advice(str(user_id), today.isoformat(), mode, language=lang)
    if cached and "advice" in cached:
        return DailyAdviceResponse(**cached["advice"])

    # 2. Check database — filter by language so stale translations are never served
    existing = await get_advice(db, user_id, today, mode, language=lang)
    if existing:
        response = _to_response(existing)
        await cache_advice(str(user_id), today.isoformat(), mode, {"advice": response.model_dump(mode="json")}, language=lang)
        return response

    # 3. Generate fresh in the user's current language
    advice = await _generate_and_store(profile, user_id, lang, today, db)
    response = _to_response(advice)
    await cache_advice(str(user_id), today.isoformat(), mode, {"advice": response.model_dump(mode="json")}, language=lang)
    return response


@router.get("/date", response_model=DailyAdviceResponse)
async def get_advice_for_date(
    target_date: date = Query(..., alias="date"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    user_id = current_user.id
    lang = current_user.language or "en"

    profile = await get_profile_by_user_id(db, user_id)
    if not profile:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Profile not found.")

    existing = await get_advice(db, user_id, target_date, profile.interpretation_mode, language=lang)
    if existing:
        return _to_response(existing)

    today = datetime.now(timezone.utc).date()
    if target_date > today:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot generate advice for future dates.")

    # Past date — generate on demand
    advice = await _generate_and_store(profile, user_id, lang, target_date, db)
    return _to_response(advice)


class TransitExplanationRequest(BaseModel):
    transit_tag: str


@router.post("/transit-explanation")
async def get_transit_explanation(
    body: TransitExplanationRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Generate a short personalized explanation for a transit tag (cached 24h)."""
    user_id = current_user.id
    lang = current_user.language or "en"
    tag = body.transit_tag.strip()

    cache_key = f"transit_exp:{user_id}:{tag}:{lang}"
    cached = await redis_get(cache_key)
    if cached:
        return {"explanation": cached}

    profile = await get_profile_by_user_id(db, user_id)
    if not profile:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Profile not found.")

    planets = profile.natal_chart_json.get("planets", {})
    sun_sign = planets.get("Sun", {}).get("sign", "unknown")
    moon_sign = planets.get("Moon", {}).get("sign", "unknown")

    explanation = await generate_transit_explanation(
        transit_tag=tag,
        name=profile.name,
        sun_sign=sun_sign,
        moon_sign=moon_sign,
        language=lang,
    )

    await redis_setex(cache_key, 86400, explanation)
    return {"explanation": explanation}
