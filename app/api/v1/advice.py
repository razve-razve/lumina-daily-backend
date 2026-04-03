from __future__ import annotations
import asyncio
from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.advice_generator import generate_all_advice
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
from app.services.redis_service import cache_advice, get_cached_advice

router = APIRouter()


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
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    import traceback as _tb
    try:
        return await _get_today_advice_inner(current_user, db)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"{type(exc).__name__}: {exc}\n{_tb.format_exc()}")


async def _get_today_advice_inner(current_user, db):
    today = datetime.now(timezone.utc).date()

    profile = await get_profile_by_user_id(db, current_user.id)
    if not profile:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Profile not found. Complete onboarding first.")

    mode = profile.interpretation_mode

    # 1. Check Redis cache
    cached = await get_cached_advice(str(current_user.id), today.isoformat(), mode)
    if cached and "advice" in cached:
        return DailyAdviceResponse(**cached["advice"])

    # 2. Check database
    existing = await get_advice(db, current_user.id, today, mode)
    if existing:
        response = _to_response(existing)
        await cache_advice(str(current_user.id), today.isoformat(), mode, {"advice": response.model_dump(mode="json")})
        return response

    # 3. Generate fresh
    advice = await _generate_and_store(profile, current_user.id, current_user.language, today, db)
    response = _to_response(advice)
    await cache_advice(str(current_user.id), today.isoformat(), mode, {"advice": response.model_dump(mode="json")})
    return response


@router.get("/date", response_model=DailyAdviceResponse)
async def get_advice_for_date(
    target_date: date = Query(..., alias="date"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    profile = await get_profile_by_user_id(db, current_user.id)
    if not profile:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Profile not found.")

    existing = await get_advice(db, current_user.id, target_date, profile.interpretation_mode)
    if existing:
        return _to_response(existing)

    today = datetime.now(timezone.utc).date()
    if target_date > today:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot generate advice for future dates.")

    # Past date — generate on demand
    advice = await _generate_and_store(profile, current_user.id, current_user.language, target_date, db)
    return _to_response(advice)
