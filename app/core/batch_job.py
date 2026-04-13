"""
Daily batch job — runs at 02:00 UTC via APScheduler.
Generates advice for all active users.

Hourly notification job — runs at :00 every hour.
Sends push notifications to users whose notification_time (stored in UTC) matches
the current UTC hour. Default time: 08:00 UTC for users with no preference set.
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
from app.services.redis_service import cache_advice, get_cached_advice

logger = logging.getLogger(__name__)

_DEFAULT_LOCAL_HOUR = 8  # 08:00 in the user's own timezone


def _local_hour_to_utc_hour(local_hour: int, tz_id: str | None, today: date) -> int:
    """Convert a local notification hour to UTC hour for the given date.
    Falls back to treating the hour as UTC if timezone is unknown."""
    if not tz_id:
        return local_hour
    try:
        tz = ZoneInfo(tz_id)
        local_dt = datetime(today.year, today.month, today.day, local_hour, 0, tzinfo=tz)
        return local_dt.astimezone(timezone.utc).hour
    except (ZoneInfoNotFoundError, Exception):
        return local_hour


async def _process_user(
    user_id,
    language: str,
    transits: dict,
    transit_aspects_cache: dict,  # keyed by natal planet combo — not used, computed per user
    today: date,
    db: AsyncSession,
) -> None:
    """Generate (but do not push) advice for a user. Push is handled by run_notification_job."""
    profile = await get_profile_by_user_id(db, user_id)
    if not profile:
        return

    mode = profile.interpretation_mode

    # Check Redis cache first
    cached = await get_cached_advice(str(user_id), today.isoformat(), mode)
    if cached:
        logger.info(f"Cache hit for user {user_id} — skipping generation")
        return

    # Check DB cache
    existing = await get_advice(db, user_id, today, mode)
    if existing:
        await cache_advice(str(user_id), today.isoformat(), mode, {"cached": True})
        return

    natal_chart = profile.natal_chart_json
    natal_planets = natal_chart.get("planets", {})

    # Compute this user's transit aspects (personal — depends on natal chart)
    transit_aspects = await asyncio.get_event_loop().run_in_executor(
        None, calculate_transit_aspects_to_natal, transits, natal_planets
    )

    scores = score_categories(transit_aspects)
    moon_phase = get_moon_phase(transits)
    transit_tags = build_transit_tags(transit_aspects, transits)

    # Generate AI text
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
        date=today,
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
    await cache_advice(str(user_id), today.isoformat(), mode, {"cached": True})
    logger.info(f"Generated advice for user {user_id}")


async def run_daily_batch() -> None:
    """Entry point called by APScheduler at 02:00 UTC."""
    today = datetime.now(timezone.utc).date()
    logger.info(f"Daily batch job started for {today}")

    # Calculate today's planetary positions once — shared across all users
    jd_now = await asyncio.get_event_loop().run_in_executor(None, now_julian_day)
    transits = await asyncio.get_event_loop().run_in_executor(None, calculate_current_transits, jd_now)

    async with AsyncSessionLocal() as db:
        users = await get_all_active_users(db)
        logger.info(f"Processing {len(users)} users")

        # Process in batches of 10 to avoid overwhelming OpenAI rate limits
        batch_size = 10
        for i in range(0, len(users), batch_size):
            batch = users[i:i + batch_size]
            tasks = [
                _process_user(u.id, u.language or "en", transits, {}, today, db)
                for u in batch
            ]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            for j, result in enumerate(results):
                if isinstance(result, Exception):
                    logger.error(f"Error processing user {batch[j].id}: {result}")

    logger.info("Daily batch job completed")


async def run_notification_job() -> None:
    """
    Runs at the top of every hour (UTC).
    Sends push notifications to users whose preferred local notification hour
    corresponds to the current UTC hour.
    - Users with explicit notification_time: use that local hour
    - Users with no preference: default to 08:00 in their device timezone
    """
    now_utc = datetime.now(timezone.utc)
    current_hour = now_utc.hour
    today = now_utc.date()
    logger.info(f"Notification job started for hour {current_hour:02d}:00 UTC")

    async with AsyncSessionLocal() as db:
        users = await get_all_active_users(db)
        sent = 0
        for user in users:
            profile = await get_profile_by_user_id(db, user.id)
            if not profile or not profile.fcm_token:
                continue

            # Determine desired local hour (explicit preference or default 08:00)
            local_hour = profile.notification_time.hour if profile.notification_time else _DEFAULT_LOCAL_HOUR
            tz_id = profile.device_timezone  # may be None for old users

            # Convert local hour → UTC hour using device timezone
            target_utc_hour = _local_hour_to_utc_hour(local_hour, tz_id, today)

            if target_utc_hour != current_hour:
                continue

            # Find today's advice for this user
            existing = await get_advice(db, user.id, today, profile.interpretation_mode)
            if not existing:
                logger.info(f"No advice for user {user.id} — skipping push")
                continue

            language = user.language or "en"
            await send_daily_notification(profile.fcm_token, language, theme=existing.theme)
            sent += 1
            logger.info(f"Sent push to user {user.id} (local {local_hour:02d}:00 → UTC {target_utc_hour:02d}:00)")

    logger.info(f"Notification job completed — sent {sent} push notifications")
