from __future__ import annotations
import asyncio
import json
import logging
from datetime import date, datetime, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import swisseph as swe
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.advice_generator import generate_all_advice, generate_transit_explanation, generate_weekly_text
from app.core.ephemeris import (
    calculate_current_transits,
    calculate_transit_aspects_to_natal,
    get_moon_phase,
    get_moon_phase_for_date,
    julian_day_for_local_noon,
)
from app.core.scoring import build_transit_tags, score_categories
from app.db.models import DailyAdvice, User
from app.db.repositories.advice_repository import create_advice, get_advice, get_advice_range, get_recent_advice
from app.db.repositories.profile_repository import get_profile_by_user_id
from app.dependencies import get_current_user, get_db
from app.schemas.advice import CategoryCard, DailyAdviceResponse
from app.services.redis_service import cache_advice, get_cached_advice, redis_get, redis_setex

logger = logging.getLogger(__name__)

router = APIRouter()


# Warm, on-brand fallback copy shown only when live generation is temporarily
# unavailable (e.g. an upstream AI outage) AND the user has no recent reading
# to fall back to. Scores/moon/tags stay REAL (computed locally) — only the
# words are these calm placeholders. Kept short and human, not error-y.
_PLACEHOLDER_TEXT: dict[str, dict[str, str]] = {
    "en": {
        "theme": "The sky is turning quietly today. Your full reading is on its way back — take this as a gentle pause.",
        "love": "Let warmth lead, without forcing anything into words just yet.",
        "work": "Steady, unhurried effort carries you further than a sprint today.",
        "energy": "Move at your own pace — there's nothing to prove right now.",
        "communication": "Say a little less, listen a little more; the right words will find their moment.",
        "mood": "Give yourself a soft, ordinary kind of day.",
        "watch_for": "Your reading is refreshing behind the scenes — check back shortly for today's full detail.",
    },
    "ru": {
        "theme": "Небо сегодня разворачивается неспешно. Полное чтение уже возвращается — примите это как тихую паузу.",
        "love": "Пусть ведёт тепло — не спешите облекать всё в слова.",
        "work": "Спокойные, размеренные усилия сегодня надёжнее рывка.",
        "energy": "Двигайтесь в своём темпе — сейчас никому ничего не нужно доказывать.",
        "communication": "Говорите чуть меньше, слушайте чуть больше — нужные слова найдут свой момент.",
        "mood": "Позвольте себе обычный, спокойный день.",
        "watch_for": "Чтение обновляется — загляните чуть позже за полными деталями дня.",
    },
    "pt": {
        "theme": "O céu se move devagar hoje. Sua leitura completa já está a caminho — receba isto como uma pausa tranquila.",
        "love": "Deixe o carinho conduzir, sem forçar nada em palavras ainda.",
        "work": "Um esforço calmo e constante leva você mais longe que a pressa hoje.",
        "energy": "Vá no seu ritmo — não é preciso provar nada agora.",
        "communication": "Fale um pouco menos, escute um pouco mais; as palavras certas acharão o momento.",
        "mood": "Permita-se um dia comum e suave.",
        "watch_for": "Sua leitura está sendo atualizada — volte em breve para os detalhes completos do dia.",
    },
}


def _placeholder_response(profile, today: date, mode: str, lang: str) -> DailyAdviceResponse:
    """A calm 200 response for when generation is down and the user has no
    recent reading. Scores, moon phase and transit tags are REAL (no AI needed);
    only the text is a gentle placeholder. Never cached, so the next request
    retries real generation once the upstream recovers."""
    natal_planets = (profile.natal_chart_json or {}).get("planets", {})
    jd = julian_day_for_local_noon(today, profile.device_timezone)
    transits = calculate_current_transits(jd)
    aspects = calculate_transit_aspects_to_natal(transits, natal_planets)
    scores = score_categories(aspects)
    t = _PLACEHOLDER_TEXT.get(lang, _PLACEHOLDER_TEXT["en"])
    return DailyAdviceResponse(
        date=today,
        generated_at=datetime.now(timezone.utc),
        mode=mode,
        theme=t["theme"],
        moon_phase=get_moon_phase(transits),
        transit_tags=build_transit_tags(aspects, transits),
        love=CategoryCard(score=scores["love"], text=t["love"]),
        work=CategoryCard(score=scores["work"], text=t["work"]),
        energy=CategoryCard(score=scores["energy"], text=t["energy"]),
        communication=CategoryCard(score=scores["communication"], text=t["communication"]),
        mood=CategoryCard(score=scores["mood"], text=t["mood"]),
        watch_for=t["watch_for"],
    )


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

    # Anchor to the user's LOCAL noon of the target date so scores depend only
    # on the date (not the minute of generation — otherwise the same day yields
    # different scores per language) and sit in the middle of the user's day.
    jd_anchor = await asyncio.get_event_loop().run_in_executor(
        None, julian_day_for_local_noon, target_date, profile.device_timezone
    )
    transits = await asyncio.get_event_loop().run_in_executor(None, calculate_current_transits, jd_anchor)
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

    # 3. Generate fresh in the user's current language.
    #    If generation is temporarily unavailable (e.g. an upstream AI outage),
    #    degrade gracefully instead of returning a 500 red-error screen:
    #      a) serve the user's most recent real reading (nearly invisible for
    #         active users — they read daily, so yesterday's exists), or
    #      b) a calm placeholder with REAL scores if they have no history.
    #    Neither fallback is cached, so the next request retries real generation
    #    once the upstream recovers.
    try:
        advice = await _generate_and_store(profile, user_id, lang, today, db)
        response = _to_response(advice)
        await cache_advice(str(user_id), today.isoformat(), mode, {"advice": response.model_dump(mode="json")}, language=lang)
        return response
    except HTTPException:
        raise
    except Exception as e:
        logger.warning(f"Advice generation failed for user {user_id} — serving graceful fallback ({type(e).__name__}: {e})")
        try:
            recent = await get_recent_advice(db, user_id, mode, limit=7)
            fallback = next((a for a in recent if a.language == lang), None) or (recent[0] if recent else None)
        except Exception:
            fallback = None  # session may be poisoned — fall through to placeholder (no DB)
        if fallback is not None:
            return _to_response(fallback)
        return _placeholder_response(profile, today, mode, lang)


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


class WeeklyForecastResponse(BaseModel):
    week_start: str            # Monday, "YYYY-MM-DD"
    week_end: str              # Sunday
    text: str                  # AI-written forecast, 5-6 sentences
    best_day: str              # "YYYY-MM-DD" — highest avg score
    challenging_day: str       # "YYYY-MM-DD" — lowest avg score
    day_scores: list[dict]     # [{date, avg_score}] for all 7 days


@router.get("/weekly", response_model=WeeklyForecastResponse)
async def get_weekly_forecast(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Weekly forecast — Pro only. One GPT call per user per ISO week (Redis-cached)."""
    if current_user.subscription_status not in ("pro", "active"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Lumina Plus required.")

    user_id = current_user.id
    lang = current_user.language or "en"

    profile = await get_profile_by_user_id(db, user_id)
    if not profile:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Profile not found.")

    local_today = _user_local_date(profile.device_timezone)
    week_start = local_today - timedelta(days=local_today.weekday())  # Monday
    week_end = week_start + timedelta(days=6)

    cache_key = f"weekly:{user_id}:{week_start.isoformat()}:{profile.interpretation_mode}:{lang}"
    cached = await redis_get(cache_key)
    if cached:
        return WeeklyForecastResponse(**json.loads(cached))

    natal_planets = (profile.natal_chart_json or {}).get("planets", {})
    houses = (profile.natal_chart_json or {}).get("houses", {})

    def compute_week() -> tuple[list[dict], list[dict]]:
        """Per-day avg scores + strongest unique aspects of the week (sync, thread pool)."""
        day_rows: list[dict] = []
        best_aspects: dict[str, dict] = {}
        for i in range(7):
            d = week_start + timedelta(days=i)
            # Local noon of each day — same anchor as the daily card, so a day's
            # weekly bar matches its daily score.
            jd = julian_day_for_local_noon(d, profile.device_timezone)
            transits = calculate_current_transits(jd)
            aspects = calculate_transit_aspects_to_natal(transits, natal_planets)
            scores = score_categories(aspects)
            avg = round(
                (scores["love"] + scores["work"] + scores["energy"]
                 + scores["communication"] + scores["mood"]) / 5
            )
            day_rows.append({"date": d.isoformat(), "avg_score": max(1, min(10, avg))})
            for a in aspects:
                key = f"{a['transiting_planet']} {a['aspect']} {a['natal_planet']}"
                if key not in best_aspects or a["orb"] < best_aspects[key]["orb"]:
                    best_aspects[key] = a
        top = sorted(best_aspects.values(), key=lambda a: a["orb"])[:5]
        return day_rows, top

    loop = asyncio.get_event_loop()
    day_rows, top_aspects = await loop.run_in_executor(None, compute_week)

    best_day = max(day_rows, key=lambda r: r["avg_score"])["date"]
    challenging_day = min(day_rows, key=lambda r: r["avg_score"])["date"]

    weekday_names = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    day_scores_line = ", ".join(
        f"{weekday_names[i]} {r['date'][5:]}: {r['avg_score']}" for i, r in enumerate(day_rows)
    )
    aspect_list = ", ".join(
        f"{a['transiting_planet']} {a['aspect']} natal {a['natal_planet']} (orb {a['orb']:.1f}°)"
        for a in top_aspects
    ) or "no major exact transits this week"

    planets = natal_planets
    text = await generate_weekly_text(
        name=profile.name,
        language=lang,
        mode=profile.interpretation_mode,
        sun_sign=planets.get("Sun", {}).get("sign", "unknown"),
        moon_sign=planets.get("Moon", {}).get("sign", "unknown"),
        rising=houses.get("asc_sign", "unknown"),
        week_range=f"{week_start.isoformat()} to {week_end.isoformat()}",
        day_scores_line=day_scores_line,
        aspect_list=aspect_list,
    )

    result = WeeklyForecastResponse(
        week_start=week_start.isoformat(),
        week_end=week_end.isoformat(),
        text=text,
        best_day=best_day,
        challenging_day=challenging_day,
        day_scores=day_rows,
    )
    await redis_setex(cache_key, 8 * 86400, json.dumps(result.model_dump()))
    return result


class DayScoreEntry(BaseModel):
    date: str        # "YYYY-MM-DD"
    avg_score: int   # 1-10 average across the 5 scored categories


@router.get("/scores", response_model=list[DayScoreEntry])
async def get_scores_range(
    start: date = Query(...),
    end: date = Query(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Average day scores for all STORED advice in [start, end] — one call for
    a whole calendar month. Read-only: never generates advice (unlike /date),
    so it is safe to call for arbitrary ranges."""
    if end < start:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="end must be >= start")
    if (end - start).days > 100:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Range too large (max 100 days).")

    rows = await get_advice_range(db, current_user.id, start, end)
    seen: dict[str, int] = {}
    for a in rows:
        # If advice exists in several modes/languages for the same date, first wins
        key = a.date.isoformat()
        if key not in seen:
            avg = round(
                (a.love_score + a.work_score + a.energy_score
                 + a.communication_score + a.mood_score) / 5
            )
            seen[key] = max(1, min(10, avg))
    return [DayScoreEntry(date=d, avg_score=s) for d, s in sorted(seen.items())]


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


# ---------------------------------------------------------------------------
# Public moon-phases endpoint — no auth, cached globally, same for all users
# ---------------------------------------------------------------------------

class MoonPhaseEntry(BaseModel):
    date: str    # "YYYY-MM-DD"
    phase: str   # e.g. "Full Moon"


@router.get("/moon-phases", response_model=list[MoonPhaseEntry])
async def get_moon_phases(
    start: date = Query(..., description="Start date (YYYY-MM-DD)"),
    end:   date = Query(..., description="End date (YYYY-MM-DD), inclusive"),
) -> list[MoonPhaseEntry]:
    """
    Return the moon phase for every day in [start, end].
    Pure astronomy — no user data, no AI. Cached in Redis for 24 hours.
    Capped at 200 days to prevent abuse.
    """
    from datetime import timedelta

    delta = (end - start).days
    if delta < 0 or delta > 200:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Date range must be between 1 and 200 days.",
        )

    cache_key = f"moon_phases:{start.isoformat()}:{end.isoformat()}"
    cached = await redis_get(cache_key)
    if cached:
        import json
        return [MoonPhaseEntry(**e) for e in json.loads(cached)]

    # Calculate in a thread pool — swisseph is CPU-bound
    def _compute() -> list[dict]:
        result = []
        current = start
        while current <= end:
            phase = get_moon_phase_for_date(current.year, current.month, current.day)
            result.append({"date": current.isoformat(), "phase": phase})
            current += timedelta(days=1)
        return result

    entries = await asyncio.get_event_loop().run_in_executor(None, _compute)

    import json
    await redis_setex(cache_key, 86400, json.dumps(entries))   # cache 24 h

    return [MoonPhaseEntry(**e) for e in entries]
