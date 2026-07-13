from __future__ import annotations
"""
Advice generation job — runs every hour.
Checks each user's LOCAL date (using device_timezone) and generates advice
for that date if it doesn't exist yet. This ensures users in any timezone
always have fresh advice ready when their local day starts.

Notification job — runs every hour.
Compares the user's current LOCAL hour against their preferred notification hour.
Sends a push only when they match, using the advice keyed to their local date.
"""
import asyncio
import logging
from datetime import date, datetime, time as time_type, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.advice_generator import generate_all_advice
from app.core.ephemeris import (
    calculate_current_transits,
    calculate_transit_aspects_to_natal,
    get_moon_phase,
    now_julian_day,
)
from app.core.scoring import build_transit_tags, score_categories
from app.db.models import DailyAdvice
from app.db.repositories.advice_repository import create_advice, get_advice
from app.db.repositories.profile_repository import get_profile_by_user_id
from app.db.repositories.user_repository import get_all_active_users
from app.db.session import AsyncSessionLocal
from app.services.apns_service import send_daily_notification
from app.services.redis_service import cache_advice, get_cached_advice, redis_setnx

logger = logging.getLogger(__name__)

_DEFAULT_LOCAL_HOUR = 8  # 08:00 in the user's own timezone


# ---------------------------------------------------------------------------
# Timezone helpers
# ---------------------------------------------------------------------------

def _user_local_date(device_timezone: str | None) -> date:
    """Return the current calendar date in the user's local timezone.
    Falls back to UTC if the timezone is unknown or invalid."""
    if not device_timezone:
        return datetime.now(timezone.utc).date()
    try:
        tz = ZoneInfo(device_timezone)
        return datetime.now(tz).date()
    except (ZoneInfoNotFoundError, Exception):
        return datetime.now(timezone.utc).date()


def _user_local_hour(device_timezone: str | None) -> int:
    """Return the current hour (0–23) in the user's local timezone."""
    if not device_timezone:
        return datetime.now(timezone.utc).hour
    try:
        tz = ZoneInfo(device_timezone)
        return datetime.now(tz).hour
    except (ZoneInfoNotFoundError, Exception):
        return datetime.now(timezone.utc).hour


# ---------------------------------------------------------------------------
# Per-user advice generation
# ---------------------------------------------------------------------------

async def _process_user(
    profile,
    user_id,
    language: str,
    transits: dict,
    target_date: date,
    db: AsyncSession,
) -> None:
    """Generate advice for a user for target_date (their local today).
    No-ops if advice already exists in cache or DB."""
    mode = profile.interpretation_mode

    # Redis cache check (cheap)
    cached = await get_cached_advice(str(user_id), target_date.isoformat(), mode, language=language)
    if cached:
        return

    # DB check
    existing = await get_advice(db, user_id, target_date, mode, language=language)
    if existing:
        await cache_advice(str(user_id), target_date.isoformat(), mode, {"cached": True}, language=language)
        return

    natal_chart = profile.natal_chart_json
    natal_planets = natal_chart.get("planets", {})

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

    await create_advice(db, advice)
    await cache_advice(str(user_id), target_date.isoformat(), mode, {"cached": True}, language=language)
    logger.info(f"Generated advice for user {user_id} — local date {target_date} ({profile.device_timezone or 'UTC'})")


# ---------------------------------------------------------------------------
# Hourly advice generation job
# ---------------------------------------------------------------------------

async def run_advice_job() -> None:
    """
    Runs every hour. For each user, determines their current local date
    and generates today's advice if it doesn't exist yet.
    Processes users in batches of 5 to respect OpenAI rate limits.
    """
    logger.info("Advice job started")

    # Compute shared planetary positions once (good enough for hourly precision)
    jd_now = await asyncio.get_event_loop().run_in_executor(None, now_julian_day)
    transits = await asyncio.get_event_loop().run_in_executor(None, calculate_current_transits, jd_now)

    async with AsyncSessionLocal() as db:
        users = await get_all_active_users(db)
        logger.info(f"Advice job: {len(users)} users to check")

        batch_size = 5
        for i in range(0, len(users), batch_size):
            batch = users[i:i + batch_size]
            tasks = []
            for u in batch:
                profile = await get_profile_by_user_id(db, u.id)
                if not profile:
                    continue
                user_today = _user_local_date(profile.device_timezone)
                tasks.append(
                    _process_user(profile, u.id, u.language or "en", transits, user_today, db)
                )

            if not tasks:
                continue

            results = await asyncio.gather(*tasks, return_exceptions=True)
            for j, result in enumerate(results):
                if isinstance(result, Exception):
                    logger.error(f"Advice job error for user {batch[j].id}: {result}")

    logger.info("Advice job completed")


# ---------------------------------------------------------------------------
# Hourly notification job
# ---------------------------------------------------------------------------

async def run_notification_job() -> None:
    """
    Runs every hour.
    Sends a push notification to each user whose current LOCAL hour matches
    their chosen notification hour (default 08:00 local).
    Uses advice keyed to the user's LOCAL date so users in any timezone
    always receive the correct day's content.

    Duplicate-send protection: before sending, we atomically claim a Redis key
    `notif_sent:{user_id}:{local_date}:{desired_hour}` (TTL 2 h).  If two
    Railway instances fire at the same second during a deploy, only the one that
    wins the SET NX will actually send — the other sees the key already exists
    and skips.  This guarantees exactly-once delivery per user per day.
    """
    logger.info("Notification job started")

    async with AsyncSessionLocal() as db:
        users = await get_all_active_users(db)
        sent = 0

        for user in users:
            profile = await get_profile_by_user_id(db, user.id)
            if not profile or not profile.fcm_token:
                continue

            tz_id = profile.device_timezone

            # User's current local hour
            current_local_hour = _user_local_hour(tz_id)

            # notification_time stores the user's DESIRED LOCAL hour (e.g. 8 for 8 am).
            # Compare directly with current local hour — no UTC conversion needed.
            desired_hour = (
                profile.notification_time.hour
                if profile.notification_time
                else _DEFAULT_LOCAL_HOUR
            )

            # Catch-up window: fire if the local hour is at or past the desired
            # hour, up to CATCHUP_HOURS later. If a deploy/cold-start makes the
            # server miss the exact :00 run, the next hourly run still delivers —
            # instead of the user silently losing the day's notification.
            # Capped so a long outage never triggers a notification late at night.
            _CATCHUP_HOURS = 6
            if not (desired_hour <= current_local_hour <= desired_hour + _CATCHUP_HOURS):
                continue

            # --- Duplicate-send guard (atomic Redis lock) ---
            # Key is per-DAY (not per-hour) so catch-up runs can't double-send:
            # once today's push goes out, every later run this day sees the lock.
            user_today = _user_local_date(tz_id)
            lock_key = f"notif_sent:{user.id}:{user_today.isoformat()}"
            claimed = await redis_setnx(lock_key, ttl=72000, value="1")  # 20-hour TTL
            if not claimed:
                # Already sent today (or another instance is sending) — skip.
                logger.info(f"Skipping duplicate push for user {user.id} (already sent today)")
                continue

            # Look up advice for the user's LOCAL today
            language = user.language or "en"
            existing = await get_advice(db, user.id, user_today, profile.interpretation_mode, language=language)
            if not existing:
                logger.info(
                    f"No advice for user {user.id} on local date {user_today} — skipping push"
                )
                continue
            success = await send_daily_notification(
                profile.fcm_token,
                language,
                theme=existing.theme,
                scores={
                    "love":          existing.love_score,
                    "work":          existing.work_score,
                    "energy":        existing.energy_score,
                    "communication": existing.communication_score,
                    "mood":          existing.mood_score,
                },
            )
            if success:
                sent += 1
                logger.info(
                    f"Push sent → user {user.id} | local {desired_hour:02d}:00 "
                    f"({tz_id or 'UTC'}) | date {user_today}"
                )

    logger.info(f"Notification job done — {sent} notifications sent")
